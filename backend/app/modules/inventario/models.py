"""Schema `inventario` (Fase 1): bodegas, ubicaciones, kardex, existencias, reservas y alertas (§7).

Traslados, conteos y ajustes llegan en la Fase 2; el kardex ya admite sus tipos (origen polimórfico, sin FK).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import (
    CANTIDAD,
    DINERO,
    PRECIO,
    AuditoriaCreacion,
    Base,
    CreatedAt,
    Mutable,
    NodoOrigen,
    SoloAgregar,
    UUIDv7PK,
    pg_enum,
)
from app.core.helpers import fk, flag, ts, txt

SCHEMA = "inventario"
TipoMovimiento = pg_enum(
    SCHEMA,
    "tipo_movimiento",
    "saldo_inicial",
    "entrada_compra",
    "devolucion_proveedor",
    "venta",
    "devolucion_venta",
    "ajuste_positivo",
    "ajuste_negativo",
    "traslado_salida",
    "traslado_entrada",
)
OrigenMovimiento = pg_enum(
    SCHEMA,
    "origen_movimiento",
    "saldo_inicial",
    "recepcion",
    "devolucion_proveedor",
    "venta",
    "devolucion_venta",
    "traslado",
    "ajuste",
)
EstadoReserva = pg_enum(SCHEMA, "estado_reserva", "activa", "consumida", "liberada", "expirada")
TipoAlertaStock = pg_enum(SCHEMA, "tipo_alerta_stock", "stock_negativo", "bajo_minimo", "reserva_sin_stock")
EstadoAlerta = pg_enum(SCHEMA, "estado_alerta", "abierta", "reconocida", "resuelta")


class Bodega(Base, Mutable):
    __tablename__ = "bodegas"
    __table_args__ = (
        UniqueConstraint("sede_id", "codigo", name="uq_bodegas_sede_codigo"),
        CheckConstraint("tipo IN ('general','averias')", name="tipo_valido"),
        CheckConstraint("tipo <> 'averias' OR NOT es_vendible", name="averias_no_vendible"),
        # una sola bodega de averías activa por sede (destino de las devoluciones defectuosas; 0009)
        Index("uq_bodegas_averias_sede", "sede_id", unique=True, postgresql_where=text("tipo = 'averias' AND activo")),
        {"schema": SCHEMA},
    )
    sede_id: Mapped[uuid.UUID] = fk("organizacion.sedes.id")
    codigo: Mapped[str] = txt()
    nombre: Mapped[str] = txt()
    tipo: Mapped[str] = txt(server_default="general")  # 'general' | 'averias' (no vendible)
    es_vendible: Mapped[bool] = flag(True)
    activo: Mapped[bool] = flag(True)


class Ubicacion(Base, Mutable):
    __tablename__ = "ubicaciones"
    __table_args__ = (UniqueConstraint("bodega_id", "codigo", name="uq_ubicaciones_bodega_codigo"), {"schema": SCHEMA})
    bodega_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.bodegas.id")
    codigo: Mapped[str] = txt()
    pasillo: Mapped[str] = txt()
    estante: Mapped[str | None] = txt(null=True)
    nivel: Mapped[str | None] = txt(null=True)
    descripcion: Mapped[str | None] = txt(null=True)
    activo: Mapped[bool] = flag(True)


class ProductoUbicacion(Base):
    __tablename__ = "productos_ubicaciones"
    __table_args__ = (Index("ix_productos_ubicaciones_ubicacion_id", "ubicacion_id"), {"schema": SCHEMA})
    producto_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalogo.productos.id", ondelete="RESTRICT"), primary_key=True
    )
    ubicacion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.ubicaciones.id", ondelete="RESTRICT"), primary_key=True
    )
    es_principal: Mapped[bool] = flag(False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MovimientoInventario(Base, SoloAgregar):
    """EL KARDEX. Solo INSERT (trigger tg_inmutable). Idempotente por (origen, línea, tipo, bodega)."""

    __tablename__ = "movimientos_inventario"
    __table_args__ = (
        UniqueConstraint("bodega_id", "producto_id", "secuencia", name="uq_movimientos_inventario_secuencia"),
        UniqueConstraint(
            "origen_tipo", "origen_linea_id", "tipo", "bodega_id", name="uq_movimientos_inventario_idempotencia"
        ),
        CheckConstraint(
            "(tipo IN ('saldo_inicial','entrada_compra','devolucion_venta','ajuste_positivo','traslado_entrada') "
            "AND cantidad > 0) OR "
            "(tipo IN ('devolucion_proveedor','venta','ajuste_negativo','traslado_salida') AND cantidad < 0)",
            name="cantidad_signo",
        ),
        CheckConstraint(
            "(tipo = 'saldo_inicial' AND origen_tipo = 'saldo_inicial') OR "
            "(tipo = 'entrada_compra' AND origen_tipo = 'recepcion') OR "
            "(tipo = 'devolucion_proveedor' AND origen_tipo = 'devolucion_proveedor') OR "
            "(tipo = 'venta' AND origen_tipo = 'venta') OR "
            "(tipo = 'devolucion_venta' AND origen_tipo = 'devolucion_venta') OR "
            "(tipo IN ('traslado_salida','traslado_entrada') AND origen_tipo = 'traslado') OR "
            "(tipo IN ('ajuste_positivo','ajuste_negativo') AND origen_tipo = 'ajuste')",
            name="origen_coherente",
        ),
        CheckConstraint("costo_unitario >= 0", name="costo_no_negativo"),
        Index("ix_movimientos_inventario_kardex", "producto_id", "bodega_id", text("ocurrido_at DESC")),
        Index("ix_movimientos_inventario_origen", "origen_tipo", "origen_id"),
        {"schema": SCHEMA},  # BRIN sobre ocurrido_at: migración 0003
    )
    bodega_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.bodegas.id")
    producto_id: Mapped[uuid.UUID] = fk("catalogo.productos.id")
    secuencia: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tipo: Mapped[str] = mapped_column(TipoMovimiento, nullable=False)
    cantidad = mapped_column(CANTIDAD(), nullable=False)
    costo_unitario = mapped_column(PRECIO(), nullable=False)
    costo_estimado: Mapped[bool] = flag(False)
    saldo_cantidad = mapped_column(CANTIDAD(), nullable=False)
    costo_promedio_resultante = mapped_column(PRECIO(), nullable=False)
    origen_tipo: Mapped[str] = mapped_column(OrigenMovimiento, nullable=False)
    origen_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)  # polimórfico, sin FK (D-14)
    origen_linea_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ocurrido_at: Mapped[datetime] = ts(null=False)


class Existencia(Base):
    """Proyección del stock por (bodega, producto); recalculable desde el kardex. Puede ser negativa."""

    __tablename__ = "existencias"
    __table_args__ = (
        CheckConstraint("cantidad_reservada >= 0", name="reservada_no_negativa"),
        Index("ix_existencias_producto_id", "producto_id"),
        Index("ix_existencias_negativas", "bodega_id", postgresql_where=text("cantidad < 0")),
        {"schema": SCHEMA},
    )
    bodega_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.bodegas.id", ondelete="RESTRICT"), primary_key=True
    )
    producto_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalogo.productos.id", ondelete="RESTRICT"), primary_key=True
    )
    cantidad = mapped_column(CANTIDAD(), nullable=False, server_default="0")
    cantidad_reservada = mapped_column(CANTIDAD(), nullable=False, server_default="0")
    # GENERATED ALWAYS AS (cantidad - cantidad_reservada) STORED: migración 0003
    cantidad_disponible = mapped_column(CANTIDAD(), nullable=False, server_default=FetchedValue())
    costo_promedio = mapped_column(PRECIO(), nullable=False, server_default="0")
    ultimo_costo = mapped_column(PRECIO(), nullable=False, server_default="0")
    stock_minimo = mapped_column(CANTIDAD())
    ultima_secuencia: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")  # lo incrementa tg_tocar


class ReservaStock(Base, Mutable):
    __tablename__ = "reservas_stock"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("origen_tipo IN ('pedido','manual')", name="origen_tipo_valido"),
        Index(
            "uq_reservas_stock_linea",
            "origen_tipo",
            "origen_linea_id",
            unique=True,
            postgresql_where=text("estado = 'activa'"),
        ),
        Index("ix_reservas_stock_vencimiento", "expira_at", postgresql_where=text("estado = 'activa'")),
        Index("ix_reservas_stock_producto", "bodega_id", "producto_id", postgresql_where=text("estado = 'activa'")),
        Index("ix_reservas_stock_origen", "origen_tipo", "origen_id"),
        {"schema": SCHEMA},
    )
    bodega_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.bodegas.id")
    producto_id: Mapped[uuid.UUID] = fk("catalogo.productos.id")
    cantidad = mapped_column(CANTIDAD(), nullable=False)
    estado: Mapped[str] = mapped_column(EstadoReserva, nullable=False, server_default="activa")
    origen_tipo: Mapped[str] = txt(server_default="pedido")
    origen_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)  # polimórfico (el pedido está en Fase 3)
    origen_linea_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    expira_at: Mapped[datetime] = ts(null=False)
    cerrada_at: Mapped[datetime | None] = ts()
    movimiento_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.movimientos_inventario.id", null=True)


class AlertaStock(Base, Mutable):
    __tablename__ = "alertas_stock"
    __table_args__ = (
        Index(
            "uq_alertas_stock_abierta",
            "bodega_id",
            "producto_id",
            "tipo",
            unique=True,
            postgresql_where=text("estado <> 'resuelta'"),
        ),
        Index(
            "ix_alertas_stock_estado", "estado", text("created_at DESC"), postgresql_where=text("estado <> 'resuelta'")
        ),
        {"schema": SCHEMA},
    )
    tipo: Mapped[str] = mapped_column(TipoAlertaStock, nullable=False)
    bodega_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.bodegas.id")
    producto_id: Mapped[uuid.UUID] = fk("catalogo.productos.id")
    movimiento_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.movimientos_inventario.id", null=True)
    cantidad_resultante = mapped_column(CANTIDAD(), nullable=False)
    estado: Mapped[str] = mapped_column(EstadoAlerta, nullable=False, server_default="abierta")
    resuelta_at: Mapped[datetime | None] = ts()
    resuelta_por_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)


class Importacion(Base, CreatedAt, AuditoriaCreacion, NodoOrigen, UUIDv7PK):
    """Importación desde Excel en dos pasos (validar -> confirmar). Estado LOCAL del nodo: no se sincroniza.

    `datos` guarda las filas ya normalizadas por la validación; confirmar aplica exactamente eso (no relee el archivo).
    """

    __tablename__ = "importaciones"
    __table_args__ = (
        CheckConstraint("estado IN ('validada','confirmada','descartada')", name="estado_valido"),
        CheckConstraint("tipo IN ('productos','compatibilidades')", name="tipo_valido"),
        Index("ix_importaciones_estado", "estado", text("created_at DESC")),
        {
            "schema": SCHEMA,
            "comment": "LOCAL del nodo: no se sincroniza. Las no confirmadas se purgan con: app.cli importaciones limpiar --dias N.",
        },
    )
    tipo: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(Text, nullable=False, server_default="validada")
    nombre_archivo: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    resumen: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reporte: Mapped[list] = mapped_column(JSONB, nullable=False)
    datos: Mapped[list] = mapped_column(JSONB, nullable=False)
    confirmada_at: Mapped[datetime | None] = ts()


class EntradaMercancia(Base, SoloAgregar):
    """Entrada simple de mercancía (Etapa 1, sin órdenes de compra). Origen de los movimientos `entrada_compra`."""

    __tablename__ = "entradas_mercancia"
    __table_args__ = (
        CheckConstraint("total >= 0", name="total_no_negativo"),
        Index(
            "uq_entradas_mercancia_factura",
            "tercero_id",
            "numero_factura",
            unique=True,
            postgresql_where=text("tercero_id IS NOT NULL AND numero_factura IS NOT NULL"),
        ),
        Index("ix_entradas_mercancia_bodega", "bodega_id", text("ocurrido_at DESC")),
        {"schema": SCHEMA},
    )
    bodega_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.bodegas.id")
    tercero_id: Mapped[uuid.UUID | None] = fk("identidad.terceros.id", null=True)
    numero_factura: Mapped[str | None] = txt(null=True)
    observaciones: Mapped[str | None] = txt(null=True)
    total = mapped_column(DINERO(), nullable=False)
    ocurrido_at: Mapped[datetime] = ts(null=False, server_default=text("now()"))


class EntradaMercanciaLinea(Base, SoloAgregar):
    __tablename__ = "entradas_mercancia_lineas"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("costo_unitario >= 0", name="costo_no_negativo"),
        Index("ix_entradas_mercancia_lineas_entrada_id", "entrada_id"),
        {"schema": SCHEMA},
    )
    entrada_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.entradas_mercancia.id")
    producto_id: Mapped[uuid.UUID] = fk("catalogo.productos.id")
    cantidad = mapped_column(CANTIDAD(), nullable=False)
    costo_unitario = mapped_column(PRECIO(), nullable=False)


class SolicitudInventario(Base, Mutable):
    """Entrada o ajuste de backoffice que supera el umbral: queda `pendiente_aprobacion` y NO mueve el kardex.

    Al aprobarse (por un empleado DISTINTO con `inventario.aprobar`, salvo autoaprobación del propietario permitida por
    la sede) se generan los movimientos en la misma transacción; al rechazarse no se mueve nada. Se conserva siempre.
    """

    __tablename__ = "solicitudes_inventario"
    __table_args__ = (
        CheckConstraint("tipo IN ('entrada','ajuste')", name="tipo_valido"),
        CheckConstraint("estado IN ('pendiente_aprobacion','aprobada','rechazada')", name="estado_valido"),
        CheckConstraint("valor >= 0 AND umbral >= 0", name="valores_no_negativos"),
        CheckConstraint("(estado = 'pendiente_aprobacion') = (resuelta_por_id IS NULL)", name="resolucion_coherente"),
        CheckConstraint("(resuelta_por_id IS NULL) = (resuelta_at IS NULL)", name="resolucion_con_fecha"),
        CheckConstraint("estado <> 'rechazada' OR motivo_resolucion IS NOT NULL", name="rechazo_con_motivo"),
        CheckConstraint("NOT autoaprobado OR estado = 'aprobada'", name="autoaprobado_solo_aprobada"),
        # segregación de funciones: quien resuelve es otro, salvo autoaprobación explícita y auditada
        CheckConstraint(
            "resuelta_por_id IS NULL OR resuelta_por_id <> solicitada_por_id OR autoaprobado",
            name="segregacion_funciones",
        ),
        Index("ix_solicitudes_inventario_estado", "estado", text("created_at DESC")),
        Index("ix_solicitudes_inventario_sede", "sede_id", "estado"),
        {"schema": SCHEMA},
    )
    tipo: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(Text, nullable=False, server_default="pendiente_aprobacion")
    sede_id: Mapped[uuid.UUID] = fk("organizacion.sedes.id")
    bodega_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.bodegas.id")
    valor = mapped_column(DINERO(), nullable=False)
    umbral = mapped_column(DINERO(), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    motivo: Mapped[str | None] = mapped_column(Text)
    solicitada_por_id: Mapped[uuid.UUID] = fk("identidad.empleados.id")
    resuelta_por_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)
    resuelta_at: Mapped[datetime | None] = ts()
    motivo_resolucion: Mapped[str | None] = mapped_column(Text)
    autoaprobado: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    resultado_tipo: Mapped[str | None] = mapped_column(Text)
    resultado_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
