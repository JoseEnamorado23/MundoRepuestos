"""Utilidades transversales sin dependencias de módulos."""

from __future__ import annotations

from sqlalchemy import inspect


def snapshot(obj) -> dict:
    """Valores de las columnas del objeto (para el payload de eventos y la auditoría)."""
    return {a.key: getattr(obj, a.key) for a in inspect(obj).mapper.column_attrs}
