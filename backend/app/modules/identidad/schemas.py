"""Esquemas Pydantic de la API de identidad."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    usuario: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expira_en: int = Field(description="Segundos de vida del access token")


class SedeAsignadaOut(BaseModel):
    sede_id: uuid.UUID
    es_sede_principal: bool
    tiene_pin: bool


class EmpleadoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tipo_documento_codigo: str
    numero_documento: str
    nombres: str
    apellidos: str
    email: str | None = None
    telefono: str | None = None
    usuario: str | None = None
    codigo_carne: str | None = None
    activo: bool
    roles: list[str] = []
    sedes: list[SedeAsignadaOut] = []


class MeOut(BaseModel):
    empleado: EmpleadoOut
    permisos: list[str]


class EmpleadoCrearIn(BaseModel):
    tipo_documento_codigo: str = Field(min_length=1, max_length=4)
    numero_documento: str = Field(min_length=3, max_length=30)
    nombres: str = Field(min_length=1, max_length=120)
    apellidos: str = Field(min_length=1, max_length=120)
    email: str | None = Field(None, max_length=200)
    telefono: str | None = Field(None, max_length=40)
    usuario: str | None = Field(None, min_length=3, max_length=80)
    password: str | None = Field(None, max_length=200)
    codigo_carne: str | None = Field(None, min_length=3, max_length=60)
    roles: list[str] = []
    sedes: list[uuid.UUID] = []


class RolesIn(BaseModel):
    roles: list[str]


class SedesIn(BaseModel):
    sedes: list[uuid.UUID]
    sede_principal: uuid.UUID | None = None


class PasswordIn(BaseModel):
    password: str = Field(max_length=200)


class PinIn(BaseModel):
    pin: str = Field(pattern=r"^[0-9]{6}$", description="Exactamente 6 dígitos")
    sede_id: uuid.UUID | None = Field(None, description="Si se omite, se aplica a todas las sedes del empleado")


class ActivoIn(BaseModel):
    activo: bool


class RolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    codigo: str
    nombre: str
    es_sistema: bool
    activo: bool
