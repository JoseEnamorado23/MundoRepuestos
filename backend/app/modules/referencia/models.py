"""Schema `referencia`: códigos DIAN y geografía. Sembradas por migración; no se sincronizan (modelo.md §3)."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.core.helpers import flag

SCHEMA = "referencia"


class _Ref(Base):
    __abstract__ = True
    __table_args__ = {"schema": SCHEMA}

    codigo: Mapped[str] = mapped_column(Text, primary_key=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    activo: Mapped[bool] = flag(True)


class TipoDocumentoIdentidad(_Ref):
    __tablename__ = "tipos_documento_identidad"
    abreviatura: Mapped[str | None] = mapped_column(Text)


class TipoPersona(_Ref):
    __tablename__ = "tipos_persona"


class Regimen(_Ref):
    __tablename__ = "regimenes"


class ResponsabilidadFiscal(_Ref):
    __tablename__ = "responsabilidades_fiscales"


class Tributo(_Ref):
    __tablename__ = "tributos"


class MedioPago(_Ref):
    __tablename__ = "medios_pago"
    es_efectivo: Mapped[bool] = flag(False)
    requiere_referencia: Mapped[bool] = flag(False)


class FormaPago(_Ref):
    __tablename__ = "formas_pago"


class UnidadMedida(_Ref):
    __tablename__ = "unidades_medida"
    abreviatura: Mapped[str | None] = mapped_column(Text)
    permite_decimales: Mapped[bool] = flag(True)


class Departamento(_Ref):
    __tablename__ = "departamentos"


class Municipio(_Ref):
    __tablename__ = "municipios"
    departamento_codigo: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.departamentos.codigo", ondelete="RESTRICT"), nullable=False, index=True
    )


class TipoDocumentoFiscal(_Ref):
    __tablename__ = "tipos_documento_fiscal"
    codigo_dian: Mapped[str | None] = mapped_column(Text)
    requiere_referencia: Mapped[bool] = flag(False)
    usa_resolucion: Mapped[bool] = flag(True)


class ConceptoNota(Base):
    __tablename__ = "conceptos_nota"
    __table_args__ = {"schema": SCHEMA}

    tipo_documento_codigo: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.tipos_documento_fiscal.codigo", ondelete="RESTRICT"), primary_key=True
    )
    codigo: Mapped[str] = mapped_column(Text, primary_key=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    activo: Mapped[bool] = flag(True)
