"""Rutas de turnos y movimientos de caja. Solo validan, llaman al caso de uso (`app.aplicacion.turnos`) y responden.

POS (sesión dispositivo + PIN; la caja sale del dispositivo): /pos/turnos...
Supervisión: POST /cajas/turnos/{id}/cierre-forzado (POS o backoffice, permiso cajas.cierre_forzado).
CONTEO CIEGO: ningún endpoint con el turno abierto devuelve lo esperado; el informe existe solo con el turno cerrado.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Actor, Db, persistir_si_falla, requiere_permiso, sede_efectiva
from app.aplicacion import turnos as uc
from app.core.errores import PermisoDenegado, ReglaNegocio
from app.modules.cajas.models import MotivoMovimientoCaja

router = APIRouter(prefix="/pos", tags=["turnos"])
forzado_router = APIRouter(prefix="/cajas/turnos", tags=["turnos"])

PuedeAbrir = Annotated[Actor, Depends(requiere_permiso("cajas.turno.abrir", canal="pos"))]
PuedeCerrar = Annotated[Actor, Depends(requiere_permiso("cajas.turno.cerrar", canal="pos"))]
PuedeMover = Annotated[Actor, Depends(requiere_permiso("cajas.movimientos", canal="pos"))]
PuedeVer = Annotated[Actor, Depends(requiere_permiso("ventas.ver"))]
PuedeForzar = Annotated[Actor, Depends(requiere_permiso("cajas.cierre_forzado"))]
Dinero = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]


class AbrirTurnoIn(BaseModel):
    base_efectivo: Dinero = Field(ge=0, description="Efectivo inicial (sencillo) de la caja")


class TurnoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    caja_id: uuid.UUID
    estado: str
    abierto_por_id: uuid.UUID
    abierto_at: datetime
    base_efectivo: Dinero


class MovimientoIn(BaseModel):
    tipo: Literal["ingreso", "retiro"]
    valor: Dinero = Field(gt=0)
    motivo_codigo: str = Field(examples=["retiro_seguridad", "reposicion_cambio"])
    descripcion: str | None = Field(None, max_length=300)
    autorizacion_id: uuid.UUID | None = Field(
        None, description="Autorización 'pos.retirar_efectivo' (retiros sobre el umbral)"
    )


class MovimientoOut(BaseModel):
    id: uuid.UUID
    tipo: str
    valor: Dinero
    motivo_codigo: str
    descripcion: str | None
    created_at: datetime


class ConteoIn(BaseModel):
    medio_pago_codigo: str = Field(examples=["10", "48"])
    valor_contado: Dinero = Field(ge=0)


class CierreIn(BaseModel):
    conteo: list[ConteoIn] = Field(
        min_length=1,
        description="Lo CONTADO por medio de pago (el efectivo es obligatorio). No se muestra lo esperado.",
    )
    observaciones: str | None = Field(None, max_length=500)


class CierreForzadoIn(BaseModel):
    motivo: str = Field(min_length=5, max_length=300)
    conteo: list[ConteoIn] | None = Field(
        None, description="Opcional; sin conteo se cierra en lo esperado y queda marcado"
    )


def _conteo(items: list[ConteoIn] | None) -> dict[str, Decimal] | None:
    if items is None:
        return None
    d: dict[str, Decimal] = {}
    for c in items:
        if c.medio_pago_codigo in d:
            raise ReglaNegocio(f"El medio {c.medio_pago_codigo} está repetido en el conteo.", code="conteo_duplicado")
        d[c.medio_pago_codigo] = c.valor_contado
    return d


@router.post(
    "/turnos", response_model=TurnoOut, status_code=201, summary="Abre el turno de la caja de este dispositivo"
)
def abrir_turno(datos: AbrirTurnoIn, db: Db, actor: PuedeAbrir):
    return uc.abrir_turno(db, actor, datos.base_efectivo)


@router.get(
    "/turnos/actual",
    response_model=TurnoOut,
    summary="Turno abierto de la caja (sin esperados: conteo ciego)",
)
def turno_actual(db: Db, actor: PuedeAbrir):
    return uc.turno_actual(db, actor)


@router.post(
    "/turnos/actual/movimientos", response_model=MovimientoOut, status_code=201, summary="Ingreso o retiro de efectivo"
)
def registrar_movimiento(datos: MovimientoIn, db: Db, actor: PuedeMover):
    m = uc.registrar_movimiento_caja(
        db,
        actor,
        tipo=datos.tipo,
        valor=datos.valor,
        motivo_codigo=datos.motivo_codigo,
        descripcion=datos.descripcion,
        autorizacion_id=datos.autorizacion_id,
    )
    return MovimientoOut(
        id=m.id,
        tipo=m.tipo,
        valor=m.valor,
        motivo_codigo=datos.motivo_codigo,
        descripcion=m.descripcion,
        created_at=m.created_at,
    )


@router.get(
    "/turnos/actual/movimientos", response_model=list[MovimientoOut], summary="Movimientos de efectivo del turno"
)
def listar_movimientos(db: Db, actor: PuedeMover):
    return [
        MovimientoOut(
            id=m.id, tipo=m.tipo, valor=m.valor, motivo_codigo=c, descripcion=m.descripcion, created_at=m.created_at
        )
        for m, c in uc.listar_movimientos(db, actor)
    ]


@router.post(
    "/turnos/actual/cierre",
    response_model=dict[str, Any],
    summary="Cierra el turno con CONTEO CIEGO; devuelve el informe de cierre (con lo esperado)",
)
def cerrar_turno(datos: CierreIn, db: Db, actor: PuedeCerrar):
    with persistir_si_falla(db):  # un intento rechazado queda auditado
        return uc.cerrar_turno(
            db,
            actor,
            conteo=_conteo(datos.conteo),
            observaciones=datos.observaciones,
        )


def _sede_del_turno(db, actor: Actor):
    def comprobar(sede_id: uuid.UUID) -> None:
        if actor.pos is not None:
            if actor.pos.sede_id != sede_id:
                raise PermisoDenegado("El turno es de otra sede.", code="sede_no_asignada")
        else:
            sede_efectiva(db, actor, sede_id)

    return comprobar


@router.get(
    "/turnos/{turno_id}/informe-cierre",
    response_model=dict[str, Any],
    summary="Informe de cierre del turno (JSON listo para imprimir; solo turnos cerrados)",
)
def informe_cierre(turno_id: uuid.UUID, db: Db, actor: PuedeVer):
    return uc.informe_cierre(db, turno_id, _sede_del_turno(db, actor))


@forzado_router.post(
    "/{turno_id}/cierre-forzado",
    response_model=dict[str, Any],
    summary="Cierre forzado de un turno abandonado por un supervisor (cajas.cierre_forzado)",
)
def cierre_forzado(turno_id: uuid.UUID, datos: CierreForzadoIn, db: Db, actor: PuedeForzar):
    return uc.cierre_forzado(
        db,
        actor,
        turno_id,
        motivo=datos.motivo,
        conteo=_conteo(datos.conteo),
        sede_permitida=_sede_del_turno(db, actor),
    )


# ------------------------------------------------------------------------------------------------ catálogos para el POS
class MotivoOut(BaseModel):
    codigo: str
    nombre: str
    tipo: str | None = None


@router.get(
    "/motivos-movimiento-caja", response_model=list[MotivoOut], summary="Motivos de ingresos/retiros de efectivo"
)
def motivos_caja(db: Db, actor: PuedeMover):
    return [
        MotivoOut(codigo=m.codigo, nombre=m.nombre, tipo=m.tipo)
        for m in db.scalars(
            select(MotivoMovimientoCaja).where(MotivoMovimientoCaja.activo).order_by(MotivoMovimientoCaja.nombre)
        )
    ]
