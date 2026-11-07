"""Configuración de la aplicación (pydantic-settings). Las variables vienen del entorno o de ../.env."""

from __future__ import annotations

import uuid
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ_REPO = Path(__file__).resolve().parents[3]

# Nodo "nube": UUID fijo y conocido, sembrado por la migración 0004 (idéntico en todos los nodos).
NODO_NUBE_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")


def _alias(nombre: str) -> AliasChoices:
    return AliasChoices(nombre.upper(), nombre)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RAIZ_REPO / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # entorno: desarrollo | pruebas | produccion (en produccion no hay /docs ni datos-demo)
    env: Literal["desarrollo", "pruebas", "produccion"] = Field("desarrollo", validation_alias=_alias("env"))
    # edge = servidor en la tienda; cloud = nube. Mismo backend, mismo esquema.
    mode: Literal["edge", "cloud"] = Field("edge", validation_alias=_alias("mode"))
    database_url: str | None = Field(None, validation_alias=_alias("database_url"))
    # UUID del nodo actual (organizacion.nodos). En modo cloud, si falta, se usa el nodo nube fijo.
    nodo_id: uuid.UUID | None = Field(None, validation_alias=_alias("nodo_id"))

    # --- API ---
    log_level: str = Field("INFO", validation_alias=_alias("log_level"))
    cors_origins: str = Field("", validation_alias=_alias("cors_origins"))  # separados por coma

    # --- Seguridad ---
    jwt_secret: str | None = Field(None, validation_alias=_alias("jwt_secret"))
    jwt_algoritmo: str = "HS256"
    access_ttl_min: int = Field(15, validation_alias=_alias("access_ttl_min"))
    refresh_ttl_dias: int = Field(7, validation_alias=_alias("refresh_ttl_dias"))
    pos_sesion_ttl_min: int = Field(600, validation_alias=_alias("pos_sesion_ttl_min"))
    # pimienta (secreto del servidor) para el índice de búsqueda del PIN (HMAC); NO cambiarla con datos cargados
    pin_pepper: str | None = Field(None, validation_alias=_alias("pin_pepper"))
    password_longitud_min: int = Field(8, validation_alias=_alias("password_longitud_min"))

    # --- Fuerza bruta (login y PIN) ---
    max_intentos_dispositivo: int = Field(5, validation_alias=_alias("max_intentos_dispositivo"))
    max_intentos_empleado: int = Field(5, validation_alias=_alias("max_intentos_empleado"))
    bloqueo_minutos: int = Field(15, validation_alias=_alias("bloqueo_minutos"))

    # --- Catálogo / inventario ---
    media_dir: str = Field(
        "media", validation_alias=_alias("media_dir")
    )  # relativo a la raíz del repo si no es absoluto
    imagen_max_mb: int = Field(5, validation_alias=_alias("imagen_max_mb"))
    # un ajuste de inventario cuyo valor (|cantidad| x costo) supere este umbral exige autorización de supervisor
    # (valor por defecto; cada sede puede fijar el suyo en configuracion_sede, clave 'inventario.umbral_aprobacion')
    ajuste_umbral_valor: Decimal = Field(Decimal("500000"), validation_alias=_alias("ajuste_umbral_valor"))

    # --- Búsqueda aproximada (errores de digitación): vecinos más cercanos con trigramas (GiST) ---
    busqueda_difusa_limite: int = Field(20, ge=1, le=200, validation_alias=_alias("busqueda_difusa_limite"))
    busqueda_difusa_timeout_ms: int = Field(300, ge=10, le=10000, validation_alias=_alias("busqueda_difusa_timeout_ms"))
    busqueda_difusa_umbral: float = Field(0.3, ge=0.05, le=1.0, validation_alias=_alias("busqueda_difusa_umbral"))

    # --- Autorización de supervisor ---
    autorizacion_ttl_seg: int = Field(120, validation_alias=_alias("autorizacion_ttl_seg"))

    @field_validator("nodo_id", "database_url", "jwt_secret", "pin_pepper", mode="before")
    @classmethod
    def _vacio_es_none(cls, v):
        """Una variable vacía en .env (copiada de .env.example) equivale a 'no definida'."""
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def es_produccion(self) -> bool:
        return self.env == "produccion"

    @property
    def es_edge(self) -> bool:
        return self.mode == "edge"

    @property
    def origenes_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


class ConfiguracionInvalida(RuntimeError):
    """Faltan o son inválidas variables obligatorias; el mensaje explica cuáles y cómo obtenerlas."""


_COMO = {
    "DATABASE_URL": "URL de PostgreSQL, p. ej. postgresql+psycopg://USUARIO:CLAVE@localhost:5460/mundorepuestos "
    "(use el usuario/clave/puerto de POSTGRES_* y DB_PORT).",
    "JWT_SECRET": 'mínimo 32 caracteres. Genérelo con: python -c "import secrets; print(secrets.token_urlsafe(48))"',
    "PIN_PEPPER": 'secreto del servidor para el índice de PIN. Genérelo con: python -c "import secrets; '
    'print(secrets.token_urlsafe(32))". NO lo cambie una vez cargados PIN de empleados.',
    "NODO_ID": "UUID del nodo de ESTA instalación. Véalo con: uv run python -m app.cli nodos listar "
    "(o cree el nodo de la sede con: uv run python -m app.cli datos-demo).",
}


def validar_configuracion(cfg: Settings | None = None, *, requiere_nodo: bool = True) -> Settings:
    """Comprueba las variables obligatorias y falla con un mensaje claro de qué falta y cómo obtenerlo."""
    cfg = cfg or get_settings()
    problemas: list[str] = []
    if not cfg.database_url:
        problemas.append(f"- Falta DATABASE_URL: {_COMO['DATABASE_URL']}")
    if not cfg.jwt_secret:
        problemas.append(f"- Falta JWT_SECRET: {_COMO['JWT_SECRET']}")
    elif len(cfg.jwt_secret) < 32:
        problemas.append(f"- JWT_SECRET es demasiado corto ({len(cfg.jwt_secret)} caracteres): {_COMO['JWT_SECRET']}")
    if not cfg.pin_pepper:
        problemas.append(f"- Falta PIN_PEPPER: {_COMO['PIN_PEPPER']}")
    if requiere_nodo and cfg.nodo_id is None and cfg.mode != "cloud":
        problemas.append(f"- Falta NODO_ID (MODE=edge): {_COMO['NODO_ID']}")
    if problemas:
        raise ConfiguracionInvalida(
            "Configuración incompleta (defínala en el archivo .env de la raíz del repositorio o como variable de "
            "entorno):\n" + "\n".join(problemas)
        )
    return cfg


@lru_cache
def get_settings() -> Settings:
    return Settings()
