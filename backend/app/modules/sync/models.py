"""Schema `sync`: outbox/inbox, cursores y conflictos (§13). Nunca se replica: es estado local de cada nodo."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, Mutable, pg_enum, uuid7
from app.core.helpers import fk, ts, txt

SCHEMA = "sync"
EstadoOutbox = pg_enum(SCHEMA, "estado_outbox", "pendiente", "enviado", "confirmado", "fallido")
EstadoInbox = pg_enum(SCHEMA, "estado_inbox", "recibido", "aplicado", "en_espera", "conflicto", "error")
DireccionSync = pg_enum(SCHEMA, "direccion_sync", "envio", "recepcion")
TipoConflicto = pg_enum(
    SCHEMA,
    "tipo_conflicto",
    "edicion_concurrente",
    "clave_natural_duplicada",
    "estado_incompatible",
    "dependencia_faltante",
    "violacion_restriccion",
)
ResolucionConflicto = pg_enum(
    SCHEMA, "resolucion_conflicto", "pendiente", "gano_nube", "gano_edge", "fusionado", "manual", "descartado"
)


class OutboxEvento(Base):
    """Cola operativa: se escribe en la MISMA transacción que el cambio de negocio."""

    __tablename__ = "outbox_eventos"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_eventos_idempotency_key"),
        CheckConstraint("alcance IN ('local','sincronizable')", name="alcance"),
        Index(
            "ix_outbox_eventos_cola",
            "proximo_intento_at",
            "secuencia",
            postgresql_where=text("estado IN ('pendiente','fallido')"),
        ),
        Index("ix_outbox_eventos_agregado", "agregado_tipo", "agregado_id", "version_agregado"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    # Orden local de emisión; NO es identidad de entidad (nunca sale del nodo ni se referencia).
    secuencia: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    nodo_origen_id: Mapped[uuid.UUID] = fk("organizacion.nodos.id")
    nodo_destino_id: Mapped[uuid.UUID | None] = fk("organizacion.nodos.id", null=True)
    agregado_tipo: Mapped[str] = txt()
    agregado_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    evento_tipo: Mapped[str] = txt()
    version_agregado: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 'local': evento de uso exclusivo del nodo (p. ej. `fiscal.*`), el agente de sync NO lo replica.
    alcance: Mapped[str] = mapped_column(Text, nullable=False, server_default="sincronizable")
    estado: Mapped[str] = mapped_column(EstadoOutbox, nullable=False, server_default="pendiente")
    intentos: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    proximo_intento_at: Mapped[datetime] = ts(null=False, server_default=text("now()"))
    ultimo_error: Mapped[str | None] = txt(null=True)
    idempotency_key: Mapped[str] = txt()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    enviado_at: Mapped[datetime | None] = ts()
    confirmado_at: Mapped[datetime | None] = ts()


class InboxEvento(Base):
    __tablename__ = "inbox_eventos"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_inbox_eventos_idempotency_key"),
        Index(
            "ix_inbox_eventos_pendientes",
            "recibido_at",
            postgresql_where=text("estado IN ('recibido','en_espera','error')"),
        ),
        Index("ix_inbox_eventos_agregado", "agregado_tipo", "agregado_id", "version_agregado"),
        {"schema": SCHEMA},
    )
    nodo_origen_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizacion.nodos.id", ondelete="RESTRICT"), primary_key=True
    )
    evento_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    idempotency_key: Mapped[str] = txt()
    agregado_tipo: Mapped[str] = txt()
    evento_tipo: Mapped[str] = txt()
    agregado_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    version_agregado: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    estado: Mapped[str] = mapped_column(EstadoInbox, nullable=False, server_default="recibido")
    intentos: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    error: Mapped[str | None] = txt(null=True)
    recibido_at: Mapped[datetime] = ts(null=False, server_default=text("now()"))
    aplicado_at: Mapped[datetime | None] = ts()


class CursorSync(Base):
    __tablename__ = "cursores_sync"
    __table_args__ = {"schema": SCHEMA}
    nodo_remoto_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizacion.nodos.id", ondelete="RESTRICT"), primary_key=True
    )
    flujo: Mapped[str] = mapped_column(Text, primary_key=True)
    direccion: Mapped[str] = mapped_column(DireccionSync, primary_key=True)
    ultima_secuencia: Mapped[int | None] = mapped_column(BigInteger)
    ultimo_updated_at: Mapped[datetime | None] = ts()
    ultimo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    ultimo_exito_at: Mapped[datetime | None] = ts()
    ultimo_error: Mapped[str | None] = txt(null=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConflictoSync(Base, Mutable):
    __tablename__ = "conflictos_sync"
    __table_args__ = (
        Index("ix_conflictos_sync_pendientes", "created_at", postgresql_where=text("resolucion = 'pendiente'")),
        Index("ix_conflictos_sync_agregado", "agregado_tipo", "agregado_id"),
        {"schema": SCHEMA},
    )
    evento_nodo_origen_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # referencia lógica al inbox
    evento_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    agregado_tipo: Mapped[str] = txt()
    agregado_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tipo: Mapped[str] = mapped_column(TipoConflicto, nullable=False)
    version_local: Mapped[int | None] = mapped_column(Integer)
    version_remota: Mapped[int | None] = mapped_column(Integer)
    datos_locales: Mapped[dict] = mapped_column(JSONB, nullable=False)
    datos_remotos: Mapped[dict] = mapped_column(JSONB, nullable=False)
    resolucion: Mapped[str] = mapped_column(ResolucionConflicto, nullable=False, server_default="pendiente")
    resuelto_por_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)
    resuelto_at: Mapped[datetime | None] = ts()
    notas: Mapped[str | None] = txt(null=True)
