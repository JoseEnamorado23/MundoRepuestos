"""Schema `ventas`: ventas, pagos, devoluciones (§10). Congeladas por trigger al confirmar (migración 0003).

El crédito (`valor_credito`, `fecha_vencimiento`) llega con el módulo `cartera` en la Fase 3.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import CANTIDAD, DINERO, PCT, PRECIO, Base, Mutable, pg_enum
from app.core.helpers import fk, fkt, flag, ts, txt

SCHEMA = "ventas"
CanalVenta = pg_enum(SCHEMA, "canal_venta", "pos", "web")
EstadoVenta = pg_enum(SCHEMA, "estado_venta", "borrador", "confirmada", "descartada")
CanalPago = pg_enum(SCHEMA, "canal_pago", "manual", "datafono", "qr", "pasarela")
EstadoDevolucion = pg_enum(SCHEMA, "estado_devolucion", "borrador", "confirmada")
TipoResolucion = pg_enum(SCHEMA, "tipo_resolucion", "nota_credito", "nota_ajuste")


class Venta(Base, Mutable):
    __tablename__ = "ventas"
    __table_args__ = (
        CheckConstraint("total = subtotal + impuesto_total + redondeo", name="total"),
        CheckConstraint("canal <> 'pos' OR (caja_id IS NOT NULL AND turno_id IS NOT NULL)", name="canal_pos"),
        CheckConstraint("canal <> 'web' OR (caja_id IS NULL AND turno_id IS NULL)", name="canal_web"),
        CheckConstraint(
            "estado <> 'confirmada' OR (confirmada_at IS NOT NULL AND (canal = 'web' OR numero_interno IS NOT NULL))",
            name="confirmada",
        ),
        CheckConstraint("subtotal >= 0 AND descuento_total >= 0 AND impuesto_total >= 0", name="montos_no_negativos"),
        CheckConstraint("tipo_documento_fiscal_codigo IN ('FE','POS_E')", name="tipo_documento"),
        Index(
            "uq_ventas_numero_interno",
            "caja_id",
            "numero_interno",
            unique=True,
            postgresql_where=text("numero_interno IS NOT NULL"),
        ),
        Index("ix_ventas_turno", "turno_id", postgresql_where=text("turno_id IS NOT NULL")),
        Index(
            "ix_ventas_sede_fecha",
            "sede_id",
            text("confirmada_at DESC"),
            postgresql_where=text("estado = 'confirmada'"),
        ),
        Index("ix_ventas_tercero_fecha", "tercero_id", text("confirmada_at DESC")),
        Index("ix_ventas_borradores", "caja_id", postgresql_where=text("estado = 'borrador'")),
        Index(
            "ix_ventas_vendedor",
            "vendedor_id",
            text("confirmada_at DESC"),
            postgresql_where=text("vendedor_id IS NOT NULL"),
        ),
        Index("ix_ventas_placa", "placa_vehiculo", postgresql_where=text("placa_vehiculo IS NOT NULL")),
        {"schema": SCHEMA},
    )
    canal: Mapped[str] = mapped_column(CanalVenta, nullable=False)
    sede_id: Mapped[uuid.UUID] = fk("organizacion.sedes.id")
    caja_id: Mapped[uuid.UUID | None] = fk("cajas.cajas.id", null=True)
    turno_id: Mapped[uuid.UUID | None] = fk("cajas.turnos.id", null=True)
    vendedor_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)
    tercero_id: Mapped[uuid.UUID] = fk("identidad.terceros.id")
    estado: Mapped[str] = mapped_column(EstadoVenta, nullable=False, server_default="borrador")
    tipo_documento_fiscal_codigo: Mapped[str] = fkt("referencia.tipos_documento_fiscal.codigo", server_default="FE")
    forma_pago_codigo: Mapped[str] = fkt("referencia.formas_pago.codigo", server_default="1")
    lista_precio_id: Mapped[uuid.UUID | None] = fk("catalogo.listas_precios.id", null=True)
    numero_interno: Mapped[int | None] = mapped_column(BigInteger)
    subtotal = mapped_column(DINERO(), nullable=False, server_default="0")
    descuento_total = mapped_column(DINERO(), nullable=False, server_default="0")
    impuesto_total = mapped_column(DINERO(), nullable=False, server_default="0")
    redondeo = mapped_column(DINERO(), nullable=False, server_default="0")
    total = mapped_column(DINERO(), nullable=False, server_default="0")
    moneda: Mapped[str] = txt(server_default="COP")
    placa_vehiculo: Mapped[str | None] = txt(null=True)
    confirmada_at: Mapped[datetime | None] = ts()
    notas: Mapped[str | None] = txt(null=True)


class VentaItem(Base, Mutable):
    __tablename__ = "ventas_items"
    __table_args__ = (
        UniqueConstraint("venta_id", "linea", name="uq_ventas_items_venta_linea"),
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("descuento_pct BETWEEN 0 AND 100", name="descuento_rango"),
        CheckConstraint("base_gravable + impuesto_valor = total_linea", name="base_mas_impuesto"),
        CheckConstraint("total_linea = bruto_linea - descuento_valor", name="total_linea"),
        CheckConstraint("bruto_linea = round(cantidad * precio_unitario, 2)", name="bruto_linea"),
        Index("ix_ventas_items_producto", "producto_id", "venta_id"),
        {"schema": SCHEMA},
    )
    venta_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.ventas.id")
    linea: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    producto_id: Mapped[uuid.UUID] = fk("catalogo.productos.id")
    bodega_id: Mapped[uuid.UUID] = fk("inventario.bodegas.id")
    sku: Mapped[str] = txt()
    descripcion: Mapped[str] = txt()
    unidad_codigo: Mapped[str] = txt()
    cantidad = mapped_column(CANTIDAD(), nullable=False)
    precio_lista = mapped_column(PRECIO(), nullable=False)
    precio_unitario = mapped_column(PRECIO(), nullable=False)
    precio_unitario_base = mapped_column(PRECIO(), nullable=False)
    descuento_pct = mapped_column(PCT(), nullable=False, server_default="0")
    descuento_valor = mapped_column(DINERO(), nullable=False, server_default="0")
    impuesto_codigo: Mapped[str] = txt()
    tributo_codigo: Mapped[str] = txt()
    tarifa_pct = mapped_column(PCT(), nullable=False)
    bruto_linea = mapped_column(DINERO(), nullable=False)
    total_linea = mapped_column(DINERO(), nullable=False)
    base_gravable = mapped_column(DINERO(), nullable=False)
    impuesto_valor = mapped_column(DINERO(), nullable=False)
    costo_unitario = mapped_column(PRECIO(), nullable=False)
    costo_estimado: Mapped[bool] = flag(False)
    autorizacion_id: Mapped[uuid.UUID | None] = fk("identidad.autorizaciones.id", null=True)


class VentaPago(Base, Mutable):
    __tablename__ = "ventas_pagos"
    __table_args__ = (
        CheckConstraint("valor > 0", name="valor_positivo"),
        CheckConstraint("cambio_devuelto >= 0", name="cambio_no_negativo"),
        CheckConstraint("valor_recibido IS NULL OR valor_recibido - cambio_devuelto = valor", name="recibido_cuadra"),
        CheckConstraint("ultimos_digitos IS NULL OR ultimos_digitos ~ '^[0-9]{4}$'", name="ultimos_digitos"),
        Index("ix_ventas_pagos_venta_id", "venta_id"),
        Index("ix_ventas_pagos_medio_fecha", "medio_pago_codigo", "created_at"),
        {"schema": SCHEMA},
    )
    venta_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.ventas.id")
    medio_pago_codigo: Mapped[str] = fkt("referencia.medios_pago.codigo")
    valor = mapped_column(DINERO(), nullable=False)
    valor_recibido = mapped_column(DINERO())
    cambio_devuelto = mapped_column(DINERO(), nullable=False, server_default="0")
    canal_pago: Mapped[str] = mapped_column(CanalPago, nullable=False, server_default="manual")
    referencia: Mapped[str | None] = txt(null=True)
    terminal: Mapped[str | None] = txt(null=True)
    ultimos_digitos: Mapped[str | None] = txt(null=True)
    franquicia: Mapped[str | None] = txt(null=True)


class MotivoDevolucion(Base, Mutable):
    __tablename__ = "motivos_devolucion"
    __table_args__ = (UniqueConstraint("codigo", name="uq_motivos_devolucion_codigo"), {"schema": SCHEMA})
    codigo: Mapped[str] = txt()
    nombre: Mapped[str] = txt()
    reintegra_stock_por_defecto: Mapped[bool] = flag(True)
    requiere_autorizacion: Mapped[bool] = flag(True)
    activo: Mapped[bool] = flag(True)


class Devolucion(Base, Mutable):
    __tablename__ = "devoluciones"
    __table_args__ = (
        CheckConstraint("total = subtotal + impuesto_total + redondeo", name="total"),
        CheckConstraint("estado <> 'confirmada' OR confirmada_at IS NOT NULL", name="confirmada"),
        Index("ix_devoluciones_venta_id", "venta_id"),
        Index("ix_devoluciones_turno", "turno_id", postgresql_where=text("turno_id IS NOT NULL")),
        Index(
            "ix_devoluciones_sede_fecha",
            "sede_id",
            text("confirmada_at DESC"),
            postgresql_where=text("estado = 'confirmada'"),
        ),
        {"schema": SCHEMA},
    )
    venta_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.ventas.id")
    sede_id: Mapped[uuid.UUID] = fk("organizacion.sedes.id")
    turno_id: Mapped[uuid.UUID | None] = fk("cajas.turnos.id", null=True)
    motivo_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.motivos_devolucion.id")
    estado: Mapped[str] = mapped_column(EstadoDevolucion, nullable=False, server_default="borrador")
    tipo_resolucion: Mapped[str] = mapped_column(TipoResolucion, nullable=False)
    subtotal = mapped_column(DINERO(), nullable=False, server_default="0")
    impuesto_total = mapped_column(DINERO(), nullable=False, server_default="0")
    redondeo = mapped_column(DINERO(), nullable=False, server_default="0")
    total = mapped_column(DINERO(), nullable=False, server_default="0")
    autorizacion_id: Mapped[uuid.UUID | None] = fk("identidad.autorizaciones.id", null=True)
    observaciones: Mapped[str | None] = txt(null=True)
    confirmada_at: Mapped[datetime | None] = ts()


class DevolucionItem(Base, Mutable):
    __tablename__ = "devoluciones_items"
    __table_args__ = (
        UniqueConstraint("devolucion_id", "venta_item_id", name="uq_devoluciones_items_devolucion_item"),
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("base_gravable + impuesto_valor = total_linea", name="base_mas_impuesto"),
        CheckConstraint("reintegra_stock = (bodega_reintegro_id IS NOT NULL)", name="reintegro_bodega"),
        Index("ix_devoluciones_items_venta_item", "venta_item_id"),
        {"schema": SCHEMA},
    )
    devolucion_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.devoluciones.id")
    venta_item_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.ventas_items.id")
    producto_id: Mapped[uuid.UUID] = fk("catalogo.productos.id")
    cantidad = mapped_column(CANTIDAD(), nullable=False)
    precio_unitario = mapped_column(PRECIO(), nullable=False)
    tarifa_pct = mapped_column(PCT(), nullable=False)
    descuento_valor = mapped_column(DINERO(), nullable=False, server_default="0")
    total_linea = mapped_column(DINERO(), nullable=False)
    base_gravable = mapped_column(DINERO(), nullable=False)
    impuesto_valor = mapped_column(DINERO(), nullable=False)
    costo_unitario = mapped_column(PRECIO(), nullable=False)
    reintegra_stock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    bodega_reintegro_id: Mapped[uuid.UUID | None] = fk("inventario.bodegas.id", null=True)


class DevolucionPago(Base, Mutable):
    __tablename__ = "devoluciones_pagos"
    __table_args__ = (
        CheckConstraint("valor > 0", name="valor_positivo"),
        Index("ix_devoluciones_pagos_devolucion_id", "devolucion_id"),
        {"schema": SCHEMA},
    )
    devolucion_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.devoluciones.id")
    medio_pago_codigo: Mapped[str] = fkt("referencia.medios_pago.codigo")
    valor = mapped_column(DINERO(), nullable=False)
    referencia: Mapped[str | None] = txt(null=True)
