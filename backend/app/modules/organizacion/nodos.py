"""Nodos de despliegue: verificación del NODO_ID configurado y listado."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import NODO_NUBE_ID, ConfiguracionInvalida, get_settings
from app.core.db import sesion
from app.modules.organizacion.models import Nodo, Sede


def verificar_nodo() -> Nodo:
    """El NODO_ID configurado debe existir y estar activo en organizacion.nodos, y coincidir con MODE."""
    cfg = get_settings()
    nodo_id = cfg.nodo_id or NODO_NUBE_ID
    with sesion() as db:
        nodo = db.get(Nodo, nodo_id)
        if nodo is not None:
            db.expunge(nodo)
    if nodo is None or nodo.estado != "activo":
        raise ConfiguracionInvalida(
            f"NODO_ID={nodo_id} no existe (o no está activo) en organizacion.nodos de esta base de datos. "
            "Liste los nodos con: uv run python -m app.cli nodos listar"
        )
    if (nodo.tipo == "edge") != (cfg.mode == "edge"):
        raise ConfiguracionInvalida(
            f"MODE={cfg.mode} no coincide con el tipo del nodo {nodo_id} ({nodo.tipo}). "
            "Revise MODE y NODO_ID en .env (uv run python -m app.cli nodos listar)."
        )
    logging.getLogger("app").info("Nodo %s (%s) verificado", nodo.nombre, nodo.tipo)
    return nodo


def siguiente_codigo_ean(db: Session) -> str:
    """Primer código EAN de 2 dígitos libre ('00' es la nube). Para registrar un nodo nuevo."""
    usados = set(db.scalars(select(Nodo.codigo_ean)))
    for n in range(100):
        c = f"{n:02d}"
        if c not in usados:
            return c
    raise ConfiguracionInvalida("No quedan códigos EAN de nodo libres (máximo 100 nodos).")


def listar_nodos(db: Session) -> list[tuple[Nodo, str | None]]:
    filas = db.execute(
        select(Nodo, Sede.nombre).outerjoin(Sede, Sede.id == Nodo.sede_id).order_by(Nodo.tipo, Nodo.nombre)
    ).all()
    return [(n, s) for n, s in filas]
