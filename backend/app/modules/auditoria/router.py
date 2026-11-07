"""Revisión posterior (0010): acciones ejecutadas bajo la política `revision_posterior` pendientes de revisar.

GET /revisiones, POST /revisiones/{id}/revisar (comentario obligatorio) y el reporte diario por fecha.
Permiso `revisiones.gestionar`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Actor, Db, requiere_permiso, sede_efectiva
from app.api.paginacion import Pag, Pagina, paginar
from app.core.errores import ReglaNegocio
from app.modules.auditoria import revisiones as svc

router = APIRouter(prefix="/revisiones", tags=["revisiones"])
Gestiona = Annotated[Actor, Depends(requiere_permiso("revisiones.gestionar"))]
Dinero = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]


class RevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sede_id: uuid.UUID
    accion: str
    entidad_tipo: str
    entidad_id: uuid.UUID | None
    monto: Dinero | None
    empleado_id: uuid.UUID | None
    detalle: dict
    estado: str
    revisada_por_id: uuid.UUID | None
    revisada_at: datetime | None
    comentario: str | None
    created_at: datetime


class RevisarIn(BaseModel):
    comentario: str = Field(min_length=3, max_length=500)


class ResumenAccionOut(BaseModel):
    accion: str
    cantidad: int
    monto_total: Dinero
    pendientes: int
    revisadas: int


class ReporteDiarioOut(BaseModel):
    sede_id: uuid.UUID
    fecha: date
    zona_horaria: str
    total: int
    pendientes: int
    revisadas: int
    por_accion: list[ResumenAccionOut]
    detalle: list[RevisionOut]


def _sede(db, actor: Actor, sede_id: uuid.UUID | None) -> uuid.UUID:
    s = sede_efectiva(db, actor, sede_id)
    if s is None:
        raise ReglaNegocio("Indique la sede (sede_id).", code="sede_requerida")
    return s


@router.get(
    "", response_model=Pagina[RevisionOut], summary="Acciones pendientes (o ya revisadas) de revisión posterior"
)
def listar(
    db: Db,
    actor: Gestiona,
    pag: Pag,
    estado: Annotated[str | None, Query(description="pendiente | revisada")] = "pendiente",
    accion: Annotated[str | None, Query(description="devolucion, retiro_caja, diferencia_arqueo...")] = None,
    empleado_id: Annotated[uuid.UUID | None, Query()] = None,
    fecha: Annotated[date | None, Query(description="Día calendario (America/Bogota)")] = None,
    sede_id: Annotated[uuid.UUID | None, Query()] = None,
):
    sede = _sede(db, actor, sede_id)
    filas, total = paginar(
        db, svc.consulta(sede, estado=estado, accion=accion, empleado_id=empleado_id, fecha=fecha), pag
    )
    return Pagina[RevisionOut](
        items=[RevisionOut.model_validate(r) for r in filas], total=total, limit=pag.limit, offset=pag.offset
    )


@router.get("/reporte-diario", response_model=ReporteDiarioOut, summary="Reporte de revisión del día (por acción)")
def reporte_diario(
    db: Db,
    actor: Gestiona,
    fecha: Annotated[date, Query(description="Día calendario (America/Bogota)")],
    sede_id: Annotated[uuid.UUID | None, Query()] = None,
):
    return ReporteDiarioOut.model_validate(
        svc.reporte_diario(db, _sede(db, actor, sede_id), fecha), from_attributes=True
    )


@router.post("/{revision_id}/revisar", response_model=RevisionOut, summary="Marca la acción como revisada")
def revisar(revision_id: uuid.UUID, datos: RevisarIn, db: Db, actor: Gestiona):
    def sede_permitida(sede_id: uuid.UUID) -> None:
        sede_efectiva(db, actor, sede_id)

    return RevisionOut.model_validate(
        svc.marcar_revisada(db, revision_id, actor.empleado.id, datos.comentario, sede_permitida)
    )
