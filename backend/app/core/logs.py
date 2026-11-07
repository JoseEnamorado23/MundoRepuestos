"""Logging estructurado en JSON (una línea por evento) con `request_id` tomado de un contextvar."""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import get_settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
ip_var: ContextVar[str | None] = ContextVar("ip_cliente", default=None)
user_agent_var: ContextVar[str | None] = ContextVar("user_agent", default=None)

_ESTANDAR = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


# --------------------------------------------------------------------------------------------- secretos
CENSURA = "***"
_SECRETOS: set[str] = set()
_BLOQUEO = threading.Lock()
_MIN_LARGO_SECRETO = 6  # valores más cortos darían falsos positivos (se censurarían palabras comunes)
_NOMBRES_SECRETOS = (
    "access_token|refresh_token|id_token|client_secret|password|passwd|secret|api_key|apikey|authorization|"
    "pin|pin_hash|jwt_secret|pin_pepper|token|x-dispositivo-token"
)
_PATRONES = (
    re.compile(r"(?i)(?<![A-Za-z0-9])(Bearer|Basic)\s+[A-Za-z0-9._~+/=\-]+"),
    # "clave": "valor"  |  clave=valor  |  'clave': 'valor'
    re.compile(rf"""(?i)((?<![A-Za-z0-9])["']?(?:{_NOMBRES_SECRETOS})["']?\s*[:=]\s*)(["']?)([^"'\s,&}}]+)(["']?)"""),
)


def registrar_secreto(valor: str | None) -> None:
    """Registra un valor sensible (token, clave) para que NUNCA salga en los logs, aparezca donde aparezca."""
    if valor and len(valor) >= _MIN_LARGO_SECRETO:
        with _BLOQUEO:
            _SECRETOS.add(valor)


def olvidar_secretos() -> None:
    """Solo para pruebas."""
    with _BLOQUEO:
        _SECRETOS.clear()


def censurar(texto: str) -> str:
    """Oculta tokens `Bearer`, pares clave/valor de nombres sensibles y los secretos registrados."""
    if not texto:
        return texto
    with _BLOQUEO:
        conocidos = sorted(_SECRETOS, key=len, reverse=True)
    for v in conocidos:
        texto = texto.replace(v, CENSURA)
    texto = _PATRONES[0].sub(lambda m: f"{m.group(1)} {CENSURA}", texto)
    return _PATRONES[1].sub(lambda m: f"{m.group(1)}{m.group(2)}{CENSURA}{m.group(4)}", texto)


def censurar_objeto(o: object) -> object:
    if isinstance(o, str):
        return censurar(o)
    if isinstance(o, dict):
        return {
            k: (CENSURA if re.fullmatch(rf"(?i){_NOMBRES_SECRETOS}", str(k)) else censurar_objeto(v))
            for k, v in o.items()
        }
    if isinstance(o, (list, tuple)):
        return type(o)(censurar_objeto(v) for v in o)
    return o


class FiltroSecretos(logging.Filter):
    """Censura mensaje, argumentos, campos `extra` y excepciones de cada registro antes de formatearlo."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = censurar(record.getMessage()) if record.args else censurar(str(record.msg))
        record.args = None
        for k, v in list(record.__dict__.items()):
            if k not in _ESTANDAR and not k.startswith("_"):
                record.__dict__[k] = censurar_objeto(v)
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = censurar(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for k, v in record.__dict__.items():  # campos añadidos con extra={...}
            if k not in _ESTANDAR and not k.startswith("_"):
                datos[k] = v
        if record.exc_info:
            datos["excepcion"] = censurar(self.formatException(record.exc_info))
        elif record.exc_text:
            datos["excepcion"] = record.exc_text
        return json.dumps(datos, ensure_ascii=False, default=str)


def configurar_logging(nivel: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FormatoJson())
    handler.addFilter(FiltroSecretos())
    for nombre in ("httpx", "httpcore"):  # registran URLs y cabeceras de cada llamada al proveedor
        logging.getLogger(nombre).setLevel(logging.WARNING)
    cfg = get_settings()
    for valor in (cfg.factus_client_secret, cfg.factus_password, cfg.jwt_secret, cfg.pin_pepper):
        registrar_secreto(valor)
    raiz = logging.getLogger()
    raiz.handlers = [handler]
    raiz.setLevel(nivel.upper())
    logging.getLogger("uvicorn.access").disabled = True  # el middleware ya registra cada petición
