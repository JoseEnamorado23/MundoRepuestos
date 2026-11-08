"""Inventario por API: bodegas, entradas con costo promedio ponderado, ajustes con autorización, kardex y verificación."""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlalchemy import text

from app.modules.inventario.verificacion import verificar
from tests import api_helpers as h
from tests import factories as f

API = "/api/v1"


@pytest.fixture
def mundo(conn, db):
    return h.construir_mundo(conn, db)


@pytest.fixture
def admin(client, mundo):
    return h.bearer(h.token_de(client, "admin"))


@pytest.fixture
def producto(client, admin):
    cat = client.post(f"{API}/catalogo/categorias", json={"nombre": "Filtros"}, headers=admin).json()["id"]
    r = client.post(
        f"{API}/catalogo/productos",
        json={"sku": "INV-1", "nombre": "Filtro", "categoria_id": cat, "impuesto_id": f.IVA19, "stock_minimo": "10"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def entrada(client, hdr, bodega, producto, cantidad, costo, **extra):
    return client.post(
        f"{API}/inventario/entradas",
        json={
            "bodega_id": bodega,
            "lineas": [{"producto_id": producto, "cantidad": str(cantidad), "costo_unitario": str(costo)}],
            **extra,
        },
        headers=hdr,
    )


def existencia(client, hdr, bodega, producto):
    r = client.get(f"{API}/inventario/existencias", params={"bodega_id": bodega, "producto_id": producto}, headers=hdr)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    return items[0] if items else None


# ------------------------------------------------------------------------------------ bodegas y ubicaciones
def test_permisos_de_inventario(client, mundo, admin, db):
    cajero = h.bearer(h.token_de(client, mundo.cajero.usuario))
    assert client.get(f"{API}/inventario/existencias", headers=cajero).status_code == 200  # inventario.ver
    assert (
        client.post(
            f"{API}/inventario/bodegas", json={"sede_id": mundo.sede, "codigo": "X", "nombre": "X"}, headers=cajero
        ).status_code
        == 403
    )
    assert client.post(f"{API}/inventario/ajustes", json={}, headers=cajero).status_code == 403
    assert client.post(f"{API}/inventario/entradas", json={}, headers=cajero).status_code == 403
    assert client.post(f"{API}/inventario/importaciones/validar", headers=cajero).status_code == 403
    assert client.get(f"{API}/inventario/existencias").status_code == 401


def test_bodegas_y_ubicaciones_crud(client, mundo, admin, producto):
    r = client.post(
        f"{API}/inventario/bodegas", json={"sede_id": mundo.sede, "codigo": "B2", "nombre": "Secundaria"}, headers=admin
    )
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    dup = client.post(
        f"{API}/inventario/bodegas", json={"sede_id": mundo.sede, "codigo": "B2", "nombre": "Otra"}, headers=admin
    )
    assert dup.status_code == 409
    assert (
        client.patch(
            f"{API}/inventario/bodegas/{bid}", json={"nombre": "Renombrada", "es_vendible": False}, headers=admin
        ).json()["nombre"]
        == "Renombrada"
    )
    u = client.post(
        f"{API}/inventario/ubicaciones",
        json={"bodega_id": bid, "codigo": "A-01", "pasillo": "A", "estante": "01"},
        headers=admin,
    )
    assert u.status_code == 201, u.text
    uid = u.json()["id"]
    asig = client.put(
        f"{API}/inventario/productos/{producto}/ubicaciones",
        json={"ubicacion_id": uid, "es_principal": True},
        headers=admin,
    )
    assert asig.status_code == 204
    assert client.get(f"{API}/inventario/ubicaciones", params={"bodega_id": bid}, headers=admin).json()["total"] == 1
    assert client.delete(f"{API}/inventario/productos/{producto}/ubicaciones/{uid}", headers=admin).status_code == 204
    assert client.get(f"{API}/inventario/bodegas", params={"sede_id": mundo.sede}, headers=admin).json()["total"] == 2


def test_la_ubicacion_principal_aparece_en_busqueda_y_escaner(client, mundo, admin, producto):
    """El POS muestra dónde está el repuesto: la ubicación principal DE LA SEDE (no la de otra sede)."""
    buscar = lambda **p: client.get(f"{API}/catalogo/productos/buscar", params={"q": "INV-1", **p}, headers=admin)  # noqa: E731
    sin = client.post(
        f"{API}/inventario/bodegas", json={"sede_id": mundo.sede, "codigo": "BU", "nombre": "BU"}, headers=admin
    )
    bid = sin.json()["id"]
    uid = client.post(
        f"{API}/inventario/ubicaciones", json={"bodega_id": bid, "codigo": "Z-09-2", "pasillo": "Z"}, headers=admin
    ).json()["id"]
    assert buscar(sede_id=mundo.sede).json()["items"][0]["ubicacion"] is None  # aún sin ubicación
    client.put(
        f"{API}/inventario/productos/{producto}/ubicaciones",
        json={"ubicacion_id": uid, "es_principal": True},
        headers=admin,
    )
    assert buscar(sede_id=mundo.sede).json()["items"][0]["ubicacion"] == "Z-09-2"
    assert buscar(sede_id=mundo.sede2).json()["items"][0]["ubicacion"] is None  # otra sede: no se muestra

    cajero = h.bearer(h.sesion_pos(client, mundo, "111111"))
    r = client.get(f"{API}/pos/productos/codigo/INV-1", headers=cajero)
    assert r.status_code == 200, r.text
    assert r.json()["ubicacion"] == "Z-09-2"


# ------------------------------------------------------------------------------------ costo promedio ponderado
def test_costo_promedio_ponderado_con_tres_entradas(client, mundo, admin, producto):
    bodega = mundo.ent["bodega"]
    pasos = [(Decimal("10"), Decimal("1000")), (Decimal("5"), Decimal("1200.50")), (Decimal("20"), Decimal("900.25"))]
    saldo, cpp, valor_compras = Decimal(0), Decimal(0), Decimal(0)
    for cantidad, costo in pasos:
        r = entrada(client, admin, bodega, producto, cantidad, costo, numero_factura=f"F-{cantidad}")
        assert r.status_code == 201, r.text
        # fórmula del modelo: (S x CPP + Q x C) / (S + Q), 4 decimales mitad hacia arriba
        cpp = (
            ((saldo * cpp + cantidad * costo) / (saldo + cantidad)).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            if saldo > 0
            else costo
        )
        saldo += cantidad
        valor_compras += cantidad * costo
        e = existencia(client, admin, bodega, producto)
        assert Decimal(e["cantidad"]) == saldo and Decimal(e["costo_promedio"]) == cpp
    assert saldo == 35 and valor_compras == Decimal("10000") + Decimal("6002.50") + Decimal("18005.00")
    # el valor del inventario (saldo x CPP) cuadra al centavo con lo comprado
    e = existencia(client, admin, bodega, producto)
    assert (Decimal(e["cantidad"]) * Decimal(e["costo_promedio"])).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    ) == valor_compras.quantize(Decimal("0.01"))
    assert Decimal(e["ultimo_costo"]) == Decimal("900.25")


def test_kardex_con_saldo_acumulado_y_paginacion(client, mundo, admin, producto):
    bodega = mundo.ent["bodega"]
    for q, c in ((10, 1000), (5, 1200), (20, 900)):
        entrada(client, admin, bodega, producto, q, c)
    client.post(
        f"{API}/inventario/ajustes",
        json={"bodega_id": bodega, "producto_id": producto, "cantidad": "-4", "motivo": "Merma por daño"},
        headers=admin,
    )
    k = client.get(
        f"{API}/inventario/productos/{producto}/kardex",
        params={"bodega_id": bodega, "orden": "secuencia"},
        headers=admin,
    ).json()
    assert [Decimal(m["saldo_cantidad"]) for m in k["items"]] == [10, 15, 35, 31]
    assert [m["secuencia"] for m in k["items"]] == [1, 2, 3, 4] and [m["tipo"] for m in k["items"]][
        -1
    ] == "ajuste_negativo"
    pag = client.get(
        f"{API}/inventario/productos/{producto}/kardex",
        params={"bodega_id": bodega, "limit": 2, "offset": 2},
        headers=admin,
    ).json()
    assert pag["total"] == 4 and len(pag["items"]) == 2 and pag["items"][0]["secuencia"] == 2  # más reciente primero
    # salida valorada al costo promedio vigente
    assert Decimal(k["items"][-1]["costo_unitario"]) == Decimal(k["items"][-2]["costo_promedio_resultante"])


def test_entrada_validaciones(client, mundo, admin, producto):
    bodega = mundo.ent["bodega"]
    assert entrada(client, admin, bodega, producto, 1, 100).status_code == 201  # sin proveedor ni factura
    mala = client.post(f"{API}/inventario/entradas", json={"bodega_id": bodega, "lineas": []}, headers=admin)
    assert mala.status_code == 422
    inexistente = entrada(client, admin, bodega, str(uuid.uuid4()), 1, 100)
    assert inexistente.status_code == 422 and inexistente.json()["code"] == "producto_invalido"
    assert entrada(client, admin, bodega, producto, 0, 100).status_code == 422
    assert entrada(client, admin, bodega, producto, 1, -5).status_code == 422


def test_bajo_stock_minimo_y_existencias_con_reservas(client, mundo, admin, producto, conn):
    bodega = mundo.ent["bodega"]
    entrada(client, admin, bodega, producto, 6, 1000)  # mínimo 10
    bajo = client.get(f"{API}/inventario/bajo-minimo", params={"sede_id": mundo.sede}, headers=admin).json()
    assert bajo["total"] == 1 and Decimal(bajo["items"][0]["faltante"]) == 4
    conn.execute(
        text("UPDATE inventario.existencias SET cantidad_reservada = 2 WHERE producto_id = :p"), {"p": producto}
    )
    e = existencia(client, admin, bodega, producto)
    assert (
        Decimal(e["cantidad"]) == 6 and Decimal(e["cantidad_reservada"]) == 2 and Decimal(e["cantidad_disponible"]) == 4
    )
    por_sede = client.get(
        f"{API}/inventario/existencias", params={"sede_id": mundo.sede, "solo_con_stock": True}, headers=admin
    ).json()
    assert por_sede["total"] == 1
    assert (
        client.get(f"{API}/inventario/existencias", params={"sede_id": mundo.sede2}, headers=admin).json()["total"] == 0
    )


# ------------------------------------------------------------------------------------ ajustes
def test_ajuste_exige_motivo_y_registra_auditoria(client, mundo, admin, producto, conn):
    bodega = mundo.ent["bodega"]
    entrada(client, admin, bodega, producto, 10, 1000)
    base = {"bodega_id": bodega, "producto_id": producto}
    sin_motivo = client.post(f"{API}/inventario/ajustes", json={**base, "cantidad": "-1", "motivo": ""}, headers=admin)
    assert sin_motivo.status_code == 422
    cero = client.post(
        f"{API}/inventario/ajustes", json={**base, "cantidad": "0", "motivo": "nada que ajustar"}, headers=admin
    )
    assert cero.status_code == 422
    pos = client.post(
        f"{API}/inventario/ajustes", json={**base, "cantidad": "3", "motivo": "Conteo encontró más"}, headers=admin
    )
    neg = client.post(
        f"{API}/inventario/ajustes", json={**base, "cantidad": "-2", "motivo": "Daño en bodega"}, headers=admin
    )
    assert pos.status_code == 201 and neg.status_code == 201
    assert pos.json()["tipo"] == "ajuste_positivo" and neg.json()["tipo"] == "ajuste_negativo"
    assert Decimal(existencia(client, admin, bodega, producto)["cantidad"]) == 11
    n = conn.execute(
        text(
            "SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'inventario.ajuste_registrado' AND motivo IS NOT NULL"
        )
    ).scalar()
    assert n == 2


def test_ajuste_sobre_el_umbral_exige_autorizacion_de_un_solo_uso(client, mundo, admin, producto, db):
    bodega = mundo.ent["bodega"]
    for unidades in (450, 450, 100):  # cada entrada <= umbral (500 000): se aplica sin aprobación
        assert entrada(client, admin, bodega, producto, unidades, 1000).status_code == 201
    # solicitante: otro supervisor que entra por el POS; autoriza el supervisor del mundo (PIN 999999)
    solicitante = h.crear_empleado(db, roles=["supervisor"], sedes=[uuid.UUID(mundo.sede)], pin="888888")
    pos = h.bearer(h.sesion_pos(client, mundo, "888888"))
    ajuste = {
        "bodega_id": bodega,
        "producto_id": producto,
        "cantidad": "-600",
        "motivo": "Pérdida por inundación",
    }  # 600 x 1000 > 500000
    sin = client.post(f"{API}/inventario/ajustes", json=ajuste, headers=pos)
    assert sin.status_code == 422 and sin.json()["code"] == "autorizacion_requerida"
    assert Decimal(existencia(client, admin, bodega, producto)["cantidad"]) == 1000  # no se movió nada
    a = client.post(f"{API}/pos/autorizaciones", json={"pin": "999999", "accion": "inventario.ajustar"}, headers=pos)
    assert a.status_code == 201, a.text
    aid = a.json()["autorizacion_id"]
    ok = client.post(f"{API}/inventario/ajustes", json={**ajuste, "autorizacion_id": aid}, headers=pos)
    assert ok.status_code == 201, ok.text
    assert Decimal(existencia(client, admin, bodega, producto)["cantidad"]) == 400
    otra = client.post(f"{API}/inventario/ajustes", json={**ajuste, "autorizacion_id": aid}, headers=pos)
    assert otra.status_code == 409 and otra.json()["code"] == "autorizacion_consumida"
    # por debajo del umbral no hace falta
    chico = client.post(f"{API}/inventario/ajustes", json={**ajuste, "cantidad": "-10"}, headers=pos)
    assert chico.status_code == 201
    assert solicitante.id


# ------------------------------------------------------------------------------------ verificación
def test_verificar_detecta_y_repara_diferencias(client, mundo, admin, producto, db, conn):
    bodega = mundo.ent["bodega"]
    entrada(client, admin, bodega, producto, 10, 1000)
    entrada(client, admin, bodega, producto, 5, 1200)
    assert verificar(db) == []
    conn.execute(
        text("UPDATE inventario.existencias SET cantidad = cantidad + 7 WHERE producto_id = :p"), {"p": producto}
    )
    dif = verificar(db)
    assert len(dif) == 1 and dif[0].cantidad_proyeccion == 22 and dif[0].cantidad_kardex == 15
    v = client.post(f"{API}/inventario/verificar", headers=admin)
    assert v.status_code == 200 and v.json()["diferencias"] == 1 and v.json()["reparadas"] is False
    assert len(verificar(db)) == 1  # sin --reparar no se toca nada
    r = client.post(f"{API}/inventario/verificar", params={"reparar": True}, headers=admin)
    assert r.json()["diferencias"] == 1 and r.json()["reparadas"] is True
    assert verificar(db) == []
    assert Decimal(existencia(client, admin, bodega, producto)["cantidad"]) == 15
    # existencia huérfana (sin kardex) también se detecta
    conn.execute(
        text("INSERT INTO inventario.existencias (bodega_id, producto_id, cantidad) VALUES (:b, :p, 3)"),
        {"b": bodega, "p": f.producto(conn)},
    )
    assert len(verificar(db, reparar=True)) == 1 and verificar(db) == []
