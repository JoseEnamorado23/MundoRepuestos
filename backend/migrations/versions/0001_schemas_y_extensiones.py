"""schemas por módulo y extensiones

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMAS = (
    "referencia",
    "organizacion",
    "identidad",
    "catalogo",
    "inventario",
    "cajas",
    "ventas",
    "fiscal",
    "sync",
    "auditoria",
)
EXTENSIONES = ("pg_trgm", "unaccent", "btree_gist", "pgcrypto")


def upgrade() -> None:
    for ext in EXTENSIONES:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    for s in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")


def downgrade() -> None:
    for s in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {s} CASCADE")
    # Las extensiones pueden ser compartidas con otras bases/objetos: no se eliminan.
