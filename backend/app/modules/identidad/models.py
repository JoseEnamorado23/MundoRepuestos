"""Schema `identidad`: empleados, roles/permisos, terceros, cuentas de clientes, direcciones, autorizaciones (§5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, Mutable, SoloAgregar, nodo_actual, pg_enum, uuid7
from app.core.helpers import fk, fkt, flag, ts, txt

SCHEMA = "identidad"
EstadoCuenta = pg_enum(SCHEMA, "estado_cuenta", "pendiente_verificacion", "activa", "bloqueada")
TipoDireccion = pg_enum(SCHEMA, "tipo_direccion", "envio", "facturacion")
TipoAutorizacion = pg_enum(
    SCHEMA,
    "tipo_autorizacion",
    "descuento_mayor",
    "anulacion",
    "devolucion",
    "precio_manual",
    "retiro_efectivo",
    "cierre_con_diferencia",
    "ajuste_inventario",
    "venta_sin_stock",
)


def _creado() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Empleado(Base, Mutable):
    __tablename__ = "empleados"
    __table_args__ = (
        UniqueConstraint("tipo_documento_codigo", "numero_documento", name="uq_empleados_documento"),
        Index("uq_empleados_carne", "codigo_carne", unique=True, postgresql_where=text("codigo_carne IS NOT NULL")),
        CheckConstraint("activo = false OR usuario IS NOT NULL OR codigo_carne IS NOT NULL", name="credencial"),
        {"schema": SCHEMA},
    )
    tipo_documento_codigo: Mapped[str] = fkt("referencia.tipos_documento_identidad.codigo")
    numero_documento: Mapped[str] = txt()
    nombres: Mapped[str] = txt()
    apellidos: Mapped[str] = txt()
    email: Mapped[str | None] = txt(null=True)
    telefono: Mapped[str | None] = txt(null=True)
    usuario: Mapped[str | None] = txt(null=True)  # unicidad lower(usuario): migración 0003
    password_hash: Mapped[str | None] = txt(null=True)
    codigo_carne: Mapped[str | None] = txt(null=True)
    activo: Mapped[bool] = flag(True)


class Rol(Base, Mutable):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("codigo", name="uq_roles_codigo"), {"schema": SCHEMA})
    codigo: Mapped[str] = txt()
    nombre: Mapped[str] = txt()
    descripcion: Mapped[str | None] = txt(null=True)
    es_sistema: Mapped[bool] = flag(False)
    activo: Mapped[bool] = flag(True)


class Permiso(Base):
    __tablename__ = "permisos"
    __table_args__ = (
        CheckConstraint(r"codigo ~ '^[a-z_]+(\.[a-z_]+){1,2}$'", name="codigo_formato"),
        {"schema": SCHEMA},
    )
    codigo: Mapped[str] = mapped_column(Text, primary_key=True)
    modulo: Mapped[str] = txt()
    descripcion: Mapped[str] = txt()
    requiere_autorizacion: Mapped[bool] = flag(False)


class RolPermiso(Base):
    __tablename__ = "roles_permisos"
    __table_args__ = (Index("ix_roles_permisos_permiso_codigo", "permiso_codigo"), {"schema": SCHEMA})
    rol_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.roles.id", ondelete="CASCADE"), primary_key=True
    )
    permiso_codigo: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.permisos.codigo", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = _creado()


class EmpleadoRol(Base):
    __tablename__ = "empleados_roles"
    __table_args__ = (Index("ix_empleados_roles_rol_id", "rol_id"), {"schema": SCHEMA})
    empleado_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.empleados.id", ondelete="RESTRICT"), primary_key=True
    )
    rol_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.roles.id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = _creado()


class EmpleadoSede(Base):
    """Asignación empleado-sede. El PIN del POS es POR SEDE (0006): `pin_lookup` = HMAC(pimienta, sede:PIN), único por
    sede, identifica al empleado solo con el PIN; `pin_hash` (argon2id) es la verificación real."""

    __tablename__ = "empleados_sedes"
    __table_args__ = (
        Index("ix_empleados_sedes_sede_id", "sede_id"),
        Index(
            "uq_empleados_sedes_pin",
            "sede_id",
            "pin_lookup",
            unique=True,
            postgresql_where=text("pin_lookup IS NOT NULL"),
        ),
        CheckConstraint("(pin_hash IS NULL) = (pin_lookup IS NULL)", name="pin_par"),
        {"schema": SCHEMA},
    )
    empleado_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.empleados.id", ondelete="RESTRICT"), primary_key=True
    )
    sede_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizacion.sedes.id", ondelete="RESTRICT"), primary_key=True
    )
    es_sede_principal: Mapped[bool] = flag(False)
    pin_hash: Mapped[str | None] = txt(null=True)
    pin_lookup: Mapped[str | None] = txt(null=True)
    created_at: Mapped[datetime] = _creado()


class Tercero(Base, Mutable):
    __tablename__ = "terceros"
    __table_args__ = (
        # búsqueda por NIT/cédula del POS; los fusionados se conservan sin chocar
        Index(
            "uq_terceros_documento",
            "tipo_documento_codigo",
            "numero_documento",
            unique=True,
            postgresql_where=text("fusionado_en_id IS NULL"),
        ),
        Index("ix_terceros_proveedores", "nombre_completo", postgresql_where=text("es_proveedor")),
        CheckConstraint(
            "es_consumidor_final "
            "OR (tipo_persona_codigo = '1' AND razon_social IS NOT NULL) "
            "OR (tipo_persona_codigo = '2' AND primer_nombre IS NOT NULL AND primer_apellido IS NOT NULL)",
            name="nombre",
        ),
        CheckConstraint("tipo_documento_codigo <> '31' OR dv IS NOT NULL", name="dv_nit"),
        CheckConstraint(
            "es_consumidor_final = (numero_documento = '222222222222' AND tipo_documento_codigo = '13')",
            name="consumidor_final",
        ),
        CheckConstraint("fusionado_en_id IS DISTINCT FROM id", name="fusion"),
        {"schema": SCHEMA},
    )
    tipo_persona_codigo: Mapped[str] = fkt("referencia.tipos_persona.codigo")
    tipo_documento_codigo: Mapped[str] = fkt("referencia.tipos_documento_identidad.codigo")
    numero_documento: Mapped[str] = txt()
    dv: Mapped[int | None] = mapped_column(SmallInteger)
    razon_social: Mapped[str | None] = txt(null=True)
    primer_nombre: Mapped[str | None] = txt(null=True)
    segundo_nombre: Mapped[str | None] = txt(null=True)
    primer_apellido: Mapped[str | None] = txt(null=True)
    segundo_apellido: Mapped[str | None] = txt(null=True)
    nombre_completo: Mapped[str] = txt()
    nombre_comercial: Mapped[str | None] = txt(null=True)
    regimen_codigo: Mapped[str | None] = fkt("referencia.regimenes.codigo", null=True)
    email_facturacion: Mapped[str | None] = txt(null=True)
    telefono: Mapped[str | None] = txt(null=True)
    municipio_codigo: Mapped[str | None] = fkt("referencia.municipios.codigo", null=True)
    direccion_fiscal: Mapped[str | None] = txt(null=True)
    es_cliente: Mapped[bool] = flag(True)
    es_proveedor: Mapped[bool] = flag(False)
    es_consumidor_final: Mapped[bool] = flag(False)
    fusionado_en_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.terceros.id", null=True)
    activo: Mapped[bool] = flag(True)


class TerceroResponsabilidad(Base):
    __tablename__ = "terceros_responsabilidades"
    __table_args__ = {"schema": SCHEMA}
    tercero_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.terceros.id", ondelete="CASCADE"), primary_key=True
    )
    responsabilidad_codigo: Mapped[str] = mapped_column(
        Text, ForeignKey("referencia.responsabilidades_fiscales.codigo", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = _creado()


class CuentaCliente(Base, Mutable):
    __tablename__ = "cuentas_clientes"
    __table_args__ = (UniqueConstraint("tercero_id", name="uq_cuentas_clientes_tercero"), {"schema": SCHEMA})
    tercero_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.terceros.id")
    email: Mapped[str] = txt()  # unicidad lower(email): migración 0003
    password_hash: Mapped[str | None] = txt(null=True)
    estado: Mapped[str] = mapped_column(EstadoCuenta, nullable=False, server_default="pendiente_verificacion")
    email_verificado_at: Mapped[datetime | None] = ts()
    acepta_terminos_at: Mapped[datetime] = ts(null=False)
    acepta_marketing: Mapped[bool] = flag(False)
    ultimo_login_at: Mapped[datetime | None] = ts()


class Direccion(Base, Mutable):
    __tablename__ = "direcciones"
    __table_args__ = (
        Index(
            "uq_direcciones_predeterminada",
            "tercero_id",
            "tipo",
            unique=True,
            postgresql_where=text("es_predeterminada AND activo"),
        ),
        {"schema": SCHEMA},
    )
    tercero_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.terceros.id", index=True)
    tipo: Mapped[str] = mapped_column(TipoDireccion, nullable=False, server_default="envio")
    alias: Mapped[str] = txt()
    destinatario_nombre: Mapped[str] = txt()
    destinatario_telefono: Mapped[str] = txt()
    municipio_codigo: Mapped[str] = fkt("referencia.municipios.codigo")
    direccion: Mapped[str] = txt()
    complemento: Mapped[str | None] = txt(null=True)
    barrio: Mapped[str | None] = txt(null=True)
    indicaciones: Mapped[str | None] = txt(null=True)
    es_predeterminada: Mapped[bool] = flag(False)
    activo: Mapped[bool] = flag(True)


class Autorizacion(Base, SoloAgregar):
    __tablename__ = "autorizaciones"
    __table_args__ = (
        CheckConstraint("autorizado_por_id <> solicitado_por_id", name="no_autoautorizacion"),
        Index("ix_autorizaciones_entidad", "entidad_tipo", "entidad_id"),
        Index("ix_autorizaciones_autorizador", "autorizado_por_id", text("created_at DESC")),
        {"schema": SCHEMA},
    )
    tipo: Mapped[str] = mapped_column(TipoAutorizacion, nullable=False)
    permiso_codigo: Mapped[str] = fkt(f"{SCHEMA}.permisos.codigo")
    solicitado_por_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.empleados.id")
    autorizado_por_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.empleados.id")
    dispositivo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # referencia lógica a cajas.dispositivos
    entidad_tipo: Mapped[str | None] = txt(null=True)
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    motivo: Mapped[str | None] = txt(null=True)
    expira_at: Mapped[datetime] = ts(null=False)  # 0006: autorización de un solo uso con vencimiento corto


class AutorizacionConsumo(Base):
    """Un consumo por autorización (la PK lo garantiza de forma atómica). Append-only (tg_inmutable, 0006)."""

    __tablename__ = "autorizaciones_consumos"
    __table_args__ = {"schema": SCHEMA}
    autorizacion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.autorizaciones.id", ondelete="RESTRICT"), primary_key=True
    )
    consumida_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    consumida_por_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.empleados.id")
    dispositivo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    entidad_tipo: Mapped[str | None] = txt(null=True)
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    nodo_origen_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizacion.nodos.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        nullable=False,
        default=nodo_actual,
    )


class SesionRefresh(Base):
    """Refresh tokens opacos (solo se guarda el SHA-256). `familia_id` agrupa la cadena de rotaciones: reutilizar un
    token ya rotado revoca toda la familia. Local del nodo (no se sincroniza)."""

    __tablename__ = "sesiones_refresh"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sesiones_refresh_token_hash"),
        Index("ix_sesiones_refresh_familia_id", "familia_id"),
        Index("ix_sesiones_refresh_empleado_id", "empleado_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    familia_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    empleado_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.empleados.id")
    token_hash: Mapped[str] = txt()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expira_at: Mapped[datetime] = ts(null=False)
    usado_at: Mapped[datetime | None] = ts()  # rotado: ya canjeado por uno nuevo
    revocado_at: Mapped[datetime | None] = ts()
    motivo_revocacion: Mapped[str | None] = txt(null=True)
    user_agent: Mapped[str | None] = txt(null=True)
    ip: Mapped[str | None] = mapped_column(INET)
