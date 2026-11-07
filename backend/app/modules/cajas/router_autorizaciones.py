"""Aprobación remota de autorizaciones (0010).

POS:        POST /pos/solicitudes-autorizacion, GET /pos/solicitudes-autorizacion/{id} (polling cada `poll_ms`).
Backoffice: GET /autorizaciones/solicitudes, POST /autorizaciones/solicitudes/{id}/aprobar|rechazar
            (permiso `autorizaciones.aprobar`; quien aprueba debe ser OTRO empleado y tener el permiso de la acción).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Actor, Db, persistir_si_falla, requiere_permiso, sede_efectiva
from app.api.paginacion import Pag, Pagina, paginar
from app.core.errores import PermisoDenegado
from app.modules.cajas import solicitudes as svc

pos_router = APIRouter(prefix="/pos/solicitudes-autorizacion", tags=["autorizaciones"])
admin_router = APIRouter(prefix="/autorizaciones/solicitudes", tags=["autorizaciones"])

PideDesdePos = Annotated[Actor, Depends(requiere_permiso("pos.acceder", canal="pos"))]
Aprueba = Annotated[Actor, Depends(requiere_permiso("autorizaciones.aprobar"))]
Dinero = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]


class SolicitudIn(BaseModel):
    accion: str = Field(examples=["pos.devolver", "pos.cambiar_precio", "pos.retirar_efectivo"])
    monto: Dinero | None = Field(None, ge=0)
    motivo: str = Field(min_length=3, max_length=300)
    contexto: dict = Field(default_factory=dict, description="Lo que debe ver quien aprueba (venta, producto, etc.)")
    entidad_tipo: str | None = Field(None, max_length=40)
    entidad_id: uuid.UUID | None = None


class ResolucionIn(BaseModel):
    comentario: str | None = Field(None, max_length=300)


class SolicitudOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    estado: str
    accion: str
    monto: Dinero | None
    motivo: str
    contexto: dict
    entidad_tipo: str | None
    entidad_id: uuid.UUID | None
    caja_id: uuid.UUID | None
    solicitado_por_id: uuid.UUID
    expira_at: datetime
    resuelta_por_id: uuid.UUID | None
    resuelta_at: datetime | None
    comentario: str | None
    autorizacion_id: uuid.UUID | None = Field(
        None, description="Solo cuando estado='aprobada': de un solo uso, se pasa a la acción protegida"
    )
    created_at: datetime


class EstadoSolicitudOut(SolicitudOut):
    poll_ms: int = Field(svc.POLL_MS, description="Intervalo sugerido para volver a consultar mientras 'pendiente'")


@pos_router.post("", response_model=EstadoSolicitudOut, status_code=201, summary="Pide una aprobación remota")
def crear_solicitud(datos: SolicitudIn, db: Db, actor: PideDesdePos):
    s = svc.crear_solicitud(
        db,
        actor.pos,
        accion=datos.accion,
        monto=datos.monto,
        motivo=datos.motivo,
        contexto=datos.contexto,
        entidad_tipo=datos.entidad_tipo,
        entidad_id=datos.entidad_id,
    )
    return EstadoSolicitudOut.model_validate(s)


@pos_router.get(
    "/{solicitud_id}",
    response_model=EstadoSolicitudOut,
    summary="Estado de mi solicitud (polling); aprobada trae autorizacion_id",
)
def estado_solicitud(solicitud_id: uuid.UUID, db: Db, actor: PideDesdePos):
    return EstadoSolicitudOut.model_validate(svc.obtener_del_solicitante(db, actor.pos, solicitud_id))


def _sede_permitida(db, actor: Actor):
    def comprobar(sede_id: uuid.UUID) -> None:
        if actor.pos is not None and actor.pos.sede_id != sede_id:
            raise PermisoDenegado("La solicitud es de otra sede.", code="sede_no_asignada")
        sede_efectiva(db, actor, sede_id)

    return comprobar


@admin_router.get("", response_model=Pagina[SolicitudOut], summary="Solicitudes (por defecto las pendientes)")
def listar(
    db: Db,
    actor: Aprueba,
    pag: Pag,
    estado: Annotated[str | None, Query(description="pendiente | aprobada | rechazada | expirada")] = None,
    sede_id: Annotated[uuid.UUID | None, Query()] = None,
):
    sede = sede_efectiva(db, actor, sede_id)
    filas, total = paginar(db, svc.consulta_pendientes(db, sede, estado), pag)
    return Pagina[SolicitudOut](
        items=[SolicitudOut.model_validate(s) for s in filas], total=total, limit=pag.limit, offset=pag.offset
    )


@admin_router.post("/{solicitud_id}/aprobar", response_model=SolicitudOut, summary="Aprueba (genera la autorización)")
def aprobar(solicitud_id: uuid.UUID, datos: ResolucionIn, db: Db, actor: Aprueba):
    with persistir_si_falla(db):  # una aprobación tardía deja la solicitud 'expirada'
        s = svc.aprobar(db, solicitud_id, actor.empleado.id, datos.comentario, _sede_permitida(db, actor))
    return SolicitudOut.model_validate(s)


@admin_router.post("/{solicitud_id}/rechazar", response_model=SolicitudOut, summary="Rechaza la solicitud")
def rechazar(solicitud_id: uuid.UUID, datos: ResolucionIn, db: Db, actor: Aprueba):
    with persistir_si_falla(db):
        s = svc.rechazar(db, solicitud_id, actor.empleado.id, datos.comentario, _sede_permitida(db, actor))
    return SolicitudOut.model_validate(s)
