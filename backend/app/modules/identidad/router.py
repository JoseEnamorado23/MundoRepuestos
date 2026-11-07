"""Rutas de identidad: /auth (backoffice) y /empleados (administración mínima)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Actor, Db, EmpleadoActual, persistir_si_falla, requiere_permiso
from app.modules.identidad import empleados as svc_emp
from app.modules.identidad import servicios as svc
from app.modules.identidad.models import Empleado, Rol
from app.modules.identidad.schemas import (
    ActivoIn,
    EmpleadoCrearIn,
    EmpleadoOut,
    LoginIn,
    MeOut,
    PasswordIn,
    PinIn,
    RefreshIn,
    RolesIn,
    RolOut,
    SedeAsignadaOut,
    SedesIn,
    TokenOut,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
empleados_router = APIRouter(tags=["empleados"])
Admin = Annotated[Actor, Depends(requiere_permiso("admin.usuarios", canal="backoffice"))]


def empleado_out(db: Session, e: Empleado) -> EmpleadoOut:
    out = EmpleadoOut.model_validate(e)
    out.roles = [r.codigo for r in svc.roles_de(db, e.id)]
    out.sedes = [
        SedeAsignadaOut(sede_id=a.sede_id, es_sede_principal=a.es_sede_principal, tiene_pin=a.pin_hash is not None)
        for a in svc.asignaciones_sede(db, e.id)
    ]
    return out


# ------------------------------------------------------------------------------------ /auth
@auth_router.post("/login", response_model=TokenOut, summary="Login de backoffice (usuario + contraseña)")
def login(datos: LoginIn, db: Db) -> TokenOut:
    with persistir_si_falla(db):  # un login fallido queda auditado y cuenta para el bloqueo
        _, t = svc.login(db, datos.usuario, datos.password)
    return TokenOut(access_token=t.access_token, refresh_token=t.refresh_token, expira_en=t.expira_en)


@auth_router.post("/refresh", response_model=TokenOut, summary="Rota el refresh token y emite un access token nuevo")
def refresh(datos: RefreshIn, db: Db) -> TokenOut:
    with persistir_si_falla(db):  # la revocación de la familia por reutilización debe persistir
        t = svc.refrescar(db, datos.refresh_token)
    return TokenOut(access_token=t.access_token, refresh_token=t.refresh_token, expira_en=t.expira_en)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoca la sesión (familia de refresh)")
def logout(datos: RefreshIn, db: Db) -> Response:
    svc.cerrar_sesion(db, datos.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.get("/me", response_model=MeOut, summary="Empleado actual, roles, permisos y sedes")
def me(empleado: EmpleadoActual, db: Db) -> MeOut:
    return MeOut(empleado=empleado_out(db, empleado), permisos=sorted(svc.permisos_de(db, empleado.id)))


# ------------------------------------------------------------------------------------ /empleados
@empleados_router.post("/empleados", response_model=EmpleadoOut, status_code=201, summary="Crear empleado")
def crear_empleado(datos: EmpleadoCrearIn, db: Db, actor: Admin) -> EmpleadoOut:
    campos = datos.model_dump(exclude={"password", "roles", "sedes"})
    emp = svc_emp.crear(
        db, datos=campos, password=datos.password, roles=datos.roles, sedes=datos.sedes, actor_id=actor.empleado.id
    )
    return empleado_out(db, emp)


@empleados_router.get("/empleados", response_model=list[EmpleadoOut], summary="Listar empleados")
def listar_empleados(
    db: Db,
    _: Admin,
    q: str | None = Query(None, description="Nombre, usuario o documento"),
    activo: bool | None = None,
    limite: int = Query(50, ge=1, le=200),
    desplazamiento: int = Query(0, ge=0),
) -> list[EmpleadoOut]:
    return [
        empleado_out(db, e)
        for e in svc_emp.listar(db, q=q, activo=activo, limite=limite, desplazamiento=desplazamiento)
    ]


@empleados_router.get("/empleados/{empleado_id}", response_model=EmpleadoOut, summary="Detalle de un empleado")
def obtener_empleado(empleado_id: uuid.UUID, db: Db, _: Admin) -> EmpleadoOut:
    return empleado_out(db, svc_emp.obtener(db, empleado_id))


@empleados_router.put("/empleados/{empleado_id}/roles", response_model=EmpleadoOut, summary="Reemplaza los roles")
def asignar_roles(empleado_id: uuid.UUID, datos: RolesIn, db: Db, actor: Admin) -> EmpleadoOut:
    svc_emp.asignar_roles(db, empleado_id, datos.roles, actor.empleado.id)
    return empleado_out(db, svc_emp.obtener(db, empleado_id))


@empleados_router.put("/empleados/{empleado_id}/sedes", response_model=EmpleadoOut, summary="Reemplaza las sedes")
def asignar_sedes(empleado_id: uuid.UUID, datos: SedesIn, db: Db, actor: Admin) -> EmpleadoOut:
    svc_emp.asignar_sedes(db, empleado_id, datos.sedes, datos.sede_principal, actor.empleado.id)
    return empleado_out(db, svc_emp.obtener(db, empleado_id))


@empleados_router.post("/empleados/{empleado_id}/password", status_code=204, summary="Cambiar contraseña")
def cambiar_password(empleado_id: uuid.UUID, datos: PasswordIn, db: Db, actor: Admin) -> Response:
    svc_emp.cambiar_password(db, empleado_id, datos.password, actor.empleado.id)
    return Response(status_code=204)


@empleados_router.post("/empleados/{empleado_id}/pin", status_code=204, summary="Cambiar PIN del POS (por sede)")
def cambiar_pin(empleado_id: uuid.UUID, datos: PinIn, db: Db, actor: Admin) -> Response:
    svc_emp.cambiar_pin(db, empleado_id, datos.pin, datos.sede_id, actor.empleado.id)
    return Response(status_code=204)


@empleados_router.patch(
    "/empleados/{empleado_id}/activo",
    response_model=EmpleadoOut,
    summary="Activar o desactivar (no hay borrado físico)",
)
def cambiar_activo(empleado_id: uuid.UUID, datos: ActivoIn, db: Db, actor: Admin) -> EmpleadoOut:
    return empleado_out(db, svc_emp.cambiar_activo(db, empleado_id, datos.activo, actor.empleado.id))


@empleados_router.get("/roles", response_model=list[RolOut], summary="Listar roles")
def listar_roles(db: Db, _: Admin) -> list[Rol]:
    return list(db.scalars(select(Rol).order_by(Rol.codigo)))
