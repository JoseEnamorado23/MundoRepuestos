"""Configuración de inventario por sede (tabla `organizacion.configuracion_sede`, clave/valor jsonb).

Claves:
* `inventario.umbral_aprobacion`: valor en COP a partir del cual una entrada o ajuste necesita aprobación
  (por defecto `AJUSTE_UMBRAL_VALOR`, 500 000);
* `inventario.propietario_autoaprueba`: si el rol «propietario» puede aprobar sus propias solicitudes (por defecto NO).
Una fila con `sede_id` nulo es el valor global; la fila de la sede manda sobre la global.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.organizacion.models import ConfiguracionSede

CLAVE_UMBRAL = "inventario.umbral_aprobacion"
CLAVE_AUTOAPROBACION = "inventario.propietario_autoaprueba"


def leer(db: Session, sede_id: uuid.UUID | None, clave: str):
    """Valor de la sede; si no tiene, el global; si tampoco, None."""
    for sid in (sede_id, None) if sede_id is not None else (None,):
        fila = db.scalar(
            select(ConfiguracionSede).where(
                ConfiguracionSede.clave == clave,
                ConfiguracionSede.sede_id.is_(None) if sid is None else ConfiguracionSede.sede_id == sid,
            )
        )
        if fila is not None:
            return fila.valor
    return None


def escribir(db: Session, sede_id: uuid.UUID, clave: str, valor, actor_id: uuid.UUID | None) -> None:
    fila = db.scalar(
        select(ConfiguracionSede).where(ConfiguracionSede.sede_id == sede_id, ConfiguracionSede.clave == clave)
    )
    if fila is None:
        db.add(ConfiguracionSede(sede_id=sede_id, clave=clave, valor=valor, created_by=actor_id))
    else:
        fila.valor = valor
    db.flush()


def umbral_sede(db: Session, sede_id: uuid.UUID | None) -> Decimal:
    v = leer(db, sede_id, CLAVE_UMBRAL)
    return Decimal(str(v)) if v is not None else get_settings().ajuste_umbral_valor


def propietario_autoaprueba(db: Session, sede_id: uuid.UUID | None) -> bool:
    return leer(db, sede_id, CLAVE_AUTOAPROBACION) is True
