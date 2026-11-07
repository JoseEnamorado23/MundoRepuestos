"""Casos de uso de turnos y caja: `cajas` no conoce `ventas`, así que aquí se le pasan los totales del turno."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.cajas import turnos as svc
from app.modules.cajas.models import Caja, MovimientoCaja, Turno
from app.modules.ventas.servicios import totales_turno

SedePermitida = Callable[[uuid.UUID], None]


def abrir_turno(db: Session, actor, base_efectivo: Decimal) -> Turno:
    return svc.abrir_turno(db, actor.pos, base_efectivo)


def turno_actual(db: Session, actor) -> Turno:
    return svc.turno_actual(db, actor.pos)


def registrar_movimiento_caja(
    db: Session,
    actor,
    *,
    tipo: str,
    valor: Decimal,
    motivo_codigo: str,
    descripcion: str | None,
    autorizacion_id: uuid.UUID | None,
) -> MovimientoCaja:
    return svc.registrar_movimiento_caja(
        db,
        actor,
        tipo=tipo,
        valor=valor,
        motivo_codigo=motivo_codigo,
        descripcion=descripcion,
        autorizacion_id=autorizacion_id,
    )


def listar_movimientos(db: Session, actor) -> list[tuple[MovimientoCaja, str]]:
    return svc.listar_movimientos(db, svc.turno_actual(db, actor.pos).id)


def cerrar_turno(
    db: Session,
    actor,
    *,
    conteo: dict[str, Decimal],
    autorizacion_id: uuid.UUID | None,
    observaciones: str | None,
) -> dict:
    """Cierre con conteo ciego; devuelve el informe (con lo esperado). La diferencia de arqueo NUNCA bloquea."""
    turno = svc.bloquear_turno_del_cajero(db, actor.pos)
    t = svc.cerrar_turno(
        db,
        actor,
        turno,
        conteo=conteo,
        autorizacion_id=autorizacion_id,
        observaciones=observaciones,
        totales=totales_turno(db, turno.id),
    )
    return svc.informe_cierre(db, t.id, totales_turno(db, t.id))


def cierre_forzado(
    db: Session,
    actor,
    turno_id: uuid.UUID,
    *,
    motivo: str,
    conteo: dict[str, Decimal] | None,
    sede_permitida: SedePermitida,
) -> dict:
    turno, sede_id = svc.bloquear_turno_para_forzar(db, turno_id, sede_permitida, motivo)
    t = svc.cierre_forzado(
        db,
        turno,
        sede_id,
        supervisor_id=actor.empleado.id,
        motivo=motivo,
        conteo=conteo,
        totales=totales_turno(db, turno.id),
        dispositivo_id=actor.pos.dispositivo_id if actor.pos else None,
    )
    return svc.informe_cierre(db, t.id, totales_turno(db, t.id))


def informe_cierre(db: Session, turno_id: uuid.UUID, sede_permitida: SedePermitida) -> dict:
    t = db.get(Turno, turno_id)
    if t is not None:
        sede_permitida(db.get(Caja, t.caja_id).sede_id)
    return svc.informe_cierre(db, turno_id, totales_turno(db, turno_id))
