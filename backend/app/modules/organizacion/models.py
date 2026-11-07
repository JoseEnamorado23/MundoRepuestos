"""Schema `organizacion`: empresa, sedes, nodos y configuración (modelo.md §4)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, Mutable, pg_enum
from app.core.helpers import fk, fkt, flag, ts, txt

SCHEMA = "organizacion"
NodoTipo = pg_enum(SCHEMA, "nodo_tipo", "cloud", "edge")
NodoEstado = pg_enum(SCHEMA, "nodo_estado", "activo", "inactivo")


class Empresa(Base, Mutable):
    __tablename__ = "empresas"
    __table_args__ = (
        UniqueConstraint("nit", name="uq_empresas_nit"),
        CheckConstraint("nit ~ '^[0-9]{6,12}$'", name="nit_formato"),
        CheckConstraint("dv BETWEEN 0 AND 9", name="dv_rango"),
        {"schema": SCHEMA},
    )
    nit: Mapped[str] = txt()
    dv: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    razon_social: Mapped[str] = txt()
    nombre_comercial: Mapped[str | None] = txt(null=True)
    tipo_persona_codigo: Mapped[str] = fkt("referencia.tipos_persona.codigo")
    regimen_codigo: Mapped[str] = fkt("referencia.regimenes.codigo")
    actividad_economica_ciiu: Mapped[str | None] = txt(null=True)
    matricula_mercantil: Mapped[str | None] = txt(null=True)
    municipio_codigo: Mapped[str] = fkt("referencia.municipios.codigo")
    direccion: Mapped[str] = txt()
    telefono: Mapped[str | None] = txt(null=True)
    email: Mapped[str | None] = txt(null=True)
    logo_url: Mapped[str | None] = txt(null=True)
    activo: Mapped[bool] = flag(True)


class EmpresaResponsabilidad(Base):
    __tablename__ = "empresas_responsabilidades"
    __table_args__ = {"schema": SCHEMA}
    empresa_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.empresas.id", ondelete="CASCADE"), primary_key=True
    )
    responsabilidad_codigo: Mapped[str] = mapped_column(
        Text, ForeignKey("referencia.responsabilidades_fiscales.codigo", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Sede(Base, Mutable):
    __tablename__ = "sedes"
    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_sedes_empresa_codigo"),
        CheckConstraint("codigo ~ '^[A-Z0-9]{2,6}$'", name="codigo_formato"),
        {"schema": SCHEMA},
    )
    empresa_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.empresas.id")
    codigo: Mapped[str] = txt()
    nombre: Mapped[str] = txt()
    municipio_codigo: Mapped[str] = fkt("referencia.municipios.codigo")
    direccion: Mapped[str] = txt()
    telefono: Mapped[str | None] = txt(null=True)
    permite_recoger_pedidos: Mapped[bool] = flag(True)
    activo: Mapped[bool] = flag(True)


class Nodo(Base, Mutable):
    __tablename__ = "nodos"
    __table_args__ = (
        CheckConstraint(
            "(tipo = 'edge' AND sede_id IS NOT NULL) OR (tipo = 'cloud' AND sede_id IS NULL)",
            name="sede_segun_tipo",
        ),
        # Un solo edge activo por sede (dos edges escribiendo la misma sede romperían el modelo de dueño único).
        Index(
            "uq_nodos_edge_activo_por_sede",
            "sede_id",
            unique=True,
            postgresql_where=text("tipo = 'edge' AND estado = 'activo'"),
        ),
        CheckConstraint("codigo_ean ~ '^[0-9]{2}$'", name="codigo_ean_formato"),
        UniqueConstraint("codigo_ean", name="uq_nodos_codigo_ean"),
        {"schema": SCHEMA},
    )
    tipo: Mapped[str] = mapped_column(NodoTipo, nullable=False)
    # 2 dígitos para los EAN-13 internos '2' + nodo + consecutivo + dígito verificador (nube = 00, sedes 01, 02...)
    codigo_ean: Mapped[str] = txt()
    sede_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.sedes.id", null=True)
    nombre: Mapped[str] = txt()
    estado: Mapped[str] = mapped_column(NodoEstado, nullable=False, server_default="activo")
    token_sync_hash: Mapped[str | None] = txt(null=True)
    version_app: Mapped[str | None] = txt(null=True)
    version_esquema: Mapped[str | None] = txt(null=True)
    ultimo_latido_at: Mapped[datetime | None] = ts()


class ConfiguracionSede(Base, Mutable):
    __tablename__ = "configuracion_sede"
    __table_args__ = {"schema": SCHEMA}  # unicidad (COALESCE(sede_id), clave): migración 0003
    sede_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.sedes.id", null=True)
    clave: Mapped[str] = txt()
    valor: Mapped[dict] = mapped_column(JSONB, nullable=False)
    descripcion: Mapped[str | None] = txt(null=True)
