"""Configuración de inventario por sede: delega en `organizacion.configuracion` (tabla `configuracion_sede`).

Claves:
* `inventario.umbral_aprobacion`: valor en COP a partir del cual una entrada o ajuste necesita aprobación
  (se siembra con `AJUSTE_UMBRAL_VALOR`, 500 000 por defecto);
* `inventario.propietario_autoaprueba`: si el rol «propietario» puede aprobar sus propias solicitudes (por defecto NO).
La fila de la sede manda sobre la global; si falta la fila se usa el valor por defecto documentado.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.organizacion import configuracion as cfg_sede
from app.modules.organizacion.configuracion import escribir, leer  # noqa: F401  (API pública histórica)

CLAVE_UMBRAL = "inventario.umbral_aprobacion"
CLAVE_AUTOAPROBACION = "inventario.propietario_autoaprueba"


def umbral_sede(db: Session, sede_id: uuid.UUID | None) -> Decimal:
    return cfg_sede.obtener_decimal(db, sede_id, CLAVE_UMBRAL)


def propietario_autoaprueba(db: Session, sede_id: uuid.UUID | None) -> bool:
    return cfg_sede.obtener(db, sede_id, CLAVE_AUTOAPROBACION) is True
