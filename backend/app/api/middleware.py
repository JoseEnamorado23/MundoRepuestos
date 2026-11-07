"""Middleware ASGI: X-Request-ID, contexto de la petición (ip, user-agent) y una línea de log JSON por petición."""

from __future__ import annotations

import ipaddress
import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logs import ip_var, request_id_var, user_agent_var

log = logging.getLogger("app.http")
_VALIDO = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
CABECERA = "X-Request-ID"


def _ip_valida(cliente) -> str | None:
    """La IP va a columnas INET: solo se acepta si parsea (p. ej. el cliente de pruebas o un socket unix no son IP)."""
    try:
        return str(ipaddress.ip_address(cliente[0])) if cliente else None
    except ValueError:
        return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        entrante = headers.get(CABECERA, "")
        rid = entrante if _VALIDO.match(entrante) else str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = rid
        cliente = scope.get("client")
        t_rid = request_id_var.set(rid)
        t_ip = ip_var.set(_ip_valida(cliente))
        t_ua = user_agent_var.set((headers.get("user-agent") or "")[:300] or None)
        inicio = time.perf_counter()
        estado = 500

        async def send_con_id(message: Message) -> None:
            nonlocal estado
            if message["type"] == "http.response.start":
                estado = message["status"]
                MutableHeaders(scope=message)[CABECERA] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_con_id)
        finally:
            log.info(
                "petición",
                extra={
                    "metodo": scope["method"],
                    "ruta": scope["path"],
                    "estado": estado,
                    "duracion_ms": round((time.perf_counter() - inicio) * 1000, 1),
                },
            )
            request_id_var.reset(t_rid)
            ip_var.reset(t_ip)
            user_agent_var.reset(t_ua)
