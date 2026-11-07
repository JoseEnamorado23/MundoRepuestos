"""Schema `cajas`: cajas, periféricos, dispositivos, turnos, movimientos de caja y arqueos (§9)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    FetchedValue,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import DINERO, Base, Mutable, SoloAgregar, pg_enum
from app.core.helpers import fk, fkt, flag, ts, txt

SCHEMA = "cajas"
TipoPeriferico = pg_enum(
    SCHEMA,
    "tipo_periferico",
    "impresora_tiquetes",
    "impresora_etiquetas",
    "cajon_monedero",
    "lector_codigos",
    "datafono",
    "pantalla_cliente",
)
TipoConexion = pg_enum(SCHEMA, "tipo_conexion", "usb", "red", "serial", "bluetooth", "via_impresora")
TipoDispositivo = pg_enum(SCHEMA, "tipo_dispositivo", "pos", "bodega")
EstadoDispositivo = pg_enum(SCHEMA, "estado_dispositivo", "pendiente", "activo", "bloqueado", "revocado")
EstadoTurno = pg_enum(SCHEMA, "estado_turno", "abierto", "cerrado")
TipoMovimientoCaja = pg_enum(SCHEMA, "tipo_movimiento_caja", "ingreso", "retiro")


class Caja(Base, Mutable):
    __tablename__ = "cajas"
    __table_args__ = (UniqueConstraint("sede_id", "codigo", name="uq_cajas_sede_codigo"), {"schema": SCHEMA})
    sede_id: Mapped[uuid.UUID] = fk("organizacion.sedes.id")
    codigo: Mapped[str] = txt()
    nombre: Mapped[str] = txt()
    bodega_id: Mapped[uuid.UUID] = fk("inventario.bodegas.id")
    ultimo_numero_interno: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    activo: Mapped[bool] = flag(True)


class Periferico(Base, Mutable):
    __tablename__ = "perifericos"
    __table_args__ = (
        Index("ix_perifericos_caja_activos", "caja_id", postgresql_where=text("activo")),
        {"schema": SCHEMA},
    )
    caja_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.cajas.id")
    tipo: Mapped[str] = mapped_column(TipoPeriferico, nullable=False)
    nombre: Mapped[str] = txt()
    conexion: Mapped[str] = mapped_column(TipoConexion, nullable=False)
    parametros: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    activo: Mapped[bool] = flag(True)


class Dispositivo(Base, Mutable):
    __tablename__ = "dispositivos"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_dispositivos_token_hash"),
        CheckConstraint("tipo <> 'pos' OR caja_id IS NOT NULL", name="pos_requiere_caja"),
        Index(
            "uq_dispositivos_caja_activo",
            "caja_id",
            unique=True,
            postgresql_where=text("estado = 'activo' AND tipo = 'pos'"),
        ),
        Index("ix_dispositivos_sede", "sede_id", "estado"),
        {"schema": SCHEMA},
    )
    sede_id: Mapped[uuid.UUID] = fk("organizacion.sedes.id")
    caja_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.cajas.id", null=True)
    tipo: Mapped[str] = mapped_column(TipoDispositivo, nullable=False, server_default="pos")
    nombre: Mapped[str] = txt()
    token_hash: Mapped[str] = txt()
    estado: Mapped[str] = mapped_column(EstadoDispositivo, nullable=False, server_default="pendiente")
    ultimo_acceso_at: Mapped[datetime | None] = ts()
    ultima_ip: Mapped[str | None] = mapped_column(INET)
    version_cliente: Mapped[str | None] = txt(null=True)
    revocado_at: Mapped[datetime | None] = ts()


class Turno(Base, Mutable):
    __tablename__ = "turnos"
    __table_args__ = (
        CheckConstraint("base_efectivo >= 0", name="base_no_negativa"),
        CheckConstraint("efectivo_contado IS NULL OR efectivo_contado >= 0", name="contado_no_negativo"),
        CheckConstraint(
            "estado = 'abierto' OR (cerrado_at IS NOT NULL AND cerrado_por_id IS NOT NULL "
            "AND efectivo_esperado IS NOT NULL AND efectivo_contado IS NOT NULL)",
            name="cierre_completo",
        ),
        # 0010: la diferencia de arqueo ya no bloquea el cierre (política `diferencia_arqueo`, revisión posterior)
        CheckConstraint("NOT cierre_forzado OR motivo_cierre_forzado IS NOT NULL", name="forzado_con_motivo"),
        CheckConstraint(
            "supervisor_cierre_id IS NULL OR supervisor_cierre_id <> cerrado_por_id", name="supervisor_distinto"
        ),
        # un solo turno abierto por caja y por cajero
        Index("uq_turnos_abierto_por_caja", "caja_id", unique=True, postgresql_where=text("estado = 'abierto'")),
        Index(
            "uq_turnos_abierto_por_cajero", "abierto_por_id", unique=True, postgresql_where=text("estado = 'abierto'")
        ),
        Index("ix_turnos_caja_fecha", "caja_id", text("abierto_at DESC")),
        {"schema": SCHEMA},
    )
    caja_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.cajas.id")
    dispositivo_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.dispositivos.id", null=True)
    estado: Mapped[str] = mapped_column(EstadoTurno, nullable=False, server_default="abierto")
    abierto_por_id: Mapped[uuid.UUID] = fk("identidad.empleados.id")
    abierto_at: Mapped[datetime] = ts(null=False, server_default=text("now()"))
    base_efectivo = mapped_column(DINERO(), nullable=False)
    cerrado_por_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)
    supervisor_cierre_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)
    autorizacion_cierre_id: Mapped[uuid.UUID | None] = fk("identidad.autorizaciones.id", null=True)
    cerrado_at: Mapped[datetime | None] = ts()
    efectivo_esperado = mapped_column(DINERO())
    efectivo_contado = mapped_column(DINERO())
    # GENERATED ALWAYS AS (efectivo_contado - efectivo_esperado) STORED: migración 0003
    diferencia = mapped_column(DINERO(), server_default=FetchedValue())
    observaciones: Mapped[str | None] = txt(null=True)
    # tolerancia de diferencia vigente al cerrar (snapshot de configuracion_sede) y datos del cierre forzado (0009)
    umbral_diferencia = mapped_column(DINERO())
    cierre_forzado: Mapped[bool] = flag(False)
    motivo_cierre_forzado: Mapped[str | None] = txt(null=True)


class MotivoMovimientoCaja(Base, Mutable):
    __tablename__ = "motivos_movimiento_caja"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_motivos_movimiento_caja_codigo"),
        CheckConstraint("tipo IN ('ingreso','retiro','ambos')", name="tipo_valido"),
        {"schema": SCHEMA},
    )
    codigo: Mapped[str] = txt()
    nombre: Mapped[str] = txt()
    tipo: Mapped[str] = txt()
    requiere_autorizacion: Mapped[bool] = flag(False)
    activo: Mapped[bool] = flag(True)


class MovimientoCaja(Base, SoloAgregar):
    __tablename__ = "movimientos_caja"
    __table_args__ = (
        CheckConstraint("valor > 0", name="valor_positivo"),
        Index("ix_movimientos_caja_turno", "turno_id", "created_at"),
        {"schema": SCHEMA},
    )
    turno_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.turnos.id")
    tipo: Mapped[str] = mapped_column(TipoMovimientoCaja, nullable=False)
    valor = mapped_column(DINERO(), nullable=False)
    motivo_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.motivos_movimiento_caja.id")
    descripcion: Mapped[str | None] = txt(null=True)
    autorizacion_id: Mapped[uuid.UUID | None] = fk("identidad.autorizaciones.id", null=True)


class ArqueoTurno(Base, SoloAgregar):
    __tablename__ = "arqueos_turno"
    __table_args__ = (
        UniqueConstraint("turno_id", "medio_pago_codigo", name="uq_arqueos_turno_turno_medio"),
        {"schema": SCHEMA},
    )
    turno_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.turnos.id")
    medio_pago_codigo: Mapped[str] = fkt("referencia.medios_pago.codigo")
    valor_esperado = mapped_column(DINERO(), nullable=False)
    valor_contado = mapped_column(DINERO(), nullable=False)
    # GENERATED ALWAYS AS (valor_contado - valor_esperado) STORED: migración 0003
    diferencia = mapped_column(DINERO(), nullable=False, server_default=FetchedValue())
    observacion: Mapped[str | None] = txt(null=True)
