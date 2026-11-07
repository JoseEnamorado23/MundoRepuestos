"""Utilidades del catálogo: slugs, códigos EAN-13 y snapshots para eventos."""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import inspect


def sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def slugify(texto: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", sin_acentos(texto).lower()).strip("-")
    return s or "item"


def normalizar_referencia(texto: str) -> str:
    """Igual a public.f_normalizar_ref: mayúsculas y solo alfanuméricos (ASCII)."""
    return re.sub(r"[^A-Za-z0-9]", "", texto).upper()


def snapshot(obj) -> dict:
    """Valores de las columnas del objeto (para el payload de eventos y la auditoría)."""
    return {a.key: getattr(obj, a.key) for a in inspect(obj).mapper.column_attrs}


# ---------------------------------------------------------------------------------------- códigos de barras
def digito_verificador(base: str) -> int:
    """Dígito GS1 (EAN-13/EAN-8/UPC-A) para `base` (sin dígito verificador)."""
    suma = 0
    for i, ch in enumerate(reversed(base)):
        suma += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - suma % 10) % 10


def gs1_valido(codigo: str, longitud: int) -> bool:
    return (
        len(codigo) == longitud
        and codigo.isascii()
        and codigo.isdigit()
        and digito_verificador(codigo[:-1]) == int(codigo[-1])
    )


CONSECUTIVO_EAN_MAX = 999_999_999


def ean13_interno(codigo_nodo: str, consecutivo: int) -> str:
    """EAN-13 interno determinístico: '2' + código del nodo (2 dígitos) + consecutivo (9 dígitos) + verificador."""
    if not (len(codigo_nodo) == 2 and codigo_nodo.isdigit()):
        raise ValueError("El código EAN del nodo debe tener 2 dígitos.")
    if not (1 <= consecutivo <= CONSECUTIVO_EAN_MAX):
        raise ValueError("Consecutivo de EAN fuera de rango (1..999999999).")
    base = f"2{codigo_nodo}{consecutivo:09d}"
    return base + str(digito_verificador(base))
