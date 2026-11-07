"""`datos-demo --catalogo`: ~300 repuestos coherentes, idempotentes y buscables ("pastillas spark 2018")."""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import text

from app.aplicacion import catalogo_demo
from app.aplicacion.demo import CLIENTES_DEMO, EMPLEADOS_DEMO, sembrar
from app.modules.catalogo import busqueda
from app.modules.catalogo.utiles import gs1_valido

D = Decimal


def _n(conn, sql, **p):
    return conn.execute(text(sql), p).scalar_one()


# ---------------------------------------------------------------------------------- datos puros (sin BD)
def test_generacion_determinista_unica_y_en_rango():
    a, b = catalogo_demo.generar(), catalogo_demo.generar()
    assert [p.sku for p in a] == [p.sku for p in b]
    assert len({p.sku for p in a}) == len(a) and 280 <= len(a) <= 400
    assert all(1000 <= p.precio <= 1_500_000 for p in a)
    # costo siempre menor que el precio neto (margen positivo)
    assert all(catalogo_demo.costo_demo(p) < D(p.precio) / D("1.19") for p in a)
    marcas = {p.marca for p in a}
    assert {"Bosch", "NGK", "Mann-Filter", "Gates", "Monroe", "Valeo", "Mobil"} <= marcas
    stocks = [catalogo_demo.stock_demo(p) for p in a]
    assert any(s == 0 for s in stocks) and any(0 < s < p.minimo for s, p in zip(stocks, a, strict=True))
    assert any(s >= p.minimo for s, p in zip(stocks, a, strict=True))
    # cobertura de vehículos pedidos
    modelos = {(v.marca, v.modelo) for v in catalogo_demo.VEHICULOS}
    for esperado in [
        ("Chevrolet", "Spark"), ("Chevrolet", "Aveo"), ("Chevrolet", "Sail"), ("Chevrolet", "Onix"),
        ("Renault", "Logan"), ("Renault", "Sandero"), ("Renault", "Duster"), ("Mazda", "Mazda 2"),
        ("Mazda", "Mazda 3"), ("Kia", "Picanto"), ("Kia", "Rio"), ("Hyundai", "i10"), ("Hyundai", "Accent"),
        ("Toyota", "Corolla"), ("Toyota", "Hilux"), ("Nissan", "March"), ("Nissan", "Versa"),
    ]:  # fmt: skip
        assert esperado in modelos, esperado


# ---------------------------------------------------------------------------------- en BD
def test_datos_demo_con_catalogo_es_idempotente_coherente_y_buscable(conn, db):
    r1 = sembrar(db, catalogo=True)
    db.flush()
    c1 = r1.catalogo
    assert c1.productos_nuevos == len(catalogo_demo.generar()) and c1.productos_existentes == 0
    assert c1.sin_stock > 0 and c1.bajo_minimo > 0 and c1.con_stock > 0

    contar = {
        "productos": "SELECT count(*) FROM catalogo.productos",
        "precios": "SELECT count(*) FROM catalogo.precios",
        "compat": "SELECT count(*) FROM catalogo.productos_compatibilidades",
        "kardex": "SELECT count(*) FROM inventario.movimientos_inventario",
        "outbox": "SELECT count(*) FROM sync.outbox_eventos",
        "auditoria": "SELECT count(*) FROM auditoria.log_acciones",
        "empleados": "SELECT count(*) FROM identidad.empleados",
        "terceros": "SELECT count(*) FROM identidad.terceros",
    }
    antes = {k: _n(conn, q) for k, q in contar.items()}

    # --- idempotente: una segunda corrida no crea, ni emite eventos, ni toca nada ---
    r2 = sembrar(db, catalogo=True)
    db.flush()
    assert r2.catalogo.productos_nuevos == 0 and r2.catalogo.productos_existentes == c1.productos_nuevos
    assert r2.creados == [] or all("catálogo" not in c for c in r2.creados)
    assert {k: _n(conn, q) for k, q in contar.items()} == antes
    assert r2.sede_id == r1.sede_id and r2.propietario_id == r1.propietario_id

    # --- coherencia ---
    assert _n(conn, "SELECT count(*) FROM catalogo.productos_referencias WHERE tipo <> 'alterna'") == 0
    sin_precio = _n(
        conn,
        "SELECT count(*) FROM catalogo.productos p WHERE NOT EXISTS (SELECT 1 FROM catalogo.precios x WHERE x.producto_id = p.id)",
    )
    assert sin_precio == 0
    codigos = conn.execute(text("SELECT codigo, tipo FROM catalogo.productos_codigos_barras")).all()
    assert len(codigos) == c1.productos_nuevos
    assert all(re.fullmatch(r"2\d{12}", c) and gs1_valido(c, 13) for c, _t in codigos)
    # tres empleados con PIN y cinco clientes
    roles = dict(
        conn.execute(
            text(
                "SELECT e.numero_documento, r.codigo FROM identidad.empleados e "
                "JOIN identidad.empleados_roles er ON er.empleado_id = e.id JOIN identidad.roles r ON r.id = er.rol_id "
                "WHERE e.numero_documento = ANY(:d)"
            ),
            {"d": [e.documento for e in EMPLEADOS_DEMO]},
        ).all()
    )
    assert sorted(roles.values()) == ["cajero", "propietario", "vendedor"]
    assert (
        _n(
            conn,
            "SELECT count(*) FROM identidad.terceros WHERE numero_documento = ANY(:d)",
            d=[c["numero_documento"] for c in CLIENTES_DEMO],
        )
        == 5
    )

    # --- búsqueda: "pastillas spark 2018" devuelve pastillas compatibles con un Spark que cubre 2018 ---
    items, total, _inc = busqueda.buscar(db, q="pastillas spark 2018", sede_id=r1.sede_id, limit=50, offset=0)
    assert total >= 2, (total, items)
    for it in items:
        assert "pastillas" in it["nombre"].lower(), it["nombre"]
        ok = _n(
            conn,
            "SELECT count(*) FROM catalogo.productos_compatibilidades pc "
            "JOIN catalogo.vehiculos_versiones v ON v.id = pc.version_id "
            "JOIN catalogo.vehiculos_modelos m ON m.id = v.modelo_id "
            "WHERE pc.producto_id = :p AND m.nombre = 'Spark' AND v.anio_desde <= 2018 AND coalesce(v.anio_hasta, 9999) >= 2018",
            p=it["id"],
        )
        assert ok >= 1, f"{it['nombre']} no es compatible con un Spark 2018"
    # y NO trae pastillas de un Hilux, que no es un Spark
    nombres = " ".join(i["nombre"] for i in items)
    assert "Hilux" not in nombres and "Corolla" not in nombres
