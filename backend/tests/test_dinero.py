"""Reproduce el ejemplo numérico de modelo.md §1.8 (algoritmo A, cliente con NIT, efectivo, redondeo a $50)."""

from decimal import Decimal as D

from app.core.dinero import calcular_linea, calcular_totales


def _lineas():
    return [
        calcular_linea(D("2"), D("45900.00"), D("19")),
        calcular_linea(D("1"), D("12500.00"), D("19"), descuento_pct=D("10")),
        calcular_linea(D("3"), D("3300.00"), D("5")),
        calcular_linea(D("1"), D("8030.00"), D("0")),
    ]


def test_lineas_del_ejemplo():
    esperado = [
        # total_linea, base, iva, precio unitario antes de IVA
        (D("91800.00"), D("77142.86"), D("14657.14"), D("38571.4286")),
        (D("11250.00"), D("9453.78"), D("1796.22"), D("10504.2017")),
        (D("9900.00"), D("9428.57"), D("471.43"), D("3142.8571")),
        (D("8030.00"), D("8030.00"), D("0.00"), D("8030.0000")),
    ]
    for li, (total, base, iva, unit_base) in zip(_lineas(), esperado, strict=True):
        assert li.total == total
        assert li.base == base
        assert li.impuesto == iva
        assert li.base + li.impuesto == li.total  # cuadra siempre al centavo
        assert li.precio_unitario_base == unit_base


def test_descuento_del_ejemplo():
    assert _lineas()[1].descuento == D("1250.00")


def test_totales_con_redondeo_a_50():
    t = calcular_totales(_lineas(), redondeo_a=50)
    assert t.subtotal == D("104055.21")
    assert t.impuesto_total == D("16924.79")
    assert t.subtotal + t.impuesto_total == D("120980.00")
    assert t.redondeo == D("20.00")
    assert t.total == D("121000.00")


def test_totales_sin_redondeo():
    t = calcular_totales(_lineas())
    assert t.redondeo == D("0")
    assert t.total == D("120980.00")


def test_por_linea_y_no_sobre_el_total():
    """Dos líneas de $1 000 con IVA 19 %: la suma por línea (1 680,68) difiere de extraer del total (1 680,67)."""
    lineas = [calcular_linea(D("1"), D("1000"), D("19")) for _ in range(2)]
    assert lineas[0].base == D("840.34")
    assert calcular_totales(lineas).subtotal == D("1680.68")
