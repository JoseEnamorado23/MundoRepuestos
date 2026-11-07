"""Logging estructurado en JSON (una línea por evento) con `request_id` tomado de un contextvar."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
ip_var: ContextVar[str | None] = ContextVar("ip_cliente", default=None)
user_agent_var: ContextVar[str | None] = ContextVar("user_agent", default=None)

_ESTANDAR = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


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
            datos["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False, default=str)


def configurar_logging(nivel: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FormatoJson())
    raiz = logging.getLogger()
    raiz.handlers = [handler]
    raiz.setLevel(nivel.upper())
    logging.getLogger("uvicorn.access").disabled = True  # el middleware ya registra cada petición
