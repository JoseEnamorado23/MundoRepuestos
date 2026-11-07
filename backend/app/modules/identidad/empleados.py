"""Administración mínima de empleados: crear, listar, roles, sedes, contraseña, PIN y (des)activación.

Sin borrado físico. Servicios sin commit (lo hace la dependencia de sesión de la API).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errores import Conflicto, NoEncontrado, ReglaNegocio
from app.core.seguridad import hash_secreto, indice_pin
from app.modules.auditoria.servicios import registrar_accion
from app.modules.identidad.models import Empleado, EmpleadoRol, EmpleadoSede, Rol
from app.modules.identidad.servicios import asignaciones_sede, revocar_sesiones_de, roles_de
from app.modules.organizacion.models import Sede

PIN_DIGITOS = 6


def validar_password(password: str) -> None:
    minimo = get_settings().password_longitud_min
    if len(password) < minimo:
        raise ReglaNegocio(f"La contraseña debe tener al menos {minimo} caracteres.", code="password_debil")


def validar_pin(pin: str) -> None:
    if not (len(pin) == PIN_DIGITOS and pin.isascii() and pin.isdigit()):
        raise ReglaNegocio(f"El PIN debe tener exactamente {PIN_DIGITOS} dígitos.", code="pin_invalido")


def obtener(db: Session, empleado_id: uuid.UUID) -> Empleado:
    e = db.get(Empleado, empleado_id)
    if e is None:
        raise NoEncontrado("Empleado no encontrado.")
    return e


def _resolver_roles(db: Session, codigos: list[str]) -> list[Rol]:
    unicos = sorted(set(codigos))
    roles = list(db.scalars(select(Rol).where(Rol.codigo.in_(unicos), Rol.activo.is_(True))))
    faltan = set(unicos) - {r.codigo for r in roles}
    if faltan:
        raise ReglaNegocio(f"Roles inexistentes o inactivos: {', '.join(sorted(faltan))}.", code="rol_invalido")
    return roles


def _validar_sedes(db: Session, sedes: list[uuid.UUID]) -> None:
    unicas = set(sedes)
    if not unicas:
        return
    existentes = set(db.scalars(select(Sede.id).where(Sede.id.in_(unicas))))
    if unicas - existentes:
        raise ReglaNegocio("Alguna de las sedes indicadas no existe.", code="sede_invalida")


def crear(
    db: Session,
    *,
    datos: dict,
    password: str | None,
    roles: list[str],
    sedes: list[uuid.UUID],
    actor_id: uuid.UUID | None,
) -> Empleado:
    if datos.get("usuario") and not password:
        raise ReglaNegocio("Un empleado con usuario necesita contraseña.", code="password_requerida")
    if password:
        validar_password(password)
    resolved = _resolver_roles(db, roles)
    _validar_sedes(db, sedes)
    emp = Empleado(**datos, password_hash=hash_secreto(password) if password else None, created_by=actor_id)
    db.add(emp)
    db.flush()  # un duplicado (usuario, documento, carné) falla aquí y la API lo traduce a 409
    for r in resolved:
        db.add(EmpleadoRol(empleado_id=emp.id, rol_id=r.id))
    for i, s in enumerate(dict.fromkeys(sedes)):
        db.add(EmpleadoSede(empleado_id=emp.id, sede_id=s, es_sede_principal=(i == 0)))
    db.flush()
    registrar_accion(
        db,
        "identidad.empleado_creado",
        actor_id=actor_id,
        entidad_tipo="empleado",
        entidad_id=emp.id,
        despues={"usuario": emp.usuario, "roles": sorted(r.codigo for r in resolved), "sedes": [str(s) for s in sedes]},
    )
    return emp


def listar(db: Session, *, q: str | None, activo: bool | None, limite: int, desplazamiento: int) -> list[Empleado]:
    stmt = select(Empleado).order_by(Empleado.apellidos, Empleado.nombres)
    if activo is not None:
        stmt = stmt.where(Empleado.activo.is_(activo))
    if q:
        patron = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Empleado.nombres + " " + Empleado.apellidos).like(patron),
                func.lower(Empleado.usuario).like(patron),
                Empleado.numero_documento.like(patron),
            )
        )
    return list(db.scalars(stmt.limit(limite).offset(desplazamiento)))


def asignar_roles(db: Session, empleado_id: uuid.UUID, codigos: list[str], actor_id: uuid.UUID | None) -> list[Rol]:
    emp = obtener(db, empleado_id)
    nuevos = _resolver_roles(db, codigos)
    antes = sorted(r.codigo for r in roles_de(db, emp.id))
    ids_nuevos = {r.id for r in nuevos}
    actuales = {er.rol_id: er for er in db.scalars(select(EmpleadoRol).where(EmpleadoRol.empleado_id == emp.id))}
    for rol_id, er in actuales.items():
        if rol_id not in ids_nuevos:
            db.delete(er)
    for r in nuevos:
        if r.id not in actuales:
            db.add(EmpleadoRol(empleado_id=emp.id, rol_id=r.id))
    db.flush()
    registrar_accion(
        db,
        "identidad.roles_cambiados",
        actor_id=actor_id,
        entidad_tipo="empleado",
        entidad_id=emp.id,
        antes={"roles": antes},
        despues={"roles": sorted(r.codigo for r in nuevos)},
    )
    return nuevos


def asignar_sedes(
    db: Session, empleado_id: uuid.UUID, sedes: list[uuid.UUID], principal: uuid.UUID | None, actor_id: uuid.UUID | None
) -> list[EmpleadoSede]:
    emp = obtener(db, empleado_id)
    sedes = list(dict.fromkeys(sedes))
    if principal is not None and principal not in sedes:
        raise ReglaNegocio("La sede principal debe estar entre las sedes asignadas.", code="sede_invalida")
    _validar_sedes(db, sedes)
    actuales = {a.sede_id: a for a in asignaciones_sede(db, emp.id)}
    antes = sorted(str(s) for s in actuales)
    for sede_id, a in actuales.items():
        if sede_id not in sedes:
            db.delete(a)  # se pierde el PIN de esa sede: es lo esperado al retirarle el acceso
    for sede_id in sedes:
        if sede_id not in actuales:
            db.add(EmpleadoSede(empleado_id=emp.id, sede_id=sede_id))
    db.flush()
    elegida = principal or (sedes[0] if sedes else None)
    resultado = asignaciones_sede(db, emp.id)
    for a in resultado:
        a.es_sede_principal = a.sede_id == elegida
    db.flush()
    registrar_accion(
        db,
        "identidad.sedes_cambiadas",
        actor_id=actor_id,
        entidad_tipo="empleado",
        entidad_id=emp.id,
        antes={"sedes": antes},
        despues={"sedes": sorted(str(s) for s in sedes)},
    )
    return resultado


def cambiar_password(db: Session, empleado_id: uuid.UUID, password: str, actor_id: uuid.UUID | None) -> None:
    emp = obtener(db, empleado_id)
    if not emp.usuario:
        raise ReglaNegocio("El empleado no tiene usuario; no usa contraseña.", code="sin_usuario")
    validar_password(password)
    emp.password_hash = hash_secreto(password)
    revocar_sesiones_de(db, emp.id, "cambio_password")
    db.flush()
    registrar_accion(db, "identidad.password_cambiada", actor_id=actor_id, entidad_tipo="empleado", entidad_id=emp.id)


def cambiar_pin(
    db: Session, empleado_id: uuid.UUID, pin: str, sede_id: uuid.UUID | None, actor_id: uuid.UUID | None
) -> list[uuid.UUID]:
    """Fija el PIN del empleado en una sede (o en todas las suyas). El PIN es único por sede."""
    emp = obtener(db, empleado_id)
    validar_pin(pin)
    asignaciones = asignaciones_sede(db, emp.id)
    if sede_id is not None:
        asignaciones = [a for a in asignaciones if a.sede_id == sede_id]
    if not asignaciones:
        raise ReglaNegocio("El empleado no está asignado a esa sede (o no tiene sedes).", code="sede_invalida")
    hash_pin = hash_secreto(pin)
    for a in asignaciones:
        lookup = indice_pin(a.sede_id, pin)
        ocupado = db.scalar(
            select(EmpleadoSede.empleado_id).where(
                EmpleadoSede.sede_id == a.sede_id,
                EmpleadoSede.pin_lookup == lookup,
                EmpleadoSede.empleado_id != emp.id,
            )
        )
        if ocupado is not None:
            raise Conflicto("PIN no disponible.", code="pin_no_disponible")  # genérico: no revela de quién es
        a.pin_hash, a.pin_lookup = hash_pin, lookup
    db.flush()
    registrar_accion(
        db,
        "identidad.pin_cambiado",
        actor_id=actor_id,
        entidad_tipo="empleado",
        entidad_id=emp.id,
        despues={"sedes": [str(a.sede_id) for a in asignaciones]},
    )
    return [a.sede_id for a in asignaciones]


def cambiar_activo(db: Session, empleado_id: uuid.UUID, activo: bool, actor_id: uuid.UUID | None) -> Empleado:
    emp = obtener(db, empleado_id)
    if emp.activo == activo:
        return emp
    emp.activo = activo
    if not activo:
        revocar_sesiones_de(db, emp.id, "empleado_desactivado")
    db.flush()
    registrar_accion(
        db,
        "identidad.empleado_activado" if activo else "identidad.empleado_desactivado",
        actor_id=actor_id,
        entidad_tipo="empleado",
        entidad_id=emp.id,
        antes={"activo": not activo},
        despues={"activo": activo},
    )
    return emp
