"""Schema `auditoria`: log de acciones sensibles (§14). Tabla normal; particionar es una evolución futura."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Uuid, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, SoloAgregar, pg_enum
from app.core.helpers import fk, ts, txt

SCHEMA = "auditoria"
ActorTipo = pg_enum(SCHEMA, "actor_tipo", "empleado", "cliente", "sistema", "dispositivo")
ResultadoAccion = pg_enum(SCHEMA, "resultado_accion", "exito", "denegado", "error")


class LogAccion(Base, SoloAgregar):
    __tablename__ = "log_acciones"
    __table_args__ = (
        CheckConstraint(r"accion ~ '^[a-z_]+\.[a-z_]+$'", name="accion_formato"),
        Index("ix_log_acciones_entidad", "entidad_tipo", "entidad_id"),
        Index("ix_log_acciones_actor", "actor_id", text("ocurrido_at DESC")),
        Index("ix_log_acciones_ocurrido", text("ocurrido_at DESC")),
        {"schema": SCHEMA},
    )
    ocurrido_at: Mapped[datetime] = ts(null=False, server_default=text("now()"))
    actor_tipo: Mapped[str] = mapped_column(ActorTipo, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # polimórfico: sin FK
    sede_id: Mapped[uuid.UUID | None] = fk("organizacion.sedes.id", null=True)
    accion: Mapped[str] = txt()
    entidad_tipo: Mapped[str | None] = txt(null=True)
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    antes: Mapped[dict | None] = mapped_column(JSONB)
    despues: Mapped[dict | None] = mapped_column(JSONB)
    autorizado_por_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)
    autorizacion_id: Mapped[uuid.UUID | None] = fk("identidad.autorizaciones.id", null=True)
    dispositivo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # referencia lógica a cajas.dispositivos
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = txt(null=True)
    resultado: Mapped[str] = mapped_column(ResultadoAccion, nullable=False, server_default="exito")
    motivo: Mapped[str | None] = txt(null=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
