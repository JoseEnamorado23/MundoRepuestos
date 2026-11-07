"""Rutas de ventas POS, ventas en espera, devoluciones y terceros rápidos (/pos/...).

Los routers solo validan la entrada, llaman al caso de uso (`app.aplicacion`) y responden.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import Actor, Db, requiere_permiso, sede_efectiva
from app.api.paginacion import Pag, Pagina, paginar
from app.aplicacion import devoluciones as uc_dev
from app.aplicacion import turnos as uc_turnos
from app.aplicacion import ventas as uc
from app.aplicacion.devoluciones import DevolucionDetalle
from app.aplicacion.ventas import VentaDetalle
from app.core.errores import ReglaNegocio
from app.modules.ventas import servicios as svc
from app.modules.ventas.models import MotivoDevolucion
from app.modules.ventas.schemas import (
    DevolucionIn,
    DevolucionOut,
    DocumentoResumenOut,
    EsperaIn,
    TerceroOut,
    TerceroRapidoIn,
    VentaIn,
    VentaOut,
    VentaResumenOut,
)


class MotivoOut(BaseModel):
    codigo: str
    nombre: str
    requiere_autorizacion: bool


router = APIRouter(prefix="/pos", tags=["ventas"])
Vende = Annotated[Actor, Depends(requiere_permiso("pos.vender", canal="pos"))]
Ve = Annotated[Actor, Depends(requiere_permiso("ventas.ver"))]


def _doc(doc) -> DocumentoResumenOut | None:
    return DocumentoResumenOut.model_validate(doc) if doc else None


def _venta_out(d: VentaDetalle, repetida: bool = False) -> VentaOut:
    v = d.venta
    return VentaOut.model_validate(
        {
            **{c: getattr(v, c) for c in VentaOut.model_fields if hasattr(v, c) and c not in ("lineas", "pagos")},
            "lineas": d.items,
            "pagos": d.pagos,
            "cambio": d.cambio,
            "documento_fiscal": _doc(d.documento),
            "repetida": repetida,
        },
        from_attributes=True,
    )


def _resumen(v, cliente: str | None = None) -> VentaResumenOut:
    return VentaResumenOut.model_validate(
        {**{c: getattr(v, c) for c in VentaResumenOut.model_fields if c != "cliente"}, "cliente": cliente}
    )


def _sede(db, actor: Actor, sede_id: uuid.UUID | None) -> uuid.UUID:
    s = sede_efectiva(db, actor, sede_id)
    if s is None:
        raise ReglaNegocio("Indique la sede (sede_id).", code="sede_requerida")
    return s


# ------------------------------------------------------------------------------------------------ ventas
@router.post(
    "/ventas",
    response_model=VentaOut,
    status_code=201,
    summary="Confirma una venta COMPLETA (idempotente por id). 201 = creada; 200 = el id ya existía",
)
def confirmar_venta(datos: VentaIn, db: Db, actor: Vende, response: Response) -> VentaOut:
    d = uc.confirmar_venta(db, actor, datos)
    if not d.creada:
        response.status_code = 200
    return _venta_out(d, repetida=not d.creada)


@router.get(
    "/ventas",
    response_model=Pagina[VentaResumenOut],
    summary="Ventas confirmadas (del turno actual, por nº interno, cliente, vendedor o cajero)",
)
def listar_ventas(
    db: Db,
    actor: Ve,
    pag: Pag,
    turno_id: Annotated[uuid.UUID | None, Query()] = None,
    turno_actual: Annotated[bool, Query(description="Solo las del turno abierto de esta caja (POS)")] = False,
    q: Annotated[str | None, Query(description="Nº interno exacto, o texto del nombre/documento del cliente")] = None,
    vendedor_id: Annotated[uuid.UUID | None, Query(description="Solo las armadas por este vendedor")] = None,
    cajero_id: Annotated[uuid.UUID | None, Query(description="Solo las cobradas por este cajero")] = None,
    sede_id: Annotated[uuid.UUID | None, Query(description="Backoffice: sede a consultar")] = None,
):
    sede = _sede(db, actor, sede_id)
    caja_id = None
    if turno_actual:
        if actor.pos is None:
            raise ReglaNegocio("'turno_actual' solo aplica con sesión POS.", code="canal_no_permitido")
        turno_id = uc_turnos.turno_actual(db, actor).id
    elif actor.pos is not None and turno_id is None:
        caja_id = actor.pos.caja_id  # el POS ve las ventas de su caja
    consulta = svc.consulta_ventas(
        db, sede, turno_id=turno_id, q=q, caja_id=caja_id, vendedor_id=vendedor_id, cajero_id=cajero_id
    )
    filas, total = paginar(db, consulta, pag, scalars=False)
    return Pagina[VentaResumenOut](
        items=[_resumen(v, cli) for v, cli in filas], total=total, limit=pag.limit, offset=pag.offset
    )


# --- ventas en espera (antes de /ventas/{id} para que 'espera' no se lea como id) ---
@router.post(
    "/ventas/espera",
    response_model=VentaOut,
    status_code=201,
    summary="Suspende un carrito (sin inventario ni numeración; no exige turno abierto)",
)
def suspender(datos: EsperaIn, db: Db, actor: Vende) -> VentaOut:
    return _venta_out(uc.suspender_venta(db, actor, datos))


@router.get(
    "/ventas/espera",
    response_model=list[VentaResumenOut],
    summary="Ventas en espera de la sede (se retoman en cualquier caja)",
)
def listar_espera(
    db: Db,
    actor: Vende,
    solo_mias: Annotated[bool, Query(description="Solo las que armé yo (vendedor)")] = False,
):
    return [_resumen(v) for v in svc.listar_espera(db, actor.pos, solo_mias=solo_mias)]


@router.get(
    "/ventas/espera/{venta_id}", response_model=VentaOut, summary="Retoma una venta en espera (carrito recalculado)"
)
def obtener_espera(venta_id: uuid.UUID, db: Db, actor: Vende) -> VentaOut:
    return _venta_out(uc.retomar_espera(db, actor, venta_id))


@router.delete("/ventas/espera/{venta_id}", status_code=204, summary="Descarta una venta en espera")
def descartar_espera(venta_id: uuid.UUID, db: Db, actor: Vende) -> Response:
    svc.descartar_espera(db, actor.pos, venta_id)
    return Response(status_code=204)


@router.get("/ventas/{venta_id}", response_model=VentaOut, summary="Detalle de una venta")
def detalle_venta(
    venta_id: uuid.UUID, db: Db, actor: Ve, sede_id: Annotated[uuid.UUID | None, Query()] = None
) -> VentaOut:
    return _venta_out(uc.detalle_venta(db, venta_id, _sede(db, actor, sede_id)))


@router.get(
    "/ventas/{venta_id}/ticket",
    response_model=dict[str, Any],
    summary="Todos los datos de la tirilla (empresa, sede, resolución, ítems, impuestos, totales, pagos, estado fiscal)",
)
def ticket(venta_id: uuid.UUID, db: Db, actor: Ve, sede_id: Annotated[uuid.UUID | None, Query()] = None):
    return uc.ticket(db, venta_id, _sede(db, actor, sede_id))


# ------------------------------------------------------------------------------------------------ devoluciones
def _devolucion_out(d: DevolucionDetalle, repetida: bool = False) -> DevolucionOut:
    dev = d.devolucion
    return DevolucionOut.model_validate(
        {
            "id": dev.id,
            "venta_id": dev.venta_id,
            "estado": dev.estado,
            "turno_id": dev.turno_id,
            "subtotal": dev.subtotal,
            "impuesto_total": dev.impuesto_total,
            "total": dev.total,
            "confirmada_at": dev.confirmada_at,
            "lineas": d.items,
            "reembolsos": d.pagos,
            "documento_fiscal": _doc(d.nota_credito),
            "repetida": repetida,
        },
        from_attributes=True,
    )


@router.post(
    "/devoluciones",
    response_model=DevolucionOut,
    status_code=201,
    summary="Devolución parcial o total (política 'devolucion': libre hasta el umbral; reembolso; nota crédito)",
)
def crear_devolucion(datos: DevolucionIn, db: Db, actor: Vende, response: Response) -> DevolucionOut:
    d = uc_dev.registrar_devolucion(db, actor, datos)
    if not d.creada:
        response.status_code = 200
    return _devolucion_out(d, repetida=not d.creada)


@router.get("/devoluciones/{devolucion_id}", response_model=DevolucionOut, summary="Detalle de una devolución")
def detalle_devolucion(
    devolucion_id: uuid.UUID, db: Db, actor: Ve, sede_id: Annotated[uuid.UUID | None, Query()] = None
):
    return _devolucion_out(uc_dev.detalle_devolucion(db, devolucion_id, _sede(db, actor, sede_id)))


@router.get("/motivos-devolucion", response_model=list[MotivoOut], summary="Motivos de devolución")
def motivos_devolucion(db: Db, actor: Ve):
    return [
        MotivoOut(codigo=m.codigo, nombre=m.nombre, requiere_autorizacion=m.requiere_autorizacion)
        for m in db.scalars(select(MotivoDevolucion).where(MotivoDevolucion.activo).order_by(MotivoDevolucion.nombre))
    ]


# ------------------------------------------------------------------------------------------------ terceros
@router.get("/terceros", response_model=list[TerceroOut], summary="Búsqueda rápida de clientes por documento o texto")
def buscar_terceros(
    db: Db,
    actor: Vende,
    documento: Annotated[str | None, Query(description="Número de documento exacto")] = None,
    q: Annotated[str | None, Query(description="Nombre o inicio del documento")] = None,
):
    return svc.buscar_terceros(db, documento=documento, q=q)


@router.post(
    "/terceros",
    response_model=TerceroOut,
    status_code=201,
    summary="Alta rápida de cliente con lo mínimo para facturar (200 si el documento ya existía)",
)
def crear_tercero(datos: TerceroRapidoIn, db: Db, actor: Vende, response: Response):
    t, creado = svc.crear_tercero_rapido(db, actor, datos)
    if not creado:
        response.status_code = 200
    return t
