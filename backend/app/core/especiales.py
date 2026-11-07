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


# Índices de FK creados en la migración 0011 (nombre = ix_<tabla>_<columna>); no están declarados en los modelos.
# Regla de modelo.md §1.9: toda FK de la Fase 1 lleva índice, salvo created_by, nodo_origen_id, nodo_destino_id, las FK a
# `referencia.*` y el schema `auditoria` (ver `tests/test_fk_indices.py`).
INDICES_FK = (
    ("cajas", "cajas", "bodega_id"),
    ("cajas", "movimientos_caja", "autorizacion_id"),
    ("cajas", "movimientos_caja", "motivo_id"),
    ("cajas", "turnos", "autorizacion_cierre_id"),
    ("cajas", "turnos", "cerrado_por_id"),
    ("cajas", "turnos", "dispositivo_id"),
    ("cajas", "turnos", "supervisor_cierre_id"),
    ("catalogo", "precios", "lista_precio_id"),
    ("catalogo", "precios", "sede_id"),
    ("catalogo", "productos", "impuesto_id"),
    ("catalogo", "productos_referencias", "marca_id"),
    ("catalogo", "terceros_listas_precios", "lista_precio_id"),
    ("fiscal", "documentos_fiscales", "adquirente_tercero_id"),
    ("fiscal", "documentos_fiscales", "caja_id"),
    ("fiscal", "documentos_fiscales_items", "devolucion_item_id"),
    ("fiscal", "documentos_fiscales_items", "producto_id"),
    ("fiscal", "documentos_fiscales_items", "venta_item_id"),
    ("identidad", "autorizaciones", "permiso_codigo"),
    ("identidad", "autorizaciones", "solicitado_por_id"),
    ("identidad", "autorizaciones_consumos", "consumida_por_id"),
    ("identidad", "solicitudes_autorizacion", "accion"),
    ("identidad", "solicitudes_autorizacion", "autorizacion_id"),
    ("identidad", "solicitudes_autorizacion", "resuelta_por_id"),
    ("identidad", "terceros", "fusionado_en_id"),
    ("inventario", "alertas_stock", "movimiento_id"),
    ("inventario", "alertas_stock", "producto_id"),
    ("inventario", "alertas_stock", "resuelta_por_id"),
    ("inventario", "entradas_mercancia_lineas", "producto_id"),
    ("inventario", "reservas_stock", "movimiento_id"),
    ("inventario", "reservas_stock", "producto_id"),
    ("inventario", "solicitudes_inventario", "bodega_id"),
    ("inventario", "solicitudes_inventario", "resuelta_por_id"),
    ("inventario", "solicitudes_inventario", "solicitada_por_id"),
    ("organizacion", "configuracion_sede", "sede_id"),
    ("sync", "conflictos_sync", "resuelto_por_id"),
    ("ventas", "devoluciones", "autorizacion_id"),
    ("ventas", "devoluciones", "motivo_id"),
    ("ventas", "devoluciones_items", "bodega_reintegro_id"),
    ("ventas", "devoluciones_items", "producto_id"),
    ("ventas", "ventas", "lista_precio_id"),
    ("ventas", "ventas_items", "autorizacion_id"),
    ("ventas", "ventas_items", "bodega_id"),
)
INDICES_ESPECIALES = INDICES_ESPECIALES | {f"ix_{t}_{c}" for _s, t, c in INDICES_FK} | {"ix_outbox_eventos_fiscal"}
