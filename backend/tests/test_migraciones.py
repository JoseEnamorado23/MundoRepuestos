"""Las migraciones suben, bajan y vuelven a subir; los modelos coinciden con la BD (`alembic check`)."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

import app.models  # noqa: F401
from app.core.base import Base
from app.core.especiales import SCHEMAS
from tests.conftest import BD_ROUNDTRIP, borrar_bd, config_alembic, crear_bd


def _tablas(url) -> set[str]:
    eng = create_engine(url)
    with eng.connect() as c:
        filas = c.execute(
            text(
                "SELECT table_schema || '.' || table_name FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE' AND table_schema = ANY(:s)"
            ),
            {"s": list(SCHEMAS)},
        )
        res = {r[0] for r in filas}
    eng.dispose()
    return res


def test_hay_una_sola_cabeza(engine):
    assert len(ScriptDirectory.from_config(config_alembic(engine.url)).get_heads()) == 1


def test_modelos_y_bd_coinciden(engine):
    """`alembic check` no detecta diferencias entre los modelos y la BD migrada (los objetos de 0003 se ignoran)."""
    command.check(config_alembic(engine.url))


def test_todas_las_tablas_del_modelo_existen(engine):
    esperadas = {f"{t.schema}.{t.name}" for t in Base.metadata.tables.values()}
    assert _tablas(engine.url) == esperadas
    assert len(esperadas) == 84


def test_roundtrip_upgrade_downgrade_upgrade(url_base):
    """base -> head -> base -> head sobre una BD aparte, sin dejar objetos huérfanos en el downgrade."""
    url = crear_bd(url_base, BD_ROUNDTRIP)
    try:
        cfg = config_alembic(url)
        command.upgrade(cfg, "head")
        completas = _tablas(url)
        assert completas
        command.downgrade(cfg, "base")
        assert _tablas(url) == set()
        eng = create_engine(url)
        with eng.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
                        "WHERE n.nspname = ANY(:s)"
                    ),
                    {"s": list(SCHEMAS)},
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                        "WHERE p.proname LIKE 'tg!_%' ESCAPE '!' OR p.proname LIKE 'f!_%' ESCAPE '!'"
                    )
                ).scalar_one()
                == 0
            )
        eng.dispose()
        command.upgrade(cfg, "head")
        assert _tablas(url) == completas
    finally:
        borrar_bd(url_base, BD_ROUNDTRIP)


@pytest.mark.parametrize("revision", ["0002", "0003", "0004", "0005", "0006", "0007", "0008"])
def test_cada_revision_baja_y_sube(url_base, revision):
    """Cada migración es reversible por separado (head -> revision-1 -> head)."""
    url = crear_bd(url_base, BD_ROUNDTRIP)
    try:
        cfg = config_alembic(url)
        command.upgrade(cfg, "head")
        previa = {
            "0002": "0001",
            "0003": "0002",
            "0004": "0003",
            "0005": "0004",
            "0006": "0005",
            "0007": "0006",
            "0008": "0007",
        }[revision]
        command.downgrade(cfg, previa)
        command.upgrade(cfg, "head")
    finally:
        borrar_bd(url_base, BD_ROUNDTRIP)
