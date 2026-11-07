"""Rutas de inventario (/inventario/...): bodegas, ubicaciones, existencias, kardex, entradas, ajustes e importación.

Permisos: `inventario.ver` (consultas), `inventario.ajustar` (ajustes y bodegas/ubicaciones),
`inventario.entradas` (entradas de mercancía), `inventario.importar` (Excel).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Actor, Db, requiere_permiso, sede_efectiva
from app.api.paginacion import Pag, Pagina, aplicar_orden, paginar
from app.core.errores import NoEncontrado
from app.modules.inventario import aprobaciones, configuracion, consultas, importacion
from app.modules.inventario import servicios as svc
from app.modules.inventario.models import Bodega, Importacion, MovimientoInventario, SolicitudInventario, Ubicacion
from app.modules.inventario.verificacion import verificar

router = APIRouter(prefix="/inventario", tags=["inventario"])
Ver = Annotated[Actor, Depends(requiere_permiso("inventario.ver"))]
Gestiona = Annotated[Actor, Depends(requiere_permiso("inventario.ajustar"))]
Entradas = Annotated[Actor, Depends(requiere_permiso("inventario.entradas"))]
Importa = Annotated[Actor, Depends(requiere_permiso("inventario.importar"))]
Aprueba = Annotated[Actor, Depends(requiere_permiso("inventario.aprobar"))]
Configura = Annotated[Actor, Depends(requiere_permiso("admin.configuracion"))]
Orden = Annotated[str | None, Query(description="'campo' o '-campo' (desc)")]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------------ esquemas
class BodegaIn(BaseModel):
    sede_id: uuid.UUID
    codigo: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=1, max_length=120)
    es_vendible: bool = True


class BodegaPatch(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=120)
    es_vendible: bool | None = None
    activo: bool | None = None


class BodegaOut(_Out):
    id: uuid.UUID
    sede_id: uuid.UUID
    codigo: str
    nombre: str
    es_vendible: bool
    activo: bool


class UbicacionIn(BaseModel):
    bodega_id: uuid.UUID
    codigo: str = Field(min_length=1, max_length=30)
    pasillo: str = Field(min_length=1, max_length=30)
    estante: str | None = None
    nivel: str | None = None
    descripcion: str | None = None


class UbicacionPatch(BaseModel):
    pasillo: str | None = Field(None, min_length=1, max_length=30)
    estante: str | None = None
    nivel: str | None = None
    descripcion: str | None = None
    activo: bool | None = None


class UbicacionOut(_Out):
    id: uuid.UUID
    bodega_id: uuid.UUID
    codigo: str
    pasillo: str
    estante: str | None
    nivel: str | None
    descripcion: str | None
    activo: bool


class AsignarUbicacionIn(BaseModel):
    ubicacion_id: uuid.UUID
    es_principal: bool = False


class ExistenciaOut(BaseModel):
    bodega_id: uuid.UUID
    bodega_codigo: str
    bodega_nombre: str
    sede_id: uuid.UUID
    producto_id: uuid.UUID
    sku: str
    producto_nombre: str
    cantidad: Decimal
    cantidad_reservada: Decimal
    cantidad_disponible: Decimal = Field(description="existencia - reservas")
    costo_promedio: Decimal
    ultimo_costo: Decimal
    stock_minimo: Decimal


class MovimientoOut(_Out):
    id: uuid.UUID
    bodega_id: uuid.UUID
    producto_id: uuid.UUID
    secuencia: int
    tipo: str
    cantidad: Decimal
    costo_unitario: Decimal
    saldo_cantidad: Decimal = Field(description="Saldo acumulado de la bodega tras este movimiento")
    costo_promedio_resultante: Decimal
    origen_tipo: str
    origen_id: uuid.UUID
    ocurrido_at: datetime


class BajoMinimoOut(BaseModel):
    producto_id: uuid.UUID
    sku: str
    nombre: str
    stock_minimo: Decimal
    disponible: Decimal
    faltante: Decimal


class LineaEntradaIn(BaseModel):
    producto_id: uuid.UUID
    cantidad: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    costo_unitario: Decimal = Field(ge=0, max_digits=18, decimal_places=4)


class EntradaIn(BaseModel):
    bodega_id: uuid.UUID
    tercero_id: uuid.UUID | None = Field(None, description="Proveedor (tercero); opcional")
    numero_factura: str | None = Field(None, max_length=60, description="Número de la factura del proveedor")
    observaciones: str | None = None
    lineas: list[LineaEntradaIn] = Field(min_length=1, max_length=500)


class EntradaOut(BaseModel):
    id: uuid.UUID
    bodega_id: uuid.UUID
    total: Decimal
    movimientos: list[MovimientoOut]


class SolicitudOut(_Out):
    id: uuid.UUID
    tipo: Literal["entrada", "ajuste"]
    estado: Literal["pendiente_aprobacion", "aprobada", "rechazada"]
    sede_id: uuid.UUID
    bodega_id: uuid.UUID
    valor: Decimal
    umbral: Decimal
    payload: dict
    motivo: str | None
    solicitada_por_id: uuid.UUID
    resuelta_por_id: uuid.UUID | None
    resuelta_at: datetime | None
    motivo_resolucion: str | None
    autoaprobado: bool
    resultado_tipo: str | None
    resultado_id: uuid.UUID | None
    created_at: datetime


class RechazoIn(BaseModel):
    motivo: str = Field(min_length=5, max_length=300)


class AprobacionIn(BaseModel):
    motivo: str | None = Field(None, max_length=300, description="Comentario opcional de la aprobación")


class ConfigInventarioIn(BaseModel):
    umbral_aprobacion: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    propietario_autoaprueba: bool | None = None


class ConfigInventarioOut(BaseModel):
    sede_id: uuid.UUID
    umbral_aprobacion: Decimal
    propietario_autoaprueba: bool


class AjusteIn(BaseModel):
    bodega_id: uuid.UUID
    producto_id: uuid.UUID
    cantidad: Decimal = Field(max_digits=14, decimal_places=3, description="Positivo suma, negativo resta")
    motivo: str = Field(min_length=5, max_length=300)
    costo_unitario: Decimal | None = Field(None, ge=0, description="Solo ajustes positivos sin costo promedio")
    autorizacion_id: uuid.UUID | None = Field(
        None,
        description="Solo con sesión POS: autorización de un supervisor distinto si el valor supera el umbral. "
        "En backoffice se ignora: el ajuste queda pendiente de aprobación (202).",
    )


class ImportacionOut(_Out):
    id: uuid.UUID
    tipo: str
    estado: str
    nombre_archivo: str
    resumen: dict
    created_at: datetime
    confirmada_at: datetime | None


class FilaReporte(BaseModel):
    fila: int
    estado: Literal["ok", "error"]
    detalle: str
    sku: str | None = None


class ValidacionOut(ImportacionOut):
    reporte: list[FilaReporte]


# ------------------------------------------------------------------------------------ bodegas / ubicaciones
@router.get("/bodegas", response_model=Pagina[BodegaOut], summary="Lista bodegas")
def listar_bodegas(
    db: Db, _: Ver, pag: Pag, sede_id: uuid.UUID | None = None, activo: bool | None = None, orden: Orden = None
):
    stmt = select(Bodega)
    if sede_id:
        stmt = stmt.where(Bodega.sede_id == sede_id)
    if activo is not None:
        stmt = stmt.where(Bodega.activo.is_(activo))
    stmt = aplicar_orden(stmt, orden, {"codigo": Bodega.codigo, "nombre": Bodega.nombre}, [Bodega.codigo])
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.post("/bodegas", response_model=BodegaOut, status_code=201, summary="Crea una bodega")
def crear_bodega(datos: BodegaIn, db: Db, actor: Gestiona):
    return svc.crear_bodega(db, actor.empleado.id, datos.model_dump())


@router.patch("/bodegas/{bodega_id}", response_model=BodegaOut, summary="Edita o desactiva una bodega")
def editar_bodega(bodega_id: uuid.UUID, datos: BodegaPatch, db: Db, actor: Gestiona):
    return svc.actualizar_bodega(db, actor.empleado.id, bodega_id, datos.model_dump(exclude_unset=True))


@router.get("/ubicaciones", response_model=Pagina[UbicacionOut], summary="Lista ubicaciones")
def listar_ubicaciones(
    db: Db, _: Ver, pag: Pag, bodega_id: uuid.UUID | None = None, activo: bool | None = None, orden: Orden = None
):
    stmt = select(Ubicacion)
    if bodega_id:
        stmt = stmt.where(Ubicacion.bodega_id == bodega_id)
    if activo is not None:
        stmt = stmt.where(Ubicacion.activo.is_(activo))
    stmt = aplicar_orden(stmt, orden, {"codigo": Ubicacion.codigo, "pasillo": Ubicacion.pasillo}, [Ubicacion.codigo])
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.post("/ubicaciones", response_model=UbicacionOut, status_code=201, summary="Crea una ubicación")
def crear_ubicacion(datos: UbicacionIn, db: Db, actor: Gestiona):
    return svc.crear_ubicacion(db, actor.empleado.id, datos.model_dump())


@router.patch("/ubicaciones/{ubicacion_id}", response_model=UbicacionOut, summary="Edita o desactiva una ubicación")
def editar_ubicacion(ubicacion_id: uuid.UUID, datos: UbicacionPatch, db: Db, actor: Gestiona):
    return svc.actualizar_ubicacion(db, actor.empleado.id, ubicacion_id, datos.model_dump(exclude_unset=True))


@router.put("/productos/{producto_id}/ubicaciones", status_code=204, summary="Asigna la ubicación de un producto")
def asignar_ubicacion(producto_id: uuid.UUID, datos: AsignarUbicacionIn, db: Db, actor: Gestiona) -> Response:
    svc.asignar_ubicacion_producto(db, actor.empleado.id, producto_id, datos.ubicacion_id, datos.es_principal)
    return Response(status_code=204)


@router.delete(
    "/productos/{producto_id}/ubicaciones/{ubicacion_id}", status_code=204, summary="Quita la ubicación de un producto"
)
def quitar_ubicacion(producto_id: uuid.UUID, ubicacion_id: uuid.UUID, db: Db, actor: Gestiona) -> Response:
    svc.quitar_ubicacion_producto(db, actor.empleado.id, producto_id, ubicacion_id)
    return Response(status_code=204)


# ------------------------------------------------------------------------------------ consultas
@router.get(
    "/existencias",
    response_model=Pagina[ExistenciaOut],
    summary="Existencias por producto/bodega/sede (disponible = existencia - reservas)",
)
def listar_existencias(
    db: Db,
    actor: Ver,
    pag: Pag,
    sede_id: uuid.UUID | None = None,
    bodega_id: uuid.UUID | None = None,
    producto_id: uuid.UUID | None = None,
    q: str | None = None,
    solo_con_stock: bool = False,
    orden: Orden = None,
):
    if not (sede_id or bodega_id or producto_id):
        sede_id = sede_efectiva(db, actor, None)  # por defecto, la sede del usuario
    stmt = consultas.existencias(
        sede_id=sede_id, bodega_id=bodega_id, producto_id=producto_id, q=q, solo_con_stock=solo_con_stock
    )
    from app.modules.catalogo.models import Producto
    from app.modules.inventario.models import Existencia

    stmt = aplicar_orden(
        stmt,
        orden,
        {
            "sku": Producto.sku,
            "nombre": Producto.nombre,
            "cantidad": Existencia.cantidad,
            "disponible": Existencia.cantidad_disponible,
        },
        [Producto.sku, Existencia.bodega_id],
    )
    filas, total = paginar(db, stmt, pag, scalars=False)
    return Pagina(items=[dict(f._mapping) for f in filas], total=total, limit=pag.limit, offset=pag.offset)


@router.get(
    "/productos/{producto_id}/kardex",
    response_model=Pagina[MovimientoOut],
    summary="Kardex paginado con saldo acumulado",
)
def kardex(
    producto_id: uuid.UUID,
    db: Db,
    _: Ver,
    pag: Pag,
    bodega_id: uuid.UUID | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    orden: Orden = None,
):
    stmt = consultas.kardex(producto_id, bodega_id, desde, hasta)
    stmt = (
        aplicar_orden(
            stmt,
            orden,
            {"fecha": MovimientoInventario.ocurrido_at, "secuencia": MovimientoInventario.secuencia},
            [MovimientoInventario.ocurrido_at.desc(), MovimientoInventario.secuencia.desc()],
        )
        if orden
        else stmt.order_by(MovimientoInventario.ocurrido_at.desc(), MovimientoInventario.secuencia.desc())
    )
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.get("/bajo-minimo", response_model=Pagina[BajoMinimoOut], summary="Productos bajo el stock mínimo")
def bajo_minimo(db: Db, actor: Ver, pag: Pag, sede_id: uuid.UUID | None = None, bodega_id: uuid.UUID | None = None):
    sede = None if bodega_id else sede_efectiva(db, actor, sede_id)
    stmt = consultas.bajo_minimo(sede, bodega_id)
    from app.modules.catalogo.models import Producto

    stmt = stmt.order_by((Producto.stock_minimo).desc(), Producto.sku)
    filas, total = paginar(db, stmt, pag, scalars=False)
    return Pagina(items=[dict(f._mapping) for f in filas], total=total, limit=pag.limit, offset=pag.offset)


# ------------------------------------------------------------------------------------ escrituras
@router.post(
    "/entradas",
    response_model=EntradaOut | SolicitudOut,
    status_code=201,
    summary="Entrada simple de mercancía (recalcula el costo promedio). Sobre el umbral: 202 pendiente de aprobación",
)
def crear_entrada(datos: EntradaIn, db: Db, actor: Entradas, response: Response):
    estado, res = aprobaciones.entrada(
        db,
        actor,
        bodega_id=datos.bodega_id,
        tercero_id=datos.tercero_id,
        numero_factura=datos.numero_factura,
        observaciones=datos.observaciones,
        lineas=[ln.model_dump() for ln in datos.lineas],
    )
    if estado == "pendiente":
        response.status_code = 202
        return SolicitudOut.model_validate(res)
    entrada, movs = res
    return EntradaOut(id=entrada.id, bodega_id=entrada.bodega_id, total=entrada.total, movimientos=movs)


@router.post(
    "/ajustes",
    response_model=MovimientoOut | SolicitudOut,
    status_code=201,
    summary="Ajuste con motivo. Sobre el umbral: POS con autorizacion_id; backoffice 202 pendiente de aprobación",
)
def crear_ajuste(datos: AjusteIn, db: Db, actor: Gestiona, response: Response):
    estado, res = aprobaciones.ajuste(db, actor, **datos.model_dump())
    if estado == "pendiente":
        response.status_code = 202
        return SolicitudOut.model_validate(res)
    return res


# ------------------------------------------------------------------------------------ aprobaciones
@router.get(
    "/solicitudes",
    response_model=Pagina[SolicitudOut],
    summary="Solicitudes de entrada/ajuste (con inventario.aprobar ve todas; sin él, solo las propias)",
)
def listar_solicitudes(
    db: Db,
    actor: Ver,
    pag: Pag,
    estado: Literal["pendiente_aprobacion", "aprobada", "rechazada"] | None = None,
    tipo: Literal["entrada", "ajuste"] | None = None,
    sede_id: uuid.UUID | None = None,
):
    stmt = select(SolicitudInventario)
    if "inventario.aprobar" not in actor.permisos:
        stmt = stmt.where(SolicitudInventario.solicitada_por_id == actor.empleado.id)
    if estado:
        stmt = stmt.where(SolicitudInventario.estado == estado)
    if tipo:
        stmt = stmt.where(SolicitudInventario.tipo == tipo)
    if sede_id:
        stmt = stmt.where(SolicitudInventario.sede_id == sede_id)
    stmt = stmt.order_by(SolicitudInventario.created_at.desc(), SolicitudInventario.id)
    filas, total = paginar(db, stmt, pag)
    return Pagina(items=filas, total=total, limit=pag.limit, offset=pag.offset)


@router.get("/solicitudes/{solicitud_id}", response_model=SolicitudOut, summary="Detalle de una solicitud")
def obtener_solicitud(solicitud_id: uuid.UUID, db: Db, actor: Ver):
    s = db.get(SolicitudInventario, solicitud_id)
    if s is None or ("inventario.aprobar" not in actor.permisos and s.solicitada_por_id != actor.empleado.id):
        raise NoEncontrado("Solicitud no encontrada.")
    return s


def _resolver(db, actor, solicitud_id, aprobar: bool, motivo: str | None):
    s = db.get(SolicitudInventario, solicitud_id)
    if s is not None:
        sede_efectiva(db, actor, s.sede_id)  # el aprobador debe tener acceso a la sede de la solicitud
    return aprobaciones.resolver(db, actor, solicitud_id, aprobar=aprobar, motivo=motivo)


@router.post(
    "/solicitudes/{solicitud_id}/aprobar",
    response_model=SolicitudOut,
    summary="Aprueba y APLICA la solicitud (genera los movimientos). Otro empleado con inventario.aprobar",
)
def aprobar_solicitud(solicitud_id: uuid.UUID, db: Db, actor: Aprueba, datos: AprobacionIn | None = None):
    return _resolver(db, actor, solicitud_id, True, datos.motivo if datos else None)


@router.post(
    "/solicitudes/{solicitud_id}/rechazar",
    response_model=SolicitudOut,
    summary="Rechaza la solicitud (motivo obligatorio); no mueve nada",
)
def rechazar_solicitud(solicitud_id: uuid.UUID, datos: RechazoIn, db: Db, actor: Aprueba):
    return _resolver(db, actor, solicitud_id, False, datos.motivo)


@router.get(
    "/configuracion/{sede_id}",
    response_model=ConfigInventarioOut,
    summary="Umbral de aprobación y autoaprobación del propietario de la sede",
)
def leer_configuracion(sede_id: uuid.UUID, db: Db, _: Ver):
    return ConfigInventarioOut(
        sede_id=sede_id,
        umbral_aprobacion=configuracion.umbral_sede(db, sede_id),
        propietario_autoaprueba=configuracion.propietario_autoaprueba(db, sede_id),
    )


@router.put(
    "/configuracion/{sede_id}",
    response_model=ConfigInventarioOut,
    summary="Fija el umbral (COP) y si el propietario puede autoaprobarse en esa sede",
)
def fijar_configuracion(sede_id: uuid.UUID, datos: ConfigInventarioIn, db: Db, actor: Configura):
    from app.modules.auditoria.servicios import registrar_accion

    antes = {
        "umbral_aprobacion": str(configuracion.umbral_sede(db, sede_id)),
        "propietario_autoaprueba": configuracion.propietario_autoaprueba(db, sede_id),
    }
    if datos.umbral_aprobacion is not None:
        configuracion.escribir(db, sede_id, configuracion.CLAVE_UMBRAL, str(datos.umbral_aprobacion), actor.empleado.id)
    if datos.propietario_autoaprueba is not None:
        configuracion.escribir(
            db, sede_id, configuracion.CLAVE_AUTOAPROBACION, datos.propietario_autoaprueba, actor.empleado.id
        )
    despues = {
        "umbral_aprobacion": str(configuracion.umbral_sede(db, sede_id)),
        "propietario_autoaprueba": configuracion.propietario_autoaprueba(db, sede_id),
    }
    registrar_accion(
        db,
        "inventario.configuracion_cambiada",
        actor_id=actor.empleado.id,
        sede_id=sede_id,
        entidad_tipo="sede",
        entidad_id=sede_id,
        antes=antes,
        despues=despues,
    )
    return ConfigInventarioOut(sede_id=sede_id, **despues)


@router.post("/verificar", summary="Recalcula las existencias desde el kardex y reporta diferencias")
def verificar_existencias(db: Db, actor: Gestiona, reparar: bool = False, bodega_id: uuid.UUID | None = None):
    dif = verificar(db, reparar=reparar, actor_id=actor.empleado.id, bodega_id=bodega_id)
    return {"diferencias": len(dif), "reparadas": reparar and bool(dif), "detalle": [d.__dict__ for d in dif]}


# ------------------------------------------------------------------------------------ importación Excel
@router.get("/importaciones/plantilla", summary="Descarga la plantilla Excel (hojas 'productos' y 'compatibilidades')")
def descargar_plantilla(_: Importa) -> Response:
    return Response(
        importacion.plantilla(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plantilla_importacion.xlsx"'},
    )


@router.post(
    "/importaciones/validar",
    response_model=ValidacionOut,
    status_code=201,
    summary="Valida un Excel SIN escribir datos de negocio: reporte por fila y resumen",
)
async def validar_importacion(
    db: Db,
    actor: Importa,
    archivo: Annotated[UploadFile, File(description=".xlsx con la hoja 'productos' o 'compatibilidades'")],
):
    contenido = await archivo.read(importacion.MAX_BYTES + 1)
    return importacion.validar(db, archivo.filename or "importacion.xlsx", contenido, actor_id=actor.empleado.id)


@router.get("/importaciones/{importacion_id}", response_model=ValidacionOut, summary="Reporte de una importación")
def obtener_importacion(importacion_id: uuid.UUID, db: Db, _: Importa):
    imp = db.get(Importacion, importacion_id)
    if imp is None:
        raise NoEncontrado("Importación no encontrada.")
    return imp


@router.post(
    "/importaciones/{importacion_id}/confirmar",
    response_model=ImportacionOut,
    summary="Aplica la importación validada (una transacción, idempotente por SKU)",
)
def confirmar_importacion(importacion_id: uuid.UUID, db: Db, actor: Importa):
    return importacion.confirmar(db, importacion_id, actor_id=actor.empleado.id)
