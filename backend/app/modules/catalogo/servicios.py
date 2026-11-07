"""Servicios del catálogo: maestros, productos, códigos de barras, compatibilidades y precios.

Sin commit (lo hace la dependencia de sesión). Toda escritura publica su evento en el outbox (misma transacción) y las
acciones sensibles (precios, activación, generación de códigos) se auditan.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import NODO_NUBE_ID, get_settings
from app.core.errores import Conflicto, NoEncontrado, ReglaNegocio
from app.modules.auditoria.servicios import registrar_accion
from app.modules.catalogo.models import (
    Categoria,
    ContadorEan,
    Impuesto,
    ListaPrecio,
    Marca,
    Precio,
    Producto,
    ProductoCodigoBarras,
    ProductoCompatibilidad,
    ProductoReferencia,
    VehiculoAlias,
    VehiculoMarca,
    VehiculoModelo,
    VehiculoVersion,
)
from app.modules.catalogo.utiles import CONSECUTIVO_EAN_MAX, ean13_interno, gs1_valido, sin_acentos, slugify, snapshot
from app.modules.organizacion.models import Nodo
from app.modules.sync.servicios import publicar_evento


def _evento(db: Session, agregado: str, obj, tipo: str) -> None:
    publicar_evento(db, agregado, obj.id, f"{agregado}.{tipo}", snapshot(obj), version=getattr(obj, "version", 1))


def _obtener(db: Session, modelo, id_: uuid.UUID, nombre: str):
    obj = db.get(modelo, id_)
    if obj is None:
        raise NoEncontrado(f"{nombre} no encontrado.")
    return obj


def _slug_unico(db: Session, modelo, base: str, excluir: uuid.UUID | None = None) -> str:
    slug, n = slugify(base), 1
    while db.scalar(select(modelo.id).where(modelo.slug == slug, modelo.id != (excluir or uuid.UUID(int=0)))):
        n += 1
        slug = f"{slugify(base)}-{n}"
    return slug


def _aplicar(obj, datos: dict[str, Any], permitidos: set[str]) -> None:
    for k, v in datos.items():
        if k in permitidos:
            setattr(obj, k, v)


# ======================================================================================= categorías
def _descendientes(db: Session, categoria_id: uuid.UUID) -> set[uuid.UUID]:
    filas = db.execute(
        text(
            "WITH RECURSIVE d AS (SELECT id FROM catalogo.categorias WHERE parent_id = :i "
            "UNION SELECT c.id FROM catalogo.categorias c JOIN d ON c.parent_id = d.id) SELECT id FROM d"
        ),
        {"i": categoria_id},
    )
    return {r[0] for r in filas}


def ids_categoria_y_descendientes(db: Session, categoria_id: uuid.UUID) -> list[uuid.UUID]:
    return [categoria_id, *_descendientes(db, categoria_id)]


def _validar_padre(db: Session, categoria_id: uuid.UUID | None, parent_id: uuid.UUID | None) -> None:
    if parent_id is None:
        return
    if db.get(Categoria, parent_id) is None:
        raise ReglaNegocio("La categoría padre no existe.", code="categoria_padre_invalida")
    if categoria_id is not None and (parent_id == categoria_id or parent_id in _descendientes(db, categoria_id)):
        raise ReglaNegocio(
            "La categoría no puede ser hija de sí misma ni de sus descendientes.", code="categoria_ciclo"
        )


def crear_categoria(db: Session, actor_id: uuid.UUID, *, nombre: str, parent_id=None, orden: int = 0) -> Categoria:
    _validar_padre(db, None, parent_id)
    c = Categoria(
        nombre=nombre.strip(),
        parent_id=parent_id,
        orden=orden,
        slug=_slug_unico(db, Categoria, nombre),
        created_by=actor_id,
    )
    db.add(c)
    db.flush()
    _evento(db, "categoria", c, "creada")
    return c


def actualizar_categoria(db: Session, actor_id: uuid.UUID, categoria_id: uuid.UUID, datos: dict) -> Categoria:
    c = _obtener(db, Categoria, categoria_id, "Categoría")
    if "parent_id" in datos:
        _validar_padre(db, c.id, datos["parent_id"])
    if "nombre" in datos and datos["nombre"] != c.nombre:
        c.slug = _slug_unico(db, Categoria, datos["nombre"], c.id)
    _aplicar(c, datos, {"nombre", "parent_id", "orden", "activo"})
    db.flush()
    _evento(db, "categoria", c, "actualizada")
    return c


def arbol_categorias(db: Session, solo_activas: bool = True) -> list[dict]:
    stmt = select(Categoria).order_by(Categoria.orden, Categoria.nombre)
    if solo_activas:
        stmt = stmt.where(Categoria.activo.is_(True))
    filas = list(db.scalars(stmt))
    nodos = {
        c.id: {"id": c.id, "nombre": c.nombre, "slug": c.slug, "orden": c.orden, "activo": c.activo, "hijos": []}
        for c in filas
    }
    raiz: list[dict] = []
    for c in filas:
        destino = nodos.get(c.parent_id) if c.parent_id else None
        (destino["hijos"] if destino else raiz).append(nodos[c.id])
    return raiz


# ======================================================================================= marcas
def crear_marca(db: Session, actor_id: uuid.UUID, datos: dict) -> Marca:
    m = Marca(
        slug=_slug_unico(db, Marca, datos["nombre"]),
        created_by=actor_id,
        **{k: v for k, v in datos.items() if k in {"nombre", "es_fabricante_oem", "pais_origen", "logo_url"}},
    )
    db.add(m)
    db.flush()  # uq_marcas_nombre -> 409
    _evento(db, "marca", m, "creada")
    return m


def actualizar_marca(db: Session, actor_id: uuid.UUID, marca_id: uuid.UUID, datos: dict) -> Marca:
    m = _obtener(db, Marca, marca_id, "Marca")
    if "nombre" in datos and datos["nombre"] != m.nombre:
        m.slug = _slug_unico(db, Marca, datos["nombre"], m.id)
    _aplicar(m, datos, {"nombre", "es_fabricante_oem", "pais_origen", "logo_url", "activo"})
    db.flush()
    _evento(db, "marca", m, "actualizada")
    return m


# ======================================================================================= vehículos
def crear_vehiculo_marca(db: Session, actor_id: uuid.UUID, datos: dict) -> VehiculoMarca:
    m = VehiculoMarca(
        nombre=datos["nombre"].strip(),
        slug=_slug_unico(db, VehiculoMarca, datos["nombre"]),
        codigo_externo=datos.get("codigo_externo"),
        created_by=actor_id,
    )
    db.add(m)
    db.flush()
    _evento(db, "vehiculo_marca", m, "creada")
    return m


def actualizar_vehiculo_marca(db: Session, actor_id: uuid.UUID, id_: uuid.UUID, datos: dict) -> VehiculoMarca:
    m = _obtener(db, VehiculoMarca, id_, "Marca de vehículo")
    if "nombre" in datos and datos["nombre"] != m.nombre:
        m.slug = _slug_unico(db, VehiculoMarca, datos["nombre"], m.id)
    _aplicar(m, datos, {"nombre", "codigo_externo", "activo"})
    db.flush()
    _evento(db, "vehiculo_marca", m, "actualizada")
    return m


def normalizar_alias(texto: str) -> str:
    """Minúsculas, sin tildes y palabras separadas por un espacio (como se compara en la búsqueda)."""
    return " ".join(re.findall(r"[a-z0-9]+", sin_acentos(texto).lower()))


def crear_alias_vehiculo(db: Session, actor_id: uuid.UUID, datos: dict) -> VehiculoAlias:
    norm = normalizar_alias(datos["alias"])
    if len(norm) < 2:
        raise ReglaNegocio("El alias debe tener letras o números.", code="alias_invalido")
    if datos.get("marca_id"):
        _obtener(db, VehiculoMarca, datos["marca_id"], "Marca de vehículo")
    if datos.get("modelo_id"):
        _obtener(db, VehiculoModelo, datos["modelo_id"], "Modelo de vehículo")
    a = VehiculoAlias(
        alias=datos["alias"].strip(),
        alias_normalizado=norm,
        marca_id=datos.get("marca_id"),
        modelo_id=datos.get("modelo_id"),
        created_by=actor_id,
    )
    db.add(a)
    db.flush()
    _evento(db, "vehiculo_alias", a, "creado")
    return a


def actualizar_alias_vehiculo(db: Session, actor_id: uuid.UUID, id_: uuid.UUID, datos: dict) -> VehiculoAlias:
    a = _obtener(db, VehiculoAlias, id_, "Alias de vehículo")
    if datos.get("alias") is not None:
        norm = normalizar_alias(datos["alias"])
        if len(norm) < 2:
            raise ReglaNegocio("El alias debe tener letras o números.", code="alias_invalido")
        a.alias, a.alias_normalizado = datos["alias"].strip(), norm
    if datos.get("activo") is not None:
        a.activo = datos["activo"]
    db.flush()
    _evento(db, "vehiculo_alias", a, "actualizado")
    return a


def anios_de_modelo(db: Session, modelo_id: uuid.UUID) -> list[int]:
    """Años (descendente) en que existe alguna versión activa del modelo; sin `anio_hasta` = hasta el año siguiente."""
    _obtener(db, VehiculoModelo, modelo_id, "Modelo de vehículo")
    filas = db.execute(
        text(
            "SELECT DISTINCT y FROM catalogo.vehiculos_versiones v, "
            "LATERAL generate_series(v.anio_desde, COALESCE(v.anio_hasta, CAST(extract(year FROM current_date) AS int) + 1)) y "
            "WHERE v.modelo_id = :m AND v.activo ORDER BY y DESC"
        ),
        {"m": modelo_id},
    )
    return [r[0] for r in filas]


def crear_vehiculo_modelo(db: Session, actor_id: uuid.UUID, datos: dict) -> VehiculoModelo:
    _obtener(db, VehiculoMarca, datos["marca_id"], "Marca de vehículo")
    base = datos["nombre"]
    slug, n = slugify(base), 1
    while db.scalar(
        select(VehiculoModelo.id).where(VehiculoModelo.marca_id == datos["marca_id"], VehiculoModelo.slug == slug)
    ):
        n += 1
        slug = f"{slugify(base)}-{n}"
    m = VehiculoModelo(
        marca_id=datos["marca_id"],
        nombre=base.strip(),
        slug=slug,
        codigo_externo=datos.get("codigo_externo"),
        created_by=actor_id,
    )
    db.add(m)
    db.flush()
    _evento(db, "vehiculo_modelo", m, "creado")
    return m


def actualizar_vehiculo_modelo(db: Session, actor_id: uuid.UUID, id_: uuid.UUID, datos: dict) -> VehiculoModelo:
    m = _obtener(db, VehiculoModelo, id_, "Modelo de vehículo")
    _aplicar(m, datos, {"nombre", "codigo_externo", "activo"})
    db.flush()
    _evento(db, "vehiculo_modelo", m, "actualizado")
    return m


_CAMPOS_VERSION = {
    "nombre",
    "anio_desde",
    "anio_hasta",
    "motor",
    "cilindraje_cc",
    "combustible",
    "transmision",
    "codigo_externo",
}


def crear_vehiculo_version(db: Session, actor_id: uuid.UUID, datos: dict) -> VehiculoVersion:
    _obtener(db, VehiculoModelo, datos["modelo_id"], "Modelo de vehículo")
    v = VehiculoVersion(modelo_id=datos["modelo_id"], created_by=actor_id, **{k: datos.get(k) for k in _CAMPOS_VERSION})
    db.add(v)
    db.flush()
    db.refresh(v)  # `anios` es columna generada
    _evento(db, "vehiculo_version", v, "creada")
    return v


def actualizar_vehiculo_version(db: Session, actor_id: uuid.UUID, id_: uuid.UUID, datos: dict) -> VehiculoVersion:
    v = _obtener(db, VehiculoVersion, id_, "Versión de vehículo")
    _aplicar(v, datos, _CAMPOS_VERSION | {"activo"})
    db.flush()
    db.refresh(v)
    _evento(db, "vehiculo_version", v, "actualizada")
    return v


# ======================================================================================= productos
_CAMPOS_PRODUCTO = {
    "nombre",
    "descripcion",
    "marca_id",
    "categoria_id",
    "unidad_codigo",
    "impuesto_id",
    "es_inventariable",
    "vendible_pos",
    "publicado_web",
    "slug",
    "peso_kg",
    "alto_cm",
    "ancho_cm",
    "largo_cm",
    "stock_minimo",
    "stock_seguridad_web",
}


def _validar_fks_producto(db: Session, datos: dict) -> None:
    if datos.get("categoria_id") is not None and db.get(Categoria, datos["categoria_id"]) is None:
        raise ReglaNegocio("La categoría no existe.", code="categoria_invalida")
    if datos.get("marca_id") is not None and db.get(Marca, datos["marca_id"]) is None:
        raise ReglaNegocio("La marca no existe.", code="marca_invalida")
    if datos.get("impuesto_id") is not None and db.get(Impuesto, datos["impuesto_id"]) is None:
        raise ReglaNegocio("El impuesto no existe.", code="impuesto_invalido")


def validar_codigo_barras(codigo: str, tipo: str) -> str:
    codigo = codigo.strip()
    if not codigo or len(codigo) > 48:
        raise ReglaNegocio("El código de barras debe tener entre 1 y 48 caracteres.", code="codigo_invalido")
    esperado = {"ean13": 13, "ean8": 8, "upc": 12}.get(tipo)
    if esperado and not gs1_valido(codigo, esperado):
        raise ReglaNegocio(
            f"Código {tipo.upper()} inválido (se esperan {esperado} dígitos con dígito verificador correcto).",
            code="codigo_invalido",
        )
    return codigo


def _verificar_codigo_libre(db: Session, codigo: str, excepto_producto: uuid.UUID | None = None) -> None:
    otro = db.scalar(
        select(ProductoCodigoBarras.producto_id).where(
            ProductoCodigoBarras.codigo == codigo, ProductoCodigoBarras.activo.is_(True)
        )
    )
    if otro is not None:
        raise Conflicto(f"El código de barras {codigo} ya existe en el catálogo.", code="codigo_barras_duplicado")


def agregar_codigo_barras(
    db: Session,
    actor_id: uuid.UUID,
    producto_id: uuid.UUID,
    *,
    codigo: str,
    tipo: str = "ean13",
    unidades_por_codigo: Decimal = Decimal(1),
    es_principal: bool | None = None,
) -> ProductoCodigoBarras:
    p = _obtener(db, Producto, producto_id, "Producto")
    codigo = validar_codigo_barras(codigo, tipo)
    _verificar_codigo_libre(db, codigo)
    activos = list(
        db.scalars(
            select(ProductoCodigoBarras).where(
                ProductoCodigoBarras.producto_id == p.id, ProductoCodigoBarras.activo.is_(True)
            )
        )
    )
    principal = es_principal if es_principal is not None else not activos
    if principal:
        for c in activos:
            if c.es_principal:
                c.es_principal = False
        db.flush()
    cb = ProductoCodigoBarras(
        producto_id=p.id,
        codigo=codigo,
        tipo=tipo,
        unidades_por_codigo=unidades_por_codigo,
        es_principal=principal,
        created_by=actor_id,
    )
    db.add(cb)
    db.flush()  # uq_productos_codigos_barras_codigo cubre la carrera entre dos peticiones -> 409
    _evento(db, "codigo_barras", cb, "agregado")
    return cb


def quitar_codigo_barras(db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, codigo_id: uuid.UUID) -> None:
    cb = _obtener(db, ProductoCodigoBarras, codigo_id, "Código de barras")
    if cb.producto_id != producto_id:
        raise NoEncontrado("Código de barras no encontrado.")
    era_principal = cb.es_principal
    cb.activo, cb.es_principal = False, False
    db.flush()
    if era_principal:
        otro = db.scalar(
            select(ProductoCodigoBarras)
            .where(ProductoCodigoBarras.producto_id == producto_id, ProductoCodigoBarras.activo.is_(True))
            .order_by(ProductoCodigoBarras.created_at)
            .limit(1)
        )
        if otro is not None:
            otro.es_principal = True
            db.flush()
    _evento(db, "codigo_barras", cb, "retirado")


def agregar_referencia(
    db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, *, tipo: str, referencia: str, marca_id=None, notas=None
) -> ProductoReferencia:
    _obtener(db, Producto, producto_id, "Producto")
    if marca_id is not None and db.get(Marca, marca_id) is None:
        raise ReglaNegocio("La marca (fabricante) no existe.", code="marca_invalida")
    r = ProductoReferencia(
        producto_id=producto_id,
        tipo=tipo,
        referencia=referencia.strip(),
        marca_id=marca_id,
        notas=notas,
        created_by=actor_id,
    )
    db.add(r)
    db.flush()  # uq_productos_referencias -> 409
    _evento(db, "referencia", r, "agregada")
    return r


def quitar_referencia(db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, referencia_id: uuid.UUID) -> None:
    r = _obtener(db, ProductoReferencia, referencia_id, "Referencia")
    if r.producto_id != producto_id:
        raise NoEncontrado("Referencia no encontrada.")
    r.activo = False
    db.flush()
    _evento(db, "referencia", r, "retirada")


def crear_producto(
    db: Session, actor_id: uuid.UUID, *, sku: str, datos: dict, codigos: list[dict], referencias: list[dict]
) -> Producto:
    sku = sku.strip()
    if db.scalar(select(Producto.id).where(Producto.sku == sku)):
        raise Conflicto(f"El SKU {sku} ya existe.", code="sku_duplicado")
    _validar_fks_producto(db, datos)
    codigos_norm = [validar_codigo_barras(c["codigo"], c.get("tipo", "ean13")) for c in codigos]
    if len(set(codigos_norm)) != len(codigos_norm):
        raise Conflicto("Hay códigos de barras repetidos en la petición.", code="codigo_barras_duplicado")
    for c in codigos_norm:
        _verificar_codigo_libre(db, c)
    p = Producto(sku=sku, created_by=actor_id, **{k: v for k, v in datos.items() if k in _CAMPOS_PRODUCTO})
    db.add(p)
    db.flush()
    for i, c in enumerate(codigos):
        agregar_codigo_barras(
            db,
            actor_id,
            p.id,
            codigo=c["codigo"],
            tipo=c.get("tipo", "ean13"),
            unidades_por_codigo=c.get("unidades_por_codigo", Decimal(1)),
            es_principal=c.get("es_principal") if c.get("es_principal") is not None else (i == 0),
        )
    for r in referencias:
        agregar_referencia(db, actor_id, p.id, **r)
    _evento(db, "producto", p, "creado")
    return p


def actualizar_producto(db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, datos: dict) -> Producto:
    p = _obtener(db, Producto, producto_id, "Producto")
    _validar_fks_producto(db, datos)
    if datos.get("publicado_web") and not p.activo:
        raise ReglaNegocio("No se puede publicar en la web un producto inactivo.", code="producto_inactivo")
    _aplicar(p, datos, _CAMPOS_PRODUCTO)
    db.flush()
    _evento(db, "producto", p, "actualizado")
    return p


def cambiar_activo_producto(db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, activo: bool) -> Producto:
    p = _obtener(db, Producto, producto_id, "Producto")
    if p.activo == activo:
        return p
    p.activo = activo
    if not activo:
        p.publicado_web = False  # ck_productos_web_activo
    db.flush()
    _evento(db, "producto", p, "activado" if activo else "desactivado")
    registrar_accion(
        db,
        "catalogo.producto_activado" if activo else "catalogo.producto_desactivado",
        actor_id=actor_id,
        entidad_tipo="producto",
        entidad_id=p.id,
        antes={"activo": not activo},
        despues={"activo": activo},
    )
    return p


def codigo_ean_del_nodo(db: Session) -> str:
    """Código EAN (2 dígitos) del nodo actual (NODO_ID, o el nodo nube si no está configurado)."""
    nodo_id = get_settings().nodo_id or NODO_NUBE_ID
    codigo = db.scalar(select(Nodo.codigo_ean).where(Nodo.id == nodo_id))
    if codigo is None:
        raise ReglaNegocio("El nodo actual no está registrado en organizacion.nodos.", code="nodo_desconocido")
    return codigo


def _siguiente_ean_interno(db: Session, codigo_nodo: str) -> str:
    """Siguiente EAN-13 interno del nodo: consecutivo por `UPDATE ... RETURNING` (sin huecos ni duplicados).

    El UPDATE bloquea la fila del contador hasta el fin de la transacción: dos generaciones simultáneas se serializan y
    si la transacción se revierte el consecutivo también (no quedan huecos). Solo si un código ya existiera en la BD
    (p. ej. un EAN aleatorio heredado de la versión anterior con el mismo valor) se salta ese consecutivo.
    """
    nodo_id = get_settings().nodo_id or NODO_NUBE_ID
    db.execute(pg_insert(ContadorEan).values(nodo_id=nodo_id, ultimo=0).on_conflict_do_nothing())
    for _ in range(20):
        n = db.execute(
            text("UPDATE catalogo.contadores_ean SET ultimo = ultimo + 1 WHERE nodo_id = :n RETURNING ultimo"),
            {"n": nodo_id},
        ).scalar_one()
        if n > CONSECUTIVO_EAN_MAX:
            raise ReglaNegocio("Se agotaron los consecutivos de EAN del nodo.", code="ean_agotado")
        codigo = ean13_interno(codigo_nodo, n)
        if db.scalar(select(ProductoCodigoBarras.id).where(ProductoCodigoBarras.codigo == codigo)) is None:
            return codigo
    raise Conflicto("No se pudo generar un código libre; reintente.", code="codigo_barras_duplicado")


def generar_codigos_internos(
    db: Session, actor_id: uuid.UUID, *, producto_ids: list[uuid.UUID] | None, limite: int
) -> list[tuple[Producto, ProductoCodigoBarras]]:
    """Asigna un EAN-13 interno (prefijo '2') a productos activos que no tienen ningún código de barras activo."""
    codigo_nodo = codigo_ean_del_nodo(db)
    con_codigo = select(ProductoCodigoBarras.producto_id).where(ProductoCodigoBarras.activo.is_(True))
    stmt = (
        select(Producto)
        .where(Producto.activo.is_(True), Producto.id.not_in(con_codigo))
        .order_by(Producto.sku)
        .limit(limite)
    )
    if producto_ids is not None:
        stmt = stmt.where(Producto.id.in_(producto_ids))
    resultado = []
    for p in db.scalars(stmt).all():
        codigo = _siguiente_ean_interno(db, codigo_nodo)
        cb = agregar_codigo_barras(db, actor_id, p.id, codigo=codigo, tipo="interno", es_principal=True)
        resultado.append((p, cb))
    if resultado:
        registrar_accion(
            db,
            "catalogo.codigos_generados",
            actor_id=actor_id,
            despues={"cantidad": len(resultado)},
            entidad_tipo="producto",
        )
    return resultado


# ======================================================================================= compatibilidades
def asignar_compatibilidades(
    db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, version_ids: list[uuid.UUID], posicion=None, notas=None
) -> list[ProductoCompatibilidad]:
    _obtener(db, Producto, producto_id, "Producto")
    unicas = list(dict.fromkeys(version_ids))
    existentes = set(db.scalars(select(VehiculoVersion.id).where(VehiculoVersion.id.in_(unicas))))
    if len(existentes) != len(unicas):
        raise ReglaNegocio("Alguna versión de vehículo no existe.", code="version_invalida")
    previas = {
        c.version_id: c
        for c in db.scalars(
            select(ProductoCompatibilidad).where(
                ProductoCompatibilidad.producto_id == producto_id, ProductoCompatibilidad.version_id.in_(unicas)
            )
        )
    }
    resultado = []
    for vid in unicas:
        c = previas.get(vid)
        if c is None:
            c = ProductoCompatibilidad(
                producto_id=producto_id, version_id=vid, posicion=posicion, notas=notas, created_by=actor_id
            )
            db.add(c)
        else:
            c.activo, c.posicion, c.notas = True, posicion, notas
        resultado.append(c)
    db.flush()
    for c in resultado:
        _evento(db, "compatibilidad", c, "asignada")
    return resultado


def quitar_compatibilidad(db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, version_id: uuid.UUID) -> None:
    c = db.scalar(
        select(ProductoCompatibilidad).where(
            ProductoCompatibilidad.producto_id == producto_id,
            ProductoCompatibilidad.version_id == version_id,
            ProductoCompatibilidad.activo.is_(True),
        )
    )
    if c is None:
        raise NoEncontrado("El producto no tiene asignada esa versión.")
    c.activo = False
    db.flush()
    _evento(db, "compatibilidad", c, "retirada")


# ======================================================================================= precios
def lista_predeterminada(db: Session) -> ListaPrecio:
    lp = db.scalar(select(ListaPrecio).where(ListaPrecio.es_predeterminada.is_(True), ListaPrecio.activo.is_(True)))
    if lp is None:
        raise ReglaNegocio("No hay lista de precios predeterminada.", code="sin_lista_precios")
    return lp


def fijar_precio(
    db: Session,
    actor_id: uuid.UUID,
    producto_id: uuid.UUID,
    *,
    precio: Decimal,
    lista_precio_id: uuid.UUID | None = None,
    sede_id: uuid.UUID | None = None,
    motivo: str | None = None,
) -> Precio:
    """Fija el precio: cierra la vigencia del abierto (hasta = ahora) y abre uno nuevo (desde = ahora)."""
    _obtener(db, Producto, producto_id, "Producto")
    if precio < 0:
        raise ReglaNegocio("El precio no puede ser negativo.", code="precio_invalido")
    lista = db.get(ListaPrecio, lista_precio_id) if lista_precio_id else lista_predeterminada(db)
    if lista is None:
        raise ReglaNegocio("La lista de precios no existe.", code="lista_invalida")
    ahora: datetime = db.scalar(select(func.clock_timestamp()))
    abierto = db.scalar(
        select(Precio)
        .where(
            Precio.producto_id == producto_id,
            Precio.lista_precio_id == lista.id,
            Precio.sede_id.is_(sede_id) if sede_id is None else Precio.sede_id == sede_id,
            Precio.vigente_hasta.is_(None),
        )
        .with_for_update()
    )
    antes = None
    if abierto is not None:
        antes = abierto.precio
        abierto.vigente_hasta = ahora
        db.flush()
    nuevo = Precio(
        producto_id=producto_id,
        lista_precio_id=lista.id,
        sede_id=sede_id,
        precio=precio,
        vigente_desde=ahora,
        created_by=actor_id,
    )
    db.add(nuevo)
    db.flush()  # ex_precios_sin_solape -> 409 si hubiera solapamiento
    _evento(db, "precio", nuevo, "fijado")
    registrar_accion(
        db,
        "catalogo.precio_fijado",
        actor_id=actor_id,
        sede_id=sede_id,
        entidad_tipo="producto",
        entidad_id=producto_id,
        antes={"precio": str(antes)} if antes is not None else None,
        despues={"precio": str(precio), "lista": lista.codigo},
        motivo=motivo,
    )
    return nuevo


def precio_vigente(
    db: Session,
    producto_id: uuid.UUID,
    *,
    lista_precio_id: uuid.UUID | None = None,
    sede_id: uuid.UUID | None = None,
    en: datetime | None = None,
) -> Precio | None:
    """Precio vigente en `en` (por defecto ahora). El de la sede tiene prioridad sobre el general (sede NULL)."""
    lista_id = lista_precio_id or lista_predeterminada(db).id
    instante = en or db.scalar(select(func.clock_timestamp()))  # no now(): sería el inicio de la transacción
    stmt = (
        select(Precio)
        .where(
            Precio.producto_id == producto_id,
            Precio.lista_precio_id == lista_id,
            Precio.vigente_desde <= instante,
            (Precio.vigente_hasta.is_(None)) | (Precio.vigente_hasta > instante),
        )
        .order_by(Precio.sede_id.is_(None), Precio.vigente_desde.desc())
        .limit(1)
    )
    stmt = (
        stmt.where((Precio.sede_id == sede_id) | (Precio.sede_id.is_(None)))
        if sede_id
        else stmt.where(Precio.sede_id.is_(None))
    )
    return db.scalar(stmt)


def historial_precios(
    db: Session, producto_id: uuid.UUID, lista_precio_id: uuid.UUID | None, sede_id: uuid.UUID | None
):
    stmt = select(Precio).where(Precio.producto_id == producto_id).order_by(Precio.vigente_desde.desc())
    if lista_precio_id:
        stmt = stmt.where(Precio.lista_precio_id == lista_precio_id)
    if sede_id:
        stmt = stmt.where(Precio.sede_id == sede_id)
    return stmt
