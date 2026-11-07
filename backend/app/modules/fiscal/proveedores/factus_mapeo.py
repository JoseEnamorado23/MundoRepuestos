"""Snapshot del documento fiscal -> JSON de Factus v2 (`/v2/bills/validate` y `/v2/credit-notes/validate`).

Reglas de Factus v2 que condicionan el mapeo (ver docs/integraciones/factus.md):
* `price` es el valor unitario NETO (sin IVA y antes de descuento), con máximo 2 decimales; `quantity` también.
* El IVA se calcula sobre (cantidad x precio - descuento); el total de la línea es base + impuesto.
* Nuestro snapshot guarda la base gravable (`base_gravable`) ya calculada. Para que Factus parta de la MISMA base:
    precio = redondeo hacia arriba a 2 decimales de (neto antes de descuento / cantidad)
    descuento = cantidad x precio - base_gravable        (siempre >= 0; incluye el descuento real de la línea)
  Así cantidad x precio - descuento == base_gravable EXACTO, y el IVA lo calcula Factus sobre nuestra base.
* Si la cantidad tiene más de 2 decimales (p. ej. 0.333 L) no cabe en `quantity`: se envía cantidad 1 y el precio es
  el neto de toda la línea; la cantidad real va en el nombre.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from typing import Any

from app.modules.fiscal.proveedores import equivalencias as eq
from app.modules.fiscal.proveedores.base import DocumentoEmision, LineaEmision, RechazoValidacion

DOS = Decimal("0.01")
CERO = Decimal("0")
NOMBRE_CONSUMIDOR_FINAL = "Consumidor Final"


def d2(v: Decimal) -> str:
    """Decimal -> texto con exactamente 2 decimales (Factus recibe importes como cadenas)."""
    return f"{v.quantize(DOS):.2f}"


def _neto_antes_de_descuento(ln: LineaEmision) -> Decimal:
    """Valor de la línea sin IVA y antes de descuento. Nuestro descuento es CON IVA: se suma y se extrae el IVA."""
    bruto = ln.total_linea + ln.descuento_valor
    divisor = Decimal(1) + ln.tarifa_pct / Decimal(100)
    return (bruto / divisor).quantize(DOS)


def _nombre(ln: LineaEmision, cantidad_en_nombre: bool) -> str:
    nombre = ln.descripcion.strip()
    if cantidad_en_nombre:
        nombre = f"{nombre} (x {ln.cantidad.normalize():f} {ln.unidad_codigo})"
    return nombre[:250]


def _impuestos(ln: LineaEmision) -> list[dict[str, Any]]:
    if ln.tributo_codigo == "ZZ":  # excluido de IVA
        return [{"code": "01", "rate": "0.00", "is_excluded": True}]
    return [{"code": ln.tributo_codigo, "rate": d2(ln.tarifa_pct)}]


def mapear_linea(ln: LineaEmision) -> dict[str, Any]:
    cantidad = ln.cantidad
    cabe = cantidad == cantidad.quantize(DOS)
    neto = _neto_antes_de_descuento(ln)
    if cabe:
        cant_envio = cantidad.quantize(DOS)
        precio = (neto / cant_envio).quantize(DOS, rounding=ROUND_CEILING) if cant_envio > 0 else CERO
    else:
        cant_envio = Decimal("1.00")
        precio = neto
    descuento = (cant_envio * precio - ln.base_gravable).quantize(DOS)
    if (
        descuento < 0
    ):  # no debería ocurrir (precio redondeado hacia arriba); defensa para no emitir un descuento negativo
        raise RechazoValidacion(
            f"Línea {ln.codigo}: el descuento calculado es negativo ({descuento}).", errores=["descuento_negativo"]
        )
    item: dict[str, Any] = {
        "code_reference": ln.codigo[:50],
        "name": _nombre(ln, not cabe),
        "quantity": d2(cant_envio),
        "price": d2(precio),
        "unit_measure_code": eq.unidad(ln.unidad_codigo),
        "standard_code": eq.ESTANDAR_PRODUCTO,
        "taxes": _impuestos(ln),
    }
    if descuento > 0:
        item["discount_amount"] = d2(descuento)
    else:
        item["discount_rate"] = "0.00"
    return item


def mapear_cliente(a: dict[str, Any]) -> dict[str, Any]:
    """Consumidor final: identificación genérica y nombre fijo; otro tercero: datos fiscales completos."""
    persona = a.get("tipo_persona_codigo") or "2"  # 1 jurídica, 2 natural
    cliente: dict[str, Any] = {
        "identification_document_code": a["tipo_documento_codigo"],
        "identification": str(a["numero_documento"]),
        "legal_organization_code": persona,
    }
    if a.get("es_consumidor_final"):
        cliente["legal_organization_code"] = "2"
        cliente["names"] = NOMBRE_CONSUMIDOR_FINAL
        return cliente
    if a.get("dv") is not None and a["tipo_documento_codigo"] == "31":
        cliente["dv"] = str(a["dv"])
    if persona == "1":
        cliente["company"] = (a.get("razon_social") or a.get("nombre_completo") or "").strip()
    else:
        cliente["names"] = (a.get("nombre_completo") or "").strip()
    resp = a.get("responsabilidades") or []
    if resp:
        cliente["responsibilities"] = list(resp)
    cliente["tribute_code"] = "01" if a.get("regimen_codigo") == "48" else "ZZ"
    for origen, destino in (("email", "email"), ("telefono", "phone"), ("direccion", "address")):
        if a.get(origen):
            cliente[destino] = str(a[origen])
    if a.get("municipio_codigo"):
        cliente["municipality_code"] = str(a["municipio_codigo"])
        cliente["country_code"] = "CO"
    return cliente


def _pagos(doc: DocumentoEmision) -> list[dict[str, Any]]:
    forma = doc.forma_pago_codigo or "1"
    pagos = [
        {
            "payment_form": forma,
            "payment_method_code": eq.medio_pago(p.medio_pago_codigo),
            "amount": d2(p.valor),
            **({"reference_code": p.referencia[:50]} if p.referencia else {}),
        }
        for p in doc.pagos
    ]
    if not pagos:  # una nota por reembolso sin pagos registrados: se declara el total como «efectivo»
        pagos = [{"payment_form": "1", "payment_method_code": "10", "amount": d2(doc.total)}]
    return pagos


def _entero(valor: str) -> int:
    try:
        return int(valor)
    except ValueError as e:
        raise RechazoValidacion(
            f"id_rango_proveedor '{valor}' no es un id numérico de rango de Factus.", errores=["rango_invalido"]
        ) from e


def construir_factura(doc: DocumentoEmision) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "reference_code": str(doc.reference_code),
        "document": "01",
        "operation_type": "10",
        "send_email": False,
        "payment_details": _pagos(doc),
        "customer": mapear_cliente(doc.adquirente),
        "items": [mapear_linea(ln) for ln in doc.lineas],
    }
    if doc.rango_proveedor_id:
        cuerpo["numbering_range_id"] = _entero(doc.rango_proveedor_id)
    if doc.redondeo:
        cuerpo["cash_rounding_amount"] = d2(doc.redondeo)
    if doc.observacion:
        cuerpo["observation"] = doc.observacion[:500]
    return cuerpo


def construir_nota_credito(doc: DocumentoEmision) -> dict[str, Any]:
    if not doc.numero_documento_referenciado:
        raise RechazoValidacion(
            "La nota crédito necesita el número de la factura original (aún no aceptada).", errores=["sin_factura"]
        )
    concepto = eq.CONCEPTO_NC.get(doc.concepto_nota_codigo or "")
    if concepto is None:
        raise RechazoValidacion(
            f"El concepto de nota '{doc.concepto_nota_codigo}' no tiene equivalente en Factus.",
            errores=["concepto_nota_no_soportado"],
        )
    cuerpo: dict[str, Any] = {
        "reference_code": str(doc.reference_code),
        "correction_concept_code": concepto,
        "customization_id": "20",
        "bill_number": doc.numero_documento_referenciado,
        "payment_details": _pagos(doc),
        "customer": mapear_cliente(doc.adquirente),
        "items": [mapear_linea(ln) for ln in doc.lineas],
    }
    if doc.rango_proveedor_id:
        cuerpo["numbering_range_id"] = _entero(doc.rango_proveedor_id)
    if doc.observacion:
        cuerpo["observation"] = doc.observacion[:500]
    return cuerpo
