"""Paginación estándar de listados: `limit`/`offset` + `total`, y orden por campos permitidos.

Respuesta: {"items": [...], "total": N, "limit": L, "offset": O}. El orden se pide con `orden=campo` o `orden=-campo`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errores import ReglaNegocio


class Pagina[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class Paginacion:
    limit: int
    offset: int


def _paginacion(
    limit: Annotated[int, Query(ge=1, le=200, description="Máximo de filas (1-200)")] = 50,
    offset: Annotated[int, Query(ge=0, description="Filas a saltar")] = 0,
) -> Paginacion:
    return Paginacion(limit, offset)


Pag = Annotated[Paginacion, Depends(_paginacion)]


def aplicar_orden(stmt: Select, orden: str | None, permitidos: dict, por_defecto: list) -> Select:
    """`orden` = 'campo' | '-campo'. `permitidos` mapea nombre -> columna/expresión."""
    if not orden:
        return stmt.order_by(*por_defecto)
    cols = []
    for parte in orden.split(","):
        desc = parte.startswith("-")
        nombre = parte.lstrip("-+ ")
        if nombre not in permitidos:
            raise ReglaNegocio(
                f"Orden no permitido '{nombre}'. Opciones: {', '.join(sorted(permitidos))}.", code="orden_invalido"
            )
        col = permitidos[nombre]
        cols.append(col.desc() if desc else col.asc())
    return stmt.order_by(*cols, *por_defecto)


def paginar(db: Session, stmt: Select, pag: Paginacion, *, scalars: bool = True) -> tuple[list, int]:
    """Ejecuta `stmt` paginado y devuelve (filas, total)."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    q = stmt.limit(pag.limit).offset(pag.offset)
    filas = list(db.scalars(q)) if scalars else list(db.execute(q).all())
    return filas, total or 0
