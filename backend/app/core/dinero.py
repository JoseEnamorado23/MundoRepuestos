"""Aritmética de dinero (modelo.md §1.7 y §1.8). Solo Decimal, nunca float. Módulo puro, sin BD."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")
CUATRO = Decimal("0.0001")


def r2(x: Decimal) -> Decimal:
    return x.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def r4(x: Decimal) -> Decimal:
    return x.quantize(CUATRO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Linea:
    bruto: Decimal
    descuento: Decimal
    total: Decimal  # con IVA
    base: Decimal
    impuesto: Decimal
    precio_unitario_base: Decimal  # precio antes de IVA, informativo (4 decimales)


def calcular_linea(
    cantidad: Decimal,
    precio_con_iva: Decimal,
    tarifa_pct: Decimal,
    descuento_pct: Decimal = Decimal("0"),
    descuento_valor: Decimal | None = None,
) -> Linea:
    """Algoritmo A: precio con IVA incluido -> base + IVA, redondeo por línea."""
    bruto = r2(cantidad * precio_con_iva)
    desc = r2(descuento_valor) if descuento_valor is not None else r2(bruto * descuento_pct / 100)
    total = bruto - desc
    divisor = 1 + tarifa_pct / 100
    base = r2(total / divisor)
    impuesto = total - base  # por diferencia: cuadra siempre al centavo
    return Linea(bruto, desc, total, base, impuesto, r4(precio_con_iva / divisor))


@dataclass(frozen=True)
class Totales:
    subtotal: Decimal
    descuento_total: Decimal
    impuesto_total: Decimal
    redondeo: Decimal
    total: Decimal


def calcular_totales(lineas: list[Linea], redondeo_a: int = 0) -> Totales:
    """Los totales son la SUMA de las líneas (nunca se re-extrae el IVA del total).

    redondeo_a: 0 = sin redondeo; 50 o 100 = redondeo del efectivo a esa unidad (half-up).
    """
    subtotal = sum((li.base for li in lineas), Decimal("0"))
    impuesto = sum((li.impuesto for li in lineas), Decimal("0"))
    descuento = sum((li.descuento for li in lineas), Decimal("0"))
    antes = subtotal + impuesto
    redondeo = Decimal("0")
    if redondeo_a:
        unidad = Decimal(redondeo_a)
        redondeo = (antes / unidad).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * unidad - antes
    return Totales(subtotal, descuento, impuesto, redondeo, antes + redondeo)
