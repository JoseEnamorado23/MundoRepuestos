"""GET /api/v1/health: estado de la BD, modo (edge/cloud), nodo y versión de migración."""

from __future__ import annotations

import time
import uuid
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.core.base import nodo_actual
from app.core.config import get_settings
from app.core.db import get_sessionmaker

router = APIRouter(tags=["sistema"])


class BdEstado(BaseModel):
    ok: bool
    latencia_ms: float | None = None
    error: str | None = None


class HealthOut(BaseModel):
    estado: Literal["ok", "degradado"]
    version_app: str
    modo: Literal["edge", "cloud"]
    nodo_id: uuid.UUID | None
    nodo_nombre: str | None = None
    version_migracion: str | None = None
    bd: BdEstado


@router.get("/health", response_model=HealthOut, summary="Estado del servicio")
def health(response: Response) -> HealthOut:
    cfg = get_settings()
    try:
        nodo = nodo_actual()
    except RuntimeError:
        nodo = None
    out = HealthOut(estado="ok", version_app=__version__, modo=cfg.mode, nodo_id=nodo, bd=BdEstado(ok=False))
    inicio = time.perf_counter()
    try:
        with get_sessionmaker()() as s:
            s.execute(text("SELECT 1"))
            out.bd = BdEstado(ok=True, latencia_ms=round((time.perf_counter() - inicio) * 1000, 1))
            out.version_migracion = s.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
            if nodo is not None:
                out.nodo_nombre = s.execute(
                    text("SELECT nombre FROM organizacion.nodos WHERE id = :i"), {"i": nodo}
                ).scalar()
    except Exception as e:  # noqa: BLE001  (el health nunca debe lanzar: informa)
        out.bd = BdEstado(ok=False, error=type(e).__name__)
        out.estado = "degradado"
        response.status_code = 503
    return out
