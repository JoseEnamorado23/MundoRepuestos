"""Rutas de cajas/POS: dispositivos (/cajas/dispositivos), login del POS (/pos/auth/pin), autorizaciones."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Actor, Db, SesionPosActual, persistir_si_falla, requiere_permiso
from app.modules.cajas import servicios as svc
from app.modules.identidad.servicios import permisos_de
from app.modules.organizacion import configuracion as cfg_sede

dispositivos_router = APIRouter(prefix="/cajas/dispositivos", tags=["cajas"])
pos_router = APIRouter(prefix="/pos", tags=["pos"])
GestionaDispositivos = Annotated[Actor, Depends(requiere_permiso("cajas.dispositivos.gestionar", canal="backoffice"))]


# ---------------------------------------------------------------------------------- esquemas
class DispositivoCrearIn(BaseModel):
    caja_id: uuid.UUID
    nombre: str = Field(min_length=1, max_length=120)


class DispositivoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sede_id: uuid.UUID
    caja_id: uuid.UUID | None
    nombre: str
    estado: str
    created_at: datetime
    revocado_at: datetime | None = None


class DispositivoCreadoOut(DispositivoOut):
    token: str = Field(description="Token del dispositivo. SE MUESTRA UNA SOLA VEZ; en la BD solo queda su SHA-256.")


class PinLoginIn(BaseModel):
    pin: str | None = Field(None, max_length=20)
    codigo_carne: str | None = Field(None, max_length=60)


class SesionPosOut(BaseModel):
    token: str
    token_type: Literal["bearer"] = "bearer"
    expira_en: int
    empleado_id: uuid.UUID
    empleado_nombre: str
    dispositivo_id: uuid.UUID
    caja_id: uuid.UUID
    sede_id: uuid.UUID
    permisos: list[str] = Field(default_factory=list, description="Permisos del empleado (para habilitar pantallas).")
    redondeo_efectivo: int = Field(
        0, description="Unidad de redondeo del pago 100 % en efectivo en esta sede (0 = sin redondeo, 50 o 100)."
    )


class AutorizacionIn(BaseModel):
    pin: str = Field(max_length=20, description="PIN del supervisor")
    accion: str = Field(examples=["pos.descuento_mayor"])
    entidad_tipo: str | None = None
    entidad_id: uuid.UUID | None = None
    detalle: dict = Field(default_factory=dict, description="Contexto (p. ej. porcentaje de descuento)")
    motivo: str | None = Field(None, max_length=300)


class AutorizacionOut(BaseModel):
    autorizacion_id: uuid.UUID
    accion: str
    expira_at: datetime
    supervisor_id: uuid.UUID


# ---------------------------------------------------------------------------------- dispositivos
@dispositivos_router.post(
    "",
    response_model=DispositivoCreadoOut,
    status_code=201,
    summary="Registra un dispositivo POS (el token se muestra una sola vez)",
)
def crear_dispositivo(datos: DispositivoCrearIn, db: Db, actor: GestionaDispositivos) -> DispositivoCreadoOut:
    disp, token = svc.crear_dispositivo(db, datos.caja_id, datos.nombre, actor.empleado.id)
    return DispositivoCreadoOut.model_validate({**DispositivoOut.model_validate(disp).model_dump(), "token": token})


@dispositivos_router.get("", response_model=list[DispositivoOut], summary="Lista dispositivos (sin tokens)")
def listar_dispositivos(db: Db, _: GestionaDispositivos, caja_id: Annotated[uuid.UUID | None, Query()] = None):
    return svc.listar_dispositivos(db, caja_id)


@dispositivos_router.post("/{dispositivo_id}/revocar", response_model=DispositivoOut, summary="Revoca un dispositivo")
def revocar_dispositivo(dispositivo_id: uuid.UUID, db: Db, actor: GestionaDispositivos):
    return svc.revocar_dispositivo(db, dispositivo_id, actor.empleado.id)


# ---------------------------------------------------------------------------------- POS
@pos_router.post(
    "/auth/pin",
    response_model=SesionPosOut,
    summary="Inicia sesión en el POS con PIN o código de carné (requiere X-Dispositivo-Token)",
)
def login_pos(
    datos: PinLoginIn,
    db: Db,
    x_dispositivo_token: Annotated[str | None, Header(alias="X-Dispositivo-Token")] = None,
) -> SesionPosOut:
    with persistir_si_falla(db):  # cada intento fallido queda auditado y cuenta para el bloqueo
        emp, disp, token, expira_en = svc.autenticar_pos(db, x_dispositivo_token, datos.pin, datos.codigo_carne)
    return SesionPosOut(
        token=token,
        expira_en=expira_en,
        empleado_id=emp.id,
        empleado_nombre=f"{emp.nombres} {emp.apellidos}",
        dispositivo_id=disp.id,
        caja_id=disp.caja_id,
        sede_id=disp.sede_id,
        permisos=sorted(permisos_de(db, emp.id)),
        redondeo_efectivo=int(cfg_sede.obtener(db, disp.sede_id, "ventas.redondeo_efectivo") or 0),
    )


@pos_router.post(
    "/autorizaciones",
    response_model=AutorizacionOut,
    status_code=201,
    summary="Autorización de supervisor por PIN: devuelve un autorizacion_id de un solo uso",
)
def crear_autorizacion(datos: AutorizacionIn, db: Db, sesion: SesionPosActual) -> AutorizacionOut:
    with persistir_si_falla(db):
        a = svc.crear_autorizacion(
            db,
            sesion,
            pin=datos.pin,
            accion=datos.accion,
            entidad_tipo=datos.entidad_tipo,
            entidad_id=datos.entidad_id,
            detalle=datos.detalle,
            motivo=datos.motivo,
        )
    return AutorizacionOut(
        autorizacion_id=a.id, accion=a.permiso_codigo, expira_at=a.expira_at, supervisor_id=a.autorizado_por_id
    )
