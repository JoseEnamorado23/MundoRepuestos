"""búsqueda de productos en tabla propia (no toca productos.version/updated_at)

Mueve `nombre_busqueda`/`busqueda` fuera de `catalogo.productos` a `catalogo.productos_busqueda`, mantenida por
triggers. Así recalcular la búsqueda (p. ej. al renombrar una marca) no cambia `version` ni `updated_at` de
productos, que generarían eventos de sync y falsos conflictos. Tabla derivada y local: no se sincroniza.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-06
"""

import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FUNCION_RECALCULAR = """
CREATE FUNCTION catalogo.f_busqueda_producto(p_id uuid) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO catalogo.productos_busqueda (producto_id, documento, texto, actualizado_at)
    SELECT p.id,
           -- A: nombre + marca + referencias ('simple': literal) y nombre + marca ('spanish': raíces)
           setweight(to_tsvector('simple', public.f_unaccent(
               p.nombre || ' ' || coalesce(m.nombre, '') || ' ' ||
               coalesce((SELECT string_agg(r.referencia || ' ' || r.referencia_normalizada, ' ')
                           FROM catalogo.productos_referencias r
                          WHERE r.producto_id = p.id AND r.activo), ''))), 'A') ||
           setweight(to_tsvector('spanish', public.f_unaccent(p.nombre || ' ' || coalesce(m.nombre, ''))), 'A') ||
           setweight(to_tsvector('spanish', public.f_unaccent(coalesce(c.nombre, ''))), 'B') ||
           setweight(to_tsvector('spanish', public.f_unaccent(coalesce(p.descripcion, ''))), 'C'),
           lower(public.f_unaccent(trim(p.nombre || ' ' || coalesce(m.nombre, '')))),
           now()
      FROM catalogo.productos p
      LEFT JOIN catalogo.marcas m ON m.id = p.marca_id
      LEFT JOIN catalogo.categorias c ON c.id = p.categoria_id
     WHERE p.id = p_id
    ON CONFLICT (producto_id) DO UPDATE
       SET documento = EXCLUDED.documento, texto = EXCLUDED.texto, actualizado_at = EXCLUDED.actualizado_at;
END $$
"""

FUNCION_TRIGGER = """
CREATE FUNCTION catalogo.tg_busqueda_producto() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    r record;
BEGIN
    IF TG_TABLE_NAME = 'productos' THEN
        PERFORM catalogo.f_busqueda_producto(NEW.id);
    ELSIF TG_TABLE_NAME = 'productos_referencias' THEN
        IF TG_OP <> 'INSERT' THEN
            PERFORM catalogo.f_busqueda_producto(OLD.producto_id);
        END IF;
        IF TG_OP <> 'DELETE' AND (TG_OP = 'INSERT' OR NEW.producto_id <> OLD.producto_id) THEN
            PERFORM catalogo.f_busqueda_producto(NEW.producto_id);
        END IF;
    ELSIF TG_TABLE_NAME = 'marcas' THEN
        FOR r IN SELECT id FROM catalogo.productos WHERE marca_id = NEW.id LOOP
            PERFORM catalogo.f_busqueda_producto(r.id);
        END LOOP;
    ELSIF TG_TABLE_NAME = 'categorias' THEN
        FOR r IN SELECT id FROM catalogo.productos WHERE categoria_id = NEW.id LOOP
            PERFORM catalogo.f_busqueda_producto(r.id);
        END LOOP;
    END IF;
    RETURN NULL;
END $$
"""

TRIGGERS = (
    (
        "catalogo.productos",
        "tg_busqueda_producto",
        "AFTER INSERT OR UPDATE OF nombre, descripcion, marca_id, categoria_id",
    ),
    ("catalogo.productos_referencias", "tg_busqueda_producto", "AFTER INSERT OR UPDATE OR DELETE"),
    ("catalogo.marcas", "tg_busqueda_producto", "AFTER UPDATE OF nombre"),
    ("catalogo.categorias", "tg_busqueda_producto", "AFTER UPDATE OF nombre"),
)

INDICES = (
    "CREATE INDEX ix_productos_busqueda_documento ON catalogo.productos_busqueda USING gin (documento)",
    "CREATE INDEX ix_productos_busqueda_texto_trgm ON catalogo.productos_busqueda USING gin (texto gin_trgm_ops)",
)


def _migracion_0003():
    ruta = Path(__file__).with_name("0003_funciones_triggers_indices.py")
    spec = importlib.util.spec_from_file_location("_m0003", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def upgrade() -> None:
    op.create_table(
        "productos_busqueda",
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("documento", postgresql.TSVECTOR(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("actualizado_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_productos_busqueda_producto_id_productos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("producto_id", name=op.f("pk_productos_busqueda")),
        schema="catalogo",
    )

    # retirar lo anterior (0003)
    op.execute("DROP TRIGGER IF EXISTS tg_busqueda ON catalogo.productos")
    op.execute("DROP TRIGGER IF EXISTS tg_refrescar_busqueda ON catalogo.productos_referencias")
    op.execute("DROP TRIGGER IF EXISTS tg_refrescar_busqueda ON catalogo.marcas")
    op.execute("DROP FUNCTION catalogo.tg_refrescar_busqueda()")
    op.execute("DROP FUNCTION catalogo.tg_productos_busqueda()")
    op.execute("DROP FUNCTION catalogo.f_producto_busqueda(text, text, uuid, uuid, uuid)")
    op.execute("DROP INDEX catalogo.ix_productos_busqueda")
    op.execute("DROP INDEX catalogo.ix_productos_nombre_trgm")
    op.execute("ALTER TABLE catalogo.productos DROP COLUMN busqueda, DROP COLUMN nombre_busqueda")

    # nuevo mecanismo
    op.execute(FUNCION_RECALCULAR)
    op.execute(FUNCION_TRIGGER)
    for tabla, nombre, evento in TRIGGERS:
        op.execute(
            f"CREATE TRIGGER {nombre} {evento} ON {tabla} FOR EACH ROW EXECUTE FUNCTION catalogo.tg_busqueda_producto()"
        )
    op.execute("SELECT catalogo.f_busqueda_producto(id) FROM catalogo.productos")
    for sql in INDICES:
        op.execute(sql)


def downgrade() -> None:
    m3 = _migracion_0003()
    op.execute("DROP INDEX catalogo.ix_productos_busqueda_texto_trgm")
    op.execute("DROP INDEX catalogo.ix_productos_busqueda_documento")
    for tabla, nombre, _ in reversed(TRIGGERS):
        op.execute(f"DROP TRIGGER {nombre} ON {tabla}")
    op.execute("DROP FUNCTION catalogo.tg_busqueda_producto()")

    op.execute("ALTER TABLE catalogo.productos ADD COLUMN nombre_busqueda text, ADD COLUMN busqueda tsvector")
    # funciones y triggers de 0003 (se reutiliza su definición)
    viejas = [
        s.strip().rstrip(";")
        for s in m3.FUNCIONES.split(";\n\n")
        if any(k in s for k in ("f_producto_busqueda", "tg_productos_busqueda", "tg_refrescar_busqueda"))
    ]
    for s in viejas:
        op.execute(s)
    op.execute(
        "UPDATE catalogo.productos p SET nombre_busqueda = lower(public.f_unaccent(p.nombre)), "
        "busqueda = catalogo.f_producto_busqueda(p.nombre, p.descripcion, p.marca_id, p.categoria_id, p.id)"
    )
    op.execute("ALTER TABLE catalogo.productos ALTER COLUMN nombre_busqueda SET NOT NULL")
    for _t, nombre, sql in m3._triggers_especiales():
        if nombre in ("tg_busqueda", "tg_refrescar_busqueda"):
            op.execute(sql)
    for nombre, sql in m3.INDICES:
        if nombre in ("ix_productos_busqueda", "ix_productos_nombre_trgm"):
            op.execute(sql)

    op.execute("DROP FUNCTION catalogo.f_busqueda_producto(uuid)")
    op.drop_table("productos_busqueda", schema="catalogo")
