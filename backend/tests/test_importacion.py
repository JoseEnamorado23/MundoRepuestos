"""Importación Excel en dos pasos: errores mezclados (nada escrito), importación válida, reimportación idempotente."""

from __future__ import annotations

import io
import time
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import text

from app.modules.catalogo.utiles import digito_verificador
from tests import api_helpers as h

API = "/api/v1"
COLS = ["sku", "nombre", "categoria", "marca", "referencias", "codigos_barras", "impuesto", "precio_venta", "costo", "stock_inicial", "bodega", "ubicacion", "stock_minimo"]  # fmt: skip
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def ean13(base12: str) -> str:
    return base12 + str(digito_verificador(base12))


def libro(filas: list[list], hoja: str = "productos", cols: list[str] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    ws.append(cols or COLS)
    for fila in filas:
        ws.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def mundo(conn, db):
    return h.construir_mundo(conn, db)


@pytest.fixture
def admin(client, mundo):
    return h.bearer(h.token_de(client, "admin"))


@pytest.fixture
def bodega_codigo(conn, mundo):
    return conn.execute(
        text("SELECT codigo FROM inventario.bodegas WHERE id = :b"), {"b": mundo.ent["bodega"]}
    ).scalar()


def validar(client, hdr, contenido, nombre="lote.xlsx"):
    return client.post(
        f"{API}/inventario/importaciones/validar", files={"archivo": (nombre, contenido, XLSX)}, headers=hdr
    )


def contar(conn, tabla, where="true"):
    return conn.execute(text(f"SELECT count(*) FROM {tabla} WHERE {where}")).scalar()


def archivo_valido(bodega: str) -> bytes:
    return libro([
        ["IMP-1", "Pastilla freno delantera", "Frenos > Pastillas", "Bosch", "OEM:Chevrolet:96 534-653|ALTERNA:Bosch:0986 AB1", ean13("770300000001"), "IVA19", 25000, 12000, 10, bodega, "A-01-02", 5],
        ["IMP-2", "Filtro de aceite", "Filtros", "Fram", "", f"{ean13('770300000002')}|{ean13('770300000003')}", 19, "30.000,50", 8000, 20, bodega, "", 8],
        ["IMP-3", "Bujía", "Encendido", "", "OEM::BKR6E", "", "IVA19", 9000, "", "", "", "", ""],
    ])  # fmt: skip


def test_plantilla_descargable(client, admin):
    r = client.get(f"{API}/inventario/importaciones/plantilla", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"] == XLSX
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames[:2] == ["productos", "compatibilidades"]
    assert [c.value for c in wb["productos"][1]] == COLS
    assert [c.value for c in wb["compatibilidades"][1]] == [
        "sku",
        "marca_vehiculo",
        "modelo",
        "anio_desde",
        "anio_hasta",
        "motor",
    ]


def test_archivo_con_errores_mezclados_reporta_y_no_escribe_nada(client, admin, conn, bodega_codigo):
    contenido = libro([
        ["OK-1", "Producto bueno", "Cat Nueva", "Marca Nueva", "OEM:Fab Nuevo:ABC-123", ean13("770400000001"), "IVA19", 1000, 500, 5, bodega_codigo, "", ""],
        ["OK-1", "SKU repetido", "Cat Nueva", "", "", "", "IVA19", "", "", "", "", "", ""],
        ["ERR-2", "", "Cat", "", "", "", "IVA19", "", "", "", "", "", ""],
        ["ERR-3", "Código malo", "Cat", "", "", "7701234567891", "IVA19", "", "", "", "", "", ""],
        ["ERR-4", "Bodega mala", "Cat", "", "", "", "IVA19", "", "", 3, "NOEXISTE", "", ""],
        ["ERR-5", "Precio negativo", "Cat", "", "", "", "IVA19", -5, "", "", "", "", ""],
        ["ERR-6", "Impuesto raro", "Cat", "", "", "", "IVA77", "", "", "", "", "", ""],
        ["ERR-7", "Ref mal", "Cat", "", "OEM:solo-dos-partes", "", "IVA19", "", "", "", "", "", ""],
        ["ERR-8", "Sin categoría", "", "", "", "", "IVA19", "", "", "", "", "", ""],
        ["OK-9", "Otro bueno", "Cat Nueva", "", "", "", "IVA19", "", "", "", "", "", ""],
    ])  # fmt: skip
    antes = {
        t: contar(conn, t)
        for t in (
            "catalogo.productos",
            "catalogo.categorias",
            "catalogo.marcas",
            "catalogo.precios",
            "inventario.movimientos_inventario",
            "catalogo.productos_codigos_barras",
            "catalogo.productos_referencias",
        )
    }
    r = validar(client, admin, contenido)
    assert r.status_code == 201, r.text
    d = r.json()
    por_fila = {x["fila"]: x for x in d["reporte"]}
    assert por_fila[2]["estado"] == "ok" and por_fila[11]["estado"] == "ok"
    assert por_fila[3]["estado"] == "error" and "repetido" in por_fila[3]["detalle"]
    assert "nombre" in por_fila[4]["detalle"].lower()
    assert "verificador" in por_fila[5]["detalle"]
    assert "bodega" in por_fila[6]["detalle"].lower()
    assert "precio_venta" in por_fila[7]["detalle"]
    assert "Impuesto" in por_fila[8]["detalle"]
    assert "TIPO:FABRICANTE:REFERENCIA" in por_fila[9]["detalle"]
    assert "categoría" in por_fila[10]["detalle"].lower()
    res = d["resumen"]
    assert (res["filas"], res["ok"], res["errores"]) == (10, 2, 8)
    assert res["productos_a_crear"] == 2 and res["productos_a_actualizar"] == 0
    assert res["categorias_nuevas"] == 1 and res["marcas_nuevas"] == 2  # Marca Nueva + Fab Nuevo
    # validar NO escribe datos de negocio
    despues = {t: contar(conn, t) for t in antes}
    assert despues == antes
    # y no se puede confirmar una validación con errores
    c = client.post(f"{API}/inventario/importaciones/{d['id']}/confirmar", headers=admin)
    assert c.status_code == 422 and c.json()["code"] == "importacion_con_errores"
    assert {t: contar(conn, t) for t in antes} == antes
    # el reporte se puede consultar después
    assert client.get(f"{API}/inventario/importaciones/{d['id']}", headers=admin).json()["resumen"]["errores"] == 8


def test_importacion_valida_y_reimportacion_idempotente(client, admin, conn, bodega_codigo, mundo):
    contenido = archivo_valido(bodega_codigo)
    v = validar(client, admin, contenido).json()
    assert v["resumen"]["errores"] == 0 and v["resumen"]["productos_a_crear"] == 3
    assert v["resumen"]["categorias_nuevas"] == 4  # Frenos, Pastillas, Filtros, Encendido
    assert contar(conn, "catalogo.productos", "sku LIKE 'IMP-%'") == 0
    c = client.post(f"{API}/inventario/importaciones/{v['id']}/confirmar", headers=admin)
    assert c.status_code == 200, c.text
    assert c.json()["estado"] == "confirmada"
    # --- resultados
    assert contar(conn, "catalogo.productos", "sku LIKE 'IMP-%'") == 3
    p1 = conn.execute(text("SELECT id, stock_minimo FROM catalogo.productos WHERE sku = 'IMP-1'")).one()
    assert p1.stock_minimo == 5
    cat = conn.execute(
        text(
            "SELECT c.nombre, pa.nombre FROM catalogo.productos p JOIN catalogo.categorias c ON c.id = p.categoria_id LEFT JOIN catalogo.categorias pa ON pa.id = c.parent_id WHERE p.sku = 'IMP-1'"
        )
    ).one()
    assert tuple(cat) == ("Pastillas", "Frenos")  # ruta Padre > Hijo
    assert contar(conn, "catalogo.productos_referencias", "producto_id = :p".replace(":p", f"'{p1.id}'")) == 2
    assert (
        conn.execute(
            text(
                "SELECT count(*) FROM catalogo.productos_codigos_barras cb JOIN catalogo.productos p ON p.id = cb.producto_id WHERE p.sku = 'IMP-2' AND cb.es_principal"
            )
        ).scalar()
        == 1
    )
    precios = dict(
        conn.execute(
            text(
                "SELECT p.sku, pr.precio FROM catalogo.precios pr JOIN catalogo.productos p ON p.id = pr.producto_id WHERE p.sku LIKE 'IMP-%' AND pr.vigente_hasta IS NULL"
            )
        ).all()
    )
    assert precios == {"IMP-1": Decimal("25000"), "IMP-2": Decimal("30000.50"), "IMP-3": Decimal("9000")}
    stock = dict(
        conn.execute(
            text(
                "SELECT p.sku, e.cantidad FROM inventario.existencias e JOIN catalogo.productos p ON p.id = e.producto_id WHERE p.sku LIKE 'IMP-%'"
            )
        ).all()
    )
    assert stock == {"IMP-1": 10, "IMP-2": 20}
    mov = conn.execute(
        text(
            "SELECT tipo, costo_unitario FROM inventario.movimientos_inventario m JOIN catalogo.productos p ON p.id = m.producto_id WHERE p.sku = 'IMP-1'"
        )
    ).one()
    assert mov.tipo == "saldo_inicial" and mov.costo_unitario == Decimal("12000")
    assert contar(conn, "inventario.productos_ubicaciones") == 1
    assert contar(conn, "sync.outbox_eventos", "evento_tipo = 'importacion.confirmada'") == 1
    assert contar(conn, "auditoria.log_acciones", "accion = 'inventario.importacion_confirmada'") == 1
    # no se puede confirmar dos veces
    assert client.post(f"{API}/inventario/importaciones/{v['id']}/confirmar", headers=admin).status_code == 409

    # --- reimportación del MISMO archivo: actualiza, no duplica
    conteos = {
        t: contar(conn, t)
        for t in (
            "catalogo.productos",
            "catalogo.precios",
            "inventario.movimientos_inventario",
            "catalogo.productos_codigos_barras",
            "catalogo.productos_referencias",
            "catalogo.categorias",
            "catalogo.marcas",
            "inventario.productos_ubicaciones",
        )
    }
    v2 = validar(client, admin, contenido).json()
    assert v2["resumen"]["productos_a_crear"] == 0 and v2["resumen"]["productos_a_actualizar"] == 3
    assert v2["resumen"]["precios_a_fijar"] == 0 and v2["resumen"]["stock_inicial_a_cargar"] == 0
    assert v2["resumen"]["categorias_nuevas"] == 0 and v2["resumen"]["marcas_nuevas"] == 0
    assert client.post(f"{API}/inventario/importaciones/{v2['id']}/confirmar", headers=admin).status_code == 200
    assert {t: contar(conn, t) for t in conteos} == conteos
    stock2 = dict(
        conn.execute(
            text(
                "SELECT p.sku, e.cantidad FROM inventario.existencias e JOIN catalogo.productos p ON p.id = e.producto_id WHERE p.sku LIKE 'IMP-%'"
            )
        ).all()
    )
    assert stock2 == {"IMP-1": 10, "IMP-2": 20}  # el stock inicial entra una sola vez

    # --- cambia el precio y el nombre: se actualiza y se fija un precio nuevo cerrando el anterior
    cambiado = libro(
        [
            [
                "IMP-1",
                "Pastilla freno delantera PLUS",
                "Frenos > Pastillas",
                "Bosch",
                "",
                "",
                "IVA19",
                27000,
                "",
                99,
                bodega_codigo,
                "",
                "",
            ]
        ]
    )
    v3 = validar(client, admin, cambiado).json()
    assert (
        v3["resumen"]["precios_a_fijar"] == 1 and v3["resumen"]["stock_inicial_a_cargar"] == 0
    )  # 99 ignorado: ya hubo inicial
    assert client.post(f"{API}/inventario/importaciones/{v3['id']}/confirmar", headers=admin).status_code == 200
    assert (
        conn.execute(text("SELECT nombre FROM catalogo.productos WHERE sku = 'IMP-1'")).scalar()
        == "Pastilla freno delantera PLUS"
    )
    assert contar(conn, "catalogo.precios", f"producto_id = '{p1.id}'") == 2
    assert (
        conn.execute(text("SELECT cantidad FROM inventario.existencias WHERE producto_id = :p"), {"p": p1.id}).scalar()
        == 10
    )


def test_importar_codigo_de_barras_de_otro_producto_es_error(client, admin, bodega_codigo):
    cod = ean13("770500000001")
    uno = libro([["DUP-1", "Uno", "Cat", "", "", cod, "IVA19", "", "", "", "", "", ""]])
    v = validar(client, admin, uno).json()
    assert client.post(f"{API}/inventario/importaciones/{v['id']}/confirmar", headers=admin).status_code == 200
    otro = libro([["DUP-2", "Dos", "Cat", "", "", cod, "IVA19", "", "", "", "", "", ""]])
    r = validar(client, admin, otro).json()
    assert r["resumen"]["errores"] == 1 and "ya pertenece a otro producto" in r["reporte"][0]["detalle"]


def test_importar_compatibilidades(client, admin, bodega_codigo):
    prod = libro([["COMP-1", "Pastilla", "Frenos", "", "", "", "IVA19", "", "", "", "", "", ""]])
    pid = validar(client, admin, prod).json()["id"]
    client.post(f"{API}/inventario/importaciones/{pid}/confirmar", headers=admin)
    cols = ["sku", "marca_vehiculo", "modelo", "anio_desde", "anio_hasta", "motor"]
    comp = libro(
        [
            ["COMP-1", "Chevrolet", "Spark", 2016, 2020, "1.2L"],
            ["COMP-1", "Chevrolet", "Aveo", 2012, "", ""],
            ["NOEXISTE", "Chevrolet", "Spark", 2016, 2020, ""],
        ],
        hoja="compatibilidades",
        cols=cols,
    )
    v = validar(client, admin, comp).json()
    assert v["tipo"] == "compatibilidades" and v["resumen"]["ok"] == 2 and v["resumen"]["errores"] == 1
    assert client.post(f"{API}/inventario/importaciones/{v['id']}/confirmar", headers=admin).status_code == 422
    solo_ok = libro(
        [["COMP-1", "Chevrolet", "Spark", 2016, 2020, "1.2L"], ["COMP-1", "Chevrolet", "Aveo", 2012, "", ""]],
        hoja="compatibilidades",
        cols=cols,
    )
    v = validar(client, admin, solo_ok).json()
    assert (
        v["resumen"]["marcas_vehiculo_nuevas"] == 1
        and v["resumen"]["modelos_nuevos"] == 2
        and v["resumen"]["versiones_nuevas"] == 2
    )
    assert client.post(f"{API}/inventario/importaciones/{v['id']}/confirmar", headers=admin).status_code == 200
    buscar = client.get(f"{API}/catalogo/productos/buscar", params={"q": "pastilla spark 2018"}, headers=admin).json()
    assert [x["sku"] for x in buscar["items"]] == ["COMP-1"]
    # reimportar no duplica compatibilidades
    again = validar(client, admin, solo_ok).json()
    assert client.post(f"{API}/inventario/importaciones/{again['id']}/confirmar", headers=admin).status_code == 200
    comps = client.get(f"{API}/catalogo/productos/{buscar['items'][0]['id']}/compatibilidades", headers=admin).json()
    assert len(comps) == 2


def test_archivos_invalidos(client, admin):
    assert validar(client, admin, b"esto no es un excel").status_code == 422
    sin_cols = libro([["a", "b"]], cols=["sku", "otra"])
    r = validar(client, admin, sin_cols)
    assert r.status_code == 422 and r.json()["code"] == "columnas_faltantes"
    vacio = libro([])
    assert validar(client, admin, vacio).json()["code"] == "archivo_vacio"


def test_5000_filas_se_validan_en_menos_de_30_segundos(client, admin, bodega_codigo):
    filas = []
    for i in range(5000):
        base = f"7706{i:08d}"
        filas.append([f"BULK-{i:05d}", f"Producto de prueba {i}", f"Categoría {i % 40} > Sub {i % 7}", f"Marca {i % 60}", f"OEM:Marca {i % 60}:REF-{i:06d}", ean13(base), "IVA19", 10000 + i, 5000, 3, bodega_codigo, f"P{i % 9}-{i % 30}", 2])  # fmt: skip
    contenido = libro(filas)
    t0 = time.perf_counter()
    r = validar(client, admin, contenido)
    dt = time.perf_counter() - t0
    print(f"\nvalidación de 5000 filas: {dt:.2f} s")
    assert r.status_code == 201, r.text[:300]
    assert r.json()["resumen"]["ok"] == 5000 and r.json()["resumen"]["errores"] == 0
    assert dt < 30
