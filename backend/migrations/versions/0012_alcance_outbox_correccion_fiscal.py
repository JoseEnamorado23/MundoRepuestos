"""alcance de los eventos del outbox y corrección/reemisión de facturas rechazadas

* `sync.outbox_eventos.alcance` ('local' | 'sincronizable', por defecto 'sincronizable'): los eventos `fiscal.*` son
  locales de la sede y el agente de sync no los replica. El valor lo fija `publicar_evento` según el registro central
  `app/modules/sync/tipos_evento.py`; aquí se rellenan los existentes con el mismo criterio.
* `fiscal.estado_documento_fiscal` gana `anulado` (FE rechazada y reemplazada por una corrección; no requiere NC).
* `fiscal.tipo_evento_fiscal` gana `correccion` (bitácora).
* `fiscal.documentos_fiscales.documento_corrige_id`: la FE corregida apunta a la FE rechazada que reemplaza (una sola
  corrección por documento).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- alcance del outbox ----------------------------------------------------------------------------------------
    op.add_column(
        "outbox_eventos",
        sa.Column("alcance", sa.Text(), server_default="sincronizable", nullable=False),
        schema="sync",
    )
    op.execute("UPDATE sync.outbox_eventos SET alcance = 'local' WHERE evento_tipo LIKE 'fiscal.%'")
    op.create_check_constraint(
        op.f("ck_outbox_eventos_alcance"), "outbox_eventos", "alcance IN ('local','sincronizable')", schema="sync"
    )

    # --- nuevos valores de enum (fuera de la transacción: no se usan en esta migración) ----------------------------
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE fiscal.estado_documento_fiscal ADD VALUE IF NOT EXISTS 'anulado'")
        op.execute("ALTER TYPE fiscal.tipo_evento_fiscal ADD VALUE IF NOT EXISTS 'correccion'")

    # --- referencia a la FE que se corrige -------------------------------------------------------------------------
    op.add_column("documentos_fiscales", sa.Column("documento_corrige_id", sa.Uuid(), nullable=True), schema="fiscal")
    op.create_foreign_key(
        op.f("fk_documentos_fiscales_documento_corrige_id_documentos_fiscales"),
        "documentos_fiscales",
        "documentos_fiscales",
        ["documento_corrige_id"],
        ["id"],
        source_schema="fiscal",
        referent_schema="fiscal",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_documentos_fiscales_corrige_otro"),
        "documentos_fiscales",
        "documento_corrige_id IS DISTINCT FROM id",
        schema="fiscal",
    )
    op.create_index(
        "uq_documentos_fiscales_corrige",
        "documentos_fiscales",
        ["documento_corrige_id"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("documento_corrige_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_documentos_fiscales_corrige", table_name="documentos_fiscales", schema="fiscal")
    op.drop_constraint(op.f("ck_documentos_fiscales_corrige_otro"), "documentos_fiscales", schema="fiscal")
    op.drop_constraint(
        op.f("fk_documentos_fiscales_documento_corrige_id_documentos_fiscales"),
        "documentos_fiscales",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_column("documentos_fiscales", "documento_corrige_id", schema="fiscal")
    op.drop_constraint(op.f("ck_outbox_eventos_alcance"), "outbox_eventos", schema="sync")
    op.drop_column("outbox_eventos", "alcance", schema="sync")
    # Los valores de enum 'anulado' y 'correccion' no se pueden quitar de un ENUM de PostgreSQL sin recrear el tipo:
    # se dejan (inofensivos). Los documentos 'anulado' se devuelven a 'rechazado' para que el código antiguo los entienda.
    op.execute("UPDATE fiscal.documentos_fiscales SET estado = 'rechazado' WHERE estado = 'anulado'")
