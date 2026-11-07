"""Turnos y caja por la sesión POS: apertura única, movimientos, conteo ciego, arqueo, cierre forzado, inmutabilidad."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from tests import factories as f
from tests.api_helpers import bearer, token_de
from tests.pos_helpers import Cliente, construir_pos, efectivo, linea, producto

D = Decimal


@pytest.fixture
def pos(conn, db, client):
    pm = construir_pos(conn, db)
    pid = producto(conn, db, pm, "Filtro de aceite", "10000")
    return pm, pid, Cliente(client, pm, "111111")


def _tarjeta(valor):
    return {"medio_pago_codigo": "48", "valor": str(valor), "referencia": "AP-1234", "canal_pago": "datafono"}


def test_un_solo_turno_abierto_por_caja_y_por_empleado(pos, client):
    pm, _, cajero = pos
    cajero.abrir_turno()
    r = cajero.post("/pos/turnos", json={"base_efectivo": "1000"})
    assert r.status_code == 409 and r.json()["code"] == "turno_abierto_en_caja"
    otro = Cliente(client, pm, "222222")
    r = otro.post("/pos/turnos", json={"base_efectivo": "1000"})
    assert r.status_code == 409 and r.json()["code"] == "turno_abierto_en_caja"
    # el otro cajero puede ver el turno pero NO cerrarlo (solo el dueño o un cierre forzado)
    assert (
        otro.post(
            "/pos/turnos/actual/cierre", json={"conteo": [{"medio_pago_codigo": "10", "valor_contado": "0"}]}
        ).status_code
        == 403
    )


def test_empleado_no_puede_tener_dos_turnos(conn, db, client):
    pm = construir_pos(conn, db)
    cajero = Cliente(client, pm, "111111")
    cajero.abrir_turno()
    # segunda caja de la misma sede con su propio dispositivo
    import uuid

    from app.modules.cajas import servicios as svc_cajas

    c2 = f.caja(conn, pm.sede, pm.bodega)
    disp, token = svc_cajas.crear_dispositivo(db, uuid.UUID(c2), "POS 2", pm.mundo.admin.id)
    db.commit()
    r = client.post("/api/v1/pos/auth/pin", json={"pin": "111111"}, headers={"X-Dispositivo-Token": token})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/pos/turnos", json={"base_efectivo": "0"}, headers=bearer(r.json()["token"]))
    assert r.status_code == 409 and r.json()["code"] == "turno_abierto_empleado"


def test_conteo_ciego_no_expone_esperados_con_turno_abierto(pos):
    _, pid, cajero = pos
    cajero.abrir_turno()
    assert cajero.vender([linea(pid)], [efectivo(10000)]).status_code == 201
    actual = cajero.get("/pos/turnos/actual")
    assert actual.status_code == 200
    assert not ({"efectivo_esperado", "esperado", "arqueos", "resumen"} & set(actual.json()))
    t = actual.json()["id"]
    r = cajero.get(f"/pos/turnos/{t}/informe-cierre")
    assert r.status_code == 409 and r.json()["code"] == "turno_abierto"


def test_arqueo_cuadra_con_efectivo_tarjeta_y_retiros(pos):
    pm, pid, cajero = pos
    t = cajero.abrir_turno("50000")["id"]
    assert cajero.vender([linea(pid)], [efectivo(10000)]).status_code == 201
    assert cajero.vender([linea(pid, "2")], [_tarjeta(20000)]).status_code == 201
    r = cajero.post(
        "/pos/turnos/actual/movimientos", json={"tipo": "retiro", "valor": "8000", "motivo_codigo": "retiro_seguridad"}
    )
    assert r.status_code == 201, r.text
    r = cajero.post(
        "/pos/turnos/actual/movimientos",
        json={"tipo": "ingreso", "valor": "3000", "motivo_codigo": "reposicion_cambio"},
    )
    assert r.status_code == 201, r.text
    assert len(cajero.get("/pos/turnos/actual/movimientos").json()) == 2

    conteo = [
        {"medio_pago_codigo": "10", "valor_contado": "55000"},
        {"medio_pago_codigo": "48", "valor_contado": "20000"},
    ]
    r = cajero.post("/pos/turnos/actual/cierre", json={"conteo": conteo})
    assert r.status_code == 200, r.text
    inf = r.json()
    arq = {a["medio_pago_codigo"]: a for a in inf["arqueos"]}
    assert D(arq["10"]["esperado"]) == D("55000") and D(arq["10"]["diferencia"]) == 0
    assert D(arq["48"]["esperado"]) == D("20000") and D(arq["48"]["diferencia"]) == 0
    assert D(inf["efectivo"]["base_efectivo"]) == 50000 and D(inf["efectivo"]["retiros"]) == 8000
    assert D(inf["efectivo"]["ingresos"]) == 3000 and D(inf["efectivo"]["ventas_efectivo"]) == 10000
    assert inf["resumen"]["num_ventas"] == 2 and D(inf["resumen"]["total_ventas"]) == 30000
    # el informe se puede volver a pedir (turno cerrado)
    assert cajero.get(f"/pos/turnos/{t}/informe-cierre").json()["turno"]["id"] == t


def test_la_diferencia_de_arqueo_nunca_bloquea_el_cierre_y_queda_en_revision(pos, conn):
    pm, pid, cajero = pos
    cajero.abrir_turno("50000")
    assert cajero.vender([linea(pid)], [efectivo(10000)]).status_code == 201
    faltante = [{"medio_pago_codigo": "10", "valor_contado": "50000"}]  # esperado 60000 -> -10000
    r = cajero.post("/pos/turnos/actual/cierre", json={"conteo": faltante})
    assert r.status_code == 200, r.text  # política por defecto: revision_posterior (jamás bloquea)
    assert D(r.json()["diferencia_total"]) == D("-10000")
    fila = conn.execute(
        text("SELECT accion, estado, monto FROM auditoria.revisiones WHERE accion = 'diferencia_arqueo'")
    ).one()
    assert fila.estado == "pendiente" and abs(D(fila.monto)) == D("10000")


def test_diferencia_dentro_de_la_tolerancia_cierra_sin_autorizacion(pos):
    _, pid, cajero = pos
    cajero.abrir_turno("50000")
    r = cajero.post(
        "/pos/turnos/actual/cierre", json={"conteo": [{"medio_pago_codigo": "10", "valor_contado": "46000"}]}
    )
    assert r.status_code == 200, r.text
    assert D(r.json()["diferencia_total"]) == D("-4000")


def test_el_conteo_exige_efectivo(pos):
    _, _, cajero = pos
    cajero.abrir_turno()
    r = cajero.post("/pos/turnos/actual/cierre", json={"conteo": [{"medio_pago_codigo": "48", "valor_contado": "0"}]})
    assert r.status_code == 422 and r.json()["code"] == "falta_efectivo"


def test_retiro_libre_hasta_el_umbral_y_con_autorizacion_por_encima(pos):
    _, _, cajero = pos
    cajero.abrir_turno("900000")
    # política por defecto: libre hasta 300 000 COP
    libre = {"tipo": "retiro", "valor": "300000", "motivo_codigo": "retiro_seguridad"}
    assert cajero.post("/pos/turnos/actual/movimientos", json=libre).status_code == 201
    cuerpo = {"tipo": "retiro", "valor": "300001", "motivo_codigo": "retiro_seguridad"}
    r = cajero.post("/pos/turnos/actual/movimientos", json=cuerpo)
    assert r.status_code == 403 and r.json()["code"] == "autorizacion_requerida"
    auth = cajero.autorizar("999999", "pos.retirar_efectivo")
    r = cajero.post("/pos/turnos/actual/movimientos", json={**cuerpo, "autorizacion_id": auth})
    assert r.status_code == 201, r.text
    # una autorización es de un solo uso
    r = cajero.post("/pos/turnos/actual/movimientos", json={**cuerpo, "valor": "350000", "autorizacion_id": auth})
    assert r.status_code == 409


def test_turno_cerrado_es_inmutable_y_no_admite_ventas(pos, conn):
    _, pid, cajero = pos
    t = cajero.abrir_turno("50000")["id"]
    assert (
        cajero.post(
            "/pos/turnos/actual/cierre", json={"conteo": [{"medio_pago_codigo": "10", "valor_contado": "50000"}]}
        ).status_code
        == 200
    )
    assert cajero.get("/pos/turnos/actual").status_code == 404
    r = cajero.post(
        "/pos/turnos/actual/movimientos", json={"tipo": "ingreso", "valor": "1", "motivo_codigo": "reposicion_cambio"}
    )
    assert r.status_code in (404, 422)
    r = cajero.vender([linea(pid)], [efectivo(10000)])
    assert r.status_code in (404, 422) and r.json()["code"] == "sin_turno_abierto"
    with pytest.raises(Exception, match="congelado"):
        conn.execute(text("UPDATE cajas.turnos SET observaciones = 'x' WHERE id = :t"), {"t": t})


def test_cierre_forzado_por_supervisor(pos, client):
    pm, pid, cajero = pos
    t = cajero.abrir_turno("50000")["id"]
    assert cajero.vender([linea(pid)], [efectivo(10000)]).status_code == 201
    # el cajero no tiene el permiso
    r = client.post(f"/api/v1/cajas/turnos/{t}/cierre-forzado", json={"motivo": "abandonado"}, headers=cajero.h)
    assert r.status_code == 403
    h = bearer(token_de(client, pm.mundo.admin.usuario))
    r = client.post(f"/api/v1/cajas/turnos/{t}/cierre-forzado", json={"motivo": "ab"}, headers=h)
    assert r.status_code == 422
    r = client.post(f"/api/v1/cajas/turnos/{t}/cierre-forzado", json={"motivo": "Cajero se fue sin cerrar"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["turno"]["cierre_forzado"] is True
    r = client.post(f"/api/v1/cajas/turnos/{t}/cierre-forzado", json={"motivo": "Cajero se fue sin cerrar"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "turno_cerrado"


def test_operaciones_de_turno_dejan_outbox_y_auditoria(pos, conn):
    _, pid, cajero = pos
    cajero.abrir_turno()
    cajero.post(
        "/pos/turnos/actual/movimientos", json={"tipo": "ingreso", "valor": "100", "motivo_codigo": "reposicion_cambio"}
    )
    cajero.post("/pos/turnos/actual/cierre", json={"conteo": [{"medio_pago_codigo": "10", "valor_contado": "50100"}]})
    tipos = {x[0] for x in conn.execute(text("SELECT evento_tipo FROM sync.outbox_eventos"))}
    assert {"turno.abierto", "turno.cerrado"} <= tipos, tipos
    acciones = {x[0] for x in conn.execute(text("SELECT accion FROM auditoria.log_acciones"))}
    assert any(a.startswith("cajas.") for a in acciones), acciones
