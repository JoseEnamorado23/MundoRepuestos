"""políticas de autorización, aprobación remota, revisiones posteriores, vendedor/cajero y permisos

* `ventas.ventas.cajero_id` (quien cobró en su turno) junto a `vendedor_id` (quien armó la venta); se rellena para las
  ventas ya confirmadas y `ck_ventas_confirmada_cajero` lo exige en las confirmadas del POS;
* `identidad.solicitudes_autorizacion`: aprobación remota (el backoffice aprueba o rechaza lo que pide la caja);
* `auditoria.revisiones`: acciones ejecutadas bajo la política `revision_posterior`;
* se elimina `ck_turnos_diferencia_autorizada` (0009): la diferencia de arqueo ya NUNCA bloquea el cierre;
* permisos: `pos.precio_manual` se fusiona en `pos.cambiar_precio` (roles y autorizaciones ya emitidas migradas);
  nuevos `autorizaciones.aprobar` y `revisiones.gestionar`; nuevo rol `vendedor`;
* configuración por sede: políticas `autorizacion.*` y `autorizacion.solicitud_expira_min`; se retiran las claves
  `cajas.umbral_retiro_efectivo`, `cajas.umbral_diferencia_arqueo` y `ventas.devolucion_requiere_autorizacion`.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-07
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NODO_NUBE_ID = "00000000-0000-7000-8000-000000000001"
ROL_VENDEDOR_ID = "00000000-0000-7000-8000-000000000026"

PERMISOS_NUEVOS = (  # codigo, modulo, descripcion, requiere_autorizacion
    ("autorizaciones.aprobar", "autorizaciones", "Aprobar o rechazar solicitudes de autorización remotas", False),
    (
        "revisiones.gestionar",
        "revisiones",
        "Consultar y marcar como revisadas las acciones de revisión posterior",
        False,
    ),
)
GRANTS = {
    "administrador": ["autorizaciones.aprobar", "revisiones.gestionar"],
    "supervisor": ["autorizaciones.aprobar", "revisiones.gestionar"],
    "propietario": ["autorizaciones.aprobar", "revisiones.gestionar"],
    "vendedor": ["pos.acceder", "pos.vender", "catalogo.ver", "inventario.ver", "ventas.ver"],
}
# Debe coincidir con CONFIG_POR_DEFECTO de app/modules/organizacion/configuracion.py (copia congelada).
CONFIG_NUEVA = (  # clave, valor, descripcion
    (
        "autorizacion.devolucion",
        {"politica": "libre", "umbral": 200000, "sobre_umbral": "requiere_autorizacion"},
        "Política de devoluciones: libre hasta el umbral (COP); por encima, la política sobre_umbral",
    ),
    (
        "autorizacion.descuento_mayor",
        {"politica": "requiere_autorizacion"},
        "Política de descuentos por encima del tope del rol",
    ),
    ("autorizacion.cambiar_precio", {"politica": "requiere_autorizacion"}, "Política de cambio de precio en una línea"),
    (
        "autorizacion.retiro_caja",
        {"politica": "libre", "umbral": 300000, "sobre_umbral": "requiere_autorizacion"},
        "Política de retiros de efectivo: libre hasta el umbral (COP); por encima, la política sobre_umbral",
    ),
    (
        "autorizacion.diferencia_arqueo",
        {"politica": "revision_posterior"},
        "Política de diferencias de arqueo al cerrar el turno (nunca bloquea con revision_posterior)",
    ),
    ("autorizacion.solicitud_expira_min", 5, "Minutos de vigencia de una solicitud de aprobación remota"),
)
CONFIG_RETIRADA = (
    ("cajas.umbral_retiro_efectivo", 200000, "Retiro de efectivo (COP) desde el cual se exige autorización"),
    ("cajas.umbral_diferencia_arqueo", 5000, "Diferencia (COP) por medio de pago tolerada al cerrar sin autorización"),
    ("ventas.devolucion_requiere_autorizacion", True, "Toda devolución exige autorización de supervisor"),
)
SQL_CONFIG = (
    "INSERT INTO organizacion.configuracion_sede (id, sede_id, clave, valor, descripcion, nodo_origen_id) "
    "VALUES (CAST(:i AS uuid), :s, :k, CAST(:v AS jsonb), :d, :o) ON CONFLICT DO NOTHING"
)


def _uuid7() -> str:
    try:
        from uuid_utils.compat import uuid7
    except ImportError:  # pragma: no cover
        from uuid import uuid4 as uuid7
    return str(uuid7())


def _sembrar(bind, filas) -> None:
    for sede_id, nodo in bind.execute(sa.text("SELECT id, nodo_origen_id FROM organizacion.sedes")).all():
        for clave, valor, desc in filas:
            bind.execute(sa.text(SQL_CONFIG), dict(i=_uuid7(), s=sede_id, k=clave, v=json.dumps(valor), d=desc, o=nodo))


def upgrade() -> None:
    # --- auditoria.revisiones ------------------------------------------------------------------------------------
    op.create_table(
        "revisiones",
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("accion", sa.Text(), nullable=False),
        sa.Column("entidad_tipo", sa.Text(), nullable=False),
        sa.Column("entidad_id", sa.Uuid(), nullable=True),
        sa.Column("monto", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("empleado_id", sa.Uuid(), nullable=True),
        sa.Column("dispositivo_id", sa.Uuid(), nullable=True),
        sa.Column(
            "detalle", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("estado", sa.Text(), server_default="pendiente", nullable=False),
        sa.Column("revisada_por_id", sa.Uuid(), nullable=True),
        sa.Column("revisada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "estado <> 'revisada' OR (revisada_por_id IS NOT NULL AND revisada_at IS NOT NULL)",
            name=op.f("ck_revisiones_revisada_completa"),
        ),
        sa.CheckConstraint("estado IN ('pendiente','revisada')", name=op.f("ck_revisiones_estado_valido")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identidad.empleados.id"],
            name=op.f("fk_revisiones_created_by_empleados"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["empleado_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_revisiones_empleado_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["nodo_origen_id"],
            ["organizacion.nodos.id"],
            name=op.f("fk_revisiones_nodo_origen_id_nodos"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["revisada_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_revisiones_revisada_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_revisiones_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revisiones")),
        schema="auditoria",
    )
    op.create_index(
        "ix_revisiones_sede_estado",
        "revisiones",
        ["sede_id", "estado", sa.literal_column("created_at DESC")],
        unique=False,
        schema="auditoria",
    )
    op.create_index(
        "uq_revisiones_accion_entidad",
        "revisiones",
        ["accion", "entidad_id"],
        unique=True,
        schema="auditoria",
        postgresql_where=sa.text("entidad_id IS NOT NULL"),
    )

    # --- identidad.solicitudes_autorizacion ----------------------------------------------------------------------
    op.create_table(
        "solicitudes_autorizacion",
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("solicitado_por_id", sa.Uuid(), nullable=False),
        sa.Column("dispositivo_id", sa.Uuid(), nullable=True),
        sa.Column("caja_id", sa.Uuid(), nullable=True),
        sa.Column("accion", sa.Text(), nullable=False),
        sa.Column("monto", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column(
            "contexto", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("entidad_tipo", sa.Text(), nullable=True),
        sa.Column("entidad_id", sa.Uuid(), nullable=True),
        sa.Column("estado", sa.Text(), server_default="pendiente", nullable=False),
        sa.Column("expira_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resuelta_por_id", sa.Uuid(), nullable=True),
        sa.Column("resuelta_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column("autorizacion_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "estado <> 'aprobada' OR (autorizacion_id IS NOT NULL AND resuelta_por_id IS NOT NULL)",
            name=op.f("ck_solicitudes_autorizacion_aprobada_completa"),
        ),
        sa.CheckConstraint(
            "estado IN ('pendiente','aprobada','rechazada','expirada')",
            name=op.f("ck_solicitudes_autorizacion_estado_valido"),
        ),
        sa.CheckConstraint(
            "resuelta_por_id IS NULL OR resuelta_por_id <> solicitado_por_id",
            name=op.f("ck_solicitudes_autorizacion_no_autoaprobacion"),
        ),
        sa.ForeignKeyConstraint(
            ["accion"],
            ["identidad.permisos.codigo"],
            name=op.f("fk_solicitudes_autorizacion_accion_permisos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["autorizacion_id"],
            ["identidad.autorizaciones.id"],
            name=op.f("fk_solicitudes_autorizacion_autorizacion_id_autorizaciones"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identidad.empleados.id"],
            name=op.f("fk_solicitudes_autorizacion_created_by_empleados"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["nodo_origen_id"],
            ["organizacion.nodos.id"],
            name=op.f("fk_solicitudes_autorizacion_nodo_origen_id_nodos"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["resuelta_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_solicitudes_autorizacion_resuelta_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"],
            ["organizacion.sedes.id"],
            name=op.f("fk_solicitudes_autorizacion_sede_id_sedes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["solicitado_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_solicitudes_autorizacion_solicitado_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solicitudes_autorizacion")),
        schema="identidad",
    )
    op.create_index(
        "ix_solicitudes_autorizacion_pendientes",
        "solicitudes_autorizacion",
        ["sede_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="identidad",
        postgresql_where=sa.text("estado = 'pendiente'"),
    )
    op.create_index(
        "ix_solicitudes_autorizacion_solicitante",
        "solicitudes_autorizacion",
        ["solicitado_por_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="identidad",
    )
    for tabla in ("auditoria.revisiones", "identidad.solicitudes_autorizacion"):
        op.execute(f"CREATE TRIGGER tg_tocar BEFORE UPDATE ON {tabla} FOR EACH ROW EXECUTE FUNCTION public.tg_tocar()")

    # --- ventas.cajero_id ------------------------------------------------------------------------------------------
    op.add_column("ventas", sa.Column("cajero_id", sa.Uuid(), nullable=True), schema="ventas")
    op.create_foreign_key(
        op.f("fk_ventas_cajero_id_empleados"),
        "ventas",
        "empleados",
        ["cajero_id"],
        ["id"],
        source_schema="ventas",
        referent_schema="identidad",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_ventas_cajero",
        "ventas",
        ["cajero_id", sa.literal_column("confirmada_at DESC")],
        unique=False,
        schema="ventas",
        postgresql_where=sa.text("cajero_id IS NOT NULL"),
    )
    op.execute("ALTER TABLE ventas.ventas DISABLE TRIGGER USER")  # las confirmadas están congeladas
    op.execute(
        "UPDATE ventas.ventas SET cajero_id = COALESCE(vendedor_id, created_by) "
        "WHERE estado = 'confirmada' AND canal = 'pos' AND cajero_id IS NULL"
    )
    op.execute("ALTER TABLE ventas.ventas ENABLE TRIGGER USER")
    op.create_check_constraint(
        op.f("ck_ventas_confirmada_cajero"),
        "ventas",
        "estado <> 'confirmada' OR canal <> 'pos' OR cajero_id IS NOT NULL",
        schema="ventas",
    )

    # --- la diferencia de arqueo ya no bloquea el cierre -------------------------------------------------------------
    op.drop_constraint(op.f("ck_turnos_diferencia_autorizada"), "turnos", schema="cajas", type_="check")

    # --- una venta en espera (borrador) puede no tener turno: se asigna al confirmarla en una caja ----------------------
    op.drop_constraint(op.f("ck_ventas_canal_pos"), "ventas", schema="ventas", type_="check")
    op.create_check_constraint(
        op.f("ck_ventas_canal_pos"),
        "ventas",
        "canal <> 'pos' OR (caja_id IS NOT NULL AND (estado = 'borrador' OR turno_id IS NOT NULL))",
        schema="ventas",
    )

    bind = op.get_bind()

    # --- permisos: pos.precio_manual -> pos.cambiar_precio ----------------------------------------------------------
    bind.execute(
        sa.text(
            "UPDATE identidad.permisos SET descripcion = :d, requiere_autorizacion = true "
            "WHERE codigo = 'pos.cambiar_precio'"
        ),
        dict(
            d="Cambiar el precio de una línea (quien lo tiene no necesita autorización; "
            "también es la acción que autoriza un supervisor)"
        ),
    )
    bind.execute(
        sa.text(
            "INSERT INTO identidad.roles_permisos (rol_id, permiso_codigo) "
            "SELECT rol_id, 'pos.cambiar_precio' FROM identidad.roles_permisos WHERE permiso_codigo = 'pos.precio_manual' "
            "ON CONFLICT DO NOTHING"
        )
    )
    bind.execute(sa.text("DELETE FROM identidad.roles_permisos WHERE permiso_codigo = 'pos.precio_manual'"))
    op.execute("ALTER TABLE identidad.autorizaciones DISABLE TRIGGER USER")  # append-only: corrección de datos
    bind.execute(
        sa.text(
            "UPDATE identidad.autorizaciones SET permiso_codigo = 'pos.cambiar_precio' "
            "WHERE permiso_codigo = 'pos.precio_manual'"
        )
    )
    op.execute("ALTER TABLE identidad.autorizaciones ENABLE TRIGGER USER")
    bind.execute(sa.text("DELETE FROM identidad.permisos WHERE codigo = 'pos.precio_manual'"))

    for codigo, modulo, desc, req in PERMISOS_NUEVOS:
        bind.execute(
            sa.text(
                "INSERT INTO identidad.permisos (codigo, modulo, descripcion, requiere_autorizacion) "
                "VALUES (:c, :m, :d, :r) ON CONFLICT DO NOTHING"
            ),
            dict(c=codigo, m=modulo, d=desc, r=req),
        )
    bind.execute(
        sa.text(
            "INSERT INTO identidad.roles (id, codigo, nombre, es_sistema, nodo_origen_id) "
            "VALUES (CAST(:i AS uuid), 'vendedor', 'Vendedor', true, CAST(:o AS uuid)) ON CONFLICT DO NOTHING"
        ),
        dict(i=ROL_VENDEDOR_ID, o=NODO_NUBE_ID),
    )
    for rol, codigos in GRANTS.items():
        for codigo in codigos:
            bind.execute(
                sa.text(
                    "INSERT INTO identidad.roles_permisos (rol_id, permiso_codigo) "
                    "SELECT id, :p FROM identidad.roles WHERE codigo = :r ON CONFLICT DO NOTHING"
                ),
                dict(p=codigo, r=rol),
            )

    # --- configuración por sede ---------------------------------------------------------------------------------------
    bind.execute(
        sa.text("DELETE FROM organizacion.configuracion_sede WHERE sede_id IS NOT NULL AND clave = ANY(:c)"),
        {"c": [c[0] for c in CONFIG_RETIRADA]},
    )
    _sembrar(bind, CONFIG_NUEVA)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM organizacion.configuracion_sede WHERE sede_id IS NOT NULL AND clave = ANY(:c)"),
        {"c": [c[0] for c in CONFIG_NUEVA]},
    )
    _sembrar(bind, CONFIG_RETIRADA)
    # permisos: se restituye pos.precio_manual (las autorizaciones ya emitidas conservan pos.cambiar_precio)
    bind.execute(
        sa.text(
            "INSERT INTO identidad.permisos (codigo, modulo, descripcion, requiere_autorizacion) "
            "VALUES ('pos.precio_manual', 'pos', 'Cambiar el precio de una línea', true) ON CONFLICT DO NOTHING"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO identidad.roles_permisos (rol_id, permiso_codigo) "
            "SELECT rol_id, 'pos.precio_manual' FROM identidad.roles_permisos "
            "WHERE permiso_codigo = 'pos.cambiar_precio' ON CONFLICT DO NOTHING"
        )
    )
    bind.execute(
        sa.text("DELETE FROM identidad.roles_permisos WHERE permiso_codigo = ANY(:c) OR rol_id = CAST(:v AS uuid)"),
        {"c": [p[0] for p in PERMISOS_NUEVOS], "v": ROL_VENDEDOR_ID},
    )
    bind.execute(
        sa.text("DELETE FROM identidad.permisos WHERE codigo = ANY(:c)"), {"c": [p[0] for p in PERMISOS_NUEVOS]}
    )
    bind.execute(sa.text("DELETE FROM identidad.roles WHERE id = CAST(:v AS uuid)"), {"v": ROL_VENDEDOR_ID})
    op.create_check_constraint(
        op.f("ck_turnos_diferencia_autorizada"),
        "turnos",
        "diferencia IS NULL OR diferencia = 0 OR cierre_forzado "
        "OR (umbral_diferencia IS NOT NULL AND abs(diferencia) <= umbral_diferencia) "
        "OR (supervisor_cierre_id IS NOT NULL AND autorizacion_cierre_id IS NOT NULL)",
        schema="cajas",
    )
    op.drop_constraint(op.f("ck_ventas_canal_pos"), "ventas", schema="ventas", type_="check")
    op.create_check_constraint(
        op.f("ck_ventas_canal_pos"),
        "ventas",
        "canal <> 'pos' OR (caja_id IS NOT NULL AND turno_id IS NOT NULL)",
        schema="ventas",
    )
    op.drop_constraint(op.f("ck_ventas_confirmada_cajero"), "ventas", schema="ventas", type_="check")
    op.drop_constraint(op.f("fk_ventas_cajero_id_empleados"), "ventas", schema="ventas", type_="foreignkey")
    op.drop_index(
        "ix_ventas_cajero",
        table_name="ventas",
        schema="ventas",
        postgresql_where=sa.text("cajero_id IS NOT NULL"),
    )
    op.drop_column("ventas", "cajero_id", schema="ventas")
    op.drop_table("solicitudes_autorizacion", schema="identidad")
    op.drop_table("revisiones", schema="auditoria")
