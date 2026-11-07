"""Equivalencias entre NUESTROS códigos (DIAN) y los que espera Factus v2.

Factus v2 usa CÓDIGOS (no ids numéricos) para documentos de identidad, tributos, unidades, municipios, medios de pago…
(`/v1/...` está vetado para esta empresa y la v2 no expone catálogos), así que casi todo es identidad. Solo se listan
las EXCEPCIONES verificadas en la documentación (`docs/integraciones/factus.md`); las pruebas `@pytest.mark.factus`
comprueban en el sandbox que cada código que usamos es aceptado.
El único id propio de Factus es el rango de numeración (`numbering_range_id`), guardado en
`fiscal.resoluciones_numeracion.id_rango_proveedor`.
"""

from __future__ import annotations

# medio de pago DIAN que usamos -> código de Factus ("Otro" es ZZ para nosotros y ZZZ para Factus)
MEDIO_PAGO = {"ZZ": "ZZZ"}
# unidad de medida: nuestra tabla ya usa códigos UN/ECE (94, LTR, MTR, KGM, GLL)
UNIDAD: dict[str, str] = {}
# concepto de nota crédito: el nuestro (referencia.conceptos_nota) -> el de Factus. El 5 nuestro es «Otros»; en Factus
# el 5 es «descuento comercial por pronto pago»: NO hay equivalente, así que no se envía (se rechaza con un motivo claro).
CONCEPTO_NC = {"1": "1", "2": "2", "3": "3", "4": "4"}
# estándar de código de producto: 999 = estándar de adopción del contribuyente (nuestro SKU)
ESTANDAR_PRODUCTO = "999"


def medio_pago(codigo: str) -> str:
    return MEDIO_PAGO.get(codigo, codigo)


def unidad(codigo: str) -> str:
    return UNIDAD.get(codigo, codigo)
