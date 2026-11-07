"""Consultas de inventario: existencias, kardex con saldo acumulado y productos bajo el mínimo."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, func, select

from app.modules.catalogo.models import Producto
from app.modules.inventario.models import Bodega, Existencia, MovimientoInventario


def existencias(
    *,
    sede_id: uuid.UUID | None,
    bodega_id: uuid.UUID | None,
    producto_id: uuid.UUID | None,
    q: str | None,
    solo_con_stock: bool,
) -> Select:
    """disponible = existencia - reservas (columna generada `cantidad_disponible`)."""
    stmt = (
        select(
            Existencia.bodega_id,
            Bodega.codigo.label("bodega_codigo"),
            Bodega.nombre.label("bodega_nombre"),
            Bodega.sede_id,
            Existencia.producto_id,
            Producto.sku,
            Producto.nombre.label("producto_nombre"),
            Existencia.cantidad,
            Existencia.cantidad_reservada,
            Existencia.cantidad_disponible,
            Existencia.costo_promedio,
            Existencia.ultimo_costo,
            func.coalesce(Existencia.stock_minimo, Producto.stock_minimo).label("stock_minimo"),
        )
        .join(Bodega, Bodega.id == Existencia.bodega_id)
        .join(Producto, Producto.id == Existencia.producto_id)
    )
    if sede_id:
        stmt = stmt.where(Bodega.sede_id == sede_id)
    if bodega_id:
        stmt = stmt.where(Existencia.bodega_id == bodega_id)
    if producto_id:
        stmt = stmt.where(Existencia.producto_id == producto_id)
    if q:
        patron = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(Producto.sku).like(patron) | func.lower(Producto.nombre).like(patron))
    if solo_con_stock:
        stmt = stmt.where(Existencia.cantidad_disponible > 0)
    return stmt


def kardex(
    producto_id: uuid.UUID, bodega_id: uuid.UUID | None, desde: datetime | None, hasta: datetime | None
) -> Select:
    """Kardex de un producto. `saldo_cantidad` es el saldo ACUMULADO de la bodega tras cada movimiento."""
    stmt = select(MovimientoInventario).where(MovimientoInventario.producto_id == producto_id)
    if bodega_id:
        stmt = stmt.where(MovimientoInventario.bodega_id == bodega_id)
    if desde:
        stmt = stmt.where(MovimientoInventario.ocurrido_at >= desde)
    if hasta:
        stmt = stmt.where(MovimientoInventario.ocurrido_at < hasta)
    return stmt


def bajo_minimo(sede_id: uuid.UUID | None, bodega_id: uuid.UUID | None) -> Select:
    """Productos activos e inventariables cuya existencia disponible está por debajo del mínimo (> 0)."""
    disponible = func.coalesce(func.sum(Existencia.cantidad_disponible), 0)
    on = Existencia.producto_id == Producto.id
    if bodega_id:
        on = on & (Existencia.bodega_id == bodega_id)
    elif sede_id:
        on = on & Existencia.bodega_id.in_(select(Bodega.id).where(Bodega.sede_id == sede_id, Bodega.activo.is_(True)))
    return (
        select(
            Producto.id.label("producto_id"),
            Producto.sku,
            Producto.nombre,
            Producto.stock_minimo,
            disponible.label("disponible"),
            (Producto.stock_minimo - disponible).label("faltante"),
        )
        .select_from(Producto)
        .outerjoin(Existencia, on)
        .where(Producto.activo.is_(True), Producto.es_inventariable.is_(True), Producto.stock_minimo > 0)
        .group_by(Producto.id)
        .having(disponible < Producto.stock_minimo)
    )
