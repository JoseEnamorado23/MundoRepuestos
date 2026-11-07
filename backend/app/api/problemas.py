"""Errores en formato único `application/problem+json` (RFC 9457): type, title, status, detail, code, request_id."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errores import ErrorDominio
from app.core.logs import request_id_var

log = logging.getLogger("app.errores")
TIPO_BASE = "https://mundorepuestos.local/errores/"
MEDIA = "application/problem+json"

# Mensajes claros para restricciones conocidas (nombre de constraint/índice -> mensaje).
MENSAJES_CONSTRAINT: dict[str, str] = {
    "uq_empleados_usuario": "Ya existe un empleado con ese usuario.",
    "uq_empleados_documento": "Ya existe un empleado con ese tipo y número de documento.",
    "uq_empleados_carne": "Ese código de carné ya está asignado a otro empleado.",
    "uq_empleados_sedes_pin": "PIN no disponible.",
    "uq_dispositivos_caja_activo": "La caja ya tiene un dispositivo POS activo; revóquelo antes de registrar otro.",
    "uq_roles_codigo": "Ya existe un rol con ese código.",
    "ck_empleados_credencial": "Un empleado activo necesita usuario o código de carné.",
    "pk_autorizaciones_consumos": "La autorización ya fue consumida.",
    "uq_productos_sku": "Ya existe un producto con ese SKU.",
    "uq_productos_slug": "Ya existe un producto con ese slug.",
    "uq_productos_codigos_barras_codigo": "Ese código de barras ya existe en el catálogo.",
    "uq_productos_codigos_barras_principal": "El producto ya tiene un código de barras principal.",
    "uq_productos_referencias": "El producto ya tiene esa referencia.",
    "uq_productos_compatibilidades_producto_version": "El producto ya es compatible con esa versión.",
    "uq_marcas_nombre": "Ya existe una marca con ese nombre.",
    "uq_marcas_slug": "Ya existe una marca con ese slug.",
    "uq_categorias_hermanas": "Ya existe una categoría con ese nombre en el mismo nivel.",
    "uq_categorias_slug": "Ya existe una categoría con ese slug.",
    "uq_vehiculos_marcas_nombre": "Ya existe una marca de vehículo con ese nombre.",
    "uq_vehiculos_modelos_marca_nombre": "La marca ya tiene un modelo con ese nombre.",
    "uq_vehiculos_alias_normalizado": "Ya existe un alias con ese nombre.",
    "uq_bodegas_sede_codigo": "La sede ya tiene una bodega con ese código.",
    "uq_ubicaciones_bodega_codigo": "La bodega ya tiene una ubicación con ese código.",
    "uq_productos_imagenes_principal": "El producto ya tiene una imagen principal.",
    "ex_precios_sin_solape": "La vigencia del precio se solapa con otra existente.",
    "uq_movimientos_inventario_idempotencia": "Ese movimiento de inventario ya fue aplicado.",
    "uq_entradas_mercancia_factura": "Esa factura del proveedor ya fue registrada.",
}
_CODIGOS_PG = {
    "23505": (409, "duplicado", "Ya existe un registro con esos datos únicos."),
    "23503": (409, "referencia_invalida", "El registro referencia o es referenciado por otro que no lo permite."),
    "23514": (422, "regla_bd", "Los datos incumplen una regla de integridad."),
    "23502": (422, "dato_requerido", "Falta un dato obligatorio."),
    "23P01": (409, "solapamiento", "El registro se solapa con otro existente."),
    "23000": (422, "regla_bd", "La operación incumple una regla de integridad."),
}


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None) or request_id_var.get()


def problema(request: Request, status: int, code: str, title: str, detail: str, **extra: object) -> JSONResponse:
    cuerpo = {
        "type": f"{TIPO_BASE}{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": _rid(request),
        **extra,
    }
    return JSONResponse(cuerpo, status_code=status, media_type=MEDIA)


def traducir_integrity(e: IntegrityError) -> tuple[int, str, str]:
    """(status, code, detail) legible a partir de un IntegrityError de PostgreSQL."""
    orig = getattr(e, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or "23000"
    diag = getattr(orig, "diag", None)
    nombre = getattr(diag, "constraint_name", None)
    status, code, detalle = _CODIGOS_PG.get(sqlstate, _CODIGOS_PG["23000"])
    if nombre and nombre in MENSAJES_CONSTRAINT:
        return status, code, MENSAJES_CONSTRAINT[nombre]
    mensaje_bd = getattr(diag, "message_primary", None)
    if sqlstate == "23000" and mensaje_bd:  # RAISE EXCEPTION de nuestros triggers: ya vienen en español
        return status, code, mensaje_bd
    if nombre:
        detalle = f"{detalle} (restricción: {nombre})"
    return status, code, detalle


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ErrorDominio)
    async def _dominio(request: Request, exc: ErrorDominio):
        resp = problema(request, exc.status, exc.code, exc.title, exc.detail, **exc.extra)
        if exc.status == 429 and "retry_after" in exc.extra:
            resp.headers["Retry-After"] = str(exc.extra["retry_after"])
        if exc.status == 401:
            resp.headers["WWW-Authenticate"] = "Bearer"
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError):
        errores = [
            {"campo": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "mensaje": e["msg"]}
            for e in exc.errors()
        ]
        return problema(
            request, 422, "validacion", "Datos inválidos", "La petición no cumple el esquema.", errores=errores
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {404: "ruta_no_encontrada", 405: "metodo_no_permitido"}.get(exc.status_code, "http_error")
        return problema(request, exc.status_code, code, "Error HTTP", str(exc.detail))

    @app.exception_handler(IntegrityError)
    async def _integridad(request: Request, exc: IntegrityError):
        status, code, detalle = traducir_integrity(exc)
        return problema(request, status, code, "Restricción de integridad", detalle)

    @app.exception_handler(StaleDataError)
    async def _version(request: Request, exc: StaleDataError):
        return problema(
            request,
            409,
            "version_obsoleta",
            "Conflicto de versión",
            "El registro fue modificado por otra persona; recárguelo e intente de nuevo.",
        )

    @app.exception_handler(OperationalError)
    async def _bd(request: Request, exc: OperationalError):
        log.error("BD no disponible", exc_info=exc)
        return problema(
            request, 503, "bd_no_disponible", "Servicio no disponible", "No hay conexión con la base de datos."
        )

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, exc: Exception):
        log.exception("error no controlado")
        return problema(request, 500, "error_interno", "Error interno", "Ocurrió un error inesperado.")
