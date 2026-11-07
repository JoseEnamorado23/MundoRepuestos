"""Importación desde Excel (openpyxl) en dos pasos: validar (no escribe datos de negocio) y confirmar (una transacción).

* Hoja `productos`: sku, nombre, categoria, marca, referencias (TIPO:FABRICANTE:REFERENCIA separadas por |),
  codigos_barras (separados por |), impuesto, precio_venta (IVA incluido), costo, stock_inicial, bodega, ubicacion,
  stock_minimo.
* Hoja `compatibilidades`: sku, marca_vehiculo, modelo, anio_desde, anio_hasta, motor.

Idempotente por SKU: reimportar actualiza, no duplica (referencias y códigos ya existentes se omiten, el precio solo se
fija si cambió y el stock inicial entra UNA sola vez por producto y bodega).

`validar` solo escribe el registro de la importación (`inventario.importaciones`: reporte y filas normalizadas);
`confirmar` aplica exactamente esas filas, volviendo a comprobar contra la BD (todo o nada).
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from openpyxl import Workbook, load_workbook
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errores import Conflicto, NoEncontrado, ReglaNegocio
from app.modules.auditoria.servicios import registrar_accion
from app.modules.catalogo import servicios as cat
from app.modules.catalogo.models import (
    Categoria,
    Impuesto,
    Marca,
    Precio,
    Producto,
    ProductoCodigoBarras,
    ProductoCompatibilidad,
    ProductoReferencia,
    VehiculoMarca,
    VehiculoModelo,
    VehiculoVersion,
)
from app.modules.catalogo.utiles import gs1_valido, normalizar_referencia, sin_acentos
from app.modules.inventario import servicios as inv
from app.modules.inventario.models import Bodega, Importacion, MovimientoInventario, Ubicacion
from app.modules.sync.servicios import publicar_evento

MAX_BYTES = 20 * 1024 * 1024
COLS_PRODUCTOS = [
    "sku", "nombre", "categoria", "marca", "referencias", "codigos_barras", "impuesto",
    "precio_venta", "costo", "stock_inicial", "bodega", "ubicacion", "stock_minimo",
]  # fmt: skip
COLS_COMPAT = ["sku", "marca_vehiculo", "modelo", "anio_desde", "anio_hasta", "motor"]
REQUERIDAS = {"productos": ["sku", "nombre"], "compatibilidades": ["sku", "marca_vehiculo", "modelo", "anio_desde"]}
TIPOS_REF = {"oem", "original", "alterna", "equivalente"}


def _k(s: str | None) -> str:
    return sin_acentos(s or "").lower().strip()


# ======================================================================================= plantilla
def limpiar(db: Session, dias: int = 7) -> int:
    """Borra las importaciones que NUNCA se confirmaron (`validada`/`descartada`) con más de `dias` días.

    Son registros LOCALES del nodo (no se sincronizan), con filas completas del Excel en `datos`: no deben acumularse.
    Las confirmadas se conservan como evidencia de lo que se cargó.
    """
    res = db.execute(
        delete(Importacion).where(
            Importacion.estado.in_(("validada", "descartada")),
            Importacion.created_at < func.now() - func.make_interval(0, 0, 0, dias),
        )
    )
    n = res.rowcount or 0
    if n:
        registrar_accion(db, "inventario.importaciones_limpiadas", despues={"eliminadas": n, "dias": dias})
    return n


def plantilla() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "productos"
    ws.append(COLS_PRODUCTOS)
    ws.append([
        "PF-0001", "Pastilla de freno delantera", "Frenos > Pastillas", "Bosch",
        "OEM:Chevrolet:96 534 653|ALTERNA:Bosch:0 986 AB1 234", "7701234567895|7701234567901", "IVA19",
        19900, 12000, 10, "B01", "A-01-02", 5,
    ])  # fmt: skip
    ws2 = wb.create_sheet("compatibilidades")
    ws2.append(COLS_COMPAT)
    ws2.append(["PF-0001", "Chevrolet", "Spark", 2016, 2020, "1.2L"])
    ws3 = wb.create_sheet("instrucciones")
    for linea in (
        "Una importación procesa UNA hoja con datos: 'productos' o 'compatibilidades'. Borre la fila de ejemplo.",
        "productos.categoria: nombre o ruta 'Padre > Hijo'. Se crea si no existe.",
        "productos.referencias: TIPO:FABRICANTE:REFERENCIA separadas por | (TIPO = oem, original, alterna, equivalente).",
        "productos.codigos_barras: separados por |. Deben ser únicos en todo el catálogo.",
        "productos.impuesto: código (IVA19, IVA5, EXENTO...) o la tarifa (19). precio_venta incluye IVA.",
        "productos.stock_inicial entra una sola vez por producto y bodega; requiere bodega (código) y usa 'costo'.",
        "Reimportar el mismo SKU actualiza el producto; no lo duplica.",
    ):
        ws3.append([linea])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ======================================================================================= lectura
def _celda(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _decimal(v: Any, campo: str, *, minimo: Decimal = Decimal(0)) -> Decimal | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float, Decimal)):
        d = Decimal(str(v))
    else:
        s = str(v).strip().replace("$", "").replace(" ", "")
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            d = Decimal(s)
        except InvalidOperation:
            raise ValueError(f"'{campo}' no es un número válido: {v!r}") from None
    if d < minimo:
        raise ValueError(f"'{campo}' no puede ser menor que {minimo}.")
    return d


def _entero(v: Any, campo: str) -> int | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return int(Decimal(str(v).strip()))
    except (InvalidOperation, ValueError):
        raise ValueError(f"'{campo}' debe ser un año numérico: {v!r}") from None


def _leer(contenido: bytes) -> tuple[str, list[tuple[int, dict[str, Any]]]]:
    if len(contenido) > MAX_BYTES:
        raise ReglaNegocio("El archivo supera 20 MB.", code="archivo_muy_grande")
    try:
        wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - openpyxl lanza varios tipos según el daño del archivo
        raise ReglaNegocio("El archivo no es un .xlsx válido.", code="archivo_invalido") from None
    hojas: dict[str, list[tuple[int, dict]]] = {}
    for nombre in ("productos", "compatibilidades"):
        if nombre not in wb.sheetnames:
            continue
        filas = wb[nombre].iter_rows(values_only=True)
        encabezado = next(filas, None)
        if not encabezado:
            continue
        cols = [_k(str(c)).replace(" ", "_") if c is not None else "" for c in encabezado]
        faltan = [c for c in REQUERIDAS[nombre] if c not in cols]
        if faltan:
            raise ReglaNegocio(
                f"A la hoja '{nombre}' le faltan columnas: {', '.join(faltan)}.", code="columnas_faltantes"
            )
        datos = []
        for n, fila in enumerate(filas, start=2):
            if fila is None or all(c is None or str(c).strip() == "" for c in fila):
                continue
            datos.append((n, dict(zip(cols, fila, strict=False))))
        if datos:
            hojas[nombre] = datos
    wb.close()
    if not hojas:
        raise ReglaNegocio("No hay filas de datos en las hojas 'productos' o 'compatibilidades'.", code="archivo_vacio")
    if len(hojas) > 1:
        raise ReglaNegocio(
            "El archivo tiene datos en ambas hojas; importe primero 'productos' y luego 'compatibilidades' "
            "(cada una en su archivo).",
            code="varias_hojas",
        )
    tipo = next(iter(hojas))
    return tipo, hojas[tipo]


# ======================================================================================= contexto de validación
@dataclass
class Ctx:
    categorias: dict[tuple[str, ...], uuid.UUID] = field(default_factory=dict)  # ruta de claves -> id
    categorias_por_nombre: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    marcas: dict[str, uuid.UUID] = field(default_factory=dict)
    impuestos_codigo: dict[str, Impuesto] = field(default_factory=dict)
    impuestos_tarifa: dict[Decimal, list[Impuesto]] = field(default_factory=dict)
    bodegas: dict[str, Bodega] = field(default_factory=dict)
    ubicaciones: dict[tuple[uuid.UUID, str], uuid.UUID] = field(default_factory=dict)
    productos: dict[str, Producto] = field(default_factory=dict)  # sku -> producto existente
    codigos: dict[str, uuid.UUID] = field(default_factory=dict)  # código -> producto_id (activos)
    precios: dict[uuid.UUID, Decimal] = field(default_factory=dict)  # producto_id -> precio vigente (lista predet.)
    con_saldo_inicial: set[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=set)
    nuevas_cat: set[tuple[str, ...]] = field(default_factory=set)
    nuevas_marcas: set[str] = field(default_factory=set)
    vmarcas: dict[str, uuid.UUID] = field(default_factory=dict)
    vmodelos: dict[tuple[uuid.UUID, str], uuid.UUID] = field(default_factory=dict)


def _cargar_contexto(db: Session, skus: list[str], codigos: list[str]) -> Ctx:
    c = Ctx()
    cats = {x.id: x for x in db.scalars(select(Categoria))}

    def ruta(x: Categoria) -> tuple[str, ...]:
        partes, cur, guard = [], x, 0
        while cur is not None and guard < 50:
            partes.append(_k(cur.nombre))
            cur = cats.get(cur.parent_id) if cur.parent_id else None
            guard += 1
        return tuple(reversed(partes))

    for x in cats.values():
        c.categorias[ruta(x)] = x.id
        c.categorias_por_nombre.setdefault(_k(x.nombre), []).append(x.id)
    c.marcas = {_k(m.nombre): m.id for m in db.scalars(select(Marca))}
    for i in db.scalars(select(Impuesto).where(Impuesto.activo.is_(True))):
        c.impuestos_codigo[_k(i.codigo)] = i
        c.impuestos_tarifa.setdefault(Decimal(i.tarifa_pct).normalize(), []).append(i)
    for b in db.scalars(select(Bodega).where(Bodega.activo.is_(True))):
        c.bodegas.setdefault(_k(b.codigo), b)
    for u in db.scalars(select(Ubicacion)):
        c.ubicaciones[(u.bodega_id, _k(u.codigo))] = u.id
    if skus:
        for p in db.scalars(select(Producto).where(Producto.sku.in_(skus))):
            c.productos[p.sku] = p
    if codigos:
        for cb in db.execute(
            select(ProductoCodigoBarras.codigo, ProductoCodigoBarras.producto_id).where(
                ProductoCodigoBarras.codigo.in_(codigos), ProductoCodigoBarras.activo.is_(True)
            )
        ):
            c.codigos[cb.codigo] = cb.producto_id
    ids = [p.id for p in c.productos.values()]
    if ids:
        lista = cat.lista_predeterminada(db)
        for pr in db.execute(
            select(Precio.producto_id, Precio.precio).where(
                Precio.producto_id.in_(ids),
                Precio.lista_precio_id == lista.id,
                Precio.sede_id.is_(None),
                Precio.vigente_hasta.is_(None),
            )
        ):
            c.precios[pr.producto_id] = pr.precio
        for m in db.execute(
            select(MovimientoInventario.producto_id, MovimientoInventario.bodega_id).where(
                MovimientoInventario.producto_id.in_(ids), MovimientoInventario.tipo == "saldo_inicial"
            )
        ):
            c.con_saldo_inicial.add((m.producto_id, m.bodega_id))
    return c


# ======================================================================================= validación de filas
def _resolver_categoria(c: Ctx, texto: str) -> tuple[uuid.UUID | None, tuple[str, ...]]:
    """(id|None si es nueva, ruta de claves). Lanza ValueError si el nombre simple es ambiguo."""
    partes = tuple(_k(p) for p in re.split(r"\s*>\s*", texto) if p.strip())
    if not partes:
        raise ValueError("La categoría está vacía.")
    if len(partes) == 1:
        ids = c.categorias_por_nombre.get(partes[0], [])
        if len(ids) > 1:
            raise ValueError(f"La categoría '{texto}' es ambigua; use la ruta 'Padre > Hijo'.")
        if ids:
            return ids[0], partes
    return c.categorias.get(partes), partes


def _parse_referencias(texto: str, c: Ctx, nuevas_marcas: set[str]) -> list[dict]:
    refs = []
    for trozo in [t for t in texto.split("|") if t.strip()]:
        partes = [p.strip() for p in trozo.split(":", 2)]
        if len(partes) != 3 or not partes[2]:
            raise ValueError(f"Referencia mal formada '{trozo}': use TIPO:FABRICANTE:REFERENCIA.")
        tipo, fab, ref = partes[0].lower(), partes[1], partes[2]
        if tipo not in TIPOS_REF:
            raise ValueError(f"Tipo de referencia '{partes[0]}' inválido (oem, original, alterna, equivalente).")
        if not normalizar_referencia(ref):
            raise ValueError(f"La referencia '{ref}' no tiene caracteres alfanuméricos.")
        if fab and _k(fab) not in c.marcas:
            nuevas_marcas.add(fab)
        refs.append({"tipo": tipo, "fabricante": fab or None, "referencia": ref})
    return refs


def _parse_codigos(texto: str) -> list[dict]:
    out, vistos = [], set()
    for cod in [t.strip() for t in texto.split("|") if t.strip()]:
        if cod in vistos:
            raise ValueError(f"Código de barras repetido en la fila: {cod}.")
        vistos.add(cod)
        if cod.isdigit() and len(cod) == 13:
            tipo = "ean13"
        elif cod.isdigit() and len(cod) == 8:
            tipo = "ean8"
        elif cod.isdigit() and len(cod) == 12:
            tipo = "upc"
        else:
            tipo = "code128"
        if tipo != "code128" and not gs1_valido(cod, {"ean13": 13, "ean8": 8, "upc": 12}[tipo]):
            raise ValueError(f"Código {cod}: dígito verificador inválido.")
        out.append({"codigo": cod, "tipo": tipo})
    return out


def _validar_productos(c: Ctx, filas: list[tuple[int, dict]]) -> tuple[list[dict], list[dict], dict]:
    reporte, datos = [], []
    vistos_sku: dict[str, int] = {}
    vistos_codigo: dict[str, str] = {}
    r = dict(productos_a_crear=0, productos_a_actualizar=0, precios_a_fijar=0, stock_inicial_a_cargar=0)
    for n, f in filas:
        sku = _celda(f.get("sku"))
        try:
            if not sku:
                raise ValueError("Falta el SKU.")
            if sku in vistos_sku:
                raise ValueError(f"SKU repetido en el archivo (también en la fila {vistos_sku[sku]}).")
            existente = c.productos.get(sku)
            nombre = _celda(f.get("nombre"))
            if not nombre:
                raise ValueError("Falta el nombre.")
            cat_txt = _celda(f.get("categoria"))
            if not cat_txt and existente is None:
                raise ValueError("Falta la categoría (obligatoria para productos nuevos).")
            fila: dict[str, Any] = {"sku": sku, "nombre": nombre, "accion": "actualizar" if existente else "crear"}
            nuevas_cat: list[tuple[str, ...]] = []
            if cat_txt:
                cid, ruta = _resolver_categoria(c, cat_txt)
                fila["categoria"] = cat_txt
                if cid is None:
                    nuevas_cat.append(ruta)
            marca = _celda(f.get("marca"))
            nuevas_m: set[str] = set()
            if marca:
                fila["marca"] = marca
                if _k(marca) not in c.marcas:
                    nuevas_m.add(marca)
            fila["referencias"] = _parse_referencias(_celda(f.get("referencias")), c, nuevas_m)
            fila["codigos"] = _parse_codigos(_celda(f.get("codigos_barras")))
            for cod in fila["codigos"]:
                dueño = c.codigos.get(cod["codigo"])
                if dueño is not None and (existente is None or dueño != existente.id):
                    raise ValueError(f"El código de barras {cod['codigo']} ya pertenece a otro producto.")
                if cod["codigo"] in vistos_codigo and vistos_codigo[cod["codigo"]] != sku:
                    raise ValueError(f"El código {cod['codigo']} ya aparece en el SKU {vistos_codigo[cod['codigo']]}.")
            imp_txt = _celda(f.get("impuesto"))
            if imp_txt:
                imp = c.impuestos_codigo.get(_k(imp_txt))
                if imp is None:
                    try:
                        tarifa = Decimal(imp_txt.replace("%", "").replace(",", ".").strip()).normalize()
                    except InvalidOperation:
                        raise ValueError(f"Impuesto '{imp_txt}' no existe.") from None
                    cand = c.impuestos_tarifa.get(tarifa, [])
                    if len(cand) != 1:
                        raise ValueError(
                            f"Impuesto '{imp_txt}' " + ("es ambiguo; use el código." if cand else "no existe.")
                        )
                    imp = cand[0]
                fila["impuesto_id"] = str(imp.id)
            elif existente is None:
                raise ValueError("Falta el impuesto (obligatorio para productos nuevos).")
            precio = _decimal(f.get("precio_venta"), "precio_venta")
            costo = _decimal(f.get("costo"), "costo")
            stock = _decimal(f.get("stock_inicial"), "stock_inicial")
            minimo = _decimal(f.get("stock_minimo"), "stock_minimo")
            if precio is not None:
                fila["precio_venta"] = str(precio)
            if costo is not None:
                fila["costo"] = str(costo)
            if minimo is not None:
                fila["stock_minimo"] = str(minimo)
            bodega_txt = _celda(f.get("bodega"))
            bodega = None
            if bodega_txt:
                bodega = c.bodegas.get(_k(bodega_txt))
                if bodega is None:
                    raise ValueError(f"La bodega '{bodega_txt}' no existe (use su código).")
                fila["bodega"] = bodega.codigo
            if stock is not None and stock > 0:
                if bodega is None:
                    raise ValueError("stock_inicial requiere la columna bodega.")
                fila["stock_inicial"] = str(stock)
            ub = _celda(f.get("ubicacion"))
            if ub:
                if bodega is None:
                    raise ValueError("ubicacion requiere la columna bodega.")
                fila["ubicacion"] = ub
            # --- resumen
            notas = []
            if existente is None:
                r["productos_a_crear"] += 1
            else:
                r["productos_a_actualizar"] += 1
            if precio is not None and c.precios.get(existente.id if existente else None) != precio:
                r["precios_a_fijar"] += 1
            if "stock_inicial" in fila:
                if existente is not None and (existente.id, bodega.id) in c.con_saldo_inicial:
                    notas.append("stock inicial ya cargado antes: se omite")
                    del fila["stock_inicial"]
                else:
                    r["stock_inicial_a_cargar"] += 1
            c.nuevas_marcas |= {_k(m) for m in nuevas_m}
            for m in nuevas_m:  # una marca nueva ya "existe" para las filas siguientes (se cuenta una sola vez)
                c.marcas.setdefault(_k(m), uuid.UUID(int=0))
            for rt in nuevas_cat:  # cada nodo faltante de la ruta cuenta una sola vez
                for i in range(1, len(rt) + 1):
                    if rt[:i] not in c.categorias:
                        c.categorias[rt[:i]] = uuid.UUID(int=0)
                        c.nuevas_cat.add(rt[:i])
            vistos_sku[sku] = n
            for cod in fila["codigos"]:
                vistos_codigo[cod["codigo"]] = sku
            datos.append({"fila": n, **fila})
            reporte.append(
                {
                    "fila": n,
                    "estado": "ok",
                    "sku": sku,
                    "detalle": fila["accion"] + (f" ({'; '.join(notas)})" if notas else ""),
                }
            )
        except (ValueError, ReglaNegocio) as e:
            reporte.append({"fila": n, "estado": "error", "sku": sku or None, "detalle": str(getattr(e, "detail", e))})
    r["categorias_nuevas"] = len(c.nuevas_cat)
    r["marcas_nuevas"] = len(c.nuevas_marcas)
    return reporte, datos, r


def _validar_compat(db: Session, c: Ctx, filas: list[tuple[int, dict]]) -> tuple[list[dict], list[dict], dict]:
    reporte, datos = [], []
    r = dict(compatibilidades=0, marcas_vehiculo_nuevas=0, modelos_nuevos=0, versiones_nuevas=0)
    nuevas_m, nuevos_mod, nuevas_v = set(), set(), set()
    for m in db.scalars(select(VehiculoMarca)):
        c.vmarcas[_k(m.nombre)] = m.id
    for m in db.scalars(select(VehiculoModelo)):
        c.vmodelos[(m.marca_id, _k(m.nombre))] = m.id
    versiones = {(v.modelo_id, v.anio_desde, v.anio_hasta, _k(v.motor)) for v in db.scalars(select(VehiculoVersion))}
    vistos: set[tuple] = set()
    for n, f in filas:
        sku = _celda(f.get("sku"))
        try:
            if sku not in c.productos:
                raise ValueError(f"El SKU {sku or '(vacío)'} no existe: importe primero los productos.")
            marca, modelo = _celda(f.get("marca_vehiculo")), _celda(f.get("modelo"))
            if not marca or not modelo:
                raise ValueError("Faltan marca_vehiculo o modelo.")
            desde = _entero(f.get("anio_desde"), "anio_desde")
            hasta = _entero(f.get("anio_hasta"), "anio_hasta")
            if desde is None or not 1950 <= desde <= 2100:
                raise ValueError("anio_desde debe estar entre 1950 y 2100.")
            if hasta is not None and (hasta < desde or hasta > 2100):
                raise ValueError("anio_hasta debe ser >= anio_desde y <= 2100.")
            motor = _celda(f.get("motor")) or None
            clave = (sku, _k(marca), _k(modelo), desde, hasta, _k(motor))
            if clave in vistos:
                raise ValueError("Fila repetida en el archivo.")
            vistos.add(clave)
            mid = c.vmarcas.get(_k(marca))
            if mid is None:
                nuevas_m.add(_k(marca))
            modid = c.vmodelos.get((mid, _k(modelo))) if mid else None
            if modid is None:
                nuevos_mod.add((_k(marca), _k(modelo)))
            if modid is None or (modid, desde, hasta, _k(motor)) not in versiones:
                nuevas_v.add((_k(marca), _k(modelo), desde, hasta, _k(motor)))
            r["compatibilidades"] += 1
            datos.append(
                {
                    "fila": n,
                    "sku": sku,
                    "marca_vehiculo": marca,
                    "modelo": modelo,
                    "anio_desde": desde,
                    "anio_hasta": hasta,
                    "motor": motor,
                }
            )
            reporte.append({"fila": n, "estado": "ok", "sku": sku, "detalle": "asignar compatibilidad"})
        except ValueError as e:
            reporte.append({"fila": n, "estado": "error", "sku": sku or None, "detalle": str(e)})
    r.update(marcas_vehiculo_nuevas=len(nuevas_m), modelos_nuevos=len(nuevos_mod), versiones_nuevas=len(nuevas_v))
    return reporte, datos, r


# ======================================================================================= API del módulo
def validar(db: Session, nombre_archivo: str, contenido: bytes, *, actor_id: uuid.UUID | None) -> Importacion:
    """Paso 1. No escribe datos de negocio; guarda el reporte y las filas normalizadas para `confirmar`."""
    tipo, filas = _leer(contenido)
    skus = list({_celda(f.get("sku")) for _, f in filas if _celda(f.get("sku"))})
    codigos = []
    if tipo == "productos":
        for _, f in filas:
            codigos += [t.strip() for t in _celda(f.get("codigos_barras")).split("|") if t.strip()]
    ctx = _cargar_contexto(db, skus, list(set(codigos)))
    if tipo == "productos":
        reporte, datos, resumen = _validar_productos(ctx, filas)
    else:
        reporte, datos, resumen = _validar_compat(db, ctx, filas)
    resumen = {"filas": len(filas), "ok": len(datos), "errores": len(filas) - len(datos), **resumen}
    imp = Importacion(
        tipo=tipo,
        estado="validada",
        nombre_archivo=nombre_archivo[:200],
        sha256=sha256(contenido).hexdigest(),
        resumen=resumen,
        reporte=reporte,
        datos=datos,
        created_by=actor_id,
    )
    db.add(imp)
    db.flush()
    return imp


def confirmar(db: Session, importacion_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> Importacion:
    """Paso 2. Aplica todo en la transacción actual (si algo falla, la dependencia de sesión revierte TODO)."""
    imp = db.scalars(select(Importacion).where(Importacion.id == importacion_id).with_for_update()).one_or_none()
    if imp is None:
        raise NoEncontrado("Importación no encontrada.")
    if imp.estado != "validada":
        raise Conflicto(f"La importación ya está '{imp.estado}'.", code="importacion_no_validada")
    if imp.resumen.get("errores"):
        raise ReglaNegocio(
            f"La validación tiene {imp.resumen['errores']} fila(s) con error: corrija el archivo y valide de nuevo.",
            code="importacion_con_errores",
        )
    if imp.tipo == "productos":
        efectos = _aplicar_productos(db, imp.datos, actor_id)
    else:
        efectos = _aplicar_compat(db, imp.datos, actor_id)
    imp.estado = "confirmada"
    imp.confirmada_at = func.now()
    db.flush()
    db.refresh(imp)
    publicar_evento(
        db,
        "importacion",
        imp.id,
        "importacion.confirmada",
        {"tipo": imp.tipo, "resumen": imp.resumen, "efectos": efectos},
    )
    registrar_accion(
        db,
        "inventario.importacion_confirmada",
        actor_id=actor_id,
        actor_tipo="empleado" if actor_id else "sistema",
        entidad_tipo="importacion",
        entidad_id=imp.id,
        despues={"tipo": imp.tipo, "archivo": imp.nombre_archivo, "sha256": imp.sha256, **efectos},
    )
    return imp


# ---------------------------------------------------------------------------------------- aplicar productos
def _categoria(db: Session, actor_id, cache: dict, texto: str) -> uuid.UUID:
    partes = [p.strip() for p in re.split(r"\s*>\s*", texto) if p.strip()]
    padre: uuid.UUID | None = None
    if len(partes) == 1:  # nombre simple: reutiliza la única existente
        hay = db.scalars(select(Categoria.id).where(func.lower(Categoria.nombre) == partes[0].lower()).limit(2)).all()
        if len(hay) == 1:
            return hay[0]
    for p in partes:
        clave = (padre, _k(p))
        if clave not in cache:
            existente = db.scalar(
                select(Categoria.id).where(
                    func.lower(Categoria.nombre) == p.lower(),
                    Categoria.parent_id.is_(None) if padre is None else Categoria.parent_id == padre,
                )
            )
            cache[clave] = existente or cat.crear_categoria(db, actor_id, nombre=p, parent_id=padre).id
        padre = cache[clave]
    return padre  # type: ignore[return-value]


def _marca(db: Session, actor_id, cache: dict, nombre: str, oem: bool = False) -> uuid.UUID:
    k = _k(nombre)
    if k not in cache:
        existente = db.scalar(select(Marca.id).where(func.lower(Marca.nombre) == nombre.strip().lower()))
        cache[k] = existente or cat.crear_marca(db, actor_id, {"nombre": nombre.strip(), "es_fabricante_oem": oem}).id
    return cache[k]


def _aplicar_productos(db: Session, filas: list[dict], actor_id) -> dict:
    cache_cat: dict = {}
    cache_marca: dict = {}
    ef = dict(creados=0, actualizados=0, precios=0, stock_inicial=0, referencias=0, codigos=0)
    for f in filas:
        p = db.scalar(select(Producto).where(Producto.sku == f["sku"]))
        campos: dict[str, Any] = {}
        if f.get("categoria"):
            campos["categoria_id"] = _categoria(db, actor_id, cache_cat, f["categoria"])
        if f.get("marca"):
            campos["marca_id"] = _marca(db, actor_id, cache_marca, f["marca"])
        if f.get("impuesto_id"):
            campos["impuesto_id"] = uuid.UUID(f["impuesto_id"])
        if f.get("stock_minimo") is not None:
            campos["stock_minimo"] = Decimal(f["stock_minimo"])
        if p is None:
            codigos = [{"codigo": c["codigo"], "tipo": c["tipo"]} for c in f["codigos"]]
            p = cat.crear_producto(
                db, actor_id, sku=f["sku"], datos={"nombre": f["nombre"], **campos}, codigos=codigos, referencias=[]
            )
            ef["creados"] += 1
            ef["codigos"] += len(codigos)
        else:
            cat.actualizar_producto(db, actor_id, p.id, {"nombre": f["nombre"], **campos})
            existentes = set(
                db.scalars(
                    select(ProductoCodigoBarras.codigo).where(
                        ProductoCodigoBarras.producto_id == p.id, ProductoCodigoBarras.activo.is_(True)
                    )
                )
            )
            for c in f["codigos"]:
                if c["codigo"] not in existentes:
                    cat.agregar_codigo_barras(db, actor_id, p.id, codigo=c["codigo"], tipo=c["tipo"])
                    ef["codigos"] += 1
            ef["actualizados"] += 1
        # referencias: se agregan solo las que faltan (clave = tipo + referencia normalizada + fabricante)
        previas = {
            (r.tipo, r.referencia_normalizada, r.marca_id)
            for r in db.scalars(
                select(ProductoReferencia).where(
                    ProductoReferencia.producto_id == p.id, ProductoReferencia.activo.is_(True)
                )
            )
        }
        for r in f["referencias"]:
            marca_id = (
                _marca(db, actor_id, cache_marca, r["fabricante"], oem=r["tipo"] == "oem") if r["fabricante"] else None
            )
            clave = (r["tipo"], normalizar_referencia(r["referencia"]), marca_id)
            if clave not in previas:
                cat.agregar_referencia(
                    db, actor_id, p.id, tipo=r["tipo"], referencia=r["referencia"], marca_id=marca_id
                )
                previas.add(clave)
                ef["referencias"] += 1
        # precio (IVA incluido, lista predeterminada, todas las sedes): solo si cambió
        if f.get("precio_venta") is not None:
            nuevo = Decimal(f["precio_venta"])
            vigente = cat.precio_vigente(db, p.id)
            if vigente is None or vigente.precio != nuevo or vigente.sede_id is not None:
                cat.fijar_precio(db, actor_id, p.id, precio=nuevo, motivo="importación Excel")
                ef["precios"] += 1
        # bodega, ubicación y stock inicial (una vez por producto y bodega)
        if f.get("bodega"):
            bodega = db.scalar(
                select(Bodega).where(func.lower(Bodega.codigo) == f["bodega"].lower(), Bodega.activo.is_(True))
            )
            if bodega is None:
                raise ReglaNegocio(f"La bodega {f['bodega']} ya no existe.", code="bodega_invalida")
            if f.get("ubicacion"):
                ub = db.scalar(
                    select(Ubicacion).where(
                        Ubicacion.bodega_id == bodega.id, func.lower(Ubicacion.codigo) == f["ubicacion"].lower()
                    )
                )
                if ub is None:
                    ub = inv.crear_ubicacion(
                        db,
                        actor_id,
                        {"bodega_id": bodega.id, "codigo": f["ubicacion"], "pasillo": f["ubicacion"].split("-")[0]},
                    )
                inv.asignar_ubicacion_producto(db, actor_id, p.id, ub.id, True)
            if f.get("stock_inicial"):
                mov = inv.stock_inicial(
                    db,
                    actor_id,
                    bodega_id=bodega.id,
                    producto_id=p.id,
                    cantidad=Decimal(f["stock_inicial"]),
                    costo=Decimal(f.get("costo") or "0"),
                )
                if mov is not None:
                    ef["stock_inicial"] += 1
    return ef


def _aplicar_compat(db: Session, filas: list[dict], actor_id) -> dict:
    ef = dict(compatibilidades=0, versiones_creadas=0)
    for f in filas:
        p = db.scalar(select(Producto).where(Producto.sku == f["sku"]))
        if p is None:
            raise ReglaNegocio(f"El SKU {f['sku']} ya no existe.", code="producto_invalido")
        vm = db.scalar(select(VehiculoMarca).where(func.lower(VehiculoMarca.nombre) == f["marca_vehiculo"].lower()))
        if vm is None:
            vm = cat.crear_vehiculo_marca(db, actor_id, {"nombre": f["marca_vehiculo"]})
        mod = db.scalar(
            select(VehiculoModelo).where(
                VehiculoModelo.marca_id == vm.id, func.lower(VehiculoModelo.nombre) == f["modelo"].lower()
            )
        )
        if mod is None:
            mod = cat.crear_vehiculo_modelo(db, actor_id, {"marca_id": vm.id, "nombre": f["modelo"]})
        motor = f.get("motor")
        q = select(VehiculoVersion).where(
            VehiculoVersion.modelo_id == mod.id, VehiculoVersion.anio_desde == f["anio_desde"]
        )
        q = q.where(
            VehiculoVersion.anio_hasta.is_(None)
            if f["anio_hasta"] is None
            else VehiculoVersion.anio_hasta == f["anio_hasta"]
        )
        q = q.where(
            VehiculoVersion.motor.is_(None) if not motor else func.lower(VehiculoVersion.motor) == motor.lower()
        )
        ver = db.scalar(q.limit(1))
        if ver is None:
            nombre = f"{f['modelo']} {f['anio_desde']}-{f['anio_hasta'] or ''}" + (f" {motor}" if motor else "")
            ver = cat.crear_vehiculo_version(
                db,
                actor_id,
                {
                    "modelo_id": mod.id,
                    "nombre": nombre.strip(),
                    "anio_desde": f["anio_desde"],
                    "anio_hasta": f["anio_hasta"],
                    "motor": motor,
                },
            )
            ef["versiones_creadas"] += 1
        ya = db.scalar(
            select(ProductoCompatibilidad.id).where(
                ProductoCompatibilidad.producto_id == p.id,
                ProductoCompatibilidad.version_id == ver.id,
                ProductoCompatibilidad.activo.is_(True),
            )
        )
        if ya is None:
            cat.asignar_compatibilidades(db, actor_id, p.id, [ver.id])
            ef["compatibilidades"] += 1
    return ef
