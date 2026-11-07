"""Rutas del catálogo (/catalogo/...) y consulta rápida del escáner (/pos/productos/codigo/{codigo}).

Permisos: lectura `catalogo.ver`; escritura `catalogo.editar`; precios `precios.editar`.
Listados: paginación limit/offset (+ total), filtros y `orden` (campo | -campo).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import Response as RawResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Actor, Db, requiere_permiso, sede_efectiva
from app.api.paginacion import Pag, Pagina, aplicar_orden, paginar
from app.core.errores import NoEncontrado
from app.modules.catalogo import busqueda, imagenes
from app.modules.catalogo import servicios as svc
from app.modules.catalogo.almacenamiento import get_almacenamiento
from app.modules.catalogo.models import (
    Categoria,
    Impuesto,
    Marca,
    Producto,
    ProductoCodigoBarras,
    ProductoCompatibilidad,
    ProductoReferencia,
    VehiculoAlias,
    VehiculoMarca,
    VehiculoModelo,
    VehiculoVersion,
)
from app.modules.catalogo.schemas import (
    AniosModeloOut,
    CategoriaIn,
    CategoriaNodo,
    CategoriaOut,
    CategoriaPatch,
    CodigoBarrasIn,
    CodigoBarrasOut,
    CodigoGeneradoOut,
    CompatibilidadIn,
    CompatibilidadOut,
    GenerarCodigosIn,
    ImagenOut,
    ImpuestoOut,
    MarcaIn,
    MarcaOut,
    MarcaPatch,
    OrdenImagenesIn,
    PaginaProductos,
    PrecioIn,
    PrecioOut,
    ProductoBuscadoOut,
    ProductoDetalleOut,
    ProductoEscaneadoOut,
    ProductoIn,
    ProductoOut,
    ProductoPatch,
    ReferenciaIn,
    ReferenciaOut,
    VehiculoAliasIn,
    VehiculoAliasOut,
    VehiculoAliasPatch,
    VehiculoMarcaIn,
    VehiculoMarcaOut,
    VehiculoMarcaPatch,
    VehiculoModeloIn,
    VehiculoModeloOut,
    VehiculoModeloPatch,
    VehiculoVersionIn,
    VehiculoVersionOut,
    VehiculoVersionPatch,
)

router = APIRouter(prefix="/catalogo", tags=["catalogo"])
escaner_router = APIRouter(prefix="/pos", tags=["pos"])
Ver = Annotated[Actor, Depends(requiere_permiso("catalogo.ver"))]
Editar = Annotated[Actor, Depends(requiere_permiso("catalogo.editar"))]
EditarPrecios = Annotated[Actor, Depends(requiere_permiso("precios.editar"))]
Orden = Annotated[str | None, Query(description="Campo de orden: 'campo' o '-campo' (desc)")]


# ============================================================================================ categorías
@router.get("/categorias", response_model=Pagina[CategoriaOut], summary="Lista categorías (plana, paginada)")
def listar_categorias(
    db: Db,
    _: Ver,
    pag: Pag,
    q: str | None = None,
    parent_id: uuid.UUID | None = None,
    activo: bool | None = None,
    orden: Orden = None,
):
    stmt = select(Categoria)
    if q:
        stmt = stmt.where(func.lower(Categoria.nombre).like(f"%{q.strip().lower()}%"))
    if parent_id:
        stmt = stmt.where(Categoria.parent_id == parent_id)
    if activo is not None:
        stmt = stmt.where(Categoria.activo.is_(activo))
    stmt = aplicar_orden(
        stmt, orden, {"nombre": Categoria.nombre, "orden": Categoria.orden}, [Categoria.orden, Categoria.nombre]
    )
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.get("/categorias/arbol", response_model=list[CategoriaNodo], summary="Árbol completo de categorías")
def arbol_categorias(db: Db, _: Ver, incluir_inactivas: bool = False):
    return svc.arbol_categorias(db, solo_activas=not incluir_inactivas)


@router.post("/categorias", response_model=CategoriaOut, status_code=201, summary="Crea una categoría")
def crear_categoria(datos: CategoriaIn, db: Db, actor: Editar):
    return svc.crear_categoria(db, actor.empleado.id, nombre=datos.nombre, parent_id=datos.parent_id, orden=datos.orden)


@router.patch("/categorias/{categoria_id}", response_model=CategoriaOut, summary="Edita/mueve/desactiva (evita ciclos)")
def editar_categoria(categoria_id: uuid.UUID, datos: CategoriaPatch, db: Db, actor: Editar):
    return svc.actualizar_categoria(db, actor.empleado.id, categoria_id, datos.model_dump(exclude_unset=True))


# ============================================================================================ marcas
@router.get("/marcas", response_model=Pagina[MarcaOut], summary="Lista marcas de productos")
def listar_marcas(db: Db, _: Ver, pag: Pag, q: str | None = None, activo: bool | None = None, orden: Orden = None):
    stmt = select(Marca)
    if q:
        stmt = stmt.where(func.lower(Marca.nombre).like(f"%{q.strip().lower()}%"))
    if activo is not None:
        stmt = stmt.where(Marca.activo.is_(activo))
    stmt = aplicar_orden(stmt, orden, {"nombre": Marca.nombre, "creada": Marca.created_at}, [Marca.nombre])
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.post("/marcas", response_model=MarcaOut, status_code=201, summary="Crea una marca")
def crear_marca(datos: MarcaIn, db: Db, actor: Editar):
    return svc.crear_marca(db, actor.empleado.id, datos.model_dump())


@router.patch("/marcas/{marca_id}", response_model=MarcaOut, summary="Edita o desactiva una marca")
def editar_marca(marca_id: uuid.UUID, datos: MarcaPatch, db: Db, actor: Editar):
    return svc.actualizar_marca(db, actor.empleado.id, marca_id, datos.model_dump(exclude_unset=True))


# ============================================================================================ impuestos
@router.get("/impuestos", response_model=Pagina[ImpuestoOut], summary="Impuestos (solo lectura)")
def listar_impuestos(db: Db, _: Ver, pag: Pag, activo: bool | None = True, orden: Orden = None):
    stmt = select(Impuesto)
    if activo is not None:
        stmt = stmt.where(Impuesto.activo.is_(activo))
    stmt = aplicar_orden(stmt, orden, {"codigo": Impuesto.codigo, "tarifa": Impuesto.tarifa_pct}, [Impuesto.codigo])
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


# ============================================================================================ vehículos
@router.get("/vehiculos/marcas", response_model=Pagina[VehiculoMarcaOut], summary="Marcas de vehículos")
def listar_vehiculo_marcas(
    db: Db, _: Ver, pag: Pag, q: str | None = None, activo: bool | None = None, orden: Orden = None
):
    stmt = select(VehiculoMarca)
    if q:
        stmt = stmt.where(func.lower(VehiculoMarca.nombre).like(f"%{q.strip().lower()}%"))
    if activo is not None:
        stmt = stmt.where(VehiculoMarca.activo.is_(activo))
    stmt = aplicar_orden(stmt, orden, {"nombre": VehiculoMarca.nombre}, [VehiculoMarca.nombre])
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.post("/vehiculos/marcas", response_model=VehiculoMarcaOut, status_code=201, summary="Crea marca de vehículo")
def crear_vehiculo_marca(datos: VehiculoMarcaIn, db: Db, actor: Editar):
    return svc.crear_vehiculo_marca(db, actor.empleado.id, datos.model_dump())


@router.patch("/vehiculos/marcas/{id}", response_model=VehiculoMarcaOut, summary="Edita marca de vehículo")
def editar_vehiculo_marca(id: uuid.UUID, datos: VehiculoMarcaPatch, db: Db, actor: Editar):
    return svc.actualizar_vehiculo_marca(db, actor.empleado.id, id, datos.model_dump(exclude_unset=True))


@router.get("/vehiculos/modelos", response_model=Pagina[VehiculoModeloOut], summary="Modelos de vehículos")
def listar_vehiculo_modelos(
    db: Db,
    _: Ver,
    pag: Pag,
    marca_id: uuid.UUID | None = None,
    q: str | None = None,
    activo: bool | None = None,
    orden: Orden = None,
):
    stmt = select(VehiculoModelo)
    if marca_id:
        stmt = stmt.where(VehiculoModelo.marca_id == marca_id)
    if q:
        stmt = stmt.where(func.lower(VehiculoModelo.nombre).like(f"%{q.strip().lower()}%"))
    if activo is not None:
        stmt = stmt.where(VehiculoModelo.activo.is_(activo))
    stmt = aplicar_orden(stmt, orden, {"nombre": VehiculoModelo.nombre}, [VehiculoModelo.nombre])
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.get(
    "/vehiculos/marcas/{marca_id}/modelos",
    response_model=list[VehiculoModeloOut],
    summary="Selector del POS: modelos activos de una marca (orden alfabético)",
)
def modelos_de_marca(marca_id: uuid.UUID, db: Db, _: Ver):
    if db.get(VehiculoMarca, marca_id) is None:
        raise NoEncontrado("Marca de vehículo no encontrada.")
    return db.scalars(
        select(VehiculoModelo)
        .where(VehiculoModelo.marca_id == marca_id, VehiculoModelo.activo.is_(True))
        .order_by(VehiculoModelo.nombre)
    ).all()


@router.get(
    "/vehiculos/modelos/{modelo_id}/anios",
    response_model=AniosModeloOut,
    summary="Selector del POS: años disponibles de un modelo según sus versiones (descendente)",
)
def anios_del_modelo(modelo_id: uuid.UUID, db: Db, _: Ver):
    return AniosModeloOut(modelo_id=modelo_id, anios=svc.anios_de_modelo(db, modelo_id))


@router.get(
    "/vehiculos/alias", response_model=Pagina[VehiculoAliasOut], summary="Alias de marcas y modelos de vehículos"
)
def listar_alias(
    db: Db,
    _: Ver,
    pag: Pag,
    q: str | None = None,
    marca_id: uuid.UUID | None = None,
    modelo_id: uuid.UUID | None = None,
    activo: bool | None = None,
):
    stmt = select(VehiculoAlias)
    if q:
        stmt = stmt.where(VehiculoAlias.alias_normalizado.like(f"%{svc.normalizar_alias(q)}%"))
    if marca_id:
        stmt = stmt.where(VehiculoAlias.marca_id == marca_id)
    if modelo_id:
        stmt = stmt.where(VehiculoAlias.modelo_id == modelo_id)
    if activo is not None:
        stmt = stmt.where(VehiculoAlias.activo.is_(activo))
    stmt = stmt.order_by(VehiculoAlias.alias_normalizado)
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.post("/vehiculos/alias", response_model=VehiculoAliasOut, status_code=201, summary="Crea un alias")
def crear_alias(datos: VehiculoAliasIn, db: Db, actor: Editar):
    return svc.crear_alias_vehiculo(db, actor.empleado.id, datos.model_dump())


@router.patch("/vehiculos/alias/{id}", response_model=VehiculoAliasOut, summary="Edita o desactiva un alias")
def editar_alias(id: uuid.UUID, datos: VehiculoAliasPatch, db: Db, actor: Editar):
    return svc.actualizar_alias_vehiculo(db, actor.empleado.id, id, datos.model_dump(exclude_unset=True))


@router.post("/vehiculos/modelos", response_model=VehiculoModeloOut, status_code=201, summary="Crea modelo de vehículo")
def crear_vehiculo_modelo(datos: VehiculoModeloIn, db: Db, actor: Editar):
    return svc.crear_vehiculo_modelo(db, actor.empleado.id, datos.model_dump())


@router.patch("/vehiculos/modelos/{id}", response_model=VehiculoModeloOut, summary="Edita modelo de vehículo")
def editar_vehiculo_modelo(id: uuid.UUID, datos: VehiculoModeloPatch, db: Db, actor: Editar):
    return svc.actualizar_vehiculo_modelo(db, actor.empleado.id, id, datos.model_dump(exclude_unset=True))


@router.get("/vehiculos/versiones", response_model=Pagina[VehiculoVersionOut], summary="Versiones de vehículos")
def listar_vehiculo_versiones(
    db: Db,
    _: Ver,
    pag: Pag,
    modelo_id: uuid.UUID | None = None,
    anio: Annotated[
        int | None, Query(ge=1950, le=2100, description="Solo versiones cuyo rango contiene el año")
    ] = None,
    activo: bool | None = None,
    orden: Orden = None,
):
    stmt = select(VehiculoVersion)
    if modelo_id:
        stmt = stmt.where(VehiculoVersion.modelo_id == modelo_id)
    if anio:
        stmt = stmt.where(VehiculoVersion.anios.contains(anio))
    if activo is not None:
        stmt = stmt.where(VehiculoVersion.activo.is_(activo))
    stmt = aplicar_orden(
        stmt,
        orden,
        {"nombre": VehiculoVersion.nombre, "anio_desde": VehiculoVersion.anio_desde},
        [VehiculoVersion.anio_desde, VehiculoVersion.nombre],
    )
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.post(
    "/vehiculos/versiones", response_model=VehiculoVersionOut, status_code=201, summary="Crea versión de vehículo"
)
def crear_vehiculo_version(datos: VehiculoVersionIn, db: Db, actor: Editar):
    return svc.crear_vehiculo_version(db, actor.empleado.id, datos.model_dump())


@router.patch("/vehiculos/versiones/{id}", response_model=VehiculoVersionOut, summary="Edita versión de vehículo")
def editar_vehiculo_version(id: uuid.UUID, datos: VehiculoVersionPatch, db: Db, actor: Editar):
    return svc.actualizar_vehiculo_version(db, actor.empleado.id, id, datos.model_dump(exclude_unset=True))


@router.get(
    "/vehiculos/versiones/{version_id}/productos",
    response_model=Pagina[ProductoBuscadoOut],
    summary="Productos compatibles con una versión de vehículo",
)
def productos_de_version(version_id: uuid.UUID, db: Db, actor: Ver, pag: Pag, sede_id: uuid.UUID | None = None):
    items, total, _inc = busqueda.buscar(
        db,
        q=None,
        sede_id=sede_efectiva(db, actor, sede_id),
        limit=pag.limit,
        offset=pag.offset,
        vehiculo_version_id=version_id,
    )
    return Pagina(items=items, total=total, limit=pag.limit, offset=pag.offset)


# ============================================================================================ productos
_ORDEN_PRODUCTOS = {"nombre": Producto.nombre, "sku": Producto.sku, "creado": Producto.created_at}


def _detalle(db: Session, p: Producto) -> ProductoDetalleOut:
    codigos = db.scalars(
        select(ProductoCodigoBarras)
        .where(ProductoCodigoBarras.producto_id == p.id, ProductoCodigoBarras.activo.is_(True))
        .order_by(ProductoCodigoBarras.es_principal.desc(), ProductoCodigoBarras.created_at)
    ).all()
    refs = db.scalars(
        select(ProductoReferencia)
        .where(ProductoReferencia.producto_id == p.id, ProductoReferencia.activo.is_(True))
        .order_by(ProductoReferencia.created_at)
    ).all()
    out = ProductoDetalleOut.model_validate(p)
    out.codigos_barras = [CodigoBarrasOut.model_validate(c) for c in codigos]
    out.referencias = [ReferenciaOut.model_validate(r) for r in refs]
    return out


@router.get("/productos", response_model=Pagina[ProductoOut], summary="Lista productos (filtros y orden)")
def listar_productos(
    db: Db,
    _: Ver,
    pag: Pag,
    q: Annotated[
        str | None, Query(description="Filtro simple por SKU o nombre; para búsqueda ranqueada use /buscar")
    ] = None,
    categoria_id: uuid.UUID | None = None,
    marca_id: uuid.UUID | None = None,
    activo: bool | None = True,
    orden: Orden = None,
):
    stmt = select(Producto)
    if q:
        patron = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Producto.sku).like(patron), func.lower(Producto.nombre).like(patron)))
    if categoria_id:
        stmt = stmt.where(Producto.categoria_id.in_(svc.ids_categoria_y_descendientes(db, categoria_id)))
    if marca_id:
        stmt = stmt.where(Producto.marca_id == marca_id)
    if activo is not None:
        stmt = stmt.where(Producto.activo.is_(activo))
    stmt = aplicar_orden(stmt, orden, _ORDEN_PRODUCTOS, [Producto.nombre, Producto.id])
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.get(
    "/productos/buscar",
    response_model=PaginaProductos,
    summary="Búsqueda por relevancia (nombre, marca, referencia, código, vehículo+año) con precio y stock de la sede",
)
def buscar_productos(
    db: Db,
    actor: Ver,
    pag: Pag,
    q: Annotated[str | None, Query(description="Texto libre. Ej.: 'pastilla freno spark 2018', 'ABC-123'")] = None,
    vehiculo_version_id: uuid.UUID | None = None,
    categoria_id: uuid.UUID | None = None,
    marca_id: uuid.UUID | None = None,
    solo_con_stock: bool = False,
    sede_id: Annotated[
        uuid.UUID | None, Query(description="Solo backoffice; en el POS es la sede de la sesión")
    ] = None,
):
    items, total, incompleta = busqueda.buscar(
        db,
        q=q,
        sede_id=sede_efectiva(db, actor, sede_id),
        limit=pag.limit,
        offset=pag.offset,
        vehiculo_version_id=vehiculo_version_id,
        categoria_id=categoria_id,
        marca_id=marca_id,
        solo_con_stock=solo_con_stock,
    )
    return PaginaProductos(
        items=items,
        total=total,
        limit=pag.limit,
        offset=pag.offset,
        busqueda_aproximada_incompleta=incompleta,
    )


@router.post(
    "/productos/codigos-barras/generar",
    response_model=list[CodigoGeneradoOut],
    summary="Genera EAN-13 interno ('2'...) a productos sin código",
)
def generar_codigos(datos: GenerarCodigosIn, db: Db, actor: Editar):
    res = svc.generar_codigos_internos(db, actor.empleado.id, producto_ids=datos.producto_ids, limite=datos.limite)
    return [CodigoGeneradoOut(producto_id=p.id, sku=p.sku, codigo=c.codigo) for p, c in res]


@router.post("/productos", response_model=ProductoDetalleOut, status_code=201, summary="Crea un producto")
def crear_producto(datos: ProductoIn, db: Db, actor: Editar):
    campos = datos.model_dump(exclude={"sku", "codigos_barras", "referencias"})
    p = svc.crear_producto(
        db,
        actor.empleado.id,
        sku=datos.sku,
        datos=campos,
        codigos=[c.model_dump() for c in datos.codigos_barras],
        referencias=[r.model_dump() for r in datos.referencias],
    )
    return _detalle(db, p)


@router.get("/productos/{producto_id}", response_model=ProductoDetalleOut, summary="Detalle de un producto")
def obtener_producto(producto_id: uuid.UUID, db: Db, _: Ver):
    p = db.get(Producto, producto_id)
    if p is None:
        raise NoEncontrado("Producto no encontrado.")
    return _detalle(db, p)


@router.patch("/productos/{producto_id}", response_model=ProductoDetalleOut, summary="Edita un producto")
def editar_producto(producto_id: uuid.UUID, datos: ProductoPatch, db: Db, actor: Editar):
    p = svc.actualizar_producto(db, actor.empleado.id, producto_id, datos.model_dump(exclude_unset=True))
    return _detalle(db, p)


@router.post("/productos/{producto_id}/activar", response_model=ProductoOut, summary="Activa un producto")
def activar_producto(producto_id: uuid.UUID, db: Db, actor: Editar):
    return svc.cambiar_activo_producto(db, actor.empleado.id, producto_id, True)


@router.post("/productos/{producto_id}/desactivar", response_model=ProductoOut, summary="Desactiva un producto")
def desactivar_producto(producto_id: uuid.UUID, db: Db, actor: Editar):
    return svc.cambiar_activo_producto(db, actor.empleado.id, producto_id, False)


@router.post(
    "/productos/{producto_id}/codigos-barras",
    response_model=CodigoBarrasOut,
    status_code=201,
    summary="Agrega un código de barras",
)
def agregar_codigo(producto_id: uuid.UUID, datos: CodigoBarrasIn, db: Db, actor: Editar):
    return svc.agregar_codigo_barras(db, actor.empleado.id, producto_id, **datos.model_dump())


@router.delete(
    "/productos/{producto_id}/codigos-barras/{codigo_id}", status_code=204, summary="Retira un código de barras"
)
def quitar_codigo(producto_id: uuid.UUID, codigo_id: uuid.UUID, db: Db, actor: Editar) -> Response:
    svc.quitar_codigo_barras(db, actor.empleado.id, producto_id, codigo_id)
    return Response(status_code=204)


@router.post(
    "/productos/{producto_id}/referencias",
    response_model=ReferenciaOut,
    status_code=201,
    summary="Agrega una referencia (OEM, alterna...)",
)
def agregar_referencia(producto_id: uuid.UUID, datos: ReferenciaIn, db: Db, actor: Editar):
    r = svc.agregar_referencia(db, actor.empleado.id, producto_id, **datos.model_dump())
    db.refresh(r)  # referencia_normalizada es columna generada
    return r


@router.delete("/productos/{producto_id}/referencias/{referencia_id}", status_code=204, summary="Retira una referencia")
def quitar_referencia(producto_id: uuid.UUID, referencia_id: uuid.UUID, db: Db, actor: Editar) -> Response:
    svc.quitar_referencia(db, actor.empleado.id, producto_id, referencia_id)
    return Response(status_code=204)


# ---- compatibilidades
@router.get(
    "/productos/{producto_id}/compatibilidades", response_model=list[CompatibilidadOut], summary="Versiones compatibles"
)
def listar_compatibilidades(producto_id: uuid.UUID, db: Db, _: Ver):
    return db.scalars(
        select(ProductoCompatibilidad).where(
            ProductoCompatibilidad.producto_id == producto_id, ProductoCompatibilidad.activo.is_(True)
        )
    ).all()


@router.post(
    "/productos/{producto_id}/compatibilidades",
    response_model=list[CompatibilidadOut],
    status_code=201,
    summary="Asigna versiones de vehículo",
)
def asignar_compatibilidades(producto_id: uuid.UUID, datos: CompatibilidadIn, db: Db, actor: Editar):
    return svc.asignar_compatibilidades(
        db, actor.empleado.id, producto_id, datos.version_ids, datos.posicion, datos.notas
    )


@router.delete(
    "/productos/{producto_id}/compatibilidades/{version_id}", status_code=204, summary="Quita una versión de vehículo"
)
def quitar_compatibilidad(producto_id: uuid.UUID, version_id: uuid.UUID, db: Db, actor: Editar) -> Response:
    svc.quitar_compatibilidad(db, actor.empleado.id, producto_id, version_id)
    return Response(status_code=204)


# ---- precios
@router.post(
    "/productos/{producto_id}/precios",
    response_model=PrecioOut,
    status_code=201,
    summary="Fija el precio (cierra la vigencia anterior)",
)
def fijar_precio(producto_id: uuid.UUID, datos: PrecioIn, db: Db, actor: EditarPrecios):
    return svc.fijar_precio(
        db,
        actor.empleado.id,
        producto_id,
        precio=datos.precio,
        lista_precio_id=datos.lista_precio_id,
        sede_id=datos.sede_id,
        motivo=datos.motivo,
    )


@router.get(
    "/productos/{producto_id}/precios/vigente", response_model=PrecioOut, summary="Precio vigente (ahora o en `en`)"
)
def precio_vigente(
    producto_id: uuid.UUID,
    db: Db,
    _: Ver,
    lista_precio_id: uuid.UUID | None = None,
    sede_id: uuid.UUID | None = None,
    en: Annotated[
        datetime | None, Query(description="Instante a consultar (ISO 8601 con zona); por defecto ahora")
    ] = None,
):
    pr = svc.precio_vigente(db, producto_id, lista_precio_id=lista_precio_id, sede_id=sede_id, en=en)
    if pr is None:
        raise NoEncontrado("El producto no tiene precio vigente en ese momento.", code="sin_precio")
    return pr


@router.get("/productos/{producto_id}/precios", response_model=Pagina[PrecioOut], summary="Historial de precios")
def historial_precios(
    producto_id: uuid.UUID,
    db: Db,
    _: Ver,
    pag: Pag,
    lista_precio_id: uuid.UUID | None = None,
    sede_id: uuid.UUID | None = None,
):
    filas, total = paginar(db, svc.historial_precios(db, producto_id, lista_precio_id, sede_id), pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


# ---- imágenes
@router.get(
    "/productos/{producto_id}/imagenes", response_model=list[ImagenOut], summary="Imágenes del producto (en orden)"
)
def listar_imagenes(producto_id: uuid.UUID, db: Db, _: Ver):
    return imagenes.listar_imagenes(db, producto_id)


@router.post(
    "/productos/{producto_id}/imagenes",
    response_model=ImagenOut,
    status_code=201,
    summary="Sube una imagen (JPEG/PNG/WebP, tamaño máximo configurable)",
)
async def subir_imagen(
    producto_id: uuid.UUID,
    db: Db,
    actor: Editar,
    archivo: Annotated[UploadFile, File(description="Imagen JPEG, PNG o WebP")],
    texto_alternativo: Annotated[str | None, Form()] = None,
):
    maximo = imagenes.get_settings().imagen_max_mb * 1024 * 1024
    datos = await archivo.read(maximo + 1)  # nunca se lee más del máximo + 1 byte
    return imagenes.agregar_imagen(db, get_almacenamiento(), actor.empleado.id, producto_id, datos, texto_alternativo)


@router.put(
    "/productos/{producto_id}/imagenes/orden",
    response_model=list[ImagenOut],
    summary="Ordena las imágenes (la primera es la principal)",
)
def ordenar_imagenes(producto_id: uuid.UUID, datos: OrdenImagenesIn, db: Db, actor: Editar):
    return imagenes.ordenar_imagenes(db, actor.empleado.id, producto_id, datos.ids)


@router.delete("/productos/{producto_id}/imagenes/{imagen_id}", status_code=204, summary="Retira una imagen")
def quitar_imagen(producto_id: uuid.UUID, imagen_id: uuid.UUID, db: Db, actor: Editar) -> Response:
    imagenes.quitar_imagen(db, actor.empleado.id, producto_id, imagen_id)
    return Response(status_code=204)


@router.get("/archivos/{clave:path}", include_in_schema=False)
def servir_archivo(clave: str) -> RawResponse:
    """Sirve las imágenes del almacenamiento local (contenido público de catálogo)."""
    datos = get_almacenamiento().leer(clave)
    tipo, _ = imagenes.detectar_tipo(datos)
    return RawResponse(datos, media_type=tipo, headers={"Cache-Control": "public, max-age=86400"})


# ============================================================================================ escáner POS
@escaner_router.get(
    "/productos/codigo/{codigo}",
    response_model=ProductoEscaneadoOut,
    summary="Escáner: producto por código de barras exacto o SKU, con precio vigente y stock de la sede",
)
def producto_por_codigo(codigo: str, db: Db, actor: Ver, sede_id: uuid.UUID | None = None):
    r = busqueda.producto_por_codigo(db, codigo, sede_efectiva(db, actor, sede_id))
    if r is None:
        raise NoEncontrado("No hay un producto con ese código de barras o SKU.", code="producto_no_encontrado")
    return r
