"""Regla de modelo.md §1.9: toda FK de la Fase 1 tiene un índice cuya(s) primera(s) columna(s) sean las de la FK.

Exclusiones documentadas (no se indexan a propósito):
* `created_by` y `nodo_origen_id`/`nodo_destino_id`: columnas de auditoría/origen; nunca se filtra por ellas y los padres
  (empleados, nodos) no se borran físicamente, así que el índice solo encarecería cada escritura;
* FK a `referencia.*`: catálogos DIAN pequeños y estáticos (sin borrado ni actualización de su clave);
* el schema `auditoria`: bitácora de solo agregar con muchísimas escrituras; se consulta por entidad/actor/fecha.
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.especiales import INDICES_FK

SCHEMAS = (
    "organizacion",
    "identidad",
    "catalogo",
    "inventario",
    "cajas",
    "ventas",
    "fiscal",
    "sync",
)
EXCLUIDAS = ("created_by", "nodo_origen_id", "nodo_destino_id")

CONSULTA = text(
    """
    SELECT n.nspname || '.' || c.relname AS tabla,
           array_to_string(ARRAY(SELECT a.attname FROM unnest(con.conkey) k
                                 JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k
                                 ORDER BY array_position(con.conkey, k)), ',') AS columnas,
           (SELECT n2.nspname FROM pg_class c2 JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
             WHERE c2.oid = con.confrelid) AS esquema_destino
      FROM pg_constraint con
      JOIN pg_class c ON c.oid = con.conrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE con.contype = 'f' AND n.nspname = ANY(:schemas)
       AND NOT EXISTS (
            SELECT 1 FROM pg_index i
             WHERE i.indrelid = con.conrelid AND i.indisvalid
               AND (i.indkey::int2[])[0:cardinality(con.conkey) - 1] = con.conkey::int2[])
     ORDER BY 1, 2
    """
)


def test_toda_fk_tiene_indice_salvo_las_exclusiones_documentadas(conn):
    sin_indice = [
        f"{tabla}({cols})"
        for tabla, cols, destino in conn.execute(CONSULTA, {"schemas": list(SCHEMAS)})
        if cols not in EXCLUIDAS and destino != "referencia"
    ]
    assert not sin_indice, (
        "FK sin índice (cree el índice en una migración o documente la excepción en modelo.md §1.9): "
        + ", ".join(sin_indice)
    )


def test_los_indices_de_fk_registrados_existen(conn):
    existentes = set(conn.execute(text("SELECT indexname FROM pg_indexes")).scalars())
    faltan = [f"ix_{t}_{c}" for _s, t, c in INDICES_FK if f"ix_{t}_{c}" not in existentes]
    assert not faltan, f"INDICES_FK cita índices que no existen: {faltan}"
