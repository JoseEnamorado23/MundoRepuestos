"""Casos de uso del backoffice fiscal que coordinan más de un módulo."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.modules.fiscal import emision
from app.modules.fiscal.models import DocumentoFiscal
from app.modules.identidad import terceros


def corregir_documento(
    db: Session,
    doc_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    cambios_adquirente: dict[str, Any],
    motivo: str,
    *,
    actualizar_tercero: bool = False,
) -> DocumentoFiscal:
    """Corrige y reemite una FE rechazada (fiscal) y, si se pide, aplica los mismos cambios al maestro de terceros
    (identidad) en la MISMA transacción: o se hace todo o nada. Sin `actualizar_tercero` el maestro no se toca."""
    nuevo = emision.corregir_y_reemitir(db, doc_id, actor_id, cambios_adquirente, motivo)
    if actualizar_tercero:
        terceros.actualizar_datos_fiscales(
            db, nuevo.adquirente_tercero_id, cambios_adquirente, actor_id, sede_id=nuevo.sede_id, motivo=motivo
        )
    return nuevo
