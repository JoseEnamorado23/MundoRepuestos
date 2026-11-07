"""Catálogo de demostración: ~300 repuestos automotrices típicos del mercado colombiano (`datos-demo --catalogo`).

IMPORTANTE (honestidad de los datos): son datos DE DEMOSTRACIÓN. Las marcas son marcas comerciales reales del mercado de
repuestos, pero las referencias se generan de forma determinista con el formato habitual de cada marca y NO están
verificadas contra los catálogos de aplicación de los fabricantes. Por eso TODAS se registran como referencia
`alterna` (nunca `oem`/`original`) y las compatibilidades son ilustrativas. No usar para decidir una compra real.

Todo se carga con los mismos servicios que la API (eventos del outbox y auditoría) y es idempotente: un SKU que ya existe
no se vuelve a tocar (ni su precio, ni su stock, ni sus compatibilidades).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalogo import servicios as svc_cat
from app.modules.catalogo.models import (
    Categoria,
    Impuesto,
    Marca,
    Producto,
    VehiculoAlias,
    VehiculoMarca,
    VehiculoModelo,
    VehiculoVersion,
)
from app.modules.inventario import servicios as svc_inv
from app.modules.inventario.models import Ubicacion


# ======================================================================================= vehículos
@dataclass(frozen=True)
class Vehiculo:
    clave: str
    marca: str
    modelo: str
    version: str
    desde: int
    hasta: int
    motor: str
    cc: int
    combustible: str = "gasolina"
    transmision: str | None = None


VEHICULOS: tuple[Vehiculo, ...] = (
    Vehiculo("spark_life", "Chevrolet", "Spark", "Spark Life 1.0", 2010, 2018, "1.0L 8V", 995),
    Vehiculo("spark_gt", "Chevrolet", "Spark", "Spark GT 1.2", 2011, 2022, "1.2L 16V", 1206),
    Vehiculo("aveo_emotion", "Chevrolet", "Aveo", "Aveo Emotion 1.6", 2008, 2017, "1.6L 16V", 1598),
    Vehiculo("aveo_family", "Chevrolet", "Aveo", "Aveo Family 1.5", 2007, 2016, "1.5L 8V", 1498),
    Vehiculo("sail", "Chevrolet", "Sail", "Sail 1.4", 2013, 2020, "1.4L 8V", 1399),
    Vehiculo("onix_14", "Chevrolet", "Onix", "Onix 1.4", 2013, 2019, "1.4L 8V", 1389),
    Vehiculo("onix_10t", "Chevrolet", "Onix", "Onix Turbo 1.0", 2020, 2024, "1.0L Turbo 12V", 999),
    Vehiculo("logan_8v", "Renault", "Logan", "Logan 1.6 8V", 2010, 2020, "1.6L 8V", 1598),
    Vehiculo("logan_16v", "Renault", "Logan", "Logan 1.6 16V", 2017, 2022, "1.6L 16V", 1598),
    Vehiculo("sandero_8v", "Renault", "Sandero", "Sandero 1.6 8V", 2009, 2020, "1.6L 8V", 1598),
    Vehiculo("sandero_16v", "Renault", "Sandero", "Sandero 1.6 16V", 2017, 2022, "1.6L 16V", 1598),
    Vehiculo("duster_16", "Renault", "Duster", "Duster 1.6 4x2", 2012, 2021, "1.6L 16V", 1598),
    Vehiculo("duster_20", "Renault", "Duster", "Duster 2.0 4x4", 2015, 2022, "2.0L 16V", 1998),
    Vehiculo("mazda2", "Mazda", "Mazda 2", "Mazda 2 1.5", 2010, 2020, "1.5L 16V", 1496),
    Vehiculo("mazda3_16", "Mazda", "Mazda 3", "Mazda 3 1.6", 2007, 2013, "1.6L 16V", 1598),
    Vehiculo("mazda3_20", "Mazda", "Mazda 3", "Mazda 3 2.0", 2010, 2018, "2.0L 16V", 1998),
    Vehiculo("picanto_10", "Kia", "Picanto", "Picanto 1.0", 2012, 2017, "1.0L 12V", 998),
    Vehiculo("picanto_12", "Kia", "Picanto", "Picanto 1.2", 2018, 2023, "1.2L 16V", 1248),
    Vehiculo("rio_14", "Kia", "Rio", "Rio 1.4", 2012, 2016, "1.4L 16V", 1396),
    Vehiculo("rio_16", "Kia", "Rio", "Rio 1.6", 2017, 2022, "1.6L 16V", 1591),
    Vehiculo("i10_11", "Hyundai", "i10", "i10 1.1", 2008, 2013, "1.1L 12V", 1086),
    Vehiculo("i10_12", "Hyundai", "i10", "Grand i10 1.2", 2014, 2022, "1.2L 16V", 1248),
    Vehiculo("accent_14", "Hyundai", "Accent", "Accent 1.4", 2008, 2011, "1.4L 16V", 1399),
    Vehiculo("accent_16", "Hyundai", "Accent", "Accent 1.6", 2012, 2022, "1.6L 16V", 1591),
    Vehiculo("corolla_a", "Toyota", "Corolla", "Corolla 1.8 (2009-2013)", 2009, 2013, "1.8L 16V", 1798),
    Vehiculo("corolla_b", "Toyota", "Corolla", "Corolla 1.8 (2014-2019)", 2014, 2019, "1.8L 16V", 1798),
    Vehiculo("hilux_27", "Toyota", "Hilux", "Hilux 2.7 gasolina", 2005, 2015, "2.7L 16V", 2693),
    Vehiculo("hilux_24d", "Toyota", "Hilux", "Hilux 2.4 diésel", 2016, 2022, "2.4L Turbo diésel", 2393, "diesel"),
    Vehiculo("march", "Nissan", "March", "March 1.6", 2012, 2022, "1.6L 16V", 1598),
    Vehiculo("versa", "Nissan", "Versa", "Versa 1.6", 2012, 2019, "1.6L 16V", 1598),
)
_VEH = {v.clave: v for v in VEHICULOS}

# Alias de búsqueda: (alias, marca, modelo|None)
ALIAS: tuple[tuple[str, str, str | None], ...] = (
    ("chevy", "Chevrolet", None),
    ("chevrolet spark gt", "Chevrolet", "Spark"),
    ("mazda3", "Mazda", "Mazda 3"),
    ("mazda2", "Mazda", "Mazda 2"),
    ("hilux vigo", "Toyota", "Hilux"),
    ("grand i10", "Hyundai", "i10"),
)

# Grupos de vehículos que comparten pieza (ilustrativo): clave -> (nombre corto, vehículos, factor de precio)
GRUPOS: dict[str, tuple[str, tuple[str, ...], float]] = {
    "a": ("Spark", ("spark_life", "spark_gt"), 1.00),
    "b": ("Aveo / Sail / Onix", ("aveo_emotion", "aveo_family", "sail", "onix_14"), 1.05),
    "c": ("Logan / Sandero / Duster 1.6", ("logan_8v", "logan_16v", "sandero_8v", "sandero_16v", "duster_16"), 1.10),
    "d": ("Duster 2.0", ("duster_20",), 1.45),
    "e": ("Mazda 2 / Mazda 3", ("mazda2", "mazda3_16", "mazda3_20"), 1.20),
    "f": ("Picanto / i10", ("picanto_10", "picanto_12", "i10_11", "i10_12"), 0.95),
    "g": ("Rio / Accent", ("rio_14", "rio_16", "accent_14", "accent_16"), 1.10),
    "h": ("Corolla", ("corolla_a", "corolla_b"), 1.35),
    "i": ("Hilux", ("hilux_27", "hilux_24d"), 1.70),
    "j": ("March / Versa", ("march", "versa"), 1.05),
    "k": ("Onix Turbo", ("onix_10t",), 1.25),
}
TODOS = tuple(GRUPOS)

# ======================================================================================= marcas y categorías
MARCAS: dict[str, str] = {  # marca -> país de origen (marcas comerciales reales del mercado de repuestos)
    "Bosch": "Alemania",
    "Mann-Filter": "Alemania",
    "Fram": "Estados Unidos",
    "Fras-le": "Brasil",
    "NGK": "Japón",
    "Gates": "Estados Unidos",
    "Dayco": "Estados Unidos",
    "Monroe": "Estados Unidos",
    "KYB": "Japón",
    "Valeo": "Francia",
    "LuK": "Alemania",
    "SKF": "Suecia",
    "NSK": "Japón",
    "TRW": "Alemania",
    "Brembo": "Italia",
    "Philips": "Países Bajos",
    "Osram": "Alemania",
    "Mobil": "Estados Unidos",
    "Castrol": "Reino Unido",
    "Shell": "Países Bajos",
    "Terpel": "Colombia",
    "Total": "Francia",
    "Valvoline": "Estados Unidos",
    "Motul": "Francia",
    "Prestone": "Estados Unidos",
    "Wynn's": "Bélgica",
    "STP": "Estados Unidos",
}

CATEGORIAS: dict[str, tuple[str, ...]] = {
    "Filtros": ("Filtros de aceite", "Filtros de aire", "Filtros de combustible", "Filtros de cabina"),
    "Frenos": ("Pastillas de freno", "Bandas y zapatas", "Discos de freno", "Líquido de frenos"),
    "Motor": ("Bujías", "Distribución y correas"),
    "Suspensión y dirección": ("Amortiguadores", "Rodamientos de rueda", "Rótulas y terminales"),
    "Transmisión": ("Kits de embrague",),
    "Lubricantes y fluidos": ("Aceites de motor", "Refrigerantes", "Aditivos y limpiadores"),
    "Iluminación": ("Bombillas",),
    "Limpiaparabrisas": ("Plumillas",),
}
PASILLO = {
    "Filtros": "A",
    "Frenos": "B",
    "Motor": "C",
    "Suspensión y dirección": "D",
    "Transmisión": "E",
    "Lubricantes y fluidos": "F",
    "Iluminación": "G",
    "Limpiaparabrisas": "H",
}


# ======================================================================================= familias de repuestos por vehículo
@dataclass(frozen=True)
class Familia:
    sku: str  # prefijo del SKU
    padre: str
    categoria: str
    nombre: str
    precio: int  # COP con IVA, grupo base (factor 1.0)
    minimo: int
    marcas: tuple[tuple[str, float, str], ...]  # (marca, factor de precio, patrón de referencia)
    grupos: tuple[str, ...] = TODOS
    posicion: str | None = None
    descripcion: str = ""


# Patrón de referencia: {a}=3 dígitos, {b}=2, {c}=4 (deterministas por marca+familia+grupo). Formato típico de la marca.
FAMILIAS: tuple[Familia, ...] = (
    Familia(
        "FAC",
        "Filtros",
        "Filtros de aceite",
        "Filtro de aceite",
        32000,
        8,
        (("Mann-Filter", 1.15, "W {a}/{b}"), ("Bosch", 1.0, "0 451 103 {a}")),
    ),
    Familia(
        "FAI",
        "Filtros",
        "Filtros de aire",
        "Filtro de aire",
        48000,
        6,
        (("Mann-Filter", 1.2, "C {a}/{b}"), ("Fram", 0.9, "CA{c}")),
    ),
    Familia(
        "FCO",
        "Filtros",
        "Filtros de combustible",
        "Filtro de combustible",
        62000,
        5,
        (("Bosch", 1.0, "0 450 905 {a}"),),
    ),
    Familia(
        "FCA",
        "Filtros",
        "Filtros de cabina",
        "Filtro de cabina (aire acondicionado)",
        52000,
        4,
        (("Mann-Filter", 1.0, "CU {a}"),),
        grupos=("a", "b", "c", "e", "f", "g", "h", "j", "k"),
    ),
    Familia(
        "PAD",
        "Frenos",
        "Pastillas de freno",
        "Pastillas de freno delanteras",
        98000,
        6,
        (("Fras-le", 0.85, "PD/{c}"), ("Bosch", 1.2, "0 986 494 {a}")),
        posicion="delantera",
    ),
    Familia(
        "PAT",
        "Frenos",
        "Pastillas de freno",
        "Pastillas de freno traseras",
        78000,
        4,
        (("Fras-le", 0.85, "PD/{c}"),),
        grupos=("c", "d", "e", "g", "h", "j", "k", "i"),
        posicion="trasera",
    ),
    Familia(
        "BAN",
        "Frenos",
        "Bandas y zapatas",
        "Bandas (zapatas) de freno traseras",
        105000,
        4,
        (("Fras-le", 0.9, "BF/{c}"),),
        grupos=("a", "b", "c", "f", "g", "j", "i", "e"),
        posicion="trasera",
    ),
    Familia(
        "DIS",
        "Frenos",
        "Discos de freno",
        "Discos de freno delanteros (par)",
        280000,
        3,
        (("Brembo", 1.3, "09.{a}.{b}"),),
        grupos=("b", "c", "d", "e", "g", "h", "j", "k", "i"),
        posicion="delantera",
    ),
    Familia(
        "BUJ",
        "Motor",
        "Bujías",
        "Bujías (juego x4)",
        72000,
        6,
        (("NGK", 1.0, "{a}-{b}"), ("Bosch", 0.85, "0 242 {a} {b}")),
    ),
    Familia(
        "KDI",
        "Motor",
        "Distribución y correas",
        "Kit de distribución (correa + tensor + rodillo)",
        340000,
        3,
        (("Gates", 1.1, "K015{a}XS"), ("Dayco", 0.95, "KTB{a}")),
        grupos=("a", "b", "c", "d", "e", "f", "g", "h", "j", "k"),
    ),
    Familia(
        "COR",
        "Motor",
        "Distribución y correas",
        "Correa de accesorios (poly-V)",
        78000,
        5,
        (("Gates", 1.1, "6PK{c}"), ("Dayco", 0.95, "6PK{c}")),
    ),
    Familia(
        "AMD",
        "Suspensión y dirección",
        "Amortiguadores",
        "Amortiguador delantero",
        210000,
        4,
        (("Monroe", 1.1, "G{c}"), ("KYB", 1.0, "33{c}")),
        posicion="delantera",
    ),
    Familia(
        "AMT",
        "Suspensión y dirección",
        "Amortiguadores",
        "Amortiguador trasero",
        170000,
        4,
        (("Monroe", 1.0, "G{c}"),),
        posicion="trasera",
    ),
    Familia(
        "EMB",
        "Transmisión",
        "Kits de embrague",
        "Kit de embrague (disco + plato + balinera)",
        640000,
        2,
        (("Valeo", 1.1, "826{a}"), ("LuK", 1.25, "62{c}")),
        grupos=("a", "b", "c", "e", "f", "g", "h", "i", "j"),
    ),
    Familia(
        "ROD",
        "Suspensión y dirección",
        "Rodamientos de rueda",
        "Rodamiento de rueda delantero",
        115000,
        4,
        (("SKF", 1.2, "VKBA {c}"), ("NSK", 1.0, "{a}BWD{b}")),
        grupos=("a", "b", "c", "e", "f", "g", "h", "i", "j", "k"),
        posicion="delantera",
    ),
    Familia(
        "ROT",
        "Suspensión y dirección",
        "Rótulas y terminales",
        "Rótula de suspensión inferior",
        82000,
        4,
        (("TRW", 1.0, "JBJ{a}"),),
        grupos=("a", "b", "c", "e", "f", "g", "h", "j", "k", "i"),
        posicion="inferior",
    ),
    Familia(
        "TER",
        "Suspensión y dirección",
        "Rótulas y terminales",
        "Terminal de dirección",
        64000,
        4,
        (("TRW", 1.0, "JTE{a}"),),
        grupos=("a", "b", "c", "e", "f", "g", "h", "j", "k", "i"),
    ),
)


# ======================================================================================= productos universales
@dataclass(frozen=True)
class Universal:
    sku: str
    padre: str
    categoria: str
    nombre: str
    marca: str
    referencia: str
    precio: int
    minimo: int
    unidad: str = "94"
    descripcion: str = ""


def _bombillas() -> list[Universal]:
    tipos = (
        ("H1", 24000), ("H3", 22000), ("H4", 28000), ("H7", 30000), ("H11", 32000), ("HB3 9005", 36000),
        ("HB4 9006", 36000), ("W5W", 6000), ("P21W", 7000), ("P21/5W", 8000), ("T10", 5000), ("R5W", 6500),
    )  # fmt: skip
    out = []
    for marca, f, pref in (("Philips", 1.15, "PH"), ("Osram", 1.0, "OS")):
        for tipo, p in tipos:
            ref = f"{pref} {tipo.replace(' ', '-')} 12V"
            out.append(
                Universal(
                    f"BOM-{pref}-{tipo.replace(' ', '').replace('/', '')}", "Iluminación", "Bombillas",
                    f"Bombilla {tipo} 12V", marca, ref, int(round(p * f, -2)), 10,
                )
            )  # fmt: skip
    return out


def _plumillas() -> list[Universal]:
    out = []
    for marca, f, pref in (("Bosch", 1.2, "AEROTWIN"), ("Valeo", 1.0, "SILENCIO")):
        for pulg, p in ((14, 22000), (16, 24000), (18, 26000), (20, 28000), (22, 31000), (24, 34000), (26, 38000)):
            out.append(
                Universal(
                    f"PLU-{pref[:3]}-{pulg}", "Limpiaparabrisas", "Plumillas", f'Plumilla {pulg}" ({pref.title()})',
                    marca, f"{pref} {pulg}", int(round(p * f, -2)), 8,
                )
            )  # fmt: skip
    return out


def _fluidos() -> list[Universal]:
    aceites = (
        ("Mobil", "Super 2000 10W-40 semisintético", "M2000-10W40", 38000, 118000),
        ("Mobil", "Super 1000 20W-50 mineral", "M1000-20W50", 29000, 92000),
        ("Mobil", "1 Advanced 5W-30 sintético", "M1-5W30", 62000, 215000),
        ("Castrol", "GTX 20W-50 mineral", "GTX-20W50", 30000, 96000),
        ("Castrol", "Magnatec 5W-30 sintético", "MAG-5W30", 58000, 198000),
        ("Castrol", "Edge 5W-40 sintético", "EDGE-5W40", 69000, 240000),
        ("Shell", "Helix HX7 10W-40 semisintético", "HX7-10W40", 39000, 122000),
        ("Shell", "Helix Ultra 5W-40 sintético", "HU-5W40", 66000, 228000),
        ("Terpel", "Celerity 20W-50 mineral", "CEL-20W50", 24000, 78000),
        ("Terpel", "Celerity Diésel 15W-40", "CELD-15W40", 31000, 102000),
        ("Total", "Quartz 7000 10W-40 semisintético", "Q7000-10W40", 40000, 126000),
        ("Valvoline", "MaxLife 10W-40", "MXL-10W40", 41000, 130000),
        ("Motul", "6100 Synergie+ 10W-40", "M6100-10W40", 52000, 178000),
    )
    out = []
    for marca, nombre, ref, litro, galon in aceites:
        s = ref.replace("-", "")
        out.append(
            Universal(
                f"ACE-{marca[:3].upper()}-{s}-L", "Lubricantes y fluidos", "Aceites de motor",
                f"Aceite {marca} {nombre} (1 litro)", marca, ref, litro, 24, "LTR",
            )
        )  # fmt: skip
        out.append(
            Universal(
                f"ACE-{marca[:3].upper()}-{s}-G", "Lubricantes y fluidos", "Aceites de motor",
                f"Aceite {marca} {nombre} (galón)", marca, ref, galon, 12, "GLL",
            )
        )  # fmt: skip
    resto = (
        ("Prestone", "Refrigerante 50/50 rosado (galón)", "PR-5050R", 38000, "Refrigerantes", "GLL", "REF"),
        ("Prestone", "Refrigerante concentrado verde (galón)", "PR-CONV", 46000, "Refrigerantes", "GLL", "REF"),
        ("Terpel", "Refrigerante 50/50 (galón)", "TP-5050", 32000, "Refrigerantes", "GLL", "REF"),
        ("Bosch", "Líquido de frenos DOT 4 (500 ml)", "BO-DOT4-500", 24000, "Líquido de frenos", "94", "LFR"),
        ("Motul", "Líquido de frenos DOT 4 (500 ml)", "MO-DOT4-500", 36000, "Líquido de frenos", "94", "LFR"),
        ("Castrol", "Líquido de frenos DOT 4 (500 ml)", "CA-DOT4-500", 29000, "Líquido de frenos", "94", "LFR"),
        ("Wynn's", "Limpiador de inyectores gasolina (325 ml)", "WY-INY-325", 42000, "Aditivos y limpiadores", "94", "ADI"),
        ("Wynn's", "Tratamiento de aceite motor (325 ml)", "WY-ACE-325", 39000, "Aditivos y limpiadores", "94", "ADI"),
        ("STP", "Limpiador de carburador y cuerpo de aceleración", "STP-CARB", 22000, "Aditivos y limpiadores", "94", "ADI"),
        ("STP", "Sellador de radiador", "STP-RAD", 18000, "Aditivos y limpiadores", "94", "ADI"),
        ("Bosch", "Limpiador de frenos en aerosol (500 ml)", "BO-LF-500", 21000, "Aditivos y limpiadores", "94", "ADI"),
    )  # fmt: skip
    for marca, nombre, ref, precio, cat, un, pref in resto:
        out.append(
            Universal(
                f"{pref}-{marca[:3].upper()}-{ref.replace('-', '')}", "Lubricantes y fluidos", cat,
                f"{nombre.split(' (')[0]} {marca} ({nombre.split('(')[1]}" if "(" in nombre else f"{nombre} {marca}",
                marca, ref, precio, 12, un,
            )
        )  # fmt: skip
    return out


# ======================================================================================= generación determinista
def _h(*partes: object) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, partes)).encode()).digest()[:8], "big")


def _referencia(patron: str, *semilla: object) -> str:
    n = _h(*semilla)
    return patron.format(a=100 + n % 900, b=10 + (n >> 12) % 90, c=1000 + (n >> 24) % 9000)


def _precio(base: float) -> int:
    """Redondea a la centena (<100 mil) o al millar (>=100 mil): precios de mostrador creíbles."""
    return int(round(base, -3)) if base >= 100_000 else int(round(base, -2))


@dataclass
class ProductoDemo:
    sku: str
    padre: str
    categoria: str
    nombre: str
    marca: str
    referencia: str
    precio: int  # COP con IVA
    minimo: int
    unidad: str = "94"
    versiones: tuple[str, ...] = ()  # claves de VEHICULOS
    posicion: str | None = None
    ubicacion: tuple[str, str, str] | None = None  # pasillo, estante, nivel
    descripcion: str = ""
    nota: str = field(default="", repr=False)


def generar() -> list[ProductoDemo]:
    """Lista determinista de productos del catálogo demo (sin tocar la BD)."""
    out: list[ProductoDemo] = []
    vistos: set[str] = set()
    for fam in FAMILIAS:
        for gi, g in enumerate(fam.grupos):
            nombre_g, vehs, fg = GRUPOS[g]
            for marca, fm, patron in fam.marcas:
                ref = _referencia(patron, fam.sku, marca, g)
                sku = f"{fam.sku}-{marca[:3].upper()}-{''.join(ch for ch in ref if ch.isalnum()).upper()}"
                if sku in vistos:
                    sku = f"{sku}-{g.upper()}"
                vistos.add(sku)
                out.append(
                    ProductoDemo(
                        sku=sku,
                        padre=fam.padre,
                        categoria=fam.categoria,
                        nombre=f"{fam.nombre} {marca} {ref} — {nombre_g}",
                        marca=marca,
                        referencia=ref,
                        precio=_precio(fam.precio * fg * fm),
                        minimo=fam.minimo,
                        versiones=vehs,
                        posicion=fam.posicion,
                        ubicacion=(PASILLO[fam.padre], f"{(gi % 6) + 1:02d}", str(_h(sku) % 3 + 1)),
                        descripcion=f"Compatible (referencia alterna, ilustrativa) con: "
                        f"{', '.join(_VEH[v].version for v in vehs)}.",
                    )
                )
    for u in (*_bombillas(), *_plumillas(), *_fluidos()):
        out.append(
            ProductoDemo(
                sku=u.sku, padre=u.padre, categoria=u.categoria, nombre=u.nombre, marca=u.marca,
                referencia=u.referencia, precio=u.precio, minimo=u.minimo, unidad=u.unidad,
                ubicacion=(PASILLO[u.padre], f"{_h(u.sku) % 6 + 1:02d}", str(_h(u.sku, 1) % 3 + 1)),
                descripcion="Producto de uso universal.",
            )
        )  # fmt: skip
    skus = [p.sku for p in out]
    assert len(skus) == len(set(skus)), "SKU duplicado en el catálogo demo"
    return out


def stock_demo(p: ProductoDemo) -> Decimal:
    """Existencia inicial variada y determinista: ~10 % en cero, ~18 % bajo el mínimo, el resto holgado."""
    r = _h(p.sku, "stock") % 100
    if r < 10:
        return Decimal(0)
    if r < 28:
        return Decimal(max(1, p.minimo - 1 - (r % max(1, p.minimo - 1))))
    return Decimal(p.minimo + 2 + (r % (p.minimo * 3)))


def costo_demo(p: ProductoDemo) -> Decimal:
    """Costo unitario (sin IVA) = precio neto × margen entre 62 % y 76 %."""
    neto = Decimal(p.precio) / Decimal("1.19")
    margen = Decimal(62 + _h(p.sku, "costo") % 15) / 100
    return (neto * margen).quantize(Decimal("0.0001"))


# ======================================================================================= carga en BD
@dataclass
class ResumenCatalogo:
    productos_nuevos: int = 0
    productos_existentes: int = 0
    con_stock: int = 0
    sin_stock: int = 0
    bajo_minimo: int = 0
    versiones: int = 0


def _categorias(db: Session, actor_id: uuid.UUID) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for orden, (padre, hijas) in enumerate(CATEGORIAS.items()):
        p = db.scalar(select(Categoria).where(Categoria.nombre == padre, Categoria.parent_id.is_(None)))
        if p is None:
            p = svc_cat.crear_categoria(db, actor_id, nombre=padre, orden=orden)
        ids[padre] = p.id
        for o, h in enumerate(hijas):
            c = db.scalar(select(Categoria).where(Categoria.nombre == h, Categoria.parent_id == p.id))
            if c is None:
                c = svc_cat.crear_categoria(db, actor_id, nombre=h, parent_id=p.id, orden=o)
            ids[h] = c.id
    return ids


def _marcas(db: Session, actor_id: uuid.UUID) -> dict[str, uuid.UUID]:
    ids = {}
    for nombre, pais in MARCAS.items():
        m = db.scalar(select(Marca).where(Marca.nombre == nombre))
        if m is None:
            m = svc_cat.crear_marca(db, actor_id, {"nombre": nombre, "pais_origen": pais, "es_fabricante_oem": False})
        ids[nombre] = m.id
    return ids


def _vehiculos(db: Session, actor_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """clave -> version_id (crea marcas, modelos y versiones que falten) y los alias de búsqueda."""
    marcas: dict[str, uuid.UUID] = {}
    modelos: dict[tuple[str, str], uuid.UUID] = {}
    versiones: dict[str, uuid.UUID] = {}
    for v in VEHICULOS:
        if v.marca not in marcas:
            m = db.scalar(select(VehiculoMarca).where(VehiculoMarca.nombre == v.marca))
            marcas[v.marca] = (m or svc_cat.crear_vehiculo_marca(db, actor_id, {"nombre": v.marca})).id
        if (v.marca, v.modelo) not in modelos:
            mo = db.scalar(
                select(VehiculoModelo).where(
                    VehiculoModelo.marca_id == marcas[v.marca], VehiculoModelo.nombre == v.modelo
                )
            )
            if mo is None:
                mo = svc_cat.crear_vehiculo_modelo(db, actor_id, {"marca_id": marcas[v.marca], "nombre": v.modelo})
            modelos[(v.marca, v.modelo)] = mo.id
        mid = modelos[(v.marca, v.modelo)]
        ver = db.scalar(
            select(VehiculoVersion).where(VehiculoVersion.modelo_id == mid, VehiculoVersion.nombre == v.version)
        )
        if ver is None:
            ver = svc_cat.crear_vehiculo_version(
                db,
                actor_id,
                dict(
                    modelo_id=mid,
                    nombre=v.version,
                    anio_desde=v.desde,
                    anio_hasta=v.hasta,
                    motor=v.motor,
                    cilindraje_cc=v.cc,
                    combustible=v.combustible,
                    transmision=v.transmision,
                ),
            )
        versiones[v.clave] = ver.id
    for alias, marca, modelo in ALIAS:
        mid = modelos.get((marca, modelo)) if modelo else None
        marca_id = None if modelo else marcas[marca]
        norm = svc_cat.normalizar_alias(alias)
        existe = db.scalar(
            select(VehiculoAlias.id).where(
                VehiculoAlias.alias_normalizado == norm,
                VehiculoAlias.marca_id.is_(None) if marca_id is None else VehiculoAlias.marca_id == marca_id,
                VehiculoAlias.modelo_id.is_(None) if mid is None else VehiculoAlias.modelo_id == mid,
            )
        )
        if existe is None:
            svc_cat.crear_alias_vehiculo(db, actor_id, {"alias": alias, "marca_id": marca_id, "modelo_id": mid})
    return versiones


def _ubicacion(db: Session, actor_id: uuid.UUID, bodega_id: uuid.UUID, ub: tuple[str, str, str]) -> Ubicacion:
    pasillo, estante, nivel = ub
    codigo = f"{pasillo}-{estante}-{nivel}"
    u = db.scalar(select(Ubicacion).where(Ubicacion.bodega_id == bodega_id, Ubicacion.codigo == codigo))
    if u is None:
        u = svc_inv.crear_ubicacion(
            db, actor_id, dict(bodega_id=bodega_id, codigo=codigo, pasillo=pasillo, estante=estante, nivel=nivel)
        )
    return u


def sembrar_catalogo(db: Session, actor_id: uuid.UUID, bodega_id: uuid.UUID) -> ResumenCatalogo:
    """Carga (idempotente) marcas, categorías, vehículos, productos, precios, compatibilidades, stock y ubicaciones."""
    res = ResumenCatalogo()
    iva = db.scalar(select(Impuesto).where(Impuesto.codigo == "IVA19"))
    cats, marcas, versiones = _categorias(db, actor_id), _marcas(db, actor_id), _vehiculos(db, actor_id)
    res.versiones = len(versiones)
    existentes = set(db.scalars(select(Producto.sku)))
    nuevos: list[uuid.UUID] = []
    for p in generar():
        if p.sku in existentes:
            res.productos_existentes += 1
            continue
        prod = svc_cat.crear_producto(
            db,
            actor_id,
            sku=p.sku,
            datos=dict(
                nombre=p.nombre,
                descripcion=p.descripcion,
                marca_id=marcas[p.marca],
                categoria_id=cats[p.categoria],
                unidad_codigo=p.unidad,
                impuesto_id=iva.id,
                stock_minimo=Decimal(p.minimo),
            ),
            codigos=[],
            referencias=[dict(tipo="alterna", referencia=p.referencia, marca_id=marcas[p.marca])],
        )
        nuevos.append(prod.id)
        svc_cat.fijar_precio(db, actor_id, prod.id, precio=Decimal(p.precio), motivo="Precio inicial (demo)")
        if p.versiones:
            svc_cat.asignar_compatibilidades(
                db, actor_id, prod.id, [versiones[v] for v in p.versiones], posicion=p.posicion
            )
        ub = _ubicacion(db, actor_id, bodega_id, p.ubicacion)
        svc_inv.asignar_ubicacion_producto(db, actor_id, prod.id, ub.id, True)
        cantidad = stock_demo(p)
        if cantidad > 0:
            svc_inv.stock_inicial(
                db, actor_id, bodega_id=bodega_id, producto_id=prod.id, cantidad=cantidad, costo=costo_demo(p)
            )
            res.con_stock += 1
            res.bajo_minimo += int(cantidad < p.minimo)
        else:
            res.sin_stock += 1
        res.productos_nuevos += 1
    if nuevos:
        svc_cat.generar_codigos_internos(db, actor_id, producto_ids=nuevos, limite=len(nuevos))  # EAN-13 internos
    return res
