"""Excepciones de dominio. La capa API las traduce a `application/problem+json` (ver app/api/problemas.py).

Los servicios lanzan estas excepciones; nunca `HTTPException`.
"""

from __future__ import annotations


class ErrorDominio(Exception):
    status = 500
    code = "error_interno"
    title = "Error"

    def __init__(self, detail: str | None = None, *, code: str | None = None, **extra: object) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code:
            self.code = code
        self.extra = extra  # datos adicionales seguros de exponer (p. ej. retry_after)


class NoAutenticado(ErrorDominio):
    status = 401
    code = "no_autenticado"
    title = "No autenticado"


class PermisoDenegado(ErrorDominio):
    status = 403
    code = "permiso_denegado"
    title = "Permiso denegado"


class NoEncontrado(ErrorDominio):
    status = 404
    code = "no_encontrado"
    title = "No encontrado"


class Conflicto(ErrorDominio):
    status = 409
    code = "conflicto"
    title = "Conflicto"


class ReglaNegocio(ErrorDominio):
    status = 422
    code = "regla_negocio"
    title = "Regla de negocio"


class DemasiadosIntentos(ErrorDominio):
    status = 429
    code = "bloqueo_temporal"
    title = "Demasiados intentos"
