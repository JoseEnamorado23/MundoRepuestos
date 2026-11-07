"""Fixtures: base de datos de pruebas real (PostgreSQL), creada y migrada con Alembic una vez por sesión.

Cada prueba corre dentro de una transacción que se revierte al final (los datos de semilla de la migración 0004
permanecen). Requiere `docker compose up -d db` y DATABASE_URL en .env.
"""

from __future__ import annotations

import os
from pathlib import Path

# Configuración de pruebas: se fija ANTES de importar la app (get_settings se cachea). Las variables de entorno
# tienen prioridad sobre .env.
os.environ.update(
    ENV="pruebas",
    MODE="cloud",
    NODO_ID="00000000-0000-7000-8000-000000000001",  # nodo nube sembrado por 0004
    JWT_SECRET="secreto-de-pruebas-0123456789-0123456789-abcdef",
    PIN_PEPPER="pimienta-de-pruebas",
    MAX_INTENTOS_DISPOSITIVO="3",
    MAX_INTENTOS_EMPLEADO="3",
    BLOQUEO_MINUTOS="15",
    LOG_LEVEL="WARNING",
    FISCAL_PROVEEDOR="simulado",  # las pruebas nunca llaman a Factus (salvo las marcadas `factus`)
)

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from app.core.config import get_settings

RAIZ_BACKEND = Path(__file__).resolve().parents[1]
BD_PRUEBAS = "mundorepuestos_test"
BD_ROUNDTRIP = "mundorepuestos_test_rt"


def url_de(base: str, nombre_bd: str) -> URL:
    return make_url(base).set(database=nombre_bd)


def crear_bd(base_url: str, nombre: str) -> URL:
    """(Re)crea una base de datos VACÍA de pruebas. Solo toca bases cuyo nombre empieza por `mundorepuestos_test`."""
    assert nombre.startswith("mundorepuestos_test")
    admin = create_engine(url_de(base_url, "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{nombre}"'))
    admin.dispose()
    return url_de(base_url, nombre)


def borrar_bd(base_url: str, nombre: str) -> None:
    assert nombre.startswith("mundorepuestos_test")
    admin = create_engine(url_de(base_url, "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
    admin.dispose()


def config_alembic(url: URL) -> Config:
    cfg = Config(str(RAIZ_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ_BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def url_base() -> str:
    return get_settings().database_url


@pytest.fixture(scope="session")
def engine(url_base):
    try:
        url = crear_bd(url_base, BD_PRUEBAS)
    except Exception as e:  # noqa: BLE001
        pytest.exit(f"No se pudo conectar a PostgreSQL ({e}). ¿Corriste `docker compose up -d db`?", returncode=2)
    command.upgrade(config_alembic(url), "head")
    eng = create_engine(url)
    yield eng
    eng.dispose()
    borrar_bd(url_base, BD_PRUEBAS)


@pytest.fixture
def conn(engine):
    """Conexión con transacción externa revertida al terminar. Las pruebas que esperan error usan `conn.begin_nested()`."""
    with engine.connect() as c:
        tx = c.begin()
        try:
            yield c
        finally:
            tx.rollback()


# ------------------------------------------------------------------------------------------ API
@pytest.fixture
def client(conn, monkeypatch):
    """TestClient cuya sesión de BD comparte la conexión/transacción de la prueba (commit = savepoint)."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    import app.core.db as db_mod
    from app.main import create_app

    sm = sessionmaker(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    monkeypatch.setattr(db_mod, "_Session", sm)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def db(conn):
    """Sesión ORM sobre la misma transacción, para preparar datos con los servicios reales."""
    from sqlalchemy.orm import Session

    with Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as s:
        yield s
