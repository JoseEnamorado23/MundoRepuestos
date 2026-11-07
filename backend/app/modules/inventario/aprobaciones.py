"""Aprobación de entradas y ajustes de backoffice que superan el umbral (segregación de funciones).

* Una entrada/ajuste cuyo valor supera el umbral de la sede NO se aplica: se guarda como `SolicitudInventario` en
  estado `pendiente_aprobacion` (sin tocar kardex ni existencias).
* Solo otro empleado con `inventario.aprobar` puede aprobarla; al aprobar se generan los movimientos en la MISMA
  transacción. Al rechazar (con motivo) queda registrado y no se mueve nada.
* Excepción: un empleado con el rol «propietario» puede aprobar su propia solicitud si la sede lo permite
  (`inventario.propietario_autoaprueba`, por defecto NO); queda `autoaprobado = true` y se audita con ese flag.
* El POS conserva su propio camino: ajuste con `autorizacion_id` de un supervisor distinto (ver `servicios.registrar_ajuste`).
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errores import Conflicto, NoEncontrado, PermisoDenegado, ReglaNegocio
from app.core.utiles import snapshot
from app.modules.auditoria.servicios import registrar_accion
from app.modules.catalogo.models import Producto
from app.modules.identidad.servicios import roles_de
from app.modules.inventario import servicios as inv
from app.modules.inventario.configuracion import propietario_autoaprueba, umbral_sede
from app.modules.inventario.models import Bodega, Existencia, SolicitudInventario
from app.modules.sync.servicios import publicar_evento

PENDIENTE = "pendiente_aprobacion"
ROL_PROPIETARIO = "propietario"


def _txt(x):
    return str(x) if isinstance(x, (uuid.UUID, Decimal)) else x


def _crear_solicitud(
    db: Session, actor, tipo: str, bodega: Bodega, valor: Decimal, umbral: Decimal, payload: dict, motivo
):
    s = SolicitudInventario(
        tipo=tipo,
        sede_id=bodega.sede_id,
        bodega_id=bodega.id,
        valor=valor,
        umbral=umbral,
        payload=payload,
        motivo=motivo,
        solicitada_por_id=actor.empleado.id,
        created_by=actor.empleado.id,
    )
    db.add(s)
    db.flush()
    publicar_evento(db, "solicitud_inventario", s.id, "solicitud_inventario.creada", snapshot(s))
    registrar_accion(
        db,
        "inventario.solicitud_creada",
        actor_id=actor.empleado.id,
        sede_id=bodega.sede_id,
        entidad_tipo="solicitud_inventario",
        entidad_id=s.id,
        despues={"tipo": tipo, "valor": str(valor), "umbral": str(umbral)},
        motivo=motivo,
    )
    return s


# ======================================================================================= crear
def entrada(db: Session, actor, *, bodega_id, tercero_id, numero_factura, lineas, observaciones=None):
    """Devuelve ("aplicada", (entrada, movimientos)) o ("pendiente", solicitud)."""
    bodega = db.get(Bodega, bodega_id)
    if bodega is None or not bodega.activo:
        raise ReglaNegocio("La bodega no existe o está inactiva.", code="bodega_invalida")
    if not lineas:
        raise ReglaNegocio("La entrada necesita al menos una línea.", code="sin_lineas")
    ids = {ln["producto_id"] for ln in lineas}
    n = db.scalar(select(func.count()).select_from(Producto).where(Producto.id.in_(ids)))
    if n != len(ids):
        raise ReglaNegocio("Hay productos inexistentes en las líneas.", code="producto_invalido")
    total = sum((inv._q4(ln["cantidad"] * ln["costo_unitario"]) for ln in lineas), Decimal(0)).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )
    umbral = umbral_sede(db, bodega.sede_id)
    if total <= umbral:
        return "aplicada", inv.registrar_entrada(
            db,
            actor.empleado.id,
            bodega_id=bodega_id,
            tercero_id=tercero_id,
            numero_factura=numero_factura,
            lineas=lineas,
            observaciones=observaciones,
        )
    payload = {
        "tercero_id": _txt(tercero_id),
        "numero_factura": numero_factura,
        "observaciones": observaciones,
        "lineas": [{k: _txt(v) for k, v in ln.items()} for ln in lineas],
    }
    return "pendiente", _crear_solicitud(db, actor, "entrada", bodega, total, umbral, payload, observaciones)


def ajuste(
    db: Session,
    actor,
    *,
    bodega_id,
    producto_id,
    cantidad: Decimal,
    motivo: str,
    costo_unitario: Decimal | None = None,
    autorizacion_id=None,
):
    """Devuelve ("aplicado", movimiento) o ("pendiente", solicitud). Con sesión POS el umbral se resuelve con
    `autorizacion_id` de un supervisor; en backoffice, con una solicitud pendiente."""
    bodega = inv.validar_ajuste(db, bodega_id, producto_id, cantidad, motivo)
    if actor.pos is None:
        ex = db.get(Existencia, (bodega_id, producto_id))
        positivo = cantidad > 0
        costo_ref = costo_unitario if (positivo and costo_unitario is not None) else (ex.costo_promedio if ex else 0)
        if positivo and costo_ref == 0 and costo_unitario is None:
            raise ReglaNegocio(
                "No hay costo promedio para valorar el ajuste positivo; indique `costo_unitario`.",
                code="costo_requerido",
            )
        valor = inv.valor_ajuste(cantidad, costo_ref)
        umbral = umbral_sede(db, bodega.sede_id)
        if valor > umbral:
            payload = {
                "producto_id": _txt(producto_id),
                "cantidad": _txt(cantidad),
                "motivo": motivo.strip(),
                "costo_unitario": _txt(costo_unitario) if costo_unitario is not None else None,
            }
            return "pendiente", _crear_solicitud(db, actor, "ajuste", bodega, valor, umbral, payload, motivo.strip())
    mov = inv.registrar_ajuste(
        db,
        actor,
        bodega_id=bodega_id,
        producto_id=producto_id,
        cantidad=cantidad,
        motivo=motivo,
        costo_unitario=costo_unitario,
        autorizacion_id=autorizacion_id,
    )
    return "aplicado", mov


# ======================================================================================= resolver
def resolver(db: Session, actor, solicitud_id: uuid.UUID, *, aprobar: bool, motivo: str | None) -> SolicitudInventario:
    """Aprueba o rechaza. `actor` debe tener `inventario.aprobar` (lo exige el endpoint)."""
    s = db.scalar(select(SolicitudInventario).where(SolicitudInventario.id == solicitud_id).with_for_update())
    if s is None:
        raise NoEncontrado("Solicitud no encontrada.")
    if s.estado != PENDIENTE:
        raise Conflicto(f"La solicitud ya fue {s.estado}.", code="solicitud_resuelta")
    motivo = (motivo or "").strip() or None
    if not aprobar and (motivo is None or len(motivo) < 5):
        raise ReglaNegocio("El motivo del rechazo es obligatorio (mínimo 5 caracteres).", code="motivo_obligatorio")

    autoaprobado = False
    if actor.empleado.id == s.solicitada_por_id:
        es_propietario = any(r.codigo == ROL_PROPIETARIO for r in roles_de(db, actor.empleado.id))
        if aprobar and es_propietario and propietario_autoaprueba(db, s.sede_id):
            autoaprobado = True
        else:
            raise PermisoDenegado(
                "Debe resolver la solicitud otro empleado con el permiso 'inventario.aprobar' "
                "(quien la creó no puede aprobarla ni rechazarla).",
                code="segregacion_funciones",
            )

    resultado = (None, None)
    if aprobar:
        p = s.payload
        quien = SimpleNamespace(empleado=SimpleNamespace(id=s.solicitada_por_id), pos=None)
        if s.tipo == "ajuste":
            mov = inv.registrar_ajuste(
                db,
                quien,
                bodega_id=s.bodega_id,
                producto_id=uuid.UUID(p["producto_id"]),
                cantidad=Decimal(p["cantidad"]),
                motivo=p["motivo"],
                costo_unitario=Decimal(p["costo_unitario"]) if p.get("costo_unitario") else None,
                aprobado_por_id=actor.empleado.id,
            )
            resultado = ("movimiento_inventario", mov.id)
        else:
            ent, _movs = inv.registrar_entrada(
                db,
                s.solicitada_por_id,
                bodega_id=s.bodega_id,
                tercero_id=uuid.UUID(p["tercero_id"]) if p.get("tercero_id") else None,
                numero_factura=p.get("numero_factura"),
                observaciones=p.get("observaciones"),
                lineas=[
                    {
                        "producto_id": uuid.UUID(ln["producto_id"]),
                        "cantidad": Decimal(ln["cantidad"]),
                        "costo_unitario": Decimal(ln["costo_unitario"]),
                    }
                    for ln in p["lineas"]
                ],
            )
            resultado = ("entrada_mercancia", ent.id)

    s.estado = "aprobada" if aprobar else "rechazada"
    s.resuelta_por_id = actor.empleado.id
    s.resuelta_at = func.clock_timestamp()
    s.motivo_resolucion = motivo
    s.autoaprobado = autoaprobado
    s.resultado_tipo, s.resultado_id = resultado
    db.flush()
    db.refresh(s)
    publicar_evento(
        db, "solicitud_inventario", s.id, f"solicitud_inventario.{s.estado}", snapshot(s), version=s.version
    )
    registrar_accion(
        db,
        "inventario.solicitud_aprobada" if aprobar else "inventario.solicitud_rechazada",
        actor_id=actor.empleado.id,
        sede_id=s.sede_id,
        entidad_tipo="solicitud_inventario",
        entidad_id=s.id,
        despues={
            "tipo": s.tipo,
            "valor": str(s.valor),
            "autoaprobado": autoaprobado,
            "solicitada_por_id": str(s.solicitada_por_id),
            "resultado_id": str(s.resultado_id) if s.resultado_id else None,
        },
        motivo=motivo,
    )
    return s
