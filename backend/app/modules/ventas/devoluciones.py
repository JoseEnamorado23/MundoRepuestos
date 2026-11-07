"""Devoluciones de venta (modelo §10.5-10.7). No existe «anular venta»: toda reversión es una devolución + nota crédito.

* Siempre referencian la venta y sus ítems; `cantidad` ≤ vendido − ya devuelto (las filas de los ítems se bloquean
  `FOR UPDATE`: dos devoluciones simultáneas no pueden exceder lo vendido).
* Montos proporcionales al ítem original (mismo precio, tarifa, descuento y costo); la última devolución de una línea
  toma el resto, así la suma de las devoluciones cuadra exactamente con la línea vendida.
* Destino físico: bodega de la venta (`vendible`) o bodega de averías (no vendible). Si el motivo no reintegra stock
  (p. ej. `cambio_de_documento`) no hay movimiento de kardex.
* Reembolso en efectivo desde el turno ACTUAL (entra en su arqueo) o por el/los medio(s) de la venta original. La
  devolución puede hacerse en otro turno y otra caja distinta a la de la venta (de la misma sede).
* En la misma transacción: kardex `devolucion_venta` y evento en el outbox. La nota crédito `pendiente_envio` la crea el
  caso de uso (app/aplicacion) con el resultado de `confirmar_devolucion`: este módulo no importa `fiscal`.
* Política `devolucion` (0010): libre hasta el umbral de la sede; por encima, autorización de OTRO empleado (PIN o
  aprobación remota). Un reembolso en efectivo mayor al efectivo esperado del turno se BLOQUEA siempre.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.base import uuid7
from app.core.dinero import r2
from app.core.errores import Conflicto, NoEncontrado, PermisoDenegado, ReglaNegocio
from app.core.utiles import snapshot
from app.modules.auditoria.servicios import registrar_accion
from app.modules.cajas import turnos as svc_turnos
from app.modules.cajas.politicas_pos import aplicar_politica
from app.modules.catalogo.models import Producto
from app.modules.inventario import servicios as inv
from app.modules.inventario.models import Bodega
from app.modules.referencia.models import MedioPago
from app.modules.sync.servicios import publicar_evento
from app.modules.ventas.models import (
    Devolucion,
    DevolucionItem,
    DevolucionPago,
    MotivoDevolucion,
    Venta,
    VentaItem,
    VentaPago,
)
from app.modules.ventas.servicios import bloquear_id, exigir_uuid7, totales_turno

CERO = Decimal("0.00")


@dataclass
class ResultadoDevolucion:
    devolucion: Devolucion
    creada: bool
    venta: Venta | None = None
    pares: list[tuple[DevolucionItem, VentaItem]] | None = None
    pagos: list[DevolucionPago] | None = None
    anulacion_total: bool = False
    exenta_de_autorizacion: bool = False


def _devuelto_previo(db: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Decimal]]:
    filas = db.execute(
        select(
            DevolucionItem.venta_item_id,
            func.coalesce(func.sum(DevolucionItem.cantidad), 0),
            func.coalesce(func.sum(DevolucionItem.total_linea), 0),
            func.coalesce(func.sum(DevolucionItem.base_gravable), 0),
            func.coalesce(func.sum(DevolucionItem.descuento_valor), 0),
        )
        .join(Devolucion, Devolucion.id == DevolucionItem.devolucion_id)
        .where(DevolucionItem.venta_item_id.in_(item_ids), Devolucion.estado == "confirmada")
        .group_by(DevolucionItem.venta_item_id)
    ).all()
    return {
        i: {"q": Decimal(q), "total": Decimal(t), "base": Decimal(b), "desc": Decimal(d)} for i, q, t, b, d in filas
    }


def _bodega_averias(db: Session, sede_id: uuid.UUID) -> Bodega:
    b = db.scalar(select(Bodega).where(Bodega.sede_id == sede_id, Bodega.tipo == "averias", Bodega.activo.is_(True)))
    if b is None:
        raise ReglaNegocio(
            "La sede no tiene una bodega de averías activa: créela (POST /inventario/bodegas con tipo 'averias').",
            code="sin_bodega_averias",
        )
    return b


def _repartir_reembolso(
    db: Session, venta: Venta, total: Decimal, modo: str, referencia: str | None
) -> list[tuple[str, Decimal, str | None]]:
    medios = {m.codigo: m for m in db.scalars(select(MedioPago))}
    if modo == "efectivo":
        efectivo = next((c for c, m in medios.items() if m.es_efectivo), None)
        if efectivo is None:
            raise ReglaNegocio("No hay un medio de pago de tipo efectivo configurado.", code="sin_medio_efectivo")
        return [(efectivo, total, None)]
    # por el/los medio(s) originales, descontando lo ya reembolsado por cada uno
    previos = dict(
        db.execute(
            select(DevolucionPago.medio_pago_codigo, func.coalesce(func.sum(DevolucionPago.valor), 0))
            .join(Devolucion, Devolucion.id == DevolucionPago.devolucion_id)
            .where(Devolucion.venta_id == venta.id, Devolucion.estado == "confirmada")
            .group_by(DevolucionPago.medio_pago_codigo)
        ).all()
    )
    disponible: dict[str, Decimal] = defaultdict(lambda: CERO)
    orden: list[str] = []
    for p in db.scalars(
        select(VentaPago).where(VentaPago.venta_id == venta.id).order_by(VentaPago.created_at, VentaPago.id)
    ):
        if p.medio_pago_codigo not in orden:
            orden.append(p.medio_pago_codigo)
        disponible[p.medio_pago_codigo] += p.valor
    reparto: list[tuple[str, Decimal, str | None]] = []
    resto = total
    for m in orden:
        libre = disponible[m] - Decimal(previos.get(m, 0))
        if libre <= 0 or resto <= 0:
            continue
        monto = min(libre, resto)
        if not medios[m].es_efectivo and medios[m].requiere_referencia and not (referencia or "").strip():
            raise ReglaNegocio(
                f"El reembolso por el medio {m} exige 'referencia_reembolso' (comprobante).",
                code="referencia_requerida",
            )
        reparto.append((m, monto, None if medios[m].es_efectivo else referencia))
        resto -= monto
    if resto > 0:
        raise ReglaNegocio(
            "El reembolso excede lo pagado por los medios originales de la venta.", code="reembolso_excede_pagos"
        )
    return reparto


def _exigir_efectivo_suficiente(db: Session, turno, reparto: list[tuple[str, Decimal, str | None]]) -> None:
    """Un reembolso en efectivo no puede superar el efectivo esperado del turno actual (no configurable)."""
    efectivo = next(
        (c for c in (m for m, _, _ in reparto) if db.get(MedioPago, c).es_efectivo),
        None,
    )
    if efectivo is None:
        return
    pedido = sum((v for m, v, _ in reparto if db.get(MedioPago, m).es_efectivo), CERO)
    # serializa los reembolsos en efectivo del mismo turno: dos a la vez no pueden gastar el mismo efectivo
    bloquear_id(db, uuid.uuid5(uuid.NAMESPACE_OID, f"reembolso-efectivo:{turno.id}"))
    esperado, _ = svc_turnos.calcular_esperado(db, turno, totales_turno(db, turno.id))
    disponible = esperado[efectivo]
    if pedido > disponible:
        raise ReglaNegocio(
            f"El reembolso en efectivo ({pedido}) supera el efectivo disponible en el turno ({disponible}). "
            "Ingrese efectivo a la caja (movimiento de ingreso) o reembolse por el medio de pago original.",
            code="reembolso_excede_efectivo",
            solicitado=str(pedido),
            disponible=str(disponible),
        )


def confirmar_devolucion(db: Session, actor, datos) -> ResultadoDevolucion:
    sesion = actor.pos
    dev_id = datos.id or uuid7()
    exigir_uuid7(dev_id)
    bloquear_id(db, dev_id)
    previa = db.scalar(select(Devolucion).where(Devolucion.id == dev_id).execution_options(populate_existing=True))
    if previa is not None:
        if previa.venta_id != datos.venta_id or previa.sede_id != sesion.sede_id:
            raise Conflicto("Ese id de devolución ya existe con otros datos.", code="id_en_uso")
        return ResultadoDevolucion(previa, False)

    venta = db.get(Venta, datos.venta_id)
    if venta is None or venta.sede_id != sesion.sede_id or venta.canal != "pos":
        raise NoEncontrado("Venta no encontrada en esta sede.")
    if venta.estado != "confirmada":
        raise ReglaNegocio("Solo se devuelven ventas confirmadas.", code="venta_no_confirmada")
    turno = svc_turnos.turno_abierto(db, sesion.caja_id, bloqueo="compartido")
    if turno is None:
        raise ReglaNegocio("Abra un turno: el reembolso sale del turno actual.", code="sin_turno_abierto")
    if turno.abierto_por_id != sesion.empleado.id:
        raise PermisoDenegado("El turno abierto pertenece a otro cajero.", code="turno_ajeno")

    motivo = db.scalar(
        select(MotivoDevolucion).where(MotivoDevolucion.codigo == datos.motivo_codigo, MotivoDevolucion.activo)
    )
    if motivo is None:
        raise ReglaNegocio(f"Motivo '{datos.motivo_codigo}' inexistente o inactivo.", code="motivo_invalido")

    ids = [it.venta_item_id for it in datos.items]
    if len(set(ids)) != len(ids):
        raise ReglaNegocio("Un ítem de la venta solo puede aparecer una vez por devolución.", code="item_duplicado")
    originales = {
        i.id: i
        for i in db.scalars(
            select(VentaItem)
            .where(VentaItem.id.in_(ids), VentaItem.venta_id == venta.id)
            .order_by(VentaItem.id)
            .with_for_update()
        )
    }
    if set(ids) - set(originales):
        raise ReglaNegocio("Algún ítem no pertenece a la venta.", code="item_invalido")
    previo = _devuelto_previo(db, ids)

    # --- cantidades y montos proporcionales ---
    calculo: list[dict] = []
    for it in datos.items:
        vi = originales[it.venta_item_id]
        p = previo.get(vi.id, {"q": Decimal(0), "total": CERO, "base": CERO, "desc": CERO})
        if it.cantidad > vi.cantidad - p["q"]:
            raise ReglaNegocio(
                f"{vi.sku}: se vendieron {vi.cantidad} y ya se devolvieron {p['q']}; no se pueden devolver {it.cantidad}.",
                code="cantidad_excede_vendida",
            )
        if p["q"] + it.cantidad == vi.cantidad:  # última devolución de la línea: toma el resto exacto
            total, base, desc = (
                vi.total_linea - p["total"],
                vi.base_gravable - p["base"],
                vi.descuento_valor - p["desc"],
            )
        else:
            f = it.cantidad / vi.cantidad
            total, base, desc = r2(vi.total_linea * f), r2(vi.base_gravable * f), r2(vi.descuento_valor * f)
        calculo.append(dict(it=it, vi=vi, total=total, base=base, desc=desc))

    reintegra_motivo = motivo.reintegra_stock_por_defecto
    averias = (
        _bodega_averias(db, sesion.sede_id)
        if reintegra_motivo and any(c["it"].destino == "averias" for c in calculo)
        else None
    )
    total_dev = r2(sum((c["total"] for c in calculo), CERO))
    base_dev = r2(sum((c["base"] for c in calculo), CERO))
    if total_dev <= 0:
        raise ReglaNegocio("El valor a devolver debe ser mayor que cero.", code="total_invalido")
    reparto = _repartir_reembolso(db, venta, total_dev, datos.reembolso, datos.referencia_reembolso)
    _exigir_efectivo_suficiente(db, turno, reparto)
    res = aplicar_politica(
        db,
        actor,
        "devolucion",
        total_dev,
        autorizacion_id=datos.autorizacion_id,
        entidad_tipo="devolucion",
        entidad_id=dev_id,
        detalle={"venta_id": str(venta.id), "motivo": datos.motivo_codigo, "reembolso": datos.reembolso},
    )
    supervisor = res.autorizado_por_id

    # --- documento en borrador y sus hijos ---
    dev = Devolucion(
        id=dev_id,
        venta_id=venta.id,
        sede_id=sesion.sede_id,
        turno_id=turno.id,
        motivo_id=motivo.id,
        tipo_resolucion="nota_credito",
        subtotal=base_dev,
        impuesto_total=total_dev - base_dev,
        redondeo=CERO,
        total=total_dev,
        autorizacion_id=res.autorizacion_id,
        observaciones=datos.observaciones,
        created_by=sesion.empleado.id,
    )
    db.add(dev)
    db.flush()
    pares: list[tuple[DevolucionItem, VentaItem]] = []
    for c in sorted(calculo, key=lambda x: str(x["vi"].producto_id)):  # orden estable de bloqueo de existencias
        vi, it = c["vi"], c["it"]
        reintegra = reintegra_motivo and db.get(Producto, vi.producto_id).es_inventariable
        bodega_id = None
        if reintegra:
            bodega_id = averias.id if it.destino == "averias" else vi.bodega_id
        di = DevolucionItem(
            devolucion_id=dev.id,
            venta_item_id=vi.id,
            producto_id=vi.producto_id,
            cantidad=it.cantidad,
            precio_unitario=vi.precio_unitario,
            tarifa_pct=vi.tarifa_pct,
            descuento_valor=c["desc"],
            total_linea=c["total"],
            base_gravable=c["base"],
            impuesto_valor=c["total"] - c["base"],
            costo_unitario=vi.costo_unitario,
            reintegra_stock=reintegra,
            bodega_reintegro_id=bodega_id,
            created_by=sesion.empleado.id,
        )
        db.add(di)
        db.flush()
        if reintegra:
            inv.registrar_movimiento(
                db,
                actor_id=sesion.empleado.id,
                bodega_id=bodega_id,
                producto_id=vi.producto_id,
                tipo="devolucion_venta",
                cantidad=it.cantidad,
                costo_unitario=vi.costo_unitario,  # la pieza reingresa al costo al que salió
                origen_tipo="devolucion_venta",
                origen_id=dev.id,
                origen_linea_id=di.id,
            )
        pares.append((di, vi))
    pagos: list[DevolucionPago] = []
    for medio, valor, ref in reparto:
        dp = DevolucionPago(
            devolucion_id=dev.id, medio_pago_codigo=medio, valor=valor, referencia=ref, created_by=sesion.empleado.id
        )
        db.add(dp)
        pagos.append(dp)
    db.flush()

    ahora_bd = db.scalar(select(func.clock_timestamp()))  # antes de tocar el estado: evita un autoflush a medias
    dev.confirmada_at = ahora_bd
    dev.estado = "confirmada"
    db.flush()

    # ¿quedó devuelta toda la venta? (concepto de la nota: anulación vs devolución parcial)
    todos = list(db.scalars(select(VentaItem).where(VentaItem.venta_id == venta.id)))
    prev_todos = _devuelto_previo(db, [v.id for v in todos])
    anulacion_total = all(prev_todos.get(v.id, {"q": Decimal(0)})["q"] == v.cantidad for v in todos)

    publicar_evento(
        db,
        "devolucion",
        dev.id,
        "devolucion.confirmada",
        {
            **snapshot(dev),
            "lineas": [
                {"venta_item_id": d.venta_item_id, "cantidad": d.cantidad, "bodega": d.bodega_reintegro_id}
                for d, _ in pares
            ],
            "reembolsos": [{"medio": p.medio_pago_codigo, "valor": p.valor} for p in pagos],
        },
        version=dev.version,
    )
    registrar_accion(
        db,
        "ventas.devolucion_confirmada",
        actor_id=sesion.empleado.id,
        sede_id=sesion.sede_id,
        dispositivo_id=sesion.dispositivo_id,
        entidad_tipo="devolucion",
        entidad_id=dev.id,
        despues={
            "venta_id": str(venta.id),
            "total": str(total_dev),
            "reembolso": datos.reembolso,
            "anulacion_total": anulacion_total,
        },
        motivo=datos.motivo_codigo,
        autorizado_por_id=supervisor,
        autorizacion_id=dev.autorizacion_id,
    )
    return ResultadoDevolucion(dev, True, venta, pares, pagos, anulacion_total, res.exento_por_permiso)


def detalle_devolucion(db: Session, dev: Devolucion) -> tuple[list[DevolucionItem], list[DevolucionPago]]:
    items = list(
        db.scalars(
            select(DevolucionItem)
            .where(DevolucionItem.devolucion_id == dev.id)
            .order_by(DevolucionItem.created_at, DevolucionItem.id)
        )
    )
    pagos = list(
        db.scalars(
            select(DevolucionPago)
            .where(DevolucionPago.devolucion_id == dev.id)
            .order_by(DevolucionPago.created_at, DevolucionPago.id)
        )
    )
    return items, pagos
