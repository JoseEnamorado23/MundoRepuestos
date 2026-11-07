"""Atajos para declarar columnas repetitivas."""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, Uuid, text
from sqlalchemy.orm import mapped_column


def fk(destino: str, *, null: bool = False, ondelete: str = "RESTRICT", **kw):
    """FK a una tabla con PK uuid (destino = 'schema.tabla.columna')."""
    return mapped_column(Uuid, ForeignKey(destino, ondelete=ondelete), nullable=null, **kw)


def fkt(destino: str, *, null: bool = False, ondelete: str = "RESTRICT", **kw):
    """FK a una tabla de referencia con PK de texto (código)."""
    return mapped_column(Text, ForeignKey(destino, ondelete=ondelete), nullable=null, **kw)


def txt(*, null: bool = False, **kw):
    return mapped_column(Text, nullable=null, **kw)


def flag(default: bool, **kw):
    return mapped_column(Boolean, nullable=False, server_default=text("true" if default else "false"), **kw)


def ts(*, null: bool = True, **kw):
    return mapped_column(DateTime(timezone=True), nullable=null, **kw)
