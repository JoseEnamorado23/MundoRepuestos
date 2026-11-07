"""Creación de documentos fiscales (FE y NC) a partir de ventas y devoluciones confirmadas (modelo §12).

NO llama al proveedor (Factus): deja el documento en `pendiente_envio` con prefijo y consecutivo NULL (modo
`proveedor`: el número lo asigna Factus al responder). Se crea en la MISMA transacción que la venta/devolución:
nace `borrador`, se le cargan líneas, impuestos y pagos (snapshots autosuficientes) y pasa a `pendiente_envio`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dinero import r2
from app.core.errores import ReglaNegocio
from app.modules.auditoria.servicios import registrar_accion
from app.modules.fiscal.models import (
    DocumentoFiscal,
    DocumentoFiscalEvento,
    DocumentoFiscalImpuesto,
    DocumentoFiscalItem,
    DocumentoFiscalPago,
    ResolucionNumeracion,
)
from app.modules.identidad.models import Tercero, TerceroResponsabilidad
from app.modules.organizacion.models import Empresa, EmpresaResponsabilidad, Sede
from app.modules.sync.servicios import publicar_evento
from app.modules.ventas.models import Devolucion, DevolucionItem, DevolucionPago, Venta, VentaItem, VentaPago


def resolucion_para(
    db: Session, empresa_id: uuid.UUID, sede_id: uuid.UUID, caja_id: uuid.UUID | None, tipo: str
) -> ResolucionNumeracion:
    """Resolución activa y vigente del tipo: la de la caja, si no la de la sede, si no la de la empresa."""
    hoy = date.today()
    candidatas = db.scalars(
        select(ResolucionNumeracion).where(
            ResolucionNumeracion.empresa_id == empresa_id,
            ResolucionNumeracion.tipo_documento_codigo == tipo,
            ResolucionNumeracion.estado == "activa",
            ResolucionNumeracion.vigente_desde <= hoy,
            ResolucionNumeracion.vigente_hasta >= hoy,
        )
    ).all()
    for r in candidatas:
        if caja_id is not None and r.caja_id == caja_id:
            return r
    for r in candidatas:
        if r.caja_id is None and r.sede_id == sede_id:
            return r
    for r in candidatas:
        if r.caja_id is None and r.sede_id is None:
            return r
    raise ReglaNegocio(
        f"No hay una resolución de numeración activa y vigente para documentos {tipo} de esta caja. "
        "Pida al administrador registrarla (fiscal.resoluciones_numeracion).",
        code="sin_resolucion_fiscal",
    )


def _emisor(db: Session, empresa: Empresa, sede: Sede) -> dict:
    resp = list(
        db.scalars(
            select(EmpresaResponsabilidad.responsabilidad_codigo).where(EmpresaResponsabilidad.empresa_id == empresa.id)
        )
    )
    return {
        "nit": empresa.nit,
        "dv": empresa.dv,
        "razon_social": empresa.razon_social,
        "nombre_comercial": empresa.nombre_comercial,
        "tipo_persona_codigo": empresa.tipo_persona_codigo,
        "regimen_codigo": empresa.regimen_codigo,
        "responsabilidades": sorted(resp),
        "direccion": empresa.direccion,
        "municipio_codigo": empresa.municipio_codigo,
        "email": empresa.email,
        "telefono": empresa.telefono,
        "sede": {"codigo": sede.codigo, "nombre": sede.nombre, "direccion": sede.direccion},
    }


def snapshot_tercero(db: Session, t: Tercero) -> dict:
    resp = list(
        db.scalars(
            select(TerceroResponsabilidad.responsabilidad_codigo).where(TerceroResponsabilidad.tercero_id == t.id)
        )
    )
    return {
        "tercero_id": str(t.id),
        "tipo_documento_codigo": t.tipo_documento_codigo,
        "numero_documento": t.numero_documento,
        "dv": t.dv,
        "tipo_persona_codigo": t.tipo_persona_codigo,
        "nombre_completo": t.nombre_completo,
        "razon_social": t.razon_social,
        "regimen_codigo": t.regimen_codigo,
        "responsabilidades": sorted(resp),
        "email": t.email_facturacion,
        "telefono": t.telefono,
        "direccion": t.direccion_fiscal,
        "municipio_codigo": t.municipio_codigo,
        "es_consumidor_final": t.es_consumidor_final,
    }


def _hash(contenido: dict) -> str:
    canon = json.dumps(jsonable_encoder(contenido), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


def _publicar(db: Session, doc: DocumentoFiscal, actor_id: uuid.UUID | None, extra: dict) -> None:
    db.add(DocumentoFiscalEvento(documento_id=doc.id, tipo="creado", estado_resultante=doc.estado, created_by=actor_id))
    publicar_evento(
        db,
        "documento_fiscal",
        doc.id,
        "fiscal.emitir",
        {
            "documento_id": doc.id,
            "tipo": doc.tipo_documento_codigo,
            "estado": doc.estado,
            "venta_id": doc.venta_id,
            "devolucion_id": doc.devolucion_id,
            "documento_referenciado_id": doc.documento_referenciado_id,
            "total": doc.total,
            "reference_code": doc.id,
            **extra,
        },
        version=doc.version,
    )
    registrar_accion(
        db,
        "fiscal.documento_creado",
        actor_id=actor_id,
        sede_id=doc.sede_id,
        entidad_tipo="documento_fiscal",
        entidad_id=doc.id,
        despues={"tipo": doc.tipo_documento_codigo, "total": str(doc.total), "estado": doc.estado},
    )


def _cargar_hijos(db: Session, doc: DocumentoFiscal, lineas: list[dict], pagos: list[dict], actor_id) -> None:
    agrupado: dict[tuple[str, Decimal], list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for n, ln in enumerate(lineas, start=1):
        db.add(DocumentoFiscalItem(documento_id=doc.id, linea=n, created_by=actor_id, **ln))
        a = agrupado[(ln["tributo_codigo"], ln["tarifa_pct"])]
        a[0] += ln["base_gravable"]
        a[1] += ln["impuesto_valor"]
    for (tributo, tarifa), (base, imp) in agrupado.items():
        db.add(
            DocumentoFiscalImpuesto(
                documento_id=doc.id,
                tributo_codigo=tributo,
                tarifa_pct=tarifa,
                base_gravable=r2(base),
                impuesto_valor=r2(imp),
                created_by=actor_id,
            )
        )
    for n, p in enumerate(pagos, start=1):
        db.add(DocumentoFiscalPago(documento_id=doc.id, linea=n, created_by=actor_id, **p))
    db.flush()
    if r2(sum((i[1] for i in agrupado.values()), Decimal(0))) != doc.impuesto_total:
        raise ReglaNegocio("Los impuestos del documento no cuadran con sus líneas.", code="impuestos_descuadrados")


def crear_fe_de_venta(
    db: Session,
    venta: Venta,
    items: list[VentaItem],
    pagos: list[VentaPago],
    tercero: Tercero,
    actor_id: uuid.UUID | None,
) -> DocumentoFiscal:
    """FE en `pendiente_envio` (sin número) para una venta confirmada. Idempotente por venta."""
    previo = db.scalar(
        select(DocumentoFiscal).where(
            DocumentoFiscal.venta_id == venta.id,
            DocumentoFiscal.vigente.is_(True),
            DocumentoFiscal.tipo_documento_codigo.in_(("FE", "POS_E")),
        )
    )
    if previo is not None:
        return previo
    sede = db.get(Sede, venta.sede_id)
    empresa = db.get(Empresa, sede.empresa_id)
    resolucion = resolucion_para(db, empresa.id, sede.id, venta.caja_id, venta.tipo_documento_fiscal_codigo)
    emisor = _emisor(db, empresa, sede)
    adquirente = snapshot_tercero(db, tercero)
    lineas = [
        dict(
            venta_item_id=i.id,
            producto_id=i.producto_id,
            codigo=i.sku,
            descripcion=i.descripcion,
            unidad_codigo=i.unidad_codigo,
            cantidad=i.cantidad,
            precio_unitario=i.precio_unitario,
            valor_unitario_base=i.precio_unitario_base,
            descuento_valor=i.descuento_valor,
            base_gravable=i.base_gravable,
            impuesto_valor=i.impuesto_valor,
            total_linea=i.total_linea,
            tributo_codigo=i.tributo_codigo,
            tarifa_pct=i.tarifa_pct,
        )
        for i in sorted(items, key=lambda x: x.linea)
    ]
    pagos_doc = [dict(medio_pago_codigo=p.medio_pago_codigo, valor=p.valor, referencia=p.referencia) for p in pagos]
    contenido = {
        "tipo": venta.tipo_documento_fiscal_codigo,
        "fecha": venta.confirmada_at,
        "emisor": emisor,
        "adquirente": adquirente,
        "totales": [venta.subtotal, venta.descuento_total, venta.impuesto_total, venta.redondeo, venta.total],
        "lineas": [{k: v for k, v in ln.items() if k not in ("venta_item_id",)} for ln in lineas],
        "pagos": pagos_doc,
    }
    doc = DocumentoFiscal(
        empresa_id=empresa.id,
        sede_id=sede.id,
        caja_id=venta.caja_id,
        tipo_documento_codigo=venta.tipo_documento_fiscal_codigo,
        resolucion_id=resolucion.id,
        fecha_emision=venta.confirmada_at,
        venta_id=venta.id,
        forma_pago_codigo=venta.forma_pago_codigo,
        emisor_snapshot=jsonable_encoder(emisor),
        adquirente_tercero_id=tercero.id,
        adquirente_snapshot=jsonable_encoder(adquirente),
        adquirente_numero_documento=tercero.numero_documento,
        adquirente_nombre=tercero.nombre_completo,
        moneda=venta.moneda,
        subtotal=venta.subtotal,
        descuento_total=venta.descuento_total,
        impuesto_total=venta.impuesto_total,
        redondeo=venta.redondeo,
        total=venta.total,
        estado="borrador",
        hash_contenido=_hash(contenido),
        created_by=actor_id,
    )
    db.add(doc)
    db.flush()
    _cargar_hijos(db, doc, lineas, pagos_doc, actor_id)
    doc.estado = "pendiente_envio"
    db.flush()
    _publicar(db, doc, actor_id, {"numero_interno": venta.numero_interno})
    return doc


def crear_nc_de_devolucion(
    db: Session,
    devolucion: Devolucion,
    items: list[tuple[DevolucionItem, VentaItem]],
    pagos: list[DevolucionPago],
    venta: Venta,
    fe: DocumentoFiscal,
    concepto: str,
    actor_id: uuid.UUID | None,
) -> DocumentoFiscal:
    """NC en `pendiente_envio` que referencia la FE original. Idempotente por devolución."""
    previo = db.scalar(select(DocumentoFiscal).where(DocumentoFiscal.devolucion_id == devolucion.id))
    if previo is not None:
        return previo
    sede = db.get(Sede, devolucion.sede_id)
    empresa = db.get(Empresa, sede.empresa_id)
    caja_id = venta.caja_id if devolucion.turno_id is None else None
    # la NC se numera con la resolución NC de la caja que recibe la devolución (turno actual) si la hay
    if devolucion.turno_id is not None:
        from app.modules.cajas.models import Turno

        caja_id = db.get(Turno, devolucion.turno_id).caja_id
    resolucion = resolucion_para(db, empresa.id, sede.id, caja_id, "NC")
    emisor = fe.emisor_snapshot
    adquirente = fe.adquirente_snapshot
    lineas = []
    for di, vi in sorted(items, key=lambda x: x[1].linea):
        divisor = 1 + di.tarifa_pct / 100
        lineas.append(
            dict(
                devolucion_item_id=di.id,
                producto_id=di.producto_id,
                codigo=vi.sku,
                descripcion=vi.descripcion,
                unidad_codigo=vi.unidad_codigo,
                cantidad=di.cantidad,
                precio_unitario=di.precio_unitario,
                valor_unitario_base=(di.precio_unitario / divisor).quantize(Decimal("0.0001")),
                descuento_valor=di.descuento_valor,
                base_gravable=di.base_gravable,
                impuesto_valor=di.impuesto_valor,
                total_linea=di.total_linea,
                tributo_codigo=vi.tributo_codigo,
                tarifa_pct=di.tarifa_pct,
            )
        )
    pagos_doc = [dict(medio_pago_codigo=p.medio_pago_codigo, valor=p.valor, referencia=p.referencia) for p in pagos]
    descuento = r2(sum((ln["descuento_valor"] for ln in lineas), Decimal(0)))
    contenido = {
        "tipo": "NC",
        "referenciado": fe.id,
        "concepto": concepto,
        "fecha": devolucion.confirmada_at,
        "totales": [devolucion.subtotal, descuento, devolucion.impuesto_total, devolucion.redondeo, devolucion.total],
        "lineas": [{k: v for k, v in ln.items() if k != "devolucion_item_id"} for ln in lineas],
        "pagos": pagos_doc,
    }
    doc = DocumentoFiscal(
        empresa_id=empresa.id,
        sede_id=sede.id,
        caja_id=caja_id,
        tipo_documento_codigo="NC",
        resolucion_id=resolucion.id,
        fecha_emision=devolucion.confirmada_at,
        devolucion_id=devolucion.id,
        documento_referenciado_id=fe.id,
        concepto_nota_codigo=concepto,
        forma_pago_codigo=fe.forma_pago_codigo,
        emisor_snapshot=emisor,
        adquirente_tercero_id=fe.adquirente_tercero_id,
        adquirente_snapshot=adquirente,
        adquirente_numero_documento=fe.adquirente_numero_documento,
        adquirente_nombre=fe.adquirente_nombre,
        moneda=fe.moneda,
        subtotal=devolucion.subtotal,
        descuento_total=descuento,
        impuesto_total=devolucion.impuesto_total,
        redondeo=devolucion.redondeo,
        total=devolucion.total,
        estado="borrador",
        hash_contenido=_hash(contenido),
        created_by=actor_id,
    )
    db.add(doc)
    db.flush()
    _cargar_hijos(db, doc, lineas, pagos_doc, actor_id)
    doc.estado = "pendiente_envio"
    db.flush()
    _publicar(db, doc, actor_id, {"concepto_nota": concepto})
    return doc


def fe_vigente_de_venta(db: Session, venta_id: uuid.UUID) -> DocumentoFiscal | None:
    return db.scalar(
        select(DocumentoFiscal).where(
            DocumentoFiscal.venta_id == venta_id,
            DocumentoFiscal.vigente.is_(True),
            DocumentoFiscal.tipo_documento_codigo.in_(("FE", "POS_E")),
        )
    )


def crear_resolucion(
    db: Session,
    *,
    empresa_id: uuid.UUID,
    sede_id: uuid.UUID | None,
    caja_id: uuid.UUID | None,
    tipo: str,
    prefijo: str,
    rango_desde: int,
    rango_hasta: int,
    numero_resolucion: str,
    id_rango_proveedor: str,
    vigente_desde: date,
    vigente_hasta: date,
    actor_id: uuid.UUID | None = None,
) -> ResolucionNumeracion:
    """Resolución en modo `proveedor` (Factus). Usada por datos-demo; el alta real vendrá con el backoffice."""
    r = ResolucionNumeracion(
        empresa_id=empresa_id,
        sede_id=sede_id,
        caja_id=caja_id,
        modo_numeracion="proveedor",
        id_rango_proveedor=id_rango_proveedor,
        tipo_documento_codigo=tipo,
        numero_resolucion=numero_resolucion,
        fecha_resolucion=vigente_desde,
        prefijo=prefijo,
        rango_desde=rango_desde,
        rango_hasta=rango_hasta,
        consecutivo_actual=rango_desde - 1,
        vigente_desde=vigente_desde,
        vigente_hasta=vigente_hasta,
        estado="activa",
        created_by=actor_id,
    )
    db.add(r)
    db.flush()
    publicar_evento(
        db,
        "resolucion_numeracion",
        r.id,
        "resolucion_numeracion.creada",
        jsonable_encoder({"id": r.id, "tipo": tipo, "prefijo": prefijo, "caja_id": caja_id, "sede_id": sede_id}),
        version=r.version,
    )
    registrar_accion(
        db,
        "fiscal.resolucion_creada",
        actor_id=actor_id,
        sede_id=sede_id,
        entidad_tipo="resolucion_numeracion",
        entidad_id=r.id,
        despues={"tipo": tipo, "prefijo": prefijo, "rango": [rango_desde, rango_hasta]},
    )
    return r
