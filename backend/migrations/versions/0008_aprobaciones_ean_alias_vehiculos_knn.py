"""aprobación de entradas/ajustes, EAN-13 por nodo, alias de vehículos y búsqueda aproximada KNN

* `inventario.solicitudes_inventario`: entradas/ajustes de backoffice sobre el umbral quedan pendientes de aprobación;
* permiso `inventario.aprobar` y rol `propietario`;
* trigger que exige que quien autoriza (identidad.autorizaciones) tenga el permiso de la acción;
* `organizacion.nodos.codigo_ean` (2 dígitos, único) y `catalogo.contadores_ean` (consecutivo local por nodo);
* `catalogo.vehiculos_alias` + índices trigram sobre nombres normalizados de marcas y modelos de vehículos;
* índice GiST trigram en `catalogo.productos_busqueda` (reemplaza al GIN) para vecinos más cercanos (`<<->`).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROL_PROPIETARIO_ID = "00000000-0000-7000-8000-000000000025"
NODO_NUBE_ID = "00000000-0000-7000-8000-000000000001"


def upgrade() -> None:
    # las migraciones corren en una sola transacción: aplicar ya las FK diferidas pendientes (sembradas en 0004)
    # para poder alterar `organizacion.nodos`
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.create_table(
        "contadores_ean",
        sa.Column("nodo_id", sa.Uuid(), nullable=False),
        sa.Column("ultimo", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("ultimo >= 0", name=op.f("ck_contadores_ean_ultimo_no_negativo")),
        sa.ForeignKeyConstraint(
            ["nodo_id"], ["organizacion.nodos.id"], name=op.f("fk_contadores_ean_nodo_id_nodos"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("nodo_id", name=op.f("pk_contadores_ean")),
        schema="catalogo",
    )
    op.create_table(
        "solicitudes_inventario",
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("estado", sa.Text(), server_default="pendiente_aprobacion", nullable=False),
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("bodega_id", sa.Uuid(), nullable=False),
        sa.Column("valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("umbral", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("solicitada_por_id", sa.Uuid(), nullable=False),
        sa.Column("resuelta_por_id", sa.Uuid(), nullable=True),
        sa.Column("resuelta_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_resolucion", sa.Text(), nullable=True),
        sa.Column("autoaprobado", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("resultado_tipo", sa.Text(), nullable=True),
        sa.Column("resultado_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "(estado = 'pendiente_aprobacion') = (resuelta_por_id IS NULL)",
            name=op.f("ck_solicitudes_inventario_resolucion_coherente"),
        ),
        sa.CheckConstraint(
            "NOT autoaprobado OR estado = 'aprobada'", name=op.f("ck_solicitudes_inventario_autoaprobado_solo_aprobada")
        ),
        sa.CheckConstraint(
            "estado <> 'rechazada' OR motivo_resolucion IS NOT NULL",
            name=op.f("ck_solicitudes_inventario_rechazo_con_motivo"),
        ),
        sa.CheckConstraint(
            "estado IN ('pendiente_aprobacion','aprobada','rechazada')",
            name=op.f("ck_solicitudes_inventario_estado_valido"),
        ),
        sa.CheckConstraint("tipo IN ('entrada','ajuste')", name=op.f("ck_solicitudes_inventario_tipo_valido")),
        sa.CheckConstraint(
            "(resuelta_por_id IS NULL) = (resuelta_at IS NULL)",
            name=op.f("ck_solicitudes_inventario_resolucion_con_fecha"),
        ),
        sa.CheckConstraint(
            "resuelta_por_id IS NULL OR resuelta_por_id <> solicitada_por_id OR autoaprobado",
            name=op.f("ck_solicitudes_inventario_segregacion_funciones"),
        ),
        sa.CheckConstraint("valor >= 0 AND umbral >= 0", name=op.f("ck_solicitudes_inventario_valores_no_negativos")),
        sa.ForeignKeyConstraint(
            ["bodega_id"],
            ["inventario.bodegas.id"],
            name=op.f("fk_solicitudes_inventario_bodega_id_bodegas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identidad.empleados.id"],
            name=op.f("fk_solicitudes_inventario_created_by_empleados"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["nodo_origen_id"],
            ["organizacion.nodos.id"],
            name=op.f("fk_solicitudes_inventario_nodo_origen_id_nodos"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["resuelta_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_solicitudes_inventario_resuelta_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"],
            ["organizacion.sedes.id"],
            name=op.f("fk_solicitudes_inventario_sede_id_sedes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["solicitada_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_solicitudes_inventario_solicitada_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solicitudes_inventario")),
        schema="inventario",
    )
    op.create_index(
        "ix_solicitudes_inventario_estado",
        "solicitudes_inventario",
        ["estado", sa.literal_column("created_at DESC")],
        unique=False,
        schema="inventario",
    )
    op.create_index(
        "ix_solicitudes_inventario_sede",
        "solicitudes_inventario",
        ["sede_id", "estado"],
        unique=False,
        schema="inventario",
    )
    op.create_table(
        "vehiculos_alias",
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("alias_normalizado", sa.Text(), nullable=False),
        sa.Column("marca_id", sa.Uuid(), nullable=True),
        sa.Column("modelo_id", sa.Uuid(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("num_nonnulls(marca_id, modelo_id) = 1", name=op.f("ck_vehiculos_alias_un_destino")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identidad.empleados.id"],
            name=op.f("fk_vehiculos_alias_created_by_empleados"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["marca_id"],
            ["catalogo.vehiculos_marcas.id"],
            name=op.f("fk_vehiculos_alias_marca_id_vehiculos_marcas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["modelo_id"],
            ["catalogo.vehiculos_modelos.id"],
            name=op.f("fk_vehiculos_alias_modelo_id_vehiculos_modelos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["nodo_origen_id"],
            ["organizacion.nodos.id"],
            name=op.f("fk_vehiculos_alias_nodo_origen_id_nodos"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehiculos_alias")),
        schema="catalogo",
    )
    op.create_index("ix_vehiculos_alias_marca_id", "vehiculos_alias", ["marca_id"], unique=False, schema="catalogo")
    op.create_index("ix_vehiculos_alias_modelo_id", "vehiculos_alias", ["modelo_id"], unique=False, schema="catalogo")
    op.create_index(
        "uq_vehiculos_alias_normalizado",
        "vehiculos_alias",
        ["alias_normalizado"],
        unique=True,
        schema="catalogo",
        postgresql_where=sa.text("activo"),
    )
    # nodos.codigo_ean: la nube = '00'; los demás nodos, en orden de creación: '01', '02', ...
    op.add_column("nodos", sa.Column("codigo_ean", sa.Text(), nullable=True), schema="organizacion")
    op.execute(
        "UPDATE organizacion.nodos n SET codigo_ean = lpad(r.rn::text, 2, '0') FROM ("
        "SELECT id, row_number() OVER (ORDER BY (tipo = 'cloud') DESC, created_at, id) - 1 AS rn "
        "FROM organizacion.nodos) r WHERE r.id = n.id"
    )
    op.alter_column("nodos", "codigo_ean", nullable=False, schema="organizacion")
    op.create_check_constraint(
        op.f("ck_nodos_codigo_ean_formato"), "nodos", "codigo_ean ~ '^[0-9]{2}$'", schema="organizacion"
    )
    op.create_unique_constraint(op.f("uq_nodos_codigo_ean"), "nodos", ["codigo_ean"], schema="organizacion")

    for tabla in ("inventario.solicitudes_inventario", "catalogo.vehiculos_alias"):
        op.execute(f"CREATE TRIGGER tg_tocar BEFORE UPDATE ON {tabla} FOR EACH ROW EXECUTE FUNCTION public.tg_tocar()")

    # tablas LOCALES del nodo (no se sincronizan)
    op.execute(
        "COMMENT ON TABLE catalogo.contadores_ean IS 'LOCAL del nodo: no se sincroniza (consecutivo de EAN-13 internos).'"
    )
    op.execute(
        "COMMENT ON TABLE inventario.importaciones IS "
        "'LOCAL del nodo: no se sincroniza. Las no confirmadas se purgan con: app.cli importaciones limpiar --dias N.'"
    )

    # búsqueda aproximada: GiST trigram (KNN con <<->) en lugar de GIN
    op.execute("DROP INDEX catalogo.ix_productos_busqueda_texto_trgm")
    op.execute(
        "CREATE INDEX ix_productos_busqueda_texto_gist ON catalogo.productos_busqueda USING gist (texto gist_trgm_ops)"
    )

    # nombres de vehículos normalizados (minúsculas, sin tildes) con trigram
    op.execute(
        "CREATE INDEX ix_vehiculos_marcas_nombre_trgm ON catalogo.vehiculos_marcas "
        "USING gin (lower(public.f_unaccent(nombre)) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_vehiculos_modelos_nombre_trgm ON catalogo.vehiculos_modelos "
        "USING gin (lower(public.f_unaccent(nombre)) gin_trgm_ops)"
    )

    # segregación de funciones: quien autoriza debe estar activo y tener el permiso de la acción
    op.execute(
        """
CREATE FUNCTION identidad.tg_autorizacion_valida() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM identidad.empleados e
        JOIN identidad.empleados_roles er ON er.empleado_id = e.id
        JOIN identidad.roles r ON r.id = er.rol_id AND r.activo
        JOIN identidad.roles_permisos rp ON rp.rol_id = r.id
        WHERE e.id = NEW.autorizado_por_id AND e.activo AND rp.permiso_codigo = NEW.permiso_codigo
    ) THEN
        RAISE EXCEPTION 'El empleado % no está activo o no tiene el permiso % para autorizar.',
            NEW.autorizado_por_id, NEW.permiso_codigo USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$
"""
    )
    op.execute(
        "CREATE TRIGGER tg_autorizacion_valida BEFORE INSERT ON identidad.autorizaciones "
        "FOR EACH ROW EXECUTE FUNCTION identidad.tg_autorizacion_valida()"
    )

    # permiso inventario.aprobar y rol propietario (todos los permisos)
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO identidad.permisos (codigo, modulo, descripcion, requiere_autorizacion) "
            "VALUES ('inventario.aprobar', 'inventario', 'Aprobar o rechazar entradas y ajustes sobre el umbral', false) "
            "ON CONFLICT DO NOTHING"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO identidad.roles (id, codigo, nombre, es_sistema, nodo_origen_id) "
            "VALUES (CAST(:i AS uuid), 'propietario', 'Propietario', true, CAST(:n AS uuid)) ON CONFLICT DO NOTHING"
        ),
        dict(i=ROL_PROPIETARIO_ID, n=NODO_NUBE_ID),
    )
    for rol in ("administrador", "supervisor"):
        bind.execute(
            sa.text(
                "INSERT INTO identidad.roles_permisos (rol_id, permiso_codigo) "
                "SELECT id, 'inventario.aprobar' FROM identidad.roles WHERE codigo = :r ON CONFLICT DO NOTHING"
            ),
            dict(r=rol),
        )
    bind.execute(
        sa.text(
            "INSERT INTO identidad.roles_permisos (rol_id, permiso_codigo) "
            "SELECT CAST(:i AS uuid), codigo FROM identidad.permisos ON CONFLICT DO NOTHING"
        ),
        dict(i=ROL_PROPIETARIO_ID),
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM identidad.roles_permisos WHERE rol_id = CAST(:i AS uuid)"), dict(i=ROL_PROPIETARIO_ID)
    )
    bind.execute(sa.text("DELETE FROM identidad.roles_permisos WHERE permiso_codigo = 'inventario.aprobar'"))
    bind.execute(
        sa.text("DELETE FROM identidad.empleados_roles WHERE rol_id = CAST(:i AS uuid)"), dict(i=ROL_PROPIETARIO_ID)
    )
    bind.execute(sa.text("DELETE FROM identidad.roles WHERE id = CAST(:i AS uuid)"), dict(i=ROL_PROPIETARIO_ID))
    bind.execute(sa.text("DELETE FROM identidad.permisos WHERE codigo = 'inventario.aprobar'"))
    op.execute("DROP TRIGGER IF EXISTS tg_autorizacion_valida ON identidad.autorizaciones")
    op.execute("DROP FUNCTION IF EXISTS identidad.tg_autorizacion_valida()")
    op.execute("DROP INDEX IF EXISTS catalogo.ix_vehiculos_modelos_nombre_trgm")
    op.execute("DROP INDEX IF EXISTS catalogo.ix_vehiculos_marcas_nombre_trgm")
    op.execute("DROP INDEX IF EXISTS catalogo.ix_productos_busqueda_texto_gist")
    op.execute(
        "CREATE INDEX ix_productos_busqueda_texto_trgm ON catalogo.productos_busqueda USING gin (texto gin_trgm_ops)"
    )
    op.execute("COMMENT ON TABLE inventario.importaciones IS NULL")
    op.drop_constraint(op.f("uq_nodos_codigo_ean"), "nodos", schema="organizacion", type_="unique")
    op.drop_constraint(op.f("ck_nodos_codigo_ean_formato"), "nodos", schema="organizacion", type_="check")
    op.drop_column("nodos", "codigo_ean", schema="organizacion")
    op.drop_index(
        "uq_vehiculos_alias_normalizado",
        table_name="vehiculos_alias",
        schema="catalogo",
        postgresql_where=sa.text("activo"),
    )
    op.drop_index("ix_vehiculos_alias_modelo_id", table_name="vehiculos_alias", schema="catalogo")
    op.drop_index("ix_vehiculos_alias_marca_id", table_name="vehiculos_alias", schema="catalogo")
    op.drop_table("vehiculos_alias", schema="catalogo")
    op.drop_index("ix_solicitudes_inventario_sede", table_name="solicitudes_inventario", schema="inventario")
    op.drop_index("ix_solicitudes_inventario_estado", table_name="solicitudes_inventario", schema="inventario")
    op.drop_table("solicitudes_inventario", schema="inventario")
    op.drop_table("contadores_ean", schema="catalogo")
