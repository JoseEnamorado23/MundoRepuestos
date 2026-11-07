"""Primitivas de seguridad: hash de contraseñas/PIN (argon2id), tokens JWT, tokens opacos y huellas."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.errores import NoAutenticado

_hasher = PasswordHasher()  # argon2id con parámetros por defecto de argon2-cffi
# Hash válido de una cadena aleatoria: se verifica cuando el usuario no existe para igualar tiempos de respuesta.
_HASH_FALSO = _hasher.hash(secrets.token_urlsafe(16))


def ahora() -> datetime:
    return datetime.now(UTC)


# --- contraseñas y PIN -------------------------------------------------------------------------
def hash_secreto(valor: str) -> str:
    return _hasher.hash(valor)


def verificar_secreto(valor: str, hash_guardado: str | None) -> bool:
    """Verificación en tiempo casi constante; con `hash_guardado=None` gasta el mismo tiempo y devuelve False."""
    try:
        _hasher.verify(hash_guardado or _HASH_FALSO, valor)
        return hash_guardado is not None
    except (VerificationError, InvalidHashError):
        return False


def indice_pin(sede_id: uuid.UUID, pin: str) -> str:
    """HMAC-SHA256(pimienta, sede || PIN): permite identificar al empleado solo con el PIN y garantizar
    unicidad por sede con un índice UNIQUE (el hash argon2 es salado y no sirve para eso)."""
    clave = get_settings().pin_pepper.encode()
    return hmac.new(clave, f"{sede_id}:{pin}".encode(), hashlib.sha256).hexdigest()


# --- tokens opacos (refresh, dispositivo) --------------------------------------------------------
def nuevo_token_opaco(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


# --- JWT ----------------------------------------------------------------------------------------
def crear_jwt(claims: dict[str, Any], ttl: timedelta) -> tuple[str, datetime]:
    cfg = get_settings()
    emitido = ahora()
    expira = emitido + ttl
    payload = {**claims, "iat": emitido, "exp": expira, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algoritmo), expira


def decodificar_jwt(token: str, *, tipo: str) -> dict[str, Any]:
    cfg = get_settings()
    try:
        datos = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algoritmo], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError as e:
        raise NoAutenticado("El token expiró", code="token_expirado") from e
    except jwt.InvalidTokenError as e:
        raise NoAutenticado("Token inválido", code="token_invalido") from e
    if datos.get("typ") != tipo:
        raise NoAutenticado("Tipo de token incorrecto para este recurso", code="token_invalido")
    return datos
