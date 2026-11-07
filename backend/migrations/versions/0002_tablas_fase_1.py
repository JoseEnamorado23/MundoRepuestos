"""tablas fase 1

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06 16:07:22.435360
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- tipos enumerados (create_type=False en las columnas: se crean aquí) ---
    op.execute("CREATE TYPE auditoria.actor_tipo AS ENUM ('empleado', 'cliente', 'sistema', 'dispositivo')")
    op.execute("CREATE TYPE auditoria.resultado_accion AS ENUM ('exito', 'denegado', 'error')")
    op.execute("CREATE TYPE cajas.estado_dispositivo AS ENUM ('pendiente', 'activo', 'bloqueado', 'revocado')")
    op.execute("CREATE TYPE cajas.estado_turno AS ENUM ('abierto', 'cerrado')")
    op.execute("CREATE TYPE cajas.tipo_conexion AS ENUM ('usb', 'red', 'serial', 'bluetooth', 'via_impresora')")
    op.execute("CREATE TYPE cajas.tipo_dispositivo AS ENUM ('pos', 'bodega')")
    op.execute("CREATE TYPE cajas.tipo_movimiento_caja AS ENUM ('ingreso', 'retiro')")
    op.execute(
        "CREATE TYPE cajas.tipo_periferico AS ENUM ('impresora_tiquetes', 'impresora_etiquetas', 'cajon_monedero', 'lector_codigos', 'datafono', 'pantalla_cliente')"
    )
    op.execute("CREATE TYPE catalogo.combustible AS ENUM ('gasolina', 'diesel', 'gas', 'hibrido', 'electrico', 'flex')")
    op.execute("CREATE TYPE catalogo.tipo_codigo_barras AS ENUM ('ean13', 'ean8', 'upc', 'code128', 'interno')")
    op.execute("CREATE TYPE catalogo.tipo_referencia AS ENUM ('oem', 'original', 'alterna', 'equivalente')")
    op.execute("CREATE TYPE catalogo.tratamiento_impuesto AS ENUM ('gravado', 'exento', 'excluido')")
    op.execute("CREATE TYPE fiscal.ambiente_dian AS ENUM ('habilitacion', 'produccion')")
    op.execute(
        "CREATE TYPE fiscal.estado_documento_fiscal AS ENUM ('borrador', 'pendiente_envio', 'enviado', 'aceptado', 'rechazado', 'contingencia')"
    )
    op.execute("CREATE TYPE fiscal.estado_resolucion AS ENUM ('borrador', 'activa', 'agotada', 'vencida', 'anulada')")
    op.execute("CREATE TYPE fiscal.modo_numeracion AS ENUM ('proveedor', 'local')")
    op.execute(
        "CREATE TYPE fiscal.tipo_evento_fiscal AS ENUM ('creado', 'envio_solicitado', 'respuesta_proveedor', 'respuesta_dian', 'error_tecnico', 'reintento_programado', 'contingencia_activada', 'contingencia_transmitida', 'estado_consultado', 'webhook_proveedor')"
    )
    op.execute("CREATE TYPE identidad.estado_cuenta AS ENUM ('pendiente_verificacion', 'activa', 'bloqueada')")
    op.execute(
        "CREATE TYPE identidad.tipo_autorizacion AS ENUM ('descuento_mayor', 'anulacion', 'devolucion', 'precio_manual', 'retiro_efectivo', 'cierre_con_diferencia', 'ajuste_inventario', 'venta_sin_stock')"
    )
    op.execute("CREATE TYPE identidad.tipo_direccion AS ENUM ('envio', 'facturacion')")
    op.execute("CREATE TYPE inventario.estado_alerta AS ENUM ('abierta', 'reconocida', 'resuelta')")
    op.execute("CREATE TYPE inventario.estado_reserva AS ENUM ('activa', 'consumida', 'liberada', 'expirada')")
    op.execute(
        "CREATE TYPE inventario.origen_movimiento AS ENUM ('saldo_inicial', 'recepcion', 'devolucion_proveedor', 'venta', 'devolucion_venta', 'traslado', 'ajuste')"
    )
    op.execute(
        "CREATE TYPE inventario.tipo_alerta_stock AS ENUM ('stock_negativo', 'bajo_minimo', 'reserva_sin_stock')"
    )
    op.execute(
        "CREATE TYPE inventario.tipo_movimiento AS ENUM ('saldo_inicial', 'entrada_compra', 'devolucion_proveedor', 'venta', 'devolucion_venta', 'ajuste_positivo', 'ajuste_negativo', 'traslado_salida', 'traslado_entrada')"
    )
    op.execute("CREATE TYPE organizacion.nodo_estado AS ENUM ('activo', 'inactivo')")
    op.execute("CREATE TYPE organizacion.nodo_tipo AS ENUM ('cloud', 'edge')")
    op.execute("CREATE TYPE sync.direccion_sync AS ENUM ('envio', 'recepcion')")
    op.execute("CREATE TYPE sync.estado_inbox AS ENUM ('recibido', 'aplicado', 'en_espera', 'conflicto', 'error')")
    op.execute("CREATE TYPE sync.estado_outbox AS ENUM ('pendiente', 'enviado', 'confirmado', 'fallido')")
    op.execute(
        "CREATE TYPE sync.resolucion_conflicto AS ENUM ('pendiente', 'gano_nube', 'gano_edge', 'fusionado', 'manual', 'descartado')"
    )
    op.execute(
        "CREATE TYPE sync.tipo_conflicto AS ENUM ('edicion_concurrente', 'clave_natural_duplicada', 'estado_incompatible', 'dependencia_faltante', 'violacion_restriccion')"
    )
    op.execute("CREATE TYPE ventas.canal_pago AS ENUM ('manual', 'datafono', 'qr', 'pasarela')")
    op.execute("CREATE TYPE ventas.canal_venta AS ENUM ('pos', 'web')")
    op.execute("CREATE TYPE ventas.estado_devolucion AS ENUM ('borrador', 'confirmada')")
    op.execute("CREATE TYPE ventas.estado_venta AS ENUM ('borrador', 'confirmada', 'descartada')")
    op.execute("CREATE TYPE ventas.tipo_resolucion AS ENUM ('nota_credito', 'nota_ajuste')")
    op.create_table(
        "permisos",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("modulo", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("requiere_autorizacion", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("codigo ~ '^[a-z_]+\\.[a-z_]+$'", name=op.f("ck_permisos_codigo_formato")),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_permisos")),
        schema="identidad",
    )
    op.create_table(
        "nodos",
        sa.Column(
            "tipo",
            postgresql.ENUM("cloud", "edge", name="nodo_tipo", create_type=False, schema="organizacion"),
            nullable=False,
        ),
        sa.Column("sede_id", sa.Uuid(), nullable=True),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM("activo", "inactivo", name="nodo_estado", create_type=False, schema="organizacion"),
            server_default="activo",
            nullable=False,
        ),
        sa.Column("token_sync_hash", sa.Text(), nullable=True),
        sa.Column("version_app", sa.Text(), nullable=True),
        sa.Column("version_esquema", sa.Text(), nullable=True),
        sa.Column("ultimo_latido_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "(tipo = 'edge' AND sede_id IS NOT NULL) OR (tipo = 'cloud' AND sede_id IS NULL)",
            name=op.f("ck_nodos_sede_segun_tipo"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nodos")),
        schema="organizacion",
    )
    op.create_index(
        "uq_nodos_edge_activo_por_sede",
        "nodos",
        ["sede_id"],
        unique=True,
        schema="organizacion",
        postgresql_where=sa.text("tipo = 'edge' AND estado = 'activo'"),
    )
    op.create_table(
        "departamentos",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_departamentos")),
        schema="referencia",
    )
    op.create_table(
        "formas_pago",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_formas_pago")),
        schema="referencia",
    )
    op.create_table(
        "medios_pago",
        sa.Column("es_efectivo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("requiere_referencia", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_medios_pago")),
        schema="referencia",
    )
    op.create_table(
        "regimenes",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_regimenes")),
        schema="referencia",
    )
    op.create_table(
        "responsabilidades_fiscales",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_responsabilidades_fiscales")),
        schema="referencia",
    )
    op.create_table(
        "tipos_documento_fiscal",
        sa.Column("codigo_dian", sa.Text(), nullable=True),
        sa.Column("requiere_referencia", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("usa_resolucion", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_tipos_documento_fiscal")),
        schema="referencia",
    )
    op.create_table(
        "tipos_documento_identidad",
        sa.Column("abreviatura", sa.Text(), nullable=True),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_tipos_documento_identidad")),
        schema="referencia",
    )
    op.create_table(
        "tipos_persona",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_tipos_persona")),
        schema="referencia",
    )
    op.create_table(
        "tributos",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_tributos")),
        schema="referencia",
    )
    op.create_table(
        "unidades_medida",
        sa.Column("abreviatura", sa.Text(), nullable=True),
        sa.Column("permite_decimales", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_unidades_medida")),
        schema="referencia",
    )
    op.create_table(
        "motivos_movimiento_caja",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("requiere_autorizacion", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("tipo IN ('ingreso','retiro','ambos')", name=op.f("ck_motivos_movimiento_caja_tipo_valido")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_motivos_movimiento_caja")),
        sa.UniqueConstraint("codigo", name="uq_motivos_movimiento_caja_codigo"),
        schema="cajas",
    )
    op.create_table(
        "categorias",
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("orden", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["catalogo.categorias.id"],
            name=op.f("fk_categorias_parent_id_categorias"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categorias")),
        sa.UniqueConstraint("slug", name="uq_categorias_slug"),
        schema="catalogo",
    )
    op.create_index(op.f("ix_categorias_parent_id"), "categorias", ["parent_id"], unique=False, schema="catalogo")
    op.create_table(
        "impuestos",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("tributo_codigo", sa.Text(), nullable=False),
        sa.Column(
            "tratamiento",
            postgresql.ENUM(
                "gravado", "exento", "excluido", name="tratamiento_impuesto", create_type=False, schema="catalogo"
            ),
            nullable=False,
        ),
        sa.Column("tarifa_pct", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("tratamiento <> 'excluido' OR tarifa_pct = 0", name=op.f("ck_impuestos_excluido_tarifa")),
        sa.CheckConstraint("tratamiento <> 'gravado' OR tarifa_pct > 0", name=op.f("ck_impuestos_gravado_tarifa")),
        sa.CheckConstraint("tarifa_pct BETWEEN 0 AND 100", name=op.f("ck_impuestos_tarifa_rango")),
        sa.ForeignKeyConstraint(
            ["tributo_codigo"],
            ["referencia.tributos.codigo"],
            name=op.f("fk_impuestos_tributo_codigo_tributos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impuestos")),
        sa.UniqueConstraint("codigo", name="uq_impuestos_codigo"),
        schema="catalogo",
    )
    op.create_table(
        "listas_precios",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("precios_incluyen_impuesto", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("es_predeterminada", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listas_precios")),
        sa.UniqueConstraint("codigo", name="uq_listas_precios_codigo"),
        schema="catalogo",
    )
    op.create_table(
        "marcas",
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("es_fabricante_oem", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("pais_origen", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marcas")),
        sa.UniqueConstraint("slug", name="uq_marcas_slug"),
        schema="catalogo",
    )
    op.create_table(
        "vehiculos_marcas",
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("codigo_externo", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehiculos_marcas")),
        sa.UniqueConstraint("slug", name="uq_vehiculos_marcas_slug"),
        schema="catalogo",
    )
    op.create_index(
        "uq_vehiculos_marcas_codigo_externo",
        "vehiculos_marcas",
        ["codigo_externo"],
        unique=True,
        schema="catalogo",
        postgresql_where=sa.text("codigo_externo IS NOT NULL"),
    )
    op.create_table(
        "roles",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("es_sistema", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("codigo", name="uq_roles_codigo"),
        schema="identidad",
    )
    op.create_table(
        "conceptos_nota",
        sa.Column("tipo_documento_codigo", sa.Text(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tipo_documento_codigo"],
            ["referencia.tipos_documento_fiscal.codigo"],
            name=op.f("fk_conceptos_nota_tipo_documento_codigo_tipos_documento_fiscal"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tipo_documento_codigo", "codigo", name=op.f("pk_conceptos_nota")),
        schema="referencia",
    )
    op.create_table(
        "municipios",
        sa.Column("departamento_codigo", sa.Text(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["departamento_codigo"],
            ["referencia.departamentos.codigo"],
            name=op.f("fk_municipios_departamento_codigo_departamentos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_municipios")),
        schema="referencia",
    )
    op.create_index(
        op.f("ix_municipios_departamento_codigo"),
        "municipios",
        ["departamento_codigo"],
        unique=False,
        schema="referencia",
    )
    op.create_table(
        "cursores_sync",
        sa.Column("nodo_remoto_id", sa.Uuid(), nullable=False),
        sa.Column("flujo", sa.Text(), nullable=False),
        sa.Column(
            "direccion",
            postgresql.ENUM("envio", "recepcion", name="direccion_sync", create_type=False, schema="sync"),
            nullable=False,
        ),
        sa.Column("ultima_secuencia", sa.BigInteger(), nullable=True),
        sa.Column("ultimo_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_id", sa.Uuid(), nullable=True),
        sa.Column("ultimo_exito_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["nodo_remoto_id"],
            ["organizacion.nodos.id"],
            name=op.f("fk_cursores_sync_nodo_remoto_id_nodos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("nodo_remoto_id", "flujo", "direccion", name=op.f("pk_cursores_sync")),
        schema="sync",
    )
    op.create_table(
        "inbox_eventos",
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("evento_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("agregado_tipo", sa.Text(), nullable=False),
        sa.Column("evento_tipo", sa.Text(), nullable=False),
        sa.Column("agregado_id", sa.Uuid(), nullable=False),
        sa.Column("version_agregado", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "recibido",
                "aplicado",
                "en_espera",
                "conflicto",
                "error",
                name="estado_inbox",
                create_type=False,
                schema="sync",
            ),
            server_default="recibido",
            nullable=False,
        ),
        sa.Column("intentos", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("recibido_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("aplicado_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("nodo_origen_id", "evento_id", name=op.f("pk_inbox_eventos")),
        sa.UniqueConstraint("idempotency_key", name="uq_inbox_eventos_idempotency_key"),
        schema="sync",
    )
    op.create_index(
        "ix_inbox_eventos_agregado",
        "inbox_eventos",
        ["agregado_tipo", "agregado_id", "version_agregado"],
        unique=False,
        schema="sync",
    )
    op.create_index(
        "ix_inbox_eventos_pendientes",
        "inbox_eventos",
        ["recibido_at"],
        unique=False,
        schema="sync",
        postgresql_where=sa.text("estado IN ('recibido','en_espera','error')"),
    )
    op.create_table(
        "outbox_eventos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("secuencia", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("nodo_destino_id", sa.Uuid(), nullable=True),
        sa.Column("agregado_tipo", sa.Text(), nullable=False),
        sa.Column("agregado_id", sa.Uuid(), nullable=False),
        sa.Column("evento_tipo", sa.Text(), nullable=False),
        sa.Column("version_agregado", sa.Integer(), nullable=False),
        sa.Column("payload_version", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "pendiente", "enviado", "confirmado", "fallido", name="estado_outbox", create_type=False, schema="sync"
            ),
            server_default="pendiente",
            nullable=False,
        ),
        sa.Column("intentos", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("proximo_intento_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("enviado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmado_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["nodo_destino_id"],
            ["organizacion.nodos.id"],
            name=op.f("fk_outbox_eventos_nodo_destino_id_nodos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_eventos")),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_eventos_idempotency_key"),
        schema="sync",
    )
    op.create_index(
        "ix_outbox_eventos_agregado",
        "outbox_eventos",
        ["agregado_tipo", "agregado_id", "version_agregado"],
        unique=False,
        schema="sync",
    )
    op.create_index(
        "ix_outbox_eventos_cola",
        "outbox_eventos",
        ["proximo_intento_at", "secuencia"],
        unique=False,
        schema="sync",
        postgresql_where=sa.text("estado IN ('pendiente','fallido')"),
    )
    op.create_table(
        "motivos_devolucion",
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("reintegra_stock_por_defecto", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("requiere_autorizacion", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_motivos_devolucion")),
        sa.UniqueConstraint("codigo", name="uq_motivos_devolucion_codigo"),
        schema="ventas",
    )
    op.create_table(
        "productos",
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("marca_id", sa.Uuid(), nullable=True),
        sa.Column("categoria_id", sa.Uuid(), nullable=False),
        sa.Column("unidad_codigo", sa.Text(), server_default="94", nullable=False),
        sa.Column("impuesto_id", sa.Uuid(), nullable=False),
        sa.Column("es_inventariable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("vendible_pos", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("publicado_web", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("peso_kg", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("alto_cm", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("ancho_cm", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("largo_cm", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("stock_minimo", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False),
        sa.Column("stock_seguridad_web", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("nombre_busqueda", sa.Text(), nullable=False),
        sa.Column("busqueda", postgresql.TSVECTOR(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("NOT publicado_web OR activo", name=op.f("ck_productos_web_activo")),
        sa.CheckConstraint("peso_kg IS NULL OR peso_kg >= 0", name=op.f("ck_productos_peso_no_negativo")),
        sa.CheckConstraint(
            "stock_seguridad_web IS NULL OR stock_seguridad_web >= 0", name=op.f("ck_productos_seguridad_no_negativa")
        ),
        sa.ForeignKeyConstraint(
            ["categoria_id"],
            ["catalogo.categorias.id"],
            name=op.f("fk_productos_categoria_id_categorias"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["impuesto_id"],
            ["catalogo.impuestos.id"],
            name=op.f("fk_productos_impuesto_id_impuestos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["marca_id"], ["catalogo.marcas.id"], name=op.f("fk_productos_marca_id_marcas"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["unidad_codigo"],
            ["referencia.unidades_medida.codigo"],
            name=op.f("fk_productos_unidad_codigo_unidades_medida"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_productos")),
        sa.UniqueConstraint("sku", name="uq_productos_sku"),
        schema="catalogo",
    )
    op.create_index(
        "ix_productos_categoria_activos",
        "productos",
        ["categoria_id"],
        unique=False,
        schema="catalogo",
        postgresql_where=sa.text("activo"),
    )
    op.create_index(op.f("ix_productos_marca_id"), "productos", ["marca_id"], unique=False, schema="catalogo")
    op.create_index(
        "ix_productos_web",
        "productos",
        ["categoria_id", "nombre"],
        unique=False,
        schema="catalogo",
        postgresql_where=sa.text("publicado_web AND activo"),
    )
    op.create_index(
        "uq_productos_slug",
        "productos",
        ["slug"],
        unique=True,
        schema="catalogo",
        postgresql_where=sa.text("slug IS NOT NULL"),
    )
    op.create_table(
        "vehiculos_modelos",
        sa.Column("marca_id", sa.Uuid(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("codigo_externo", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["marca_id"],
            ["catalogo.vehiculos_marcas.id"],
            name=op.f("fk_vehiculos_modelos_marca_id_vehiculos_marcas"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehiculos_modelos")),
        schema="catalogo",
    )
    op.create_index(
        "uq_vehiculos_modelos_codigo_externo",
        "vehiculos_modelos",
        ["codigo_externo"],
        unique=True,
        schema="catalogo",
        postgresql_where=sa.text("codigo_externo IS NOT NULL"),
    )
    op.create_table(
        "roles_permisos",
        sa.Column("rol_id", sa.Uuid(), nullable=False),
        sa.Column("permiso_codigo", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["permiso_codigo"],
            ["identidad.permisos.codigo"],
            name=op.f("fk_roles_permisos_permiso_codigo_permisos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rol_id"], ["identidad.roles.id"], name=op.f("fk_roles_permisos_rol_id_roles"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("rol_id", "permiso_codigo", name=op.f("pk_roles_permisos")),
        schema="identidad",
    )
    op.create_index(
        "ix_roles_permisos_permiso_codigo", "roles_permisos", ["permiso_codigo"], unique=False, schema="identidad"
    )
    op.create_table(
        "terceros",
        sa.Column("tipo_persona_codigo", sa.Text(), nullable=False),
        sa.Column("tipo_documento_codigo", sa.Text(), nullable=False),
        sa.Column("numero_documento", sa.Text(), nullable=False),
        sa.Column("dv", sa.SmallInteger(), nullable=True),
        sa.Column("razon_social", sa.Text(), nullable=True),
        sa.Column("primer_nombre", sa.Text(), nullable=True),
        sa.Column("segundo_nombre", sa.Text(), nullable=True),
        sa.Column("primer_apellido", sa.Text(), nullable=True),
        sa.Column("segundo_apellido", sa.Text(), nullable=True),
        sa.Column("nombre_completo", sa.Text(), nullable=False),
        sa.Column("nombre_comercial", sa.Text(), nullable=True),
        sa.Column("regimen_codigo", sa.Text(), nullable=True),
        sa.Column("email_facturacion", sa.Text(), nullable=True),
        sa.Column("telefono", sa.Text(), nullable=True),
        sa.Column("municipio_codigo", sa.Text(), nullable=True),
        sa.Column("direccion_fiscal", sa.Text(), nullable=True),
        sa.Column("es_cliente", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("es_proveedor", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("es_consumidor_final", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("fusionado_en_id", sa.Uuid(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "es_consumidor_final = (numero_documento = '222222222222' AND tipo_documento_codigo = '13')",
            name=op.f("ck_terceros_consumidor_final"),
        ),
        sa.CheckConstraint(
            "es_consumidor_final OR (tipo_persona_codigo = '1' AND razon_social IS NOT NULL) OR (tipo_persona_codigo = '2' AND primer_nombre IS NOT NULL AND primer_apellido IS NOT NULL)",
            name=op.f("ck_terceros_nombre"),
        ),
        sa.CheckConstraint("tipo_documento_codigo <> '31' OR dv IS NOT NULL", name=op.f("ck_terceros_dv_nit")),
        sa.CheckConstraint("fusionado_en_id IS DISTINCT FROM id", name=op.f("ck_terceros_fusion")),
        sa.ForeignKeyConstraint(
            ["fusionado_en_id"],
            ["identidad.terceros.id"],
            name=op.f("fk_terceros_fusionado_en_id_terceros"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["municipio_codigo"],
            ["referencia.municipios.codigo"],
            name=op.f("fk_terceros_municipio_codigo_municipios"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["regimen_codigo"],
            ["referencia.regimenes.codigo"],
            name=op.f("fk_terceros_regimen_codigo_regimenes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tipo_documento_codigo"],
            ["referencia.tipos_documento_identidad.codigo"],
            name=op.f("fk_terceros_tipo_documento_codigo_tipos_documento_identidad"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tipo_persona_codigo"],
            ["referencia.tipos_persona.codigo"],
            name=op.f("fk_terceros_tipo_persona_codigo_tipos_persona"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terceros")),
        schema="identidad",
    )
    op.create_index(
        "ix_terceros_proveedores",
        "terceros",
        ["nombre_completo"],
        unique=False,
        schema="identidad",
        postgresql_where=sa.text("es_proveedor"),
    )
    op.create_index(
        "uq_terceros_documento",
        "terceros",
        ["tipo_documento_codigo", "numero_documento"],
        unique=True,
        schema="identidad",
        postgresql_where=sa.text("fusionado_en_id IS NULL"),
    )
    op.create_table(
        "productos_codigos_barras",
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "ean13",
                "ean8",
                "upc",
                "code128",
                "interno",
                name="tipo_codigo_barras",
                create_type=False,
                schema="catalogo",
            ),
            server_default="ean13",
            nullable=False,
        ),
        sa.Column("unidades_por_codigo", sa.Numeric(precision=14, scale=3), server_default="1", nullable=False),
        sa.Column("es_principal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("unidades_por_codigo > 0", name=op.f("ck_productos_codigos_barras_unidades_positivas")),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_productos_codigos_barras_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_productos_codigos_barras")),
        schema="catalogo",
    )
    op.create_index(
        op.f("ix_productos_codigos_barras_producto_id"),
        "productos_codigos_barras",
        ["producto_id"],
        unique=False,
        schema="catalogo",
    )
    op.create_index(
        "uq_productos_codigos_barras_codigo",
        "productos_codigos_barras",
        ["codigo"],
        unique=True,
        schema="catalogo",
        postgresql_where=sa.text("activo"),
    )
    op.create_index(
        "uq_productos_codigos_barras_principal",
        "productos_codigos_barras",
        ["producto_id"],
        unique=True,
        schema="catalogo",
        postgresql_where=sa.text("es_principal AND activo"),
    )
    op.create_table(
        "productos_imagenes",
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_miniatura", sa.Text(), nullable=True),
        sa.Column("texto_alternativo", sa.Text(), nullable=True),
        sa.Column("orden", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("es_principal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_productos_imagenes_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_productos_imagenes")),
        schema="catalogo",
    )
    op.create_index(
        "ix_productos_imagenes_producto_orden",
        "productos_imagenes",
        ["producto_id", "orden"],
        unique=False,
        schema="catalogo",
    )
    op.create_index(
        "uq_productos_imagenes_principal",
        "productos_imagenes",
        ["producto_id"],
        unique=True,
        schema="catalogo",
        postgresql_where=sa.text("es_principal AND activo"),
    )
    op.create_table(
        "productos_referencias",
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "oem",
                "original",
                "alterna",
                "equivalente",
                name="tipo_referencia",
                create_type=False,
                schema="catalogo",
            ),
            nullable=False,
        ),
        sa.Column("referencia", sa.Text(), nullable=False),
        sa.Column("marca_id", sa.Uuid(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["marca_id"],
            ["catalogo.marcas.id"],
            name=op.f("fk_productos_referencias_marca_id_marcas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_productos_referencias_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_productos_referencias")),
        schema="catalogo",
    )
    op.create_index(
        op.f("ix_productos_referencias_producto_id"),
        "productos_referencias",
        ["producto_id"],
        unique=False,
        schema="catalogo",
    )
    op.create_table(
        "terceros_listas_precios",
        sa.Column("tercero_id", sa.Uuid(), nullable=False),
        sa.Column("lista_precio_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["lista_precio_id"],
            ["catalogo.listas_precios.id"],
            name=op.f("fk_terceros_listas_precios_lista_precio_id_listas_precios"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tercero_id"],
            ["identidad.terceros.id"],
            name=op.f("fk_terceros_listas_precios_tercero_id_terceros"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tercero_id", name=op.f("pk_terceros_listas_precios")),
        schema="catalogo",
    )
    op.create_table(
        "vehiculos_versiones",
        sa.Column("modelo_id", sa.Uuid(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("anio_desde", sa.SmallInteger(), nullable=False),
        sa.Column("anio_hasta", sa.SmallInteger(), nullable=True),
        sa.Column("motor", sa.Text(), nullable=True),
        sa.Column("cilindraje_cc", sa.Integer(), nullable=True),
        sa.Column(
            "combustible",
            postgresql.ENUM(
                "gasolina",
                "diesel",
                "gas",
                "hibrido",
                "electrico",
                "flex",
                name="combustible",
                create_type=False,
                schema="catalogo",
            ),
            nullable=True,
        ),
        sa.Column("transmision", sa.Text(), nullable=True),
        sa.Column("codigo_externo", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("anio_desde BETWEEN 1950 AND 2100", name=op.f("ck_vehiculos_versiones_anio_desde_rango")),
        sa.CheckConstraint(
            "anio_hasta IS NULL OR anio_hasta >= anio_desde", name=op.f("ck_vehiculos_versiones_anios_orden")
        ),
        sa.CheckConstraint(
            "cilindraje_cc IS NULL OR cilindraje_cc > 0", name=op.f("ck_vehiculos_versiones_cilindraje_positivo")
        ),
        sa.ForeignKeyConstraint(
            ["modelo_id"],
            ["catalogo.vehiculos_modelos.id"],
            name=op.f("fk_vehiculos_versiones_modelo_id_vehiculos_modelos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehiculos_versiones")),
        schema="catalogo",
    )
    op.create_index(
        "uq_vehiculos_versiones_codigo_externo",
        "vehiculos_versiones",
        ["codigo_externo"],
        unique=True,
        schema="catalogo",
        postgresql_where=sa.text("codigo_externo IS NOT NULL"),
    )
    op.create_table(
        "cuentas_clientes",
        sa.Column("tercero_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "pendiente_verificacion",
                "activa",
                "bloqueada",
                name="estado_cuenta",
                create_type=False,
                schema="identidad",
            ),
            server_default="pendiente_verificacion",
            nullable=False,
        ),
        sa.Column("email_verificado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acepta_terminos_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acepta_marketing", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ultimo_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["tercero_id"],
            ["identidad.terceros.id"],
            name=op.f("fk_cuentas_clientes_tercero_id_terceros"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cuentas_clientes")),
        sa.UniqueConstraint("tercero_id", name="uq_cuentas_clientes_tercero"),
        schema="identidad",
    )
    op.create_table(
        "direcciones",
        sa.Column("tercero_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM("envio", "facturacion", name="tipo_direccion", create_type=False, schema="identidad"),
            server_default="envio",
            nullable=False,
        ),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("destinatario_nombre", sa.Text(), nullable=False),
        sa.Column("destinatario_telefono", sa.Text(), nullable=False),
        sa.Column("municipio_codigo", sa.Text(), nullable=False),
        sa.Column("direccion", sa.Text(), nullable=False),
        sa.Column("complemento", sa.Text(), nullable=True),
        sa.Column("barrio", sa.Text(), nullable=True),
        sa.Column("indicaciones", sa.Text(), nullable=True),
        sa.Column("es_predeterminada", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["municipio_codigo"],
            ["referencia.municipios.codigo"],
            name=op.f("fk_direcciones_municipio_codigo_municipios"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tercero_id"],
            ["identidad.terceros.id"],
            name=op.f("fk_direcciones_tercero_id_terceros"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_direcciones")),
        schema="identidad",
    )
    op.create_index(op.f("ix_direcciones_tercero_id"), "direcciones", ["tercero_id"], unique=False, schema="identidad")
    op.create_index(
        "uq_direcciones_predeterminada",
        "direcciones",
        ["tercero_id", "tipo"],
        unique=True,
        schema="identidad",
        postgresql_where=sa.text("es_predeterminada AND activo"),
    )
    op.create_table(
        "terceros_responsabilidades",
        sa.Column("tercero_id", sa.Uuid(), nullable=False),
        sa.Column("responsabilidad_codigo", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["responsabilidad_codigo"],
            ["referencia.responsabilidades_fiscales.codigo"],
            name=op.f("fk_terceros_responsabilidades_responsabilidad_codigo_responsabilidades_fiscales"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tercero_id"],
            ["identidad.terceros.id"],
            name=op.f("fk_terceros_responsabilidades_tercero_id_terceros"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tercero_id", "responsabilidad_codigo", name=op.f("pk_terceros_responsabilidades")),
        schema="identidad",
    )
    op.create_table(
        "productos_compatibilidades",
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("posicion", sa.Text(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_productos_compatibilidades_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["catalogo.vehiculos_versiones.id"],
            name=op.f("fk_productos_compatibilidades_version_id_vehiculos_versiones"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_productos_compatibilidades")),
        sa.UniqueConstraint("producto_id", "version_id", name="uq_productos_compatibilidades_producto_version"),
        schema="catalogo",
    )
    op.create_index(
        "ix_productos_compatibilidades_version_producto",
        "productos_compatibilidades",
        ["version_id", "producto_id"],
        unique=False,
        schema="catalogo",
    )
    op.create_table(
        "empleados",
        sa.Column("tipo_documento_codigo", sa.Text(), nullable=False),
        sa.Column("numero_documento", sa.Text(), nullable=False),
        sa.Column("nombres", sa.Text(), nullable=False),
        sa.Column("apellidos", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("telefono", sa.Text(), nullable=True),
        sa.Column("usuario", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("pin_hash", sa.Text(), nullable=True),
        sa.Column("pin_intentos_fallidos", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("pin_bloqueado_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("codigo_carne", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "activo = false OR usuario IS NOT NULL OR codigo_carne IS NOT NULL", name=op.f("ck_empleados_credencial")
        ),
        sa.ForeignKeyConstraint(
            ["tipo_documento_codigo"],
            ["referencia.tipos_documento_identidad.codigo"],
            name=op.f("fk_empleados_tipo_documento_codigo_tipos_documento_identidad"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_empleados")),
        sa.UniqueConstraint("tipo_documento_codigo", "numero_documento", name="uq_empleados_documento"),
        schema="identidad",
    )
    op.create_index(
        "uq_empleados_carne",
        "empleados",
        ["codigo_carne"],
        unique=True,
        schema="identidad",
        postgresql_where=sa.text("codigo_carne IS NOT NULL"),
    )
    op.create_table(
        "empresas",
        sa.Column("nit", sa.Text(), nullable=False),
        sa.Column("dv", sa.SmallInteger(), nullable=False),
        sa.Column("razon_social", sa.Text(), nullable=False),
        sa.Column("nombre_comercial", sa.Text(), nullable=True),
        sa.Column("tipo_persona_codigo", sa.Text(), nullable=False),
        sa.Column("regimen_codigo", sa.Text(), nullable=False),
        sa.Column("actividad_economica_ciiu", sa.Text(), nullable=True),
        sa.Column("matricula_mercantil", sa.Text(), nullable=True),
        sa.Column("municipio_codigo", sa.Text(), nullable=False),
        sa.Column("direccion", sa.Text(), nullable=False),
        sa.Column("telefono", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("nit ~ '^[0-9]{6,12}$'", name=op.f("ck_empresas_nit_formato")),
        sa.CheckConstraint("dv BETWEEN 0 AND 9", name=op.f("ck_empresas_dv_rango")),
        sa.ForeignKeyConstraint(
            ["municipio_codigo"],
            ["referencia.municipios.codigo"],
            name=op.f("fk_empresas_municipio_codigo_municipios"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["regimen_codigo"],
            ["referencia.regimenes.codigo"],
            name=op.f("fk_empresas_regimen_codigo_regimenes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tipo_persona_codigo"],
            ["referencia.tipos_persona.codigo"],
            name=op.f("fk_empresas_tipo_persona_codigo_tipos_persona"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_empresas")),
        sa.UniqueConstraint("nit", name="uq_empresas_nit"),
        schema="organizacion",
    )
    op.create_table(
        "sedes",
        sa.Column("empresa_id", sa.Uuid(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("municipio_codigo", sa.Text(), nullable=False),
        sa.Column("direccion", sa.Text(), nullable=False),
        sa.Column("telefono", sa.Text(), nullable=True),
        sa.Column("permite_recoger_pedidos", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("codigo ~ '^[A-Z0-9]{2,6}$'", name=op.f("ck_sedes_codigo_formato")),
        sa.ForeignKeyConstraint(
            ["empresa_id"], ["organizacion.empresas.id"], name=op.f("fk_sedes_empresa_id_empresas"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["municipio_codigo"],
            ["referencia.municipios.codigo"],
            name=op.f("fk_sedes_municipio_codigo_municipios"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sedes")),
        sa.UniqueConstraint("empresa_id", "codigo", name="uq_sedes_empresa_codigo"),
        schema="organizacion",
    )
    op.create_table(
        "configuracion_proveedor",
        sa.Column("empresa_id", sa.Uuid(), nullable=False),
        sa.Column("proveedor", sa.Text(), nullable=False),
        sa.Column(
            "ambiente",
            postgresql.ENUM("habilitacion", "produccion", name="ambiente_dian", create_type=False, schema="fiscal"),
            server_default="habilitacion",
            nullable=False,
        ),
        sa.Column("url_base", sa.Text(), nullable=False),
        sa.Column("credenciales_ref", sa.Text(), nullable=False),
        sa.Column("set_pruebas_id", sa.Text(), nullable=True),
        sa.Column(
            "parametros", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["empresa_id"],
            ["organizacion.empresas.id"],
            name=op.f("fk_configuracion_proveedor_empresa_id_empresas"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_configuracion_proveedor")),
        schema="fiscal",
    )
    op.create_index(
        "uq_configuracion_proveedor_activo",
        "configuracion_proveedor",
        ["empresa_id"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("activo"),
    )
    op.create_table(
        "autorizaciones",
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "descuento_mayor",
                "anulacion",
                "devolucion",
                "precio_manual",
                "retiro_efectivo",
                "cierre_con_diferencia",
                "ajuste_inventario",
                "venta_sin_stock",
                name="tipo_autorizacion",
                create_type=False,
                schema="identidad",
            ),
            nullable=False,
        ),
        sa.Column("permiso_codigo", sa.Text(), nullable=False),
        sa.Column("solicitado_por_id", sa.Uuid(), nullable=False),
        sa.Column("autorizado_por_id", sa.Uuid(), nullable=False),
        sa.Column("dispositivo_id", sa.Uuid(), nullable=True),
        sa.Column("entidad_tipo", sa.Text(), nullable=True),
        sa.Column("entidad_id", sa.Uuid(), nullable=True),
        sa.Column(
            "detalle", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "autorizado_por_id <> solicitado_por_id", name=op.f("ck_autorizaciones_no_autoautorizacion")
        ),
        sa.ForeignKeyConstraint(
            ["autorizado_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_autorizaciones_autorizado_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["permiso_codigo"],
            ["identidad.permisos.codigo"],
            name=op.f("fk_autorizaciones_permiso_codigo_permisos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["solicitado_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_autorizaciones_solicitado_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_autorizaciones")),
        schema="identidad",
    )
    op.create_index(
        "ix_autorizaciones_autorizador",
        "autorizaciones",
        ["autorizado_por_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="identidad",
    )
    op.create_index(
        "ix_autorizaciones_entidad", "autorizaciones", ["entidad_tipo", "entidad_id"], unique=False, schema="identidad"
    )
    op.create_table(
        "empleados_sedes",
        sa.Column("empleado_id", sa.Uuid(), nullable=False),
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("es_sede_principal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["empleado_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_empleados_sedes_empleado_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_empleados_sedes_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("empleado_id", "sede_id", name=op.f("pk_empleados_sedes")),
        schema="identidad",
    )
    op.create_index("ix_empleados_sedes_sede_id", "empleados_sedes", ["sede_id"], unique=False, schema="identidad")
    op.create_table(
        "bodegas",
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("es_vendible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_bodegas_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bodegas")),
        sa.UniqueConstraint("sede_id", "codigo", name="uq_bodegas_sede_codigo"),
        schema="inventario",
    )
    op.create_table(
        "configuracion_sede",
        sa.Column("sede_id", sa.Uuid(), nullable=True),
        sa.Column("clave", sa.Text(), nullable=False),
        sa.Column("valor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["sede_id"],
            ["organizacion.sedes.id"],
            name=op.f("fk_configuracion_sede_sede_id_sedes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_configuracion_sede")),
        schema="organizacion",
    )
    op.create_table(
        "empresas_responsabilidades",
        sa.Column("empresa_id", sa.Uuid(), nullable=False),
        sa.Column("responsabilidad_codigo", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["empresa_id"],
            ["organizacion.empresas.id"],
            name=op.f("fk_empresas_responsabilidades_empresa_id_empresas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["responsabilidad_codigo"],
            ["referencia.responsabilidades_fiscales.codigo"],
            name=op.f("fk_empresas_responsabilidades_responsabilidad_codigo_responsabilidades_fiscales"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("empresa_id", "responsabilidad_codigo", name=op.f("pk_empresas_responsabilidades")),
        schema="organizacion",
    )
    op.create_table(
        "conflictos_sync",
        sa.Column("evento_nodo_origen_id", sa.Uuid(), nullable=True),
        sa.Column("evento_id", sa.Uuid(), nullable=True),
        sa.Column("agregado_tipo", sa.Text(), nullable=False),
        sa.Column("agregado_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "edicion_concurrente",
                "clave_natural_duplicada",
                "estado_incompatible",
                "dependencia_faltante",
                "violacion_restriccion",
                name="tipo_conflicto",
                create_type=False,
                schema="sync",
            ),
            nullable=False,
        ),
        sa.Column("version_local", sa.Integer(), nullable=True),
        sa.Column("version_remota", sa.Integer(), nullable=True),
        sa.Column("datos_locales", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("datos_remotos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "resolucion",
            postgresql.ENUM(
                "pendiente",
                "gano_nube",
                "gano_edge",
                "fusionado",
                "manual",
                "descartado",
                name="resolucion_conflicto",
                create_type=False,
                schema="sync",
            ),
            server_default="pendiente",
            nullable=False,
        ),
        sa.Column("resuelto_por_id", sa.Uuid(), nullable=True),
        sa.Column("resuelto_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["resuelto_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_conflictos_sync_resuelto_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conflictos_sync")),
        schema="sync",
    )
    op.create_index(
        "ix_conflictos_sync_agregado", "conflictos_sync", ["agregado_tipo", "agregado_id"], unique=False, schema="sync"
    )
    op.create_index(
        "ix_conflictos_sync_pendientes",
        "conflictos_sync",
        ["created_at"],
        unique=False,
        schema="sync",
        postgresql_where=sa.text("resolucion = 'pendiente'"),
    )
    op.create_table(
        "log_acciones",
        sa.Column("ocurrido_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "actor_tipo",
            postgresql.ENUM(
                "empleado",
                "cliente",
                "sistema",
                "dispositivo",
                name="actor_tipo",
                create_type=False,
                schema="auditoria",
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("sede_id", sa.Uuid(), nullable=True),
        sa.Column("accion", sa.Text(), nullable=False),
        sa.Column("entidad_tipo", sa.Text(), nullable=True),
        sa.Column("entidad_id", sa.Uuid(), nullable=True),
        sa.Column("antes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("despues", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("autorizado_por_id", sa.Uuid(), nullable=True),
        sa.Column("autorizacion_id", sa.Uuid(), nullable=True),
        sa.Column("dispositivo_id", sa.Uuid(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "resultado",
            postgresql.ENUM(
                "exito", "denegado", "error", name="resultado_accion", create_type=False, schema="auditoria"
            ),
            server_default="exito",
            nullable=False,
        ),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("accion ~ '^[a-z_]+\\.[a-z_]+$'", name=op.f("ck_log_acciones_accion_formato")),
        sa.ForeignKeyConstraint(
            ["autorizacion_id"],
            ["identidad.autorizaciones.id"],
            name=op.f("fk_log_acciones_autorizacion_id_autorizaciones"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["autorizado_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_log_acciones_autorizado_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_log_acciones_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_log_acciones")),
        schema="auditoria",
    )
    op.create_index(
        "ix_log_acciones_actor",
        "log_acciones",
        ["actor_id", sa.literal_column("ocurrido_at DESC")],
        unique=False,
        schema="auditoria",
    )
    op.create_index(
        "ix_log_acciones_entidad", "log_acciones", ["entidad_tipo", "entidad_id"], unique=False, schema="auditoria"
    )
    op.create_index(
        "ix_log_acciones_ocurrido",
        "log_acciones",
        [sa.literal_column("ocurrido_at DESC")],
        unique=False,
        schema="auditoria",
    )
    op.create_table(
        "cajas",
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("bodega_id", sa.Uuid(), nullable=False),
        sa.Column("ultimo_numero_interno", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["bodega_id"], ["inventario.bodegas.id"], name=op.f("fk_cajas_bodega_id_bodegas"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_cajas_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cajas")),
        sa.UniqueConstraint("sede_id", "codigo", name="uq_cajas_sede_codigo"),
        schema="cajas",
    )
    op.create_table(
        "empleados_roles",
        sa.Column("empleado_id", sa.Uuid(), nullable=False),
        sa.Column("rol_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["empleado_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_empleados_roles_empleado_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rol_id"], ["identidad.roles.id"], name=op.f("fk_empleados_roles_rol_id_roles"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("empleado_id", "rol_id", name=op.f("pk_empleados_roles")),
        schema="identidad",
    )
    op.create_index("ix_empleados_roles_rol_id", "empleados_roles", ["rol_id"], unique=False, schema="identidad")
    op.create_table(
        "ubicaciones",
        sa.Column("bodega_id", sa.Uuid(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("pasillo", sa.Text(), nullable=False),
        sa.Column("estante", sa.Text(), nullable=True),
        sa.Column("nivel", sa.Text(), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["bodega_id"], ["inventario.bodegas.id"], name=op.f("fk_ubicaciones_bodega_id_bodegas"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ubicaciones")),
        sa.UniqueConstraint("bodega_id", "codigo", name="uq_ubicaciones_bodega_codigo"),
        schema="inventario",
    )
    op.create_table(
        "dispositivos",
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("caja_id", sa.Uuid(), nullable=True),
        sa.Column(
            "tipo",
            postgresql.ENUM("pos", "bodega", name="tipo_dispositivo", create_type=False, schema="cajas"),
            server_default="pos",
            nullable=False,
        ),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "pendiente",
                "activo",
                "bloqueado",
                "revocado",
                name="estado_dispositivo",
                create_type=False,
                schema="cajas",
            ),
            server_default="pendiente",
            nullable=False,
        ),
        sa.Column("ultimo_acceso_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultima_ip", postgresql.INET(), nullable=True),
        sa.Column("version_cliente", sa.Text(), nullable=True),
        sa.Column("revocado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("tipo <> 'pos' OR caja_id IS NOT NULL", name=op.f("ck_dispositivos_pos_requiere_caja")),
        sa.ForeignKeyConstraint(
            ["caja_id"], ["cajas.cajas.id"], name=op.f("fk_dispositivos_caja_id_cajas"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_dispositivos_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dispositivos")),
        sa.UniqueConstraint("token_hash", name="uq_dispositivos_token_hash"),
        schema="cajas",
    )
    op.create_index("ix_dispositivos_sede", "dispositivos", ["sede_id", "estado"], unique=False, schema="cajas")
    op.create_index(
        "uq_dispositivos_caja_activo",
        "dispositivos",
        ["caja_id"],
        unique=True,
        schema="cajas",
        postgresql_where=sa.text("estado = 'activo' AND tipo = 'pos'"),
    )
    op.create_table(
        "perifericos",
        sa.Column("caja_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "impresora_tiquetes",
                "impresora_etiquetas",
                "cajon_monedero",
                "lector_codigos",
                "datafono",
                "pantalla_cliente",
                name="tipo_periferico",
                create_type=False,
                schema="cajas",
            ),
            nullable=False,
        ),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column(
            "conexion",
            postgresql.ENUM(
                "usb",
                "red",
                "serial",
                "bluetooth",
                "via_impresora",
                name="tipo_conexion",
                create_type=False,
                schema="cajas",
            ),
            nullable=False,
        ),
        sa.Column(
            "parametros", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["caja_id"], ["cajas.cajas.id"], name=op.f("fk_perifericos_caja_id_cajas"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_perifericos")),
        schema="cajas",
    )
    op.create_index(
        "ix_perifericos_caja_activos",
        "perifericos",
        ["caja_id"],
        unique=False,
        schema="cajas",
        postgresql_where=sa.text("activo"),
    )
    op.create_table(
        "precios",
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("lista_precio_id", sa.Uuid(), nullable=False),
        sa.Column("sede_id", sa.Uuid(), nullable=True),
        sa.Column("precio", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("vigente_desde", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("vigente_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("precio >= 0", name=op.f("ck_precios_precio_no_negativo")),
        sa.CheckConstraint(
            "vigente_hasta IS NULL OR vigente_hasta > vigente_desde", name=op.f("ck_precios_vigencia_orden")
        ),
        sa.ForeignKeyConstraint(
            ["lista_precio_id"],
            ["catalogo.listas_precios.id"],
            name=op.f("fk_precios_lista_precio_id_listas_precios"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_precios_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_precios_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_precios")),
        schema="catalogo",
    )
    op.create_index(
        "ix_precios_vigente",
        "precios",
        ["producto_id", "lista_precio_id"],
        unique=False,
        schema="catalogo",
        postgresql_where=sa.text("vigente_hasta IS NULL"),
    )
    op.create_table(
        "resoluciones_numeracion",
        sa.Column("empresa_id", sa.Uuid(), nullable=False),
        sa.Column("sede_id", sa.Uuid(), nullable=True),
        sa.Column("caja_id", sa.Uuid(), nullable=True),
        sa.Column(
            "modo_numeracion",
            postgresql.ENUM("proveedor", "local", name="modo_numeracion", create_type=False, schema="fiscal"),
            server_default="proveedor",
            nullable=False,
        ),
        sa.Column("id_rango_proveedor", sa.Text(), nullable=True),
        sa.Column("nodo_propietario_id", sa.Uuid(), nullable=True),
        sa.Column("tipo_documento_codigo", sa.Text(), nullable=False),
        sa.Column("numero_resolucion", sa.Text(), nullable=False),
        sa.Column("fecha_resolucion", sa.Date(), nullable=False),
        sa.Column("prefijo", sa.Text(), server_default="", nullable=False),
        sa.Column("rango_desde", sa.BigInteger(), nullable=False),
        sa.Column("rango_hasta", sa.BigInteger(), nullable=False),
        sa.Column("consecutivo_actual", sa.BigInteger(), nullable=False),
        sa.Column("vigente_desde", sa.Date(), nullable=False),
        sa.Column("vigente_hasta", sa.Date(), nullable=False),
        sa.Column("clave_tecnica_ref", sa.Text(), nullable=True),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "borrador",
                "activa",
                "agotada",
                "vencida",
                "anulada",
                name="estado_resolucion",
                create_type=False,
                schema="fiscal",
            ),
            server_default="borrador",
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "modo_numeracion <> 'local' OR nodo_propietario_id IS NOT NULL",
            name=op.f("ck_resoluciones_numeracion_propietario_local"),
        ),
        sa.CheckConstraint(
            "modo_numeracion <> 'proveedor' OR id_rango_proveedor IS NOT NULL",
            name=op.f("ck_resoluciones_numeracion_rango_proveedor"),
        ),
        sa.CheckConstraint("prefijo ~ '^[A-Z0-9]{0,4}$'", name=op.f("ck_resoluciones_numeracion_prefijo_formato")),
        sa.CheckConstraint("caja_id IS NULL OR sede_id IS NOT NULL", name=op.f("ck_resoluciones_numeracion_alcance")),
        sa.CheckConstraint(
            "consecutivo_actual BETWEEN rango_desde - 1 AND rango_hasta",
            name=op.f("ck_resoluciones_numeracion_consecutivo_en_rango"),
        ),
        sa.CheckConstraint(
            "rango_desde >= 1 AND rango_hasta >= rango_desde", name=op.f("ck_resoluciones_numeracion_rango_valido")
        ),
        sa.CheckConstraint("vigente_hasta > vigente_desde", name=op.f("ck_resoluciones_numeracion_vigencia_valida")),
        sa.ForeignKeyConstraint(
            ["caja_id"], ["cajas.cajas.id"], name=op.f("fk_resoluciones_numeracion_caja_id_cajas"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["empresa_id"],
            ["organizacion.empresas.id"],
            name=op.f("fk_resoluciones_numeracion_empresa_id_empresas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["nodo_propietario_id"],
            ["organizacion.nodos.id"],
            name=op.f("fk_resoluciones_numeracion_nodo_propietario_id_nodos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"],
            ["organizacion.sedes.id"],
            name=op.f("fk_resoluciones_numeracion_sede_id_sedes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tipo_documento_codigo"],
            ["referencia.tipos_documento_fiscal.codigo"],
            name=op.f("fk_resoluciones_numeracion_tipo_documento_codigo_tipos_documento_fiscal"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resoluciones_numeracion")),
        schema="fiscal",
    )
    op.create_index(
        "ix_resoluciones_propietario",
        "resoluciones_numeracion",
        ["nodo_propietario_id", "estado"],
        unique=False,
        schema="fiscal",
    )
    op.create_index(
        "uq_resoluciones_activa_caja",
        "resoluciones_numeracion",
        ["caja_id", "tipo_documento_codigo"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("estado = 'activa' AND caja_id IS NOT NULL"),
    )
    op.create_index(
        "uq_resoluciones_activa_empresa",
        "resoluciones_numeracion",
        ["empresa_id", "tipo_documento_codigo"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("estado = 'activa' AND sede_id IS NULL"),
    )
    op.create_index(
        "uq_resoluciones_activa_sede",
        "resoluciones_numeracion",
        ["sede_id", "tipo_documento_codigo"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("estado = 'activa' AND caja_id IS NULL AND sede_id IS NOT NULL"),
    )
    op.create_table(
        "existencias",
        sa.Column("bodega_id", sa.Uuid(), nullable=False),
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False),
        sa.Column("cantidad_reservada", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False),
        sa.Column("costo_promedio", sa.Numeric(precision=18, scale=4), server_default="0", nullable=False),
        sa.Column("ultimo_costo", sa.Numeric(precision=18, scale=4), server_default="0", nullable=False),
        sa.Column("stock_minimo", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("ultima_secuencia", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("cantidad_reservada >= 0", name=op.f("ck_existencias_reservada_no_negativa")),
        sa.ForeignKeyConstraint(
            ["bodega_id"], ["inventario.bodegas.id"], name=op.f("fk_existencias_bodega_id_bodegas"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_existencias_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("bodega_id", "producto_id", name=op.f("pk_existencias")),
        schema="inventario",
    )
    op.create_index(
        "ix_existencias_negativas",
        "existencias",
        ["bodega_id"],
        unique=False,
        schema="inventario",
        postgresql_where=sa.text("cantidad < 0"),
    )
    op.create_index("ix_existencias_producto_id", "existencias", ["producto_id"], unique=False, schema="inventario")
    op.create_table(
        "movimientos_inventario",
        sa.Column("bodega_id", sa.Uuid(), nullable=False),
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("secuencia", sa.BigInteger(), nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "saldo_inicial",
                "entrada_compra",
                "devolucion_proveedor",
                "venta",
                "devolucion_venta",
                "ajuste_positivo",
                "ajuste_negativo",
                "traslado_salida",
                "traslado_entrada",
                name="tipo_movimiento",
                create_type=False,
                schema="inventario",
            ),
            nullable=False,
        ),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("costo_unitario", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("costo_estimado", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("saldo_cantidad", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("costo_promedio_resultante", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column(
            "origen_tipo",
            postgresql.ENUM(
                "saldo_inicial",
                "recepcion",
                "devolucion_proveedor",
                "venta",
                "devolucion_venta",
                "traslado",
                "ajuste",
                name="origen_movimiento",
                create_type=False,
                schema="inventario",
            ),
            nullable=False,
        ),
        sa.Column("origen_id", sa.Uuid(), nullable=False),
        sa.Column("origen_linea_id", sa.Uuid(), nullable=False),
        sa.Column("ocurrido_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(tipo = 'saldo_inicial' AND origen_tipo = 'saldo_inicial') OR (tipo = 'entrada_compra' AND origen_tipo = 'recepcion') OR (tipo = 'devolucion_proveedor' AND origen_tipo = 'devolucion_proveedor') OR (tipo = 'venta' AND origen_tipo = 'venta') OR (tipo = 'devolucion_venta' AND origen_tipo = 'devolucion_venta') OR (tipo IN ('traslado_salida','traslado_entrada') AND origen_tipo = 'traslado') OR (tipo IN ('ajuste_positivo','ajuste_negativo') AND origen_tipo = 'ajuste')",
            name=op.f("ck_movimientos_inventario_origen_coherente"),
        ),
        sa.CheckConstraint(
            "(tipo IN ('saldo_inicial','entrada_compra','devolucion_venta','ajuste_positivo','traslado_entrada') AND cantidad > 0) OR (tipo IN ('devolucion_proveedor','venta','ajuste_negativo','traslado_salida') AND cantidad < 0)",
            name=op.f("ck_movimientos_inventario_cantidad_signo"),
        ),
        sa.CheckConstraint("costo_unitario >= 0", name=op.f("ck_movimientos_inventario_costo_no_negativo")),
        sa.ForeignKeyConstraint(
            ["bodega_id"],
            ["inventario.bodegas.id"],
            name=op.f("fk_movimientos_inventario_bodega_id_bodegas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_movimientos_inventario_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_movimientos_inventario")),
        sa.UniqueConstraint("bodega_id", "producto_id", "secuencia", name="uq_movimientos_inventario_secuencia"),
        sa.UniqueConstraint(
            "origen_tipo", "origen_linea_id", "tipo", "bodega_id", name="uq_movimientos_inventario_idempotencia"
        ),
        schema="inventario",
    )
    op.create_index(
        "ix_movimientos_inventario_kardex",
        "movimientos_inventario",
        ["producto_id", "bodega_id", sa.literal_column("ocurrido_at DESC")],
        unique=False,
        schema="inventario",
    )
    op.create_index(
        "ix_movimientos_inventario_origen",
        "movimientos_inventario",
        ["origen_tipo", "origen_id"],
        unique=False,
        schema="inventario",
    )
    op.create_table(
        "productos_ubicaciones",
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("ubicacion_id", sa.Uuid(), nullable=False),
        sa.Column("es_principal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_productos_ubicaciones_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ubicacion_id"],
            ["inventario.ubicaciones.id"],
            name=op.f("fk_productos_ubicaciones_ubicacion_id_ubicaciones"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("producto_id", "ubicacion_id", name=op.f("pk_productos_ubicaciones")),
        schema="inventario",
    )
    op.create_index(
        "ix_productos_ubicaciones_ubicacion_id",
        "productos_ubicaciones",
        ["ubicacion_id"],
        unique=False,
        schema="inventario",
    )
    op.create_table(
        "turnos",
        sa.Column("caja_id", sa.Uuid(), nullable=False),
        sa.Column("dispositivo_id", sa.Uuid(), nullable=True),
        sa.Column(
            "estado",
            postgresql.ENUM("abierto", "cerrado", name="estado_turno", create_type=False, schema="cajas"),
            server_default="abierto",
            nullable=False,
        ),
        sa.Column("abierto_por_id", sa.Uuid(), nullable=False),
        sa.Column("abierto_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("base_efectivo", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cerrado_por_id", sa.Uuid(), nullable=True),
        sa.Column("supervisor_cierre_id", sa.Uuid(), nullable=True),
        sa.Column("autorizacion_cierre_id", sa.Uuid(), nullable=True),
        sa.Column("cerrado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("efectivo_esperado", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("efectivo_contado", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "estado = 'abierto' OR (cerrado_at IS NOT NULL AND cerrado_por_id IS NOT NULL AND efectivo_esperado IS NOT NULL AND efectivo_contado IS NOT NULL)",
            name=op.f("ck_turnos_cierre_completo"),
        ),
        sa.CheckConstraint("base_efectivo >= 0", name=op.f("ck_turnos_base_no_negativa")),
        sa.CheckConstraint(
            "efectivo_contado IS NULL OR efectivo_contado >= 0", name=op.f("ck_turnos_contado_no_negativo")
        ),
        sa.CheckConstraint(
            "supervisor_cierre_id IS NULL OR supervisor_cierre_id <> cerrado_por_id",
            name=op.f("ck_turnos_supervisor_distinto"),
        ),
        sa.ForeignKeyConstraint(
            ["abierto_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_turnos_abierto_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["autorizacion_cierre_id"],
            ["identidad.autorizaciones.id"],
            name=op.f("fk_turnos_autorizacion_cierre_id_autorizaciones"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["caja_id"], ["cajas.cajas.id"], name=op.f("fk_turnos_caja_id_cajas"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["cerrado_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_turnos_cerrado_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dispositivo_id"],
            ["cajas.dispositivos.id"],
            name=op.f("fk_turnos_dispositivo_id_dispositivos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supervisor_cierre_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_turnos_supervisor_cierre_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_turnos")),
        schema="cajas",
    )
    op.create_index(
        "ix_turnos_caja_fecha",
        "turnos",
        ["caja_id", sa.literal_column("abierto_at DESC")],
        unique=False,
        schema="cajas",
    )
    op.create_index(
        "uq_turnos_abierto_por_caja",
        "turnos",
        ["caja_id"],
        unique=True,
        schema="cajas",
        postgresql_where=sa.text("estado = 'abierto'"),
    )
    op.create_index(
        "uq_turnos_abierto_por_cajero",
        "turnos",
        ["abierto_por_id"],
        unique=True,
        schema="cajas",
        postgresql_where=sa.text("estado = 'abierto'"),
    )
    op.create_table(
        "alertas_stock",
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "stock_negativo",
                "bajo_minimo",
                "reserva_sin_stock",
                name="tipo_alerta_stock",
                create_type=False,
                schema="inventario",
            ),
            nullable=False,
        ),
        sa.Column("bodega_id", sa.Uuid(), nullable=False),
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("movimiento_id", sa.Uuid(), nullable=True),
        sa.Column("cantidad_resultante", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "abierta", "reconocida", "resuelta", name="estado_alerta", create_type=False, schema="inventario"
            ),
            server_default="abierta",
            nullable=False,
        ),
        sa.Column("resuelta_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resuelta_por_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["bodega_id"],
            ["inventario.bodegas.id"],
            name=op.f("fk_alertas_stock_bodega_id_bodegas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["movimiento_id"],
            ["inventario.movimientos_inventario.id"],
            name=op.f("fk_alertas_stock_movimiento_id_movimientos_inventario"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_alertas_stock_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resuelta_por_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_alertas_stock_resuelta_por_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alertas_stock")),
        schema="inventario",
    )
    op.create_index(
        "ix_alertas_stock_estado",
        "alertas_stock",
        ["estado", sa.literal_column("created_at DESC")],
        unique=False,
        schema="inventario",
        postgresql_where=sa.text("estado <> 'resuelta'"),
    )
    op.create_index(
        "uq_alertas_stock_abierta",
        "alertas_stock",
        ["bodega_id", "producto_id", "tipo"],
        unique=True,
        schema="inventario",
        postgresql_where=sa.text("estado <> 'resuelta'"),
    )
    op.create_table(
        "reservas_stock",
        sa.Column("bodega_id", sa.Uuid(), nullable=False),
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "activa",
                "consumida",
                "liberada",
                "expirada",
                name="estado_reserva",
                create_type=False,
                schema="inventario",
            ),
            server_default="activa",
            nullable=False,
        ),
        sa.Column("origen_tipo", sa.Text(), server_default="pedido", nullable=False),
        sa.Column("origen_id", sa.Uuid(), nullable=False),
        sa.Column("origen_linea_id", sa.Uuid(), nullable=False),
        sa.Column("expira_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cerrada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("movimiento_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("origen_tipo IN ('pedido','manual')", name=op.f("ck_reservas_stock_origen_tipo_valido")),
        sa.CheckConstraint("cantidad > 0", name=op.f("ck_reservas_stock_cantidad_positiva")),
        sa.ForeignKeyConstraint(
            ["bodega_id"],
            ["inventario.bodegas.id"],
            name=op.f("fk_reservas_stock_bodega_id_bodegas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["movimiento_id"],
            ["inventario.movimientos_inventario.id"],
            name=op.f("fk_reservas_stock_movimiento_id_movimientos_inventario"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_reservas_stock_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservas_stock")),
        schema="inventario",
    )
    op.create_index(
        "ix_reservas_stock_origen", "reservas_stock", ["origen_tipo", "origen_id"], unique=False, schema="inventario"
    )
    op.create_index(
        "ix_reservas_stock_producto",
        "reservas_stock",
        ["bodega_id", "producto_id"],
        unique=False,
        schema="inventario",
        postgresql_where=sa.text("estado = 'activa'"),
    )
    op.create_index(
        "ix_reservas_stock_vencimiento",
        "reservas_stock",
        ["expira_at"],
        unique=False,
        schema="inventario",
        postgresql_where=sa.text("estado = 'activa'"),
    )
    op.create_index(
        "uq_reservas_stock_linea",
        "reservas_stock",
        ["origen_tipo", "origen_linea_id"],
        unique=True,
        schema="inventario",
        postgresql_where=sa.text("estado = 'activa'"),
    )
    op.create_table(
        "arqueos_turno",
        sa.Column("turno_id", sa.Uuid(), nullable=False),
        sa.Column("medio_pago_codigo", sa.Text(), nullable=False),
        sa.Column("valor_esperado", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("valor_contado", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("observacion", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["medio_pago_codigo"],
            ["referencia.medios_pago.codigo"],
            name=op.f("fk_arqueos_turno_medio_pago_codigo_medios_pago"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["turno_id"], ["cajas.turnos.id"], name=op.f("fk_arqueos_turno_turno_id_turnos"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_arqueos_turno")),
        sa.UniqueConstraint("turno_id", "medio_pago_codigo", name="uq_arqueos_turno_turno_medio"),
        schema="cajas",
    )
    op.create_table(
        "movimientos_caja",
        sa.Column("turno_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM("ingreso", "retiro", name="tipo_movimiento_caja", create_type=False, schema="cajas"),
            nullable=False,
        ),
        sa.Column("valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("motivo_id", sa.Uuid(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("autorizacion_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("valor > 0", name=op.f("ck_movimientos_caja_valor_positivo")),
        sa.ForeignKeyConstraint(
            ["autorizacion_id"],
            ["identidad.autorizaciones.id"],
            name=op.f("fk_movimientos_caja_autorizacion_id_autorizaciones"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["motivo_id"],
            ["cajas.motivos_movimiento_caja.id"],
            name=op.f("fk_movimientos_caja_motivo_id_motivos_movimiento_caja"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["turno_id"], ["cajas.turnos.id"], name=op.f("fk_movimientos_caja_turno_id_turnos"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_movimientos_caja")),
        schema="cajas",
    )
    op.create_index(
        "ix_movimientos_caja_turno", "movimientos_caja", ["turno_id", "created_at"], unique=False, schema="cajas"
    )
    op.create_table(
        "ventas",
        sa.Column(
            "canal",
            postgresql.ENUM("pos", "web", name="canal_venta", create_type=False, schema="ventas"),
            nullable=False,
        ),
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("caja_id", sa.Uuid(), nullable=True),
        sa.Column("turno_id", sa.Uuid(), nullable=True),
        sa.Column("vendedor_id", sa.Uuid(), nullable=True),
        sa.Column("tercero_id", sa.Uuid(), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "borrador", "confirmada", "descartada", name="estado_venta", create_type=False, schema="ventas"
            ),
            server_default="borrador",
            nullable=False,
        ),
        sa.Column("tipo_documento_fiscal_codigo", sa.Text(), server_default="FE", nullable=False),
        sa.Column("forma_pago_codigo", sa.Text(), server_default="1", nullable=False),
        sa.Column("lista_precio_id", sa.Uuid(), nullable=True),
        sa.Column("numero_interno", sa.BigInteger(), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("descuento_total", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("impuesto_total", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("redondeo", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("moneda", sa.Text(), server_default="COP", nullable=False),
        sa.Column("placa_vehiculo", sa.Text(), nullable=True),
        sa.Column("confirmada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "canal <> 'pos' OR (caja_id IS NOT NULL AND turno_id IS NOT NULL)", name=op.f("ck_ventas_canal_pos")
        ),
        sa.CheckConstraint(
            "canal <> 'web' OR (caja_id IS NULL AND turno_id IS NULL)", name=op.f("ck_ventas_canal_web")
        ),
        sa.CheckConstraint(
            "estado <> 'confirmada' OR (confirmada_at IS NOT NULL AND (canal = 'web' OR numero_interno IS NOT NULL))",
            name=op.f("ck_ventas_confirmada"),
        ),
        sa.CheckConstraint("tipo_documento_fiscal_codigo IN ('FE','POS_E')", name=op.f("ck_ventas_tipo_documento")),
        sa.CheckConstraint(
            "subtotal >= 0 AND descuento_total >= 0 AND impuesto_total >= 0", name=op.f("ck_ventas_montos_no_negativos")
        ),
        sa.CheckConstraint("total = subtotal + impuesto_total + redondeo", name=op.f("ck_ventas_total")),
        sa.ForeignKeyConstraint(
            ["caja_id"], ["cajas.cajas.id"], name=op.f("fk_ventas_caja_id_cajas"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["forma_pago_codigo"],
            ["referencia.formas_pago.codigo"],
            name=op.f("fk_ventas_forma_pago_codigo_formas_pago"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lista_precio_id"],
            ["catalogo.listas_precios.id"],
            name=op.f("fk_ventas_lista_precio_id_listas_precios"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_ventas_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tercero_id"], ["identidad.terceros.id"], name=op.f("fk_ventas_tercero_id_terceros"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tipo_documento_fiscal_codigo"],
            ["referencia.tipos_documento_fiscal.codigo"],
            name=op.f("fk_ventas_tipo_documento_fiscal_codigo_tipos_documento_fiscal"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["turno_id"], ["cajas.turnos.id"], name=op.f("fk_ventas_turno_id_turnos"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["vendedor_id"],
            ["identidad.empleados.id"],
            name=op.f("fk_ventas_vendedor_id_empleados"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ventas")),
        schema="ventas",
    )
    op.create_index(
        "ix_ventas_borradores",
        "ventas",
        ["caja_id"],
        unique=False,
        schema="ventas",
        postgresql_where=sa.text("estado = 'borrador'"),
    )
    op.create_index(
        "ix_ventas_placa",
        "ventas",
        ["placa_vehiculo"],
        unique=False,
        schema="ventas",
        postgresql_where=sa.text("placa_vehiculo IS NOT NULL"),
    )
    op.create_index(
        "ix_ventas_sede_fecha",
        "ventas",
        ["sede_id", sa.literal_column("confirmada_at DESC")],
        unique=False,
        schema="ventas",
        postgresql_where=sa.text("estado = 'confirmada'"),
    )
    op.create_index(
        "ix_ventas_tercero_fecha",
        "ventas",
        ["tercero_id", sa.literal_column("confirmada_at DESC")],
        unique=False,
        schema="ventas",
    )
    op.create_index(
        "ix_ventas_turno",
        "ventas",
        ["turno_id"],
        unique=False,
        schema="ventas",
        postgresql_where=sa.text("turno_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ventas_vendedor",
        "ventas",
        ["vendedor_id", sa.literal_column("confirmada_at DESC")],
        unique=False,
        schema="ventas",
        postgresql_where=sa.text("vendedor_id IS NOT NULL"),
    )
    op.create_index(
        "uq_ventas_numero_interno",
        "ventas",
        ["caja_id", "numero_interno"],
        unique=True,
        schema="ventas",
        postgresql_where=sa.text("numero_interno IS NOT NULL"),
    )
    op.create_table(
        "devoluciones",
        sa.Column("venta_id", sa.Uuid(), nullable=False),
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("turno_id", sa.Uuid(), nullable=True),
        sa.Column("motivo_id", sa.Uuid(), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM("borrador", "confirmada", name="estado_devolucion", create_type=False, schema="ventas"),
            server_default="borrador",
            nullable=False,
        ),
        sa.Column(
            "tipo_resolucion",
            postgresql.ENUM("nota_credito", "nota_ajuste", name="tipo_resolucion", create_type=False, schema="ventas"),
            nullable=False,
        ),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("impuesto_total", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("redondeo", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("autorizacion_id", sa.Uuid(), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("confirmada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "estado <> 'confirmada' OR confirmada_at IS NOT NULL", name=op.f("ck_devoluciones_confirmada")
        ),
        sa.CheckConstraint("total = subtotal + impuesto_total + redondeo", name=op.f("ck_devoluciones_total")),
        sa.ForeignKeyConstraint(
            ["autorizacion_id"],
            ["identidad.autorizaciones.id"],
            name=op.f("fk_devoluciones_autorizacion_id_autorizaciones"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["motivo_id"],
            ["ventas.motivos_devolucion.id"],
            name=op.f("fk_devoluciones_motivo_id_motivos_devolucion"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"], ["organizacion.sedes.id"], name=op.f("fk_devoluciones_sede_id_sedes"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["turno_id"], ["cajas.turnos.id"], name=op.f("fk_devoluciones_turno_id_turnos"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["venta_id"], ["ventas.ventas.id"], name=op.f("fk_devoluciones_venta_id_ventas"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devoluciones")),
        schema="ventas",
    )
    op.create_index(
        "ix_devoluciones_sede_fecha",
        "devoluciones",
        ["sede_id", sa.literal_column("confirmada_at DESC")],
        unique=False,
        schema="ventas",
        postgresql_where=sa.text("estado = 'confirmada'"),
    )
    op.create_index(
        "ix_devoluciones_turno",
        "devoluciones",
        ["turno_id"],
        unique=False,
        schema="ventas",
        postgresql_where=sa.text("turno_id IS NOT NULL"),
    )
    op.create_index("ix_devoluciones_venta_id", "devoluciones", ["venta_id"], unique=False, schema="ventas")
    op.create_table(
        "ventas_items",
        sa.Column("venta_id", sa.Uuid(), nullable=False),
        sa.Column("linea", sa.SmallInteger(), nullable=False),
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("bodega_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("unidad_codigo", sa.Text(), nullable=False),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("precio_lista", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("precio_unitario_base", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("descuento_pct", sa.Numeric(precision=7, scale=4), server_default="0", nullable=False),
        sa.Column("descuento_valor", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("impuesto_codigo", sa.Text(), nullable=False),
        sa.Column("tributo_codigo", sa.Text(), nullable=False),
        sa.Column("tarifa_pct", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("bruto_linea", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total_linea", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("base_gravable", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("impuesto_valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("costo_unitario", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("costo_estimado", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("autorizacion_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "base_gravable + impuesto_valor = total_linea", name=op.f("ck_ventas_items_base_mas_impuesto")
        ),
        sa.CheckConstraint(
            "bruto_linea = round(cantidad * precio_unitario, 2)", name=op.f("ck_ventas_items_bruto_linea")
        ),
        sa.CheckConstraint("cantidad > 0", name=op.f("ck_ventas_items_cantidad_positiva")),
        sa.CheckConstraint("descuento_pct BETWEEN 0 AND 100", name=op.f("ck_ventas_items_descuento_rango")),
        sa.CheckConstraint("total_linea = bruto_linea - descuento_valor", name=op.f("ck_ventas_items_total_linea")),
        sa.ForeignKeyConstraint(
            ["autorizacion_id"],
            ["identidad.autorizaciones.id"],
            name=op.f("fk_ventas_items_autorizacion_id_autorizaciones"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["bodega_id"],
            ["inventario.bodegas.id"],
            name=op.f("fk_ventas_items_bodega_id_bodegas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_ventas_items_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["venta_id"], ["ventas.ventas.id"], name=op.f("fk_ventas_items_venta_id_ventas"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ventas_items")),
        sa.UniqueConstraint("venta_id", "linea", name="uq_ventas_items_venta_linea"),
        schema="ventas",
    )
    op.create_index(
        "ix_ventas_items_producto", "ventas_items", ["producto_id", "venta_id"], unique=False, schema="ventas"
    )
    op.create_table(
        "ventas_pagos",
        sa.Column("venta_id", sa.Uuid(), nullable=False),
        sa.Column("medio_pago_codigo", sa.Text(), nullable=False),
        sa.Column("valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("valor_recibido", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("cambio_devuelto", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column(
            "canal_pago",
            postgresql.ENUM(
                "manual", "datafono", "qr", "pasarela", name="canal_pago", create_type=False, schema="ventas"
            ),
            server_default="manual",
            nullable=False,
        ),
        sa.Column("referencia", sa.Text(), nullable=True),
        sa.Column("terminal", sa.Text(), nullable=True),
        sa.Column("ultimos_digitos", sa.Text(), nullable=True),
        sa.Column("franquicia", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "ultimos_digitos IS NULL OR ultimos_digitos ~ '^[0-9]{4}$'", name=op.f("ck_ventas_pagos_ultimos_digitos")
        ),
        sa.CheckConstraint("cambio_devuelto >= 0", name=op.f("ck_ventas_pagos_cambio_no_negativo")),
        sa.CheckConstraint("valor > 0", name=op.f("ck_ventas_pagos_valor_positivo")),
        sa.CheckConstraint(
            "valor_recibido IS NULL OR valor_recibido - cambio_devuelto = valor",
            name=op.f("ck_ventas_pagos_recibido_cuadra"),
        ),
        sa.ForeignKeyConstraint(
            ["medio_pago_codigo"],
            ["referencia.medios_pago.codigo"],
            name=op.f("fk_ventas_pagos_medio_pago_codigo_medios_pago"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["venta_id"], ["ventas.ventas.id"], name=op.f("fk_ventas_pagos_venta_id_ventas"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ventas_pagos")),
        schema="ventas",
    )
    op.create_index(
        "ix_ventas_pagos_medio_fecha",
        "ventas_pagos",
        ["medio_pago_codigo", "created_at"],
        unique=False,
        schema="ventas",
    )
    op.create_index("ix_ventas_pagos_venta_id", "ventas_pagos", ["venta_id"], unique=False, schema="ventas")
    op.create_table(
        "documentos_fiscales",
        sa.Column("empresa_id", sa.Uuid(), nullable=False),
        sa.Column("sede_id", sa.Uuid(), nullable=False),
        sa.Column("caja_id", sa.Uuid(), nullable=True),
        sa.Column("tipo_documento_codigo", sa.Text(), nullable=False),
        sa.Column("resolucion_id", sa.Uuid(), nullable=False),
        sa.Column("prefijo", sa.Text(), nullable=True),
        sa.Column("consecutivo", sa.BigInteger(), nullable=True),
        sa.Column("fecha_emision", sa.DateTime(timezone=True), nullable=False),
        sa.Column("venta_id", sa.Uuid(), nullable=True),
        sa.Column("devolucion_id", sa.Uuid(), nullable=True),
        sa.Column("documento_referenciado_id", sa.Uuid(), nullable=True),
        sa.Column("concepto_nota_codigo", sa.Text(), nullable=True),
        sa.Column("forma_pago_codigo", sa.Text(), server_default="1", nullable=False),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
        sa.Column("emisor_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("adquirente_tercero_id", sa.Uuid(), nullable=True),
        sa.Column("adquirente_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("adquirente_numero_documento", sa.Text(), nullable=False),
        sa.Column("adquirente_nombre", sa.Text(), nullable=False),
        sa.Column("moneda", sa.Text(), server_default="COP", nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("descuento_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("impuesto_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("redondeo", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "borrador",
                "pendiente_envio",
                "enviado",
                "aceptado",
                "rechazado",
                "contingencia",
                name="estado_documento_fiscal",
                create_type=False,
                schema="fiscal",
            ),
            server_default="borrador",
            nullable=False,
        ),
        sa.Column("vigente", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("cufe_cude", sa.Text(), nullable=True),
        sa.Column("qr_data", sa.Text(), nullable=True),
        sa.Column("proveedor_documento_id", sa.Text(), nullable=True),
        sa.Column("proveedor_respuesta_codigo", sa.Text(), nullable=True),
        sa.Column("xml_url", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("intentos", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.Column("ultimo_intento_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proximo_intento_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("es_contingencia", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("contingencia_motivo", sa.Text(), nullable=True),
        sa.Column("enviado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aceptado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hash_contenido", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "estado <> 'aceptado' OR (cufe_cude IS NOT NULL AND aceptado_at IS NOT NULL AND consecutivo IS NOT NULL)",
            name=op.f("ck_documentos_fiscales_aceptado"),
        ),
        sa.CheckConstraint(
            "tipo_documento_codigo NOT IN ('NC','ND','NA') OR (documento_referenciado_id IS NOT NULL AND concepto_nota_codigo IS NOT NULL)",
            name=op.f("ck_documentos_fiscales_nota"),
        ),
        sa.CheckConstraint("(prefijo IS NULL) = (consecutivo IS NULL)", name=op.f("ck_documentos_fiscales_numero_par")),
        sa.CheckConstraint("num_nonnulls(venta_id, devolucion_id) = 1", name=op.f("ck_documentos_fiscales_origen")),
        sa.CheckConstraint("total = subtotal + impuesto_total + redondeo", name=op.f("ck_documentos_fiscales_total")),
        sa.ForeignKeyConstraint(
            ["adquirente_tercero_id"],
            ["identidad.terceros.id"],
            name=op.f("fk_documentos_fiscales_adquirente_tercero_id_terceros"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["caja_id"], ["cajas.cajas.id"], name=op.f("fk_documentos_fiscales_caja_id_cajas"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["devolucion_id"],
            ["ventas.devoluciones.id"],
            name=op.f("fk_documentos_fiscales_devolucion_id_devoluciones"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["documento_referenciado_id"],
            ["fiscal.documentos_fiscales.id"],
            name=op.f("fk_documentos_fiscales_documento_referenciado_id_documentos_fiscales"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["empresa_id"],
            ["organizacion.empresas.id"],
            name=op.f("fk_documentos_fiscales_empresa_id_empresas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["forma_pago_codigo"],
            ["referencia.formas_pago.codigo"],
            name=op.f("fk_documentos_fiscales_forma_pago_codigo_formas_pago"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolucion_id"],
            ["fiscal.resoluciones_numeracion.id"],
            name=op.f("fk_documentos_fiscales_resolucion_id_resoluciones_numeracion"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sede_id"],
            ["organizacion.sedes.id"],
            name=op.f("fk_documentos_fiscales_sede_id_sedes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tipo_documento_codigo", "concepto_nota_codigo"],
            ["referencia.conceptos_nota.tipo_documento_codigo", "referencia.conceptos_nota.codigo"],
            name="fk_documentos_fiscales_concepto_nota",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tipo_documento_codigo"],
            ["referencia.tipos_documento_fiscal.codigo"],
            name=op.f("fk_documentos_fiscales_tipo_documento_codigo_tipos_documento_fiscal"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["venta_id"], ["ventas.ventas.id"], name=op.f("fk_documentos_fiscales_venta_id_ventas"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documentos_fiscales")),
        schema="fiscal",
    )
    op.create_index(
        "ix_documentos_fiscales_adquirente",
        "documentos_fiscales",
        ["adquirente_numero_documento", sa.literal_column("fecha_emision DESC")],
        unique=False,
        schema="fiscal",
    )
    op.create_index(
        "ix_documentos_fiscales_cola",
        "documentos_fiscales",
        [sa.literal_column("proximo_intento_at NULLS FIRST")],
        unique=False,
        schema="fiscal",
        postgresql_where=sa.text("estado IN ('pendiente_envio','contingencia','rechazado')"),
    )
    op.create_index(
        "ix_documentos_fiscales_contingencia",
        "documentos_fiscales",
        ["sede_id"],
        unique=False,
        schema="fiscal",
        postgresql_where=sa.text("es_contingencia AND estado <> 'aceptado'"),
    )
    op.create_index(
        "ix_documentos_fiscales_fecha",
        "documentos_fiscales",
        ["empresa_id", "tipo_documento_codigo", sa.literal_column("fecha_emision DESC")],
        unique=False,
        schema="fiscal",
    )
    op.create_index(
        "ix_documentos_fiscales_referenciado",
        "documentos_fiscales",
        ["documento_referenciado_id"],
        unique=False,
        schema="fiscal",
        postgresql_where=sa.text("documento_referenciado_id IS NOT NULL"),
    )
    op.create_index(
        "ix_documentos_fiscales_sede",
        "documentos_fiscales",
        ["sede_id", sa.literal_column("fecha_emision DESC")],
        unique=False,
        schema="fiscal",
    )
    op.create_index(
        "uq_documentos_fiscales_cufe",
        "documentos_fiscales",
        ["cufe_cude"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("cufe_cude IS NOT NULL"),
    )
    op.create_index(
        "uq_documentos_fiscales_devolucion",
        "documentos_fiscales",
        ["devolucion_id"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("devolucion_id IS NOT NULL"),
    )
    op.create_index(
        "uq_documentos_fiscales_numero",
        "documentos_fiscales",
        ["empresa_id", "tipo_documento_codigo", "prefijo", "consecutivo"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("consecutivo IS NOT NULL"),
    )
    op.create_index(
        "uq_documentos_fiscales_proveedor",
        "documentos_fiscales",
        ["resolucion_id", "proveedor_documento_id"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("proveedor_documento_id IS NOT NULL"),
    )
    op.create_index(
        "uq_documentos_fiscales_resolucion",
        "documentos_fiscales",
        ["resolucion_id", "consecutivo"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("consecutivo IS NOT NULL"),
    )
    op.create_index(
        "uq_documentos_fiscales_venta_vigente",
        "documentos_fiscales",
        ["venta_id"],
        unique=True,
        schema="fiscal",
        postgresql_where=sa.text("vigente AND tipo_documento_codigo IN ('FE','POS_E')"),
    )
    op.create_table(
        "devoluciones_items",
        sa.Column("devolucion_id", sa.Uuid(), nullable=False),
        sa.Column("venta_item_id", sa.Uuid(), nullable=False),
        sa.Column("producto_id", sa.Uuid(), nullable=False),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("tarifa_pct", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("descuento_valor", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("total_linea", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("base_gravable", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("impuesto_valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("costo_unitario", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("reintegra_stock", sa.Boolean(), nullable=False),
        sa.Column("bodega_reintegro_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "base_gravable + impuesto_valor = total_linea", name=op.f("ck_devoluciones_items_base_mas_impuesto")
        ),
        sa.CheckConstraint("cantidad > 0", name=op.f("ck_devoluciones_items_cantidad_positiva")),
        sa.CheckConstraint(
            "reintegra_stock = (bodega_reintegro_id IS NOT NULL)", name=op.f("ck_devoluciones_items_reintegro_bodega")
        ),
        sa.ForeignKeyConstraint(
            ["bodega_reintegro_id"],
            ["inventario.bodegas.id"],
            name=op.f("fk_devoluciones_items_bodega_reintegro_id_bodegas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["devolucion_id"],
            ["ventas.devoluciones.id"],
            name=op.f("fk_devoluciones_items_devolucion_id_devoluciones"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_devoluciones_items_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["venta_item_id"],
            ["ventas.ventas_items.id"],
            name=op.f("fk_devoluciones_items_venta_item_id_ventas_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devoluciones_items")),
        sa.UniqueConstraint("devolucion_id", "venta_item_id", name="uq_devoluciones_items_devolucion_item"),
        schema="ventas",
    )
    op.create_index(
        "ix_devoluciones_items_venta_item", "devoluciones_items", ["venta_item_id"], unique=False, schema="ventas"
    )
    op.create_table(
        "devoluciones_pagos",
        sa.Column("devolucion_id", sa.Uuid(), nullable=False),
        sa.Column("medio_pago_codigo", sa.Text(), nullable=False),
        sa.Column("valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("referencia", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("valor > 0", name=op.f("ck_devoluciones_pagos_valor_positivo")),
        sa.ForeignKeyConstraint(
            ["devolucion_id"],
            ["ventas.devoluciones.id"],
            name=op.f("fk_devoluciones_pagos_devolucion_id_devoluciones"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["medio_pago_codigo"],
            ["referencia.medios_pago.codigo"],
            name=op.f("fk_devoluciones_pagos_medio_pago_codigo_medios_pago"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devoluciones_pagos")),
        schema="ventas",
    )
    op.create_index(
        "ix_devoluciones_pagos_devolucion_id", "devoluciones_pagos", ["devolucion_id"], unique=False, schema="ventas"
    )
    op.create_table(
        "documentos_fiscales_eventos",
        sa.Column("documento_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM(
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
                name="tipo_evento_fiscal",
                create_type=False,
                schema="fiscal",
            ),
            nullable=False,
        ),
        sa.Column("intento", sa.SmallInteger(), nullable=True),
        sa.Column(
            "estado_resultante",
            postgresql.ENUM(
                "borrador",
                "pendiente_envio",
                "enviado",
                "aceptado",
                "rechazado",
                "contingencia",
                name="estado_documento_fiscal",
                create_type=False,
                schema="fiscal",
            ),
            nullable=True,
        ),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column("codigo_respuesta", sa.Text(), nullable=True),
        sa.Column("mensaje", sa.Text(), nullable=True),
        sa.Column("request_resumen", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("respuesta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duracion_ms", sa.Integer(), nullable=True),
        sa.Column("ocurrido_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["documento_id"],
            ["fiscal.documentos_fiscales.id"],
            name=op.f("fk_documentos_fiscales_eventos_documento_id_documentos_fiscales"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documentos_fiscales_eventos")),
        schema="fiscal",
    )
    op.create_index(
        "ix_documentos_fiscales_eventos_documento",
        "documentos_fiscales_eventos",
        ["documento_id", "ocurrido_at"],
        unique=False,
        schema="fiscal",
    )
    op.create_table(
        "documentos_fiscales_impuestos",
        sa.Column("documento_id", sa.Uuid(), nullable=False),
        sa.Column("tributo_codigo", sa.Text(), nullable=False),
        sa.Column("tarifa_pct", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("base_gravable", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("impuesto_valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["documento_id"],
            ["fiscal.documentos_fiscales.id"],
            name=op.f("fk_documentos_fiscales_impuestos_documento_id_documentos_fiscales"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tributo_codigo"],
            ["referencia.tributos.codigo"],
            name=op.f("fk_documentos_fiscales_impuestos_tributo_codigo_tributos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documentos_fiscales_impuestos")),
        sa.UniqueConstraint(
            "documento_id", "tributo_codigo", "tarifa_pct", name="uq_documentos_fiscales_impuestos_documento_tributo"
        ),
        schema="fiscal",
    )
    op.create_table(
        "documentos_fiscales_items",
        sa.Column("documento_id", sa.Uuid(), nullable=False),
        sa.Column("linea", sa.SmallInteger(), nullable=False),
        sa.Column("venta_item_id", sa.Uuid(), nullable=True),
        sa.Column("devolucion_item_id", sa.Uuid(), nullable=True),
        sa.Column("producto_id", sa.Uuid(), nullable=True),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("unidad_codigo", sa.Text(), nullable=False),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("valor_unitario_base", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("descuento_valor", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("base_gravable", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("impuesto_valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total_linea", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tributo_codigo", sa.Text(), nullable=False),
        sa.Column("tarifa_pct", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["devolucion_item_id"],
            ["ventas.devoluciones_items.id"],
            name=op.f("fk_documentos_fiscales_items_devolucion_item_id_devoluciones_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["documento_id"],
            ["fiscal.documentos_fiscales.id"],
            name=op.f("fk_documentos_fiscales_items_documento_id_documentos_fiscales"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["catalogo.productos.id"],
            name=op.f("fk_documentos_fiscales_items_producto_id_productos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["venta_item_id"],
            ["ventas.ventas_items.id"],
            name=op.f("fk_documentos_fiscales_items_venta_item_id_ventas_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documentos_fiscales_items")),
        sa.UniqueConstraint("documento_id", "linea", name="uq_documentos_fiscales_items_documento_linea"),
        schema="fiscal",
    )
    op.create_table(
        "documentos_fiscales_pagos",
        sa.Column("documento_id", sa.Uuid(), nullable=False),
        sa.Column("linea", sa.SmallInteger(), nullable=False),
        sa.Column("medio_pago_codigo", sa.Text(), nullable=False),
        sa.Column("valor", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("referencia", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("nodo_origen_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("valor > 0", name=op.f("ck_documentos_fiscales_pagos_valor_positivo")),
        sa.ForeignKeyConstraint(
            ["documento_id"],
            ["fiscal.documentos_fiscales.id"],
            name=op.f("fk_documentos_fiscales_pagos_documento_id_documentos_fiscales"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["medio_pago_codigo"],
            ["referencia.medios_pago.codigo"],
            name=op.f("fk_documentos_fiscales_pagos_medio_pago_codigo_medios_pago"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documentos_fiscales_pagos")),
        sa.UniqueConstraint("documento_id", "linea", name="uq_documentos_fiscales_pagos_documento_linea"),
        schema="fiscal",
    )
    # --- FKs circulares (created_by / nodo_origen_id / nodos.sede_id), al final y DEFERRABLE ---
    op.create_foreign_key(
        "fk_empleados_created_by_empleados",
        "empleados",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="identidad",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_empleados_nodo_origen_id_nodos",
        "empleados",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="identidad",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_empresas_created_by_empleados",
        "empresas",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="organizacion",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_empresas_nodo_origen_id_nodos",
        "empresas",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="organizacion",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_nodos_created_by_empleados",
        "nodos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="organizacion",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_nodos_nodo_origen_id_nodos",
        "nodos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="organizacion",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_nodos_sede_id_sedes",
        "nodos",
        "sedes",
        ["sede_id"],
        ["id"],
        source_schema="organizacion",
        referent_schema="organizacion",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_sedes_created_by_empleados",
        "sedes",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="organizacion",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_sedes_nodo_origen_id_nodos",
        "sedes",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="organizacion",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_motivos_movimiento_caja_created_by_empleados",
        "motivos_movimiento_caja",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="cajas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_motivos_movimiento_caja_nodo_origen_id_nodos",
        "motivos_movimiento_caja",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="cajas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_categorias_created_by_empleados",
        "categorias",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_categorias_nodo_origen_id_nodos",
        "categorias",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_impuestos_created_by_empleados",
        "impuestos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_impuestos_nodo_origen_id_nodos",
        "impuestos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_listas_precios_created_by_empleados",
        "listas_precios",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_listas_precios_nodo_origen_id_nodos",
        "listas_precios",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_marcas_created_by_empleados",
        "marcas",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_marcas_nodo_origen_id_nodos",
        "marcas",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_vehiculos_marcas_created_by_empleados",
        "vehiculos_marcas",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_vehiculos_marcas_nodo_origen_id_nodos",
        "vehiculos_marcas",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_configuracion_proveedor_created_by_empleados",
        "configuracion_proveedor",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="fiscal",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_configuracion_proveedor_nodo_origen_id_nodos",
        "configuracion_proveedor",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="fiscal",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_autorizaciones_created_by_empleados",
        "autorizaciones",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="identidad",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_autorizaciones_nodo_origen_id_nodos",
        "autorizaciones",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="identidad",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_roles_created_by_empleados",
        "roles",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="identidad",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_roles_nodo_origen_id_nodos",
        "roles",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="identidad",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_bodegas_created_by_empleados",
        "bodegas",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="inventario",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_bodegas_nodo_origen_id_nodos",
        "bodegas",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="inventario",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_configuracion_sede_created_by_empleados",
        "configuracion_sede",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="organizacion",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_configuracion_sede_nodo_origen_id_nodos",
        "configuracion_sede",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="organizacion",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_conflictos_sync_created_by_empleados",
        "conflictos_sync",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="sync",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_conflictos_sync_nodo_origen_id_nodos",
        "conflictos_sync",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="sync",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_inbox_eventos_nodo_origen_id_nodos",
        "inbox_eventos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="sync",
        referent_schema="organizacion",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_outbox_eventos_nodo_origen_id_nodos",
        "outbox_eventos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="sync",
        referent_schema="organizacion",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_motivos_devolucion_created_by_empleados",
        "motivos_devolucion",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="ventas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_motivos_devolucion_nodo_origen_id_nodos",
        "motivos_devolucion",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="ventas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_log_acciones_created_by_empleados",
        "log_acciones",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="auditoria",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_log_acciones_nodo_origen_id_nodos",
        "log_acciones",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="auditoria",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_cajas_created_by_empleados",
        "cajas",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="cajas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_cajas_nodo_origen_id_nodos",
        "cajas",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="cajas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_created_by_empleados",
        "productos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_nodo_origen_id_nodos",
        "productos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_vehiculos_modelos_created_by_empleados",
        "vehiculos_modelos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_vehiculos_modelos_nodo_origen_id_nodos",
        "vehiculos_modelos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_terceros_created_by_empleados",
        "terceros",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="identidad",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_terceros_nodo_origen_id_nodos",
        "terceros",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="identidad",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_ubicaciones_created_by_empleados",
        "ubicaciones",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="inventario",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_ubicaciones_nodo_origen_id_nodos",
        "ubicaciones",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="inventario",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_dispositivos_created_by_empleados",
        "dispositivos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="cajas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_dispositivos_nodo_origen_id_nodos",
        "dispositivos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="cajas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_perifericos_created_by_empleados",
        "perifericos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="cajas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_perifericos_nodo_origen_id_nodos",
        "perifericos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="cajas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_precios_created_by_empleados",
        "precios",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_precios_nodo_origen_id_nodos",
        "precios",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_codigos_barras_created_by_empleados",
        "productos_codigos_barras",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_codigos_barras_nodo_origen_id_nodos",
        "productos_codigos_barras",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_imagenes_created_by_empleados",
        "productos_imagenes",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_imagenes_nodo_origen_id_nodos",
        "productos_imagenes",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_referencias_created_by_empleados",
        "productos_referencias",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_referencias_nodo_origen_id_nodos",
        "productos_referencias",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_vehiculos_versiones_created_by_empleados",
        "vehiculos_versiones",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_vehiculos_versiones_nodo_origen_id_nodos",
        "vehiculos_versiones",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_resoluciones_numeracion_created_by_empleados",
        "resoluciones_numeracion",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="fiscal",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_resoluciones_numeracion_nodo_origen_id_nodos",
        "resoluciones_numeracion",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="fiscal",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_cuentas_clientes_created_by_empleados",
        "cuentas_clientes",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="identidad",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_cuentas_clientes_nodo_origen_id_nodos",
        "cuentas_clientes",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="identidad",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_direcciones_created_by_empleados",
        "direcciones",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="identidad",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_direcciones_nodo_origen_id_nodos",
        "direcciones",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="identidad",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_movimientos_inventario_created_by_empleados",
        "movimientos_inventario",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="inventario",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_movimientos_inventario_nodo_origen_id_nodos",
        "movimientos_inventario",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="inventario",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_turnos_created_by_empleados",
        "turnos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="cajas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_turnos_nodo_origen_id_nodos",
        "turnos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="cajas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_compatibilidades_created_by_empleados",
        "productos_compatibilidades",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="catalogo",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_productos_compatibilidades_nodo_origen_id_nodos",
        "productos_compatibilidades",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="catalogo",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_alertas_stock_created_by_empleados",
        "alertas_stock",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="inventario",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_alertas_stock_nodo_origen_id_nodos",
        "alertas_stock",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="inventario",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_reservas_stock_created_by_empleados",
        "reservas_stock",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="inventario",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_reservas_stock_nodo_origen_id_nodos",
        "reservas_stock",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="inventario",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_arqueos_turno_created_by_empleados",
        "arqueos_turno",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="cajas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_arqueos_turno_nodo_origen_id_nodos",
        "arqueos_turno",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="cajas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_movimientos_caja_created_by_empleados",
        "movimientos_caja",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="cajas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_movimientos_caja_nodo_origen_id_nodos",
        "movimientos_caja",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="cajas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_ventas_created_by_empleados",
        "ventas",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="ventas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_ventas_nodo_origen_id_nodos",
        "ventas",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="ventas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_devoluciones_created_by_empleados",
        "devoluciones",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="ventas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_devoluciones_nodo_origen_id_nodos",
        "devoluciones",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="ventas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_ventas_items_created_by_empleados",
        "ventas_items",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="ventas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_ventas_items_nodo_origen_id_nodos",
        "ventas_items",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="ventas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_ventas_pagos_created_by_empleados",
        "ventas_pagos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="ventas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_ventas_pagos_nodo_origen_id_nodos",
        "ventas_pagos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="ventas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_created_by_empleados",
        "documentos_fiscales",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="fiscal",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_nodo_origen_id_nodos",
        "documentos_fiscales",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="fiscal",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_devoluciones_items_created_by_empleados",
        "devoluciones_items",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="ventas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_devoluciones_items_nodo_origen_id_nodos",
        "devoluciones_items",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="ventas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_devoluciones_pagos_created_by_empleados",
        "devoluciones_pagos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="ventas",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_devoluciones_pagos_nodo_origen_id_nodos",
        "devoluciones_pagos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="ventas",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_eventos_created_by_empleados",
        "documentos_fiscales_eventos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="fiscal",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_eventos_nodo_origen_id_nodos",
        "documentos_fiscales_eventos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="fiscal",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_impuestos_created_by_empleados",
        "documentos_fiscales_impuestos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="fiscal",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_impuestos_nodo_origen_id_nodos",
        "documentos_fiscales_impuestos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="fiscal",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_items_created_by_empleados",
        "documentos_fiscales_items",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="fiscal",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_items_nodo_origen_id_nodos",
        "documentos_fiscales_items",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="fiscal",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_pagos_created_by_empleados",
        "documentos_fiscales_pagos",
        "empleados",
        ["created_by"],
        ["id"],
        source_schema="fiscal",
        referent_schema="identidad",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_documentos_fiscales_pagos_nodo_origen_id_nodos",
        "documentos_fiscales_pagos",
        "nodos",
        ["nodo_origen_id"],
        ["id"],
        source_schema="fiscal",
        referent_schema="organizacion",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    # --- FKs circulares ---
    op.drop_constraint("fk_empleados_created_by_empleados", "empleados", schema="identidad", type_="foreignkey")
    op.drop_constraint("fk_empleados_nodo_origen_id_nodos", "empleados", schema="identidad", type_="foreignkey")
    op.drop_constraint("fk_empresas_created_by_empleados", "empresas", schema="organizacion", type_="foreignkey")
    op.drop_constraint("fk_empresas_nodo_origen_id_nodos", "empresas", schema="organizacion", type_="foreignkey")
    op.drop_constraint("fk_nodos_created_by_empleados", "nodos", schema="organizacion", type_="foreignkey")
    op.drop_constraint("fk_nodos_nodo_origen_id_nodos", "nodos", schema="organizacion", type_="foreignkey")
    op.drop_constraint("fk_nodos_sede_id_sedes", "nodos", schema="organizacion", type_="foreignkey")
    op.drop_constraint("fk_sedes_created_by_empleados", "sedes", schema="organizacion", type_="foreignkey")
    op.drop_constraint("fk_sedes_nodo_origen_id_nodos", "sedes", schema="organizacion", type_="foreignkey")
    op.drop_constraint(
        "fk_motivos_movimiento_caja_created_by_empleados", "motivos_movimiento_caja", schema="cajas", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_motivos_movimiento_caja_nodo_origen_id_nodos", "motivos_movimiento_caja", schema="cajas", type_="foreignkey"
    )
    op.drop_constraint("fk_categorias_created_by_empleados", "categorias", schema="catalogo", type_="foreignkey")
    op.drop_constraint("fk_categorias_nodo_origen_id_nodos", "categorias", schema="catalogo", type_="foreignkey")
    op.drop_constraint("fk_impuestos_created_by_empleados", "impuestos", schema="catalogo", type_="foreignkey")
    op.drop_constraint("fk_impuestos_nodo_origen_id_nodos", "impuestos", schema="catalogo", type_="foreignkey")
    op.drop_constraint(
        "fk_listas_precios_created_by_empleados", "listas_precios", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_listas_precios_nodo_origen_id_nodos", "listas_precios", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint("fk_marcas_created_by_empleados", "marcas", schema="catalogo", type_="foreignkey")
    op.drop_constraint("fk_marcas_nodo_origen_id_nodos", "marcas", schema="catalogo", type_="foreignkey")
    op.drop_constraint(
        "fk_vehiculos_marcas_created_by_empleados", "vehiculos_marcas", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_vehiculos_marcas_nodo_origen_id_nodos", "vehiculos_marcas", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_configuracion_proveedor_created_by_empleados",
        "configuracion_proveedor",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_configuracion_proveedor_nodo_origen_id_nodos",
        "configuracion_proveedor",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_autorizaciones_created_by_empleados", "autorizaciones", schema="identidad", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_autorizaciones_nodo_origen_id_nodos", "autorizaciones", schema="identidad", type_="foreignkey"
    )
    op.drop_constraint("fk_roles_created_by_empleados", "roles", schema="identidad", type_="foreignkey")
    op.drop_constraint("fk_roles_nodo_origen_id_nodos", "roles", schema="identidad", type_="foreignkey")
    op.drop_constraint("fk_bodegas_created_by_empleados", "bodegas", schema="inventario", type_="foreignkey")
    op.drop_constraint("fk_bodegas_nodo_origen_id_nodos", "bodegas", schema="inventario", type_="foreignkey")
    op.drop_constraint(
        "fk_configuracion_sede_created_by_empleados", "configuracion_sede", schema="organizacion", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_configuracion_sede_nodo_origen_id_nodos", "configuracion_sede", schema="organizacion", type_="foreignkey"
    )
    op.drop_constraint("fk_conflictos_sync_created_by_empleados", "conflictos_sync", schema="sync", type_="foreignkey")
    op.drop_constraint("fk_conflictos_sync_nodo_origen_id_nodos", "conflictos_sync", schema="sync", type_="foreignkey")
    op.drop_constraint("fk_inbox_eventos_nodo_origen_id_nodos", "inbox_eventos", schema="sync", type_="foreignkey")
    op.drop_constraint("fk_outbox_eventos_nodo_origen_id_nodos", "outbox_eventos", schema="sync", type_="foreignkey")
    op.drop_constraint(
        "fk_motivos_devolucion_created_by_empleados", "motivos_devolucion", schema="ventas", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_motivos_devolucion_nodo_origen_id_nodos", "motivos_devolucion", schema="ventas", type_="foreignkey"
    )
    op.drop_constraint("fk_log_acciones_created_by_empleados", "log_acciones", schema="auditoria", type_="foreignkey")
    op.drop_constraint("fk_log_acciones_nodo_origen_id_nodos", "log_acciones", schema="auditoria", type_="foreignkey")
    op.drop_constraint("fk_cajas_created_by_empleados", "cajas", schema="cajas", type_="foreignkey")
    op.drop_constraint("fk_cajas_nodo_origen_id_nodos", "cajas", schema="cajas", type_="foreignkey")
    op.drop_constraint("fk_productos_created_by_empleados", "productos", schema="catalogo", type_="foreignkey")
    op.drop_constraint("fk_productos_nodo_origen_id_nodos", "productos", schema="catalogo", type_="foreignkey")
    op.drop_constraint(
        "fk_vehiculos_modelos_created_by_empleados", "vehiculos_modelos", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_vehiculos_modelos_nodo_origen_id_nodos", "vehiculos_modelos", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint("fk_terceros_created_by_empleados", "terceros", schema="identidad", type_="foreignkey")
    op.drop_constraint("fk_terceros_nodo_origen_id_nodos", "terceros", schema="identidad", type_="foreignkey")
    op.drop_constraint("fk_ubicaciones_created_by_empleados", "ubicaciones", schema="inventario", type_="foreignkey")
    op.drop_constraint("fk_ubicaciones_nodo_origen_id_nodos", "ubicaciones", schema="inventario", type_="foreignkey")
    op.drop_constraint("fk_dispositivos_created_by_empleados", "dispositivos", schema="cajas", type_="foreignkey")
    op.drop_constraint("fk_dispositivos_nodo_origen_id_nodos", "dispositivos", schema="cajas", type_="foreignkey")
    op.drop_constraint("fk_perifericos_created_by_empleados", "perifericos", schema="cajas", type_="foreignkey")
    op.drop_constraint("fk_perifericos_nodo_origen_id_nodos", "perifericos", schema="cajas", type_="foreignkey")
    op.drop_constraint("fk_precios_created_by_empleados", "precios", schema="catalogo", type_="foreignkey")
    op.drop_constraint("fk_precios_nodo_origen_id_nodos", "precios", schema="catalogo", type_="foreignkey")
    op.drop_constraint(
        "fk_productos_codigos_barras_created_by_empleados",
        "productos_codigos_barras",
        schema="catalogo",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_productos_codigos_barras_nodo_origen_id_nodos",
        "productos_codigos_barras",
        schema="catalogo",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_productos_imagenes_created_by_empleados", "productos_imagenes", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_productos_imagenes_nodo_origen_id_nodos", "productos_imagenes", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_productos_referencias_created_by_empleados", "productos_referencias", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_productos_referencias_nodo_origen_id_nodos", "productos_referencias", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_vehiculos_versiones_created_by_empleados", "vehiculos_versiones", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_vehiculos_versiones_nodo_origen_id_nodos", "vehiculos_versiones", schema="catalogo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_resoluciones_numeracion_created_by_empleados",
        "resoluciones_numeracion",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_resoluciones_numeracion_nodo_origen_id_nodos",
        "resoluciones_numeracion",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_cuentas_clientes_created_by_empleados", "cuentas_clientes", schema="identidad", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_cuentas_clientes_nodo_origen_id_nodos", "cuentas_clientes", schema="identidad", type_="foreignkey"
    )
    op.drop_constraint("fk_direcciones_created_by_empleados", "direcciones", schema="identidad", type_="foreignkey")
    op.drop_constraint("fk_direcciones_nodo_origen_id_nodos", "direcciones", schema="identidad", type_="foreignkey")
    op.drop_constraint(
        "fk_movimientos_inventario_created_by_empleados",
        "movimientos_inventario",
        schema="inventario",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_movimientos_inventario_nodo_origen_id_nodos",
        "movimientos_inventario",
        schema="inventario",
        type_="foreignkey",
    )
    op.drop_constraint("fk_turnos_created_by_empleados", "turnos", schema="cajas", type_="foreignkey")
    op.drop_constraint("fk_turnos_nodo_origen_id_nodos", "turnos", schema="cajas", type_="foreignkey")
    op.drop_constraint(
        "fk_productos_compatibilidades_created_by_empleados",
        "productos_compatibilidades",
        schema="catalogo",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_productos_compatibilidades_nodo_origen_id_nodos",
        "productos_compatibilidades",
        schema="catalogo",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_alertas_stock_created_by_empleados", "alertas_stock", schema="inventario", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_alertas_stock_nodo_origen_id_nodos", "alertas_stock", schema="inventario", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_reservas_stock_created_by_empleados", "reservas_stock", schema="inventario", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_reservas_stock_nodo_origen_id_nodos", "reservas_stock", schema="inventario", type_="foreignkey"
    )
    op.drop_constraint("fk_arqueos_turno_created_by_empleados", "arqueos_turno", schema="cajas", type_="foreignkey")
    op.drop_constraint("fk_arqueos_turno_nodo_origen_id_nodos", "arqueos_turno", schema="cajas", type_="foreignkey")
    op.drop_constraint(
        "fk_movimientos_caja_created_by_empleados", "movimientos_caja", schema="cajas", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_movimientos_caja_nodo_origen_id_nodos", "movimientos_caja", schema="cajas", type_="foreignkey"
    )
    op.drop_constraint("fk_ventas_created_by_empleados", "ventas", schema="ventas", type_="foreignkey")
    op.drop_constraint("fk_ventas_nodo_origen_id_nodos", "ventas", schema="ventas", type_="foreignkey")
    op.drop_constraint("fk_devoluciones_created_by_empleados", "devoluciones", schema="ventas", type_="foreignkey")
    op.drop_constraint("fk_devoluciones_nodo_origen_id_nodos", "devoluciones", schema="ventas", type_="foreignkey")
    op.drop_constraint("fk_ventas_items_created_by_empleados", "ventas_items", schema="ventas", type_="foreignkey")
    op.drop_constraint("fk_ventas_items_nodo_origen_id_nodos", "ventas_items", schema="ventas", type_="foreignkey")
    op.drop_constraint("fk_ventas_pagos_created_by_empleados", "ventas_pagos", schema="ventas", type_="foreignkey")
    op.drop_constraint("fk_ventas_pagos_nodo_origen_id_nodos", "ventas_pagos", schema="ventas", type_="foreignkey")
    op.drop_constraint(
        "fk_documentos_fiscales_created_by_empleados", "documentos_fiscales", schema="fiscal", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_documentos_fiscales_nodo_origen_id_nodos", "documentos_fiscales", schema="fiscal", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_devoluciones_items_created_by_empleados", "devoluciones_items", schema="ventas", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_devoluciones_items_nodo_origen_id_nodos", "devoluciones_items", schema="ventas", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_devoluciones_pagos_created_by_empleados", "devoluciones_pagos", schema="ventas", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_devoluciones_pagos_nodo_origen_id_nodos", "devoluciones_pagos", schema="ventas", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_documentos_fiscales_eventos_created_by_empleados",
        "documentos_fiscales_eventos",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_documentos_fiscales_eventos_nodo_origen_id_nodos",
        "documentos_fiscales_eventos",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_documentos_fiscales_impuestos_created_by_empleados",
        "documentos_fiscales_impuestos",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_documentos_fiscales_impuestos_nodo_origen_id_nodos",
        "documentos_fiscales_impuestos",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_documentos_fiscales_items_created_by_empleados",
        "documentos_fiscales_items",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_documentos_fiscales_items_nodo_origen_id_nodos",
        "documentos_fiscales_items",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_documentos_fiscales_pagos_created_by_empleados",
        "documentos_fiscales_pagos",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_documentos_fiscales_pagos_nodo_origen_id_nodos",
        "documentos_fiscales_pagos",
        schema="fiscal",
        type_="foreignkey",
    )
    op.drop_table("documentos_fiscales_pagos", schema="fiscal")
    op.drop_table("documentos_fiscales_items", schema="fiscal")
    op.drop_table("documentos_fiscales_impuestos", schema="fiscal")
    op.drop_index("ix_documentos_fiscales_eventos_documento", table_name="documentos_fiscales_eventos", schema="fiscal")
    op.drop_table("documentos_fiscales_eventos", schema="fiscal")
    op.drop_index("ix_devoluciones_pagos_devolucion_id", table_name="devoluciones_pagos", schema="ventas")
    op.drop_table("devoluciones_pagos", schema="ventas")
    op.drop_index("ix_devoluciones_items_venta_item", table_name="devoluciones_items", schema="ventas")
    op.drop_table("devoluciones_items", schema="ventas")
    op.drop_index(
        "uq_documentos_fiscales_venta_vigente",
        table_name="documentos_fiscales",
        schema="fiscal",
        postgresql_where=sa.text("vigente AND tipo_documento_codigo IN ('FE','POS_E')"),
    )
    op.drop_index(
        "uq_documentos_fiscales_resolucion",
        table_name="documentos_fiscales",
        schema="fiscal",
        postgresql_where=sa.text("consecutivo IS NOT NULL"),
    )
    op.drop_index(
        "uq_documentos_fiscales_proveedor",
        table_name="documentos_fiscales",
        schema="fiscal",
        postgresql_where=sa.text("proveedor_documento_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_documentos_fiscales_numero",
        table_name="documentos_fiscales",
        schema="fiscal",
        postgresql_where=sa.text("consecutivo IS NOT NULL"),
    )
    op.drop_index(
        "uq_documentos_fiscales_devolucion",
        table_name="documentos_fiscales",
        schema="fiscal",
        postgresql_where=sa.text("devolucion_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_documentos_fiscales_cufe",
        table_name="documentos_fiscales",
        schema="fiscal",
        postgresql_where=sa.text("cufe_cude IS NOT NULL"),
    )
    op.drop_index("ix_documentos_fiscales_sede", table_name="documentos_fiscales", schema="fiscal")
    op.drop_index(
        "ix_documentos_fiscales_referenciado",
        table_name="documentos_fiscales",
        schema="fiscal",
        postgresql_where=sa.text("documento_referenciado_id IS NOT NULL"),
    )
    op.drop_index("ix_documentos_fiscales_fecha", table_name="documentos_fiscales", schema="fiscal")
    op.drop_index(
        "ix_documentos_fiscales_contingencia",
        table_name="documentos_fiscales",
        schema="fiscal",
        postgresql_where=sa.text("es_contingencia AND estado <> 'aceptado'"),
    )
    op.drop_index(
        "ix_documentos_fiscales_cola",
        table_name="documentos_fiscales",
        schema="fiscal",
        postgresql_where=sa.text("estado IN ('pendiente_envio','contingencia','rechazado')"),
    )
    op.drop_index("ix_documentos_fiscales_adquirente", table_name="documentos_fiscales", schema="fiscal")
    op.drop_table("documentos_fiscales", schema="fiscal")
    op.drop_index("ix_ventas_pagos_venta_id", table_name="ventas_pagos", schema="ventas")
    op.drop_index("ix_ventas_pagos_medio_fecha", table_name="ventas_pagos", schema="ventas")
    op.drop_table("ventas_pagos", schema="ventas")
    op.drop_index("ix_ventas_items_producto", table_name="ventas_items", schema="ventas")
    op.drop_table("ventas_items", schema="ventas")
    op.drop_index("ix_devoluciones_venta_id", table_name="devoluciones", schema="ventas")
    op.drop_index(
        "ix_devoluciones_turno",
        table_name="devoluciones",
        schema="ventas",
        postgresql_where=sa.text("turno_id IS NOT NULL"),
    )
    op.drop_index(
        "ix_devoluciones_sede_fecha",
        table_name="devoluciones",
        schema="ventas",
        postgresql_where=sa.text("estado = 'confirmada'"),
    )
    op.drop_table("devoluciones", schema="ventas")
    op.drop_index(
        "uq_ventas_numero_interno",
        table_name="ventas",
        schema="ventas",
        postgresql_where=sa.text("numero_interno IS NOT NULL"),
    )
    op.drop_index(
        "ix_ventas_vendedor", table_name="ventas", schema="ventas", postgresql_where=sa.text("vendedor_id IS NOT NULL")
    )
    op.drop_index(
        "ix_ventas_turno", table_name="ventas", schema="ventas", postgresql_where=sa.text("turno_id IS NOT NULL")
    )
    op.drop_index("ix_ventas_tercero_fecha", table_name="ventas", schema="ventas")
    op.drop_index(
        "ix_ventas_sede_fecha", table_name="ventas", schema="ventas", postgresql_where=sa.text("estado = 'confirmada'")
    )
    op.drop_index(
        "ix_ventas_placa", table_name="ventas", schema="ventas", postgresql_where=sa.text("placa_vehiculo IS NOT NULL")
    )
    op.drop_index(
        "ix_ventas_borradores", table_name="ventas", schema="ventas", postgresql_where=sa.text("estado = 'borrador'")
    )
    op.drop_table("ventas", schema="ventas")
    op.drop_index("ix_movimientos_caja_turno", table_name="movimientos_caja", schema="cajas")
    op.drop_table("movimientos_caja", schema="cajas")
    op.drop_table("arqueos_turno", schema="cajas")
    op.drop_index(
        "uq_reservas_stock_linea",
        table_name="reservas_stock",
        schema="inventario",
        postgresql_where=sa.text("estado = 'activa'"),
    )
    op.drop_index(
        "ix_reservas_stock_vencimiento",
        table_name="reservas_stock",
        schema="inventario",
        postgresql_where=sa.text("estado = 'activa'"),
    )
    op.drop_index(
        "ix_reservas_stock_producto",
        table_name="reservas_stock",
        schema="inventario",
        postgresql_where=sa.text("estado = 'activa'"),
    )
    op.drop_index("ix_reservas_stock_origen", table_name="reservas_stock", schema="inventario")
    op.drop_table("reservas_stock", schema="inventario")
    op.drop_index(
        "uq_alertas_stock_abierta",
        table_name="alertas_stock",
        schema="inventario",
        postgresql_where=sa.text("estado <> 'resuelta'"),
    )
    op.drop_index(
        "ix_alertas_stock_estado",
        table_name="alertas_stock",
        schema="inventario",
        postgresql_where=sa.text("estado <> 'resuelta'"),
    )
    op.drop_table("alertas_stock", schema="inventario")
    op.drop_index(
        "uq_turnos_abierto_por_cajero",
        table_name="turnos",
        schema="cajas",
        postgresql_where=sa.text("estado = 'abierto'"),
    )
    op.drop_index(
        "uq_turnos_abierto_por_caja",
        table_name="turnos",
        schema="cajas",
        postgresql_where=sa.text("estado = 'abierto'"),
    )
    op.drop_index("ix_turnos_caja_fecha", table_name="turnos", schema="cajas")
    op.drop_table("turnos", schema="cajas")
    op.drop_index("ix_productos_ubicaciones_ubicacion_id", table_name="productos_ubicaciones", schema="inventario")
    op.drop_table("productos_ubicaciones", schema="inventario")
    op.drop_index("ix_movimientos_inventario_origen", table_name="movimientos_inventario", schema="inventario")
    op.drop_index("ix_movimientos_inventario_kardex", table_name="movimientos_inventario", schema="inventario")
    op.drop_table("movimientos_inventario", schema="inventario")
    op.drop_index("ix_existencias_producto_id", table_name="existencias", schema="inventario")
    op.drop_index(
        "ix_existencias_negativas",
        table_name="existencias",
        schema="inventario",
        postgresql_where=sa.text("cantidad < 0"),
    )
    op.drop_table("existencias", schema="inventario")
    op.drop_index(
        "uq_resoluciones_activa_sede",
        table_name="resoluciones_numeracion",
        schema="fiscal",
        postgresql_where=sa.text("estado = 'activa' AND caja_id IS NULL AND sede_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_resoluciones_activa_empresa",
        table_name="resoluciones_numeracion",
        schema="fiscal",
        postgresql_where=sa.text("estado = 'activa' AND sede_id IS NULL"),
    )
    op.drop_index(
        "uq_resoluciones_activa_caja",
        table_name="resoluciones_numeracion",
        schema="fiscal",
        postgresql_where=sa.text("estado = 'activa' AND caja_id IS NOT NULL"),
    )
    op.drop_index("ix_resoluciones_propietario", table_name="resoluciones_numeracion", schema="fiscal")
    op.drop_table("resoluciones_numeracion", schema="fiscal")
    op.drop_index(
        "ix_precios_vigente", table_name="precios", schema="catalogo", postgresql_where=sa.text("vigente_hasta IS NULL")
    )
    op.drop_table("precios", schema="catalogo")
    op.drop_index(
        "ix_perifericos_caja_activos", table_name="perifericos", schema="cajas", postgresql_where=sa.text("activo")
    )
    op.drop_table("perifericos", schema="cajas")
    op.drop_index(
        "uq_dispositivos_caja_activo",
        table_name="dispositivos",
        schema="cajas",
        postgresql_where=sa.text("estado = 'activo' AND tipo = 'pos'"),
    )
    op.drop_index("ix_dispositivos_sede", table_name="dispositivos", schema="cajas")
    op.drop_table("dispositivos", schema="cajas")
    op.drop_table("ubicaciones", schema="inventario")
    op.drop_index("ix_empleados_roles_rol_id", table_name="empleados_roles", schema="identidad")
    op.drop_table("empleados_roles", schema="identidad")
    op.drop_table("cajas", schema="cajas")
    op.drop_index("ix_log_acciones_ocurrido", table_name="log_acciones", schema="auditoria")
    op.drop_index("ix_log_acciones_entidad", table_name="log_acciones", schema="auditoria")
    op.drop_index("ix_log_acciones_actor", table_name="log_acciones", schema="auditoria")
    op.drop_table("log_acciones", schema="auditoria")
    op.drop_index(
        "ix_conflictos_sync_pendientes",
        table_name="conflictos_sync",
        schema="sync",
        postgresql_where=sa.text("resolucion = 'pendiente'"),
    )
    op.drop_index("ix_conflictos_sync_agregado", table_name="conflictos_sync", schema="sync")
    op.drop_table("conflictos_sync", schema="sync")
    op.drop_table("empresas_responsabilidades", schema="organizacion")
    op.drop_table("configuracion_sede", schema="organizacion")
    op.drop_table("bodegas", schema="inventario")
    op.drop_index("ix_empleados_sedes_sede_id", table_name="empleados_sedes", schema="identidad")
    op.drop_table("empleados_sedes", schema="identidad")
    op.drop_index("ix_autorizaciones_entidad", table_name="autorizaciones", schema="identidad")
    op.drop_index("ix_autorizaciones_autorizador", table_name="autorizaciones", schema="identidad")
    op.drop_table("autorizaciones", schema="identidad")
    op.drop_index(
        "uq_configuracion_proveedor_activo",
        table_name="configuracion_proveedor",
        schema="fiscal",
        postgresql_where=sa.text("activo"),
    )
    op.drop_table("configuracion_proveedor", schema="fiscal")
    op.drop_table("sedes", schema="organizacion")
    op.drop_table("empresas", schema="organizacion")
    op.drop_index(
        "uq_empleados_carne",
        table_name="empleados",
        schema="identidad",
        postgresql_where=sa.text("codigo_carne IS NOT NULL"),
    )
    op.drop_table("empleados", schema="identidad")
    op.drop_index(
        "ix_productos_compatibilidades_version_producto", table_name="productos_compatibilidades", schema="catalogo"
    )
    op.drop_table("productos_compatibilidades", schema="catalogo")
    op.drop_table("terceros_responsabilidades", schema="identidad")
    op.drop_index(
        "uq_direcciones_predeterminada",
        table_name="direcciones",
        schema="identidad",
        postgresql_where=sa.text("es_predeterminada AND activo"),
    )
    op.drop_index(op.f("ix_direcciones_tercero_id"), table_name="direcciones", schema="identidad")
    op.drop_table("direcciones", schema="identidad")
    op.drop_table("cuentas_clientes", schema="identidad")
    op.drop_index(
        "uq_vehiculos_versiones_codigo_externo",
        table_name="vehiculos_versiones",
        schema="catalogo",
        postgresql_where=sa.text("codigo_externo IS NOT NULL"),
    )
    op.drop_table("vehiculos_versiones", schema="catalogo")
    op.drop_table("terceros_listas_precios", schema="catalogo")
    op.drop_index(op.f("ix_productos_referencias_producto_id"), table_name="productos_referencias", schema="catalogo")
    op.drop_table("productos_referencias", schema="catalogo")
    op.drop_index(
        "uq_productos_imagenes_principal",
        table_name="productos_imagenes",
        schema="catalogo",
        postgresql_where=sa.text("es_principal AND activo"),
    )
    op.drop_index("ix_productos_imagenes_producto_orden", table_name="productos_imagenes", schema="catalogo")
    op.drop_table("productos_imagenes", schema="catalogo")
    op.drop_index(
        "uq_productos_codigos_barras_principal",
        table_name="productos_codigos_barras",
        schema="catalogo",
        postgresql_where=sa.text("es_principal AND activo"),
    )
    op.drop_index(
        "uq_productos_codigos_barras_codigo",
        table_name="productos_codigos_barras",
        schema="catalogo",
        postgresql_where=sa.text("activo"),
    )
    op.drop_index(
        op.f("ix_productos_codigos_barras_producto_id"), table_name="productos_codigos_barras", schema="catalogo"
    )
    op.drop_table("productos_codigos_barras", schema="catalogo")
    op.drop_index(
        "uq_terceros_documento",
        table_name="terceros",
        schema="identidad",
        postgresql_where=sa.text("fusionado_en_id IS NULL"),
    )
    op.drop_index(
        "ix_terceros_proveedores", table_name="terceros", schema="identidad", postgresql_where=sa.text("es_proveedor")
    )
    op.drop_table("terceros", schema="identidad")
    op.drop_index("ix_roles_permisos_permiso_codigo", table_name="roles_permisos", schema="identidad")
    op.drop_table("roles_permisos", schema="identidad")
    op.drop_index(
        "uq_vehiculos_modelos_codigo_externo",
        table_name="vehiculos_modelos",
        schema="catalogo",
        postgresql_where=sa.text("codigo_externo IS NOT NULL"),
    )
    op.drop_table("vehiculos_modelos", schema="catalogo")
    op.drop_index(
        "uq_productos_slug", table_name="productos", schema="catalogo", postgresql_where=sa.text("slug IS NOT NULL")
    )
    op.drop_index(
        "ix_productos_web",
        table_name="productos",
        schema="catalogo",
        postgresql_where=sa.text("publicado_web AND activo"),
    )
    op.drop_index(op.f("ix_productos_marca_id"), table_name="productos", schema="catalogo")
    op.drop_index(
        "ix_productos_categoria_activos", table_name="productos", schema="catalogo", postgresql_where=sa.text("activo")
    )
    op.drop_table("productos", schema="catalogo")
    op.drop_table("motivos_devolucion", schema="ventas")
    op.drop_index(
        "ix_outbox_eventos_cola",
        table_name="outbox_eventos",
        schema="sync",
        postgresql_where=sa.text("estado IN ('pendiente','fallido')"),
    )
    op.drop_index("ix_outbox_eventos_agregado", table_name="outbox_eventos", schema="sync")
    op.drop_table("outbox_eventos", schema="sync")
    op.drop_index(
        "ix_inbox_eventos_pendientes",
        table_name="inbox_eventos",
        schema="sync",
        postgresql_where=sa.text("estado IN ('recibido','en_espera','error')"),
    )
    op.drop_index("ix_inbox_eventos_agregado", table_name="inbox_eventos", schema="sync")
    op.drop_table("inbox_eventos", schema="sync")
    op.drop_table("cursores_sync", schema="sync")
    op.drop_index(op.f("ix_municipios_departamento_codigo"), table_name="municipios", schema="referencia")
    op.drop_table("municipios", schema="referencia")
    op.drop_table("conceptos_nota", schema="referencia")
    op.drop_table("roles", schema="identidad")
    op.drop_index(
        "uq_vehiculos_marcas_codigo_externo",
        table_name="vehiculos_marcas",
        schema="catalogo",
        postgresql_where=sa.text("codigo_externo IS NOT NULL"),
    )
    op.drop_table("vehiculos_marcas", schema="catalogo")
    op.drop_table("marcas", schema="catalogo")
    op.drop_table("listas_precios", schema="catalogo")
    op.drop_table("impuestos", schema="catalogo")
    op.drop_index(op.f("ix_categorias_parent_id"), table_name="categorias", schema="catalogo")
    op.drop_table("categorias", schema="catalogo")
    op.drop_table("motivos_movimiento_caja", schema="cajas")
    op.drop_table("unidades_medida", schema="referencia")
    op.drop_table("tributos", schema="referencia")
    op.drop_table("tipos_persona", schema="referencia")
    op.drop_table("tipos_documento_identidad", schema="referencia")
    op.drop_table("tipos_documento_fiscal", schema="referencia")
    op.drop_table("responsabilidades_fiscales", schema="referencia")
    op.drop_table("regimenes", schema="referencia")
    op.drop_table("medios_pago", schema="referencia")
    op.drop_table("formas_pago", schema="referencia")
    op.drop_table("departamentos", schema="referencia")
    op.drop_index(
        "uq_nodos_edge_activo_por_sede",
        table_name="nodos",
        schema="organizacion",
        postgresql_where=sa.text("tipo = 'edge' AND estado = 'activo'"),
    )
    op.drop_table("nodos", schema="organizacion")
    op.drop_table("permisos", schema="identidad")

    # --- tipos enumerados ---
    op.execute("DROP TYPE IF EXISTS auditoria.actor_tipo")
    op.execute("DROP TYPE IF EXISTS auditoria.resultado_accion")
    op.execute("DROP TYPE IF EXISTS cajas.estado_dispositivo")
    op.execute("DROP TYPE IF EXISTS cajas.estado_turno")
    op.execute("DROP TYPE IF EXISTS cajas.tipo_conexion")
    op.execute("DROP TYPE IF EXISTS cajas.tipo_dispositivo")
    op.execute("DROP TYPE IF EXISTS cajas.tipo_movimiento_caja")
    op.execute("DROP TYPE IF EXISTS cajas.tipo_periferico")
    op.execute("DROP TYPE IF EXISTS catalogo.combustible")
    op.execute("DROP TYPE IF EXISTS catalogo.tipo_codigo_barras")
    op.execute("DROP TYPE IF EXISTS catalogo.tipo_referencia")
    op.execute("DROP TYPE IF EXISTS catalogo.tratamiento_impuesto")
    op.execute("DROP TYPE IF EXISTS fiscal.ambiente_dian")
    op.execute("DROP TYPE IF EXISTS fiscal.estado_documento_fiscal")
    op.execute("DROP TYPE IF EXISTS fiscal.estado_resolucion")
    op.execute("DROP TYPE IF EXISTS fiscal.modo_numeracion")
    op.execute("DROP TYPE IF EXISTS fiscal.tipo_evento_fiscal")
    op.execute("DROP TYPE IF EXISTS identidad.estado_cuenta")
    op.execute("DROP TYPE IF EXISTS identidad.tipo_autorizacion")
    op.execute("DROP TYPE IF EXISTS identidad.tipo_direccion")
    op.execute("DROP TYPE IF EXISTS inventario.estado_alerta")
    op.execute("DROP TYPE IF EXISTS inventario.estado_reserva")
    op.execute("DROP TYPE IF EXISTS inventario.origen_movimiento")
    op.execute("DROP TYPE IF EXISTS inventario.tipo_alerta_stock")
    op.execute("DROP TYPE IF EXISTS inventario.tipo_movimiento")
    op.execute("DROP TYPE IF EXISTS organizacion.nodo_estado")
    op.execute("DROP TYPE IF EXISTS organizacion.nodo_tipo")
    op.execute("DROP TYPE IF EXISTS sync.direccion_sync")
    op.execute("DROP TYPE IF EXISTS sync.estado_inbox")
    op.execute("DROP TYPE IF EXISTS sync.estado_outbox")
    op.execute("DROP TYPE IF EXISTS sync.resolucion_conflicto")
    op.execute("DROP TYPE IF EXISTS sync.tipo_conflicto")
    op.execute("DROP TYPE IF EXISTS ventas.canal_pago")
    op.execute("DROP TYPE IF EXISTS ventas.canal_venta")
    op.execute("DROP TYPE IF EXISTS ventas.estado_devolucion")
    op.execute("DROP TYPE IF EXISTS ventas.estado_venta")
    op.execute("DROP TYPE IF EXISTS ventas.tipo_resolucion")
