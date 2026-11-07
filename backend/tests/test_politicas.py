"""Políticas de autorización por acción (0010): libre / revisión posterior / requiere autorización, aprobación remota,
reembolso en efectivo acotado por la caja, y vendedor/cajero."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.api_helpers import bearer, token_de
from tests.pos_helpers import API, Cliente, agregar_caja, construir_pos, efectivo, linea, producto, uid7

D = Decimal

LIBRE = {"politica": "libre"}
REVISION = {"politica": "revision_posterior"}
REQUIERE = {"politica": "requiere_autorizacion"}


class Admin:
    """Cliente de backoffice (login con usuario y contraseña)."""

    def __init__(self, client, usuario: str):
        self.c = client
        self.h = bearer(token_de(client, usuario))

    def get(self, ruta, **kw):
        return self.c.get(f"{API}{ruta}", headers=self.h, **kw)

    def post(self, ruta, **kw):
        return self.c.post(f"{API}{ruta}", headers=self.h, **kw)

    def put(self, ruta, **kw):
        return self.c.put(f"{API}{ruta}", headers=self.h, **kw)


@pytest.fixture
def mundo(conn, db, client):
    pm = construir_pos(conn, db)
    pid = producto(conn, db, pm, "Filtro", "10000", costo="4000")
    caro = producto(conn, db, pm, "Amortiguador", "250000", costo="100000")
    cajero = Cliente(client, pm, "111111")
    admin = Admin(client, pm.mundo.admin.usuario)
    return pm, pid, caro, cajero, admin, client


def _politica(admin, pm, accion, valor):
    r = admin.put(f"/organizacion/politicas-autorizacion/{pm.sede}/{accion}", json=valor)
    assert r.status_code == 200, r.text


def _revisiones(conn, accion):
    return conn.execute(
        text("SELECT estado, monto, entidad_tipo FROM auditoria.revisiones WHERE accion = :a ORDER BY created_at"),
        {"a": accion},
    ).all()


def _vender(cajero, pid, cantidad="1", precio=10000, **extra):
    r = cajero.vender([linea(pid, cantidad)], [efectivo(int(D(cantidad) * precio))], **extra)
    assert r.status_code == 201, r.text
    v = r.json()
    return v, v["lineas"][0]["id"]


def _devolver(cajero, venta, item, **extra):
    cuerpo = {
        "id": uid7(),
        "venta_id": venta["id"],
        "motivo_codigo": "cliente_desiste",
        "reembolso": "efectivo",
        "items": [{"venta_item_id": item, "cantidad": "1"}],
        **extra,
    }
    return cajero.post("/pos/devoluciones", json=cuerpo)


# ============================================================================== catálogo de políticas
def test_las_siete_acciones_tienen_politica_con_los_valores_por_defecto(mundo):
    pm, *_, admin, _c = mundo
    r = admin.get(f"/organizacion/politicas-autorizacion/{pm.sede}")
    assert r.status_code == 200, r.text
    p = r.json()
    assert set(p) == {
        "devolucion",
        "descuento_mayor",
        "cambiar_precio",
        "retiro_caja",
        "diferencia_arqueo",
        "ajuste_inventario",
        "entrada_inventario",
    }
    assert p["devolucion"] == {"politica": "libre", "umbral": 200000, "sobre_umbral": "requiere_autorizacion"}
    assert p["retiro_caja"]["umbral"] == 300000 and p["retiro_caja"]["politica"] == "libre"
    assert p["descuento_mayor"]["politica"] == p["cambiar_precio"]["politica"] == "requiere_autorizacion"
    assert p["diferencia_arqueo"]["politica"] == "revision_posterior"


def test_politicas_invalidas_se_rechazan(mundo):
    pm, *_, admin, _c = mundo
    base = f"/organizacion/politicas-autorizacion/{pm.sede}"
    assert admin.put(f"{base}/devolucion", json={"politica": "inventada"}).status_code == 422
    # la diferencia de arqueo NUNCA puede bloquear el cierre
    r = admin.put(f"{base}/diferencia_arqueo", json=REQUIERE)
    assert r.status_code == 422 and r.json()["code"] == "politica_invalida"
    # las de inventario se gobiernan con el umbral de aprobación
    r = admin.put(f"{base}/ajuste_inventario", json=LIBRE)
    assert r.status_code == 422 and r.json()["code"] == "politica_no_configurable"


# ============================================================================== devolución
def test_devolucion_libre_revision_y_requiere(mundo, conn):
    pm, pid, caro, cajero, admin, _c = mundo
    cajero.abrir_turno("900000")
    # libre (sin umbral): ni autorización ni revisión
    _politica(admin, pm, "devolucion", LIBRE)
    v, it = _vender(cajero, caro, precio=250000)
    assert _devolver(cajero, v, it).status_code == 201
    assert _revisiones(conn, "devolucion") == []
    # revisión posterior: se ejecuta y queda pendiente de revisar con su monto
    _politica(admin, pm, "devolucion", REVISION)
    v, it = _vender(cajero, caro, precio=250000)
    r = _devolver(cajero, v, it)
    assert r.status_code == 201, r.text
    filas = _revisiones(conn, "devolucion")
    assert len(filas) == 1 and filas[0].estado == "pendiente" and D(filas[0].monto) == D("250000")
    # requiere autorización: aun una devolución pequeña
    _politica(admin, pm, "devolucion", REQUIERE)
    v, it = _vender(cajero, pid)
    r = _devolver(cajero, v, it)
    assert r.status_code == 403 and r.json()["code"] == "autorizacion_requerida"
    assert r.json()["vias"] == ["pin_supervisor", "solicitud_remota"]
    auth = cajero.autorizar("999999", "pos.devolver")
    assert _devolver(cajero, v, it, autorizacion_id=auth).status_code == 201


# ============================================================================== descuento y precio
def test_descuento_mayor_libre_revision_y_requiere(mundo, conn):
    pm, pid, _caro, cajero, admin, _c = mundo
    cajero.abrir_turno("50000")
    _politica(admin, pm, "descuento_mayor", LIBRE)
    r = cajero.vender([linea(pid, "1", descuento_pct="10")], [efectivo(9000)])
    assert r.status_code == 201, r.text
    assert _revisiones(conn, "descuento_mayor") == []
    _politica(admin, pm, "descuento_mayor", REVISION)
    r = cajero.vender([linea(pid, "1", descuento_pct="10")], [efectivo(9000)])
    assert r.status_code == 201, r.text
    assert len(_revisiones(conn, "descuento_mayor")) == 1
    _politica(admin, pm, "descuento_mayor", REQUIERE)
    r = cajero.vender([linea(pid, "1", descuento_pct="10")], [efectivo(9000)])
    assert r.status_code == 403 and r.json()["code"] == "autorizacion_requerida"
    auth = cajero.autorizar("999999", "pos.descuento_mayor")
    r = cajero.vender([linea(pid, "1", descuento_pct="10")], [efectivo(9000)], autorizacion_descuento_id=auth)
    assert r.status_code == 201, r.text
    # dentro del tope del rol nunca se pide nada
    assert cajero.vender([linea(pid, "1", descuento_pct="3")], [efectivo(9700)]).status_code == 201


def test_cambiar_precio_libre_revision_y_requiere(mundo, conn):
    pm, pid, _caro, cajero, admin, _c = mundo
    cajero.abrir_turno("50000")
    _politica(admin, pm, "cambiar_precio", LIBRE)
    assert cajero.vender([linea(pid, "1", precio_manual="9000")], [efectivo(9000)]).status_code == 201
    assert _revisiones(conn, "cambiar_precio") == []
    _politica(admin, pm, "cambiar_precio", REVISION)
    assert cajero.vender([linea(pid, "1", precio_manual="9000")], [efectivo(9000)]).status_code == 201
    assert len(_revisiones(conn, "cambiar_precio")) == 1
    _politica(admin, pm, "cambiar_precio", REQUIERE)
    r = cajero.vender([linea(pid, "1", precio_manual="9000")], [efectivo(9000)])
    assert r.status_code == 403 and r.json()["code"] == "autorizacion_requerida"
    auth = cajero.autorizar("999999", "pos.cambiar_precio")
    r = cajero.vender([linea(pid, "1", precio_manual="9000")], [efectivo(9000)], autorizacion_precio_id=auth)
    assert r.status_code == 201, r.text


def test_quien_tiene_el_permiso_no_necesita_autorizacion(mundo, client):
    pm, pid, _caro, _cajero, _admin, _c = mundo
    sup = Cliente(client, pm, "999999")  # supervisor: tiene pos.cambiar_precio y pos.descuento_mayor
    sup.abrir_turno("50000")
    assert sup.vender([linea(pid, "1", precio_manual="9000")], [efectivo(9000)]).status_code == 201
    assert sup.vender([linea(pid, "1", descuento_pct="20")], [efectivo(8000)]).status_code == 201


# ============================================================================== retiro de caja
def test_retiro_libre_revision_y_requiere(mundo, conn):
    pm, _pid, _caro, cajero, admin, _c = mundo
    cajero.abrir_turno("2000000")
    mov = {"tipo": "retiro", "valor": "500000", "motivo_codigo": "retiro_seguridad"}
    # por defecto: libre hasta 300 000, requiere autorización por encima
    r = cajero.post("/pos/turnos/actual/movimientos", json=mov)
    assert r.status_code == 403 and r.json()["code"] == "autorizacion_requerida"
    _politica(admin, pm, "retiro_caja", {"politica": "libre"})
    assert cajero.post("/pos/turnos/actual/movimientos", json=mov).status_code == 201
    assert _revisiones(conn, "retiro_caja") == []
    _politica(admin, pm, "retiro_caja", REVISION)
    assert cajero.post("/pos/turnos/actual/movimientos", json=mov).status_code == 201
    filas = _revisiones(conn, "retiro_caja")
    assert len(filas) == 1 and D(filas[0].monto) == D("500000")
    _politica(admin, pm, "retiro_caja", REQUIERE)
    r = cajero.post("/pos/turnos/actual/movimientos", json={**mov, "valor": "1000"})
    assert r.status_code == 403


# ============================================================================== diferencia de arqueo
def test_diferencia_de_arqueo_nunca_bloquea_en_ninguna_politica(mundo, conn):
    pm, pid, _caro, cajero, admin, _c = mundo
    faltante = [{"medio_pago_codigo": "10", "valor_contado": "10000"}]  # esperado 50000: faltan 40000
    cajero.abrir_turno("50000")
    r = cajero.post("/pos/turnos/actual/cierre", json={"conteo": faltante})
    assert r.status_code == 200, r.text
    assert len(_revisiones(conn, "diferencia_arqueo")) == 1
    _politica(admin, pm, "diferencia_arqueo", LIBRE)
    cajero.abrir_turno("50000")
    assert cajero.post("/pos/turnos/actual/cierre", json={"conteo": faltante}).status_code == 200
    assert len(_revisiones(conn, "diferencia_arqueo")) == 1  # libre: no genera revisión
    # una autorización enviada se ignora (no se consume ni hace falta)
    cajero.abrir_turno("50000")
    r = cajero.post("/pos/turnos/actual/cierre", json={"conteo": faltante, "autorizacion_id": uid7()})
    assert r.status_code == 200, r.text


# ============================================================================== reembolso en efectivo acotado
def test_reembolso_en_efectivo_mayor_al_efectivo_del_turno_se_bloquea_siempre(mundo, conn):
    pm, pid, caro, cajero, admin, _c = mundo
    cajero.abrir_turno("20000")  # el turno solo tiene 20 000 en efectivo
    tarjeta = [{"medio_pago_codigo": "48", "valor": "250000", "referencia": "APR123"}]
    r = cajero.vender([linea(caro, "1")], tarjeta)
    assert r.status_code == 201, r.text
    v = r.json()
    it = v["lineas"][0]["id"]
    _politica(admin, pm, "devolucion", LIBRE)  # aunque la política sea libre, el límite NO es configurable
    r = _devolver(cajero, v, it, reembolso="efectivo")
    assert r.status_code == 422 and r.json()["code"] == "reembolso_excede_efectivo", r.text
    assert "efectivo" in r.json()["detail"].lower()
    assert conn.execute(text("SELECT count(*) FROM ventas.devoluciones")).scalar_one() == 0
    # al medio de pago original sí se puede
    r = _devolver(cajero, v, it, reembolso="medio_original", referencia_reembolso="REV123")
    assert r.status_code == 201, r.text


# ============================================================================== revisiones (backoffice)
def test_revisiones_listar_revisar_y_reporte_diario(mundo, conn):
    pm, pid, caro, cajero, admin, _c = mundo
    cajero.abrir_turno("900000")
    _politica(admin, pm, "devolucion", REVISION)
    for _ in range(2):
        v, it = _vender(cajero, caro, precio=250000)
        assert _devolver(cajero, v, it).status_code == 201
    lista = admin.get("/revisiones", params={"accion": "devolucion"}).json()
    assert lista["total"] == 2 and all(r["estado"] == "pendiente" for r in lista["items"])
    rid = lista["items"][0]["id"]
    # comentario obligatorio
    assert admin.post(f"/revisiones/{rid}/revisar", json={"comentario": "x"}).status_code == 422
    r = admin.post(f"/revisiones/{rid}/revisar", json={"comentario": "Devolución verificada con el cliente"})
    assert r.status_code == 200 and r.json()["estado"] == "revisada" and r.json()["revisada_por_id"]
    assert admin.post(f"/revisiones/{rid}/revisar", json={"comentario": "otra vez"}).status_code == 409
    assert admin.get("/revisiones", params={"accion": "devolucion"}).json()["total"] == 1
    hoy = conn.execute(text("SELECT (now() AT TIME ZONE 'America/Bogota')::date")).scalar_one()
    rep = admin.get("/revisiones/reporte-diario", params={"fecha": str(hoy)}).json()
    assert rep["total"] == 2 and rep["pendientes"] == 1 and rep["revisadas"] == 1
    d = next(a for a in rep["por_accion"] if a["accion"] == "devolucion")
    assert d["cantidad"] == 2 and D(d["monto_total"]) == D("500000")
    ayer = admin.get("/revisiones/reporte-diario", params={"fecha": "2000-01-01"}).json()
    assert ayer["total"] == 0
    # el cajero no gestiona revisiones
    r = cajero.c.get(f"{API}/revisiones", headers=cajero.h)
    assert r.status_code == 403


# ============================================================================== aprobación remota
def _solicitar(cajero, accion="pos.devolver", monto="250000", **extra):
    r = cajero.post(
        "/pos/solicitudes-autorizacion",
        json={"accion": accion, "monto": monto, "motivo": "Cliente en mostrador", **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_aprobacion_remota_crear_aprobar_y_consumir(mundo):
    pm, pid, caro, cajero, admin, _c = mundo
    cajero.abrir_turno("900000")
    v, it = _vender(cajero, caro, precio=250000)
    dev_id = uid7()
    s = _solicitar(cajero, entidad_tipo="devolucion", entidad_id=dev_id, contexto={"venta": v["id"]})
    assert s["estado"] == "pendiente" and s["poll_ms"] == 2000 and s["autorizacion_id"] is None
    # el POS consulta (polling) y sigue pendiente
    assert cajero.get(f"/pos/solicitudes-autorizacion/{s['id']}").json()["estado"] == "pendiente"
    # sin la aprobación, la devolución se rechaza
    assert _devolver(cajero, v, it, id=dev_id).status_code == 403
    # backoffice: aparece en pendientes y se aprueba
    pend = admin.get("/autorizaciones/solicitudes").json()
    assert pend["total"] == 1 and pend["items"][0]["id"] == s["id"]
    r = admin.post(f"/autorizaciones/solicitudes/{s['id']}/aprobar", json={"comentario": "ok"})
    assert r.status_code == 200 and r.json()["estado"] == "aprobada"
    est = cajero.get(f"/pos/solicitudes-autorizacion/{s['id']}").json()
    assert est["estado"] == "aprobada" and est["autorizacion_id"]
    # se consume como una autorización por PIN (un solo uso)
    r = _devolver(cajero, v, it, id=dev_id, autorizacion_id=est["autorizacion_id"])
    assert r.status_code == 201, r.text
    v2, it2 = _vender(cajero, caro, precio=250000)
    r = _devolver(cajero, v2, it2, autorizacion_id=est["autorizacion_id"])
    assert r.status_code in (409, 422)  # ya consumida / de otro documento
    # una solicitud resuelta no se puede volver a resolver
    r = admin.post(f"/autorizaciones/solicitudes/{s['id']}/rechazar", json={})
    assert r.status_code == 409 and r.json()["code"] == "solicitud_resuelta"


def test_aprobacion_remota_rechazada(mundo):
    pm, pid, caro, cajero, admin, _c = mundo
    s = _solicitar(cajero)
    r = admin.post(f"/autorizaciones/solicitudes/{s['id']}/rechazar", json={"comentario": "No procede"})
    assert r.status_code == 200 and r.json()["estado"] == "rechazada"
    est = cajero.get(f"/pos/solicitudes-autorizacion/{s['id']}").json()
    assert est["estado"] == "rechazada" and est["autorizacion_id"] is None and est["comentario"] == "No procede"


def test_aprobacion_remota_expira(mundo, conn):
    pm, pid, caro, cajero, admin, _c = mundo
    s = _solicitar(cajero)
    conn.execute(
        text("UPDATE identidad.solicitudes_autorizacion SET expira_at = now() - interval '1 second' WHERE id = :i"),
        {"i": s["id"]},
    )
    assert cajero.get(f"/pos/solicitudes-autorizacion/{s['id']}").json()["estado"] == "expirada"
    assert admin.get("/autorizaciones/solicitudes").json()["total"] == 0
    # una aprobación tardía se rechaza y la solicitud queda expirada
    s2 = _solicitar(cajero)
    conn.execute(
        text("UPDATE identidad.solicitudes_autorizacion SET expira_at = now() - interval '1 second' WHERE id = :i"),
        {"i": s2["id"]},
    )
    r = admin.post(f"/autorizaciones/solicitudes/{s2['id']}/aprobar", json={})
    assert r.status_code == 422 and r.json()["code"] == "solicitud_expirada"
    assert cajero.get(f"/pos/solicitudes-autorizacion/{s2['id']}").json()["estado"] == "expirada"


def test_expiracion_configurable_por_sede(mundo, conn):
    pm, *_rest = mundo
    cajero = _rest[2]
    conn.execute(
        text(
            "UPDATE organizacion.configuracion_sede SET valor = '1'::jsonb "
            "WHERE sede_id = :s AND clave = 'autorizacion.solicitud_expira_min'"
        ),
        {"s": pm.sede},
    )
    s = _solicitar(cajero)
    seg = conn.execute(
        text("SELECT extract(epoch FROM expira_at - created_at) FROM identidad.solicitudes_autorizacion WHERE id = :i"),
        {"i": s["id"]},
    ).scalar_one()
    assert 55 <= float(seg) <= 65


def test_nadie_aprueba_su_propia_solicitud(mundo, client):
    pm, pid, caro, cajero, admin, _c = mundo
    sup = Cliente(client, pm, "999999")
    s = _solicitar(sup)
    sup_bo = Admin(client, pm.mundo.supervisor.usuario)
    r = sup_bo.post(f"/autorizaciones/solicitudes/{s['id']}/aprobar", json={})
    assert r.status_code == 403 and r.json()["code"] == "autoaprobacion"
    r = sup_bo.post(f"/autorizaciones/solicitudes/{s['id']}/rechazar", json={})
    assert r.status_code == 403
    # el cajero no puede aprobar ni listar (no tiene autorizaciones.aprobar)
    r = cajero.post(f"/autorizaciones/solicitudes/{s['id']}/aprobar", json={})
    assert r.status_code == 403


def test_solo_el_solicitante_ve_su_solicitud(mundo, client):
    pm, *_rest = mundo
    cajero = _rest[2]
    s = _solicitar(cajero)
    otro = Cliente(client, pm, "222222")
    assert otro.get(f"/pos/solicitudes-autorizacion/{s['id']}").status_code == 404


# ============================================================================== vendedor y cajero
def test_vendedor_deja_la_venta_en_espera_y_otra_caja_la_cobra(mundo, conn, db, client):
    pm, pid, caro, cajero1, admin, _c = mundo
    pm2 = agregar_caja(conn, db, pm)
    vendedor = Cliente(client, pm, "333333")
    # el vendedor arma el carrito: no necesita turno abierto ni puede cobrar
    vid = uid7()
    r = vendedor.post("/pos/ventas/espera", json={"id": vid, "lineas": [linea(pid, "2")]})
    assert r.status_code == 201, r.text
    assert r.json()["vendedor_id"] == str(pm.vendedor.id) and r.json()["cajero_id"] is None
    assert vendedor.post("/pos/turnos", json={"base_efectivo": "0"}).status_code == 403
    assert vendedor.vender([linea(pid, "2")], [efectivo(20000)]).status_code == 422  # sin turno
    # otra caja de la sede la ve y la retoma
    cajero2 = Cliente(client, pm2, "222222")
    cajero2.abrir_turno("50000")
    en_espera = cajero2.get("/pos/ventas/espera").json()
    assert [x["id"] for x in en_espera] == [vid]
    assert cajero2.get("/pos/ventas/espera", params={"solo_mias": "true"}).json() == []
    carrito = cajero2.get(f"/pos/ventas/espera/{vid}").json()
    assert carrito["lineas"][0]["cantidad"] and carrito["estado"] == "borrador"
    # el cajero que confirma es el cajero; el vendedor se conserva
    r = cajero2.vender([linea(pid, "2")], [efectivo(20000)], vid=vid)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["vendedor_id"] == str(pm.vendedor.id) and v["cajero_id"] == str(pm2.cajero2.id)
    assert v["caja_id"] == pm2.caja and v["numero_interno"] == 1
    t = cajero2.get(f"/pos/ventas/{vid}/ticket").json()
    assert t["cajero"] and t["vendedor"] and t["cajero"] != t["vendedor"]
    assert conn.execute(text("SELECT vendedor_id, cajero_id FROM ventas.ventas WHERE id = :i"), {"i": vid}).one() == (
        pm.vendedor.id,
        pm2.cajero2.id,
    )


def test_sin_espera_vendedor_y_cajero_son_el_mismo_y_se_filtra_por_vendedor(mundo, client):
    pm, pid, caro, cajero, admin, _c = mundo
    cajero.abrir_turno("50000")
    v1, _ = _vender(cajero, pid)
    assert v1["vendedor_id"] == v1["cajero_id"] == str(pm.mundo.cajero.id)
    r = admin.get("/pos/ventas", params={"vendedor_id": str(pm.vendedor.id)}).json()
    assert r["total"] == 0
    r = admin.get("/pos/ventas", params={"vendedor_id": str(pm.mundo.cajero.id)}).json()
    assert r["total"] == 1 and r["items"][0]["id"] == v1["id"]
    r = admin.get("/pos/ventas", params={"cajero_id": str(pm.mundo.cajero.id)}).json()
    assert r["total"] == 1
