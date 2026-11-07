"""Consumo de autorizaciones de un solo uso (`identidad.autorizaciones`), compartido por todos los módulos.

Una autorización nace por PIN de supervisor (`cajas.servicios.crear_autorizacion`) o por aprobación remota
(`cajas.solicitudes.aprobar`); cualquier acción protegida la consume AQUÍ, sin depender de `cajas`.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.base import nodo_actual
from app.core.errores import Conflicto, NoEncontrado, PermisoDenegado, ReglaNegocio
from app.core.seguridad import ahora
from app.modules.auditoria.servicios import registrar_accion
from app.modules.identidad.models import Autorizacion, AutorizacionConsumo, Empleado


class SesionPosLike(Protocol):
    """Lo que los servicios necesitan de una sesión POS (la implementa `app.api.deps.SesionPos`)."""

    empleado: Empleado
    dispositivo_id: uuid.UUID
    caja_id: uuid.UUID
    sede_id: uuid.UUID


def consumir_autorizacion(
    db: Session,
    autorizacion_id: uuid.UUID,
    *,
    accion: str,
    sesion: SesionPosLike,
    entidad_tipo: str | None = None,
    entidad_id: uuid.UUID | None = None,
) -> Autorizacion:
    """La acción protegida llama a esto UNA vez. Valida acción, solicitante, dispositivo, entidad y vigencia, y
    marca el consumo de forma atómica (la PK de `autorizaciones_consumos` impide el segundo uso)."""
    a = db.get(Autorizacion, autorizacion_id)
    if a is None:
        raise NoEncontrado("Autorización no encontrada.", code="autorizacion_no_encontrada")
    if a.permiso_codigo != accion:
        raise ReglaNegocio("La autorización no corresponde a esta acción.", code="autorizacion_otra_accion")
    if a.solicitado_por_id != sesion.empleado.id or a.dispositivo_id != sesion.dispositivo_id:
        raise PermisoDenegado(
            "La autorización fue emitida para otro empleado o dispositivo.", code="autorizacion_ajena"
        )
    if a.entidad_id is not None and a.entidad_id != entidad_id:
        raise ReglaNegocio("La autorización es para otro documento.", code="autorizacion_otra_entidad")
    if a.expira_at <= ahora():
        raise ReglaNegocio("La autorización venció; solicite una nueva.", code="autorizacion_vencida")
    res = db.execute(
        pg_insert(AutorizacionConsumo)
        .values(
            autorizacion_id=a.id,
            consumida_por_id=sesion.empleado.id,
            dispositivo_id=sesion.dispositivo_id,
            entidad_tipo=entidad_tipo,
            entidad_id=entidad_id,
            nodo_origen_id=nodo_actual(),
        )
        .on_conflict_do_nothing(index_elements=["autorizacion_id"])
        .returning(AutorizacionConsumo.autorizacion_id)
    )
    if res.scalar_one_or_none() is None:
        raise Conflicto("La autorización ya fue utilizada.", code="autorizacion_consumida")
    registrar_accion(
        db,
        "pos.autorizacion_consumida",
        actor_id=sesion.empleado.id,
        sede_id=sesion.sede_id,
        dispositivo_id=sesion.dispositivo_id,
        autorizacion_id=a.id,
        autorizado_por_id=a.autorizado_por_id,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
    )
    return a
