"""Schema `fiscal` (Fase 1): resoluciones, documentos fiscales y bitácora (§12). Proveedor inicial: Factus.

`documentos_fiscales.numero_completo` es columna generada (migración 0003). `documento_soporte_id` llega en la
Fase 2. El número lo asigna el proveedor: `prefijo`/`consecutivo` son NULL hasta su respuesta.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    FetchedValue,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import CANTIDAD, DINERO, PCT, PRECIO, Base, Mutable, SoloAgregar, pg_enum
from app.core.helpers import fk, fkt, flag, ts, txt

SCHEMA = "fiscal"
AmbienteDian = pg_enum(SCHEMA, "ambiente_dian", "habilitacion", "produccion")
ModoNumeracion = pg_enum(SCHEMA, "modo_numeracion", "proveedor", "local")
EstadoResolucion = pg_enum(SCHEMA, "estado_resolucion", "borrador", "activa", "agotada", "vencida", "anulada")
EstadoDocumentoFiscal = pg_enum(
    SCHEMA,
    "estado_documento_fiscal",
    "borrador",
    "pendiente_envio",
    "enviado",
    "aceptado",
    "rechazado",
    "contingencia",
)
TipoEventoFiscal = pg_enum(
    SCHEMA,
    "tipo_evento_fiscal",
    "creado",
    "envio_solicitado",
    "respuesta_proveedor",
    "respuesta_dian",
    "error_tecnico",
    "reintento_programado",
    "contingencia_activada",
    "contingencia_transmitida",
    "estado_consultado",
    "webhook_proveedor",
)


class ConfiguracionProveedor(Base, Mutable):
    __tablename__ = "configuracion_proveedor"
    __table_args__ = (
        Index("uq_configuracion_proveedor_activo", "empresa_id", unique=True, postgresql_where=text("activo")),
        {"schema": SCHEMA},
    )
    empresa_id: Mapped[uuid.UUID] = fk("organizacion.empresas.id")
    proveedor: Mapped[str] = txt()
    ambiente: Mapped[str] = mapped_column(AmbienteDian, nullable=False, server_default="habilitacion")
    url_base: Mapped[str] = txt()
    credenciales_ref: Mapped[str] = txt()
    set_pruebas_id: Mapped[str | None] = txt(null=True)
    parametros: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    activo: Mapped[bool] = flag(True)


class ResolucionNumeracion(Base, Mutable):
    __tablename__ = "resoluciones_numeracion"
    __table_args__ = (
        CheckConstraint("caja_id IS NULL OR sede_id IS NOT NULL", name="alcance"),
        CheckConstraint("modo_numeracion <> 'proveedor' OR id_rango_proveedor IS NOT NULL", name="rango_proveedor"),
        CheckConstraint("modo_numeracion <> 'local' OR nodo_propietario_id IS NOT NULL", name="propietario_local"),
        CheckConstraint(r"prefijo ~ '^[A-Z0-9]{0,4}$'", name="prefijo_formato"),
        CheckConstraint("rango_desde >= 1 AND rango_hasta >= rango_desde", name="rango_valido"),
        CheckConstraint("consecutivo_actual BETWEEN rango_desde - 1 AND rango_hasta", name="consecutivo_en_rango"),
        CheckConstraint("vigente_hasta > vigente_desde", name="vigencia_valida"),
        Index(
            "uq_resoluciones_activa_caja",
            "caja_id",
            "tipo_documento_codigo",
            unique=True,
            postgresql_where=text("estado = 'activa' AND caja_id IS NOT NULL"),
        ),
        Index(
            "uq_resoluciones_activa_sede",
            "sede_id",
            "tipo_documento_codigo",
            unique=True,
            postgresql_where=text("estado = 'activa' AND caja_id IS NULL AND sede_id IS NOT NULL"),
        ),
        Index(
            "uq_resoluciones_activa_empresa",
            "empresa_id",
            "tipo_documento_codigo",
            unique=True,
            postgresql_where=text("estado = 'activa' AND sede_id IS NULL"),
        ),
        Index("ix_resoluciones_propietario", "nodo_propietario_id", "estado"),
        {"schema": SCHEMA},  # EXCLUDE de rangos solapados: migración 0003
    )
    empresa_id: Mapped[uuid.UUID] = fk("organizacion.empresas.id")
    sede_id: Mapped[uuid.UUID | None] = fk("organizacion.sedes.id", null=True)
    caja_id: Mapped[uuid.UUID | None] = fk("cajas.cajas.id", null=True)
    modo_numeracion: Mapped[str] = mapped_column(ModoNumeracion, nullable=False, server_default="proveedor")
    id_rango_proveedor: Mapped[str | None] = txt(null=True)  # numbering_range_id de Factus
    nodo_propietario_id: Mapped[uuid.UUID | None] = fk("organizacion.nodos.id", null=True)
    tipo_documento_codigo: Mapped[str] = fkt("referencia.tipos_documento_fiscal.codigo")
    numero_resolucion: Mapped[str] = txt()
    fecha_resolucion: Mapped[date] = mapped_column(Date, nullable=False)
    prefijo: Mapped[str] = txt(server_default="")
    rango_desde: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rango_hasta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consecutivo_actual: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vigente_desde: Mapped[date] = mapped_column(Date, nullable=False)
    vigente_hasta: Mapped[date] = mapped_column(Date, nullable=False)
    clave_tecnica_ref: Mapped[str | None] = txt(null=True)
    estado: Mapped[str] = mapped_column(EstadoResolucion, nullable=False, server_default="borrador")


class DocumentoFiscal(Base, Mutable):
    """Contenido inmutable tras salir de `borrador`; solo cambian las columnas de transporte (trigger, 0003)."""

    __tablename__ = "documentos_fiscales"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tipo_documento_codigo", "concepto_nota_codigo"],
            ["referencia.conceptos_nota.tipo_documento_codigo", "referencia.conceptos_nota.codigo"],
            name="fk_documentos_fiscales_concepto_nota",
            ondelete="RESTRICT",
        ),
        CheckConstraint("num_nonnulls(venta_id, devolucion_id) = 1", name="origen"),
        CheckConstraint(
            "tipo_documento_codigo NOT IN ('NC','ND','NA') "
            "OR (documento_referenciado_id IS NOT NULL AND concepto_nota_codigo IS NOT NULL)",
            name="nota",
        ),
        CheckConstraint(
            "estado <> 'aceptado' OR (cufe_cude IS NOT NULL AND aceptado_at IS NOT NULL AND consecutivo IS NOT NULL)",
            name="aceptado",
        ),
        CheckConstraint("(prefijo IS NULL) = (consecutivo IS NULL)", name="numero_par"),
        CheckConstraint("total = subtotal + impuesto_total + redondeo", name="total"),
        Index(
            "uq_documentos_fiscales_numero",
            "empresa_id",
            "tipo_documento_codigo",
            "prefijo",
            "consecutivo",
            unique=True,
            postgresql_where=text("consecutivo IS NOT NULL"),
        ),
        Index(
            "uq_documentos_fiscales_resolucion",
            "resolucion_id",
            "consecutivo",
            unique=True,
            postgresql_where=text("consecutivo IS NOT NULL"),
        ),
        Index("uq_documentos_fiscales_cufe", "cufe_cude", unique=True, postgresql_where=text("cufe_cude IS NOT NULL")),
        Index(
            "uq_documentos_fiscales_proveedor",
            "resolucion_id",
            "proveedor_documento_id",
            unique=True,
            postgresql_where=text("proveedor_documento_id IS NOT NULL"),
        ),
        Index(
            "uq_documentos_fiscales_venta_vigente",
            "venta_id",
            unique=True,
            postgresql_where=text("vigente AND tipo_documento_codigo IN ('FE','POS_E')"),
        ),
        Index(
            "uq_documentos_fiscales_devolucion",
            "devolucion_id",
            unique=True,
            postgresql_where=text("devolucion_id IS NOT NULL"),
        ),
        Index(
            "ix_documentos_fiscales_cola",
            text("proximo_intento_at NULLS FIRST"),
            postgresql_where=text("estado IN ('pendiente_envio','contingencia','rechazado')"),
        ),
        Index(
            "ix_documentos_fiscales_referenciado",
            "documento_referenciado_id",
            postgresql_where=text("documento_referenciado_id IS NOT NULL"),
        ),
        Index("ix_documentos_fiscales_fecha", "empresa_id", "tipo_documento_codigo", text("fecha_emision DESC")),
        Index("ix_documentos_fiscales_adquirente", "adquirente_numero_documento", text("fecha_emision DESC")),
        Index("ix_documentos_fiscales_sede", "sede_id", text("fecha_emision DESC")),
        Index(
            "ix_documentos_fiscales_contingencia",
            "sede_id",
            postgresql_where=text("es_contingencia AND estado <> 'aceptado'"),
        ),
        {"schema": SCHEMA},
    )
    empresa_id: Mapped[uuid.UUID] = fk("organizacion.empresas.id")
    sede_id: Mapped[uuid.UUID] = fk("organizacion.sedes.id")
    caja_id: Mapped[uuid.UUID | None] = fk("cajas.cajas.id", null=True)
    tipo_documento_codigo: Mapped[str] = fkt("referencia.tipos_documento_fiscal.codigo")
    resolucion_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.resoluciones_numeracion.id")
    prefijo: Mapped[str | None] = txt(null=True)  # NULL hasta que el proveedor responda
    consecutivo: Mapped[int | None] = mapped_column(BigInteger)
    numero_completo: Mapped[str | None] = mapped_column(Text, server_default=FetchedValue())  # generada (0003)
    fecha_emision: Mapped[datetime] = ts(null=False)
    venta_id: Mapped[uuid.UUID | None] = fk("ventas.ventas.id", null=True)
    devolucion_id: Mapped[uuid.UUID | None] = fk("ventas.devoluciones.id", null=True)
    documento_referenciado_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.documentos_fiscales.id", null=True)
    concepto_nota_codigo: Mapped[str | None] = txt(null=True)
    forma_pago_codigo: Mapped[str] = fkt("referencia.formas_pago.codigo", server_default="1")
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date)
    emisor_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    adquirente_tercero_id: Mapped[uuid.UUID | None] = fk("identidad.terceros.id", null=True)
    adquirente_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    adquirente_numero_documento: Mapped[str] = txt()
    adquirente_nombre: Mapped[str] = txt()
    moneda: Mapped[str] = txt(server_default="COP")
    subtotal = mapped_column(DINERO(), nullable=False)
    descuento_total = mapped_column(DINERO(), nullable=False)
    impuesto_total = mapped_column(DINERO(), nullable=False)
    redondeo = mapped_column(DINERO(), nullable=False)
    total = mapped_column(DINERO(), nullable=False)
    estado: Mapped[str] = mapped_column(EstadoDocumentoFiscal, nullable=False, server_default="borrador")
    vigente: Mapped[bool] = flag(True)
    cufe_cude: Mapped[str | None] = txt(null=True)
    qr_data: Mapped[str | None] = txt(null=True)
    proveedor_documento_id: Mapped[str | None] = txt(null=True)
    proveedor_respuesta_codigo: Mapped[str | None] = txt(null=True)
    xml_url: Mapped[str | None] = txt(null=True)
    pdf_url: Mapped[str | None] = txt(null=True)
    intentos: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    ultimo_error: Mapped[str | None] = txt(null=True)
    ultimo_intento_at: Mapped[datetime | None] = ts()
    proximo_intento_at: Mapped[datetime | None] = ts()
    es_contingencia: Mapped[bool] = flag(False)
    contingencia_motivo: Mapped[str | None] = txt(null=True)
    enviado_at: Mapped[datetime | None] = ts()
    aceptado_at: Mapped[datetime | None] = ts()
    hash_contenido: Mapped[str] = txt()


class DocumentoFiscalItem(Base, Mutable):
    __tablename__ = "documentos_fiscales_items"
    __table_args__ = (
        UniqueConstraint("documento_id", "linea", name="uq_documentos_fiscales_items_documento_linea"),
        {"schema": SCHEMA},
    )
    documento_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.documentos_fiscales.id")
    linea: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    venta_item_id: Mapped[uuid.UUID | None] = fk("ventas.ventas_items.id", null=True)
    devolucion_item_id: Mapped[uuid.UUID | None] = fk("ventas.devoluciones_items.id", null=True)
    producto_id: Mapped[uuid.UUID | None] = fk("catalogo.productos.id", null=True)
    codigo: Mapped[str] = txt()
    descripcion: Mapped[str] = txt()
    unidad_codigo: Mapped[str] = txt()
    cantidad = mapped_column(CANTIDAD(), nullable=False)
    precio_unitario = mapped_column(PRECIO(), nullable=False)
    valor_unitario_base = mapped_column(PRECIO(), nullable=False)
    descuento_valor = mapped_column(DINERO(), nullable=False, server_default="0")
    base_gravable = mapped_column(DINERO(), nullable=False)
    impuesto_valor = mapped_column(DINERO(), nullable=False)
    total_linea = mapped_column(DINERO(), nullable=False)
    tributo_codigo: Mapped[str] = txt()
    tarifa_pct = mapped_column(PCT(), nullable=False)


class DocumentoFiscalImpuesto(Base, SoloAgregar):
    __tablename__ = "documentos_fiscales_impuestos"
    __table_args__ = (
        UniqueConstraint(
            "documento_id", "tributo_codigo", "tarifa_pct", name="uq_documentos_fiscales_impuestos_documento_tributo"
        ),
        {"schema": SCHEMA},
    )
    documento_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.documentos_fiscales.id")
    tributo_codigo: Mapped[str] = fkt("referencia.tributos.codigo")
    tarifa_pct = mapped_column(PCT(), nullable=False)
    base_gravable = mapped_column(DINERO(), nullable=False)
    impuesto_valor = mapped_column(DINERO(), nullable=False)


class DocumentoFiscalPago(Base, SoloAgregar):
    __tablename__ = "documentos_fiscales_pagos"
    __table_args__ = (
        UniqueConstraint("documento_id", "linea", name="uq_documentos_fiscales_pagos_documento_linea"),
        CheckConstraint("valor > 0", name="valor_positivo"),
        {"schema": SCHEMA},
    )
    documento_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.documentos_fiscales.id")
    linea: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    medio_pago_codigo: Mapped[str] = fkt("referencia.medios_pago.codigo")
    valor = mapped_column(DINERO(), nullable=False)
    referencia: Mapped[str | None] = txt(null=True)


class DocumentoFiscalEvento(Base, SoloAgregar):
    __tablename__ = "documentos_fiscales_eventos"
    __table_args__ = (
        Index("ix_documentos_fiscales_eventos_documento", "documento_id", "ocurrido_at"),
        {"schema": SCHEMA},  # BRIN sobre ocurrido_at: migración 0003
    )
    documento_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.documentos_fiscales.id")
    tipo: Mapped[str] = mapped_column(TipoEventoFiscal, nullable=False)
    intento: Mapped[int | None] = mapped_column(SmallInteger)
    estado_resultante: Mapped[str | None] = mapped_column(EstadoDocumentoFiscal)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    codigo_respuesta: Mapped[str | None] = txt(null=True)
    mensaje: Mapped[str | None] = txt(null=True)
    request_resumen: Mapped[dict | None] = mapped_column(JSONB)
    respuesta: Mapped[dict | None] = mapped_column(JSONB)  # respuesta completa del proveedor
    duracion_ms: Mapped[int | None] = mapped_column()
    ocurrido_at: Mapped[datetime] = ts(null=False, server_default=text("now()"))


class AlertaFiscal(Base, Mutable):
    """Aviso para el backoffice sobre un documento que necesita atención (rechazo, reintentos agotados, descuadre…).

    Hay a lo sumo UNA alerta abierta por (documento, tipo): el worker la reutiliza en vez de duplicarla.
    """

    __tablename__ = "alertas_fiscales"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('rechazado','reintentos_agotados','configuracion','totales_descuadrados','nota_sin_factura')",
            name="tipo",
        ),
        CheckConstraint("estado IN ('abierta','resuelta')", name="estado"),
        CheckConstraint("(estado = 'resuelta') = (resuelta_at IS NOT NULL)", name="resuelta_coherente"),
        Index(
            "uq_alertas_fiscales_abierta",
            "documento_id",
            "tipo",
            unique=True,
            postgresql_where=text("estado = 'abierta'"),
        ),
        Index("ix_alertas_fiscales_documento", "documento_id"),
        Index("ix_alertas_fiscales_sede_estado", "sede_id", "estado", text("created_at DESC")),
        Index(
            "ix_alertas_fiscales_resuelta_por_id",
            "resuelta_por_id",
            postgresql_where=text("resuelta_por_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )
    documento_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.documentos_fiscales.id")
    sede_id: Mapped[uuid.UUID] = fk("organizacion.sedes.id")
    tipo: Mapped[str] = txt()
    mensaje: Mapped[str] = txt()
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    estado: Mapped[str] = txt(server_default="abierta")
    resuelta_at: Mapped[datetime | None] = ts()
    resuelta_por_id: Mapped[uuid.UUID | None] = fk("identidad.empleados.id", null=True)
    comentario: Mapped[str | None] = txt(null=True)


class WorkerLatido(Base):
    """LOCAL del nodo (no se sincroniza): latido del worker fiscal para que `/health` sepa si está vivo."""

    __tablename__ = "worker_latidos"
    __table_args__ = {"schema": SCHEMA, "comment": "LOCAL del nodo: no se sincroniza"}
    nombre: Mapped[str] = mapped_column(Text, primary_key=True)
    ultimo_latido_at: Mapped[datetime] = ts(null=False, server_default=text("now()"))
    ultimo_ciclo_at: Mapped[datetime | None] = ts()
    ciclos: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    procesados: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    ultimo_error: Mapped[str | None] = txt(null=True)
    version_app: Mapped[str | None] = txt(null=True)
