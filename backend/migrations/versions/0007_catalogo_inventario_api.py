"""ajustes de autenticación + soporte de catálogo/inventario por API

* elimina las columnas sin uso `empleados.pin_*` (el PIN vive por sede desde 0006);
* índices de `auditoria.log_acciones` que cubren la consulta de intentos fallidos (bloqueo);
* permisos nuevos (catalogo.ver, precios.editar, inventario.entradas, inventario.importar) y sus asignaciones;
* tabla local `inventario.importaciones` (importación Excel en dos pasos).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISOS_NUEVOS = (
    ("catalogo.ver", "catalogo", "Consultar y buscar productos, precios y compatibilidades", False),
    ("precios.editar", "catalogo", "Fijar precios de productos", False),
    ("inventario.entradas", "inventario", "Registrar entradas de mercancía (compra simple)", False),
    ("inventario.importar", "inventario", "Importar catálogo e inventario desde Excel", False),
)
GRANTS = {
    "administrador": [p[0] for p in PERMISOS_NUEVOS],
    "supervisor": [p[0] for p in PERMISOS_NUEVOS],
    "cajero": ["catalogo.ver"],
    "bodeguero": ["catalogo.ver", "inventario.entradas", "inventario.importar"],
}
# El rol 'bodeguero' ya tenía catalogo.editar; el administrador/supervisor reciben además los existentes por 0004.
GRANTS_EXTRA = {
    "supervisor": ["catalogo.editar", "catalogo.editar_precios", "inventario.ver", "inventario.ajustar"],
}


def upgrade() -> None:
    op.drop_column("empleados", "pin_bloqueado_hasta", schema="identidad")
    op.drop_column("empleados", "pin_intentos_fallidos", schema="identidad")
    op.drop_column("empleados", "pin_hash", schema="identidad")

    # Consulta de bloqueo: WHERE (dispositivo_id | actor_id) = :x AND accion = :a AND ocurrido_at > :desde
    # ORDER BY ocurrido_at DESC LIMIT N  -> índice (clave, accion, ocurrido_at DESC).
    op.execute("DROP INDEX auditoria.ix_log_acciones_dispositivo")
    op.execute(
        "CREATE INDEX ix_log_acciones_dispositivo ON auditoria.log_acciones (dispositivo_id, accion, ocurrido_at DESC) "
        "WHERE dispositivo_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_log_acciones_actor_accion ON auditoria.log_acciones (actor_id, accion, ocurrido_at DESC) "
        "WHERE actor_id IS NOT NULL"
    )

    op.create_table(
        "importaciones",
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("estado", sa.Text(), server_default="validada", nullable=False),
        sa.Column("nombre_archivo", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("resumen", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reporte", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("datos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confirmada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "estado IN ('validada','confirmada','descartada')", name=op.f("ck_importaciones_estado_valido")
        ),
        sa.CheckConstraint("tipo IN ('productos','compatibilidades')", name=op.f("ck_importaciones_tipo_valido")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identidad.empleados.id"],
            name=op.f("fk_importaciones_created_by_empleados"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["nodo_origen_id"],
            ["organizacion.nodos.id"],
            name=op.f("fk_importaciones_nodo_origen_id_nodos"),
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_importaciones")),
        schema="inventario",
    )
    op.create_index(
        "ix_importaciones_estado",
        "importaciones",
        ["estado", sa.literal_column("created_at DESC")],
        unique=False,
        schema="inventario",
    )

    for nombre, cols, checks, extra in (
        (
            "entradas_mercancia",
            [
                sa.Column("bodega_id", sa.Uuid(), nullable=False),
                sa.Column("tercero_id", sa.Uuid(), nullable=True),
                sa.Column("numero_factura", sa.Text(), nullable=True),
                sa.Column("observaciones", sa.Text(), nullable=True),
                sa.Column("total", sa.Numeric(18, 2), nullable=False),
                sa.Column("ocurrido_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            ],
            [sa.CheckConstraint("total >= 0", name=op.f("ck_entradas_mercancia_total_no_negativo"))],
            [
                sa.ForeignKeyConstraint(
                    ["bodega_id"],
                    ["inventario.bodegas.id"],
                    name=op.f("fk_entradas_mercancia_bodega_id_bodegas"),
                    ondelete="RESTRICT",
                ),
                sa.ForeignKeyConstraint(
                    ["tercero_id"],
                    ["identidad.terceros.id"],
                    name=op.f("fk_entradas_mercancia_tercero_id_terceros"),
                    ondelete="RESTRICT",
                ),
            ],
        ),
        (
            "entradas_mercancia_lineas",
            [
                sa.Column("entrada_id", sa.Uuid(), nullable=False),
                sa.Column("producto_id", sa.Uuid(), nullable=False),
                sa.Column("cantidad", sa.Numeric(14, 3), nullable=False),
                sa.Column("costo_unitario", sa.Numeric(18, 4), nullable=False),
            ],
            [
                sa.CheckConstraint("cantidad > 0", name=op.f("ck_entradas_mercancia_lineas_cantidad_positiva")),
                sa.CheckConstraint("costo_unitario >= 0", name=op.f("ck_entradas_mercancia_lineas_costo_no_negativo")),
            ],
            [
                sa.ForeignKeyConstraint(
                    ["entrada_id"],
                    ["inventario.entradas_mercancia.id"],
                    name=op.f("fk_entradas_mercancia_lineas_entrada_id_entradas_mercancia"),
                    ondelete="RESTRICT",
                ),
                sa.ForeignKeyConstraint(
                    ["producto_id"],
                    ["catalogo.productos.id"],
                    name=op.f("fk_entradas_mercancia_lineas_producto_id_productos"),
                    ondelete="RESTRICT",
                ),
            ],
        ),
    ):
        op.create_table(
            nombre,
            *cols,
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
            sa.Column("id", sa.Uuid(), nullable=False),
            *checks,
            *extra,
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["identidad.empleados.id"],
                name=op.f(f"fk_{nombre}_created_by_empleados"),
                ondelete="RESTRICT",
                initially="DEFERRED",
                deferrable=True,
            ),
            sa.ForeignKeyConstraint(
                ["nodo_origen_id"],
                ["organizacion.nodos.id"],
                name=op.f(f"fk_{nombre}_nodo_origen_id_nodos"),
                ondelete="RESTRICT",
                initially="DEFERRED",
                deferrable=True,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{nombre}")),
            schema="inventario",
        )
        op.execute(
            f"CREATE TRIGGER tg_inmutable BEFORE UPDATE OR DELETE ON inventario.{nombre} "
            "FOR EACH ROW EXECUTE FUNCTION public.tg_inmutable()"
        )
    op.create_index(
        "uq_entradas_mercancia_factura",
        "entradas_mercancia",
        ["tercero_id", "numero_factura"],
        unique=True,
        schema="inventario",
        postgresql_where=sa.text("tercero_id IS NOT NULL AND numero_factura IS NOT NULL"),
    )
    op.create_index(
        "ix_entradas_mercancia_bodega",
        "entradas_mercancia",
        ["bodega_id", sa.literal_column("ocurrido_at DESC")],
        unique=False,
        schema="inventario",
    )
    op.create_index(
        "ix_entradas_mercancia_lineas_entrada_id",
        "entradas_mercancia_lineas",
        ["entrada_id"],
        unique=False,
        schema="inventario",
    )

    bind = op.get_bind()
    for codigo, modulo, desc, req in PERMISOS_NUEVOS:
        bind.execute(
            sa.text(
                "INSERT INTO identidad.permisos (codigo, modulo, descripcion, requiere_autorizacion) "
                "VALUES (:c, :m, :d, :r) ON CONFLICT DO NOTHING"
            ),
            dict(c=codigo, m=modulo, d=desc, r=req),
        )
    for rol, codigos in {**GRANTS, "supervisor": GRANTS["supervisor"] + GRANTS_EXTRA["supervisor"]}.items():
        for codigo in codigos:
            bind.execute(
                sa.text(
                    "INSERT INTO identidad.roles_permisos (rol_id, permiso_codigo) "
                    "SELECT id, :p FROM identidad.roles WHERE codigo = :r ON CONFLICT DO NOTHING"
                ),
                dict(p=codigo, r=rol),
            )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inventario.entradas_mercancia_lineas")
    op.execute("DROP TABLE IF EXISTS inventario.entradas_mercancia")
    bind = op.get_bind()
    codigos = [p[0] for p in PERMISOS_NUEVOS]
    bind.execute(sa.text("DELETE FROM identidad.roles_permisos WHERE permiso_codigo = ANY(:c)"), {"c": codigos})
    bind.execute(sa.text("DELETE FROM identidad.permisos WHERE codigo = ANY(:c)"), {"c": codigos})
    op.drop_index("ix_importaciones_estado", table_name="importaciones", schema="inventario")
    op.drop_table("importaciones", schema="inventario")
    op.execute("DROP INDEX auditoria.ix_log_acciones_actor_accion")
    op.execute("DROP INDEX auditoria.ix_log_acciones_dispositivo")
    op.execute(
        "CREATE INDEX ix_log_acciones_dispositivo ON auditoria.log_acciones (dispositivo_id, ocurrido_at DESC) "
        "WHERE dispositivo_id IS NOT NULL"
    )
    op.add_column("empleados", sa.Column("pin_hash", sa.Text(), nullable=True), schema="identidad")
    op.add_column(
        "empleados",
        sa.Column("pin_intentos_fallidos", sa.SmallInteger(), server_default="0", nullable=False),
        schema="identidad",
    )
    op.add_column(
        "empleados", sa.Column("pin_bloqueado_hasta", sa.DateTime(timezone=True), nullable=True), schema="identidad"
    )
