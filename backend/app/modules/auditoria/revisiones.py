"""Revisión posterior (0010): acciones sensibles que se ejecutan sin bloquear y quedan pendientes de revisar.

`registrar` lo llaman los servicios cuando la política de la acción es `revision_posterior`. El backoffice las lista,
las marca como revisadas (con comentario) y consulta el reporte diario por fecha (día calendario de America/Bogota).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Select, cast, func, select
from sqlalchemy.orm import Session

from app.core.errores import Conflicto, NoEncontrado, ReglaNegocio
from app.core.utiles import snapshot
from app.modules.auditoria.models import Revision
from app.modules.auditoria.servicios import registrar_accion
from app.modules.sync.servicios import publicar_evento

ZONA = "America/Bogota"
CERO = Decimal("0.00")


def registrar(
    db: Session,
    *,
    sede_id: uuid.UUID,
    accion: str,
    entidad_tipo: str,
    entidad_id: uuid.UUID | None,
    monto: Decimal | None,
    empleado_id: uuid.UUID | None,
    dispositivo_id: uuid.UUID | None = None,
    detalle: dict | None = None,
) -> Revision:
    """Deja la acción pendiente de revisión. Idempotente por (acción, entidad)."""
    if entidad_id is not None:
        previa = db.scalar(select(Revision).where(Revision.accion == accion, Revision.entidad_id == entidad_id))
        if previa is not None:
            return previa
    rev = Revision(
        sede_id=sede_id,
        accion=accion,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
        monto=monto,
        empleado_id=empleado_id,
        dispositivo_id=dispositivo_id,
        detalle=detalle or {},
        created_by=empleado_id,
    )
    db.add(rev)
    db.flush()
    publicar_evento(db, "revision", rev.id, "revision.creada", snapshot(rev), version=rev.version)
    registrar_accion(
        db,
        "auditoria.revision_creada",
        actor_id=empleado_id,
        sede_id=sede_id,
        dispositivo_id=dispositivo_id,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
        despues={"accion": accion, "monto": str(monto) if monto is not None else None},
    )
    return rev


def _filtrada(
    sede_id: uuid.UUID | None,
    estado: str | None,
    accion: str | None,
    empleado_id: uuid.UUID | None,
    fecha: date | None,
) -> Select:
    q = select(Revision)
    if sede_id is not None:
        q = q.where(Revision.sede_id == sede_id)
    if estado is not None:
        q = q.where(Revision.estado == estado)
    if accion is not None:
        q = q.where(Revision.accion == accion)
    if empleado_id is not None:
        q = q.where(Revision.empleado_id == empleado_id)
    if fecha is not None:
        q = q.where(cast(func.timezone(ZONA, Revision.created_at), Date) == fecha)
    return q.order_by(Revision.created_at.desc(), Revision.id.desc())


def consulta(
    sede_id: uuid.UUID | None,
    *,
    estado: str | None = None,
    accion: str | None = None,
    empleado_id: uuid.UUID | None = None,
    fecha: date | None = None,
) -> Select:
    if estado is not None and estado not in ("pendiente", "revisada"):
        raise ReglaNegocio("El estado debe ser 'pendiente' o 'revisada'.", code="estado_invalido")
    return _filtrada(sede_id, estado, accion, empleado_id, fecha)


def marcar_revisada(
    db: Session, revision_id: uuid.UUID, revisor_id: uuid.UUID, comentario: str, sede_permitida=None
) -> Revision:
    rev = db.get(Revision, revision_id, with_for_update=True)
    if rev is None:
        raise NoEncontrado("Revisión no encontrada.")
    if sede_permitida is not None:
        sede_permitida(rev.sede_id)
    if rev.estado == "revisada":
        raise Conflicto("La revisión ya fue marcada como revisada.", code="ya_revisada")
    if not comentario or len(comentario.strip()) < 3:
        raise ReglaNegocio("El comentario de la revisión es obligatorio.", code="comentario_obligatorio")
    from app.core.seguridad import ahora

    rev.estado = "revisada"
    rev.revisada_por_id = revisor_id
    rev.revisada_at = ahora()
    rev.comentario = comentario.strip()
    db.flush()
    publicar_evento(db, "revision", rev.id, "revision.revisada", snapshot(rev), version=rev.version)
    registrar_accion(
        db,
        "auditoria.revision_revisada",
        actor_id=revisor_id,
        sede_id=rev.sede_id,
        entidad_tipo=rev.entidad_tipo,
        entidad_id=rev.entidad_id,
        despues={"accion": rev.accion, "comentario": rev.comentario},
    )
    return rev


def reporte_diario(db: Session, sede_id: uuid.UUID, fecha: date) -> dict:
    """Reporte de revisión de un día: totales por acción y el detalle."""
    filas = list(db.scalars(_filtrada(sede_id, None, None, None, fecha).order_by(None).order_by(Revision.created_at)))
    por_accion: dict[str, dict] = {}
    for r in filas:
        a = por_accion.setdefault(
            r.accion, {"accion": r.accion, "cantidad": 0, "monto_total": CERO, "pendientes": 0, "revisadas": 0}
        )
        a["cantidad"] += 1
        a["monto_total"] += r.monto or CERO
        a["pendientes" if r.estado == "pendiente" else "revisadas"] += 1
    return {
        "sede_id": sede_id,
        "fecha": fecha,
        "zona_horaria": ZONA,
        "total": len(filas),
        "pendientes": sum(1 for r in filas if r.estado == "pendiente"),
        "revisadas": sum(1 for r in filas if r.estado == "revisada"),
        "por_accion": sorted(por_accion.values(), key=lambda x: x["accion"]),
        "detalle": filas,
    }
