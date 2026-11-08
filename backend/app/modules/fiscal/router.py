"""Backoffice fiscal: documentos electrónicos (FE/NC), su bitácora, PDF, reintentos y alertas (/fiscal/...).

Permisos: `fiscal.ver` (consultar) y `fiscal.gestionar` (reintentar, resolver alertas). Los routers solo validan,
delegan en el servicio y responden.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Actor, Db, requiere_permiso, sede_efectiva
from app.api.paginacion import Pag, Pagina, aplicar_orden, paginar
from app.aplicacion import fiscal as uc
from app.core.almacenamiento import get_almacenamiento
from app.core.errores import NoEncontrado
from app.modules.fiscal import emision
from app.modules.fiscal.models import AlertaFiscal, DocumentoFiscal, DocumentoFiscalEvento

router = APIRouter(prefix="/fiscal", tags=["fiscal"])
Ve = Annotated[Actor, Depends(requiere_permiso("fiscal.ver"))]
Gestiona = Annotated[Actor, Depends(requiere_permiso("fiscal.gestionar"))]
Dinero = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]
EstadoDoc = Literal["borrador", "pendiente_envio", "enviado", "aceptado", "rechazado", "contingencia", "anulado"]
TipoDoc = Literal["FE", "NC", "ND", "POS_E", "NA", "DS"]


class DocumentoListaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tipo_documento_codigo: str
    estado: str
    numero_completo: str | None
    fecha_emision: datetime
    adquirente_numero_documento: str
    adquirente_nombre: str
    total: Dinero
    cufe_cude: str | None
    intentos: int
    ultimo_error: str | None
    proximo_intento_at: datetime | None
    aceptado_at: datetime | None
    venta_id: uuid.UUID | None
    devolucion_id: uuid.UUID | None
    documento_referenciado_id: uuid.UUID | None
    documento_corrige_id: uuid.UUID | None = None
    tiene_pdf: bool = False


class EventoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tipo: str
    intento: int | None
    estado_resultante: str | None
    http_status: int | None
    codigo_respuesta: str | None
    mensaje: str | None
    request_resumen: dict | None
    respuesta: dict | None
    duracion_ms: int | None
    ocurrido_at: datetime


class AlertaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    documento_id: uuid.UUID
    tipo: str
    mensaje: str
    detalle: dict
    estado: str
    created_at: datetime
    resuelta_at: datetime | None
    comentario: str | None


class DocumentoDetalleOut(DocumentoListaOut):
    subtotal: Dinero
    impuesto_total: Dinero
    redondeo: Dinero
    qr_data: str | None
    proveedor_documento_id: str | None
    resolucion_id: uuid.UUID
    enviado_at: datetime | None
    adquirente_snapshot: dict
    eventos: list[EventoOut]
    alertas: list[AlertaOut]


class ReintentoIn(BaseModel):
    comentario: str | None = Field(None, max_length=300)


class CorreccionIn(BaseModel):
    """Datos del adquirente a corregir (solo los enviados cambian). Montos, ítems y pagos NO se pueden tocar."""

    model_config = ConfigDict(extra="forbid")
    motivo: str = Field(min_length=3, max_length=300)
    tipo_documento_codigo: str | None = Field(None, max_length=3)
    numero_documento: str | None = Field(None, min_length=3, max_length=20)
    dv: int | None = Field(None, ge=0, le=9)
    tipo_persona_codigo: Literal["1", "2"] | None = None
    nombre_completo: str | None = Field(None, min_length=2, max_length=250)
    razon_social: str | None = Field(None, min_length=2, max_length=250)
    regimen_codigo: str | None = Field(None, max_length=5)
    responsabilidades: list[str] | None = None
    email: str | None = Field(None, max_length=200)
    telefono: str | None = Field(None, max_length=40)
    direccion: str | None = Field(None, max_length=250)
    municipio_codigo: str | None = Field(None, max_length=10)
    actualizar_tercero: bool = Field(
        False,
        description="Si es true, aplica los mismos cambios al maestro `identidad.terceros` (con evento y auditoría). "
        "Por defecto solo cambia el snapshot de la FE nueva.",
    )


class ResolverIn(BaseModel):
    comentario: str = Field(min_length=3, max_length=300)


def _lista(d: DocumentoFiscal) -> DocumentoListaOut:
    out = DocumentoListaOut.model_validate(d)
    out.tiene_pdf = bool(d.pdf_url)
    return out


@router.get("/documentos", response_model=Pagina[DocumentoListaOut], summary="Documentos fiscales (FE, NC…)")
def listar_documentos(
    db: Db,
    actor: Ve,
    pag: Pag,
    estado: EstadoDoc | None = None,
    tipo: TipoDoc | None = None,
    desde: Annotated[date | None, Query(description="Fecha de emisión desde (día de Bogotá)")] = None,
    hasta: Annotated[date | None, Query(description="Fecha de emisión hasta, inclusive")] = None,
    cliente: Annotated[str | None, Query(min_length=2, description="Documento o parte del nombre del cliente")] = None,
    sede_id: uuid.UUID | None = None,
    orden: str | None = None,
):
    stmt = select(DocumentoFiscal)
    sede = sede_efectiva(db, actor, sede_id)
    if sede is not None:
        stmt = stmt.where(DocumentoFiscal.sede_id == sede)
    if estado:
        stmt = stmt.where(DocumentoFiscal.estado == estado)
    if tipo:
        stmt = stmt.where(DocumentoFiscal.tipo_documento_codigo == tipo)
    if desde:
        stmt = stmt.where(DocumentoFiscal.fecha_emision >= datetime.combine(desde, time.min).astimezone())
    if hasta:
        stmt = stmt.where(
            DocumentoFiscal.fecha_emision < datetime.combine(hasta + timedelta(days=1), time.min).astimezone()
        )
    if cliente:
        patron = f"%{cliente.strip()}%"
        stmt = stmt.where(
            DocumentoFiscal.adquirente_numero_documento.ilike(patron) | DocumentoFiscal.adquirente_nombre.ilike(patron)
        )
    stmt = aplicar_orden(
        stmt,
        orden,
        {"fecha": DocumentoFiscal.fecha_emision, "total": DocumentoFiscal.total, "estado": DocumentoFiscal.estado},
        [DocumentoFiscal.fecha_emision.desc(), DocumentoFiscal.id.desc()],
    )
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=[_lista(d) for d in filas], total=total, limit=pag.limit, offset=pag.offset)


def _documento(db, actor: Actor, doc_id: uuid.UUID) -> DocumentoFiscal:
    doc = db.get(DocumentoFiscal, doc_id)
    if doc is None:
        raise NoEncontrado("Documento fiscal no encontrado.")
    sede_efectiva(db, actor, doc.sede_id)  # valida que el empleado pueda ver esa sede
    return doc


@router.get("/documentos/{doc_id}", response_model=DocumentoDetalleOut, summary="Documento con su bitácora de envíos")
def detalle_documento(doc_id: uuid.UUID, db: Db, actor: Ve):
    d = _documento(db, actor, doc_id)
    eventos = db.scalars(
        select(DocumentoFiscalEvento)
        .where(DocumentoFiscalEvento.documento_id == d.id)
        .order_by(DocumentoFiscalEvento.ocurrido_at, DocumentoFiscalEvento.id)
    ).all()
    alertas = db.scalars(
        select(AlertaFiscal).where(AlertaFiscal.documento_id == d.id).order_by(AlertaFiscal.created_at)
    ).all()
    base = _lista(d).model_dump()
    return DocumentoDetalleOut(
        **base,
        subtotal=d.subtotal,
        impuesto_total=d.impuesto_total,
        redondeo=d.redondeo,
        qr_data=d.qr_data,
        proveedor_documento_id=d.proveedor_documento_id,
        resolucion_id=d.resolucion_id,
        enviado_at=d.enviado_at,
        adquirente_snapshot=d.adquirente_snapshot,
        eventos=[EventoOut.model_validate(e) for e in eventos],
        alertas=[AlertaOut.model_validate(a) for a in alertas],
    )


@router.post(
    "/documentos/{doc_id}/reintentar",
    response_model=DocumentoListaOut,
    summary="Reintenta un documento rechazado o con los reintentos agotados (fiscal.gestionar; queda auditado)",
)
def reintentar_documento(doc_id: uuid.UUID, datos: ReintentoIn, db: Db, actor: Gestiona):
    _documento(db, actor, doc_id)
    d = emision.reintentar(db, doc_id, actor.empleado.id, datos.comentario)
    return _lista(d)


@router.post(
    "/documentos/{doc_id}/corregir",
    response_model=DocumentoListaOut,
    status_code=201,
    summary="Corrige el adquirente de una FE rechazada y la reemite (fiscal.gestionar; queda auditado)",
)
def corregir_documento(doc_id: uuid.UUID, datos: CorreccionIn, db: Db, actor: Gestiona):
    """El rechazado queda `anulado` (no requiere NC) y se crea una FE nueva para la misma venta. Devuelve la nueva."""
    _documento(db, actor, doc_id)
    cambios = datos.model_dump(exclude_unset=True, exclude={"motivo", "actualizar_tercero"})
    nuevo = uc.corregir_documento(
        db, doc_id, actor.empleado.id, cambios, datos.motivo, actualizar_tercero=datos.actualizar_tercero
    )
    return _lista(nuevo)


@router.get("/documentos/{doc_id}/pdf", summary="PDF de la representación gráfica (documento aceptado)")
def pdf_documento(doc_id: uuid.UUID, db: Db, actor: Ve):
    d = _documento(db, actor, doc_id)
    if not d.pdf_url:
        raise NoEncontrado(
            "El PDF aún no está disponible (el documento no está aceptado o la descarga está pendiente).",
            code="pdf_no_disponible",
        )
    datos = get_almacenamiento().leer(d.pdf_url)
    nombre = (d.numero_completo or str(d.id)) + ".pdf"
    return Response(
        datos, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{nombre}"'}
    )


@router.get("/alertas", response_model=Pagina[AlertaOut], summary="Alertas fiscales para el backoffice")
def listar_alertas(
    db: Db, actor: Ve, pag: Pag, estado: Literal["abierta", "resuelta"] = "abierta", sede_id: uuid.UUID | None = None
):
    stmt = select(AlertaFiscal).where(AlertaFiscal.estado == estado)
    sede = sede_efectiva(db, actor, sede_id)
    if sede is not None:
        stmt = stmt.where(AlertaFiscal.sede_id == sede)
    filas, total = paginar(db, stmt.order_by(AlertaFiscal.created_at.desc()), pag)
    return Pagina(items=[AlertaOut.model_validate(a) for a in filas], total=total, limit=pag.limit, offset=pag.offset)


@router.post("/alertas/{alerta_id}/resolver", response_model=AlertaOut, summary="Marca una alerta como resuelta")
def resolver_alerta(alerta_id: uuid.UUID, datos: ResolverIn, db: Db, actor: Gestiona):
    from app.core.errores import ReglaNegocio
    from app.modules.auditoria.servicios import registrar_accion

    a = db.get(AlertaFiscal, alerta_id)
    if a is None:
        raise NoEncontrado("Alerta no encontrada.")
    sede_efectiva(db, actor, a.sede_id)
    if a.estado != "abierta":
        raise ReglaNegocio("La alerta ya está resuelta.", code="alerta_resuelta")
    from datetime import UTC

    a.estado, a.resuelta_at, a.resuelta_por_id, a.comentario = (
        "resuelta",
        datetime.now(UTC),
        actor.empleado.id,
        datos.comentario,
    )
    registrar_accion(
        db,
        "fiscal.alerta_resuelta",
        actor_id=actor.empleado.id,
        sede_id=a.sede_id,
        entidad_tipo="alerta_fiscal",
        entidad_id=a.id,
        motivo=datos.comentario,
    )
    db.flush()
    return AlertaOut.model_validate(a)
