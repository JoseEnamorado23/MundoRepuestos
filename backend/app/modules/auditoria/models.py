"""Schema `auditoria`: log de acciones sensibles (§14). Tabla normal; particionar es una evolución futura."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Numeric, Uuid, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, Mutable, SoloAgregar, pg_enum
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


class Revision(Base, Mutable):
    """Acción sensible ejecutada bajo la política `revision_posterior` (0010): queda pendiente de que alguien del
    backoffice la marque como revisada (con comentario). No bloquea la operación; solo deja constancia revisable."""

    __tablename__ = "revisiones"
    __table_args__ = (
        CheckConstraint("estado IN ('pendiente','revisada')", name="estado_valido"),
        CheckConstraint(
            "estado <> 'revisada' OR (revisada_por_id IS NOT NULL AND revisada_at IS NOT NULL)",
            name="revisada_completa",
        ),
        Index("ix_revisiones_sede_estado", "sede_id", "estado", text("created_at DESC")),
        Index(
            "uq_revisiones_accion_entidad",
            "accion",
            "entidad_id",
            unique=True,
            postgresql_where=text("entidad_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )
    sede_id: Mapped[uuid.UUID] = fk("organizacion.sedes.id")
    accion: Mapped[str] = txt()  # devolucion, retiro_caja, diferencia_arqueo, descuento_mayor, cambiar_precio...
    entidad_tipo: Mapped[str] = txt()
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    monto = mapped_column(Numeric(18, 2))
    empleado_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)  # quien ejecutó la acción
    dispositivo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    estado: Mapped[str] = txt(server_default="pendiente")
    revisada_por_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)
    revisada_at: Mapped[datetime | None] = ts()
    comentario: Mapped[str | None] = txt(null=True)
