"""Engine y sesiones de SQLAlchemy (síncronos, psycopg 3)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def cargar_modelos() -> None:
    """Registra TODOS los modelos en Base.metadata (resuelve las FK entre módulos).

    Único punto de carga: lo llaman create_app, el CLI, migrations/env.py, el futuro worker y, como red de
    seguridad, crear_engine. El registro vive en app/models.py. Es idempotente.
    """
    import app.models  # noqa: F401


def crear_engine(url: str | None = None, **kw) -> Engine:
    cargar_modelos()
    # pool_pre_ping: el edge puede reiniciar PostgreSQL sin reiniciar la API.
    url = url or get_settings().database_url
    if not url:
        from app.core.config import validar_configuracion

        validar_configuracion(requiere_nodo=False)  # lanza el mensaje claro de qué falta
    return create_engine(url, pool_pre_ping=True, **kw)


_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = crear_engine()
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _Session
    cargar_modelos()
    if _Session is None:
        _Session = sessionmaker(get_engine(), expire_on_commit=False)
    return _Session


@contextmanager
def sesion() -> Iterator[Session]:
    """Una transacción: commit al salir, rollback si hay excepción."""
    with get_sessionmaker()() as s:
        with s.begin():
            yield s
