"""Casos de uso de ventas POS: confirmar (venta + factura electrónica `pendiente_envio`), espera, detalle y tirilla."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import ReglaNegocio
from app.modules.cajas.models import Caja
from app.modules.fiscal import servicios as fiscal
from app.modules.fiscal.models import DocumentoFiscal, ResolucionNumeracion
from app.modules.identidad.models import Empleado, Tercero
from app.modules.organizacion.models import Empresa, Sede
from app.modules.referencia.models import MedioPago
from app.modules.ventas import servicios as svc
from app.modules.ventas.models import Venta, VentaItem, VentaPago


@dataclass
class VentaDetalle:
    venta: Venta
    items: list[VentaItem]
    pagos: list[VentaPago]
    documento: DocumentoFiscal | None
    creada: bool = True
    cambio: Decimal = field(init=False)

    def __post_init__(self) -> None:
        self.cambio = sum((p.cambio_devuelto for p in self.pagos), Decimal("0.00"))


def _detalle(db: Session, venta: Venta, *, creada: bool = True) -> VentaDetalle:
    items, pagos = svc.lineas_y_pagos(db, venta.id)
    return VentaDetalle(venta, items, pagos, fiscal.fe_vigente_de_venta(db, venta.id), creada)


def confirmar_venta(db: Session, actor, datos) -> VentaDetalle:
    """Confirma la venta y, si es nueva, crea su factura electrónica (`pendiente_envio`; sin llamar a Factus)."""
    r = svc.confirmar_venta(db, actor, datos)
    if not r.creada:
        return _detalle(db, r.venta, creada=False)
    doc = fiscal.crear_fe_de_venta(db, r.venta, r.items, r.pagos, r.tercero, actor.empleado.id)
    return VentaDetalle(r.venta, r.items, r.pagos, doc, True)


def suspender_venta(db: Session, actor, datos) -> VentaDetalle:
    return _detalle(db, svc.suspender_venta(db, actor, datos))


def retomar_espera(db: Session, actor, venta_id: uuid.UUID) -> VentaDetalle:
    return _detalle(db, svc.obtener_espera(db, actor.pos, venta_id))


def detalle_venta(db: Session, venta_id: uuid.UUID, sede_id: uuid.UUID | None) -> VentaDetalle:
    return _detalle(db, svc.obtener_venta(db, venta_id, sede_id))


_LEYENDAS = {
    None: "Factura electrónica pendiente de validación ante la DIAN",
    "borrador": "Factura electrónica pendiente de validación ante la DIAN",
    "pendiente_envio": "Factura electrónica pendiente de validación ante la DIAN",
    "enviado": "Factura electrónica en validación ante la DIAN",
    "rechazado": "Factura electrónica en revisión: la tienda la regularizará ante la DIAN",
    "contingencia": "Factura en contingencia: se enviará a la DIAN cuando se restablezca el servicio",
}


def _estado_fiscal(doc: DocumentoFiscal | None) -> dict:
    """Estado fiscal para la tirilla y el POS: número, CUFE y QR cuando está aceptado; si no, una leyenda."""
    aceptado = doc is not None and doc.estado == "aceptado"
    return {
        "documento_id": doc.id if doc else None,
        "tipo": doc.tipo_documento_codigo if doc else None,
        "estado": doc.estado if doc else None,
        "numero_completo": doc.numero_completo if doc else None,
        "cufe": doc.cufe_cude if doc else None,
        "qr_data": doc.qr_data if doc else None,
        "leyenda": None if aceptado else _LEYENDAS.get(doc.estado if doc else None),
        "definitivo": aceptado,  # el POS deja de consultar cuando es True
    }


def estado_fiscal(db: Session, venta_id: uuid.UUID, sede_id: uuid.UUID | None) -> dict:
    """Consulta liviana para que el POS siga el estado de la FE después de confirmar la venta."""
    v = svc.obtener_venta(db, venta_id, sede_id)
    return {"venta_id": v.id, **_estado_fiscal(fiscal.fe_vigente_de_venta(db, v.id))}


def ticket(db: Session, venta_id: uuid.UUID, sede_id: uuid.UUID | None) -> dict:
    """Todos los datos de la tirilla (empresa, sede, resolución, ítems, impuestos, totales, pagos, estado fiscal)."""
    v = svc.obtener_venta(db, venta_id, sede_id)
    if v.estado != "confirmada":
        raise ReglaNegocio("Solo las ventas confirmadas tienen tirilla.", code="venta_no_confirmada")
    items, pagos = svc.lineas_y_pagos(db, v.id)
    sede = db.get(Sede, v.sede_id)
    empresa = db.get(Empresa, sede.empresa_id)
    caja = db.get(Caja, v.caja_id)
    cajero = db.get(Empleado, v.cajero_id) if v.cajero_id else None
    vendedor = db.get(Empleado, v.vendedor_id) if v.vendedor_id else None
    cliente = db.get(Tercero, v.tercero_id)
    doc = fiscal.fe_vigente_de_venta(db, v.id)
    res = db.get(ResolucionNumeracion, doc.resolucion_id) if doc else None
    medios = {m.codigo: m.nombre for m in db.scalars(select(MedioPago))}
    impuestos: dict[tuple[str, Decimal], list[Decimal]] = {}
    for i in items:
        a = impuestos.setdefault((i.impuesto_codigo, i.tarifa_pct), [Decimal("0"), Decimal("0")])
        a[0] += i.base_gravable
        a[1] += i.impuesto_valor

    def nombre(e: Empleado | None) -> str | None:
        return f"{e.nombres} {e.apellidos}" if e else None

    return {
        "empresa": {
            "nit": f"{empresa.nit}-{empresa.dv}",
            "razon_social": empresa.razon_social,
            "nombre_comercial": empresa.nombre_comercial,
            "direccion": empresa.direccion,
            "telefono": empresa.telefono,
        },
        "sede": {"codigo": sede.codigo, "nombre": sede.nombre, "direccion": sede.direccion, "telefono": sede.telefono},
        "caja": {"codigo": caja.codigo, "nombre": caja.nombre},
        "cajero": nombre(cajero),
        "vendedor": nombre(vendedor),
        "venta": {
            "id": v.id,
            "numero_interno": v.numero_interno,
            "numero_ticket": f"{caja.codigo}-{v.numero_interno:06d}",
            # Texto para imprimir como Code128 (juego B, ASCII imprimible): el escáner lo devuelve tal cual y con él
            # se busca la venta en las devoluciones. Incluye la caja porque `numero_interno` es consecutivo POR CAJA.
            "codigo_barras": f"{caja.codigo}-{v.numero_interno:06d}",
            "fecha": v.confirmada_at,
            "placa_vehiculo": v.placa_vehiculo,
        },
        "cliente": {
            "documento": cliente.numero_documento,
            "tipo_documento": cliente.tipo_documento_codigo,
            "nombre": cliente.nombre_completo,
            "es_consumidor_final": cliente.es_consumidor_final,
        },
        "resolucion": None
        if res is None
        else {
            "numero_resolucion": res.numero_resolucion,
            "fecha_resolucion": res.fecha_resolucion,
            "prefijo": res.prefijo,
            "rango_desde": res.rango_desde,
            "rango_hasta": res.rango_hasta,
            "vigente_desde": res.vigente_desde,
            "vigente_hasta": res.vigente_hasta,
        },
        "lineas": [
            {
                "linea": i.linea,
                "sku": i.sku,
                "descripcion": i.descripcion,
                "cantidad": i.cantidad,
                "unidad": i.unidad_codigo,
                "precio_unitario": i.precio_unitario,
                "descuento_valor": i.descuento_valor,
                "tarifa_pct": i.tarifa_pct,
                "total_linea": i.total_linea,
            }
            for i in items
        ],
        "impuestos": [
            {"codigo": c, "tarifa_pct": t, "base_gravable": b, "impuesto": imp}
            for (c, t), (b, imp) in sorted(impuestos.items())
        ],
        "totales": {
            "subtotal": v.subtotal,
            "descuento_total": v.descuento_total,
            "impuesto_total": v.impuesto_total,
            "redondeo": v.redondeo,
            "total": v.total,
        },
        "pagos": [
            {
                "medio_pago_codigo": p.medio_pago_codigo,
                "medio_pago": medios.get(p.medio_pago_codigo),
                "valor": p.valor,
                "valor_recibido": p.valor_recibido,
                "cambio_devuelto": p.cambio_devuelto,
                "referencia": p.referencia,
                "ultimos_digitos": p.ultimos_digitos,
            }
            for p in pagos
        ],
        "cambio_total": sum((p.cambio_devuelto for p in pagos), Decimal("0.00")),
        "fiscal": _estado_fiscal(doc),
    }
