"""Objetos de BD creados SOLO en la migración 0003 (índices GIN/GiST/BRIN, de expresión, etc.).

No están declarados en los modelos; `alembic check` los ignora a través de `incluir_objeto` (migrations/env.py)
para no reportarlos como "índices sobrantes".
"""

from __future__ import annotations

# schemas gestionados por Alembic (el resto, p. ej. `public`, se ignora)
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

# Columnas que se crean en 0003 como GENERATED ... STORED: se excluyen de 0002 (modelo.md, D-37)
COLUMNAS_GENERADAS = {
    ("inventario", "existencias"): ["cantidad_disponible"],
    ("cajas", "turnos"): ["diferencia"],
    ("cajas", "arqueos_turno"): ["diferencia"],
    ("catalogo", "productos_referencias"): ["referencia_normalizada"],
    ("catalogo", "vehiculos_versiones"): ["anios"],
    ("fiscal", "documentos_fiscales"): ["numero_completo"],
}

INDICES_ESPECIALES = {
    # unicidad con expresiones
    "uq_nodos_un_cloud",
    "ix_log_acciones_dispositivo",
    "ix_log_acciones_actor_accion",
    "uq_configuracion_sede_clave",
    "uq_empleados_usuario",
    "uq_terceros_consumidor_final",
    "uq_cuentas_clientes_email",
    "uq_marcas_nombre",
    "uq_categorias_hermanas",
    "uq_vehiculos_marcas_nombre",
    "uq_vehiculos_modelos_marca_nombre",
    "uq_listas_precios_predeterminada",
    "uq_productos_referencias",
    # búsqueda de texto
    "ix_municipios_nombre_trgm",
    "ix_terceros_nombre_trgm",
    "ix_productos_busqueda_documento",
    "ix_productos_busqueda_texto_gist",
    "ix_vehiculos_marcas_nombre_trgm",
    "ix_vehiculos_modelos_nombre_trgm",
    "ix_productos_referencias_norm",
    "ix_productos_referencias_trgm",
    # rangos / BRIN
    "ix_vehiculos_versiones_modelo_anios",
    "brin_movimientos_inventario_ocurrido",
    "brin_documentos_fiscales_eventos_ocurrido",
}
