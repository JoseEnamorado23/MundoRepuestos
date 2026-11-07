"""Devoluciones POS: parciales con tope, reembolso desde el turno actual, nota crédito pendiente, destino averías."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.pos_helpers import Cliente, construir_pos, efectivo, linea, producto, uid7

D = Decimal


@pytest.fixture
def pos(conn, db, client):
    pm = construir_pos(conn, db)
    pid = producto(conn, db, pm, "Filtro", "10000", costo="4000")
    cajero = Cliente(client, pm, "111111")
    cajero.abrir_turno("50000")
    return pm, pid, cajero


def _uno(conn, sql, **p):
    return conn.execute(text(sql), p).scalar_one()


def _devolver(
    cajero,
    venta,
    item,
    cantidad,
    *,
    reembolso="efectivo",
    destino="vendible",
    motivo="cliente_desiste",
    auth=True,
    **extra,
):
    cuerpo = {
        "id": uid7(),
        "venta_id": venta["id"],
        "motivo_codigo": motivo,
        "reembolso": reembolso,
        "items": [{"venta_item_id": item, "cantidad": str(cantidad), "destino": destino}],
        **extra,
    }
    if auth and "autorizacion_id" not in cuerpo:
        cuerpo["autorizacion_id"] = cajero.autorizar("999999", "pos.devolver")
    return cajero.post("/pos/devoluciones", json=cuerpo)


def _vender(cajero, pid, cantidad="3", pagos=None):
    v = cajero.vender([linea(pid, cantidad)], pagos or [efectivo(int(D(cantidad) * 10000))])
    assert v.status_code == 201, v.text
    v = v.json()
    return v, v["lineas"][0]["id"]


def test_devolucion_parcial_y_luego_una_excesiva(conn, pos):
    pm, pid, cajero = pos
    venta, item = _vender(cajero, pid, "3")
    r = _devolver(cajero, venta, item, 1)
    assert r.status_code == 201, r.text
    d = r.json()
    assert D(d["total"]) == D("10000") and d["estado"] == "confirmada"
    assert d["lineas"][0]["reintegra_stock"] is True
    assert _uno(conn, "SELECT cantidad FROM inventario.existencias WHERE producto_id = :p", p=pid) == D("98")
    # quedan 2 por devolver: 3 es demasiado
    r = _devolver(cajero, venta, item, 3)
    assert r.status_code == 422 and r.json()["code"] == "cantidad_excede_vendida"
    assert _uno(conn, "SELECT count(*) FROM ventas.devoluciones WHERE estado = 'confirmada'") == 1
    # las 2 restantes sí; la última toma el resto exacto de la línea
    r = _devolver(cajero, venta, item, 2)
    assert r.status_code == 201, r.text
    assert D(r.json()["total"]) == D("20000")
    assert _uno(conn, "SELECT cantidad FROM inventario.existencias WHERE producto_id = :p", p=pid) == D("100")
    # y ya no queda nada
    assert _devolver(cajero, venta, item, 1).status_code == 422


def test_la_devolucion_es_libre_hasta_el_umbral_y_exige_autorizacion_por_encima(conn, db, pos):
    pm, pid, cajero = pos
    # bajo el umbral (200 000) el cajero devuelve SIN autorización ni permiso pos.devolver
    venta, item = _vender(cajero, pid, "1")
    r = _devolver(cajero, venta, item, 1, auth=False)
    assert r.status_code == 201, r.text
    r = _devolver(cajero, venta, item, 1, motivo="inventado")
    assert r.status_code == 422 and r.json()["code"] == "motivo_invalido"
    # sobre el umbral: requiere autorización de otro empleado
    caro = producto(conn, db, pm, "Amortiguador", "250000", costo="100000")
    venta2, item2 = _vender(cajero, caro, "1", pagos=[efectivo(250000)])
    r = _devolver(cajero, venta2, item2, 1, auth=False)
    assert r.status_code == 403 and r.json()["code"] == "autorizacion_requerida"
    assert "solicitud_remota" in r.json()["vias"]
    r = _devolver(cajero, venta2, item2, 1)
    assert r.status_code == 201, r.text


def test_idempotencia_de_la_devolucion(conn, pos):
    _, pid, cajero = pos
    venta, item = _vender(cajero, pid, "2")
    cuerpo = {
        "id": uid7(),
        "venta_id": venta["id"],
        "motivo_codigo": "defectuosa",
        "reembolso": "efectivo",
        "items": [{"venta_item_id": item, "cantidad": "1"}],
    }
    r1 = cajero.post(
        "/pos/devoluciones", json={**cuerpo, "autorizacion_id": cajero.autorizar("999999", "pos.devolver")}
    )
    r2 = cajero.post(
        "/pos/devoluciones", json={**cuerpo, "autorizacion_id": cajero.autorizar("999999", "pos.devolver")}
    )
    assert (r1.status_code, r2.status_code) == (201, 200) and r2.json()["repetida"] is True
    assert _uno(conn, "SELECT count(*) FROM ventas.devoluciones") == 1
    assert _uno(conn, "SELECT count(*) FROM inventario.movimientos_inventario WHERE tipo = 'devolucion_venta'") == 1


def test_reembolso_en_efectivo_sale_del_turno_actual_aunque_la_venta_sea_de_otro(pos):
    pm, pid, cajero = pos
    venta, item = _vender(cajero, pid, "3")  # turno A: ingresa 30000
    cierre = cajero.post(
        "/pos/turnos/actual/cierre", json={"conteo": [{"medio_pago_codigo": "10", "valor_contado": "80000"}]}
    )
    assert cierre.status_code == 200, cierre.text
    # turno B (otro cajero, misma caja)
    otro = Cliente(cajero.c, pm, "222222")
    otro.abrir_turno("20000")
    r = _devolver(otro, venta, item, 1)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["reembolsos"][0]["medio_pago_codigo"] == "10" and D(d["reembolsos"][0]["valor"]) == D("10000")
    # arqueo del turno B: base 20000 - reembolso 10000 = 10000 esperados
    r = otro.post("/pos/turnos/actual/cierre", json={"conteo": [{"medio_pago_codigo": "10", "valor_contado": "10000"}]})
    assert r.status_code == 200, r.text
    inf = r.json()
    arq = {a["medio_pago_codigo"]: a for a in inf["arqueos"]}
    assert D(arq["10"]["esperado"]) == D("10000") and D(arq["10"]["diferencia"]) == 0
    assert D(inf["efectivo"]["reembolsos_efectivo"]) == D("10000")
    assert inf["resumen"]["num_devoluciones"] == 1 and D(inf["resumen"]["total_devoluciones"]) == D("10000")
    # el turno A ya cerrado no cambió: su informe sigue mostrando 80000 esperados
    t_a = cierre.json()["turno"]["id"]
    inf_a = otro.get(f"/pos/turnos/{t_a}/informe-cierre").json()
    assert D({a["medio_pago_codigo"]: a for a in inf_a["arqueos"]}["10"]["esperado"]) == D("80000")


def test_reembolso_por_el_medio_original_exige_referencia(pos):
    _, pid, cajero = pos
    tarjeta = [{"medio_pago_codigo": "48", "valor": "10000", "referencia": "AP-77", "canal_pago": "datafono"}]
    venta, item = _vender(cajero, pid, "1", pagos=tarjeta)
    r = _devolver(cajero, venta, item, 1, reembolso="medio_original")
    assert r.status_code == 422 and r.json()["code"] == "referencia_requerida"
    r = _devolver(cajero, venta, item, 1, reembolso="medio_original", referencia_reembolso="REV-77")
    assert r.status_code == 201, r.text
    assert r.json()["reembolsos"][0]["medio_pago_codigo"] == "48"
    assert r.json()["reembolsos"][0]["referencia"] == "REV-77"
    # no era efectivo: no afecta el arqueo de efectivo
    cierre = cajero.post(
        "/pos/turnos/actual/cierre",
        json={
            "conteo": [
                {"medio_pago_codigo": "10", "valor_contado": "50000"},
                {"medio_pago_codigo": "48", "valor_contado": "0"},
            ]
        },
    )
    assert cierre.status_code == 200, cierre.text
    assert D(cierre.json()["efectivo"]["reembolsos_efectivo"]) == 0


def test_nota_credito_pendiente_referencia_la_factura(conn, pos):
    _, pid, cajero = pos
    venta, item = _vender(cajero, pid, "3")
    parcial = _devolver(cajero, venta, item, 1).json()
    nc = parcial["documento_fiscal"]
    assert nc["tipo_documento_codigo"] == "NC" and nc["estado"] == "pendiente_envio" and nc["numero_completo"] is None
    assert nc["documento_referenciado_id"] == venta["documento_fiscal"]["id"]
    fila = conn.execute(
        text("SELECT prefijo, consecutivo, documento_referenciado_id FROM fiscal.documentos_fiscales WHERE id = :i"),
        {"i": nc["id"]},
    ).one()
    assert fila[0] is None and fila[1] is None and str(fila[2]) == venta["documento_fiscal"]["id"]
    tipos = {x[0] for x in conn.execute(text("SELECT evento_tipo FROM sync.outbox_eventos"))}
    assert {"devolucion.confirmada", "fiscal.emitir"} <= tipos
    assert _uno(conn, "SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'ventas.devolucion_confirmada'") == 1


def test_destino_averias_no_queda_disponible_para_vender(conn, pos):
    pm, pid, cajero = pos
    venta, item = _vender(cajero, pid, "2")
    r = _devolver(cajero, venta, item, 1, destino="averias", motivo="defectuosa")
    assert r.status_code == 201, r.text
    assert r.json()["lineas"][0]["bodega_reintegro_id"] == pm.averias
    # la bodega vendible sigue en 98 (100 - 2) y la unidad quedó en averías, que no es vendible
    assert _uno(
        conn,
        "SELECT cantidad FROM inventario.existencias WHERE producto_id = :p AND bodega_id = :b",
        p=pid,
        b=pm.bodega,
    ) == D("98")
    assert _uno(
        conn,
        "SELECT cantidad FROM inventario.existencias WHERE producto_id = :p AND bodega_id = :b",
        p=pid,
        b=pm.averias,
    ) == D("1")
    vendible = _uno(
        conn,
        "SELECT coalesce(sum(e.cantidad), 0) FROM inventario.existencias e JOIN inventario.bodegas b ON b.id = e.bodega_id"
        " WHERE e.producto_id = :p AND b.es_vendible",
        p=pid,
    )
    assert vendible == D("98")
    assert _uno(conn, "SELECT es_vendible FROM inventario.bodegas WHERE id = :b", b=pm.averias) is False
    # y el costo del reintegro es el de la venta original
    assert _uno(
        conn,
        "SELECT costo_unitario FROM inventario.movimientos_inventario WHERE tipo = 'devolucion_venta' AND producto_id = :p",
        p=pid,
    ) == D("4000")


def test_no_existe_anular_venta(client, pos):
    _, pid, cajero = pos
    venta, _ = _vender(cajero, pid, "1")
    assert cajero.delete(f"/pos/ventas/{venta['id']}").status_code in (404, 405)
    assert cajero.post(f"/pos/ventas/{venta['id']}/anular").status_code in (404, 405)


def test_devolucion_sin_turno_abierto(conn, db, client):
    pm = construir_pos(conn, db)
    pid = producto(conn, db, pm, "Filtro", "10000")
    cajero = Cliente(client, pm, "111111")
    cajero.abrir_turno("0")
    venta, item = _vender(cajero, pid, "1")
    cajero.post("/pos/turnos/actual/cierre", json={"conteo": [{"medio_pago_codigo": "10", "valor_contado": "10000"}]})
    r = _devolver(cajero, venta, item, 1)
    assert r.status_code == 422 and r.json()["code"] == "sin_turno_abierto"
