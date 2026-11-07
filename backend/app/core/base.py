"""Base declarativa, convención de nombres y mixins (modelo.md §1.3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, MetaData, Numeric, Uuid, func
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.core.config import NODO_NUBE_ID, get_settings

try:  # Python 3.14+
    from uuid import uuid7 as _uuid7  # type: ignore[attr-defined]
except ImportError:  # Python 3.12/3.13: librería mantenida (Rust)
    from uuid_utils.compat import uuid7 as _uuid7


def uuid7() -> uuid.UUID:
    """UUIDv7 (ordenado por tiempo) generado por la aplicación; la BD no tiene default."""
    return _uuid7()


# --- nombres estables de constraints (para Alembic) ---------------------------------------
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --- tipos de dato según las convenciones --------------------------------------------------
def DINERO() -> Numeric:  # totales: NUMERIC(18,2)
    return Numeric(18, 2)


def PRECIO() -> Numeric:  # precios y costos unitarios: NUMERIC(18,4)
    return Numeric(18, 4)


def CANTIDAD() -> Numeric:  # cantidades: NUMERIC(14,3)
    return Numeric(14, 3)


def PCT() -> Numeric:  # tarifas y porcentajes: NUMERIC(7,4)
    return Numeric(7, 4)


# --- ENUMs de PostgreSQL --------------------------------------------------------------------
# Se declaran con create_type=False: los tipos se crean explícitamente en la migración 0002, así
# un mismo ENUM puede usarse en varias tablas sin intentar crearse dos veces.
ENUMS: dict[tuple[str, str], tuple[str, ...]] = {}


def pg_enum(schema: str, name: str, *valores: str) -> PgEnum:
    previo = ENUMS.get((schema, name))
    if previo is not None and previo != valores:
        raise ValueError(f"ENUM {schema}.{name} definido dos veces con valores distintos")
    ENUMS[(schema, name)] = valores
    return PgEnum(*valores, name=name, schema=schema, create_type=False)


def nodo_actual() -> uuid.UUID:
    """Default de `nodo_origen_id`: el nodo configurado en NODO_ID."""
    cfg = get_settings()
    if cfg.nodo_id is not None:
        return cfg.nodo_id
    if cfg.mode == "cloud":
        return NODO_NUBE_ID
    raise RuntimeError("NODO_ID no está configurado; no se puede determinar nodo_origen_id")


# --- mixins ----------------------------------------------------------------------------------
class UUIDv7PK:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Timestamps(CreatedAt):
    # El trigger public.tg_tocar también fija updated_at en cada UPDATE (migración 0003).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditoriaCreacion:
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("identidad.empleados.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )


class NodoOrigen:
    nodo_origen_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizacion.nodos.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        nullable=False,
        default=nodo_actual,
    )


class Versionado:
    """Bloqueo optimista: SQLAlchemy emite UPDATE ... WHERE version = :viejo y falla si no afecta filas."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls) -> dict:
        return {"version_id_col": cls.version}


class Mutable(UUIDv7PK, Timestamps, AuditoriaCreacion, NodoOrigen, Versionado):
    """Plantilla [M] del modelo: maestros y documentos editables."""


class SoloAgregar(UUIDv7PK, CreatedAt, AuditoriaCreacion, NodoOrigen):
    """Plantilla [A]: kardex, bitácoras, líneas inmutables. Sin updated_at ni version."""
