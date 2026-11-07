"""Entorno de Alembic: include_schemas=True, compare_type=True, URL tomada de la configuración."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.base import Base
from app.core.config import get_settings
from app.core.db import cargar_modelos
from app.core.especiales import INDICES_ESPECIALES, SCHEMAS

cargar_modelos()  # registra todos los modelos (único punto de carga)

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # prioridad: -x url=... > sqlalchemy.url del .ini (lo usan las pruebas) > DATABASE_URL
    x = context.get_x_argument(as_dictionary=True).get("url")
    return x or config.get_main_option("sqlalchemy.url") or get_settings().database_url


def incluir_nombre(nombre, tipo, parent_names):
    """Solo los schemas del proyecto; ignora `public` (alembic_version) y demás."""
    if tipo == "schema":
        return nombre in SCHEMAS
    return True


def incluir_objeto(objeto, nombre, tipo, reflejado, comparado):
    """Los índices especiales (0003) no están en los modelos: no se reportan como sobrantes."""
    if tipo == "index" and nombre in INDICES_ESPECIALES:
        return False
    return True


_OPCIONES = dict(
    target_metadata=target_metadata,
    include_schemas=True,
    compare_type=True,
    include_name=incluir_nombre,
    include_object=incluir_objeto,
    version_table_schema="public",
)


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"}, **_OPCIONES)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, **_OPCIONES)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
