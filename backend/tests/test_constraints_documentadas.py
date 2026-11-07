"""Los nombres de constraints e índices (ck_*, uq_*, ix_*, ex_*) que cita docs/base-de-datos/modelo.md deben existir en la
BD migrada, y a la inversa (nombres de la BD sin documentar) se avisa con una advertencia.

La deriva que YA existía al crear esta prueba está congelada en `nombres_documentados_pendientes.txt`: solo puede encogerse.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from sqlalchemy import text

MODELO = Path(__file__).resolve().parents[2] / "docs" / "base-de-datos" / "modelo.md"
PENDIENTES = Path(__file__).with_name("nombres_documentados_pendientes.txt")
NOMBRE = re.compile(r"\b(?:ck|uq|ix|ex)_[a-z0-9_]+")
PREFIJO_BD = re.compile(r"^(?:ck|uq|ix|ex)_")


def _documentados() -> set[str]:
    return {m.rstrip("_") for m in NOMBRE.findall(MODELO.read_text(encoding="utf-8"))}


def _pendientes() -> set[str]:
    return {
        ln.strip()
        for ln in PENDIENTES.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    }


def _en_bd(conn) -> set[str]:
    filas = conn.execute(
        text(
            "SELECT c.conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
            "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
            "UNION SELECT indexname FROM pg_indexes WHERE schemaname NOT IN ('pg_catalog','information_schema')"
        )
    ).scalars()
    return set(filas)


def test_los_nombres_documentados_existen_en_la_bd(conn):
    en_bd = _en_bd(conn)
    faltan = _documentados() - en_bd
    pendientes = _pendientes()
    nuevos = sorted(faltan - pendientes)
    assert not nuevos, (
        "modelo.md cita constraints/índices que NO existen en la BD (y no estaban en la lista congelada): "
        f"{nuevos}. Corrija el documento o la migración."
    )
    obsoletos = sorted(pendientes - faltan)
    assert not obsoletos, (
        "Estos nombres ya existen en la BD o ya no se citan en modelo.md: quítelos de "
        f"tests/nombres_documentados_pendientes.txt: {obsoletos}"
    )


def test_nombres_de_la_bd_sin_documentar_son_solo_advertencia(conn):
    documentados = _documentados()
    sin_documentar = sorted(n for n in _en_bd(conn) if PREFIJO_BD.match(n) and n not in documentados)
    if sin_documentar:
        warnings.warn(
            f"{len(sin_documentar)} constraints/índices de la BD no aparecen en modelo.md "
            f"(p. ej. {', '.join(sin_documentar[:8])}...)",
            UserWarning,
            stacklevel=1,
        )
    assert isinstance(sin_documentar, list)  # nunca falla: la documentación completa de nombres es deseable, no exigida


def test_la_lista_de_pendientes_esta_ordenada_y_sin_duplicados():
    lineas = [
        ln.strip()
        for ln in PENDIENTES.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    assert lineas == sorted(set(lineas))
