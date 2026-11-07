"""facturación electrónica (Factus), índices de FK, motivos sin requiere_autorizacion y permisos unificados

* `fiscal.alertas_fiscales`: avisos para el backoffice (rechazo, reintentos agotados, descuadre de totales…);
* `fiscal.worker_latidos`: LOCAL del nodo (no se sincroniza); el worker fiscal anota su latido para `/health`;
* se eliminan `cajas.motivos_movimiento_caja.requiere_autorizacion` y `ventas.motivos_devolucion.requiere_autorizacion`
  (manda la política por sede, `configuracion_sede` `autorizacion.*`; el `downgrade` las restituye con su valor por defecto);
* índices en las FK que no tenían (regla: toda FK de la Fase 1 con índice, salvo `created_by`, `nodo_origen_id`,
  `nodo_destino_id`, las FK a `referencia.*` y el schema `auditoria`; ver modelo.md §1.9);
* permisos: `caja.abrir`/`caja.cerrar` se unifican en `cajas.turno.abrir`/`cajas.turno.cerrar` (los roles migran);
  `fiscal.reenviar` pasa a `fiscal.gestionar` (reintentar documentos rechazados o con reintentos agotados).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (schema, tabla, columna, anulable) — copia congelada de la regla de modelo.md §1.9
INDICES_FK = (
    ("cajas", "cajas", "bodega_id", False),
    ("cajas", "movimientos_caja", "autorizacion_id", True),
    ("cajas", "movimientos_caja", "motivo_id", False),
    ("cajas", "turnos", "autorizacion_cierre_id", True),
    ("cajas", "turnos", "cerrado_por_id", True),
    ("cajas", "turnos", "dispositivo_id", True),
    ("cajas", "turnos", "supervisor_cierre_id", True),
    ("catalogo", "precios", "lista_precio_id", False),
    ("catalogo", "precios", "sede_id", True),
    ("catalogo", "productos", "impuesto_id", False),
    ("catalogo", "productos_referencias", "marca_id", True),
    ("catalogo", "terceros_listas_precios", "lista_precio_id", False),
    ("fiscal", "documentos_fiscales", "adquirente_tercero_id", True),
    ("fiscal", "documentos_fiscales", "caja_id", True),
    ("fiscal", "documentos_fiscales_items", "devolucion_item_id", True),
    ("fiscal", "documentos_fiscales_items", "producto_id", True),
    ("fiscal", "documentos_fiscales_items", "venta_item_id", True),
    ("identidad", "autorizaciones", "permiso_codigo", False),
    ("identidad", "autorizaciones", "solicitado_por_id", False),
    ("identidad", "autorizaciones_consumos", "consumida_por_id", False),
    ("identidad", "solicitudes_autorizacion", "accion", False),
    ("identidad", "solicitudes_autorizacion", "autorizacion_id", True),
    ("identidad", "solicitudes_autorizacion", "resuelta_por_id", True),
    ("identidad", "terceros", "fusionado_en_id", True),
    ("inventario", "alertas_stock", "movimiento_id", True),
    ("inventario", "alertas_stock", "producto_id", False),
    ("inventario", "alertas_stock", "resuelta_por_id", True),
    ("inventario", "entradas_mercancia_lineas", "producto_id", False),
    ("inventario", "reservas_stock", "movimiento_id", True),
    ("inventario", "reservas_stock", "producto_id", False),
    ("inventario", "solicitudes_inventario", "bodega_id", False),
    ("inventario", "solicitudes_inventario", "resuelta_por_id", True),
    ("inventario", "solicitudes_inventario", "solicitada_por_id", False),
    ("organizacion", "configuracion_sede", "sede_id", True),
    ("sync", "conflictos_sync", "resuelto_por_id", True),
    ("ventas", "devoluciones", "autorizacion_id", True),
    ("ventas", "devoluciones", "motivo_id", False),
    ("ventas", "devoluciones_items", "bodega_reintegro_id", True),
    ("ventas", "devoluciones_items", "producto_id", False),
    ("ventas", "ventas", "lista_precio_id", True),
    ("ventas", "ventas_items", "autorizacion_id", True),
    ("ventas", "ventas_items", "bodega_id", False),
)

PERMISOS_NUEVOS = (  # codigo, modulo, descripcion, requiere_autorizacion
    (
        "fiscal.gestionar",
        "fiscal",
        "Gestionar documentos fiscales: reintentar rechazados o con reintentos agotados y resolver alertas",
        False,
    ),
)
# antiguo -> nuevo (los roles que tenían el antiguo reciben el nuevo)
FUSIONES = {
    "caja.abrir": "cajas.turno.abrir",
    "caja.cerrar": "cajas.turno.cerrar",
    "fiscal.reenviar": "fiscal.gestionar",
}
DESCRIPCION_ANTIGUA = {
    "caja.abrir": ("caja", "Abrir turno de caja"),
    "caja.cerrar": ("caja", "Cerrar turno de caja"),
    "fiscal.reenviar": ("fiscal", "Reenviar documentos al proveedor tecnológico"),
}


def _nombre_indice(tabla: str, columna: str) -> str:
    return f"ix_{tabla}_{columna}"


def upgrade() -> None:
    # --- fiscal.worker_latidos (LOCAL) -----------------------------------------------------------------------------
    op.create_table(
        "worker_latidos",
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("ultimo_latido_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ultimo_ciclo_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ciclos", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("procesados", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.Column("version_app", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("nombre", name=op.f("pk_worker_latidos")),
        schema="fiscal",
        comment="LOCAL del nodo: no se sincroniza",
    )

    # --- fiscal.alertas_fiscales -----------------------------------------------------------------------------------
    op.create_table(
        "alertas_fiscales",
        sa.Column("documento_id", sa.Uuid(), nullable=False),
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("mensaje", sa.Text(), nullable=False),
        sa.Column(
            "detalle", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("estado", sa.Text(), server_default="abierta", nullable=False),
        sa.Column("resuelta_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resuelta_por_id", sa.Uuid(), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "(estado = 'resuelta') = (resuelta_at IS NOT NULL)", name=op.f("ck_alertas_fiscales_resuelta_coherente")
        ),
        sa.CheckConstraint("estado IN ('abierta','resuelta')", name=op.f("ck_alertas_fiscales_estado")),
        sa.CheckConstraint(
            "tipo IN ('rechazado','reintentos_agotados','configuracion','totales_descuadrados','nota_sin_factura')",
            name=op.f("ck_alertas_fiscales_tipo"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identidad.empleados.id"],
            name=op.f("fk_alertas_fiscales_created_by_empleados"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["documento_id"],
            ["fiscal.documentos_fiscales.id"],
            name=op.f("fk_alertas_fiscales_documento_id_documentos_fiscales"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["nodo_origen_id"],
            ["organizacion.nodos.id"],
            name=op.f("fk_alertas_fiscales_nodo_origen_id_nodos"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["resuelta_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_alertas_fiscales_resuelta_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_alertas_fiscales_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alertas_fiscales")),
        schema="fiscal",
    )
    op.create_index("ix_alertas_fiscales_documento", "alertas_fiscales", ["documento_id"], schema="fiscal")
    op.create_index(
        "ix_alertas_fiscales_sede_estado",
        "alertas_fiscales",
        ["sede_id", "estado", sa.literal_column("created_at DESC")],
        schema="fiscal",
    )
    op.create_index(
        "ix_alertas_fiscales_resuelta_por_id",
        "alertas_fiscales",
        ["resuelta_por_id"],
        schema="fiscal",
        postgresql_where=sa.text("resuelta_por_id IS NOT NULL"),
    )
    op.create_index(
        "uq_alertas_fiscales_abierta",
        "alertas_fiscales",
        ["documento_id", "tipo"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("estado = 'abierta'"),
    )
    op.execute(
        "CREATE TRIGGER tg_tocar BEFORE UPDATE ON fiscal.alertas_fiscales "
        "FOR EACH ROW EXECUTE FUNCTION public.tg_tocar()"
    )

    # --- motivos: manda la política por sede -----------------------------------------------------------------------
    op.drop_column("motivos_movimiento_caja", "requiere_autorizacion", schema="cajas")
    op.drop_column("motivos_devolucion", "requiere_autorizacion", schema="ventas")

    # --- índices de FK ---------------------------------------------------------------------------------------------
    for schema, tabla, columna, anulable in INDICES_FK:
        donde = f" WHERE {columna} IS NOT NULL" if anulable else ""
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {_nombre_indice(tabla, columna)} ON {schema}.{tabla} ({columna}){donde}"
        )

    # --- cola del worker fiscal: eventos `fiscal.emitir` por procesar, en orden de secuencia -----------------------------
    op.execute(
        "CREATE INDEX ix_outbox_eventos_fiscal ON sync.outbox_eventos (secuencia) "
        "WHERE evento_tipo = 'fiscal.emitir' AND estado IN ('pendiente','enviado')"
    )

    # --- permisos --------------------------------------------------------------------------------------------------
    bind = op.get_bind()
    for codigo, modulo, desc, req in PERMISOS_NUEVOS:
        bind.execute(
            sa.text(
                "INSERT INTO identidad.permisos (codigo, modulo, descripcion, requiere_autorizacion) "
                "VALUES (:c, :m, :d, :r) ON CONFLICT DO NOTHING"
            ),
            dict(c=codigo, m=modulo, d=desc, r=req),
        )
    for antiguo, nuevo in FUSIONES.items():
        bind.execute(
            sa.text(
                "INSERT INTO identidad.roles_permisos (rol_id, permiso_codigo) "
                "SELECT rol_id, :n FROM identidad.roles_permisos WHERE permiso_codigo = :a ON CONFLICT DO NOTHING"
            ),
            dict(n=nuevo, a=antiguo),
        )
        bind.execute(sa.text("DELETE FROM identidad.roles_permisos WHERE permiso_codigo = :a"), dict(a=antiguo))
        bind.execute(sa.text("DELETE FROM identidad.permisos WHERE codigo = :a"), dict(a=antiguo))


def downgrade() -> None:
    bind = op.get_bind()
    # permisos: se restituyen los antiguos (los roles con el nuevo vuelven a tenerlos)
    for antiguo, nuevo in FUSIONES.items():
        modulo, desc = DESCRIPCION_ANTIGUA[antiguo]
        bind.execute(
            sa.text(
                "INSERT INTO identidad.permisos (codigo, modulo, descripcion, requiere_autorizacion) "
                "VALUES (:c, :m, :d, false) ON CONFLICT DO NOTHING"
            ),
            dict(c=antiguo, m=modulo, d=desc),
        )
        bind.execute(
            sa.text(
                "INSERT INTO identidad.roles_permisos (rol_id, permiso_codigo) "
                "SELECT rol_id, :a FROM identidad.roles_permisos WHERE permiso_codigo = :n ON CONFLICT DO NOTHING"
            ),
            dict(a=antiguo, n=nuevo),
        )
    # fiscal.gestionar solo existía desde 0011; cajas.turno.* existían desde 0009
    bind.execute(sa.text("DELETE FROM identidad.roles_permisos WHERE permiso_codigo = 'fiscal.gestionar'"))
    bind.execute(sa.text("DELETE FROM identidad.permisos WHERE codigo = 'fiscal.gestionar'"))

    op.execute("DROP INDEX IF EXISTS sync.ix_outbox_eventos_fiscal")
    for schema, tabla, columna, _anulable in reversed(INDICES_FK):
        op.execute(f"DROP INDEX IF EXISTS {schema}.{_nombre_indice(tabla, columna)}")

    op.add_column(
        "motivos_devolucion",
        sa.Column("requiere_autorizacion", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        schema="ventas",
    )
    op.add_column(
        "motivos_movimiento_caja",
        sa.Column("requiere_autorizacion", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="cajas",
    )
    op.drop_table("alertas_fiscales", schema="fiscal")
    op.drop_table("worker_latidos", schema="fiscal")
