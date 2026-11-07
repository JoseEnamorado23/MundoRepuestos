"""Autenticación de empleados (backoffice): login, refresh con rotación, logout, y consulta de permisos.

Convención: estos servicios NO hacen commit. En los flujos de autenticación que pueden fallar, lo único que escriben
antes de lanzar el error es una fila de auditoría; el router la confirma explícitamente (ver `app/api/deps.py`,
`persistir_si_falla`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errores import NoAutenticado
from app.core.logs import ip_var, user_agent_var
from app.core.seguridad import ahora, crear_jwt, nuevo_token_opaco, sha256_hex, verificar_secreto
from app.modules.auditoria.servicios import registrar_accion, verificar_bloqueo
from app.modules.identidad.models import Empleado, EmpleadoRol, EmpleadoSede, Rol, RolPermiso, SesionRefresh


@dataclass(frozen=True)
class TokenPar:
    access_token: str
    refresh_token: str
    expira_en: int  # segundos de vida del access token


# --------------------------------------------------------------------------------------------------
# permisos / roles / sedes
# --------------------------------------------------------------------------------------------------
def permisos_de(db: Session, empleado_id: uuid.UUID) -> frozenset[str]:
    """Unión de los permisos de los roles ACTIVOS del empleado."""
    filas = db.scalars(
        select(RolPermiso.permiso_codigo)
        .join(Rol, Rol.id == RolPermiso.rol_id)
        .join(EmpleadoRol, EmpleadoRol.rol_id == Rol.id)
        .where(EmpleadoRol.empleado_id == empleado_id, Rol.activo.is_(True))
    )
    return frozenset(filas)


def roles_de(db: Session, empleado_id: uuid.UUID) -> list[Rol]:
    return list(
        db.scalars(
            select(Rol)
            .join(EmpleadoRol, EmpleadoRol.rol_id == Rol.id)
            .where(EmpleadoRol.empleado_id == empleado_id)
            .order_by(Rol.codigo)
        )
    )


def asignaciones_sede(db: Session, empleado_id: uuid.UUID) -> list[EmpleadoSede]:
    return list(db.scalars(select(EmpleadoSede).where(EmpleadoSede.empleado_id == empleado_id)))


def buscar_por_usuario(db: Session, usuario: str) -> Empleado | None:
    return db.scalar(select(Empleado).where(func.lower(Empleado.usuario) == usuario.strip().lower()))


# --------------------------------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------------------------------
def _crear_access(empleado: Empleado) -> tuple[str, int]:
    ttl = timedelta(minutes=get_settings().access_ttl_min)
    token, _ = crear_jwt({"sub": str(empleado.id), "typ": "access"}, ttl)
    return token, int(ttl.total_seconds())


def _nuevo_refresh(db: Session, empleado_id: uuid.UUID, familia_id: uuid.UUID) -> str:
    plano = nuevo_token_opaco(48)
    db.add(
        SesionRefresh(
            familia_id=familia_id,
            empleado_id=empleado_id,
            token_hash=sha256_hex(plano),
            expira_at=ahora() + timedelta(days=get_settings().refresh_ttl_dias),
            user_agent=user_agent_var.get(),
            ip=ip_var.get(),
        )
    )
    db.flush()
    return plano


def emitir_tokens(db: Session, empleado: Empleado, familia_id: uuid.UUID | None = None) -> TokenPar:
    access, expira_en = _crear_access(empleado)
    refresh = _nuevo_refresh(db, empleado.id, familia_id or uuid.uuid4())
    return TokenPar(access, refresh, expira_en)


def revocar_familia(db: Session, familia_id: uuid.UUID, motivo: str) -> int:
    r = db.execute(
        update(SesionRefresh)
        .where(SesionRefresh.familia_id == familia_id, SesionRefresh.revocado_at.is_(None))
        .values(revocado_at=ahora(), motivo_revocacion=motivo)
    )
    return r.rowcount


def revocar_sesiones_de(db: Session, empleado_id: uuid.UUID, motivo: str) -> int:
    r = db.execute(
        update(SesionRefresh)
        .where(SesionRefresh.empleado_id == empleado_id, SesionRefresh.revocado_at.is_(None))
        .values(revocado_at=ahora(), motivo_revocacion=motivo)
    )
    return r.rowcount


# --------------------------------------------------------------------------------------------------
# login / refresh / logout
# --------------------------------------------------------------------------------------------------
def login(db: Session, usuario: str, password: str) -> tuple[Empleado, TokenPar]:
    cfg = get_settings()
    empleado = buscar_por_usuario(db, usuario)
    if empleado is not None:
        verificar_bloqueo(
            db,
            accion_fallo="identidad.login_fallido",
            accion_ok="identidad.login_ok",
            maximo=cfg.max_intentos_empleado,
            actor_id=empleado.id,
        )
    # se verifica SIEMPRE (con hash falso si no existe) para no revelar por tiempo qué usuarios existen
    valido = verificar_secreto(password, empleado.password_hash if empleado else None)
    if not valido or empleado is None or not empleado.activo:
        registrar_accion(
            db,
            "identidad.login_fallido",
            actor_id=empleado.id if empleado else None,
            resultado="denegado",
            motivo="credenciales_invalidas" if not valido else "empleado_inactivo",
            despues={"usuario": usuario[:80]},
        )
        raise NoAutenticado("Usuario o contraseña incorrectos.", code="credenciales_invalidas")
    tokens = emitir_tokens(db, empleado)
    registrar_accion(db, "identidad.login_ok", actor_id=empleado.id)
    return empleado, tokens


def refrescar(db: Session, refresh_plano: str) -> TokenPar:
    fila = db.scalar(
        select(SesionRefresh).where(SesionRefresh.token_hash == sha256_hex(refresh_plano)).with_for_update()
    )
    if fila is None:
        raise NoAutenticado("Refresh token inválido.", code="refresh_invalido")
    if fila.revocado_at is not None:
        raise NoAutenticado("La sesión fue revocada.", code="refresh_invalido")
    if fila.usado_at is not None:
        # token ya rotado presentado de nuevo: posible robo -> se revoca TODA la familia
        revocar_familia(db, fila.familia_id, "reutilizacion")
        registrar_accion(
            db,
            "identidad.refresh_reutilizado",
            actor_id=fila.empleado_id,
            resultado="denegado",
            motivo="reutilizacion_de_refresh_rotado",
        )
        raise NoAutenticado("Sesión revocada por reutilización de token.", code="refresh_reutilizado")
    if fila.expira_at <= ahora():
        raise NoAutenticado("La sesión expiró; inicie sesión de nuevo.", code="refresh_expirado")
    empleado = db.get(Empleado, fila.empleado_id)
    if empleado is None or not empleado.activo:
        revocar_familia(db, fila.familia_id, "empleado_inactivo")
        raise NoAutenticado("Empleado inactivo.", code="credenciales_invalidas")
    fila.usado_at = ahora()
    access, expira_en = _crear_access(empleado)
    nuevo = _nuevo_refresh(db, empleado.id, fila.familia_id)
    return TokenPar(access, nuevo, expira_en)


def cerrar_sesion(db: Session, refresh_plano: str) -> None:
    """Revoca la familia del refresh token. Idempotente: un token desconocido no es error."""
    fila = db.scalar(select(SesionRefresh).where(SesionRefresh.token_hash == sha256_hex(refresh_plano)))
    if fila is None:
        return
    revocar_familia(db, fila.familia_id, "logout")
    registrar_accion(db, "identidad.logout", actor_id=fila.empleado_id)
