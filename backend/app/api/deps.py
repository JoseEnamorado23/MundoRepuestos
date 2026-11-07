"""Dependencias reutilizables de la API: sesión de BD, autenticación y permisos.

* `Db`: una sesión por petición; **commit al final y rollback ante cualquier error**. Los servicios no hacen commit.
  Se usa `scope="function"`: el commit ocurre ANTES de enviar la respuesta, así un fallo de integridad al confirmar
  llega al cliente como `problem+json` y no como respuesta 200 ya enviada.
* `persistir_si_falla(db)`: excepción deliberada para los flujos de autenticación, donde un intento FALLIDO debe quedar
  auditado y contado para el bloqueo aunque la petición termine en error.
* `get_empleado_actual` (token de backoffice), `get_sesion_pos` (token de sesión POS) y `requiere_permiso("codigo")`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_sessionmaker
from app.core.errores import ErrorDominio, NoAutenticado, PermisoDenegado
from app.core.seguridad import decodificar_jwt
from app.modules.cajas.models import Dispositivo
from app.modules.identidad.models import Empleado, EmpleadoSede
from app.modules.identidad.servicios import permisos_de


def get_db() -> Iterator[Session]:
    with get_sessionmaker()() as sesion:
        try:
            yield sesion
            sesion.commit()
        except BaseException:
            sesion.rollback()
            raise


Db = Annotated[Session, Depends(get_db, scope="function")]


@contextmanager
def persistir_si_falla(db: Session) -> Iterator[None]:
    """Confirma lo escrito (auditoría del intento) si el bloque termina en un error de dominio, y relanza."""
    try:
        yield
    except ErrorDominio:
        db.commit()
        raise


# --------------------------------------------------------------------------------------------------
# autenticación
# --------------------------------------------------------------------------------------------------
_bearer = HTTPBearer(auto_error=False, description="Access token (backoffice) o token de sesión POS")


def _token(cred: HTTPAuthorizationCredentials | None) -> str:
    if cred is None or cred.scheme.lower() != "bearer":
        raise NoAutenticado("Falta el encabezado Authorization: Bearer <token>.", code="token_ausente")
    return cred.credentials


@dataclass(frozen=True)
class SesionPos:
    empleado: Empleado
    dispositivo_id: uuid.UUID
    caja_id: uuid.UUID
    sede_id: uuid.UUID


@dataclass(frozen=True)
class Actor:
    """Quién hace la petición, venga de backoffice o del POS."""

    empleado: Empleado
    permisos: frozenset[str]
    canal: Literal["backoffice", "pos"]
    pos: SesionPos | None = None


def _empleado_activo(db: Session, empleado_id: str) -> Empleado:
    try:
        emp = db.get(Empleado, uuid.UUID(empleado_id))
    except ValueError:
        emp = None
    if emp is None or not emp.activo:
        raise NoAutenticado("El empleado no existe o está inactivo.", code="token_invalido")
    return emp


def get_empleado_actual(db: Db, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> Empleado:
    datos = decodificar_jwt(_token(cred), tipo="access")
    return _empleado_activo(db, datos["sub"])


def get_sesion_pos(db: Db, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> SesionPos:
    datos = decodificar_jwt(_token(cred), tipo="pos")
    emp = _empleado_activo(db, datos["sub"])
    disp = db.get(Dispositivo, uuid.UUID(datos["dsp"]))
    if disp is None or disp.estado != "activo" or str(disp.caja_id) != datos["caja"]:
        raise NoAutenticado("El dispositivo ya no está activo.", code="dispositivo_invalido")
    asignado = db.get(EmpleadoSede, (emp.id, disp.sede_id))
    if asignado is None:
        raise NoAutenticado("El empleado ya no está asignado a la sede.", code="token_invalido")
    return SesionPos(emp, disp.id, disp.caja_id, disp.sede_id)


def get_actor(db: Db, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> Actor:
    """Acepta token de backoffice o de POS (según el claim `typ`)."""
    token = _token(cred)
    try:
        decodificar_jwt(token, tipo="access")
    except NoAutenticado as e:
        if e.code == "token_expirado":
            raise
        sesion = get_sesion_pos(db, cred)
        return Actor(sesion.empleado, permisos_de(db, sesion.empleado.id), "pos", sesion)
    emp = get_empleado_actual(db, cred)
    return Actor(emp, permisos_de(db, emp.id), "backoffice")


def requiere_permiso(codigo: str, *, canal: Literal["backoffice", "pos", "cualquiera"] = "cualquiera"):
    """Dependencia de endpoint: exige el permiso `codigo` (y opcionalmente el canal). Devuelve el `Actor`."""

    def dependencia(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
        if canal != "cualquiera" and actor.canal != canal:
            raise PermisoDenegado(
                f"Este recurso solo está disponible desde el canal {canal}.", code="canal_no_permitido"
            )
        if codigo not in actor.permisos:
            raise PermisoDenegado(f"Falta el permiso '{codigo}'.", code="permiso_denegado", permiso=codigo)
        return actor

    dependencia.__name__ = f"requiere_{codigo.replace('.', '_')}"
    return dependencia


EmpleadoActual = Annotated[Empleado, Depends(get_empleado_actual)]
SesionPosActual = Annotated[SesionPos, Depends(get_sesion_pos)]


def sede_efectiva(db: Session, actor: Actor, sede_id: uuid.UUID | None = None) -> uuid.UUID | None:
    """Sede sobre la que opera la petición: la de la sesión POS; en backoffice, la indicada o la principal del empleado."""
    if actor.pos is not None:
        return actor.pos.sede_id
    asignaciones = db.query(EmpleadoSede).filter(EmpleadoSede.empleado_id == actor.empleado.id).all()
    if sede_id is not None:
        if asignaciones and sede_id not in {a.sede_id for a in asignaciones} and "admin.usuarios" not in actor.permisos:
            raise PermisoDenegado("No está asignado a esa sede.", code="sede_no_asignada")
        return sede_id
    principal = next((a for a in asignaciones if a.es_sede_principal), None) or (
        asignaciones[0] if asignaciones else None
    )
    return principal.sede_id if principal else None
