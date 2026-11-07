"""Casos de uso de devoluciones: registrar (kardex, reembolso, nota crédito `pendiente_envio`) y consultar."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import NoEncontrado, ReglaNegocio
from app.modules.fiscal import servicios as fiscal
from app.modules.fiscal.models import DocumentoFiscal
from app.modules.ventas import devoluciones as svc
from app.modules.ventas.models import Devolucion, DevolucionItem, DevolucionPago


@dataclass
class DevolucionDetalle:
    devolucion: Devolucion
    items: list[DevolucionItem]
    pagos: list[DevolucionPago]
    nota_credito: DocumentoFiscal | None
    creada: bool = True


def _detalle(db: Session, dev: Devolucion, *, creada: bool = True) -> DevolucionDetalle:
    items, pagos = svc.detalle_devolucion(db, dev)
    nc = db.scalar(select(DocumentoFiscal).where(DocumentoFiscal.devolucion_id == dev.id))
    return DevolucionDetalle(dev, items, pagos, nc, creada)


def registrar_devolucion(db: Session, actor, datos) -> DevolucionDetalle:
    """Registra la devolución y, si es nueva, crea la nota crédito de la factura vigente de la venta."""
    r = svc.confirmar_devolucion(db, actor, datos)
    if not r.creada:
        return _detalle(db, r.devolucion, creada=False)
    fe = fiscal.fe_vigente_de_venta(db, r.venta.id)
    if fe is None:
        raise ReglaNegocio(
            "La venta no tiene una factura electrónica vigente que corregir.", code="sin_documento_fiscal"
        )
    fiscal.crear_nc_de_devolucion(
        db, r.devolucion, r.pares, r.pagos, r.venta, fe, "2" if r.anulacion_total else "1", actor.empleado.id
    )
    return _detalle(db, r.devolucion)


def detalle_devolucion(db: Session, devolucion_id: uuid.UUID, sede_id: uuid.UUID) -> DevolucionDetalle:
    d = db.get(Devolucion, devolucion_id)
    if d is None or d.sede_id != sede_id:
        raise NoEncontrado("Devolución no encontrada.")
    return _detalle(db, d)
