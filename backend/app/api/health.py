"""GET /api/v1/health: estado de la BD, modo (edge/cloud), nodo y versión de migración."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
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


class FiscalEstado(BaseModel):
    proveedor: str
    worker_activo: bool
    ultimo_latido_at: datetime | None = None
    ultimo_error: str | None = None
    pendientes: int = 0
    rechazados: int = 0


class HealthOut(BaseModel):
    estado: Literal["ok", "degradado"]
    version_app: str
    modo: Literal["edge", "cloud"]
    nodo_id: uuid.UUID | None
    nodo_nombre: str | None = None
    version_migracion: str | None = None
    bd: BdEstado
    fiscal: FiscalEstado | None = None


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
            out.fiscal = _fiscal(s, cfg)
            if out.fiscal.pendientes and not out.fiscal.worker_activo:
                out.estado = "degradado"  # hay documentos por emitir y nadie los está procesando
    except Exception as e:  # noqa: BLE001  (el health nunca debe lanzar: informa)
        out.bd = BdEstado(ok=False, error=type(e).__name__)
        out.estado = "degradado"
        response.status_code = 503
    return out


def _fiscal(s, cfg) -> FiscalEstado:
    """Estado del worker fiscal (latido en `fiscal.worker_latidos`) y conteo de documentos pendientes/rechazados."""
    from app.modules.fiscal import emision
    from app.modules.fiscal.models import WorkerLatido

    latido = s.get(WorkerLatido, "fiscal")
    ultimo = latido.ultimo_latido_at if latido else None
    activo = ultimo is not None and (datetime.now(UTC) - ultimo).total_seconds() <= cfg.fiscal_worker_latido_max_seg
    c = emision.contadores(s)
    return FiscalEstado(
        proveedor=cfg.fiscal_proveedor,
        worker_activo=activo,
        ultimo_latido_at=ultimo,
        ultimo_error=latido.ultimo_error if latido else None,
        pendientes=c["pendientes"],
        rechazados=c["rechazados"],
    )
