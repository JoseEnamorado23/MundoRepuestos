"""Auditoría: `registrar_accion` (append-only) y conteo de intentos fallidos para el bloqueo temporal."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errores import DemasiadosIntentos
from app.core.logs import ip_var, request_id_var, user_agent_var
from app.modules.auditoria.models import LogAccion


def _uuid_o_none(valor: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(valor) if valor else None
    except ValueError:
        return None


def registrar_accion(
    db: Session,
    accion: str,
    *,
    actor_tipo: str = "empleado",
    actor_id: uuid.UUID | None = None,
    resultado: str = "exito",
    sede_id: uuid.UUID | None = None,
    entidad_tipo: str | None = None,
    entidad_id: uuid.UUID | None = None,
    antes: dict | None = None,
    despues: dict | None = None,
    autorizado_por_id: uuid.UUID | None = None,
    autorizacion_id: uuid.UUID | None = None,
    dispositivo_id: uuid.UUID | None = None,
    motivo: str | None = None,
) -> LogAccion:
    """Añade una fila a `auditoria.log_acciones` en la transacción actual (el llamador decide el commit).

    `accion` = `modulo.verbo` (p. ej. `identidad.login_fallido`). Toma ip, user-agent y request_id del contexto.
    Nunca incluir contraseñas, PIN ni tokens en `antes`/`despues`/`motivo`.
    """
    fila = LogAccion(
        ocurrido_at=func.clock_timestamp(),  # now() es la hora de INICIO de la transacción: no sirve para ordenar
        actor_tipo=actor_tipo,
        actor_id=actor_id,
        sede_id=sede_id,
        accion=accion,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
        antes=antes,
        despues=despues,
        autorizado_por_id=autorizado_por_id,
        autorizacion_id=autorizacion_id,
        dispositivo_id=dispositivo_id,
        ip=ip_var.get(),
        user_agent=user_agent_var.get(),
        resultado=resultado,
        motivo=motivo,
        request_id=_uuid_o_none(request_id_var.get()),
        created_by=actor_id if actor_tipo == "empleado" else None,
    )
    db.add(fila)
    db.flush()
    return fila


def verificar_bloqueo(
    db: Session,
    *,
    accion_fallo: str,
    accion_ok: str,
    maximo: int,
    dispositivo_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Lanza `DemasiadosIntentos` si hay >= `maximo` fallos en los últimos `bloqueo_minutos` desde el último éxito.

    Sin estado propio: se deriva de la bitácora (cada intento ya queda auditado). El bloqueo cede solo cuando los
    fallos más antiguos salen de la ventana.
    """
    ventana = timedelta(minutes=get_settings().bloqueo_minutos)
    filtros = []
    if dispositivo_id is not None:
        filtros.append(LogAccion.dispositivo_id == dispositivo_id)
    if actor_id is not None:
        filtros.append(LogAccion.actor_id == actor_id)
    if not filtros:
        return

    ahora_bd: datetime = db.scalar(select(func.clock_timestamp()))
    desde: datetime = ahora_bd - ventana
    ultimo_ok = db.scalar(select(func.max(LogAccion.ocurrido_at)).where(LogAccion.accion == accion_ok, *filtros))
    if ultimo_ok is not None and ultimo_ok > desde:
        desde = ultimo_ok
    recientes = list(
        db.scalars(
            select(LogAccion.ocurrido_at)
            .where(LogAccion.accion == accion_fallo, LogAccion.ocurrido_at > desde, *filtros)
            .order_by(LogAccion.ocurrido_at.desc())
            .limit(maximo)
        )
    )
    if len(recientes) >= maximo:
        libre_en = recientes[maximo - 1] + ventana  # cuando el fallo N-ésimo más reciente salga de la ventana
        espera = max(1, int((libre_en - ahora_bd).total_seconds()) + 1)
        raise DemasiadosIntentos(
            f"Demasiados intentos fallidos. Intente de nuevo en {max(1, espera // 60)} min.",
            retry_after=espera,
        )
