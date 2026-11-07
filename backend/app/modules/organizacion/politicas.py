"""Políticas de autorización por acción sensible (0010), guardadas en `organizacion.configuracion_sede`.

Cada acción tiene una clave `autorizacion.<accion>` con un objeto:

    {"politica": "libre" | "revision_posterior" | "requiere_autorizacion",
     "umbral": 200000,                       # opcional (COP): hasta aquí aplica `politica`...
     "sobre_umbral": "requiere_autorizacion"}  # ...y por encima aplica esta (por defecto requiere_autorizacion)

* `libre`: se ejecuta sin más.
* `revision_posterior`: se ejecuta y queda una fila en `auditoria.revisiones` para que el backoffice la revise.
* `requiere_autorizacion`: se exige la autorización de OTRO empleado, por PIN de supervisor en la caja o por aprobación
  remota (`identidad.solicitudes_autorizacion`).

`ajuste_inventario` y `entrada_inventario` conservan su flujo de aprobación por umbral (`inventario.umbral_aprobacion`):
aquí se DERIVAN de ese umbral (libre hasta el umbral; por encima, requiere aprobación de otro empleado con
`inventario.aprobar`), para que `GET /organizacion/politicas-autorizacion` muestre las siete acciones.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errores import ReglaNegocio
from app.modules.organizacion import configuracion as cfg

LIBRE = "libre"
REVISION = "revision_posterior"
REQUIERE = "requiere_autorizacion"
POLITICAS = (LIBRE, REVISION, REQUIERE)

ACCIONES = (
    "devolucion",
    "descuento_mayor",
    "cambiar_precio",
    "retiro_caja",
    "diferencia_arqueo",
    "ajuste_inventario",
    "entrada_inventario",
)
ACCIONES_CONFIGURABLES = ACCIONES[:5]  # las dos de inventario se derivan de inventario.umbral_aprobacion
_INVENTARIO = ("ajuste_inventario", "entrada_inventario")

# Permiso que (a) identifica la autorización de un supervisor y (b) exime de pedirla a quien ya lo tiene.
PERMISO_DE_ACCION = {
    "devolucion": "pos.devolver",
    "descuento_mayor": "pos.descuento_mayor",
    "cambiar_precio": "pos.cambiar_precio",
    "retiro_caja": "pos.retirar_efectivo",
    "diferencia_arqueo": "caja.cerrar_con_diferencia",
    "ajuste_inventario": "inventario.ajustar",
    "entrada_inventario": "inventario.ajustar",
}


def clave(accion: str) -> str:
    return f"autorizacion.{accion}"


def validar(valor: object) -> dict:
    """Valida el objeto de una política; devuelve una copia normalizada."""
    if not isinstance(valor, dict) or set(valor) - {"politica", "umbral", "sobre_umbral"}:
        raise ReglaNegocio(
            "La política debe ser un objeto con 'politica' y, opcionalmente, 'umbral' y 'sobre_umbral'.",
            code="politica_invalida",
        )
    if valor.get("politica") not in POLITICAS:
        raise ReglaNegocio(f"'politica' debe ser una de {', '.join(POLITICAS)}.", code="politica_invalida")
    if "sobre_umbral" in valor and valor["sobre_umbral"] not in POLITICAS:
        raise ReglaNegocio(f"'sobre_umbral' debe ser una de {', '.join(POLITICAS)}.", code="politica_invalida")
    umbral = valor.get("umbral")
    if umbral is not None:
        try:
            ok = Decimal(str(umbral)) >= 0
        except Exception:  # noqa: BLE001
            ok = False
        if isinstance(umbral, bool) or not ok:
            raise ReglaNegocio("'umbral' debe ser un monto >= 0.", code="politica_invalida")
    return dict(valor)


def configuracion_de(db: Session, sede_id: uuid.UUID | None, accion: str) -> dict:
    """Política efectiva de la acción (fila de la sede -> global -> valor por defecto documentado)."""
    if accion in _INVENTARIO:
        umbral = cfg.obtener(db, sede_id, "inventario.umbral_aprobacion")
        return {"politica": LIBRE, "umbral": umbral, "sobre_umbral": REQUIERE}
    if accion not in ACCIONES_CONFIGURABLES:
        raise ValueError(f"Acción sin política: {accion}")
    return cfg.obtener(db, sede_id, clave(accion))


def evaluar(db: Session, sede_id: uuid.UUID | None, accion: str, monto: Decimal | None = None) -> str:
    """'libre' | 'revision_posterior' | 'requiere_autorizacion' para esta acción y este monto."""
    c = configuracion_de(db, sede_id, accion)
    base = c["politica"]
    umbral = c.get("umbral")
    if umbral is not None and monto is not None and Decimal(str(monto)) > Decimal(str(umbral)):
        return c.get("sobre_umbral", REQUIERE)
    return base


def listar(db: Session, sede_id: uuid.UUID | None) -> dict[str, dict]:
    return {a: configuracion_de(db, sede_id, a) for a in ACCIONES}


def escribir(db: Session, sede_id: uuid.UUID, accion: str, valor: object, actor_id: uuid.UUID | None) -> dict:
    if accion not in ACCIONES_CONFIGURABLES:
        raise ReglaNegocio(
            f"La política de '{accion}' se gobierna con inventario.umbral_aprobacion "
            "(PUT /inventario/configuracion/{sede}).",
            code="politica_no_configurable",
        )
    v = validar(valor)
    if accion == "diferencia_arqueo" and REQUIERE in (v["politica"], v.get("sobre_umbral")):
        raise ReglaNegocio(
            "La diferencia de arqueo nunca bloquea el cierre del turno: use 'libre' o 'revision_posterior'.",
            code="politica_invalida",
        )
    cfg.escribir(db, sede_id, clave(accion), v, actor_id)
    return v


def minutos_expiracion_solicitud(db: Session, sede_id: uuid.UUID | None) -> int:
    return int(cfg.obtener(db, sede_id, "autorizacion.solicitud_expira_min"))
