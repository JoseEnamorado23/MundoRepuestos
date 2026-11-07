"""Aprobación remota de autorizaciones (0010).

El cajero pide desde la caja (`crear_solicitud`); alguien con `autorizaciones.aprobar` responde desde el backoffice
(`aprobar` / `rechazar`). Al aprobarse nace una fila normal de `identidad.autorizaciones` (de un solo uso, con el
mismo TTL corto), así que la acción protegida la consume IGUAL que una autorización por PIN. Reglas:
* quien aprueba es OTRO empleado (también lo exige la BD) y debe tener el permiso de la acción pedida;
* una solicitud pendiente vence a los `autorizacion.solicitud_expira_min` minutos (por defecto 5); el vencimiento se
  aplica de forma perezosa al consultar o listar, y una aprobación tardía se rechaza.
El POS consulta por polling (ver docs/arquitectura.md).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errores import Conflicto, NoEncontrado, PermisoDenegado, ReglaNegocio
from app.core.seguridad import ahora
from app.core.utiles import snapshot
from app.modules.auditoria.servicios import registrar_accion
from app.modules.cajas.servicios import ACCIONES_AUTORIZABLES, SesionPosLike
from app.modules.identidad.models import Autorizacion, SolicitudAutorizacion
from app.modules.identidad.servicios import permisos_de
from app.modules.organizacion import politicas
from app.modules.sync.servicios import publicar_evento

POLL_MS = 2000  # intervalo de consulta sugerido al POS


def _vencer(db: Session, sede_id: uuid.UUID | None = None, solicitud_id: uuid.UUID | None = None) -> int:
    q = (
        update(SolicitudAutorizacion)
        .where(SolicitudAutorizacion.estado == "pendiente", SolicitudAutorizacion.expira_at <= ahora())
        .values(estado="expirada")
    )
    if sede_id is not None:
        q = q.where(SolicitudAutorizacion.sede_id == sede_id)
    if solicitud_id is not None:
        q = q.where(SolicitudAutorizacion.id == solicitud_id)
    res = db.execute(q.execution_options(synchronize_session="fetch"))
    return res.rowcount or 0


def crear_solicitud(
    db: Session,
    sesion: SesionPosLike,
    *,
    accion: str,
    monto: Decimal | None,
    motivo: str,
    contexto: dict,
    entidad_tipo: str | None,
    entidad_id: uuid.UUID | None,
) -> SolicitudAutorizacion:
    if accion not in ACCIONES_AUTORIZABLES:
        raise ReglaNegocio(f"La acción '{accion}' no admite autorización.", code="accion_no_autorizable")
    if not motivo or len(motivo.strip()) < 3:
        raise ReglaNegocio("Indique el motivo de la solicitud.", code="motivo_obligatorio")
    minutos = politicas.minutos_expiracion_solicitud(db, sesion.sede_id)
    s = SolicitudAutorizacion(
        sede_id=sesion.sede_id,
        solicitado_por_id=sesion.empleado.id,
        dispositivo_id=sesion.dispositivo_id,
        caja_id=sesion.caja_id,
        accion=accion,
        monto=monto,
        motivo=motivo.strip(),
        contexto=contexto,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
        expira_at=ahora() + timedelta(minutes=minutos),
        created_by=sesion.empleado.id,
    )
    db.add(s)
    db.flush()
    publicar_evento(db, "solicitud_autorizacion", s.id, "solicitud_autorizacion.creada", snapshot(s), version=s.version)
    registrar_accion(
        db,
        "pos.solicitud_autorizacion_creada",
        actor_id=sesion.empleado.id,
        sede_id=sesion.sede_id,
        dispositivo_id=sesion.dispositivo_id,
        entidad_tipo="solicitud_autorizacion",
        entidad_id=s.id,
        despues={"accion": accion, "monto": str(monto) if monto is not None else None},
        motivo=s.motivo,
    )
    return s


def obtener_del_solicitante(db: Session, sesion: SesionPosLike, solicitud_id: uuid.UUID) -> SolicitudAutorizacion:
    _vencer(db, solicitud_id=solicitud_id)
    s = db.scalar(
        select(SolicitudAutorizacion)
        .where(SolicitudAutorizacion.id == solicitud_id)
        .execution_options(populate_existing=True)
    )
    if s is None or s.solicitado_por_id != sesion.empleado.id:
        raise NoEncontrado("Solicitud no encontrada.")
    return s


def consulta_pendientes(db: Session, sede_id: uuid.UUID | None, estado: str | None):
    if estado is not None and estado not in ("pendiente", "aprobada", "rechazada", "expirada"):
        raise ReglaNegocio("Estado inválido.", code="estado_invalido")
    _vencer(db, sede_id=sede_id)
    q = select(SolicitudAutorizacion).order_by(SolicitudAutorizacion.created_at.desc())
    if sede_id is not None:
        q = q.where(SolicitudAutorizacion.sede_id == sede_id)
    return q.where(SolicitudAutorizacion.estado == (estado or "pendiente"))


def _pendiente_bloqueada(db: Session, solicitud_id: uuid.UUID, sede_permitida) -> SolicitudAutorizacion:
    s = db.scalar(
        select(SolicitudAutorizacion)
        .where(SolicitudAutorizacion.id == solicitud_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if s is None:
        raise NoEncontrado("Solicitud no encontrada.")
    if sede_permitida is not None:
        sede_permitida(s.sede_id)
    if s.estado != "pendiente":
        raise Conflicto(f"La solicitud ya está {s.estado}.", code="solicitud_resuelta", estado=s.estado)
    if s.expira_at <= ahora():
        s.estado = "expirada"
        db.flush()  # el router confirma con persistir_si_falla
        raise ReglaNegocio("La solicitud venció; el cajero debe pedirla de nuevo.", code="solicitud_expirada")
    return s


def aprobar(
    db: Session, solicitud_id: uuid.UUID, aprobador_id: uuid.UUID, comentario: str | None, sede_permitida=None
) -> SolicitudAutorizacion:
    s = _pendiente_bloqueada(db, solicitud_id, sede_permitida)
    if aprobador_id == s.solicitado_por_id:
        raise PermisoDenegado("No puede aprobar su propia solicitud.", code="autoaprobacion")
    if s.accion not in permisos_de(db, aprobador_id):
        raise PermisoDenegado(
            f"Quien aprueba necesita el permiso '{s.accion}'.", code="permiso_denegado", permiso=s.accion
        )
    a = Autorizacion(
        tipo=ACCIONES_AUTORIZABLES[s.accion],
        permiso_codigo=s.accion,
        solicitado_por_id=s.solicitado_por_id,
        autorizado_por_id=aprobador_id,
        dispositivo_id=s.dispositivo_id,
        entidad_tipo=s.entidad_tipo,
        entidad_id=s.entidad_id,
        detalle={"solicitud_id": str(s.id), "via": "remota", "monto": str(s.monto) if s.monto is not None else None},
        motivo=s.motivo,
        expira_at=ahora() + timedelta(seconds=get_settings().autorizacion_ttl_seg),
        created_by=aprobador_id,
    )
    db.add(a)
    db.flush()
    s.estado = "aprobada"
    s.resuelta_por_id = aprobador_id
    s.resuelta_at = ahora()
    s.comentario = comentario
    s.autorizacion_id = a.id
    db.flush()
    publicar_evento(
        db, "solicitud_autorizacion", s.id, "solicitud_autorizacion.aprobada", snapshot(s), version=s.version
    )
    registrar_accion(
        db,
        "pos.solicitud_autorizacion_aprobada",
        actor_id=s.solicitado_por_id,
        sede_id=s.sede_id,
        dispositivo_id=s.dispositivo_id,
        autorizado_por_id=aprobador_id,
        autorizacion_id=a.id,
        entidad_tipo="solicitud_autorizacion",
        entidad_id=s.id,
        despues={"accion": s.accion},
    )
    return s


def rechazar(
    db: Session, solicitud_id: uuid.UUID, rechazador_id: uuid.UUID, comentario: str | None, sede_permitida=None
) -> SolicitudAutorizacion:
    s = _pendiente_bloqueada(db, solicitud_id, sede_permitida)
    if rechazador_id == s.solicitado_por_id:
        raise PermisoDenegado("No puede resolver su propia solicitud.", code="autoaprobacion")
    s.estado = "rechazada"
    s.resuelta_por_id = rechazador_id
    s.resuelta_at = ahora()
    s.comentario = comentario
    db.flush()
    publicar_evento(
        db, "solicitud_autorizacion", s.id, "solicitud_autorizacion.rechazada", snapshot(s), version=s.version
    )
    registrar_accion(
        db,
        "pos.solicitud_autorizacion_rechazada",
        actor_id=s.solicitado_por_id,
        sede_id=s.sede_id,
        dispositivo_id=s.dispositivo_id,
        entidad_tipo="solicitud_autorizacion",
        entidad_id=s.id,
        despues={"accion": s.accion},
        motivo=comentario,
    )
    return s
