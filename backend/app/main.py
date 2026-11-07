"""Punto de entrada de la API: `uvicorn app.main:app` (o `uvicorn --factory app.main:create_app`)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import health
from app.api.middleware import RequestContextMiddleware
from app.api.problemas import registrar_manejadores
from app.core.config import validar_configuracion
from app.core.db import cargar_modelos
from app.core.logs import configurar_logging
from app.modules.auditoria.router import router as revisiones_router
from app.modules.cajas.router import dispositivos_router, pos_router
from app.modules.cajas.router_autorizaciones import admin_router as solicitudes_admin_router
from app.modules.cajas.router_autorizaciones import pos_router as solicitudes_pos_router
from app.modules.cajas.router_turnos import forzado_router
from app.modules.cajas.router_turnos import router as turnos_router
from app.modules.catalogo.router import escaner_router
from app.modules.catalogo.router import router as catalogo_router
from app.modules.identidad.router import auth_router, empleados_router
from app.modules.inventario.router import router as inventario_router
from app.modules.organizacion.nodos import verificar_nodo
from app.modules.organizacion.router import router as politicas_router
from app.modules.ventas.router import router as ventas_router

API_PREFIX = "/api/v1"


@asynccontextmanager
async def _ciclo_de_vida(app: FastAPI):
    """Al arrancar: verifica que NODO_ID exista en organizacion.nodos (falla con un mensaje claro)."""
    await run_in_threadpool(verificar_nodo)
    yield


def create_app() -> FastAPI:
    cargar_modelos()
    cfg = validar_configuracion()
    configurar_logging(cfg.log_level)
    docs = not cfg.es_produccion  # en producción no se publican /docs ni el esquema OpenAPI

    app = FastAPI(
        lifespan=_ciclo_de_vida,
        title="MundoRepuestos API",
        version=__version__,
        description="POS + e-commerce de repuestos automotrices (local-first: edge y nube comparten esta API).",
        openapi_url=f"{API_PREFIX}/openapi.json" if docs else None,
        docs_url=f"{API_PREFIX}/docs" if docs else None,
        redoc_url=None,
    )
    registrar_manejadores(app)
    if cfg.origenes_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.origenes_cors,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "Retry-After"],
        )
    app.add_middleware(RequestContextMiddleware)  # el más externo: todo (incluso errores) lleva X-Request-ID

    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(health.router)
    v1.include_router(auth_router)
    v1.include_router(empleados_router)
    v1.include_router(dispositivos_router)
    v1.include_router(pos_router)
    v1.include_router(turnos_router)
    v1.include_router(forzado_router)
    v1.include_router(ventas_router)
    v1.include_router(solicitudes_pos_router)
    v1.include_router(solicitudes_admin_router)
    v1.include_router(revisiones_router)
    v1.include_router(politicas_router)
    v1.include_router(escaner_router)
    v1.include_router(catalogo_router)
    v1.include_router(inventario_router)
    app.include_router(v1)
    return app


app = create_app()
