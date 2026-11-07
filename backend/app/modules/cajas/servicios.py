"""Dispositivos POS y autenticación del POS (PIN/carné), con autorización de supervisor de un solo uso.

Servicios sin commit. En los flujos de autenticación (`autenticar_pos`, `crear_autorizacion`) lo único que se escribe
antes de un error es auditoría, que el router confirma con `persistir_si_falla`.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errores import NoAutenticado, NoEncontrado, PermisoDenegado, ReglaNegocio
from app.core.seguridad import ahora, crear_jwt, indice_pin, nuevo_token_opaco, sha256_hex, verificar_secreto
from app.core.utiles import snapshot
from app.modules.auditoria.servicios import registrar_accion, verificar_bloqueo
from app.modules.cajas.models import Caja, Dispositivo
from app.modules.identidad.autorizaciones import SesionPosLike
from app.modules.identidad.models import Autorizacion, Empleado, EmpleadoSede
from app.modules.identidad.servicios import permisos_de
from app.modules.sync.servicios import publicar_evento

# Acción (permiso) que un supervisor puede autorizar -> valor del ENUM identidad.tipo_autorizacion
ACCIONES_AUTORIZABLES: dict[str, str] = {
    "pos.descuento_mayor": "descuento_mayor",
    "pos.anular": "anulacion",
    "pos.devolver": "devolucion",
    "pos.cambiar_precio": "precio_manual",
    "pos.retirar_efectivo": "retiro_efectivo",
    "caja.cerrar_con_diferencia": "cierre_con_diferencia",
    "inventario.ajustar": "ajuste_inventario",
    "pos.venta_sin_stock": "venta_sin_stock",
}


# --------------------------------------------------------------------------------------------------
# cajas
# --------------------------------------------------------------------------------------------------
def crear_caja(
    db: Session, sede_id: uuid.UUID, codigo: str, nombre: str, bodega_id: uuid.UUID, *, actor_id: uuid.UUID | None
) -> Caja:
    """Alta de una caja. Su bodega debe ser de la misma sede y vendible. Publica evento y deja auditoría."""
    from app.modules.inventario.models import Bodega

    bodega = db.get(Bodega, bodega_id)
    if bodega is None or bodega.sede_id != sede_id or not bodega.es_vendible or not bodega.activo:
        raise ReglaNegocio(
            "La bodega de la caja debe ser activa, vendible y de la misma sede.", code="bodega_caja_invalida"
        )
    caja = Caja(sede_id=sede_id, codigo=codigo, nombre=nombre, bodega_id=bodega_id, created_by=actor_id)
    db.add(caja)
    db.flush()  # uq_cajas_sede_codigo -> 409
    publicar_evento(db, "caja", caja.id, "caja.creada", snapshot(caja), version=caja.version)
    registrar_accion(
        db,
        "cajas.caja_creada",
        actor_id=actor_id,
        sede_id=sede_id,
        entidad_tipo="caja",
        entidad_id=caja.id,
        despues={"codigo": codigo, "bodega_id": str(bodega_id)},
    )
    return caja


# --------------------------------------------------------------------------------------------------
# dispositivos
# --------------------------------------------------------------------------------------------------
def crear_dispositivo(db: Session, caja_id: uuid.UUID, nombre: str, actor_id: uuid.UUID) -> tuple[Dispositivo, str]:
    """Registra un dispositivo POS activo en la caja. Devuelve el token en claro: es la ÚNICA vez que existe."""
    caja = db.get(Caja, caja_id)
    if caja is None or not caja.activo:
        raise NoEncontrado("La caja no existe o está inactiva.")
    token = nuevo_token_opaco(32)  # 32 bytes aleatorios (43 caracteres base64url)
    disp = Dispositivo(
        sede_id=caja.sede_id,
        caja_id=caja.id,
        tipo="pos",
        nombre=nombre,
        token_hash=sha256_hex(token),
        estado="activo",
        created_by=actor_id,
    )
    db.add(disp)
    db.flush()  # uq_dispositivos_caja_activo -> 409 con mensaje claro
    registrar_accion(
        db,
        "cajas.dispositivo_creado",
        actor_id=actor_id,
        sede_id=caja.sede_id,
        entidad_tipo="dispositivo",
        entidad_id=disp.id,
        dispositivo_id=disp.id,
        despues={"caja_id": str(caja.id), "nombre": nombre},
    )
    return disp, token


def listar_dispositivos(db: Session, caja_id: uuid.UUID | None = None) -> list[Dispositivo]:
    stmt = select(Dispositivo).order_by(Dispositivo.created_at.desc())
    if caja_id is not None:
        stmt = stmt.where(Dispositivo.caja_id == caja_id)
    return list(db.scalars(stmt))


def revocar_dispositivo(db: Session, dispositivo_id: uuid.UUID, actor_id: uuid.UUID) -> Dispositivo:
    disp = db.get(Dispositivo, dispositivo_id)
    if disp is None:
        raise NoEncontrado("Dispositivo no encontrado.")
    if disp.estado != "revocado":
        previo = disp.estado
        disp.estado = "revocado"
        disp.revocado_at = ahora()
        db.flush()
        registrar_accion(
            db,
            "cajas.dispositivo_revocado",
            actor_id=actor_id,
            sede_id=disp.sede_id,
            entidad_tipo="dispositivo",
            entidad_id=disp.id,
            dispositivo_id=disp.id,
            antes={"estado": previo},
            despues={"estado": "revocado"},
        )
    return disp


def dispositivo_por_token(db: Session, token: str) -> Dispositivo | None:
    return db.scalar(select(Dispositivo).where(Dispositivo.token_hash == sha256_hex(token)))


# --------------------------------------------------------------------------------------------------
# login del POS por PIN / carné
# --------------------------------------------------------------------------------------------------
def _fallo_pin(
    db: Session, disp: Dispositivo, motivo: str, empleado_id: uuid.UUID | None = None, entidad: str | None = None
) -> None:
    registrar_accion(
        db,
        "pos.pin_fallido",
        actor_id=empleado_id,
        resultado="denegado",
        sede_id=disp.sede_id,
        dispositivo_id=disp.id,
        motivo=motivo,
        entidad_tipo=entidad,
    )


def _bloqueos_pos(db: Session, disp: Dispositivo, empleado_id: uuid.UUID | None = None) -> None:
    cfg = get_settings()
    verificar_bloqueo(
        db,
        accion_fallo="pos.pin_fallido",
        accion_ok="pos.pin_ok",
        maximo=cfg.max_intentos_dispositivo,
        dispositivo_id=disp.id,
    )
    if empleado_id is not None:
        verificar_bloqueo(
            db,
            accion_fallo="pos.pin_fallido",
            accion_ok="pos.pin_ok",
            maximo=cfg.max_intentos_empleado,
            actor_id=empleado_id,
        )


def _identificar_por_pin(db: Session, sede_id: uuid.UUID, pin: str) -> tuple[Empleado, EmpleadoSede] | None:
    """Empleado de la sede cuyo PIN coincide (índice HMAC único por sede + verificación argon2)."""
    asign = db.scalar(
        select(EmpleadoSede).where(EmpleadoSede.sede_id == sede_id, EmpleadoSede.pin_lookup == indice_pin(sede_id, pin))
    )
    valido = verificar_secreto(pin, asign.pin_hash if asign else None)
    if asign is None or not valido:
        return None
    return db.get(Empleado, asign.empleado_id), asign


def autenticar_pos(db: Session, token_dispositivo: str | None, pin: str | None, codigo_carne: str | None):
    """Devuelve (empleado, dispositivo, jwt, expira_en_seg). Lanza 401/403/429 y deja auditado cada intento."""
    if not token_dispositivo:
        raise NoAutenticado("Falta el encabezado X-Dispositivo-Token.", code="dispositivo_invalido")
    disp = dispositivo_por_token(db, token_dispositivo)
    if disp is None or disp.estado != "activo" or disp.caja_id is None:
        registrar_accion(
            db,
            "pos.dispositivo_invalido",
            actor_tipo="sistema",
            resultado="denegado",
            dispositivo_id=disp.id if disp else None,
            motivo="token_desconocido" if disp is None else f"estado_{disp.estado}",
        )
        raise NoAutenticado("Dispositivo no autorizado.", code="dispositivo_invalido")
    if bool(pin) == bool(codigo_carne):
        raise ReglaNegocio("Envíe exactamente uno: 'pin' o 'codigo_carne'.", code="credencial_requerida")

    _bloqueos_pos(db, disp)  # por dispositivo, antes de tocar nada más

    asign: EmpleadoSede | None
    if pin:
        hallado = _identificar_por_pin(db, disp.sede_id, pin)
        if hallado is None:
            _fallo_pin(db, disp, "pin_invalido")
            raise NoAutenticado("Credencial inválida.", code="credenciales_invalidas")
        emp, asign = hallado
    else:
        emp = db.scalar(select(Empleado).where(Empleado.codigo_carne == codigo_carne))
        if emp is None:
            _fallo_pin(db, disp, "carne_desconocido")
            raise NoAutenticado("Credencial inválida.", code="credenciales_invalidas")
        asign = db.get(EmpleadoSede, (emp.id, disp.sede_id))

    _bloqueos_pos(db, disp, emp.id)  # por empleado ya identificado

    if not emp.activo:
        _fallo_pin(db, disp, "empleado_inactivo", emp.id)
        raise NoAutenticado("Credencial inválida.", code="credenciales_invalidas")
    if asign is None:
        _fallo_pin(db, disp, "otra_sede", emp.id)
        raise PermisoDenegado("El empleado no está asignado a esta sede.", code="sede_no_asignada")
    if "pos.acceder" not in permisos_de(db, emp.id):
        _fallo_pin(db, disp, "sin_permiso_pos_acceder", emp.id)
        raise PermisoDenegado("Falta el permiso 'pos.acceder'.", code="permiso_denegado", permiso="pos.acceder")

    ttl = timedelta(minutes=get_settings().pos_sesion_ttl_min)
    token, _ = crear_jwt(
        {"sub": str(emp.id), "typ": "pos", "dsp": str(disp.id), "caja": str(disp.caja_id), "sede": str(disp.sede_id)},
        ttl,
    )
    registrar_accion(
        db,
        "pos.pin_ok",
        actor_id=emp.id,
        sede_id=disp.sede_id,
        dispositivo_id=disp.id,
        motivo="pin" if pin else "carne",
    )
    return emp, disp, token, int(ttl.total_seconds())


# --------------------------------------------------------------------------------------------------
# autorización de supervisor (un solo uso)
# --------------------------------------------------------------------------------------------------
def crear_autorizacion(
    db: Session,
    sesion: SesionPosLike,
    *,
    pin: str,
    accion: str,
    entidad_tipo: str | None,
    entidad_id: uuid.UUID | None,
    detalle: dict,
    motivo: str | None,
) -> Autorizacion:
    tipo = ACCIONES_AUTORIZABLES.get(accion)
    if tipo is None:
        raise ReglaNegocio(f"La acción '{accion}' no admite autorización de supervisor.", code="accion_no_autorizable")
    disp = db.get(Dispositivo, sesion.dispositivo_id)
    _bloqueos_pos(db, disp, sesion.empleado.id)
    hallado = _identificar_por_pin(db, sesion.sede_id, pin)
    if hallado is None:
        _fallo_pin(db, disp, "pin_supervisor_invalido", sesion.empleado.id, entidad="autorizacion")
        raise NoAutenticado("PIN de supervisor inválido.", code="credenciales_invalidas")
    supervisor, _ = hallado
    if supervisor.id == sesion.empleado.id:
        registrar_accion(
            db,
            "pos.autorizacion_denegada",
            actor_id=sesion.empleado.id,
            resultado="denegado",
            sede_id=sesion.sede_id,
            dispositivo_id=disp.id,
            motivo="autoautorizacion",
        )
        raise ReglaNegocio("No puede autorizarse a sí mismo; pida a otro supervisor.", code="autoautorizacion")
    if not supervisor.activo or accion not in permisos_de(db, supervisor.id):
        registrar_accion(
            db,
            "pos.autorizacion_denegada",
            actor_id=sesion.empleado.id,
            resultado="denegado",
            sede_id=sesion.sede_id,
            dispositivo_id=disp.id,
            autorizado_por_id=supervisor.id,
            motivo="supervisor_sin_permiso",
        )
        raise PermisoDenegado(f"El supervisor no tiene el permiso '{accion}'.", code="permiso_denegado", permiso=accion)

    autorizacion = Autorizacion(
        tipo=tipo,
        permiso_codigo=accion,
        solicitado_por_id=sesion.empleado.id,
        autorizado_por_id=supervisor.id,
        dispositivo_id=sesion.dispositivo_id,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
        detalle=detalle,
        motivo=motivo,
        expira_at=ahora() + timedelta(seconds=get_settings().autorizacion_ttl_seg),
        created_by=sesion.empleado.id,
    )
    db.add(autorizacion)
    db.flush()
    registrar_accion(
        db,
        "pos.autorizacion_creada",
        actor_id=sesion.empleado.id,
        sede_id=sesion.sede_id,
        dispositivo_id=sesion.dispositivo_id,
        autorizado_por_id=supervisor.id,
        autorizacion_id=autorizacion.id,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
        despues={"accion": accion},
    )
    return autorizacion
