"""Interfaz `ProveedorFiscal` y tipos comunes a todos los proveedores tecnológicos (Factus, simulado, otros).

Los proveedores reciben un `DocumentoEmision` (datos planos construidos desde el SNAPSHOT del documento fiscal, nunca
desde los maestros) y devuelven una `RespuestaProveedor` o lanzan una de tres excepciones que el worker clasifica:

* `ErrorTransitorio`  -> red, timeout, 5xx, 429, 401 sin recuperar: se reintenta con backoff.
* `RechazoValidacion` -> reglas DIAN/proveedor: estado `rechazado`, no se reintenta solo.
* `ErrorConfiguracion` -> credenciales, rango inexistente, ruta no disponible: se reintenta pocas veces y alerta.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal


class ErrorProveedor(Exception):
    """Base de los errores del proveedor. `detalle` nunca contiene secretos."""

    def __init__(self, mensaje: str, *, http_status: int | None = None, detalle: dict[str, Any] | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.http_status = http_status
        self.detalle = detalle or {}


class ErrorTransitorio(ErrorProveedor):
    """Se puede reintentar sin riesgo (el `reference_code` hace idempotente el reenvío)."""

    def __init__(self, mensaje: str, *, http_status: int | None = None, reintentar_en: float | None = None, **kw):
        super().__init__(mensaje, http_status=http_status, **kw)
        self.reintentar_en = reintentar_en  # segundos pedidos por el proveedor (Retry-After)


class ConflictoPendiente(ErrorTransitorio):
    """409: el proveedor tiene un documento sin validar que bloquea nuevos envíos."""


class RechazoValidacion(ErrorProveedor):
    """El proveedor o la DIAN rechazan el contenido. `errores` = lista de textos/reglas (p. ej. 'FAJ43b: …')."""

    def __init__(self, mensaje: str, *, errores: list[str] | None = None, **kw):
        super().__init__(mensaje, **kw)
        self.errores = errores or []


class ErrorConfiguracion(ErrorProveedor):
    """Credenciales, rango de numeración o ruta no disponible para esta empresa."""


@dataclass
class LineaEmision:
    codigo: str
    descripcion: str
    unidad_codigo: str
    cantidad: Decimal
    # importes del SNAPSHOT (con IVA el precio y el descuento; base/impuesto/total ya calculados por nosotros)
    precio_unitario: Decimal
    descuento_valor: Decimal
    base_gravable: Decimal
    impuesto_valor: Decimal
    total_linea: Decimal
    tributo_codigo: str
    tarifa_pct: Decimal


@dataclass
class PagoEmision:
    medio_pago_codigo: str
    valor: Decimal
    referencia: str | None = None


@dataclass
class DocumentoEmision:
    reference_code: uuid.UUID  # = documentos_fiscales.id: idempotencia en el proveedor
    tipo: Literal["FE", "NC"]
    fecha: datetime
    rango_proveedor_id: str | None  # resoluciones_numeracion.id_rango_proveedor
    prefijo_resolucion: str
    adquirente: dict[str, Any]  # snapshot
    lineas: list[LineaEmision]
    pagos: list[PagoEmision]
    forma_pago_codigo: str
    subtotal: Decimal
    impuesto_total: Decimal
    redondeo: Decimal
    total: Decimal
    observacion: str | None = None
    # solo notas
    numero_documento_referenciado: str | None = None  # número que el proveedor asignó a la FE original
    concepto_nota_codigo: str | None = None


@dataclass
class RespuestaProveedor:
    estado: Literal["aceptado", "pendiente"]  # "pendiente": enviado pero la DIAN aún no valida
    numero: str | None = None  # número completo asignado por el proveedor (prefijo + consecutivo)
    cufe: str | None = None
    qr_url: str | None = None
    url_publica: str | None = None
    validado_at: datetime | None = None
    # totales calculados por el PROVEEDOR (para comprobar que cuadran con los nuestros)
    subtotal: Decimal | None = None
    impuesto_total: Decimal | None = None
    total: Decimal | None = None
    advertencias: list[str] = field(default_factory=list)  # notificaciones informativas de la DIAN (no son rechazo)
    http_status: int | None = None
    crudo: dict[str, Any] = field(default_factory=dict)  # respuesta SANEADA, para documentos_fiscales_eventos


class ProveedorFiscal(ABC):
    """Contrato del proveedor tecnológico. Todas las operaciones son idempotentes por `reference_code`."""

    nombre: str

    @abstractmethod
    def emitir_factura(self, doc: DocumentoEmision) -> RespuestaProveedor: ...

    @abstractmethod
    def emitir_nota_credito(self, doc: DocumentoEmision) -> RespuestaProveedor: ...

    @abstractmethod
    def consultar_documento(self, tipo: Literal["FE", "NC"], numero: str) -> RespuestaProveedor: ...

    @abstractmethod
    def descargar_pdf(self, tipo: Literal["FE", "NC"], numero: str) -> bytes: ...

    @abstractmethod
    def descargar_xml(self, tipo: Literal["FE", "NC"], numero: str) -> bytes: ...

    @abstractmethod
    def eliminar_pendiente(self, tipo: Literal["FE", "NC"], reference_code: uuid.UUID) -> bool:
        """Borra en el proveedor un documento NO validado por la DIAN (desbloquea el 409). True si lo borró."""

    def cerrar(self) -> None:  # noqa: B027  # pragma: no cover - opcional
        """Libera recursos (conexiones HTTP)."""
