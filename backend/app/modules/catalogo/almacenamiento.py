"""Compatibilidad: el almacenamiento vive en `app.core.almacenamiento` (lo usan también las facturas electrónicas)."""

from app.core.almacenamiento import Almacenamiento, AlmacenamientoLocal, get_almacenamiento

__all__ = ["Almacenamiento", "AlmacenamientoLocal", "get_almacenamiento"]
