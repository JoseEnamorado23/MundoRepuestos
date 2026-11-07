"""Servicios de inventario: kardex (movimientos), existencias, entradas simples y ajustes.

Concurrencia: TODO movimiento bloquea la fila de existencias (`SELECT ... FOR UPDATE`) y actualiza la proyección en
la misma transacción; así la secuencia por (bodega, producto) y el saldo no tienen carreras. Sin commit aquí.

Costo promedio ponderado (CPP), en cada entrada con saldo previo `S` (si S <= 0 el nuevo costo es el de la entrada):

    CPP_nuevo = (S x CPP_ant + Q x C_entrada) / (S + Q)         [redondeado a 4 decimales, mitad hacia arriba]

Las salidas salen al CPP vigente y no lo modifican. Ver docs/base-de-datos/modelo.md (D-43).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.base import uuid7
from app.core.errores import Conflicto, NoEncontrado, PermisoDenegado, ReglaNegocio
from app.modules.auditoria.servicios import registrar_accion
from app.modules.catalogo.models import Producto
from app.modules.catalogo.utiles import snapshot
from app.modules.identidad.models import Autorizacion, Tercero
from app.modules.inventario.configuracion import umbral_sede
from app.modules.inventario.models import (
    Bodega,
    EntradaMercancia,
    EntradaMercanciaLinea,
    Existencia,
    MovimientoInventario,
    ProductoUbicacion,
    Ubicacion,
)
from app.modules.organizacion.models import Sede
from app.modules.sync.servicios import publicar_evento

CUATRO = Decimal("0.0001")
ENTRADAS = {"saldo_inicial", "entrada_compra", "devolucion_venta", "ajuste_positivo", "traslado_entrada"}
ORIGEN_DE_TIPO = {
    "saldo_inicial": "saldo_inicial",
    "entrada_compra": "recepcion",
    "ajuste_positivo": "ajuste",
    "ajuste_negativo": "ajuste",
}


def _q4(x: Decimal) -> Decimal:
    return x.quantize(CUATRO, rounding=ROUND_HALF_UP)


def _evento(db: Session, agregado: str, obj, tipo: str) -> None:
    publicar_evento(db, agregado, obj.id, f"{agregado}.{tipo}", snapshot(obj), version=getattr(obj, "version", 1))


# ======================================================================================= núcleo del kardex
def bloquear_existencia(db: Session, bodega_id: uuid.UUID, producto_id: uuid.UUID) -> Existencia:
    """Crea la fila si no existe y la devuelve BLOQUEADA (FOR UPDATE) con valores frescos."""
    db.execute(pg_insert(Existencia).values(bodega_id=bodega_id, producto_id=producto_id).on_conflict_do_nothing())
    return db.scalars(
        select(Existencia)
        .where(Existencia.bodega_id == bodega_id, Existencia.producto_id == producto_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def registrar_movimiento(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    bodega_id: uuid.UUID,
    producto_id: uuid.UUID,
    tipo: str,
    cantidad: Decimal,
    costo_unitario: Decimal | None,
    origen_tipo: str,
    origen_id: uuid.UUID,
    origen_linea_id: uuid.UUID,
    ocurrido_at: datetime | None = None,
    costo_estimado: bool = False,
) -> MovimientoInventario:
    """Registra UN movimiento. `cantidad` es la magnitud (> 0); el signo lo da el tipo."""
    if cantidad <= 0:
        raise ReglaNegocio("La cantidad debe ser mayor que cero.", code="cantidad_invalida")
    ex = bloquear_existencia(db, bodega_id, producto_id)
    entrada = tipo in ENTRADAS
    saldo_prev = ex.cantidad
    cpp_prev = ex.costo_promedio
    if entrada:
        costo = _q4(costo_unitario if costo_unitario is not None else cpp_prev)
        if costo < 0:
            raise ReglaNegocio("El costo no puede ser negativo.", code="costo_invalido")
        nuevo_saldo = saldo_prev + cantidad
        if saldo_prev > 0:
            cpp = _q4((saldo_prev * cpp_prev + cantidad * costo) / nuevo_saldo)
        else:
            cpp = costo
        signed = cantidad
        if tipo in ("entrada_compra", "saldo_inicial"):
            ex.ultimo_costo = costo
    else:
        costo = cpp_prev  # las salidas valoran al costo promedio vigente
        nuevo_saldo = saldo_prev - cantidad
        cpp = cpp_prev
        signed = -cantidad
    ex.cantidad, ex.costo_promedio = nuevo_saldo, cpp
    ex.ultima_secuencia = ex.ultima_secuencia + 1
    mov = MovimientoInventario(
        bodega_id=bodega_id,
        producto_id=producto_id,
        secuencia=ex.ultima_secuencia,
        tipo=tipo,
        cantidad=signed,
        costo_unitario=costo,
        costo_estimado=costo_estimado,
        saldo_cantidad=nuevo_saldo,
        costo_promedio_resultante=cpp,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        origen_linea_id=origen_linea_id,
        ocurrido_at=ocurrido_at or func.clock_timestamp(),
        created_by=actor_id,
    )
    db.add(mov)
    db.flush()  # uq_movimientos_inventario_idempotencia -> 409 si el origen ya se aplicó
    publicar_evento(
        db,
        "movimiento_inventario",
        mov.id,
        "movimiento_inventario.registrado",
        {**snapshot(mov), "existencia_resultante": nuevo_saldo},
    )
    return mov


# ======================================================================================= bodegas y ubicaciones
def crear_bodega(db: Session, actor_id: uuid.UUID, datos: dict) -> Bodega:
    if db.get(Sede, datos["sede_id"]) is None:
        raise ReglaNegocio("La sede no existe.", code="sede_invalida")
    b = Bodega(created_by=actor_id, **datos)
    db.add(b)
    db.flush()  # uq_bodegas_sede_codigo -> 409
    _evento(db, "bodega", b, "creada")
    return b


def actualizar_bodega(db: Session, actor_id: uuid.UUID, bodega_id: uuid.UUID, datos: dict) -> Bodega:
    b = db.get(Bodega, bodega_id)
    if b is None:
        raise NoEncontrado("Bodega no encontrada.")
    for k in ("nombre", "es_vendible", "activo"):
        if k in datos:
            setattr(b, k, datos[k])
    db.flush()
    _evento(db, "bodega", b, "actualizada")
    return b


def crear_ubicacion(db: Session, actor_id: uuid.UUID, datos: dict) -> Ubicacion:
    if db.get(Bodega, datos["bodega_id"]) is None:
        raise ReglaNegocio("La bodega no existe.", code="bodega_invalida")
    u = Ubicacion(created_by=actor_id, **datos)
    db.add(u)
    db.flush()
    _evento(db, "ubicacion", u, "creada")
    return u


def actualizar_ubicacion(db: Session, actor_id: uuid.UUID, ubicacion_id: uuid.UUID, datos: dict) -> Ubicacion:
    u = db.get(Ubicacion, ubicacion_id)
    if u is None:
        raise NoEncontrado("Ubicación no encontrada.")
    for k in ("pasillo", "estante", "nivel", "descripcion", "activo"):
        if k in datos:
            setattr(u, k, datos[k])
    db.flush()
    _evento(db, "ubicacion", u, "actualizada")
    return u


def asignar_ubicacion_producto(
    db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, ubicacion_id: uuid.UUID, es_principal: bool
) -> ProductoUbicacion:
    if db.get(Producto, producto_id) is None:
        raise NoEncontrado("Producto no encontrado.")
    u = db.get(Ubicacion, ubicacion_id)
    if u is None or not u.activo:
        raise ReglaNegocio("La ubicación no existe o está inactiva.", code="ubicacion_invalida")
    pu = db.get(ProductoUbicacion, (producto_id, ubicacion_id))
    if pu is None:
        pu = ProductoUbicacion(producto_id=producto_id, ubicacion_id=ubicacion_id, es_principal=es_principal)
        db.add(pu)
    else:
        pu.es_principal = es_principal
    db.flush()
    publicar_evento(
        db,
        "producto_ubicacion",
        producto_id,
        "producto_ubicacion.asignada",
        {"producto_id": producto_id, "ubicacion_id": ubicacion_id, "es_principal": es_principal},
    )
    return pu


def quitar_ubicacion_producto(
    db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, ubicacion_id: uuid.UUID
) -> None:
    pu = db.get(ProductoUbicacion, (producto_id, ubicacion_id))
    if pu is None:
        raise NoEncontrado("El producto no tiene asignada esa ubicación.")
    db.delete(pu)
    db.flush()
    publicar_evento(
        db,
        "producto_ubicacion",
        producto_id,
        "producto_ubicacion.retirada",
        {"producto_id": producto_id, "ubicacion_id": ubicacion_id},
    )


# ======================================================================================= entrada simple
def registrar_entrada(
    db: Session,
    actor_id: uuid.UUID,
    *,
    bodega_id: uuid.UUID,
    tercero_id: uuid.UUID | None,
    numero_factura: str | None,
    lineas: list[dict],
    observaciones: str | None = None,
) -> tuple[EntradaMercancia, list[MovimientoInventario]]:
    """Entrada de mercancía (compra simple): un movimiento `entrada_compra` por línea y recálculo del CPP."""
    bodega = db.get(Bodega, bodega_id)
    if bodega is None or not bodega.activo:
        raise ReglaNegocio("La bodega no existe o está inactiva.", code="bodega_invalida")
    if tercero_id is not None and db.get(Tercero, tercero_id) is None:
        raise ReglaNegocio("El proveedor (tercero) no existe.", code="tercero_invalido")
    if not lineas:
        raise ReglaNegocio("La entrada necesita al menos una línea.", code="sin_lineas")
    if tercero_id is not None and numero_factura:
        previa = db.scalar(
            select(EntradaMercancia.id).where(
                EntradaMercancia.tercero_id == tercero_id, EntradaMercancia.numero_factura == numero_factura
            )
        )
        if previa is not None:
            raise Conflicto(
                f"La factura {numero_factura} de ese proveedor ya fue registrada.", code="factura_duplicada"
            )
    ids = {ln["producto_id"] for ln in lineas}
    encontrados = {p.id: p for p in db.scalars(select(Producto).where(Producto.id.in_(ids)))}
    faltan = ids - set(encontrados)
    if faltan:
        raise ReglaNegocio(
            f"Productos inexistentes: {', '.join(sorted(str(i) for i in faltan))}.", code="producto_invalido"
        )
    no_inv = [p.sku for p in encontrados.values() if not p.es_inventariable]
    if no_inv:
        raise ReglaNegocio(f"Productos no inventariables: {', '.join(no_inv)}.", code="producto_no_inventariable")

    total = sum((_q4(ln["cantidad"] * ln["costo_unitario"]) for ln in lineas), Decimal(0)).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )
    entrada = EntradaMercancia(
        bodega_id=bodega_id,
        tercero_id=tercero_id,
        numero_factura=numero_factura,
        observaciones=observaciones,
        total=total,
        created_by=actor_id,
    )
    db.add(entrada)
    db.flush()
    movs: list[MovimientoInventario] = []
    # orden estable por producto: dos entradas simultáneas con los mismos productos no se bloquean en cruz
    for ln in sorted(lineas, key=lambda x: str(x["producto_id"])):
        linea = EntradaMercanciaLinea(
            entrada_id=entrada.id,
            producto_id=ln["producto_id"],
            cantidad=ln["cantidad"],
            costo_unitario=ln["costo_unitario"],
            created_by=actor_id,
        )
        db.add(linea)
        db.flush()
        movs.append(
            registrar_movimiento(
                db,
                actor_id=actor_id,
                bodega_id=bodega_id,
                producto_id=ln["producto_id"],
                tipo="entrada_compra",
                cantidad=ln["cantidad"],
                costo_unitario=ln["costo_unitario"],
                origen_tipo="recepcion",
                origen_id=entrada.id,
                origen_linea_id=linea.id,
            )
        )
    publicar_evento(
        db,
        "entrada_mercancia",
        entrada.id,
        "entrada_mercancia.registrada",
        {
            **snapshot(entrada),
            "lineas": [
                {"producto_id": ln["producto_id"], "cantidad": ln["cantidad"], "costo_unitario": ln["costo_unitario"]}
                for ln in lineas
            ],
        },
    )
    registrar_accion(
        db,
        "inventario.entrada_registrada",
        actor_id=actor_id,
        sede_id=bodega.sede_id,
        entidad_tipo="entrada_mercancia",
        entidad_id=entrada.id,
        despues={
            "total": str(total),
            "lineas": len(lineas),
            "factura": numero_factura,
            "tercero_id": str(tercero_id) if tercero_id else None,
        },
    )
    return entrada, movs


# ======================================================================================= ajustes
def valor_ajuste(cantidad: Decimal, costo: Decimal) -> Decimal:
    return (abs(cantidad) * costo).quantize(Decimal("0.01"), ROUND_HALF_UP)


def validar_ajuste(
    db: Session, bodega_id: uuid.UUID, producto_id: uuid.UUID, cantidad: Decimal, motivo: str | None
) -> Bodega:
    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        raise ReglaNegocio("El motivo del ajuste es obligatorio (mínimo 5 caracteres).", code="motivo_obligatorio")
    if cantidad == 0:
        raise ReglaNegocio("La cantidad del ajuste no puede ser cero.", code="cantidad_invalida")
    bodega = db.get(Bodega, bodega_id)
    if bodega is None or not bodega.activo:
        raise ReglaNegocio("La bodega no existe o está inactiva.", code="bodega_invalida")
    p = db.get(Producto, producto_id)
    if p is None:
        raise NoEncontrado("Producto no encontrado.")
    if not p.es_inventariable:
        raise ReglaNegocio("El producto no es inventariable.", code="producto_no_inventariable")
    return bodega


def registrar_ajuste(
    db: Session,
    actor,
    *,
    bodega_id: uuid.UUID,
    producto_id: uuid.UUID,
    cantidad: Decimal,
    motivo: str,
    costo_unitario: Decimal | None = None,
    autorizacion_id: uuid.UUID | None = None,
    aprobado_por_id: uuid.UUID | None = None,
) -> MovimientoInventario:
    """Ajuste positivo (`cantidad` > 0) o negativo (< 0) con motivo obligatorio.

    Si |cantidad| x costo supera el umbral de la sede (`configuracion_sede` o `AJUSTE_UMBRAL_VALOR`):
    * con sesión POS: exige `autorizacion_id` de un supervisor DISTINTO (acción `inventario.ajustar`, un solo uso);
    * en backoffice NO se llega aquí: `aprobaciones.ajustar` crea una solicitud `pendiente_aprobacion` y, al aprobarla
      otro empleado, vuelve a llamar con `aprobado_por_id` (ya validado) para ejecutar el movimiento.
    `actor` es el `Actor` de la API.
    """
    bodega = validar_ajuste(db, bodega_id, producto_id, cantidad, motivo)
    motivo = motivo.strip()

    positivo = cantidad > 0
    ex = bloquear_existencia(db, bodega_id, producto_id)  # el costo de referencia se lee con la fila bloqueada
    costo_ref = costo_unitario if (positivo and costo_unitario is not None) else ex.costo_promedio
    if positivo and costo_ref == 0 and costo_unitario is None:
        raise ReglaNegocio(
            "No hay costo promedio para valorar el ajuste positivo; indique `costo_unitario`.", code="costo_requerido"
        )
    valor = valor_ajuste(cantidad, costo_ref)
    umbral = umbral_sede(db, bodega.sede_id)
    autorizado_por = aprobado_por_id
    if aprobado_por_id is None and valor > umbral:
        if actor.pos is None:
            raise ReglaNegocio(
                f"El ajuste vale {valor} COP y supera el umbral de {umbral}: debe pasar por aprobación "
                "(use aprobaciones.ajustar).",
                code="aprobacion_requerida",
            )
        if autorizacion_id is None:
            raise ReglaNegocio(
                f"El ajuste vale {valor} COP y supera el umbral de {umbral}: requiere autorizacion_id de un supervisor "
                "(POST /pos/autorizaciones con accion 'inventario.ajustar').",
                code="autorizacion_requerida",
                valor=str(valor),
                umbral=str(umbral),
            )
        from app.modules.cajas.servicios import consumir_autorizacion

        a = db.get(Autorizacion, autorizacion_id)
        if a is None:
            raise NoEncontrado("Autorización no encontrada.", code="autorizacion_no_encontrada")
        if a.autorizado_por_id == actor.empleado.id:
            raise PermisoDenegado(
                "Una autorización no puede ser del mismo empleado que ejecuta.", code="autoautorizacion"
            )
        consumir_autorizacion(db, autorizacion_id, accion="inventario.ajustar", sesion=actor.pos)
        autorizado_por = a.autorizado_por_id

    ajuste_id = uuid7()
    mov = registrar_movimiento(
        db,
        actor_id=actor.empleado.id,
        bodega_id=bodega_id,
        producto_id=producto_id,
        tipo="ajuste_positivo" if positivo else "ajuste_negativo",
        cantidad=abs(cantidad),
        costo_unitario=costo_ref if positivo else None,
        origen_tipo="ajuste",
        origen_id=ajuste_id,
        origen_linea_id=ajuste_id,
    )
    registrar_accion(
        db,
        "inventario.ajuste_registrado",
        actor_id=actor.empleado.id,
        sede_id=bodega.sede_id,
        entidad_tipo="producto",
        entidad_id=producto_id,
        antes={"existencia": str(mov.saldo_cantidad - mov.cantidad)},
        despues={"existencia": str(mov.saldo_cantidad), "cantidad": str(mov.cantidad), "valor": str(valor)},
        motivo=motivo,
        autorizado_por_id=autorizado_por,
        autorizacion_id=autorizacion_id if autorizacion_id and autorizado_por else None,
    )
    return mov


def stock_inicial(
    db: Session,
    actor_id: uuid.UUID | None,
    *,
    bodega_id: uuid.UUID,
    producto_id: uuid.UUID,
    cantidad: Decimal,
    costo: Decimal,
) -> MovimientoInventario | None:
    """Stock inicial: UNA sola vez por (producto, bodega). La idempotencia la da (origen_tipo, origen_linea_id=producto,
    tipo, bodega) del kardex: si ya existe devuelve None sin tocar nada."""
    ya = db.scalar(
        select(MovimientoInventario.id).where(
            MovimientoInventario.bodega_id == bodega_id,
            MovimientoInventario.producto_id == producto_id,
            MovimientoInventario.tipo == "saldo_inicial",
        )
    )
    if ya is not None:
        return None
    return registrar_movimiento(
        db,
        actor_id=actor_id,
        bodega_id=bodega_id,
        producto_id=producto_id,
        tipo="saldo_inicial",
        cantidad=cantidad,
        costo_unitario=costo,
        origen_tipo="saldo_inicial",
        origen_id=bodega_id,
        origen_linea_id=producto_id,
    )
