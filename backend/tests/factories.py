"""Fábricas mínimas: insertan filas válidas por SQL directo (sin ORM) para probar las reglas de la BD."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from itertools import count

from sqlalchemy import text

from app.core.base import uuid7

NODO_NUBE = "00000000-0000-7000-8000-000000000001"
TERCERO_CONSUMIDOR_FINAL = "00000000-0000-7000-8000-000000000002"
LISTA_GENERAL = "00000000-0000-7000-8000-000000000003"
IVA19 = "00000000-0000-7000-8000-000000000011"

_n = count(1)


def n() -> int:
    return next(_n)


def insertar(conn, tabla: str, *, con_id: bool = True, con_nodo: bool = True, **v) -> str | None:
    """INSERT genérico. Dict/list -> jsonb. Devuelve el id (str) cuando la tabla tiene `id`."""
    datos = dict(v)
    if con_id and "id" not in datos:
        datos["id"] = str(uuid7())
    if con_nodo and "nodo_origen_id" not in datos:
        datos["nodo_origen_id"] = NODO_NUBE
    cols, vals, params = [], [], {}
    for k, x in datos.items():
        cols.append(k)
        if isinstance(x, (dict, list)):
            vals.append(f"CAST(:{k} AS jsonb)")
            params[k] = json.dumps(x)
        else:
            vals.append(f":{k}")
            params[k] = str(x) if hasattr(x, "hex") and not isinstance(x, (str, bytes)) else x
    conn.execute(text(f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join(vals)})"), params)
    return datos.get("id")


def empresa(conn) -> str:
    return insertar(
        conn,
        "organizacion.empresas",
        nit=f"9{n():08d}",
        dv=1,
        razon_social="Repuestos SAS",
        tipo_persona_codigo="1",
        regimen_codigo="48",
        municipio_codigo="11001",
        direccion="Cll 1 # 2-3",
    )


def sede(conn, empresa_id: str | None = None) -> str:
    return insertar(
        conn,
        "organizacion.sedes",
        empresa_id=empresa_id or empresa(conn),
        codigo=f"S{n()}",
        nombre="Principal",
        municipio_codigo="11001",
        direccion="Cll 1 # 2-3",
    )


def bodega(conn, sede_id: str) -> str:
    return insertar(conn, "inventario.bodegas", sede_id=sede_id, codigo=f"B{n()}", nombre="Bodega")


def caja(conn, sede_id: str, bodega_id: str) -> str:
    return insertar(conn, "cajas.cajas", sede_id=sede_id, codigo=f"C{n()}", nombre="Caja", bodega_id=bodega_id)


def empleado(conn) -> str:
    return insertar(
        conn,
        "identidad.empleados",
        tipo_documento_codigo="13",
        numero_documento=f"{n():010d}",
        nombres="Ana",
        apellidos="Pérez",
        usuario=f"ana{n()}",
    )


def turno(conn, caja_id: str, empleado_id: str) -> str:
    return insertar(conn, "cajas.turnos", caja_id=caja_id, abierto_por_id=empleado_id, base_efectivo=Decimal("50000"))


def entorno_pos(conn) -> dict:
    """empresa -> sede -> bodega -> caja -> empleado -> turno abierto."""
    e = empresa(conn)
    s = sede(conn, e)
    b = bodega(conn, s)
    c = caja(conn, s, b)
    emp = empleado(conn)
    t = turno(conn, c, emp)
    return dict(empresa=e, sede=s, bodega=b, caja=c, empleado=emp, turno=t)


def categoria(conn) -> str:
    return insertar(conn, "catalogo.categorias", nombre=f"Cat {n()}", slug=f"cat-{n()}")


def producto(conn, nombre: str = "Filtro de aceite", **extra) -> str:
    return insertar(
        conn,
        "catalogo.productos",
        sku=f"SKU{n():05d}",
        nombre=nombre,
        categoria_id=categoria(conn),
        impuesto_id=IVA19,
        **extra,
    )


def venta_borrador(conn, ent: dict, total: Decimal = Decimal("0")) -> str:
    return insertar(
        conn,
        "ventas.ventas",
        canal="pos",
        sede_id=ent["sede"],
        caja_id=ent["caja"],
        turno_id=ent["turno"],
        tercero_id=TERCERO_CONSUMIDOR_FINAL,
        subtotal=total,
        descuento_total=0,
        impuesto_total=0,
        redondeo=0,
        total=total,
    )


def venta_item(conn, venta_id: str, bodega_id: str, producto_id: str, linea: int = 1) -> str:
    return insertar(
        conn,
        "ventas.ventas_items",
        venta_id=venta_id,
        linea=linea,
        producto_id=producto_id,
        bodega_id=bodega_id,
        sku="X",
        descripcion="Item",
        unidad_codigo="94",
        cantidad=1,
        precio_lista=119,
        precio_unitario=119,
        precio_unitario_base=100,
        impuesto_codigo="IVA19",
        tributo_codigo="01",
        tarifa_pct=19,
        bruto_linea=119,
        total_linea=119,
        base_gravable=100,
        impuesto_valor=19,
        costo_unitario=50,
    )


def hoy() -> date:
    return date.today()
