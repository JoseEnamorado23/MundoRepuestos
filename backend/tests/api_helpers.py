"""Ayudas para pruebas de API: crean empleados/dispositivos con los servicios reales y hacen login."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.modules.cajas import servicios as svc_cajas
from app.modules.identidad import empleados as svc_emp
from app.modules.identidad.models import Empleado
from tests import factories as f

PASSWORD = "Clave-Segura-123"
_c = 0


def _n() -> int:
    global _c
    _c += 1
    return _c


def crear_empleado(
    db: Session,
    *,
    roles: list[str],
    sedes: list[uuid.UUID],
    usuario: str | None = None,
    pin: str | None = None,
    carne: str | None = None,
    password: str = PASSWORD,
) -> Empleado:
    n = _n()
    usuario = usuario or f"user{n}"
    emp = svc_emp.crear(
        db,
        datos=dict(
            tipo_documento_codigo="13",
            numero_documento=f"{7000000 + n}",
            nombres=f"Nombre{n}",
            apellidos=f"Apellido{n}",
            usuario=usuario,
            codigo_carne=carne,
        ),
        password=password,
        roles=roles,
        sedes=sedes,
        actor_id=None,
    )
    if pin:
        svc_emp.cambiar_pin(db, emp.id, pin, None, None)
    db.commit()
    return emp


@dataclass
class Mundo:
    """Una sede con caja y dispositivo activo, más una segunda sede, y empleados típicos."""

    ent: dict
    sede2: str
    dispositivo_id: uuid.UUID
    token_dispositivo: str
    admin: Empleado
    cajero: Empleado
    supervisor: Empleado
    extra: dict = field(default_factory=dict)

    @property
    def sede(self) -> str:
        return self.ent["sede"]

    @property
    def caja(self) -> str:
        return self.ent["caja"]

    def cabecera_disp(self, token: str | None = None) -> dict:
        return {"X-Dispositivo-Token": token or self.token_dispositivo}


def construir_mundo(conn, db: Session) -> Mundo:
    ent = f.entorno_pos(conn)
    sede2 = f.sede(conn, ent["empresa"])
    sede = uuid.UUID(ent["sede"])
    admin = crear_empleado(db, roles=["administrador"], sedes=[sede], usuario="admin")
    cajero = crear_empleado(db, roles=["cajero"], sedes=[sede], pin="111111", carne="CARNE-CAJERO")
    supervisor = crear_empleado(db, roles=["supervisor"], sedes=[sede], pin="999999")
    disp, token = svc_cajas.crear_dispositivo(db, uuid.UUID(ent["caja"]), "POS 1", admin.id)
    db.commit()
    return Mundo(ent, sede2, disp.id, token, admin, cajero, supervisor)


def login(client, usuario: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"usuario": usuario, "password": password})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def token_de(client, usuario: str, password: str = PASSWORD) -> str:
    r = login(client, usuario, password)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def sesion_pos(client, mundo: Mundo, pin: str):
    r = client.post("/api/v1/pos/auth/pin", json={"pin": pin}, headers=mundo.cabecera_disp())
    assert r.status_code == 200, r.text
    return r.json()["token"]
