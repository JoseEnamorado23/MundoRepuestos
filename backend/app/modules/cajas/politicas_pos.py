"""Aplicación de las políticas de autorización (0010) a una acción sensible hecha desde una sesión POS.

`aplicar_politica` decide, según `organizacion.politicas`:
* `libre`: no hace nada;
* `revision_posterior`: deja la acción en `auditoria.revisiones` y sigue;
* `requiere_autorizacion`: exige `autorizacion_id` de OTRO empleado (PIN de supervisor o aprobación remota; las dos
  producen una fila de `identidad.autorizaciones` de un solo uso). Quien ya tiene el permiso de la acción
  (`PERMISO_DE_ACCION`: un supervisor, el propietario) no necesita pedirla.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errores import PermisoDenegado
from app.modules.auditoria import revisiones
from app.modules.identidad.autorizaciones import consumir_autorizacion
from app.modules.organizacion import politicas

VIAS = ["pin_supervisor", "solicitud_remota"]


@dataclass(frozen=True)
class ResultadoPolitica:
    politica: str
    autorizado_por_id: uuid.UUID | None = None
    autorizacion_id: uuid.UUID | None = None
    exento_por_permiso: bool = False
    revision_id: uuid.UUID | None = None


def aplicar_politica(
    db: Session,
    actor,
    accion: str,
    monto: Decimal | None,
    *,
    autorizacion_id: uuid.UUID | None,
    entidad_tipo: str,
    entidad_id: uuid.UUID,
    detalle: dict | None = None,
) -> ResultadoPolitica:
    """Aplica la política de `accion` (ver módulo). `actor` = Actor con sesión POS."""
    sesion = actor.pos
    politica = politicas.evaluar(db, sesion.sede_id, accion, monto)
    if politica == politicas.LIBRE:
        return ResultadoPolitica(politica)
    if politica == politicas.REVISION:
        rev = revisiones.registrar(
            db,
            sede_id=sesion.sede_id,
            accion=accion,
            entidad_tipo=entidad_tipo,
            entidad_id=entidad_id,
            monto=monto,
            empleado_id=sesion.empleado.id,
            dispositivo_id=sesion.dispositivo_id,
            detalle=detalle,
        )
        return ResultadoPolitica(politica, revision_id=rev.id)

    permiso = politicas.PERMISO_DE_ACCION[accion]
    if permiso in actor.permisos:
        return ResultadoPolitica(politica, exento_por_permiso=True)
    if autorizacion_id is None:
        raise PermisoDenegado(
            f"Esta acción ('{accion}') requiere la autorización de otro empleado: PIN de supervisor "
            f"(POST /pos/autorizaciones, accion '{permiso}') o aprobación remota "
            "(POST /pos/solicitudes-autorizacion).",
            code="autorizacion_requerida",
            accion=accion,
            permiso_autorizacion=permiso,
            monto=str(monto) if monto is not None else None,
            vias=VIAS,
        )
    a = consumir_autorizacion(
        db, autorizacion_id, accion=permiso, sesion=sesion, entidad_tipo=entidad_tipo, entidad_id=entidad_id
    )
    return ResultadoPolitica(politica, autorizado_por_id=a.autorizado_por_id, autorizacion_id=a.id)
