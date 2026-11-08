"""Contratos de la API de ventas POS, devoluciones y terceros rápidos. Dinero siempre como Decimal (JSON: texto)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Dinero = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]
Precio = Annotated[Decimal, Field(max_digits=18, decimal_places=4)]
Cantidad = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
Pct = Annotated[Decimal, Field(ge=0, le=100, max_digits=7, decimal_places=4)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------------------------ entrada
class LineaIn(BaseModel):
    producto_id: uuid.UUID
    cantidad: Cantidad
    descuento_pct: Pct = Decimal("0")
    precio_informativo: Precio | None = Field(
        None, description="Lo que el POS mostró al cliente. SOLO informativo: el servidor usa el precio vigente."
    )
    precio_manual: Precio | None = Field(
        None, description="Precio de venta distinto al de lista; exige pos.cambiar_precio o autorizacion_precio_id."
    )


class PagoIn(BaseModel):
    medio_pago_codigo: str = Field(examples=["10", "48", "49", "47"])
    valor: Dinero | None = Field(None, gt=0, description="Monto de tarjeta/transferencia/QR (no efectivo).")
    valor_recibido: Dinero | None = Field(
        None, gt=0, description="Efectivo entregado por el cliente (el cambio lo calcula el servidor)."
    )
    referencia: str | None = Field(
        None, max_length=60, description="Aprobación del datáfono o comprobante QR/transferencia"
    )
    canal_pago: Literal["manual", "datafono", "qr", "pasarela"] = "manual"
    terminal: str | None = Field(None, max_length=60)
    ultimos_digitos: str | None = Field(None, pattern=r"^[0-9]{4}$")
    franquicia: str | None = Field(None, max_length=30)


class VentaIn(BaseModel):
    id: uuid.UUID = Field(description="UUIDv7 generado por el POS: es la clave de idempotencia de la venta.")
    tercero_id: uuid.UUID | None = Field(None, description="Cliente fiscal; por defecto, consumidor final.")
    placa_vehiculo: str | None = Field(None, max_length=12)
    notas: str | None = Field(None, max_length=500)
    descuento_global_pct: Pct = Decimal("0")
    lineas: list[LineaIn] = Field(min_length=1, max_length=200)
    pagos: list[PagoIn] = Field(min_length=1, max_length=10)
    autorizacion_descuento_id: uuid.UUID | None = Field(
        None, description="Autorización 'pos.descuento_mayor' de OTRO empleado"
    )
    autorizacion_precio_id: uuid.UUID | None = Field(
        None, description="Autorización 'pos.cambiar_precio' (PIN de supervisor o aprobación remota)"
    )


class EsperaIn(BaseModel):
    id: uuid.UUID | None = Field(
        None, description="UUIDv7; si se omite el servidor lo genera. Reutilizarlo reemplaza el carrito."
    )
    tercero_id: uuid.UUID | None = None
    placa_vehiculo: str | None = Field(None, max_length=12)
    notas: str | None = Field(None, max_length=500)
    descuento_global_pct: Pct = Decimal("0")
    lineas: list[LineaIn] = Field(min_length=1, max_length=200)


# ------------------------------------------------------------------------------------------------ salida
class LineaOut(_Out):
    id: uuid.UUID
    linea: int
    producto_id: uuid.UUID
    sku: str
    descripcion: str
    unidad_codigo: str
    cantidad: Decimal
    precio_lista: Decimal
    precio_unitario: Decimal
    descuento_pct: Decimal
    descuento_valor: Dinero
    tarifa_pct: Decimal
    bruto_linea: Dinero
    total_linea: Dinero
    base_gravable: Dinero
    impuesto_valor: Dinero


class PagoOut(_Out):
    medio_pago_codigo: str
    valor: Dinero
    valor_recibido: Dinero | None
    cambio_devuelto: Dinero
    canal_pago: str
    referencia: str | None


class DocumentoResumenOut(_Out):
    id: uuid.UUID
    tipo_documento_codigo: str
    estado: str
    numero_completo: str | None
    cufe_cude: str | None
    qr_data: str | None
    documento_referenciado_id: uuid.UUID | None = None


class VentaOut(_Out):
    id: uuid.UUID
    estado: str
    numero_interno: int | None
    sede_id: uuid.UUID
    caja_id: uuid.UUID | None
    turno_id: uuid.UUID | None
    vendedor_id: uuid.UUID | None = None
    cajero_id: uuid.UUID | None = None
    tercero_id: uuid.UUID
    placa_vehiculo: str | None
    subtotal: Dinero
    descuento_total: Dinero
    impuesto_total: Dinero
    redondeo: Dinero
    total: Dinero
    confirmada_at: datetime | None
    lineas: list[LineaOut]
    pagos: list[PagoOut]
    cambio: Dinero
    documento_fiscal: DocumentoResumenOut | None
    repetida: bool = Field(False, description="true si el id ya existía: se devuelve la venta original sin crear otra.")


class VentaResumenOut(_Out):
    id: uuid.UUID
    estado: str
    numero_interno: int | None
    caja_id: uuid.UUID | None
    turno_id: uuid.UUID | None
    vendedor_id: uuid.UUID | None = None
    cajero_id: uuid.UUID | None = None
    tercero_id: uuid.UUID
    cliente: str | None = None
    total: Dinero
    confirmada_at: datetime | None


class TerceroRapidoIn(BaseModel):
    tipo_documento_codigo: str = Field(examples=["13", "31"], description="Código DIAN (13 cédula, 31 NIT...)")
    numero_documento: str = Field(min_length=3, max_length=20, pattern=r"^[0-9A-Za-z]+$")
    razon_social: str | None = Field(None, max_length=200, description="Persona jurídica (NIT)")
    primer_nombre: str | None = Field(None, max_length=60)
    segundo_nombre: str | None = Field(None, max_length=60)
    primer_apellido: str | None = Field(None, max_length=60)
    segundo_apellido: str | None = Field(None, max_length=60)
    email_facturacion: str | None = Field(None, max_length=150)
    telefono: str | None = Field(None, max_length=30)
    direccion_fiscal: str | None = Field(None, max_length=200)
    municipio_codigo: str | None = Field(None, max_length=5)


class TerceroOut(_Out):
    id: uuid.UUID
    tipo_documento_codigo: str
    numero_documento: str
    dv: int | None
    nombre_completo: str
    email_facturacion: str | None
    telefono: str | None
    es_consumidor_final: bool


class DevolucionItemIn(BaseModel):
    venta_item_id: uuid.UUID
    cantidad: Cantidad
    destino: Literal["vendible", "averias"] = Field(
        "vendible", description="'vendible' = vuelve a la bodega de la venta; 'averias' = bodega no vendible"
    )


class DevolucionIn(BaseModel):
    id: uuid.UUID | None = Field(None, description="UUIDv7 del POS (idempotencia); si se omite lo genera el servidor.")
    venta_id: uuid.UUID
    motivo_codigo: str
    observaciones: str | None = Field(None, max_length=500)
    items: list[DevolucionItemIn] = Field(min_length=1, max_length=200)
    reembolso: Literal["efectivo", "medio_original"] = Field(
        description="'efectivo' = desde el turno ACTUAL; 'medio_original' = por el(los) medio(s) de la venta"
    )
    referencia_reembolso: str | None = Field(None, max_length=60, description="Comprobante del reembolso no efectivo")
    autorizacion_id: uuid.UUID | None = Field(None, description="Autorización 'pos.devolver' de un supervisor")


class DevolucionLineaOut(_Out):
    venta_item_id: uuid.UUID
    producto_id: uuid.UUID
    cantidad: Decimal
    total_linea: Dinero
    base_gravable: Dinero
    impuesto_valor: Dinero
    reintegra_stock: bool
    bodega_reintegro_id: uuid.UUID | None


class ReembolsoOut(_Out):
    medio_pago_codigo: str
    valor: Dinero
    referencia: str | None


class DevolucionOut(_Out):
    id: uuid.UUID
    venta_id: uuid.UUID
    estado: str
    turno_id: uuid.UUID | None
    subtotal: Dinero
    impuesto_total: Dinero
    total: Dinero
    confirmada_at: datetime | None
    lineas: list[DevolucionLineaOut]
    reembolsos: list[ReembolsoOut]
    documento_fiscal: DocumentoResumenOut | None
    repetida: bool = False


# ------------------------------------------------------------------------------------------------ tirilla y estado fiscal
class EstadoFiscalOut(_Out):
    """Estado de la FE de una venta. `definitivo=true` ⇒ el POS deja de consultar."""

    documento_id: uuid.UUID | None
    tipo: str | None
    estado: str | None
    numero_completo: str | None
    cufe: str | None
    qr_data: str | None
    leyenda: str | None
    definitivo: bool


class EstadoFiscalVentaOut(EstadoFiscalOut):
    venta_id: uuid.UUID


class TicketEmpresaOut(_Out):
    nit: str
    razon_social: str
    nombre_comercial: str | None
    direccion: str | None
    telefono: str | None


class TicketSedeOut(_Out):
    codigo: str
    nombre: str
    direccion: str | None
    telefono: str | None


class TicketCajaOut(_Out):
    codigo: str
    nombre: str


class TicketVentaOut(_Out):
    id: uuid.UUID
    numero_interno: int
    numero_ticket: str
    codigo_barras: str = Field(
        description="Texto para el Code128 de la tirilla; con él se busca la venta (devoluciones)."
    )
    fecha: datetime | None
    placa_vehiculo: str | None


class TicketClienteOut(_Out):
    documento: str
    tipo_documento: str
    nombre: str
    es_consumidor_final: bool


class TicketResolucionOut(_Out):
    numero_resolucion: str | None
    fecha_resolucion: datetime | None
    prefijo: str | None
    rango_desde: int | None
    rango_hasta: int | None
    vigente_desde: datetime | None
    vigente_hasta: datetime | None


class TicketLineaOut(_Out):
    linea: int
    sku: str | None
    descripcion: str
    cantidad: Decimal
    unidad: str | None
    precio_unitario: Decimal
    descuento_valor: Decimal
    tarifa_pct: Decimal
    total_linea: Decimal


class TicketImpuestoOut(_Out):
    codigo: str
    tarifa_pct: Decimal
    base_gravable: Decimal
    impuesto: Decimal


class TicketTotalesOut(_Out):
    subtotal: Decimal
    descuento_total: Decimal
    impuesto_total: Decimal
    redondeo: Decimal
    total: Decimal


class TicketPagoOut(_Out):
    medio_pago_codigo: str
    medio_pago: str | None
    valor: Decimal
    valor_recibido: Decimal | None
    cambio_devuelto: Decimal
    referencia: str | None
    ultimos_digitos: str | None


class TicketOut(_Out):
    """Todos los datos de la tirilla; el POS los renderiza (ESC/POS o vista previa HTML)."""

    empresa: TicketEmpresaOut
    sede: TicketSedeOut
    caja: TicketCajaOut
    cajero: str | None
    vendedor: str | None
    venta: TicketVentaOut
    cliente: TicketClienteOut
    resolucion: TicketResolucionOut | None
    lineas: list[TicketLineaOut]
    impuestos: list[TicketImpuestoOut]
    totales: TicketTotalesOut
    pagos: list[TicketPagoOut]
    cambio_total: Decimal
    fiscal: EstadoFiscalOut
