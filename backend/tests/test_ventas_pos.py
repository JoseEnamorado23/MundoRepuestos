"""Ventas POS por la API: dinero exacto al peso, precios del servidor, descuentos con tope, idempotencia, espera, ticket."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from tests import factories as f
from tests.pos_helpers import (
    CONSUMIDOR_FINAL,
    EXCLUIDO,
    Cliente,
    construir_pos,
    efectivo,
    linea,
    producto,
    uid7,
)

D = Decimal


@pytest.fixture
def pos(conn, db, client):
    pm = construir_pos(conn, db)
    cajero = Cliente(client, pm, "111111")
    cajero.abrir_turno("50000")
    return pm, cajero


def _uno(conn, sql, **p):
    return conn.execute(text(sql), p).scalar_one()


def test_tres_items_iva_mixto_descuento_y_pago_mixto_exacto_al_peso(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Pastillas", "11900")  # IVA 19 % incluido
    b = producto(conn, db, pm, "Libro de taller", "8000", impuesto=EXCLUIDO)
    c = producto(conn, db, pm, "Bombillo", "2500")
    lineas = [
        # el precio que mostró el POS no manda: el servidor usa el vigente (11900)
        linea(a, "3", descuento_pct="5", precio_informativo="1"),
        linea(b, "2"),
        linea(c, "1"),
    ]
    pagos = [
        {"medio_pago_codigo": "48", "valor": "30000", "referencia": "AP-9", "canal_pago": "datafono"},
        efectivo(25000),
    ]
    r = cajero.vender(lineas, pagos)
    assert r.status_code == 201, r.text
    v = r.json()
    por_sku = {ln["descripcion"]: ln for ln in v["lineas"]}
    la, lb, lc = por_sku["Pastillas"], por_sku["Libro de taller"], por_sku["Bombillo"]
    # A: 3 x 11900 = 35700; -5 % = 1785; total 33915; base 28500; IVA 5415
    assert (D(la["precio_unitario"]), D(la["descuento_valor"]), D(la["total_linea"])) == (
        D("11900"),
        D("1785"),
        D("33915"),
    )
    assert (D(la["base_gravable"]), D(la["impuesto_valor"])) == (D("28500"), D("5415"))
    # B excluido: sin IVA
    assert (D(lb["total_linea"]), D(lb["base_gravable"]), D(lb["impuesto_valor"])) == (D("16000"), D("16000"), D("0"))
    # C: 2500 / 1,19 = 2100,84 ; IVA 399,16 (por diferencia)
    assert (D(lc["base_gravable"]), D(lc["impuesto_valor"])) == (D("2100.84"), D("399.16"))
    assert D(v["subtotal"]) == D("46600.84") and D(v["impuesto_total"]) == D("5814.16")
    assert D(v["descuento_total"]) == D("1785") and D(v["total"]) == D("52415.00")
    assert D(v["subtotal"]) + D(v["impuesto_total"]) == D(v["total"])  # los totales son la suma de las líneas
    assert D(v["redondeo"]) == 0  # el redondeo solo aplica si TODO se paga en efectivo
    # pago mixto: tarjeta 30000 + efectivo 22415 (recibe 25000 -> cambio 2585)
    pg = {p["medio_pago_codigo"]: p for p in v["pagos"]}
    assert D(pg["48"]["valor"]) == 30000
    assert D(pg["10"]["valor"]) == D("22415") and D(pg["10"]["valor_recibido"]) == 25000
    assert D(pg["10"]["cambio_devuelto"]) == D("2585") and D(v["cambio"]) == D("2585")
    assert v["tercero_id"] == CONSUMIDOR_FINAL and v["numero_interno"] == 1 and v["estado"] == "confirmada"
    # la suma de lo cobrado cuadra con el total
    assert sum(D(p["valor"]) for p in v["pagos"]) == D(v["total"])


def test_el_precio_del_cliente_se_ignora(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    r = cajero.vender([linea(a, "1", precio_informativo="1")], [efectivo(10000)])
    assert r.status_code == 201, r.text
    assert D(r.json()["total"]) == D("10000")


def test_cambiar_precio_exige_permiso_o_autorizacion(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    r = cajero.vender([linea(a, "1", precio_manual="9000")], [efectivo(10000)])
    assert r.status_code == 403 and r.json()["code"] == "autorizacion_requerida"
    auth = cajero.autorizar("999999", "pos.cambiar_precio")
    r = cajero.vender([linea(a, "1", precio_manual="9000")], [efectivo(10000)], autorizacion_precio_id=auth)
    assert r.status_code == 201, r.text
    assert D(r.json()["total"]) == D("9000")


def test_descuento_sobre_el_tope_del_cajero(conn, db, pos, client):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    # tope del cajero: 5 %
    r = cajero.vender([linea(a, "1", descuento_pct="10")], [efectivo(10000)])
    assert r.status_code == 403 and r.json()["code"] == "autorizacion_requerida"
    # el mismo empleado no puede autorizarse a sí mismo (segregación)
    sup = Cliente(client, pm, "999999")
    r = sup.post(
        "/pos/autorizaciones", json={"pin": "999999", "accion": "pos.descuento_mayor", "motivo": "me lo autorizo yo"}
    )
    assert r.status_code >= 400
    # otro empleado con permiso sí puede
    auth = cajero.autorizar("999999", "pos.descuento_mayor")
    r = cajero.vender([linea(a, "1", descuento_pct="10")], [efectivo(9000)], autorizacion_descuento_id=auth)
    assert r.status_code == 201, r.text
    assert D(r.json()["total"]) == D("9000")
    # y esa autorización ya se usó
    r = cajero.vender([linea(a, "1", descuento_pct="10")], [efectivo(9000)], autorizacion_descuento_id=auth)
    assert r.status_code == 409


def test_idempotencia_misma_venta_dos_veces(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    vid = uid7()
    r1 = cajero.vender([linea(a)], [efectivo(10000)], vid=vid)
    r2 = cajero.vender([linea(a)], [efectivo(10000)], vid=vid)
    assert r1.status_code == 201 and r2.status_code == 200
    assert r2.json()["repetida"] is True and r2.json()["numero_interno"] == r1.json()["numero_interno"]
    assert _uno(conn, "SELECT count(*) FROM ventas.ventas WHERE id = :i", i=vid) == 1
    assert (
        _uno(
            conn,
            "SELECT count(*) FROM inventario.movimientos_inventario WHERE tipo = 'venta' AND producto_id = :p",
            p=a,
        )
        == 1
    )
    assert _uno(conn, "SELECT count(*) FROM fiscal.documentos_fiscales WHERE venta_id = :i", i=vid) == 1
    assert _uno(conn, "SELECT cantidad FROM inventario.existencias WHERE producto_id = :p", p=a) == D("99")


def test_el_id_debe_ser_uuid7(pos, conn, db):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    r = cajero.vender([linea(a)], [efectivo(10000)], vid="3f2504e0-4f89-41d3-9a0c-0305e82c3301")  # v4
    assert r.status_code == 422 and r.json()["code"] == "id_invalido"


def test_venta_confirmada_fiscal_pendiente_kardex_con_costo_y_eventos(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000", costo="4000")
    r = cajero.vender([linea(a, "2")], [efectivo(20000)])
    assert r.status_code == 201, r.text
    v = r.json()
    doc = v["documento_fiscal"]
    assert (
        doc["tipo_documento_codigo"] == "FE" and doc["estado"] == "pendiente_envio" and doc["numero_completo"] is None
    )
    fila = conn.execute(
        text("SELECT prefijo, consecutivo FROM fiscal.documentos_fiscales WHERE id = :i"), {"i": doc["id"]}
    ).one()
    assert tuple(fila) == (None, None)  # Factus asigna el número al enviar
    mov = conn.execute(
        text(
            "SELECT cantidad, costo_unitario FROM inventario.movimientos_inventario WHERE tipo = 'venta' AND producto_id = :p"
        ),
        {"p": a},
    ).one()
    assert mov[0] == D("-2") and mov[1] == D("4000")  # snapshot del costo promedio
    assert _uno(conn, "SELECT costo_unitario FROM ventas.ventas_items WHERE venta_id = :v", v=v["id"]) == D("4000")
    tipos = {x[0] for x in conn.execute(text("SELECT evento_tipo FROM sync.outbox_eventos"))}
    assert {"venta.confirmada", "fiscal.emitir"} <= tipos
    assert _uno(conn, "SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'ventas.venta_confirmada'") == 1


def test_venta_confirmada_es_inmutable(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    v = cajero.vender([linea(a)], [efectivo(10000)]).json()
    with pytest.raises(Exception, match="congelad|inmutable"):
        conn.execute(text("UPDATE ventas.ventas SET notas = 'x' WHERE id = :i"), {"i": v["id"]})


def test_sin_turno_abierto_no_hay_venta(conn, db, client):
    pm = construir_pos(conn, db)
    a = producto(conn, db, pm, "Filtro", "10000")
    cajero = Cliente(client, pm, "111111")
    r = cajero.vender([linea(a)], [efectivo(10000)])
    assert r.status_code == 422 and r.json()["code"] == "sin_turno_abierto"


def test_stock_negativo_se_permite_con_alerta(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Último", "10000", stock="1")
    assert cajero.vender([linea(a)], [efectivo(10000)]).status_code == 201
    assert cajero.vender([linea(a)], [efectivo(10000)]).status_code == 201  # no hay existencias: se vende igual
    assert _uno(conn, "SELECT cantidad FROM inventario.existencias WHERE producto_id = :p", p=a) == D("-1")
    assert (
        _uno(conn, "SELECT count(*) FROM inventario.alertas_stock WHERE producto_id = :p AND estado <> 'resuelta'", p=a)
        == 1
    )


def test_pagos_que_no_cuadran(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    r = cajero.vender([linea(a)], [efectivo(5000)])
    assert r.status_code == 422 and r.json()["code"] == "pagos_insuficientes"
    r = cajero.vender([linea(a)], [{"medio_pago_codigo": "48", "valor": "10000"}])
    assert r.status_code == 422 and r.json()["code"] == "referencia_requerida"
    r = cajero.vender([linea(a)], [{"medio_pago_codigo": "48", "valor": "12000", "referencia": "X1"}])
    assert r.status_code == 422 and r.json()["code"] == "pagos_exceden_total"
    assert _uno(conn, "SELECT count(*) FROM ventas.ventas WHERE estado = 'confirmada'") == 0


def test_cliente_rapido_y_venta_a_su_nombre(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    r = cajero.post(
        "/pos/terceros",
        json={
            "tipo_documento_codigo": "13",
            "numero_documento": "1020304050",
            "primer_nombre": "Luis",
            "primer_apellido": "Gómez",
        },
    )
    assert r.status_code in (200, 201), r.text
    tid = r.json()["id"]
    assert cajero.get("/pos/terceros", params={"documento": "1020304050"}).json()[0]["id"] == tid
    v = cajero.vender([linea(a)], [efectivo(10000)], tercero_id=tid, placa_vehiculo="ABC123").json()
    assert v["tercero_id"] == tid
    assert cajero.get(f"/pos/ventas/{v['id']}/ticket").json()["cliente"]["documento"] == "1020304050"


def test_ventas_en_espera(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    espera = uid7()
    r = cajero.post("/pos/ventas/espera", json={"id": espera, "lineas": [linea(a, "2")]})
    assert r.status_code == 201, r.text
    # no mueve inventario ni numera
    assert _uno(conn, "SELECT cantidad FROM inventario.existencias WHERE producto_id = :p", p=a) == D("100")
    assert r.json()["numero_interno"] is None and r.json()["estado"] == "borrador"
    assert [x["id"] for x in cajero.get("/pos/ventas/espera").json()] == [espera]
    assert cajero.get(f"/pos/ventas/espera/{espera}").status_code == 200
    # se retoma confirmando con el mismo id
    r = cajero.vender([linea(a, "2")], [efectivo(20000)], vid=espera)
    assert r.status_code == 201 and r.json()["id"] == espera
    assert cajero.get("/pos/ventas/espera").json() == []
    # descartar
    otra = uid7()
    cajero.post("/pos/ventas/espera", json={"id": otra, "lineas": [linea(a)]})
    assert cajero.delete(f"/pos/ventas/espera/{otra}").status_code == 204
    assert cajero.get("/pos/ventas/espera").json() == []


def test_espera_vencida_se_descarta(conn, db, pos):
    from app.modules.ventas import servicios as svc

    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    espera = uid7()
    cajero.post("/pos/ventas/espera", json={"id": espera, "lineas": [linea(a)]})
    conn.execute(text("SET LOCAL session_replication_role = replica"))  # el trigger de tocar actualiza updated_at
    conn.execute(text("UPDATE ventas.ventas SET updated_at = now() - interval '48 hours' WHERE id = :i"), {"i": espera})
    conn.execute(text("SET LOCAL session_replication_role = origin"))
    import uuid

    assert svc.descartar_vencidas(db, uuid.UUID(pm.sede)) == 1
    assert _uno(conn, "SELECT estado FROM ventas.ventas WHERE id = :i", i=espera) == "descartada"


def test_consulta_de_ventas_y_ticket(conn, db, pos):
    pm, cajero = pos
    a = producto(conn, db, pm, "Filtro", "10000")
    v = cajero.vender([linea(a, "2")], [efectivo(20000)]).json()
    lista = cajero.get("/pos/ventas", params={"turno_actual": "true"}).json()
    assert lista["total"] == 1 and lista["items"][0]["id"] == v["id"]
    assert cajero.get("/pos/ventas", params={"q": str(v["numero_interno"])}).json()["total"] == 1
    t = cajero.get(f"/pos/ventas/{v['id']}/ticket")
    assert t.status_code == 200, t.text
    t = t.json()
    for k in (
        "empresa",
        "sede",
        "caja",
        "cajero",
        "venta",
        "cliente",
        "resolucion",
        "lineas",
        "impuestos",
        "totales",
        "pagos",
        "fiscal",
    ):
        assert k in t, k
    assert t["resolucion"]["prefijo"] == "TF" and t["fiscal"]["estado"] == "pendiente_envio"
    assert t["fiscal"]["leyenda"] and t["venta"]["numero_ticket"].endswith("000001")
    assert D(t["totales"]["total"]) == D("20000") and f.hoy()
