"""Emisión de documentos fiscales al proveedor tecnológico (lo ejecuta el worker `python -m app.workers.fiscal`).

Cola = eventos `fiscal.emitir` de `sync.outbox_eventos` (los publica `servicios.crear_*` en la MISMA transacción que la
venta o la devolución). Estados del evento: `pendiente` (por procesar), `enviado` (el proveedor lo recibió pero la DIAN
aún no valida), `confirmado` (documento aceptado) y `fallido` (rechazado o con reintentos agotados).

Cada documento se procesa en UNA transacción que conserva `FOR UPDATE SKIP LOCKED` sobre el evento y el documento
mientras dura la llamada: dos workers nunca procesan el mismo documento. Si el proceso muere a mitad de la llamada no se
registra nada y el evento se reintenta; el `reference_code` (= id del documento) hace que el reenvío devuelva el MISMO
documento del proveedor, así que nunca se emite un duplicado.

Clasificación de la respuesta del proveedor:
* aceptado               -> `aceptado` (número, CUFE, QR, fechas, PDF); evento `confirmado`;
* enviado sin validar    -> `enviado`; se consulta de nuevo con backoff corto (cuenta como intento);
* `RechazoValidacion`    -> `rechazado`; NO se reintenta solo; alerta para el backoffice;
* `ErrorTransitorio`     -> sigue `pendiente_envio`; backoff exponencial con jitter hasta `fiscal_max_intentos`; al
                            agotarse: evento `fallido`, alerta `reintentos_agotados`;
* `ConflictoPendiente`   -> como transitorio, pero antes se intenta borrar en el proveedor el documento NO validado;
* `ErrorConfiguracion`   -> como transitorio, con alerta `configuracion` desde el primer fallo.
Una nota crédito espera a que su factura esté `aceptada`.
"""

from __future__ import annotations

import logging
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.almacenamiento import Almacenamiento
from app.core.config import Settings
from app.modules.auditoria.servicios import registrar_accion
from app.modules.fiscal.models import (
    AlertaFiscal,
    DocumentoFiscal,
    DocumentoFiscalEvento,
    DocumentoFiscalItem,
    DocumentoFiscalPago,
    ResolucionNumeracion,
)
from app.modules.fiscal.proveedores.base import (
    ConflictoPendiente,
    DocumentoEmision,
    ErrorConfiguracion,
    ErrorProveedor,
    ErrorTransitorio,
    LineaEmision,
    PagoEmision,
    ProveedorFiscal,
    RechazoValidacion,
    RespuestaProveedor,
)
from app.modules.sync.models import OutboxEvento
from app.modules.sync.servicios import publicar_evento
from app.modules.ventas.models import Venta

log = logging.getLogger("fiscal.emision")
EVENTO = "fiscal.emitir"
ESPERA_FACTURA_SEG = 15  # una NC cuya FE aún no está aceptada vuelve a mirarse cada tanto (sin gastar intentos)
ESPERA_FACTURA_RECHAZADA_SEG = 300
ESPERA_VALIDACION_SEG = 15  # el proveedor recibió el documento pero la DIAN no ha validado
_NUMERO = re.compile(r"^([A-Za-z]*)(\d+)$")


@dataclass
class Resultado:
    documento_id: uuid.UUID
    accion: str  # aceptado | enviado | rechazado | reintento | agotado | esperando_factura | omitido
    detalle: str | None = None


# ------------------------------------------------------------------------------------------------ utilidades
def espera_backoff(intento: int, cfg: Settings, rng: random.Random | None = None) -> float:
    """Segundos hasta el siguiente intento: base x 2^(intento-1), tope `max`, con «jitter» en [50 %, 100 %]."""
    r = rng or random
    bruto = min(cfg.fiscal_backoff_max_seg, cfg.fiscal_backoff_base_seg * (2 ** max(0, intento - 1)))
    return bruto * (0.5 + r.random() / 2)


def partir_numero(numero: str, prefijo_resolucion: str) -> tuple[str, int]:
    """«SETP990034490» -> («SETP», 990034490), usando el prefijo de la resolución si coincide."""
    if prefijo_resolucion and numero.startswith(prefijo_resolucion) and numero[len(prefijo_resolucion) :].isdigit():
        return prefijo_resolucion, int(numero[len(prefijo_resolucion) :])
    m = _NUMERO.match(numero)
    if not m:
        raise ErrorConfiguracion(f"El número «{numero}» del proveedor no tiene el formato prefijo+dígitos.")
    return m.group(1), int(m.group(2))


def _clave_archivo(doc: DocumentoFiscal, extension: str) -> str:
    return f"fiscal/{doc.empresa_id}/{doc.fecha_emision:%Y}/{doc.id}.{extension}"


def _resumen_error(e: ErrorProveedor, tope: int = 500) -> str:
    texto = e.mensaje
    errores = getattr(e, "errores", None) or e.detalle.get("errors")
    if errores:
        texto += " | " + "; ".join(str(x) for x in errores)
    return texto[:tope]


def abrir_alerta(
    db: Session, doc: DocumentoFiscal, tipo: str, mensaje: str, detalle: dict | None = None
) -> AlertaFiscal:
    """Una sola alerta ABIERTA por (documento, tipo): si ya existe se actualiza en vez de duplicarla."""
    previa = db.scalar(
        select(AlertaFiscal).where(
            AlertaFiscal.documento_id == doc.id, AlertaFiscal.tipo == tipo, AlertaFiscal.estado == "abierta"
        )
    )
    if previa is not None:
        previa.mensaje, previa.detalle = mensaje[:1000], detalle or previa.detalle
        return previa
    a = AlertaFiscal(documento_id=doc.id, sede_id=doc.sede_id, tipo=tipo, mensaje=mensaje[:1000], detalle=detalle or {})
    db.add(a)
    db.flush()
    return a


def resolver_alertas(
    db: Session, doc: DocumentoFiscal, tipos: tuple[str, ...], por: uuid.UUID | None, nota: str
) -> int:
    ahora = datetime.now(UTC)
    n = 0
    for a in db.scalars(
        select(AlertaFiscal).where(
            AlertaFiscal.documento_id == doc.id, AlertaFiscal.estado == "abierta", AlertaFiscal.tipo.in_(tipos)
        )
    ):
        a.estado, a.resuelta_at, a.resuelta_por_id, a.comentario = "resuelta", ahora, por, nota[:500]
        n += 1
    return n


def _evento_bitacora(
    db: Session,
    doc: DocumentoFiscal,
    tipo: str,
    *,
    intento: int | None = None,
    http_status: int | None = None,
    codigo: str | None = None,
    mensaje: str | None = None,
    request: dict | None = None,
    respuesta: dict | None = None,
    duracion_ms: int | None = None,
) -> None:
    db.add(
        DocumentoFiscalEvento(
            documento_id=doc.id,
            tipo=tipo,
            intento=intento,
            estado_resultante=doc.estado,
            http_status=http_status,
            codigo_respuesta=codigo,
            mensaje=(mensaje or "")[:1000] or None,
            request_resumen=request,
            respuesta=respuesta,
            duracion_ms=duracion_ms,
            ocurrido_at=func.clock_timestamp(),
        )
    )


# ------------------------------------------------------------------------------------------------ armado
def armar_emision(db: Session, doc: DocumentoFiscal, referenciado: DocumentoFiscal | None) -> DocumentoEmision:
    """Datos planos para el proveedor, tomados SOLO de los snapshots del documento (nunca de los maestros)."""
    res = db.get(ResolucionNumeracion, doc.resolucion_id)
    items = db.scalars(
        select(DocumentoFiscalItem)
        .where(DocumentoFiscalItem.documento_id == doc.id)
        .order_by(DocumentoFiscalItem.linea)
    ).all()
    pagos = db.scalars(
        select(DocumentoFiscalPago)
        .where(DocumentoFiscalPago.documento_id == doc.id)
        .order_by(DocumentoFiscalPago.linea)
    ).all()
    observacion = None
    if doc.venta_id is not None:
        n = db.scalar(select(Venta.numero_interno).where(Venta.id == doc.venta_id))
        observacion = f"Venta POS No. {n}" if n else None
    return DocumentoEmision(
        reference_code=doc.id,
        tipo="FE" if doc.tipo_documento_codigo in ("FE", "POS_E") else "NC",
        fecha=doc.fecha_emision,
        rango_proveedor_id=res.id_rango_proveedor,
        prefijo_resolucion=res.prefijo,
        adquirente=dict(doc.adquirente_snapshot),
        lineas=[
            LineaEmision(
                codigo=i.codigo,
                descripcion=i.descripcion,
                unidad_codigo=i.unidad_codigo,
                cantidad=i.cantidad,
                precio_unitario=i.precio_unitario,
                descuento_valor=i.descuento_valor,
                base_gravable=i.base_gravable,
                impuesto_valor=i.impuesto_valor,
                total_linea=i.total_linea,
                tributo_codigo=i.tributo_codigo,
                tarifa_pct=i.tarifa_pct,
            )
            for i in items
        ],
        pagos=[PagoEmision(p.medio_pago_codigo, p.valor, p.referencia) for p in pagos],
        forma_pago_codigo=doc.forma_pago_codigo,
        subtotal=doc.subtotal,
        impuesto_total=doc.impuesto_total,
        redondeo=doc.redondeo,
        total=doc.total,
        observacion=observacion,
        numero_documento_referenciado=referenciado.proveedor_documento_id if referenciado else None,
        concepto_nota_codigo=doc.concepto_nota_codigo,
    )


# ------------------------------------------------------------------------------------------------ resultado
def _aplicar_aceptado(db: Session, doc: DocumentoFiscal, r: RespuestaProveedor) -> None:
    res = db.get(ResolucionNumeracion, doc.resolucion_id)
    if not r.numero or not r.cufe:
        raise ErrorTransitorio("El proveedor aceptó el documento pero no informó número o CUFE.")
    prefijo, consecutivo = partir_numero(r.numero, res.prefijo)
    ahora = datetime.now(UTC)
    doc.prefijo, doc.consecutivo = prefijo, consecutivo
    doc.cufe_cude, doc.qr_data = r.cufe, r.qr_url
    doc.proveedor_documento_id = r.numero
    doc.proveedor_respuesta_codigo = str(r.http_status) if r.http_status else None
    doc.estado = "aceptado"
    doc.aceptado_at = r.validado_at or ahora
    doc.ultimo_error = None
    doc.proximo_intento_at = None
    # el contador de la resolución sigue al del proveedor (monótono; nunca baja) sin salirse del rango configurado
    db.execute(
        update(ResolucionNumeracion)
        .where(ResolucionNumeracion.id == res.id)
        .values(
            consecutivo_actual=func.least(
                ResolucionNumeracion.rango_hasta, func.greatest(ResolucionNumeracion.consecutivo_actual, consecutivo)
            )
        )
    )
    if consecutivo > res.rango_hasta or consecutivo < res.rango_desde:
        abrir_alerta(
            db,
            doc,
            "configuracion",
            f"El número {r.numero} queda fuera del rango configurado de la resolución ({res.rango_desde}-{res.rango_hasta}).",
            {"numero": r.numero, "resolucion_id": str(res.id)},
        )
    # los totales calculados por el proveedor deben coincidir con los nuestros AL CENTAVO
    diferencias = {}
    for nombre, nuestro, suyo in (
        ("subtotal", doc.subtotal, r.subtotal),
        ("impuesto_total", doc.impuesto_total, r.impuesto_total),
        ("total", doc.subtotal + doc.impuesto_total, r.total),
    ):
        if suyo is not None and suyo != nuestro:
            diferencias[nombre] = {"nuestro": str(nuestro), "proveedor": str(suyo)}
    if diferencias:
        log.warning(
            "Totales del proveedor distintos a los nuestros", extra={"documento_id": str(doc.id), **diferencias}
        )
        abrir_alerta(
            db,
            doc,
            "totales_descuadrados",
            "Los totales del proveedor no coinciden con los del documento.",
            diferencias,
        )


def _guardar_archivos(db: Session, doc: DocumentoFiscal, proveedor: ProveedorFiscal, almacen: Almacenamiento) -> bool:
    """Descarga PDF y XML del documento aceptado. True si quedaron ambos guardados."""
    tipo = "FE" if doc.tipo_documento_codigo in ("FE", "POS_E") else "NC"
    try:
        if not doc.pdf_url:
            almacen.guardar(
                _clave_archivo(doc, "pdf"), proveedor.descargar_pdf(tipo, doc.proveedor_documento_id), "application/pdf"
            )
            doc.pdf_url = _clave_archivo(doc, "pdf")
        if not doc.xml_url:
            almacen.guardar(
                _clave_archivo(doc, "xml"), proveedor.descargar_xml(tipo, doc.proveedor_documento_id), "application/xml"
            )
            doc.xml_url = _clave_archivo(doc, "xml")
        return True
    except ErrorProveedor as e:
        log.warning(
            "No se pudo descargar el PDF/XML (se reintenta)", extra={"documento_id": str(doc.id), "motivo": e.mensaje}
        )
        return False


# ------------------------------------------------------------------------------------------------ procesamiento
def _siguiente_evento(db: Session) -> OutboxEvento | None:
    return db.scalar(
        select(OutboxEvento)
        .where(
            OutboxEvento.evento_tipo == EVENTO,
            OutboxEvento.estado.in_(("pendiente", "enviado")),
            OutboxEvento.proximo_intento_at <= func.now(),
        )
        .order_by(OutboxEvento.secuencia)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def procesar_siguiente(
    db: Session,
    proveedor: ProveedorFiscal,
    cfg: Settings,
    almacen: Almacenamiento,
    *,
    rng: random.Random | None = None,
) -> Resultado | None:
    """Toma el siguiente evento elegible, lo procesa y deja el resultado en la sesión (el llamador hace `commit`).

    None = no hay nada elegible. Puede lanzar si la BD falla: el llamador hace `rollback` y el evento se reintenta.
    """
    ev = _siguiente_evento(db)
    if ev is None:
        return None
    doc = db.scalar(
        select(DocumentoFiscal)
        .where(DocumentoFiscal.id == ev.agregado_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    ahora = datetime.now(UTC)
    if doc is None or doc.estado in ("aceptado", "borrador", "rechazado") or not doc.vigente:
        # ya resuelto por otra vía, o aún sin contenido: no hay nada que enviar
        ev.estado = "confirmado" if doc is not None and doc.estado == "aceptado" else "fallido"
        ev.confirmado_at = ahora
        ev.ultimo_error = (
            None if ev.estado == "confirmado" else f"documento en estado {doc.estado if doc else 'inexistente'}"
        )
        return Resultado(ev.agregado_id, "omitido", ev.ultimo_error)

    es_nota = doc.tipo_documento_codigo not in ("FE", "POS_E")
    referenciado = db.get(DocumentoFiscal, doc.documento_referenciado_id) if doc.documento_referenciado_id else None
    if es_nota and referenciado is not None:
        referenciado = _fe_vigente(db, referenciado)  # la FE original pudo ser anulada y reemitida corregida
    if es_nota and (referenciado is None or referenciado.estado != "aceptado"):
        rechazada = referenciado is not None and referenciado.estado == "rechazado"
        if rechazada:
            abrir_alerta(
                db,
                doc,
                "nota_sin_factura",
                "La factura original fue rechazada: la nota crédito no puede emitirse.",
                {"factura_id": str(referenciado.id)},
            )
        ev.proximo_intento_at = ahora + timedelta(
            seconds=ESPERA_FACTURA_RECHAZADA_SEG if rechazada else ESPERA_FACTURA_SEG
        )
        return Resultado(doc.id, "esperando_factura", referenciado.estado if referenciado else "sin factura")

    payload = ev.payload or {}
    intento = doc.intentos + 1
    inicio = time.perf_counter()
    tipo = "NC" if es_nota else "FE"
    request = {
        "reference_code": str(doc.id),
        "tipo": tipo,
        "intento": intento,
        "reintento": bool(payload.get("reintento")),
    }
    try:
        if payload.get("borrar_remoto_de") and intento == 1:
            # FE corregida: el rechazado anterior sigue sin validar en el proveedor y podría bloquear (409) el envío
            try:
                proveedor.eliminar_pendiente(tipo, uuid.UUID(str(payload["borrar_remoto_de"])))
            except ErrorProveedor:
                pass  # si no se pudo borrar, el flujo de 409 lo reintenta
        if payload.get("borrar_remoto") and intento == 1:
            # reintento manual de un rechazado: el proveedor bloquea nuevos envíos mientras exista el no validado
            proveedor.eliminar_pendiente(tipo, doc.id)
        if doc.estado == "enviado" and doc.proveedor_documento_id:
            r = proveedor.consultar_documento(tipo, doc.proveedor_documento_id)
        else:
            emision = armar_emision(db, doc, referenciado)
            r = proveedor.emitir_nota_credito(emision) if es_nota else proveedor.emitir_factura(emision)
    except RechazoValidacion as e:
        return _registrar_rechazo(db, doc, ev, e, intento, request, int((time.perf_counter() - inicio) * 1000))
    except ConflictoPendiente as e:
        try:  # se desbloquea el proveedor borrando el documento propio NO validado; el reintento lo reenvía limpio
            proveedor.eliminar_pendiente(tipo, doc.id)
        except ErrorProveedor:
            pass
        return _registrar_fallo(db, doc, ev, e, intento, request, cfg, rng, int((time.perf_counter() - inicio) * 1000))
    except ErrorConfiguracion as e:
        abrir_alerta(db, doc, "configuracion", _resumen_error(e), {"http_status": e.http_status})
        return _registrar_fallo(db, doc, ev, e, intento, request, cfg, rng, int((time.perf_counter() - inicio) * 1000))
    except ErrorTransitorio as e:
        return _registrar_fallo(db, doc, ev, e, intento, request, cfg, rng, int((time.perf_counter() - inicio) * 1000))
    except ErrorProveedor as e:  # cualquier otro error del proveedor se trata como transitorio
        return _registrar_fallo(db, doc, ev, e, intento, request, cfg, rng, int((time.perf_counter() - inicio) * 1000))

    duracion = int((time.perf_counter() - inicio) * 1000)
    doc.intentos, doc.ultimo_intento_at = intento, ahora
    doc.enviado_at = doc.enviado_at or ahora
    if r.estado == "pendiente":
        doc.estado = "enviado"
        doc.proveedor_documento_id = r.numero or doc.proveedor_documento_id
        doc.ultimo_error = None
        if intento >= cfg.fiscal_max_intentos:
            return _agotar(db, doc, ev, "La DIAN no validó el documento a tiempo.", intento)
        doc.proximo_intento_at = ev.proximo_intento_at = ahora + timedelta(seconds=ESPERA_VALIDACION_SEG)
        ev.estado, ev.intentos = "enviado", intento
        _evento_bitacora(
            db,
            doc,
            "respuesta_proveedor",
            intento=intento,
            http_status=r.http_status,
            mensaje="Enviado; pendiente de validación de la DIAN",
            request=request,
            respuesta=r.crudo,
            duracion_ms=duracion,
        )
        return Resultado(doc.id, "enviado")

    _aplicar_aceptado(db, doc, r)
    _guardar_archivos(db, doc, proveedor, almacen)  # si falla, `completar_archivos` lo reintenta en cada ciclo
    _evento_bitacora(
        db,
        doc,
        "respuesta_proveedor",
        intento=intento,
        http_status=r.http_status,
        codigo="aceptado",
        mensaje=("; ".join(r.advertencias))[:1000],
        request=request,
        respuesta=r.crudo,
        duracion_ms=duracion,
    )
    resolver_alertas(db, doc, ("rechazado", "reintentos_agotados", "configuracion"), None, "Documento aceptado")
    ev.estado, ev.confirmado_at, ev.intentos, ev.ultimo_error = "confirmado", ahora, intento, None
    db.flush()
    publicar_evento(
        db,
        "documento_fiscal",
        doc.id,
        "documento_fiscal.aceptado",
        {"documento_id": doc.id, "numero": doc.numero_completo, "cufe": doc.cufe_cude, "estado": doc.estado},
        version=doc.version,
    )
    registrar_accion(
        db,
        "fiscal.documento_aceptado",
        actor_tipo="sistema",
        sede_id=doc.sede_id,
        entidad_tipo="documento_fiscal",
        entidad_id=doc.id,
        despues={"numero": r.numero, "intento": intento},
    )
    return Resultado(doc.id, "aceptado", r.numero)


def _registrar_rechazo(
    db: Session, doc: DocumentoFiscal, ev: OutboxEvento, e: RechazoValidacion, intento: int, request: dict, ms: int
) -> Resultado:
    ahora = datetime.now(UTC)
    doc.estado, doc.intentos, doc.ultimo_intento_at = "rechazado", intento, ahora
    doc.ultimo_error, doc.proximo_intento_at = _resumen_error(e), None
    doc.proveedor_respuesta_codigo = str(e.http_status) if e.http_status else None
    ev.estado, ev.intentos, ev.ultimo_error = "fallido", intento, doc.ultimo_error
    _evento_bitacora(
        db,
        doc,
        "respuesta_dian",
        intento=intento,
        http_status=e.http_status,
        codigo="rechazado",
        mensaje=doc.ultimo_error,
        request=request,
        respuesta={"errores": e.errores, **e.detalle},
        duracion_ms=ms,
    )
    abrir_alerta(db, doc, "rechazado", doc.ultimo_error, {"errores": e.errores, "intento": intento})
    registrar_accion(
        db,
        "fiscal.documento_rechazado",
        actor_tipo="sistema",
        resultado="error",
        sede_id=doc.sede_id,
        entidad_tipo="documento_fiscal",
        entidad_id=doc.id,
        despues={"errores": e.errores[:10]},
    )
    log.warning("Documento fiscal rechazado", extra={"documento_id": str(doc.id), "errores": e.errores[:5]})
    return Resultado(doc.id, "rechazado", doc.ultimo_error)


def _registrar_fallo(
    db: Session,
    doc: DocumentoFiscal,
    ev: OutboxEvento,
    e: ErrorProveedor,
    intento: int,
    request: dict,
    cfg: Settings,
    rng: random.Random | None,
    ms: int,
) -> Resultado:
    ahora = datetime.now(UTC)
    doc.intentos, doc.ultimo_intento_at, doc.ultimo_error = intento, ahora, _resumen_error(e)
    _evento_bitacora(
        db,
        doc,
        "error_tecnico",
        intento=intento,
        http_status=e.http_status,
        codigo=type(e).__name__,
        mensaje=doc.ultimo_error,
        request=request,
        respuesta=e.detalle or None,
        duracion_ms=ms,
    )
    if intento >= cfg.fiscal_max_intentos:
        return _agotar(db, doc, ev, doc.ultimo_error, intento)
    espera = espera_backoff(intento, cfg, rng)
    if isinstance(e, ErrorTransitorio) and e.reintentar_en:
        espera = max(espera, e.reintentar_en)
    doc.proximo_intento_at = ev.proximo_intento_at = ahora + timedelta(seconds=espera)
    ev.intentos, ev.ultimo_error = intento, doc.ultimo_error
    _evento_bitacora(
        db,
        doc,
        "reintento_programado",
        intento=intento,
        mensaje=f"Próximo intento en {espera:.0f} s",
        request={"espera_seg": round(espera, 1)},
    )
    return Resultado(doc.id, "reintento", doc.ultimo_error)


def _agotar(db: Session, doc: DocumentoFiscal, ev: OutboxEvento, motivo: str | None, intento: int) -> Resultado:
    doc.proximo_intento_at = None
    ev.estado, ev.intentos, ev.ultimo_error = "fallido", intento, (motivo or "")[:500]
    abrir_alerta(
        db, doc, "reintentos_agotados", f"Se agotaron los {intento} intentos de envío: {motivo}", {"intentos": intento}
    )
    registrar_accion(
        db,
        "fiscal.reintentos_agotados",
        actor_tipo="sistema",
        resultado="error",
        sede_id=doc.sede_id,
        entidad_tipo="documento_fiscal",
        entidad_id=doc.id,
        despues={"intentos": intento},
    )
    log.error("Reintentos agotados para un documento fiscal", extra={"documento_id": str(doc.id), "intentos": intento})
    return Resultado(doc.id, "agotado", motivo)


def completar_archivos(db: Session, proveedor: ProveedorFiscal, almacen: Almacenamiento, limite: int = 5) -> int:
    """Descarga PDF/XML de documentos aceptados que quedaron sin archivos (falló la descarga al aceptarse)."""
    n = 0
    docs = db.scalars(
        select(DocumentoFiscal)
        .where(
            DocumentoFiscal.estado == "aceptado",
            (DocumentoFiscal.pdf_url.is_(None)) | (DocumentoFiscal.xml_url.is_(None)),
        )
        .order_by(DocumentoFiscal.aceptado_at)
        .limit(limite)
        .with_for_update(skip_locked=True)
    ).all()
    for d in docs:
        if _guardar_archivos(db, d, proveedor, almacen):
            n += 1
    return n


# ------------------------------------------------------------------------------------------------ reintento manual
def reintentar(
    db: Session, doc_id: uuid.UUID, actor_id: uuid.UUID | None, comentario: str | None = None
) -> DocumentoFiscal:
    """Backoffice: vuelve a encolar un documento `rechazado` o con reintentos agotados (permiso fiscal.gestionar)."""
    from app.core.errores import NoEncontrado, ReglaNegocio

    doc = db.scalar(select(DocumentoFiscal).where(DocumentoFiscal.id == doc_id).with_for_update())
    if doc is None:
        raise NoEncontrado("Documento fiscal no encontrado.")
    agotado = doc.estado in ("pendiente_envio", "enviado") and doc.proximo_intento_at is None and doc.intentos > 0
    if doc.estado != "rechazado" and not agotado:
        raise ReglaNegocio(
            "Solo se reintentan documentos rechazados o con los reintentos agotados.",
            code="reintento_no_aplica",
            estado=doc.estado,
        )
    era_rechazado = doc.estado == "rechazado"
    doc.estado = "pendiente_envio"
    doc.intentos, doc.ultimo_error = 0, None
    doc.proximo_intento_at = None
    doc.vigente = True
    resolver_alertas(
        db,
        doc,
        ("rechazado", "reintentos_agotados", "configuracion", "nota_sin_factura"),
        actor_id,
        comentario or "Reintento manual",
    )
    db.flush()
    publicar_evento(
        db,
        "documento_fiscal",
        doc.id,
        EVENTO,
        {
            "documento_id": doc.id,
            "tipo": doc.tipo_documento_codigo,
            "reference_code": doc.id,
            "reintento": True,
            "borrar_remoto": era_rechazado,
        },
        version=doc.version,
    )
    _evento_bitacora(db, doc, "reintento_programado", mensaje="Reintento manual solicitado desde el backoffice")
    registrar_accion(
        db,
        "fiscal.reintento_manual",
        actor_id=actor_id,
        sede_id=doc.sede_id,
        entidad_tipo="documento_fiscal",
        entidad_id=doc.id,
        motivo=comentario,
    )
    return doc


def _fe_vigente(db: Session, doc: DocumentoFiscal) -> DocumentoFiscal:
    """Sigue la cadena de correcciones: una FE `anulado` se sustituye por la FE que la corrige."""
    for _ in range(20):  # tope defensivo
        if doc.estado != "anulado":
            return doc
        siguiente = db.scalar(select(DocumentoFiscal).where(DocumentoFiscal.documento_corrige_id == doc.id))
        if siguiente is None:
            return doc
        doc = siguiente
    return doc


CAMPOS_ADQUIRENTE_CORREGIBLES = (
    "tipo_documento_codigo",
    "numero_documento",
    "dv",
    "tipo_persona_codigo",
    "nombre_completo",
    "razon_social",
    "regimen_codigo",
    "responsabilidades",
    "email",
    "telefono",
    "direccion",
    "municipio_codigo",
)


def corregir_y_reemitir(
    db: Session, doc_id: uuid.UUID, actor_id: uuid.UUID | None, cambios_adquirente: dict[str, Any], motivo: str
) -> DocumentoFiscal:
    """Backoffice (fiscal.gestionar): corrige los datos del adquirente de una FE RECHAZADA y la reemite.

    Solo aplica a una FE que la DIAN nunca aceptó. El documento rechazado queda `anulado` (sin NC) y se crea uno nuevo
    para la MISMA venta, con los mismos ítems, impuestos, pagos y totales (NO se pueden cambiar por esta vía), un
    snapshot de adquirente corregido, `documento_corrige_id` apuntando al anterior y su propio `reference_code`.
    """
    from app.core.errores import NoEncontrado, ReglaNegocio
    from app.modules.fiscal.servicios import _cargar_hijos, _hash, _publicar

    desconocidos = set(cambios_adquirente) - set(CAMPOS_ADQUIRENTE_CORREGIBLES)
    if desconocidos or not cambios_adquirente:
        raise ReglaNegocio(
            "Solo se pueden corregir datos del adquirente: " + ", ".join(CAMPOS_ADQUIRENTE_CORREGIBLES) + ".",
            code="correccion_campos_invalidos",
            campos=sorted(desconocidos),
        )
    cambios = dict(cambios_adquirente)
    viejo = db.scalar(select(DocumentoFiscal).where(DocumentoFiscal.id == doc_id).with_for_update())
    if viejo is None:
        raise NoEncontrado("Documento fiscal no encontrado.")
    if viejo.tipo_documento_codigo not in ("FE", "POS_E") or viejo.venta_id is None:
        raise ReglaNegocio(
            "Solo se corrigen facturas de venta rechazadas (las notas crédito no).", code="correccion_no_aplica"
        )
    if viejo.estado != "rechazado" or viejo.aceptado_at is not None or viejo.cufe_cude is not None or not viejo.vigente:
        raise ReglaNegocio(
            "Solo se corrige un documento RECHAZADO que la DIAN nunca aceptó; "
            "uno aceptado se corrige con una nota crédito.",
            code="correccion_no_aplica",
            estado=viejo.estado,
        )
    if db.scalar(select(DocumentoFiscal.id).where(DocumentoFiscal.documento_corrige_id == viejo.id)) is not None:
        raise ReglaNegocio("Este documento ya fue corregido.", code="ya_corregido")

    adquirente = {**viejo.adquirente_snapshot, **cambios}
    if adquirente.get("es_consumidor_final") and ("numero_documento" in cambios or "tipo_documento_codigo" in cambios):
        adquirente["es_consumidor_final"] = False
    adquirente = jsonable_encoder(adquirente)
    nombre = (
        adquirente.get("razon_social") if adquirente.get("tipo_persona_codigo") == "1" else None
    ) or adquirente.get("nombre_completo")
    items = db.scalars(
        select(DocumentoFiscalItem)
        .where(DocumentoFiscalItem.documento_id == viejo.id)
        .order_by(DocumentoFiscalItem.linea)
    ).all()
    pagos = db.scalars(
        select(DocumentoFiscalPago)
        .where(DocumentoFiscalPago.documento_id == viejo.id)
        .order_by(DocumentoFiscalPago.linea)
    ).all()
    columnas_item = (
        "venta_item_id producto_id codigo descripcion unidad_codigo cantidad precio_unitario valor_unitario_base "
        "descuento_valor base_gravable impuesto_valor total_linea tributo_codigo tarifa_pct"
    ).split()
    lineas = [{c: getattr(i, c) for c in columnas_item} for i in items]
    pagos_doc = [dict(medio_pago_codigo=p.medio_pago_codigo, valor=p.valor, referencia=p.referencia) for p in pagos]

    # 1) el rechazado deja de ser el vigente de la venta (índice único) y queda anulado, sin NC
    viejo.estado, viejo.vigente, viejo.proximo_intento_at = "anulado", False, None
    resolver_alertas(
        db, viejo, ("rechazado", "reintentos_agotados", "configuracion"), actor_id, f"Corregido y reemitido: {motivo}"
    )
    db.flush()

    # 2) documento nuevo: mismo contenido económico, adquirente corregido, otro reference_code (su id)
    nuevo = DocumentoFiscal(
        empresa_id=viejo.empresa_id,
        sede_id=viejo.sede_id,
        caja_id=viejo.caja_id,
        tipo_documento_codigo=viejo.tipo_documento_codigo,
        resolucion_id=viejo.resolucion_id,
        fecha_emision=viejo.fecha_emision,
        venta_id=viejo.venta_id,
        documento_corrige_id=viejo.id,
        forma_pago_codigo=viejo.forma_pago_codigo,
        fecha_vencimiento=viejo.fecha_vencimiento,
        emisor_snapshot=viejo.emisor_snapshot,
        adquirente_tercero_id=viejo.adquirente_tercero_id,
        adquirente_snapshot=adquirente,
        adquirente_numero_documento=str(adquirente["numero_documento"]),
        adquirente_nombre=nombre or viejo.adquirente_nombre,
        moneda=viejo.moneda,
        subtotal=viejo.subtotal,
        descuento_total=viejo.descuento_total,
        impuesto_total=viejo.impuesto_total,
        redondeo=viejo.redondeo,
        total=viejo.total,
        estado="borrador",
        hash_contenido=_hash(
            {
                "tipo": viejo.tipo_documento_codigo,
                "corrige": viejo.id,
                "fecha": viejo.fecha_emision,
                "emisor": viejo.emisor_snapshot,
                "adquirente": adquirente,
                "totales": [viejo.subtotal, viejo.descuento_total, viejo.impuesto_total, viejo.redondeo, viejo.total],
                "lineas": [{k: v for k, v in ln.items() if k != "venta_item_id"} for ln in lineas],
                "pagos": pagos_doc,
            }
        ),
        created_by=actor_id,
    )
    db.add(nuevo)
    db.flush()
    _cargar_hijos(db, nuevo, lineas, pagos_doc, actor_id)
    nuevo.estado = "pendiente_envio"
    db.flush()
    _publicar(db, nuevo, actor_id, {"corrige_documento_id": viejo.id, "borrar_remoto_de": viejo.id})

    _evento_bitacora(db, viejo, "correccion", mensaje=f"Anulado y reemplazado por {nuevo.id}: {motivo}")
    _evento_bitacora(db, nuevo, "correccion", mensaje=f"Corrige al documento rechazado {viejo.id}: {motivo}")
    registrar_accion(
        db,
        "fiscal.documento_corregido",
        actor_id=actor_id,
        sede_id=viejo.sede_id,
        entidad_tipo="documento_fiscal",
        entidad_id=viejo.id,
        # solo los NOMBRES de los campos: los valores son datos personales y ya viven en los snapshots
        despues={"documento_nuevo_id": str(nuevo.id), "campos_corregidos": sorted(cambios)},
        motivo=motivo,
    )
    return nuevo


def contadores(db: Session) -> dict[str, Any]:
    """Para `/health`: documentos por atender y estado del worker."""
    filas = dict(
        db.execute(
            select(DocumentoFiscal.estado, func.count())
            .where(DocumentoFiscal.estado.in_(("pendiente_envio", "enviado", "rechazado")))
            .group_by(DocumentoFiscal.estado)
        ).all()
    )
    return {
        "pendientes": int(filas.get("pendiente_envio", 0)) + int(filas.get("enviado", 0)),
        "rechazados": int(filas.get("rechazado", 0)),
    }


__all__ = [
    "Resultado",
    "abrir_alerta",
    "armar_emision",
    "completar_archivos",
    "contadores",
    "corregir_y_reemitir",
    "espera_backoff",
    "partir_numero",
    "procesar_siguiente",
    "reintentar",
    "resolver_alertas",
]
