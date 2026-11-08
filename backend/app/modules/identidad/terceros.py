"""Terceros (clientes/proveedores fiscales): actualización de datos fiscales con evento de sync y auditoría.

El alta rápida del POS vive en `ventas.servicios.crear_tercero_rapido`; aquí está lo que modifica un tercero existente.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import Conflicto, NoEncontrado, ReglaNegocio
from app.core.utiles import snapshot
from app.modules.auditoria.servicios import registrar_accion
from app.modules.identidad.models import Tercero, TerceroResponsabilidad
from app.modules.sync.servicios import publicar_evento

# Nombre del campo en los snapshots fiscales (adquirente) -> columna de `identidad.terceros`.
CAMPOS_FISCALES: dict[str, str] = {
    "tipo_documento_codigo": "tipo_documento_codigo",
    "numero_documento": "numero_documento",
    "dv": "dv",
    "tipo_persona_codigo": "tipo_persona_codigo",
    "nombre_completo": "nombre_completo",
    "razon_social": "razon_social",
    "regimen_codigo": "regimen_codigo",
    "email": "email_facturacion",
    "telefono": "telefono",
    "direccion": "direccion_fiscal",
    "municipio_codigo": "municipio_codigo",
}


def actualizar_datos_fiscales(
    db: Session,
    tercero_id: uuid.UUID | None,
    cambios: dict[str, Any],
    actor_id: uuid.UUID | None,
    *,
    sede_id: uuid.UUID | None = None,
    motivo: str | None = None,
) -> Tercero:
    """Aplica `cambios` (claves del snapshot fiscal, ver `CAMPOS_FISCALES` + `responsabilidades`) a un tercero.

    Publica `tercero.actualizado` en la MISMA transacción y deja la acción en la bitácora (solo los NOMBRES de los
    campos: los valores son datos personales). No hace commit.
    """
    if tercero_id is None:
        raise NoEncontrado("El documento no tiene un tercero asociado para actualizar.", code="tercero_no_encontrado")
    t = db.scalar(select(Tercero).where(Tercero.id == tercero_id).with_for_update())
    if t is None:
        raise NoEncontrado("Tercero no encontrado.", code="tercero_no_encontrado")
    if t.es_consumidor_final:
        raise ReglaNegocio(
            "El consumidor final no se modifica: cree o seleccione el cliente real.", code="tercero_no_actualizable"
        )
    desconocidos = set(cambios) - set(CAMPOS_FISCALES) - {"responsabilidades"}
    if desconocidos:
        raise ReglaNegocio(
            "Campos no actualizables del tercero.", code="tercero_campos_invalidos", campos=sorted(desconocidos)
        )

    antes = snapshot(t)
    for clave, columna in CAMPOS_FISCALES.items():
        if clave in cambios:
            setattr(t, columna, cambios[clave])

    # Coherencia con las restricciones de la tabla, con un mensaje claro en vez de un error de BD.
    if t.tipo_persona_codigo == "1" and not (t.razon_social or "").strip():
        raise ReglaNegocio("Una persona jurídica necesita razón social.", code="nombre_requerido")
    if t.tipo_persona_codigo == "2" and not ((t.primer_nombre or "").strip() and (t.primer_apellido or "").strip()):
        raise ReglaNegocio("Una persona natural necesita primer nombre y primer apellido.", code="nombre_requerido")
    if t.tipo_documento_codigo == "31" and t.dv is None:
        raise ReglaNegocio("Un NIT necesita dígito de verificación.", code="dv_requerido")
    if ("numero_documento" in cambios or "tipo_documento_codigo" in cambios) and db.scalar(
        select(Tercero.id).where(
            Tercero.tipo_documento_codigo == t.tipo_documento_codigo,
            Tercero.numero_documento == t.numero_documento,
            Tercero.fusionado_en_id.is_(None),
            Tercero.id != t.id,
        )
    ):
        raise Conflicto("Ya existe otro tercero con ese documento.", code="tercero_documento_duplicado")

    if "responsabilidades" in cambios:
        nuevas = set(cambios["responsabilidades"] or [])
        actuales = {
            r.responsabilidad_codigo: r
            for r in db.scalars(select(TerceroResponsabilidad).where(TerceroResponsabilidad.tercero_id == t.id))
        }
        for codigo, fila in actuales.items():
            if codigo not in nuevas:
                db.delete(fila)
        for codigo in nuevas - set(actuales):
            db.add(TerceroResponsabilidad(tercero_id=t.id, responsabilidad_codigo=codigo))
    db.flush()
    db.refresh(t)  # `tg_tocar` sube `version`/`updated_at` en la BD

    cambiados = sorted(k for k in cambios if k == "responsabilidades" or antes[CAMPOS_FISCALES[k]] != cambios[k])
    publicar_evento(
        db,
        "tercero",
        t.id,
        "tercero.actualizado",
        {k: v for k, v in snapshot(t).items() if k != "created_by"} | {"campos": cambiados},
        version=t.version,
    )
    registrar_accion(
        db,
        "identidad.tercero_actualizado",
        actor_id=actor_id,
        sede_id=sede_id,
        entidad_tipo="tercero",
        entidad_id=t.id,
        despues={"campos": cambiados},
        motivo=motivo,
    )
    return t
