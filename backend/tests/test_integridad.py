"""Reglas de integridad que impone la propia BD (modelo.md D-24): triggers, EXCLUDE, índices, columnas generadas."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests import factories as f

ERR_BD = (DBAPIError, IntegrityError)


def uno(conn, sql: str, **p):
    return conn.execute(text(sql), p).scalar_one()


def falla(conn, sql: str, **p) -> str:
    """Ejecuta `sql` esperando que la BD lo rechace; el savepoint evita abortar la transacción de la prueba."""
    with pytest.raises(ERR_BD) as exc, conn.begin_nested():
        conn.execute(text(sql), p)
    return str(exc.value)


# ---------------------------------------------------------------- semillas ------------------------------------
def test_semillas_basicas(conn):
    assert uno(conn, "SELECT count(*) FROM organizacion.nodos WHERE tipo = 'cloud'") == 1
    assert (
        uno(conn, "SELECT nombre_completo FROM identidad.terceros WHERE id = :i", i=f.TERCERO_CONSUMIDOR_FINAL)
        == "Consumidor final"
    )
    activos = {r[0] for r in conn.execute(text("SELECT codigo FROM referencia.tipos_documento_fiscal WHERE activo"))}
    assert activos == {"FE", "NC", "ND"}
    assert uno(conn, "SELECT count(*) FROM referencia.departamentos") == 33
    assert uno(conn, "SELECT es_efectivo FROM referencia.medios_pago WHERE codigo = '10'") is True
    assert uno(
        conn,
        "SELECT count(*) FROM identidad.roles_permisos rp JOIN identidad.roles r ON r.id = rp.rol_id "
        "WHERE r.codigo = 'administrador'",
    ) == uno(conn, "SELECT count(*) FROM identidad.permisos")


# ---------------------------------------------------------------- índices de unicidad -------------------------
def test_una_sola_nube(conn):
    falla(
        conn,
        "INSERT INTO organizacion.nodos (id, tipo, nombre, nodo_origen_id) "
        "VALUES (gen_random_uuid(), 'cloud', 'Otra nube', :n)",
        n=f.NODO_NUBE,
    )


def test_un_solo_consumidor_final(conn):
    falla(
        conn,
        "INSERT INTO identidad.terceros (id, tipo_persona_codigo, tipo_documento_codigo, numero_documento, "
        "nombre_completo, es_consumidor_final, nodo_origen_id) "
        "VALUES (gen_random_uuid(), '2', '13', '222222222222', 'Otro', true, :n)",
        n=f.NODO_NUBE,
    )


def test_usuario_unico_sin_importar_mayusculas(conn):
    f.insertar(
        conn,
        "identidad.empleados",
        tipo_documento_codigo="13",
        numero_documento="111",
        nombres="A",
        apellidos="B",
        usuario="Maria",
    )
    falla(
        conn,
        "INSERT INTO identidad.empleados (id, tipo_documento_codigo, numero_documento, nombres, apellidos, "
        "usuario, nodo_origen_id) VALUES (gen_random_uuid(), '13', '222', 'C', 'D', 'MARIA', :n)",
        n=f.NODO_NUBE,
    )


def test_una_sola_lista_predeterminada(conn):
    falla(
        conn,
        "INSERT INTO catalogo.listas_precios (id, codigo, nombre, es_predeterminada, nodo_origen_id) "
        "VALUES (gen_random_uuid(), 'MAYORISTA', 'Mayorista', true, :n)",
        n=f.NODO_NUBE,
    )


# ---------------------------------------------------------------- tg_tocar (versión / updated_at) -------------
def test_tg_tocar_incrementa_version_y_updated_at(conn):
    emp = f.empleado(conn)
    v1, t1 = conn.execute(text("SELECT version, updated_at FROM identidad.empleados WHERE id = :i"), {"i": emp}).one()
    assert v1 == 1
    # el cliente envía una versión cualquiera: el trigger impone OLD.version + 1
    conn.execute(text("UPDATE identidad.empleados SET nombres = 'Beatriz', version = 99 WHERE id = :i"), {"i": emp})
    v2, t2 = conn.execute(text("SELECT version, updated_at FROM identidad.empleados WHERE id = :i"), {"i": emp}).one()
    assert v2 == 2
    assert t2 >= t1


# ---------------------------------------------------------------- inmutabilidad -------------------------------
def test_kardex_es_append_only(conn):
    ent = f.entorno_pos(conn)
    prod = f.producto(conn)
    conn.execute(
        text(
            "INSERT INTO inventario.movimientos_inventario (id, bodega_id, producto_id, secuencia, tipo, cantidad, "
            "costo_unitario, saldo_cantidad, costo_promedio_resultante, origen_tipo, origen_id, origen_linea_id, "
            "ocurrido_at, nodo_origen_id) VALUES (gen_random_uuid(), :b, :p, 1, 'saldo_inicial', 10, 5, 10, 5, "
            "'saldo_inicial', :b, :b, now(), :n)"
        ),
        {"b": ent["bodega"], "p": prod, "n": f.NODO_NUBE},
    )
    falla(
        conn,
        "INSERT INTO inventario.movimientos_inventario (id, bodega_id, producto_id, secuencia, tipo, cantidad, "
        "costo_unitario, saldo_cantidad, costo_promedio_resultante, origen_tipo, origen_id, origen_linea_id, "
        "ocurrido_at, nodo_origen_id) VALUES (gen_random_uuid(), :b, :p, 1, 'saldo_inicial', 1, 5, 1, 5, "
        "'saldo_inicial', :b, :b, now(), :n)",
        b=ent["bodega"],
        p=prod,
        n=f.NODO_NUBE,
    )  # secuencia repetida
    assert "inmutable" in falla(conn, "UPDATE inventario.movimientos_inventario SET cantidad = 99")
    assert "inmutable" in falla(conn, "DELETE FROM inventario.movimientos_inventario")


def test_venta_confirmada_queda_congelada(conn):
    ent = f.entorno_pos(conn)
    prod = f.producto(conn)
    venta = f.venta_borrador(conn, ent, total=D("119"))
    f.venta_item(conn, venta, ent["bodega"], prod)  # en borrador se puede escribir
    conn.execute(text("UPDATE ventas.ventas SET notas = 'ok' WHERE id = :i"), {"i": venta})
    conn.execute(text("UPDATE ventas.ventas SET estado = 'descartada' WHERE id = :i"), {"i": venta})
    assert "congelado" in falla(conn, "UPDATE ventas.ventas SET notas = 'x' WHERE id = :i", i=venta)
    assert "congelado" in falla(conn, "DELETE FROM ventas.ventas WHERE id = :i", i=venta)
    assert "no se puede modificar" in falla(conn, "DELETE FROM ventas.ventas_items WHERE venta_id = :i", i=venta)
    with pytest.raises(ERR_BD), conn.begin_nested():
        f.venta_item(conn, venta, ent["bodega"], prod, linea=2)


def test_turno_cerrado_queda_congelado(conn):
    ent = f.entorno_pos(conn)
    # 0010: la BD ya NO rechaza un cierre con diferencia (la política decide; nunca bloquea)
    assert not conn.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = 'ck_turnos_diferencia_autorizada'")
    ).first()
    conn.execute(
        text(
            "UPDATE cajas.turnos SET estado = 'cerrado', cerrado_at = now(), cerrado_por_id = :e, "
            "umbral_diferencia = 5000, efectivo_esperado = 50000, efectivo_contado = 49000 WHERE id = :t"
        ),
        {"e": ent["empleado"], "t": ent["turno"]},
    )
    assert uno(conn, "SELECT diferencia FROM cajas.turnos WHERE id = :t", t=ent["turno"]) == D("-1000.00")
    assert "congelado" in falla(conn, "UPDATE cajas.turnos SET observaciones = 'x' WHERE id = :t", t=ent["turno"])


def _confirmar(conn, venta: str) -> None:
    conn.execute(
        text(
            "UPDATE ventas.ventas SET estado = 'confirmada', confirmada_at = now(), numero_interno = 1, "
            "subtotal = 100, cajero_id = (SELECT t.abierto_por_id FROM cajas.turnos t WHERE t.id = turno_id) "
            "WHERE id = :i"
        ),
        {"i": venta},
    )


def test_pagos_deben_cuadrar_con_el_total_al_confirmar(conn):
    ent = f.entorno_pos(conn)
    venta = f.venta_borrador(conn, ent, total=D("100"))
    f.insertar(conn, "ventas.ventas_pagos", venta_id=venta, medio_pago_codigo="10", valor=D("90"))
    _confirmar(conn, venta)
    with pytest.raises(ERR_BD), conn.begin_nested():
        conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))  # equivale al COMMIT: 90 <> 100


def test_pagos_que_cuadran_pasan(conn):
    ent = f.entorno_pos(conn)
    venta = f.venta_borrador(conn, ent, total=D("100"))
    f.insertar(conn, "ventas.ventas_pagos", venta_id=venta, medio_pago_codigo="10", valor=D("100"))
    _confirmar(conn, venta)
    with conn.begin_nested():
        conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


# ---------------------------------------------------------------- EXCLUDE -------------------------------------
def test_precios_sin_vigencias_solapadas(conn):
    prod = f.producto(conn)

    def precio(desde, hasta):
        return f.insertar(
            conn,
            "catalogo.precios",
            producto_id=prod,
            lista_precio_id=f.LISTA_GENERAL,
            precio=D("1000"),
            vigente_desde=desde,
            vigente_hasta=hasta,
        )

    precio("2026-01-01", "2026-02-01")
    precio("2026-02-01", "2026-03-01")  # contiguo: permitido (rango semiabierto)
    with pytest.raises(ERR_BD), conn.begin_nested():
        precio("2026-01-15", "2026-02-15")  # solapa


def _resolucion(conn, emp, **extra):
    base = dict(
        empresa_id=emp,
        tipo_documento_codigo="FE",
        numero_resolucion="1",
        fecha_resolucion="2026-01-01",
        prefijo="SETP",
        consecutivo_actual=extra.get("rango_desde", 1) - 1,
        vigente_desde="2026-01-01",
        vigente_hasta="2099-01-01",
        modo_numeracion="proveedor",
        id_rango_proveedor=1,
        estado="activa",
    )
    base.update(extra)
    return f.insertar(conn, "fiscal.resoluciones_numeracion", **base)


def test_resoluciones_sin_rangos_solapados(conn):
    emp = f.empresa(conn)
    _resolucion(conn, emp, rango_desde=1, rango_hasta=1000)
    # las demás van 'vencida' para no chocar con uq_resoluciones_activa_empresa: aquí se prueba solo el EXCLUDE
    msg = falla_ins(conn, emp, rango_desde=500, rango_hasta=2000)
    assert "ex_resoluciones_sin_solape" in msg
    _resolucion(conn, emp, estado="vencida", rango_desde=1001, rango_hasta=2000)  # contiguo
    _resolucion(conn, emp, estado="vencida", prefijo="OTRO", rango_desde=1, rango_hasta=10)  # otro prefijo


def falla_ins(conn, emp, **kw) -> str:
    with pytest.raises(ERR_BD) as exc, conn.begin_nested():
        _resolucion(conn, emp, estado="vencida", **kw)
    return str(exc.value)


# ---------------------------------------------------------------- columnas generadas --------------------------
def test_columnas_generadas(conn):
    ent = f.entorno_pos(conn)
    prod = f.producto(conn)
    f.insertar(
        conn,
        "inventario.existencias",
        con_id=False,
        con_nodo=False,
        bodega_id=ent["bodega"],
        producto_id=prod,
        cantidad=D("10"),
        cantidad_reservada=D("3"),
        costo_promedio=D("5"),
    )
    assert uno(conn, "SELECT cantidad_disponible FROM inventario.existencias WHERE producto_id = :p", p=prod) == D(
        "7.000"
    )

    f.insertar(conn, "catalogo.productos_referencias", producto_id=prod, tipo="oem", referencia="04465-0k240")
    assert (
        uno(conn, "SELECT referencia_normalizada FROM catalogo.productos_referencias WHERE producto_id = :p", p=prod)
        == "044650K240"
    )


def test_anios_de_version_de_vehiculo(conn):
    marca = f.insertar(conn, "catalogo.vehiculos_marcas", nombre="Toyota", slug="toyota")
    modelo = f.insertar(conn, "catalogo.vehiculos_modelos", marca_id=marca, nombre="Hilux", slug="hilux")
    ver = f.insertar(
        conn, "catalogo.vehiculos_versiones", modelo_id=modelo, nombre="2.4 4x4", anio_desde=2016, anio_hasta=2020
    )
    assert uno(conn, "SELECT 2018 <@ anios FROM catalogo.vehiculos_versiones WHERE id = :i", i=ver) is True
    assert uno(conn, "SELECT 2021 <@ anios FROM catalogo.vehiculos_versiones WHERE id = :i", i=ver) is False


# ---------------------------------------------------------------- numeración ----------------------------------
def test_numero_interno_por_caja_sin_huecos(conn):
    ent = f.entorno_pos(conn)
    otra = f.caja(conn, ent["sede"], ent["bodega"])

    def n(c):
        return uno(conn, "SELECT cajas.siguiente_numero_interno(:c)", c=c)

    assert [n(ent["caja"]), n(ent["caja"]), n(otra), n(ent["caja"])] == [1, 2, 1, 3]
    assert "no existe" in falla(conn, "SELECT cajas.siguiente_numero_interno(gen_random_uuid())")


def test_consecutivo_modo_local(conn):
    emp = f.empresa(conn)
    res = _resolucion(
        conn,
        emp,
        prefijo="LOC",
        rango_desde=1,
        rango_hasta=2,
        modo_numeracion="local",
        id_rango_proveedor=None,
        nodo_propietario_id=f.NODO_NUBE,
    )

    def sig(nodo):
        return conn.execute(text("SELECT * FROM fiscal.siguiente_consecutivo(:r, :n)"), {"r": res, "n": nodo}).one()

    assert tuple(sig(f.NODO_NUBE)) == (1, "LOC")
    assert tuple(sig(f.NODO_NUBE)) == (2, "LOC")
    with pytest.raises(ERR_BD), conn.begin_nested():
        sig(f.NODO_NUBE)  # agotada
    with pytest.raises(ERR_BD), conn.begin_nested():
        sig(f.IVA19)  # nodo que no es el propietario


# ---------------------------------------------------------------- documento fiscal ----------------------------
def _documento(conn, ent, res=None):
    res = res or _resolucion(conn, ent["empresa"], rango_desde=1, rango_hasta=100, id_rango_proveedor=7)
    venta = f.venta_borrador(conn, ent, total=D("119"))
    return f.insertar(
        conn,
        "fiscal.documentos_fiscales",
        empresa_id=ent["empresa"],
        sede_id=ent["sede"],
        tipo_documento_codigo="FE",
        resolucion_id=res,
        fecha_emision="2026-06-01T10:00:00-05:00",
        emisor_snapshot={"nit": "1"},
        adquirente_snapshot={"nombre": "X"},
        adquirente_numero_documento="222222222222",
        adquirente_nombre="Consumidor final",
        subtotal=D("100"),
        descuento_total=0,
        impuesto_total=D("19"),
        redondeo=0,
        total=D("119"),
        hash_contenido="abc",
        venta_id=venta,
        estado="borrador",
    )


def test_documento_fiscal_contenido_inmutable_transporte_mutable(conn):
    ent = f.entorno_pos(conn)
    doc = _documento(conn, ent)
    # en borrador todo es editable
    conn.execute(
        text("UPDATE fiscal.documentos_fiscales SET total = 120, impuesto_total = 20 WHERE id = :i"), {"i": doc}
    )
    conn.execute(
        text(
            "UPDATE fiscal.documentos_fiscales SET total = 119, impuesto_total = 19, "
            "estado = 'pendiente_envio' WHERE id = :i"
        ),
        {"i": doc},
    )
    # transporte: el proveedor responde con el número (una sola vez)
    conn.execute(
        text(
            "UPDATE fiscal.documentos_fiscales SET prefijo = 'SETP', consecutivo = 981, estado = 'enviado', "
            "intentos = 1 WHERE id = :i"
        ),
        {"i": doc},
    )
    assert uno(conn, "SELECT numero_completo FROM fiscal.documentos_fiscales WHERE id = :i", i=doc) == "SETP981"
    assert "inmutable" in falla(conn, "UPDATE fiscal.documentos_fiscales SET total = 1 WHERE id = :i", i=doc)
    assert "ya fue asignado" in falla(
        conn, "UPDATE fiscal.documentos_fiscales SET consecutivo = 982 WHERE id = :i", i=doc
    )
    assert "no se borran" in falla(conn, "DELETE FROM fiscal.documentos_fiscales WHERE id = :i", i=doc)


# ---------------------------------------------------------------- búsqueda de productos ------------------------
def _busca(conn, prod, config, q):
    return uno(
        conn,
        "SELECT count(*) FROM catalogo.productos_busqueda WHERE producto_id = :i "
        f"AND documento @@ websearch_to_tsquery('{config}', public.f_unaccent(:q))",
        i=prod,
        q=q,
    )


def test_busqueda_de_productos(conn):
    prod = f.producto(conn, nombre="Pastillas de freno delanteras")
    f.insertar(conn, "catalogo.productos_referencias", producto_id=prod, tipo="oem", referencia="04465-0K240")
    assert _busca(conn, prod, "spanish", "freno") == 1  # raíces
    assert _busca(conn, prod, "simple", "delanteras freno") == 1
    assert _busca(conn, prod, "simple", "044650K240") == 1  # la referencia entra al documento
    assert _busca(conn, prod, "simple", "amortiguador") == 0
    assert (
        uno(conn, "SELECT texto FROM catalogo.productos_busqueda WHERE producto_id = :i", i=prod)
        == "pastillas de freno delanteras"
    )
    # búsqueda difusa (pg_trgm) tolera errores de digitación
    assert (
        uno(
            conn,
            "SELECT count(*) FROM catalogo.productos_busqueda WHERE producto_id = :i AND texto % 'pastilas de frenno'",
            i=prod,
        )
        == 1
    )


def test_busqueda_sin_tildes(conn):
    prod = f.producto(conn, nombre="Bomba de dirección hidráulica", descripcion="Sistema hidráulico")
    assert _busca(conn, prod, "spanish", "hidraulica") == 1


def test_recalcular_busqueda_no_toca_version_ni_updated_at_de_productos(conn):
    marca = f.insertar(conn, "catalogo.marcas", nombre="Bosch", slug=f"bosch-{f.n()}")
    prod = f.producto(conn, nombre="Bujía", marca_id=marca)
    antes = conn.execute(text("SELECT version, updated_at FROM catalogo.productos WHERE id = :i"), {"i": prod}).one()
    assert _busca(conn, prod, "simple", "bosch") == 1
    # renombrar la marca y agregar/borrar referencias recalcula la búsqueda...
    conn.execute(text("UPDATE catalogo.marcas SET nombre = 'Denso' WHERE id = :i"), {"i": marca})
    ref = f.insertar(conn, "catalogo.productos_referencias", producto_id=prod, tipo="oem", referencia="ZX-99")
    assert _busca(conn, prod, "simple", "denso") == 1 and _busca(conn, prod, "simple", "bosch") == 0
    assert _busca(conn, prod, "simple", "ZX99") == 1
    conn.execute(text("DELETE FROM catalogo.productos_referencias WHERE id = :i"), {"i": ref})
    assert _busca(conn, prod, "simple", "ZX99") == 0
    # ...sin modificar la fila de productos
    despues = conn.execute(text("SELECT version, updated_at FROM catalogo.productos WHERE id = :i"), {"i": prod}).one()
    assert tuple(despues) == tuple(antes)


def test_numero_fiscal_nulo_hasta_la_respuesta_y_unico_despues(conn):
    ent = f.entorno_pos(conn)
    res = _resolucion(conn, ent["empresa"], rango_desde=1, rango_hasta=100, id_rango_proveedor=7)
    d1 = _documento(conn, ent, res)
    d2 = _documento(conn, ent, res)
    nulos = uno(
        conn,
        "SELECT count(*) FROM fiscal.documentos_fiscales WHERE id IN (:a, :b) AND prefijo IS NULL "
        "AND consecutivo IS NULL AND numero_completo IS NULL",
        a=d1,
        b=d2,
    )
    assert nulos == 2  # varios documentos sin número conviven (índice parcial)
    assert "numero_par" in falla(conn, "UPDATE fiscal.documentos_fiscales SET prefijo = 'SETP' WHERE id = :i", i=d1)
    asignar = "UPDATE fiscal.documentos_fiscales SET prefijo = 'SETP', consecutivo = 5 WHERE id = :i"
    conn.execute(text(asignar), {"i": d1})
    assert "uq_documentos_fiscales_numero" in falla(conn, asignar, i=d2)
