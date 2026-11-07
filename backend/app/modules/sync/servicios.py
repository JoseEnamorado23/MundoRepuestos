"""Outbox: toda escritura de catálogo/inventario publica su evento en la MISMA transacción.

Por ahora nadie consume los eventos (el agente de sync llega en otra etapa). `idempotency_key` es única: el
consumidor puede reintentar sin duplicar.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.base import nodo_actual, uuid7
from app.modules.sync.models import OutboxEvento


def publicar_evento(
    db: Session,
    agregado: str,
    agregado_id: uuid.UUID,
    tipo: str,
    payload: dict[str, Any],
    *,
    version: int = 1,
) -> OutboxEvento:
    """Añade un evento al outbox (sin commit). `agregado` = tipo de entidad ('producto'), `tipo` = 'producto.creado'."""
    nodo = nodo_actual()
    evento_id = uuid7()
    ev = OutboxEvento(
        id=evento_id,
        nodo_origen_id=nodo,
        agregado_tipo=agregado,
        agregado_id=agregado_id,
        evento_tipo=tipo,
        version_agregado=version,
        payload=jsonable_encoder(payload),
        idempotency_key=f"{nodo}:{agregado}:{agregado_id}:{tipo}:{evento_id}",
    )
    db.add(ev)
    return ev
