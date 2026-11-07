"""funciones, triggers, columnas generadas, EXCLUDE e índices especiales

Todo lo que Alembic no compara de forma fiable (modelo.md, D-37) vive aquí.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CERO = "'00000000-0000-0000-0000-000000000000'::uuid"

# Tablas [M] (tienen `version`): reciben tg_tocar
MUTABLES = (
    "cajas.cajas",
    "cajas.dispositivos",
    "cajas.motivos_movimiento_caja",
    "cajas.perifericos",
    "cajas.turnos",
    "catalogo.categorias",
    "catalogo.impuestos",
    "catalogo.listas_precios",
    "catalogo.marcas",
    "catalogo.precios",
    "catalogo.productos",
    "catalogo.productos_codigos_barras",
    "catalogo.productos_compatibilidades",
    "catalogo.productos_imagenes",
    "catalogo.productos_referencias",
    "catalogo.vehiculos_marcas",
    "catalogo.vehiculos_modelos",
    "catalogo.vehiculos_versiones",
    "fiscal.configuracion_proveedor",
    "fiscal.documentos_fiscales",
    "fiscal.documentos_fiscales_items",
    "fiscal.resoluciones_numeracion",
    "identidad.cuentas_clientes",
    "identidad.direcciones",
    "identidad.empleados",
    "identidad.roles",
    "identidad.terceros",
    "inventario.alertas_stock",
    "inventario.bodegas",
    "inventario.existencias",
    "inventario.reservas_stock",
    "inventario.ubicaciones",
    "organizacion.configuracion_sede",
    "organizacion.empresas",
    "organizacion.nodos",
    "organizacion.sedes",
    "sync.conflictos_sync",
    "ventas.devoluciones",
    "ventas.devoluciones_items",
    "ventas.devoluciones_pagos",
    "ventas.motivos_devolucion",
    "ventas.ventas",
    "ventas.ventas_items",
    "ventas.ventas_pagos",
)

# Tablas [A] append-only: tg_inmutable incondicional. (sync.outbox/inbox_eventos quedan fuera: su `estado` avanza.)
INMUTABLES = (
    "identidad.autorizaciones",
    "auditoria.log_acciones",
    "inventario.movimientos_inventario",
    "cajas.arqueos_turno",
    "cajas.movimientos_caja",
    "fiscal.documentos_fiscales_eventos",
    "fiscal.documentos_fiscales_impuestos",
    "fiscal.documentos_fiscales_pagos",
)

# (schema.tabla, columna, expresión)
GENERADAS = (
    ("inventario.existencias", "cantidad_disponible", "numeric(14,3) NOT NULL", "cantidad - cantidad_reservada"),
    ("cajas.turnos", "diferencia", "numeric(18,2)", "efectivo_contado - efectivo_esperado"),
    ("cajas.arqueos_turno", "diferencia", "numeric(18,2) NOT NULL", "valor_contado - valor_esperado"),
    (
        "catalogo.productos_referencias",
        "referencia_normalizada",
        "text NOT NULL",
        "public.f_normalizar_ref(referencia)",
    ),
    (
        "catalogo.vehiculos_versiones",
        "anios",
        "int4range NOT NULL",
        "int4range(anio_desde::int, anio_hasta::int, '[]')",
    ),
    ("fiscal.documentos_fiscales", "numero_completo", "text", "prefijo || consecutivo::text"),
)

# (nombre, sentencia CREATE)
INDICES = (
    ("uq_nodos_un_cloud", "CREATE UNIQUE INDEX uq_nodos_un_cloud ON organizacion.nodos ((true)) WHERE tipo = 'cloud'"),
    (
        "uq_configuracion_sede_clave",
        f"CREATE UNIQUE INDEX uq_configuracion_sede_clave ON organizacion.configuracion_sede (COALESCE(sede_id, {CERO}), clave)",
    ),
    (
        "uq_empleados_usuario",
        "CREATE UNIQUE INDEX uq_empleados_usuario ON identidad.empleados (lower(usuario)) WHERE usuario IS NOT NULL",
    ),
    (
        "uq_terceros_consumidor_final",
        "CREATE UNIQUE INDEX uq_terceros_consumidor_final ON identidad.terceros ((true)) WHERE es_consumidor_final",
    ),
    (
        "uq_cuentas_clientes_email",
        "CREATE UNIQUE INDEX uq_cuentas_clientes_email ON identidad.cuentas_clientes (lower(email))",
    ),
    ("uq_marcas_nombre", "CREATE UNIQUE INDEX uq_marcas_nombre ON catalogo.marcas (lower(nombre))"),
    (
        "uq_categorias_hermanas",
        f"CREATE UNIQUE INDEX uq_categorias_hermanas ON catalogo.categorias (COALESCE(parent_id, {CERO}), lower(nombre))",
    ),
    (
        "uq_vehiculos_marcas_nombre",
        "CREATE UNIQUE INDEX uq_vehiculos_marcas_nombre ON catalogo.vehiculos_marcas (lower(nombre))",
    ),
    (
        "uq_vehiculos_modelos_marca_nombre",
        "CREATE UNIQUE INDEX uq_vehiculos_modelos_marca_nombre ON catalogo.vehiculos_modelos (marca_id, lower(nombre))",
    ),
    (
        "uq_listas_precios_predeterminada",
        "CREATE UNIQUE INDEX uq_listas_precios_predeterminada ON catalogo.listas_precios ((true)) WHERE es_predeterminada",
    ),
    (
        "uq_productos_referencias",
        "CREATE UNIQUE INDEX uq_productos_referencias ON catalogo.productos_referencias "
        f"(producto_id, tipo, referencia_normalizada, COALESCE(marca_id, {CERO}))",
    ),
    (
        "ix_municipios_nombre_trgm",
        "CREATE INDEX ix_municipios_nombre_trgm ON referencia.municipios USING gin (public.f_unaccent(lower(nombre)) gin_trgm_ops)",
    ),
    (
        "ix_terceros_nombre_trgm",
        "CREATE INDEX ix_terceros_nombre_trgm ON identidad.terceros USING gin (public.f_unaccent(lower(nombre_completo)) gin_trgm_ops)",
    ),
    ("ix_productos_busqueda", "CREATE INDEX ix_productos_busqueda ON catalogo.productos USING gin (busqueda)"),
    (
        "ix_productos_nombre_trgm",
        "CREATE INDEX ix_productos_nombre_trgm ON catalogo.productos USING gin (nombre_busqueda gin_trgm_ops)",
    ),
    (
        "ix_productos_referencias_norm",
        "CREATE INDEX ix_productos_referencias_norm ON catalogo.productos_referencias (referencia_normalizada text_pattern_ops)",
    ),
    (
        "ix_productos_referencias_trgm",
        "CREATE INDEX ix_productos_referencias_trgm ON catalogo.productos_referencias USING gin (referencia_normalizada gin_trgm_ops)",
    ),
    (
        "ix_vehiculos_versiones_modelo_anios",
        "CREATE INDEX ix_vehiculos_versiones_modelo_anios ON catalogo.vehiculos_versiones USING gist (modelo_id, anios)",
    ),
    (
        "brin_movimientos_inventario_ocurrido",
        "CREATE INDEX brin_movimientos_inventario_ocurrido ON inventario.movimientos_inventario USING brin (ocurrido_at)",
    ),
    (
        "brin_documentos_fiscales_eventos_ocurrido",
        "CREATE INDEX brin_documentos_fiscales_eventos_ocurrido ON fiscal.documentos_fiscales_eventos USING brin (ocurrido_at)",
    ),
)

# --- columnas de documentos_fiscales que pueden cambiar tras salir de borrador (lista blanca de transporte) ---
LISTA_BLANCA_DOC = (
    "estado",
    "cufe_cude",
    "qr_data",
    "proveedor_documento_id",
    "proveedor_respuesta_codigo",
    "xml_url",
    "pdf_url",
    "intentos",
    "ultimo_error",
    "ultimo_intento_at",
    "proximo_intento_at",
    "enviado_at",
    "aceptado_at",
    "vigente",
    "es_contingencia",
    "contingencia_motivo",
    "prefijo",
    "consecutivo",
    "numero_completo",
    "updated_at",
    "version",
)

FUNCIONES = """
CREATE FUNCTION public.f_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

CREATE FUNCTION public.f_normalizar_ref(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT upper(regexp_replace($1, '[^A-Za-z0-9]', '', 'g')) $$;

CREATE FUNCTION public.tg_tocar() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    NEW.version := OLD.version + 1;
    RETURN NEW;
END $$;

CREATE FUNCTION public.tg_inmutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'La tabla %.% es inmutable: % no permitido. Corrija con un documento nuevo.',
        TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
END $$;

-- Cabeceras congeladas al salir de 'borrador' (ventas, devoluciones) o 'cerrado' (turnos)
CREATE FUNCTION public.tg_congelar_cabecera() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% % en estado "%" está congelado (% no permitido).',
        TG_TABLE_NAME, OLD.id, OLD.estado, TG_OP USING ERRCODE = 'integrity_constraint_violation';
END $$;

-- Líneas/pagos hijos: solo se tocan mientras la cabecera está en 'borrador'.
-- TG_ARGV[0] = tabla padre (schema.tabla), TG_ARGV[1] = columna FK hacia el padre.
CREATE FUNCTION public.tg_congelar_hijo() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_fila   jsonb;
    v_padre  uuid;
    v_estado text;
BEGIN
    IF TG_OP = 'DELETE' THEN v_fila := to_jsonb(OLD); ELSE v_fila := to_jsonb(NEW); END IF;
    v_padre := (v_fila ->> TG_ARGV[1])::uuid;
    EXECUTE format('SELECT estado::text FROM %s WHERE id = $1', TG_ARGV[0]) INTO v_estado USING v_padre;
    IF v_estado IS DISTINCT FROM 'borrador' THEN
        RAISE EXCEPTION '%.% no se puede modificar: el documento % está en estado "%".',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, v_padre, v_estado USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION fiscal.tg_documentos_congelar() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_blanca text[] := ARRAY[__LISTA_BLANCA__];
    v_old jsonb;
    v_new jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Los documentos fiscales no se borran (id %).', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.estado = 'borrador' THEN
        RETURN NEW;
    END IF;
    v_old := to_jsonb(OLD) - v_blanca;
    v_new := to_jsonb(NEW) - v_blanca;
    IF v_old IS DISTINCT FROM v_new THEN
        RAISE EXCEPTION 'El contenido del documento fiscal % es inmutable (solo cambian columnas de transporte).', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (OLD.prefijo IS NOT NULL AND NEW.prefijo IS DISTINCT FROM OLD.prefijo)
       OR (OLD.consecutivo IS NOT NULL AND NEW.consecutivo IS DISTINCT FROM OLD.consecutivo) THEN
        RAISE EXCEPTION 'El número del documento fiscal % ya fue asignado y no puede cambiar.', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;

-- Σ ventas_pagos.valor = ventas.total al confirmar (se evalúa al COMMIT)
CREATE FUNCTION ventas.tg_pagos_cuadran() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_suma numeric(18,2);
BEGIN
    IF NEW.estado = 'confirmada' THEN
        SELECT COALESCE(sum(valor), 0) INTO v_suma FROM ventas.ventas_pagos WHERE venta_id = NEW.id;
        IF v_suma <> NEW.total THEN
            RAISE EXCEPTION 'Venta %: los pagos (%) no cuadran con el total (%).', NEW.id, v_suma, NEW.total
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NULL;
END $$;

-- Búsqueda de productos: nombre_busqueda + tsvector ponderado (A nombre/marca/referencias, B categoría, C descripción).
-- Nombre y marca entran en 'simple' (literal) Y en 'spanish' (raíces) para que ambas consultas encuentren el producto;
-- las referencias solo en 'simple' (un número de parte no se debe stemmear).
CREATE FUNCTION catalogo.f_producto_busqueda(p_nombre text, p_descripcion text, p_marca uuid, p_categoria uuid, p_id uuid)
RETURNS tsvector LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN
        setweight(to_tsvector('simple', public.f_unaccent(
            coalesce(p_nombre, '') || ' ' ||
            coalesce((SELECT nombre FROM catalogo.marcas WHERE id = p_marca), '') || ' ' ||
            coalesce((SELECT string_agg(referencia || ' ' || referencia_normalizada, ' ')
                        FROM catalogo.productos_referencias WHERE producto_id = p_id AND activo), '')
        )), 'A') ||
        setweight(to_tsvector('spanish', public.f_unaccent(
            coalesce(p_nombre, '') || ' ' || coalesce((SELECT nombre FROM catalogo.marcas WHERE id = p_marca), ''))), 'A') ||
        setweight(to_tsvector('spanish', public.f_unaccent(
            coalesce((SELECT nombre FROM catalogo.categorias WHERE id = p_categoria), ''))), 'B') ||
        setweight(to_tsvector('spanish', public.f_unaccent(coalesce(p_descripcion, ''))), 'C');
END $$;

CREATE FUNCTION catalogo.tg_productos_busqueda() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.nombre_busqueda := lower(public.f_unaccent(NEW.nombre));
    NEW.busqueda := catalogo.f_producto_busqueda(NEW.nombre, NEW.descripcion, NEW.marca_id, NEW.categoria_id, NEW.id);
    RETURN NEW;
END $$;

-- Recalcula `busqueda` de los productos afectados por un cambio en referencias o marcas.
-- Columna derivada: no se sincroniza, cada nodo la recalcula.
CREATE FUNCTION catalogo.tg_refrescar_busqueda() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'productos_referencias' THEN
        IF TG_OP = 'DELETE' THEN
            v_id := OLD.producto_id;
        ELSE
            v_id := NEW.producto_id;
        END IF;
        UPDATE catalogo.productos p
           SET busqueda = catalogo.f_producto_busqueda(p.nombre, p.descripcion, p.marca_id, p.categoria_id, p.id)
         WHERE p.id = v_id;
    ELSE
        UPDATE catalogo.productos p
           SET busqueda = catalogo.f_producto_busqueda(p.nombre, p.descripcion, p.marca_id, p.categoria_id, p.id)
         WHERE p.marca_id = NEW.id;
    END IF;
    RETURN NULL;
END $$;

-- Numeración interna por caja (sin valor fiscal). Lock de fila: sin huecos ante rollback.
CREATE FUNCTION cajas.siguiente_numero_interno(p_caja_id uuid) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_n bigint;
BEGIN
    UPDATE cajas.cajas SET ultimo_numero_interno = ultimo_numero_interno + 1
     WHERE id = p_caja_id RETURNING ultimo_numero_interno INTO v_n;
    IF v_n IS NULL THEN
        RAISE EXCEPTION 'Caja % no existe.', p_caja_id;
    END IF;
    RETURN v_n;
END $$;

-- Modo 'local' (no usado por Factus): siguiente consecutivo de una resolución propia del nodo.
CREATE FUNCTION fiscal.siguiente_consecutivo(p_resolucion_id uuid, p_nodo_id uuid)
RETURNS TABLE (consecutivo bigint, prefijo text)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    UPDATE fiscal.resoluciones_numeracion r
       SET consecutivo_actual = r.consecutivo_actual + 1
     WHERE r.id = p_resolucion_id
       AND r.modo_numeracion = 'local'
       AND r.nodo_propietario_id = p_nodo_id
       AND r.estado = 'activa'
       AND current_date BETWEEN r.vigente_desde AND r.vigente_hasta
       AND r.consecutivo_actual < r.rango_hasta
    RETURNING r.consecutivo_actual, r.prefijo;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resolución % no disponible (agotada, vencida, ajena o en modo proveedor).', p_resolucion_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
END $$;
""".replace("__LISTA_BLANCA__", ", ".join(f"'{c}'" for c in LISTA_BLANCA_DOC))

DROP_FUNCIONES = (
    "fiscal.siguiente_consecutivo(uuid, uuid)",
    "cajas.siguiente_numero_interno(uuid)",
    "catalogo.tg_refrescar_busqueda()",
    "catalogo.tg_productos_busqueda()",
    "catalogo.f_producto_busqueda(text, text, uuid, uuid, uuid)",
    "ventas.tg_pagos_cuadran()",
    "fiscal.tg_documentos_congelar()",
    "public.tg_congelar_hijo()",
    "public.tg_congelar_cabecera()",
    "public.tg_inmutable()",
    "public.tg_tocar()",
    "public.f_normalizar_ref(text)",
    "public.f_unaccent(text)",
)


# (tabla, nombre trigger, definición completa) — triggers condicionales / especiales
def _triggers_especiales() -> list[tuple[str, str, str]]:
    t = []
    for tabla in ("ventas.ventas", "ventas.devoluciones"):
        t.append(
            (
                tabla,
                "tg_congelar",
                f"CREATE TRIGGER tg_congelar BEFORE UPDATE OR DELETE ON {tabla} "
                "FOR EACH ROW WHEN (OLD.estado <> 'borrador') EXECUTE FUNCTION public.tg_congelar_cabecera()",
            )
        )
    t.append(
        (
            "cajas.turnos",
            "tg_congelar",
            "CREATE TRIGGER tg_congelar BEFORE UPDATE OR DELETE ON cajas.turnos "
            "FOR EACH ROW WHEN (OLD.estado = 'cerrado') EXECUTE FUNCTION public.tg_congelar_cabecera()",
        )
    )
    hijos = (
        ("ventas.ventas_items", "ventas.ventas", "venta_id"),
        ("ventas.ventas_pagos", "ventas.ventas", "venta_id"),
        ("ventas.devoluciones_items", "ventas.devoluciones", "devolucion_id"),
        ("ventas.devoluciones_pagos", "ventas.devoluciones", "devolucion_id"),
        ("fiscal.documentos_fiscales_items", "fiscal.documentos_fiscales", "documento_id"),
        ("fiscal.documentos_fiscales_impuestos", "fiscal.documentos_fiscales", "documento_id"),
        ("fiscal.documentos_fiscales_pagos", "fiscal.documentos_fiscales", "documento_id"),
    )
    for tabla, padre, col in hijos:
        if tabla in INMUTABLES:  # ya tienen tg_inmutable incondicional
            continue
        t.append(
            (
                tabla,
                "tg_congelar",
                f"CREATE TRIGGER tg_congelar BEFORE INSERT OR UPDATE OR DELETE ON {tabla} "
                f"FOR EACH ROW EXECUTE FUNCTION public.tg_congelar_hijo('{padre}', '{col}')",
            )
        )
    t.append(
        (
            "fiscal.documentos_fiscales",
            "tg_congelar",
            "CREATE TRIGGER tg_congelar BEFORE UPDATE OR DELETE ON fiscal.documentos_fiscales "
            "FOR EACH ROW EXECUTE FUNCTION fiscal.tg_documentos_congelar()",
        )
    )
    t.append(
        (
            "ventas.ventas",
            "ctg_ventas_pagos_cuadran",
            "CREATE CONSTRAINT TRIGGER ctg_ventas_pagos_cuadran AFTER INSERT OR UPDATE ON ventas.ventas "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ventas.tg_pagos_cuadran()",
        )
    )
    t.append(
        (
            "catalogo.productos",
            "tg_busqueda",
            "CREATE TRIGGER tg_busqueda BEFORE INSERT OR UPDATE OF nombre, descripcion, marca_id, categoria_id "
            "ON catalogo.productos FOR EACH ROW EXECUTE FUNCTION catalogo.tg_productos_busqueda()",
        )
    )
    t.append(
        (
            "catalogo.productos_referencias",
            "tg_refrescar_busqueda",
            "CREATE TRIGGER tg_refrescar_busqueda AFTER INSERT OR UPDATE OR DELETE ON catalogo.productos_referencias "
            "FOR EACH ROW EXECUTE FUNCTION catalogo.tg_refrescar_busqueda()",
        )
    )
    t.append(
        (
            "catalogo.marcas",
            "tg_refrescar_busqueda",
            "CREATE TRIGGER tg_refrescar_busqueda AFTER UPDATE OF nombre ON catalogo.marcas "
            "FOR EACH ROW EXECUTE FUNCTION catalogo.tg_refrescar_busqueda()",
        )
    )
    return t


EXCLUSIONES = (
    (
        "catalogo.precios",
        "ex_precios_sin_solape",
        "EXCLUDE USING gist (producto_id WITH =, lista_precio_id WITH =, "
        f"(COALESCE(sede_id, {CERO})) WITH =, tstzrange(vigente_desde, vigente_hasta) WITH &&)",
    ),
    (
        "fiscal.resoluciones_numeracion",
        "ex_resoluciones_sin_solape",
        "EXCLUDE USING gist (empresa_id WITH =, tipo_documento_codigo WITH =, prefijo WITH =, "
        "int8range(rango_desde, rango_hasta, '[]') WITH &&) WHERE (estado NOT IN ('anulada', 'borrador'))",
    ),
)


def upgrade() -> None:
    for sentencia in FUNCIONES.split(";\n\n"):
        if sentencia.strip():
            op.execute(sentencia.strip().rstrip(";"))

    for tabla, col, tipo, expr in GENERADAS:
        op.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo} GENERATED ALWAYS AS ({expr}) STORED")

    for tabla in MUTABLES:
        op.execute(f"CREATE TRIGGER tg_tocar BEFORE UPDATE ON {tabla} FOR EACH ROW EXECUTE FUNCTION public.tg_tocar()")
    for tabla in INMUTABLES:
        op.execute(
            f"CREATE TRIGGER tg_inmutable BEFORE UPDATE OR DELETE ON {tabla} "
            "FOR EACH ROW EXECUTE FUNCTION public.tg_inmutable()"
        )
    for _tabla, _nombre, sql in _triggers_especiales():
        op.execute(sql)

    for tabla, nombre, definicion in EXCLUSIONES:
        op.execute(f"ALTER TABLE {tabla} ADD CONSTRAINT {nombre} {definicion}")
    for _nombre, sql in INDICES:
        op.execute(sql)


def downgrade() -> None:
    for nombre, _sql in reversed(INDICES):
        op.execute(f"DROP INDEX IF EXISTS {_esquema_de(nombre)}")
    for tabla, nombre, _def in reversed(EXCLUSIONES):
        op.execute(f"ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS {nombre}")

    for tabla, nombre, _sql in reversed(_triggers_especiales()):
        op.execute(f"DROP TRIGGER IF EXISTS {nombre} ON {tabla}")
    for tabla in reversed(INMUTABLES):
        op.execute(f"DROP TRIGGER IF EXISTS tg_inmutable ON {tabla}")
    for tabla in reversed(MUTABLES):
        op.execute(f"DROP TRIGGER IF EXISTS tg_tocar ON {tabla}")

    for tabla, col, _tipo, _expr in reversed(GENERADAS):
        op.execute(f"ALTER TABLE {tabla} DROP COLUMN IF EXISTS {col}")

    for f in DROP_FUNCIONES:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")


def _esquema_de(nombre_indice: str) -> str:
    """Devuelve `schema.indice` buscando la tabla en la sentencia CREATE correspondiente."""
    for n, sql in INDICES:
        if n == nombre_indice:
            tabla = sql.split(" ON ", 1)[1].split()[0]
            return f"{tabla.split('.')[0]}.{nombre_indice}"
    raise KeyError(nombre_indice)
