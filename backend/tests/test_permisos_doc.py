"""docs/permisos.md está generado desde la BD: debe coincidir con los permisos/roles sembrados por las migraciones."""

from __future__ import annotations

from scripts.permisos_doc import DESTINO, generar


def test_permisos_md_esta_al_dia(conn):
    esperado = generar(conn)
    actual = DESTINO.read_text(encoding="utf-8")
    assert actual == esperado, "docs/permisos.md desactualizado: ejecute `uv run python -m scripts.permisos_doc`"


def test_no_queda_el_permiso_precio_manual(conn):
    md = generar(conn)
    assert "pos.precio_manual" not in md and "`pos.cambiar_precio`" in md
    assert "`autorizaciones.aprobar`" in md and "`revisiones.gestionar`" in md and "`vendedor`" in md
