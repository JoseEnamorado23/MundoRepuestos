"""Reglas de dependencia entre capas y módulos (análisis estático con `ast`; no importa la aplicación).

    api  ->  aplicacion  ->  modules (servicios)  ->  core

* `core` no importa nada de `modules`, `aplicacion` ni `api` (solo el registro `app.models` de `core/db.py`).
* Los servicios de un módulo (todo lo que no es `router*.py` ni `schemas.py`) no importan `api`, `aplicacion`, `main` ni `cli`.
* `api` (dependencias y utilidades HTTP) no importa `aplicacion`; `aplicacion` no importa `api`, `main` ni `cli`.
* Entre módulos solo hay dependencias "hacia abajo" (referencia -> organizacion -> identidad -> catalogo -> inventario ->
  compras -> cajas -> ventas -> pedidos -> fiscal); `sync` y `auditoria` son transversales y no dependen de módulos de negocio.
* Todo borde entre módulos debe estar en la lista congelada `DEPENDENCIAS` (y documentada en docs/arquitectura.md):
  una dependencia nueva obliga a editar esta lista A PROPÓSITO.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
DOCS = Path(__file__).resolve().parents[2] / "docs"

ORDEN = [
    "referencia",
    "organizacion",
    "identidad",
    "catalogo",
    "inventario",
    "compras",
    "cajas",
    "ventas",
    "pedidos",
    "fiscal",
]
TRANSVERSALES = {"sync", "auditoria"}
CAPAS_SUPERIORES = {"api", "aplicacion", "main", "cli"}

# Dependencias entre módulos permitidas (congeladas). Clave = módulo que importa.
DEPENDENCIAS: dict[str, set[str]] = {
    "referencia": set(),
    "organizacion": {"auditoria", "sync"},
    "identidad": {"auditoria", "organizacion", "sync"},
    "catalogo": {"auditoria", "organizacion", "sync"},
    "inventario": {"auditoria", "catalogo", "identidad", "organizacion", "sync"},
    "compras": set(),
    "cajas": {"auditoria", "identidad", "inventario", "organizacion", "referencia", "sync"},
    "ventas": {"auditoria", "cajas", "catalogo", "identidad", "inventario", "organizacion", "referencia", "sync"},
    "pedidos": set(),
    "fiscal": {"auditoria", "cajas", "identidad", "organizacion", "sync", "ventas"},
    "auditoria": {"sync"},
    "sync": set(),
}


def _importaciones(fuente: str) -> set[str]:
    """Módulos `app.X[.Y]` importados (a cualquier profundidad del archivo)."""
    out: set[str] = set()
    for n in ast.walk(ast.parse(fuente)):
        if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module)
        elif isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
    return {m for m in out if m == "app" or m.startswith("app.")}


def _destino(importado: str) -> tuple[str, str | None]:
    """(capa, módulo) de un import: `app.modules.ventas.x` -> ('modules', 'ventas'); `app.core.y` -> ('core', None)."""
    partes = importado.split(".")
    capa = partes[1] if len(partes) > 1 else ""
    if capa == "modules":
        return "modules", partes[2] if len(partes) > 2 else None
    return capa, None


def _es_borde_http(archivo: Path) -> bool:
    return archivo.name.startswith("router") or archivo.name == "schemas.py"


def violaciones(archivo_rel: str, fuente: str) -> list[str]:
    """Reglas aplicadas a UN archivo (`archivo_rel` relativo a `app/`). Función pura: se prueba con fuentes sintéticas."""
    partes = Path(archivo_rel).parts
    capa = partes[0]
    modulo = partes[1] if capa == "modules" and len(partes) > 2 else None
    errores: list[str] = []
    for imp in _importaciones(fuente):
        dcapa, dmod = _destino(imp)
        if capa == "core":
            if dcapa not in ("core", "models"):
                errores.append(f"core no puede importar {imp}")
        elif capa == "api":
            if dcapa in ("aplicacion", "main", "cli"):
                errores.append(f"api no puede importar {imp}")
        elif capa == "aplicacion":
            if dcapa in ("api", "main", "cli"):
                errores.append(f"aplicacion no puede importar {imp}")
        elif capa == "modules" and modulo is not None:
            if dcapa in CAPAS_SUPERIORES and not (_es_borde_http(Path(archivo_rel)) and dcapa in ("api", "aplicacion")):
                errores.append(f"{modulo}: un servicio no puede importar {imp}")
            if dcapa == "modules" and dmod and dmod != modulo:
                if modulo in TRANSVERSALES and dmod not in TRANSVERSALES:
                    errores.append(f"{modulo} (transversal) no puede depender del módulo de negocio {dmod}")
                elif modulo in ORDEN and dmod in ORDEN and ORDEN.index(dmod) > ORDEN.index(modulo):
                    errores.append(f"{modulo} -> {dmod} es una dependencia hacia ARRIBA")
                elif dmod not in DEPENDENCIAS.get(modulo, set()):
                    errores.append(f"{modulo} -> {dmod} no está en DEPENDENCIAS (¿dependencia nueva?)")
    return errores


def _archivos():
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in p.parts)


def test_el_codigo_cumple_las_reglas_de_capas_y_modulos():
    todas = []
    for p in _archivos():
        rel = p.relative_to(APP)
        if rel.parts[0] not in ("core", "api", "aplicacion", "modules"):
            continue
        todas += [f"{rel}: {e}" for e in violaciones(str(rel), p.read_text(encoding="utf-8"))]
    assert not todas, "Violaciones de arquitectura:\n" + "\n".join(todas)


def test_la_lista_congelada_no_tiene_bordes_que_el_codigo_ya_no_usa():
    usados: dict[str, set[str]] = defaultdict(set)
    for p in _archivos():
        rel = p.relative_to(APP)
        if rel.parts[0] != "modules" or len(rel.parts) < 3:
            continue
        for imp in _importaciones(p.read_text(encoding="utf-8")):
            dcapa, dmod = _destino(imp)
            if dcapa == "modules" and dmod and dmod != rel.parts[1]:
                usados[rel.parts[1]].add(dmod)
    sobran = {
        m: sorted(DEPENDENCIAS[m] - usados.get(m, set()))
        for m in DEPENDENCIAS
        if DEPENDENCIAS[m] - usados.get(m, set())
    }
    assert not sobran, f"Quite de DEPENDENCIAS (y de docs/arquitectura.md) lo que ya no se usa: {sobran}"


def test_las_dependencias_estan_documentadas():
    doc = (DOCS / "arquitectura.md").read_text(encoding="utf-8")
    for modulo, deps in DEPENDENCIAS.items():
        linea = next((ln for ln in doc.splitlines() if ln.startswith(f"| `{modulo}` |")), None)
        assert linea is not None, f"docs/arquitectura.md no documenta las dependencias de {modulo}"
        for d in deps:
            assert f"`{d}`" in linea, f"docs/arquitectura.md: {modulo} -> {d} no está documentado"


# ---- el verificador detecta de verdad las violaciones (pruebas con código sintético) ----
@pytest.mark.parametrize(
    ("archivo", "fuente", "esperado"),
    [
        ("core/x.py", "from app.modules.ventas.servicios import y", "core no puede importar"),
        ("modules/ventas/servicios.py", "from app.api.deps import Db", "no puede importar"),
        ("modules/ventas/servicios.py", "from app.aplicacion.ventas import z", "no puede importar"),
        ("modules/inventario/servicios.py", "from app.modules.cajas.servicios import z", "hacia ARRIBA"),
        ("modules/catalogo/servicios.py", "from app.modules.ventas import servicios", "hacia ARRIBA"),
        ("modules/ventas/servicios.py", "from app.modules.fiscal import servicios", "hacia ARRIBA"),
        ("modules/auditoria/servicios.py", "from app.modules.identidad.models import E", "transversal"),
        ("modules/cajas/servicios.py", "from app.modules.catalogo.models import C", "no está en DEPENDENCIAS"),
        ("aplicacion/ventas.py", "from app.api.deps import Db", "aplicacion no puede importar"),
        ("api/deps.py", "from app.aplicacion import ventas", "api no puede importar"),
    ],
)
def test_el_verificador_detecta_violaciones(archivo, fuente, esperado):
    errores = violaciones(archivo, fuente)
    assert any(esperado in e for e in errores), errores


def test_los_routers_si_pueden_usar_api_y_aplicacion():
    fuente = "from app.api.deps import Db\nfrom app.aplicacion import ventas\n"
    assert violaciones("modules/ventas/router.py", fuente) == []
    assert violaciones("modules/ventas/servicios.py", fuente) != []
