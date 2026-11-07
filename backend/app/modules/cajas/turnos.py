"""Turnos de caja: apertura, movimientos de efectivo, cierre con CONTEO CIEGO, cierre forzado e informe (modelo §9.4-9.7).

Todo opera con la sesión POS (dispositivo + PIN): la caja sale del dispositivo, nunca del cliente.

* Un turno abierto por caja y por cajero (índices únicos parciales; aquí se revisan antes para dar un mensaje claro).
* Conteo ciego: mientras el turno está abierto NINGÚN endpoint devuelve lo esperado; el cajero declara lo contado por
  medio de pago y solo el cierre calcula y devuelve el arqueo. Un rechazo por diferencia fuera de tolerancia no incluye
  montos (se audita cada intento).
* Efectivo esperado = base + ventas en efectivo (netas de cambio) + ingresos − retiros − reembolsos en efectivo;
  para cada otro medio: ventas − reembolsos de ese medio.
* El cierre toma el turno `FOR UPDATE`; cada venta/devolución lo toma `FOR SHARE`: no se cierra con una venta a medio
  confirmar y no se confirma una venta en un turno que se está cerrando (la fila se reevalúa al desbloquearse).
* Los totales de ventas/devoluciones (`TotalesTurno`) los calcula el caso de uso (app/aplicacion) con el módulo
  `ventas` y los pasa como datos: `cajas` no importa `ventas`.
* La diferencia de arqueo NUNCA bloquea el cierre salvo que la sede configure la política `requiere_autorizacion`
  (`autorizacion.diferencia_arqueo`); por defecto es `revision_posterior` (queda en `auditoria.revisiones`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.base import uuid7
from app.core.dinero import r2
from app.core.errores import Conflicto, NoEncontrado, PermisoDenegado, ReglaNegocio
from app.core.utiles import snapshot
from app.modules.auditoria import revisiones
from app.modules.auditoria.servicios import registrar_accion
from app.modules.cajas.models import ArqueoTurno, Caja, MotivoMovimientoCaja, MovimientoCaja, Turno
from app.modules.cajas.politicas_pos import aplicar_politica
from app.modules.cajas.servicios import SesionPosLike
from app.modules.identidad.models import Empleado
from app.modules.organizacion import politicas
from app.modules.organizacion.models import Empresa, Sede
from app.modules.referencia.models import MedioPago
from app.modules.sync.servicios import publicar_evento

CERO = Decimal("0.00")


@dataclass
class TotalesTurno:
    """Lo que `ventas` aporta al cierre. Los pagos en efectivo ya vienen netos de cambio."""

    ventas_por_medio: dict[str, Decimal] = field(default_factory=dict)
    reembolsos_por_medio: dict[str, Decimal] = field(default_factory=dict)
    num_ventas: int = 0
    total_ventas: Decimal = CERO
    num_devoluciones: int = 0
    total_devoluciones: Decimal = CERO


# ------------------------------------------------------------------------------------------------ consultas
def turno_abierto(db: Session, caja_id: uuid.UUID, *, bloqueo: str | None = None) -> Turno | None:
    """Turno abierto de la caja. `bloqueo`: None, 'compartido' (FOR SHARE, ventas) o 'exclusivo' (FOR UPDATE, cierre)."""
    stmt = select(Turno).where(Turno.caja_id == caja_id, Turno.estado == "abierto")
    if bloqueo == "compartido":
        stmt = stmt.with_for_update(read=True)
    elif bloqueo == "exclusivo":
        stmt = stmt.with_for_update()
    return db.scalar(stmt.execution_options(populate_existing=True))


def _codigo_efectivo(db: Session) -> str:
    codigo = db.scalar(select(MedioPago.codigo).where(MedioPago.es_efectivo.is_(True)).order_by(MedioPago.codigo))
    if codigo is None:
        raise ReglaNegocio("No hay un medio de pago de tipo efectivo configurado.", code="sin_medio_efectivo")
    return codigo


def _sumas_movimientos(db: Session, turno_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    filas = dict(
        db.execute(
            select(MovimientoCaja.tipo, func.coalesce(func.sum(MovimientoCaja.valor), 0))
            .where(MovimientoCaja.turno_id == turno_id)
            .group_by(MovimientoCaja.tipo)
        ).all()
    )
    return Decimal(filas.get("ingreso", 0)), Decimal(filas.get("retiro", 0))


def calcular_esperado(
    db: Session, turno: Turno, totales: TotalesTurno
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """(esperado por medio, desglose del efectivo)."""
    efectivo = _codigo_efectivo(db)
    ingresos, retiros = _sumas_movimientos(db, turno.id)
    medios = set(totales.ventas_por_medio) | set(totales.reembolsos_por_medio) | {efectivo}
    esperado = {
        m: r2(totales.ventas_por_medio.get(m, CERO) - totales.reembolsos_por_medio.get(m, CERO)) for m in medios
    }
    desglose = {
        "base_efectivo": turno.base_efectivo,
        "ventas_efectivo": totales.ventas_por_medio.get(efectivo, CERO),
        "ingresos": ingresos,
        "retiros": retiros,
        "reembolsos_efectivo": totales.reembolsos_por_medio.get(efectivo, CERO),
    }
    esperado[efectivo] = r2(
        turno.base_efectivo + desglose["ventas_efectivo"] + ingresos - retiros - desglose["reembolsos_efectivo"]
    )
    return esperado, desglose


# ------------------------------------------------------------------------------------------------ apertura
def abrir_turno(db: Session, sesion: SesionPosLike, base_efectivo: Decimal) -> Turno:
    if base_efectivo < 0:
        raise ReglaNegocio("La base de efectivo no puede ser negativa.", code="base_invalida")
    caja = db.get(Caja, sesion.caja_id)
    if caja is None or not caja.activo:
        raise NoEncontrado("La caja no existe o está inactiva.")
    # bloquea la fila de la caja: dos aperturas simultáneas se serializan y la segunda ve el turno de la primera
    db.execute(select(Caja.id).where(Caja.id == caja.id).with_for_update())
    if turno_abierto(db, caja.id) is not None:
        raise Conflicto("La caja ya tiene un turno abierto.", code="turno_abierto_en_caja")
    otro = db.scalar(
        select(Caja.codigo)
        .join(Turno, Turno.caja_id == Caja.id)
        .where(Turno.abierto_por_id == sesion.empleado.id, Turno.estado == "abierto")
    )
    if otro is not None:
        raise Conflicto(f"El empleado ya tiene un turno abierto en la caja {otro}.", code="turno_abierto_empleado")
    turno = Turno(
        caja_id=caja.id,
        dispositivo_id=sesion.dispositivo_id,
        abierto_por_id=sesion.empleado.id,
        base_efectivo=r2(base_efectivo),
        created_by=sesion.empleado.id,
    )
    db.add(turno)
    db.flush()
    publicar_evento(db, "turno", turno.id, "turno.abierto", snapshot(turno), version=turno.version)
    registrar_accion(
        db,
        "cajas.turno_abierto",
        actor_id=sesion.empleado.id,
        sede_id=sesion.sede_id,
        dispositivo_id=sesion.dispositivo_id,
        entidad_tipo="turno",
        entidad_id=turno.id,
        despues={"caja_id": str(caja.id), "base_efectivo": str(turno.base_efectivo)},
    )
    return turno


def turno_actual(db: Session, sesion: SesionPosLike) -> Turno:
    t = turno_abierto(db, sesion.caja_id)
    if t is None:
        raise NoEncontrado("La caja no tiene un turno abierto.", code="sin_turno_abierto")
    return t


# ------------------------------------------------------------------------------------------------ movimientos
def registrar_movimiento_caja(
    db: Session,
    actor,
    *,
    tipo: str,
    valor: Decimal,
    motivo_codigo: str,
    descripcion: str | None,
    autorizacion_id: uuid.UUID | None,
) -> MovimientoCaja:
    """Ingreso o retiro de efectivo del turno. Los retiros siguen la política `retiro_caja` (libre hasta el umbral)."""
    sesion = actor.pos
    turno = turno_abierto(db, sesion.caja_id, bloqueo="compartido")
    if turno is None:
        raise ReglaNegocio("La caja no tiene un turno abierto.", code="sin_turno_abierto")
    if turno.abierto_por_id != sesion.empleado.id:
        raise PermisoDenegado("El turno pertenece a otro cajero.", code="turno_ajeno")
    valor = r2(valor)
    if valor <= 0:
        raise ReglaNegocio("El valor del movimiento debe ser mayor que cero.", code="valor_invalido")
    motivo = db.scalar(
        select(MotivoMovimientoCaja).where(MotivoMovimientoCaja.codigo == motivo_codigo, MotivoMovimientoCaja.activo)
    )
    if motivo is None:
        raise ReglaNegocio(f"Motivo '{motivo_codigo}' inexistente o inactivo.", code="motivo_invalido")
    if motivo.tipo not in (tipo, "ambos"):
        raise ReglaNegocio(
            f"El motivo '{motivo_codigo}' no admite movimientos de tipo {tipo}.", code="motivo_incompatible"
        )
    if motivo.codigo == "otro" and not (descripcion or "").strip():
        raise ReglaNegocio("El motivo 'otro' exige una descripción.", code="descripcion_requerida")

    mov_id = uuid7()
    resultado = None
    if tipo == "retiro":
        resultado = aplicar_politica(
            db,
            actor,
            "retiro_caja",
            valor,
            autorizacion_id=autorizacion_id,
            entidad_tipo="movimiento_caja",
            entidad_id=mov_id,
            detalle={"motivo": motivo.codigo, "turno_id": str(turno.id)},
        )
    supervisor = resultado.autorizado_por_id if resultado else None
    mov = MovimientoCaja(
        id=mov_id,
        turno_id=turno.id,
        tipo=tipo,
        valor=valor,
        motivo_id=motivo.id,
        descripcion=descripcion,
        autorizacion_id=resultado.autorizacion_id if resultado else None,
        created_by=sesion.empleado.id,
    )
    db.add(mov)
    db.flush()
    publicar_evento(
        db,
        "movimiento_caja",
        mov.id,
        "movimiento_caja.registrado",
        {**snapshot(mov), "motivo_codigo": motivo.codigo},
    )
    registrar_accion(
        db,
        "cajas.movimiento_registrado",
        actor_id=sesion.empleado.id,
        sede_id=sesion.sede_id,
        dispositivo_id=sesion.dispositivo_id,
        entidad_tipo="movimiento_caja",
        entidad_id=mov.id,
        despues={"tipo": tipo, "valor": str(valor), "motivo": motivo.codigo},
        autorizado_por_id=supervisor,
        autorizacion_id=mov.autorizacion_id,
    )
    return mov


def listar_movimientos(db: Session, turno_id: uuid.UUID) -> list[tuple[MovimientoCaja, str]]:
    return [
        (m, c)
        for m, c in db.execute(
            select(MovimientoCaja, MotivoMovimientoCaja.codigo)
            .join(MotivoMovimientoCaja, MotivoMovimientoCaja.id == MovimientoCaja.motivo_id)
            .where(MovimientoCaja.turno_id == turno_id)
            .order_by(MovimientoCaja.created_at)
        ).all()
    ]


# ------------------------------------------------------------------------------------------------ cierre
def _cerrar(
    db: Session,
    turno: Turno,
    *,
    sede_id: uuid.UUID,
    cerrador_id: uuid.UUID,
    conteo: dict[str, Decimal] | None,
    totales: TotalesTurno,
    autorizacion_id: uuid.UUID | None,
    actor,
    observaciones: str | None,
    forzado: bool,
    motivo_forzado: str | None,
    dispositivo_id: uuid.UUID | None,
) -> Turno:
    efectivo = _codigo_efectivo(db)
    esperado, _ = calcular_esperado(db, turno, totales)
    sin_conteo = conteo is None
    if conteo is None:  # cierre forzado sin conteo: se cierra en lo esperado y queda marcado
        conteo = dict(esperado)
    else:
        for m in conteo:
            if m not in esperado and db.get(MedioPago, m) is None:
                raise ReglaNegocio(f"Medio de pago '{m}' inexistente.", code="medio_invalido")
        if efectivo not in conteo:
            raise ReglaNegocio("Debe declarar el efectivo contado.", code="falta_efectivo")
    medios = set(esperado) | set(conteo)
    contado = {m: r2(conteo.get(m, CERO)) for m in medios}
    for v in contado.values():
        if v < 0:
            raise ReglaNegocio("Los valores contados no pueden ser negativos.", code="valor_invalido")
    diferencias = {m: r2(contado[m] - esperado.get(m, CERO)) for m in medios}

    supervisor_id = aut_id = None
    conf = politicas.configuracion_de(db, sede_id, "diferencia_arqueo")
    umbral = Decimal(str(conf["umbral"])) if conf.get("umbral") is not None else None
    mayor = max((abs(d) for d in diferencias.values()), default=CERO)
    if mayor > 0:
        total_abs = sum((abs(d) for d in diferencias.values()), CERO)
        detalle = {
            "turno_id": str(turno.id),
            "diferencias": {m: str(d) for m, d in diferencias.items() if d != 0},
            "cierre_forzado": forzado,
        }
        # La diferencia de arqueo NUNCA bloquea el cierre (la política no admite 'requiere_autorizacion'): según la
        # política queda libre o pendiente de revisión posterior.
        if politicas.evaluar(db, sede_id, "diferencia_arqueo", mayor) != politicas.LIBRE:
            revisiones.registrar(
                db,
                sede_id=sede_id,
                accion="diferencia_arqueo",
                entidad_tipo="turno",
                entidad_id=turno.id,
                monto=total_abs,
                empleado_id=cerrador_id,
                dispositivo_id=dispositivo_id,
                detalle=detalle,
            )

    for m in sorted(medios):
        db.add(
            ArqueoTurno(
                turno_id=turno.id,
                medio_pago_codigo=m,
                valor_esperado=esperado.get(m, CERO),
                valor_contado=contado[m],
                observacion="cierre forzado sin conteo" if sin_conteo else None,
                created_by=cerrador_id,
            )
        )
    cierre_bd = db.scalar(select(func.clock_timestamp()))  # reloj de la BD (el mismo de confirmada_at de las ventas)
    turno.cerrado_at = cierre_bd
    turno.estado = "cerrado"
    turno.cerrado_por_id = cerrador_id
    turno.efectivo_esperado = esperado[efectivo]
    turno.efectivo_contado = contado[efectivo]
    turno.supervisor_cierre_id = supervisor_id
    turno.autorizacion_cierre_id = aut_id
    turno.umbral_diferencia = umbral
    turno.observaciones = observaciones
    turno.cierre_forzado = forzado
    turno.motivo_cierre_forzado = motivo_forzado
    db.flush()
    publicar_evento(
        db,
        "turno",
        turno.id,
        "turno.cerrado",
        {
            **snapshot(turno),
            "arqueos": [
                {"medio": m, "esperado": esperado.get(m, CERO), "contado": contado[m], "diferencia": diferencias[m]}
                for m in sorted(medios)
            ],
        },
        version=turno.version,
    )
    registrar_accion(
        db,
        "cajas.turno_cierre_forzado" if forzado else "cajas.turno_cerrado",
        actor_id=cerrador_id,
        sede_id=sede_id,
        dispositivo_id=dispositivo_id,
        entidad_tipo="turno",
        entidad_id=turno.id,
        despues={
            "efectivo_esperado": str(esperado[efectivo]),
            "efectivo_contado": str(contado[efectivo]),
            "diferencias": {m: str(d) for m, d in diferencias.items() if d != 0},
        },
        motivo=motivo_forzado,
        autorizado_por_id=supervisor_id,
        autorizacion_id=aut_id,
    )
    return turno


def bloquear_turno_del_cajero(db: Session, sesion: SesionPosLike) -> Turno:
    """Turno abierto de la caja tomado FOR UPDATE (primer paso del cierre); solo su cajero puede cerrarlo."""
    turno = turno_abierto(db, sesion.caja_id, bloqueo="exclusivo")
    if turno is None:
        raise ReglaNegocio("La caja no tiene un turno abierto.", code="sin_turno_abierto")
    if turno.abierto_por_id != sesion.empleado.id:
        raise PermisoDenegado(
            "Solo el cajero del turno puede cerrarlo; pida un cierre forzado a un supervisor.", code="turno_ajeno"
        )
    return turno


def cerrar_turno(
    db: Session,
    actor,
    turno: Turno,
    *,
    conteo: dict[str, Decimal],
    autorizacion_id: uuid.UUID | None,
    observaciones: str | None,
    totales: TotalesTurno,
) -> Turno:
    """Cierre del cajero con conteo ciego sobre el turno ya bloqueado. El informe se pide aparte."""
    sesion = actor.pos
    return _cerrar(
        db,
        turno,
        sede_id=sesion.sede_id,
        cerrador_id=sesion.empleado.id,
        conteo=conteo,
        totales=totales,
        autorizacion_id=autorizacion_id,
        actor=actor,
        observaciones=observaciones,
        forzado=False,
        motivo_forzado=None,
        dispositivo_id=sesion.dispositivo_id,
    )


def bloquear_turno_para_forzar(
    db: Session, turno_id: uuid.UUID, sede_permitida, motivo: str
) -> tuple[Turno, uuid.UUID]:
    """Primer paso del cierre forzado: valida el motivo y toma el turno FOR UPDATE. Devuelve (turno, sede_id)."""
    if len((motivo or "").strip()) < 5:
        raise ReglaNegocio(
            "El motivo del cierre forzado es obligatorio (mínimo 5 caracteres).", code="motivo_obligatorio"
        )
    turno = db.scalar(
        select(Turno).where(Turno.id == turno_id).with_for_update().execution_options(populate_existing=True)
    )
    if turno is None:
        raise NoEncontrado("Turno no encontrado.")
    caja = db.get(Caja, turno.caja_id)
    sede_permitida(caja.sede_id)
    if turno.estado != "abierto":
        raise Conflicto("El turno ya está cerrado.", code="turno_cerrado")
    return turno, caja.sede_id


def cierre_forzado(
    db: Session,
    turno: Turno,
    sede_id: uuid.UUID,
    *,
    supervisor_id: uuid.UUID,
    motivo: str,
    conteo: dict[str, Decimal] | None,
    totales: TotalesTurno,
    dispositivo_id: uuid.UUID | None = None,
) -> Turno:
    """Un supervisor (permiso cajas.cierre_forzado) cierra un turno abandonado (ya bloqueado)."""
    return _cerrar(
        db,
        turno,
        sede_id=sede_id,
        cerrador_id=supervisor_id,
        conteo=conteo,
        totales=totales,
        autorizacion_id=None,
        actor=None,
        observaciones=None,
        forzado=True,
        motivo_forzado=motivo.strip(),
        dispositivo_id=dispositivo_id,
    )


# ------------------------------------------------------------------------------------------------ informe
def informe_cierre(db: Session, turno_id: uuid.UUID, tot: TotalesTurno) -> dict:
    """JSON listo para imprimir del turno CERRADO (con lo esperado, ahora sí)."""
    turno = db.get(Turno, turno_id)
    if turno is None:
        raise NoEncontrado("Turno no encontrado.")
    if turno.estado != "cerrado":
        raise Conflicto("El informe de cierre solo existe cuando el turno está cerrado.", code="turno_abierto")
    caja = db.get(Caja, turno.caja_id)
    sede = db.get(Sede, caja.sede_id)
    empresa = db.get(Empresa, sede.empresa_id)
    esperado, desglose = calcular_esperado(db, turno, tot)
    nombres = {
        e.id: f"{e.nombres} {e.apellidos}"
        for e in db.scalars(
            select(Empleado).where(
                Empleado.id.in_(
                    [x for x in (turno.abierto_por_id, turno.cerrado_por_id, turno.supervisor_cierre_id) if x]
                )
            )
        )
    }
    medios = {m.codigo: m.nombre for m in db.scalars(select(MedioPago))}
    arqueos = list(
        db.scalars(select(ArqueoTurno).where(ArqueoTurno.turno_id == turno.id).order_by(ArqueoTurno.medio_pago_codigo))
    )
    return {
        "empresa": {"nit": f"{empresa.nit}-{empresa.dv}", "razon_social": empresa.razon_social},
        "sede": {"codigo": sede.codigo, "nombre": sede.nombre},
        "caja": {"id": caja.id, "codigo": caja.codigo, "nombre": caja.nombre},
        "turno": {
            "id": turno.id,
            "abierto_at": turno.abierto_at,
            "cerrado_at": turno.cerrado_at,
            "cajero": nombres.get(turno.abierto_por_id),
            "cerrado_por": nombres.get(turno.cerrado_por_id),
            "supervisor": nombres.get(turno.supervisor_cierre_id),
            "cierre_forzado": turno.cierre_forzado,
            "motivo_cierre_forzado": turno.motivo_cierre_forzado,
            "observaciones": turno.observaciones,
            "tolerancia_diferencia": turno.umbral_diferencia,
        },
        "resumen": {
            "num_ventas": tot.num_ventas,
            "total_ventas": tot.total_ventas,
            "num_devoluciones": tot.num_devoluciones,
            "total_devoluciones": tot.total_devoluciones,
        },
        "efectivo": desglose,
        "arqueos": [
            {
                "medio_pago_codigo": a.medio_pago_codigo,
                "medio_pago": medios.get(a.medio_pago_codigo),
                "esperado": a.valor_esperado,
                "contado": a.valor_contado,
                "diferencia": a.diferencia,
                "observacion": a.observacion,
            }
            for a in arqueos
        ],
        "diferencia_total": sum((a.diferencia for a in arqueos), CERO),
        "movimientos": [
            {"tipo": m.tipo, "valor": m.valor, "motivo": c, "descripcion": m.descripcion, "hora": m.created_at}
            for m, c in listar_movimientos(db, turno.id)
        ],
    }
