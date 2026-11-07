"""Ventas POS (modelo §10): confirmación idempotente, ventas en espera, consultas y terceros rápidos.

Modelo de confirmación: el POS arma el carrito y envía la venta COMPLETA en una petición (`confirmar_venta`) con un id
UUIDv7 propio que es la clave de idempotencia (un `pg_advisory_xact_lock` por id serializa los reintentos en paralelo:
el segundo ve la venta del primero y la devuelve). El servidor recalcula TODO (precios vigentes de la sede, descuentos,
IVA con el algoritmo A de `core/dinero.py`, cambio y redondeo) y, en la MISMA transacción: toma el turno `FOR SHARE`,
asigna `numero_interno`, escribe el kardex (costo promedio como snapshot), abre la alerta de stock negativo si procede,
congela la venta (borrador -> confirmada) y publica los eventos del outbox. Sin commit aquí.

`ventas` no importa `fiscal` (que va después en la cadena): el documento fiscal lo crea el caso de uso
`app.aplicacion.ventas.confirmar_venta` justo después, en la misma transacción.

Vendedor y cajero (0010): `vendedor_id` es quien armó la venta; `cajero_id`, quien la cobró en su turno. Una venta en
espera se guarda desde cualquier sesión POS y se retoma en cualquier caja de la sede; quien la confirma es el cajero.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.base import uuid7
from app.core.dinero import Linea, Totales, calcular_linea, calcular_totales, r2, r4
from app.core.errores import Conflicto, NoEncontrado, PermisoDenegado, ReglaNegocio
from app.core.utiles import snapshot
from app.modules.auditoria.servicios import registrar_accion
from app.modules.cajas import turnos as svc_turnos
from app.modules.cajas.models import Caja
from app.modules.cajas.politicas_pos import aplicar_politica
from app.modules.cajas.turnos import TotalesTurno
from app.modules.catalogo.models import Impuesto, Precio, Producto
from app.modules.catalogo.servicios import lista_predeterminada
from app.modules.identidad.models import Tercero
from app.modules.identidad.servicios import roles_de
from app.modules.inventario import servicios as inv
from app.modules.inventario.models import Bodega, Existencia
from app.modules.organizacion import configuracion as cfg_sede
from app.modules.referencia.models import MedioPago
from app.modules.sync.servicios import publicar_evento
from app.modules.ventas.models import Devolucion, DevolucionPago, Venta, VentaItem, VentaPago

CONSUMIDOR_FINAL_ID = uuid.UUID("00000000-0000-7000-8000-000000000002")
CERO = Decimal("0.00")


@dataclass
class ResultadoVenta:
    venta: Venta
    creada: bool
    items: list[VentaItem]
    pagos: list[VentaPago]
    tercero: Tercero


def exigir_uuid7(valor: uuid.UUID, campo: str = "id") -> None:
    if valor.version != 7:
        raise ReglaNegocio(f"El {campo} debe ser un UUIDv7 generado por el POS.", code="id_invalido")


def bloquear_id(db: Session, valor: uuid.UUID) -> None:
    """Serializa las operaciones concurrentes con el mismo id (idempotencia en paralelo). Se libera al terminar la txn."""
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(valor), 0))))


# ======================================================================================= armado y cálculo
@dataclass
class LineaArmada:
    id: uuid.UUID
    numero: int
    producto: Producto
    impuesto: Impuesto
    cantidad: Decimal
    precio_lista: Decimal
    precio_unitario: Decimal
    calculo: Linea
    descuento_pct: Decimal  # efectivo (línea + global) sobre el bruto
    precio_manual: bool


@dataclass
class Armado:
    lineas: list[LineaArmada]
    max_descuento_pct: Decimal
    hay_precio_manual: bool


def _tercero_valido(db: Session, tercero_id: uuid.UUID | None) -> Tercero:
    t = db.get(Tercero, tercero_id or CONSUMIDOR_FINAL_ID)
    if t is None or t.fusionado_en_id is not None:
        raise ReglaNegocio("El cliente no existe o fue fusionado con otro.", code="tercero_invalido")
    return t


def _precios_vigentes(db: Session, producto_ids: set[uuid.UUID], sede_id: uuid.UUID, lista_id: uuid.UUID) -> dict:
    instante = db.scalar(select(func.clock_timestamp()))
    filas = db.scalars(
        select(Precio)
        .where(
            Precio.producto_id.in_(producto_ids),
            Precio.lista_precio_id == lista_id,
            Precio.vigente_desde <= instante,
            (Precio.vigente_hasta.is_(None)) | (Precio.vigente_hasta > instante),
            (Precio.sede_id == sede_id) | (Precio.sede_id.is_(None)),
        )
        .order_by(Precio.sede_id.is_(None), Precio.vigente_desde.desc())
    )
    out: dict[uuid.UUID, Decimal] = {}
    for p in filas:  # el primero por producto es el de la sede (si hay) y el más reciente
        out.setdefault(p.producto_id, p.precio)
    return out


def armar_lineas(db: Session, sede_id: uuid.UUID, datos, lista_id: uuid.UUID) -> Armado:
    """Recalcula cada línea con el precio vigente de la sede. El precio del cliente solo es informativo."""
    ids = {ln.producto_id for ln in datos.lineas}
    encontrados = {
        p.id: (p, i)
        for p, i in db.execute(
            select(Producto, Impuesto).join(Impuesto, Impuesto.id == Producto.impuesto_id).where(Producto.id.in_(ids))
        )
    }
    faltan = ids - set(encontrados)
    if faltan:
        raise ReglaNegocio(f"Productos inexistentes: {', '.join(sorted(map(str, faltan)))}.", code="producto_invalido")
    precios = _precios_vigentes(db, ids, sede_id, lista_id)
    lineas: list[LineaArmada] = []
    max_desc = Decimal("0")
    hay_manual = False
    g = Decimal(datos.descuento_global_pct)
    for n, ln in enumerate(datos.lineas, start=1):
        prod, imp = encontrados[ln.producto_id]
        if not prod.activo or not prod.vendible_pos:
            raise ReglaNegocio(f"El producto {prod.sku} no está disponible para la venta.", code="producto_no_vendible")
        lista = precios.get(prod.id)
        if lista is None:
            raise ReglaNegocio(f"El producto {prod.sku} no tiene precio vigente en la sede.", code="sin_precio")
        manual = ln.precio_manual is not None and r4(ln.precio_manual) != r4(lista)
        precio = r4(ln.precio_manual) if manual else lista
        hay_manual = hay_manual or manual
        bruto = r2(ln.cantidad * precio)
        d1 = r2(bruto * ln.descuento_pct / 100)
        d2 = r2((bruto - d1) * g / 100)
        desc = d1 + d2
        calc = calcular_linea(ln.cantidad, precio, imp.tarifa_pct, descuento_valor=desc)
        pct = (desc / bruto * 100).quantize(Decimal("0.0001")) if bruto > 0 else Decimal("0")
        max_desc = max(max_desc, pct)
        lineas.append(LineaArmada(uuid7(), n, prod, imp, ln.cantidad, lista, precio, calc, pct, manual))
    return Armado(lineas, max_desc, hay_manual)


def tope_descuento(db: Session, sede_id: uuid.UUID, empleado_id: uuid.UUID) -> Decimal:
    """Mayor tope de descuento (%) entre los roles del empleado, según configuracion_sede. Rol ausente = 0."""
    mapa = cfg_sede.obtener(db, sede_id, "ventas.descuento_max_pct_por_rol") or {}
    return max((Decimal(str(mapa.get(r.codigo, 0))) for r in roles_de(db, empleado_id)), default=Decimal("0"))


# ======================================================================================= pagos
@dataclass
class PagoResuelto:
    medio: str
    valor: Decimal
    recibido: Decimal | None
    cambio: Decimal
    entrada: object


def resolver_pagos(
    db: Session, pagos_in: list, total_sin_redondeo: Decimal, sede_id: uuid.UUID
) -> tuple[Decimal, list[PagoResuelto]]:
    """(redondeo, pagos). Efectivo con cambio calculado; el redondeo solo aplica si TODO se paga en efectivo."""
    medios = {
        m.codigo: m
        for m in db.scalars(select(MedioPago).where(MedioPago.codigo.in_({p.medio_pago_codigo for p in pagos_in})))
    }
    for p in pagos_in:
        if p.medio_pago_codigo not in medios:
            raise ReglaNegocio(f"Medio de pago '{p.medio_pago_codigo}' inexistente.", code="medio_invalido")
    efectivo = [p for p in pagos_in if medios[p.medio_pago_codigo].es_efectivo]
    otros = [p for p in pagos_in if not medios[p.medio_pago_codigo].es_efectivo]
    if len(efectivo) > 1:
        raise ReglaNegocio("Envíe un solo pago en efectivo (sume lo recibido).", code="pagos_efectivo_multiples")
    for p in otros:
        if p.valor is None:
            raise ReglaNegocio(f"El pago {p.medio_pago_codigo} necesita 'valor'.", code="pago_invalido")
        if medios[p.medio_pago_codigo].requiere_referencia and not (p.referencia or "").strip():
            raise ReglaNegocio(
                f"El medio {p.medio_pago_codigo} exige la referencia/aprobación.", code="referencia_requerida"
            )
    solo_efectivo = bool(efectivo) and not otros
    redondeo = CERO
    if solo_efectivo:
        a = int(cfg_sede.obtener(db, sede_id, "ventas.redondeo_efectivo") or 0)
        if a in (50, 100):
            unidad = Decimal(a)
            redondeo = (total_sin_redondeo / unidad).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            ) * unidad - total_sin_redondeo
    total = total_sin_redondeo + redondeo
    suma_otros = r2(sum((p.valor for p in otros), CERO))
    resto = total - suma_otros
    if resto < 0:
        raise ReglaNegocio("Los pagos exceden el total de la venta.", code="pagos_exceden_total")
    resueltos: list[PagoResuelto] = []
    for p in otros:
        resueltos.append(PagoResuelto(p.medio_pago_codigo, r2(p.valor), None, CERO, p))
    if efectivo:
        e = efectivo[0]
        if e.valor_recibido is None:
            raise ReglaNegocio("El pago en efectivo necesita 'valor_recibido'.", code="pago_invalido")
        if resto == 0:
            raise ReglaNegocio(
                "El efectivo sobra: la venta ya está pagada con los otros medios.", code="pagos_exceden_total"
            )
        recibido = r2(e.valor_recibido)
        if recibido < resto:
            raise ReglaNegocio("El efectivo recibido no alcanza para cubrir el saldo.", code="pagos_insuficientes")
        resueltos.append(PagoResuelto(e.medio_pago_codigo, resto, recibido, recibido - resto, e))
    elif resto != 0:
        raise ReglaNegocio("La suma de los pagos no cuadra con el total de la venta.", code="pagos_no_cuadran")
    return redondeo, resueltos


# ======================================================================================= confirmación
def _bodega_de_caja(db: Session, caja: Caja) -> Bodega:
    b = db.get(Bodega, caja.bodega_id)
    if b is None or not b.activo or not b.es_vendible:
        raise ReglaNegocio("La bodega de la caja no está disponible para vender.", code="bodega_invalida")
    return b


def confirmar_venta(db: Session, actor, datos) -> ResultadoVenta:
    """Confirma la venta completa. `actor` = Actor con sesión POS (`actor.pos`).

    Si el id corresponde a una venta ya confirmada devuelve esa (creada=False). El cajero es quien confirma; el
    vendedor es quien armó la venta en espera (si la hubo) o el propio cajero.
    """
    sesion = actor.pos
    exigir_uuid7(datos.id)
    bloquear_id(db, datos.id)
    previa = db.scalar(select(Venta).where(Venta.id == datos.id).execution_options(populate_existing=True))
    if previa is not None:
        if previa.sede_id != sesion.sede_id:
            raise Conflicto("Ese id de venta pertenece a otra sede.", code="id_en_uso")
        if previa.estado == "confirmada":
            if previa.caja_id != sesion.caja_id:
                raise Conflicto("Ese id de venta pertenece a otra caja.", code="id_en_uso")
            items, pagos_prev = lineas_y_pagos(db, previa.id)
            return ResultadoVenta(previa, False, items, pagos_prev, db.get(Tercero, previa.tercero_id))
        if previa.estado == "descartada":
            raise Conflicto("Esa venta en espera fue descartada; use un id nuevo.", code="venta_descartada")

    turno = svc_turnos.turno_abierto(db, sesion.caja_id, bloqueo="compartido")
    if turno is None:
        raise ReglaNegocio("La caja no tiene un turno abierto: ábralo para vender.", code="sin_turno_abierto")
    if turno.abierto_por_id != sesion.empleado.id:
        raise PermisoDenegado("El turno abierto pertenece a otro cajero.", code="turno_ajeno")
    caja = db.get(Caja, sesion.caja_id)
    bodega = _bodega_de_caja(db, caja)
    tercero = _tercero_valido(db, datos.tercero_id)
    lista = lista_predeterminada(db)
    armado = armar_lineas(db, sesion.sede_id, datos, lista.id)

    # --- precio manual y descuentos por encima del tope (autorización de OTRO empleado) ---
    sin_redondeo = calcular_totales([ln.calculo for ln in armado.lineas], 0)
    if sin_redondeo.total <= 0:
        raise ReglaNegocio("El total de la venta debe ser mayor que cero.", code="total_invalido")
    autorizado: dict[str, uuid.UUID] = {}
    autorizacion_descuento: uuid.UUID | None = None
    if armado.hay_precio_manual:
        r = aplicar_politica(
            db,
            actor,
            "cambiar_precio",
            None,
            autorizacion_id=datos.autorizacion_precio_id,
            entidad_tipo="venta",
            entidad_id=datos.id,
        )
        if r.autorizado_por_id:
            autorizado["precio"] = r.autorizado_por_id
    tope = tope_descuento(db, sesion.sede_id, sesion.empleado.id)
    if armado.max_descuento_pct > tope:
        r = aplicar_politica(
            db,
            actor,
            "descuento_mayor",
            sin_redondeo.descuento_total,
            autorizacion_id=datos.autorizacion_descuento_id,
            entidad_tipo="venta",
            entidad_id=datos.id,
            detalle={"descuento_pct": str(armado.max_descuento_pct), "tope_pct": str(tope)},
        )
        if r.autorizado_por_id:
            autorizado["descuento"] = r.autorizado_por_id
            autorizacion_descuento = r.autorizacion_id

    redondeo, pagos = resolver_pagos(db, datos.pagos, sin_redondeo.total, sesion.sede_id)
    tot = Totales(
        sin_redondeo.subtotal,
        sin_redondeo.descuento_total,
        sin_redondeo.impuesto_total,
        redondeo,
        sin_redondeo.total + redondeo,
    )

    # --- venta en borrador (reutiliza la ‘en espera’ si existía) ---
    if previa is not None:
        for it in db.scalars(select(VentaItem).where(VentaItem.venta_id == previa.id)):
            db.delete(it)
        db.flush()
        venta = previa
    else:
        venta = Venta(
            id=datos.id,
            canal="pos",
            sede_id=sesion.sede_id,
            caja_id=caja.id,
            created_by=sesion.empleado.id,
            tercero_id=tercero.id,
        )
        db.add(venta)
    venta.caja_id = caja.id
    venta.turno_id = turno.id
    venta.cajero_id = sesion.empleado.id
    venta.vendedor_id = venta.vendedor_id or sesion.empleado.id  # el de la venta en espera, o el propio cajero
    venta.tercero_id = tercero.id
    venta.lista_precio_id = lista.id
    venta.placa_vehiculo = datos.placa_vehiculo
    venta.notas = datos.notas
    venta.subtotal, venta.descuento_total, venta.impuesto_total = tot.subtotal, tot.descuento_total, tot.impuesto_total
    venta.redondeo, venta.total = tot.redondeo, tot.total
    db.flush()

    # --- kardex: orden estable por producto (evita bloqueos cruzados entre ventas concurrentes) ---
    costos: dict[uuid.UUID, tuple[Decimal, bool]] = {}
    inventariables = sorted(
        (x for x in armado.lineas if x.producto.es_inventariable), key=lambda x: (str(x.producto.id), x.numero)
    )
    existencias = inv.bloquear_existencias(db, bodega.id, [x.producto.id for x in inventariables])
    ocurrido = db.scalar(select(func.clock_timestamp()))  # una sola lectura del reloj de la BD para todo el kardex
    for ln in inventariables:
        ex = existencias[ln.producto.id]
        estimado = ex.cantidad < ln.cantidad or ex.costo_promedio == 0
        mov = inv.registrar_movimiento(
            db,
            actor_id=sesion.empleado.id,
            bodega_id=bodega.id,
            producto_id=ln.producto.id,
            tipo="venta",
            cantidad=ln.cantidad,
            costo_unitario=None,
            origen_tipo="venta",
            origen_id=venta.id,
            origen_linea_id=ln.id,
            costo_estimado=estimado,
            existencia=ex,
            ocurrido_at=ocurrido,
        )
        costos[ln.id] = (mov.costo_unitario, estimado)
        inv.alerta_stock_negativo(db, mov)

    items: list[VentaItem] = []
    for ln in armado.lineas:
        c = ln.calculo
        costo, estimado = costos.get(ln.id, (Decimal("0"), False))
        item = VentaItem(
            id=ln.id,
            venta_id=venta.id,
            linea=ln.numero,
            producto_id=ln.producto.id,
            bodega_id=bodega.id,
            sku=ln.producto.sku,
            descripcion=ln.producto.nombre,
            unidad_codigo=ln.producto.unidad_codigo,
            cantidad=ln.cantidad,
            precio_lista=ln.precio_lista,
            precio_unitario=ln.precio_unitario,
            precio_unitario_base=c.precio_unitario_base,
            descuento_pct=ln.descuento_pct,
            descuento_valor=c.descuento,
            impuesto_codigo=ln.impuesto.codigo,
            tributo_codigo=ln.impuesto.tributo_codigo,
            tarifa_pct=ln.impuesto.tarifa_pct,
            bruto_linea=c.bruto,
            total_linea=c.total,
            base_gravable=c.base,
            impuesto_valor=c.impuesto,
            costo_unitario=costo,
            costo_estimado=estimado,
            autorizacion_id=autorizacion_descuento if ln.descuento_pct > tope else None,
            created_by=sesion.empleado.id,
        )
        db.add(item)
        items.append(item)
    pagos_db: list[VentaPago] = []
    for p in pagos:
        e = p.entrada
        vp = VentaPago(
            venta_id=venta.id,
            medio_pago_codigo=p.medio,
            valor=p.valor,
            valor_recibido=p.recibido,
            cambio_devuelto=p.cambio,
            canal_pago=e.canal_pago,
            referencia=e.referencia,
            terminal=e.terminal,
            ultimos_digitos=e.ultimos_digitos,
            franquicia=e.franquicia,
            created_by=sesion.empleado.id,
        )
        db.add(vp)
        pagos_db.append(vp)
    db.flush()

    # --- congelar: número interno y estado ---
    venta.numero_interno = db.scalar(select(func.cajas.siguiente_numero_interno(caja.id)))
    venta.confirmada_at = db.scalar(select(func.clock_timestamp()))
    venta.estado = "confirmada"
    db.flush()

    publicar_evento(
        db,
        "venta",
        venta.id,
        "venta.confirmada",
        {
            **snapshot(venta),
            "lineas": [
                {
                    "producto_id": i.producto_id,
                    "cantidad": i.cantidad,
                    "precio_unitario": i.precio_unitario,
                    "total_linea": i.total_linea,
                }
                for i in items
            ],
            "pagos": [{"medio": p.medio_pago_codigo, "valor": p.valor} for p in pagos_db],
        },
        version=venta.version,
    )
    registrar_accion(
        db,
        "ventas.venta_confirmada",
        actor_id=sesion.empleado.id,
        sede_id=sesion.sede_id,
        dispositivo_id=sesion.dispositivo_id,
        entidad_tipo="venta",
        entidad_id=venta.id,
        despues={"numero_interno": venta.numero_interno, "total": str(venta.total), "lineas": len(items)},
        autorizado_por_id=autorizado.get("descuento") or autorizado.get("precio"),
    )
    return ResultadoVenta(venta, True, items, pagos_db, tercero)


# ======================================================================================= ventas en espera
def suspender_venta(db: Session, actor, datos) -> Venta:
    """Guarda (o reemplaza) un carrito como venta `borrador`: sin kardex, sin numeración, sin documento fiscal."""
    sesion = actor.pos
    vid = datos.id or uuid7()
    exigir_uuid7(vid)
    bloquear_id(db, vid)
    caja = db.get(Caja, sesion.caja_id)
    bodega = _bodega_de_caja(db, caja)
    tercero = _tercero_valido(db, datos.tercero_id)
    lista = lista_predeterminada(db)
    armado = armar_lineas(db, sesion.sede_id, datos, lista.id)
    tot = calcular_totales([ln.calculo for ln in armado.lineas], 0)
    previa = db.scalar(select(Venta).where(Venta.id == vid).execution_options(populate_existing=True))
    if previa is not None:
        if previa.estado != "borrador" or previa.sede_id != sesion.sede_id:
            raise Conflicto("Ese id ya corresponde a una venta que no está en espera.", code="id_en_uso")
        for it in db.scalars(select(VentaItem).where(VentaItem.venta_id == previa.id)):
            db.delete(it)
        db.flush()
        venta = previa
    else:
        # La espera no exige turno abierto: la arma un vendedor y la cobra cualquier caja de la sede.
        turno = svc_turnos.turno_abierto(db, sesion.caja_id)
        venta = Venta(
            id=vid,
            canal="pos",
            sede_id=sesion.sede_id,
            caja_id=caja.id,
            turno_id=turno.id if turno is not None else None,
            tercero_id=tercero.id,
            vendedor_id=sesion.empleado.id,
            created_by=sesion.empleado.id,
        )
        db.add(venta)
    venta.tercero_id = tercero.id
    venta.lista_precio_id = lista.id
    venta.placa_vehiculo = datos.placa_vehiculo
    venta.notas = datos.notas
    venta.subtotal, venta.descuento_total, venta.impuesto_total = tot.subtotal, tot.descuento_total, tot.impuesto_total
    venta.redondeo, venta.total = CERO, tot.total
    db.flush()
    costos = {
        e.producto_id: e.costo_promedio
        for e in db.scalars(
            select(Existencia).where(
                Existencia.bodega_id == bodega.id, Existencia.producto_id.in_([x.producto.id for x in armado.lineas])
            )
        )
    }
    for ln in armado.lineas:
        c = ln.calculo
        db.add(
            VentaItem(
                id=ln.id,
                venta_id=venta.id,
                linea=ln.numero,
                producto_id=ln.producto.id,
                bodega_id=bodega.id,
                sku=ln.producto.sku,
                descripcion=ln.producto.nombre,
                unidad_codigo=ln.producto.unidad_codigo,
                cantidad=ln.cantidad,
                precio_lista=ln.precio_lista,
                precio_unitario=ln.precio_unitario,
                precio_unitario_base=c.precio_unitario_base,
                descuento_pct=ln.descuento_pct,
                descuento_valor=c.descuento,
                impuesto_codigo=ln.impuesto.codigo,
                tributo_codigo=ln.impuesto.tributo_codigo,
                tarifa_pct=ln.impuesto.tarifa_pct,
                bruto_linea=c.bruto,
                total_linea=c.total,
                base_gravable=c.base,
                impuesto_valor=c.impuesto,
                costo_unitario=costos.get(ln.producto.id, Decimal("0")),
                created_by=sesion.empleado.id,
            )
        )
    db.flush()
    registrar_accion(
        db,
        "ventas.venta_suspendida",
        actor_id=sesion.empleado.id,
        sede_id=sesion.sede_id,
        dispositivo_id=sesion.dispositivo_id,
        entidad_tipo="venta",
        entidad_id=venta.id,
        despues={"total": str(venta.total), "lineas": len(armado.lineas)},
    )
    return venta


def descartar_vencidas(db: Session, sede_id: uuid.UUID) -> int:
    """Descarta las ventas en espera sin actividad por más de `ventas.espera_expira_horas`. Devuelve cuántas."""
    horas = int(cfg_sede.obtener(db, sede_id, "ventas.espera_expira_horas") or 24)
    limite = db.scalar(select(func.clock_timestamp())) - timedelta(hours=horas)
    vencidas = list(
        db.scalars(
            select(Venta)
            .where(Venta.sede_id == sede_id, Venta.estado == "borrador", Venta.updated_at < limite)
            .with_for_update(skip_locked=True)
        )
    )
    for v in vencidas:
        v.estado = "descartada"
        registrar_accion(
            db,
            "ventas.venta_espera_vencida",
            actor_tipo="sistema",
            sede_id=sede_id,
            entidad_tipo="venta",
            entidad_id=v.id,
        )
    if vencidas:
        db.flush()
    return len(vencidas)


def listar_espera(db: Session, sesion, *, solo_mias: bool = False) -> list[Venta]:
    """Ventas en espera de TODA la sede (se retoman en cualquier caja); `solo_mias` filtra por vendedor."""
    descartar_vencidas(db, sesion.sede_id)
    q = select(Venta).where(Venta.sede_id == sesion.sede_id, Venta.estado == "borrador")
    if solo_mias:
        q = q.where(Venta.vendedor_id == sesion.empleado.id)
    return list(db.scalars(q.order_by(Venta.updated_at.desc())))


def obtener_espera(db: Session, sesion, venta_id: uuid.UUID) -> Venta:
    descartar_vencidas(db, sesion.sede_id)
    v = db.get(Venta, venta_id)
    if v is None or v.sede_id != sesion.sede_id or v.estado != "borrador":
        raise NoEncontrado("No hay una venta en espera con ese id en esta sede.")
    return v


def descartar_espera(db: Session, sesion, venta_id: uuid.UUID) -> Venta:
    v = db.scalar(select(Venta).where(Venta.id == venta_id).with_for_update())
    if v is None or v.sede_id != sesion.sede_id or v.estado != "borrador":
        raise NoEncontrado("No hay una venta en espera con ese id en esta sede.")
    v.estado = "descartada"
    db.flush()
    registrar_accion(
        db,
        "ventas.venta_descartada",
        actor_id=sesion.empleado.id,
        sede_id=sesion.sede_id,
        dispositivo_id=sesion.dispositivo_id,
        entidad_tipo="venta",
        entidad_id=v.id,
    )
    return v


# ======================================================================================= consultas
def lineas_y_pagos(db: Session, venta_id: uuid.UUID) -> tuple[list[VentaItem], list[VentaPago]]:
    items = list(db.scalars(select(VentaItem).where(VentaItem.venta_id == venta_id).order_by(VentaItem.linea)))
    pagos = list(
        db.scalars(select(VentaPago).where(VentaPago.venta_id == venta_id).order_by(VentaPago.created_at, VentaPago.id))
    )
    return items, pagos


def obtener_venta(db: Session, venta_id: uuid.UUID, sede_id: uuid.UUID | None) -> Venta:
    v = db.get(Venta, venta_id)
    if v is None or (sede_id is not None and v.sede_id != sede_id):
        raise NoEncontrado("Venta no encontrada.")
    return v


def consulta_ventas(
    db: Session,
    sede_id: uuid.UUID,
    *,
    turno_id: uuid.UUID | None,
    q: str | None,
    caja_id: uuid.UUID | None = None,
    vendedor_id: uuid.UUID | None = None,
    cajero_id: uuid.UUID | None = None,
):
    """SELECT de ventas confirmadas (para paginar) con el nombre del cliente. `q`: nº interno exacto o texto del cliente."""
    stmt = (
        select(Venta, Tercero.nombre_completo.label("cliente"))
        .join(Tercero, Tercero.id == Venta.tercero_id)
        .where(Venta.sede_id == sede_id, Venta.estado == "confirmada")
        .order_by(Venta.confirmada_at.desc(), Venta.id.desc())
    )
    if turno_id is not None:
        stmt = stmt.where(Venta.turno_id == turno_id)
    if caja_id is not None:
        stmt = stmt.where(Venta.caja_id == caja_id)
    if vendedor_id is not None:
        stmt = stmt.where(Venta.vendedor_id == vendedor_id)
    if cajero_id is not None:
        stmt = stmt.where(Venta.cajero_id == cajero_id)
    if q and q.strip():
        q = q.strip()
        like = f"%{q}%"
        cond = [Tercero.nombre_completo.ilike(like), Tercero.numero_documento.like(f"{q}%")]
        if q.isdigit() and len(q) <= 12:
            cond.append(Venta.numero_interno == int(q))
        stmt = stmt.where(or_(*cond))
    return stmt


def totales_turno(db: Session, turno_id: uuid.UUID) -> TotalesTurno:
    """Lo que `ventas` aporta al cierre: pagos netos por medio, reembolsos por medio y conteos."""
    ventas = dict(
        db.execute(
            select(VentaPago.medio_pago_codigo, func.coalesce(func.sum(VentaPago.valor), 0))
            .join(Venta, Venta.id == VentaPago.venta_id)
            .where(Venta.turno_id == turno_id, Venta.estado == "confirmada")
            .group_by(VentaPago.medio_pago_codigo)
        ).all()
    )
    reemb = dict(
        db.execute(
            select(DevolucionPago.medio_pago_codigo, func.coalesce(func.sum(DevolucionPago.valor), 0))
            .join(Devolucion, Devolucion.id == DevolucionPago.devolucion_id)
            .where(Devolucion.turno_id == turno_id, Devolucion.estado == "confirmada")
            .group_by(DevolucionPago.medio_pago_codigo)
        ).all()
    )
    nv, tv = db.execute(
        select(func.count(), func.coalesce(func.sum(Venta.total), 0)).where(
            Venta.turno_id == turno_id, Venta.estado == "confirmada"
        )
    ).one()
    nd, td = db.execute(
        select(func.count(), func.coalesce(func.sum(Devolucion.total), 0)).where(
            Devolucion.turno_id == turno_id, Devolucion.estado == "confirmada"
        )
    ).one()
    return TotalesTurno(
        {k: Decimal(v) for k, v in ventas.items()},
        {k: Decimal(v) for k, v in reemb.items()},
        nv,
        Decimal(tv),
        nd,
        Decimal(td),
    )


# ======================================================================================= terceros rápidos
def _dv_nit(numero: str) -> int:
    from app.modules.organizacion.servicios import calcular_dv

    return calcular_dv(numero)


def buscar_terceros(db: Session, *, documento: str | None, q: str | None, limite: int = 20) -> list[Tercero]:
    stmt = select(Tercero).where(Tercero.fusionado_en_id.is_(None), Tercero.es_cliente.is_(True))
    if documento:
        stmt = stmt.where(Tercero.numero_documento == documento.strip())
    elif q and q.strip():
        stmt = stmt.where(
            or_(Tercero.nombre_completo.ilike(f"%{q.strip()}%"), Tercero.numero_documento.like(f"{q.strip()}%"))
        )
    else:
        raise ReglaNegocio("Indique 'documento' o 'q'.", code="busqueda_vacia")
    return list(db.scalars(stmt.order_by(Tercero.nombre_completo).limit(limite)))


def crear_tercero_rapido(db: Session, actor, datos) -> tuple[Tercero, bool]:
    """Alta rápida desde el POS con lo mínimo para facturar. Si el documento ya existe devuelve ese tercero (creado=False)."""
    existente = db.scalar(
        select(Tercero).where(
            Tercero.tipo_documento_codigo == datos.tipo_documento_codigo,
            Tercero.numero_documento == datos.numero_documento,
            Tercero.fusionado_en_id.is_(None),
        )
    )
    if existente is not None:
        return existente, False
    juridica = datos.tipo_documento_codigo == "31"
    if juridica:
        if not (datos.razon_social or "").strip():
            raise ReglaNegocio("Un NIT necesita razón social.", code="nombre_requerido")
        nombre = datos.razon_social.strip()
        campos = dict(tipo_persona_codigo="1", razon_social=nombre, dv=_dv_nit(datos.numero_documento))
    else:
        if not ((datos.primer_nombre or "").strip() and (datos.primer_apellido or "").strip()):
            raise ReglaNegocio("Indique primer nombre y primer apellido.", code="nombre_requerido")
        partes = [datos.primer_nombre, datos.segundo_nombre, datos.primer_apellido, datos.segundo_apellido]
        nombre = " ".join(p.strip() for p in partes if p and p.strip())
        campos = dict(
            tipo_persona_codigo="2",
            primer_nombre=datos.primer_nombre.strip(),
            segundo_nombre=datos.segundo_nombre,
            primer_apellido=datos.primer_apellido.strip(),
            segundo_apellido=datos.segundo_apellido,
        )
    t = Tercero(
        tipo_documento_codigo=datos.tipo_documento_codigo,
        numero_documento=datos.numero_documento,
        nombre_completo=nombre,
        email_facturacion=datos.email_facturacion,
        telefono=datos.telefono,
        direccion_fiscal=datos.direccion_fiscal,
        municipio_codigo=datos.municipio_codigo,
        regimen_codigo="49",
        created_by=actor.empleado.id,
        **campos,
    )
    db.add(t)
    db.flush()
    publicar_evento(
        db,
        "tercero",
        t.id,
        "tercero.creado",
        {k: v for k, v in snapshot(t).items() if k not in ("created_by",)},
        version=t.version,
    )
    registrar_accion(
        db,
        "ventas.tercero_creado",
        actor_id=actor.empleado.id,
        sede_id=actor.pos.sede_id if actor.pos else None,
        entidad_tipo="tercero",
        entidad_id=t.id,
        despues={"documento": f"{t.tipo_documento_codigo}:{t.numero_documento}"},
    )
    return t, True
