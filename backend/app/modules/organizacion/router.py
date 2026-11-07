"""Políticas de autorización por acción de la sede (0010): GET/PUT /organizacion/politicas-autorizacion/{sede_id}."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import Actor, Db, requiere_permiso, sede_efectiva
from app.modules.auditoria.servicios import registrar_accion
from app.modules.organizacion import politicas

router = APIRouter(prefix="/organizacion/politicas-autorizacion", tags=["organizacion"])
Configura = Annotated[Actor, Depends(requiere_permiso("admin.configuracion"))]


class PoliticaIn(BaseModel):
    politica: Literal["libre", "revision_posterior", "requiere_autorizacion"]
    umbral: int | None = Field(None, ge=0, description="COP: por encima de este monto aplica 'sobre_umbral'")
    sobre_umbral: Literal["libre", "revision_posterior", "requiere_autorizacion"] | None = None


@router.get("/{sede_id}", response_model=dict[str, dict], summary="Política efectiva de cada una de las 7 acciones")
def ver(sede_id: uuid.UUID, db: Db, actor: Configura):
    sede_efectiva(db, actor, sede_id)
    return politicas.listar(db, sede_id)


@router.put(
    "/{sede_id}/{accion}",
    response_model=dict,
    summary="Cambia la política de una acción (las de inventario se gobiernan con inventario.umbral_aprobacion)",
)
def cambiar(sede_id: uuid.UUID, accion: str, datos: PoliticaIn, db: Db, actor: Configura):
    sede_efectiva(db, actor, sede_id)
    antes = politicas.configuracion_de(db, sede_id, accion) if accion in politicas.ACCIONES else None
    nuevo = politicas.escribir(db, sede_id, accion, datos.model_dump(exclude_none=True), actor.empleado.id)
    registrar_accion(
        db,
        "organizacion.politica_autorizacion_cambiada",
        actor_id=actor.empleado.id,
        sede_id=sede_id,
        entidad_tipo="politica_autorizacion",
        antes={"accion": accion, **(antes or {})},
        despues={"accion": accion, **nuevo},
    )
    return nuevo
