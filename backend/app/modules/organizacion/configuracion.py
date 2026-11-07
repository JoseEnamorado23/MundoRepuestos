"""Configuración por sede (`organizacion.configuracion_sede`, clave/valor jsonb) con valores por defecto documentados.

* Cada sede tiene UNA fila por clave: `inicializar` las crea (`sembrar_configuracion`) y la migración 0009 las agrega a
  las sedes ya existentes. El código SIEMPRE lee de la tabla (`obtener`): primero la fila de la sede, luego una fila
  global (`sede_id` nulo) y, solo si la fila falta (sede creada por fuera de `inicializar`), el valor por defecto de
  `CONFIG_POR_DEFECTO`, que es la misma tabla de valores que se siembra.
* El umbral de aprobación de inventario tiene además el override de entorno `AJUSTE_UMBRAL_VALOR` para sembrarlo.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.organizacion.models import ConfiguracionSede

# clave -> (valor por defecto, descripción)
CONFIG_POR_DEFECTO: dict[str, tuple[object, str]] = {
    "inventario.umbral_aprobacion": (
        500000,
        "Valor (COP) desde el cual una entrada o ajuste de inventario necesita aprobación",
    ),
    "inventario.propietario_autoaprueba": (False, "El rol propietario puede aprobar sus propias solicitudes"),
    "ventas.descuento_max_pct_por_rol": (
        {"cajero": 5, "supervisor": 15, "administrador": 100, "propietario": 100},
        "Descuento máximo (%) sin autorización de otro empleado, por rol; un rol ausente tiene tope 0",
    ),
    # Políticas de autorización por acción sensible (0010). Ver app/modules/organizacion/politicas.py
    "autorizacion.devolucion": (
        {"politica": "libre", "umbral": 200000, "sobre_umbral": "requiere_autorizacion"},
        "Política de devoluciones: libre hasta el umbral (COP); por encima, la política sobre_umbral",
    ),
    "autorizacion.descuento_mayor": (
        {"politica": "requiere_autorizacion"},
        "Política de descuentos por encima del tope del rol",
    ),
    "autorizacion.cambiar_precio": ({"politica": "requiere_autorizacion"}, "Política de cambio de precio en una línea"),
    "autorizacion.retiro_caja": (
        {"politica": "libre", "umbral": 300000, "sobre_umbral": "requiere_autorizacion"},
        "Política de retiros de efectivo: libre hasta el umbral (COP); por encima, la política sobre_umbral",
    ),
    "autorizacion.diferencia_arqueo": (
        {"politica": "revision_posterior"},
        "Política de diferencias de arqueo al cerrar el turno (nunca bloquea con revision_posterior)",
    ),
    "autorizacion.solicitud_expira_min": (5, "Minutos de vigencia de una solicitud de aprobación remota"),
    "ventas.espera_expira_horas": (24, "Horas tras las que una venta en espera se descarta"),
    "ventas.redondeo_efectivo": (0, "Redondeo del total en ventas pagadas solo en efectivo: 0 (ninguno), 50 o 100"),
}


def _por_defecto(clave: str):
    if clave == "inventario.umbral_aprobacion":
        return int(get_settings().ajuste_umbral_valor)
    return CONFIG_POR_DEFECTO[clave][0]


def leer(db: Session, sede_id: uuid.UUID | None, clave: str):
    """Valor de la fila de la sede; si no tiene, el global; si tampoco, None (sin valor por defecto)."""
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


def obtener(db: Session, sede_id: uuid.UUID | None, clave: str):
    """Valor efectivo de la clave para la sede (fila de la sede -> global -> valor por defecto documentado)."""
    v = leer(db, sede_id, clave)
    return v if v is not None else _por_defecto(clave)


def obtener_decimal(db: Session, sede_id: uuid.UUID | None, clave: str) -> Decimal:
    return Decimal(str(obtener(db, sede_id, clave)))


def escribir(db: Session, sede_id: uuid.UUID, clave: str, valor, actor_id: uuid.UUID | None) -> None:
    fila = db.scalar(
        select(ConfiguracionSede).where(ConfiguracionSede.sede_id == sede_id, ConfiguracionSede.clave == clave)
    )
    if fila is None:
        descripcion = CONFIG_POR_DEFECTO.get(clave, (None, None))[1]
        db.add(
            ConfiguracionSede(sede_id=sede_id, clave=clave, valor=valor, descripcion=descripcion, created_by=actor_id)
        )
    else:
        fila.valor = valor
    db.flush()


def sembrar_configuracion(db: Session, sede_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> list[str]:
    """Crea las claves que falten para la sede con su valor por defecto. Devuelve las creadas (idempotente)."""
    existentes = set(db.scalars(select(ConfiguracionSede.clave).where(ConfiguracionSede.sede_id == sede_id)))
    creadas: list[str] = []
    for clave, (_, descripcion) in CONFIG_POR_DEFECTO.items():
        if clave in existentes:
            continue
        db.add(
            ConfiguracionSede(
                sede_id=sede_id, clave=clave, valor=_por_defecto(clave), descripcion=descripcion, created_by=actor_id
            )
        )
        creadas.append(clave)
    if creadas:
        db.flush()
    return creadas
