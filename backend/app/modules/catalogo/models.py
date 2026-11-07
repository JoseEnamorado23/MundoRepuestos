"""Schema `catalogo`: productos, referencias, vehículos, compatibilidades, impuestos y precios (§6).

Columnas derivadas (`referencia_normalizada`, `anios`) las crea la migración 0003 (columnas generadas). La búsqueda
vive en `productos_busqueda` (migración 0005), mantenida por triggers sin tocar `productos.version`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INT4RANGE, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import CANTIDAD, PCT, PRECIO, Base, Mutable, pg_enum
from app.core.helpers import fk, fkt, flag, ts, txt

SCHEMA = "catalogo"
TratamientoImpuesto = pg_enum(SCHEMA, "tratamiento_impuesto", "gravado", "exento", "excluido")
TipoCodigoBarras = pg_enum(SCHEMA, "tipo_codigo_barras", "ean13", "ean8", "upc", "code128", "interno")
TipoReferencia = pg_enum(SCHEMA, "tipo_referencia", "oem", "original", "alterna", "equivalente")
Combustible = pg_enum(SCHEMA, "combustible", "gasolina", "diesel", "gas", "hibrido", "electrico", "flex")


class Categoria(Base, Mutable):
    __tablename__ = "categorias"
    __table_args__ = (UniqueConstraint("slug", name="uq_categorias_slug"), {"schema": SCHEMA})
    parent_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.categorias.id", null=True, index=True)
    nombre: Mapped[str] = txt()
    slug: Mapped[str] = txt()
    orden: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    activo: Mapped[bool] = flag(True)


class Marca(Base, Mutable):
    __tablename__ = "marcas"
    __table_args__ = (UniqueConstraint("slug", name="uq_marcas_slug"), {"schema": SCHEMA})
    nombre: Mapped[str] = txt()  # unicidad lower(nombre): migración 0003
    slug: Mapped[str] = txt()
    es_fabricante_oem: Mapped[bool] = flag(False)
    pais_origen: Mapped[str | None] = txt(null=True)
    logo_url: Mapped[str | None] = txt(null=True)
    activo: Mapped[bool] = flag(True)


class Impuesto(Base, Mutable):
    __tablename__ = "impuestos"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_impuestos_codigo"),
        CheckConstraint("tarifa_pct BETWEEN 0 AND 100", name="tarifa_rango"),
        CheckConstraint("tratamiento <> 'gravado' OR tarifa_pct > 0", name="gravado_tarifa"),
        CheckConstraint("tratamiento <> 'excluido' OR tarifa_pct = 0", name="excluido_tarifa"),
        {"schema": SCHEMA},
    )
    codigo: Mapped[str] = txt()
    nombre: Mapped[str] = txt()
    tributo_codigo: Mapped[str] = fkt("referencia.tributos.codigo")
    tratamiento: Mapped[str] = mapped_column(TratamientoImpuesto, nullable=False)
    tarifa_pct = mapped_column(PCT(), nullable=False)
    activo: Mapped[bool] = flag(True)


class Producto(Base, Mutable):
    __tablename__ = "productos"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_productos_sku"),
        CheckConstraint("NOT publicado_web OR activo", name="web_activo"),
        CheckConstraint("peso_kg IS NULL OR peso_kg >= 0", name="peso_no_negativo"),
        CheckConstraint("stock_seguridad_web IS NULL OR stock_seguridad_web >= 0", name="seguridad_no_negativa"),
        Index("uq_productos_slug", "slug", unique=True, postgresql_where=text("slug IS NOT NULL")),
        Index("ix_productos_categoria_activos", "categoria_id", postgresql_where=text("activo")),
        Index("ix_productos_web", "categoria_id", "nombre", postgresql_where=text("publicado_web AND activo")),
        {"schema": SCHEMA},
    )
    sku: Mapped[str] = txt()
    nombre: Mapped[str] = txt()
    descripcion: Mapped[str | None] = txt(null=True)
    marca_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.marcas.id", null=True, index=True)
    categoria_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.categorias.id")
    unidad_codigo: Mapped[str] = fkt("referencia.unidades_medida.codigo", server_default="94")
    impuesto_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.impuestos.id")
    es_inventariable: Mapped[bool] = flag(True)
    vendible_pos: Mapped[bool] = flag(True)
    publicado_web: Mapped[bool] = flag(False)
    slug: Mapped[str | None] = txt(null=True)
    peso_kg = mapped_column(Numeric(10, 3))
    alto_cm = mapped_column(Numeric(8, 2))
    ancho_cm = mapped_column(Numeric(8, 2))
    largo_cm = mapped_column(Numeric(8, 2))
    stock_minimo = mapped_column(CANTIDAD(), nullable=False, server_default="0")
    stock_seguridad_web = mapped_column(CANTIDAD())
    activo: Mapped[bool] = flag(True)


class ProductoBusqueda(Base):
    """Proyección de búsqueda (derivada, local: NO se sincroniza). La mantienen triggers; los índices GIN van en 0005."""

    __tablename__ = "productos_busqueda"
    __table_args__ = {"schema": SCHEMA}

    producto_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.productos.id", ondelete="CASCADE"), primary_key=True
    )
    documento: Mapped[str] = mapped_column(TSVECTOR, nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    actualizado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductoCodigoBarras(Base, Mutable):
    __tablename__ = "productos_codigos_barras"
    __table_args__ = (
        CheckConstraint("unidades_por_codigo > 0", name="unidades_positivas"),
        Index("uq_productos_codigos_barras_codigo", "codigo", unique=True, postgresql_where=text("activo")),
        Index(
            "uq_productos_codigos_barras_principal",
            "producto_id",
            unique=True,
            postgresql_where=text("es_principal AND activo"),
        ),
        {"schema": SCHEMA},
    )
    producto_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.productos.id", index=True)
    codigo: Mapped[str] = txt()
    tipo: Mapped[str] = mapped_column(TipoCodigoBarras, nullable=False, server_default="ean13")
    unidades_por_codigo = mapped_column(CANTIDAD(), nullable=False, server_default="1")
    es_principal: Mapped[bool] = flag(False)
    activo: Mapped[bool] = flag(True)


class ProductoReferencia(Base, Mutable):
    __tablename__ = "productos_referencias"
    __table_args__ = {"schema": SCHEMA}  # índices sobre referencia_normalizada: migración 0003
    producto_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.productos.id", index=True)
    tipo: Mapped[str] = mapped_column(TipoReferencia, nullable=False)
    referencia: Mapped[str] = txt()
    referencia_normalizada: Mapped[str] = mapped_column(Text, nullable=False, server_default=FetchedValue())
    marca_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.marcas.id", null=True)
    notas: Mapped[str | None] = txt(null=True)
    activo: Mapped[bool] = flag(True)


class VehiculoMarca(Base, Mutable):
    __tablename__ = "vehiculos_marcas"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_vehiculos_marcas_slug"),
        Index(
            "uq_vehiculos_marcas_codigo_externo",
            "codigo_externo",
            unique=True,
            postgresql_where=text("codigo_externo IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )
    nombre: Mapped[str] = txt()  # unicidad lower(nombre): migración 0003
    slug: Mapped[str] = txt()
    codigo_externo: Mapped[str | None] = txt(null=True)
    activo: Mapped[bool] = flag(True)


class VehiculoModelo(Base, Mutable):
    __tablename__ = "vehiculos_modelos"
    __table_args__ = (
        Index(
            "uq_vehiculos_modelos_codigo_externo",
            "codigo_externo",
            unique=True,
            postgresql_where=text("codigo_externo IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )
    marca_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.vehiculos_marcas.id")  # unicidad (marca, lower(nombre)): 0003
    nombre: Mapped[str] = txt()
    slug: Mapped[str] = txt()
    codigo_externo: Mapped[str | None] = txt(null=True)
    activo: Mapped[bool] = flag(True)


class VehiculoVersion(Base, Mutable):
    __tablename__ = "vehiculos_versiones"
    __table_args__ = (
        CheckConstraint("anio_hasta IS NULL OR anio_hasta >= anio_desde", name="anios_orden"),
        CheckConstraint("anio_desde BETWEEN 1950 AND 2100", name="anio_desde_rango"),
        CheckConstraint("cilindraje_cc IS NULL OR cilindraje_cc > 0", name="cilindraje_positivo"),
        Index(
            "uq_vehiculos_versiones_codigo_externo",
            "codigo_externo",
            unique=True,
            postgresql_where=text("codigo_externo IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )
    modelo_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.vehiculos_modelos.id")  # índice GiST (modelo_id, anios): 0003
    nombre: Mapped[str] = txt()
    anio_desde: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    anio_hasta: Mapped[int | None] = mapped_column(SmallInteger)
    motor: Mapped[str | None] = txt(null=True)
    cilindraje_cc: Mapped[int | None] = mapped_column(Integer)
    combustible: Mapped[str | None] = mapped_column(Combustible)
    transmision: Mapped[str | None] = txt(null=True)
    codigo_externo: Mapped[str | None] = txt(null=True)
    anios: Mapped[object] = mapped_column(INT4RANGE, nullable=False, server_default=FetchedValue())
    activo: Mapped[bool] = flag(True)


class ProductoCompatibilidad(Base, Mutable):
    __tablename__ = "productos_compatibilidades"
    __table_args__ = (
        UniqueConstraint("producto_id", "version_id", name="uq_productos_compatibilidades_producto_version"),
        Index("ix_productos_compatibilidades_version_producto", "version_id", "producto_id"),
        {"schema": SCHEMA},
    )
    producto_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.productos.id")
    version_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.vehiculos_versiones.id")
    posicion: Mapped[str | None] = txt(null=True)
    notas: Mapped[str | None] = txt(null=True)
    activo: Mapped[bool] = flag(True)


class ProductoImagen(Base, Mutable):
    __tablename__ = "productos_imagenes"
    __table_args__ = (
        Index("ix_productos_imagenes_producto_orden", "producto_id", "orden"),
        Index(
            "uq_productos_imagenes_principal",
            "producto_id",
            unique=True,
            postgresql_where=text("es_principal AND activo"),
        ),
        {"schema": SCHEMA},
    )
    producto_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.productos.id")
    url: Mapped[str] = txt()
    url_miniatura: Mapped[str | None] = txt(null=True)
    texto_alternativo: Mapped[str | None] = txt(null=True)
    orden: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    es_principal: Mapped[bool] = flag(False)
    activo: Mapped[bool] = flag(True)


class ListaPrecio(Base, Mutable):
    __tablename__ = "listas_precios"
    __table_args__ = (UniqueConstraint("codigo", name="uq_listas_precios_codigo"), {"schema": SCHEMA})
    codigo: Mapped[str] = txt()
    nombre: Mapped[str] = txt()
    precios_incluyen_impuesto: Mapped[bool] = flag(True)
    es_predeterminada: Mapped[bool] = flag(False)  # una sola: índice único sobre ((true)) en 0003
    activo: Mapped[bool] = flag(True)


class TerceroListaPrecio(Base):
    __tablename__ = "terceros_listas_precios"
    __table_args__ = {"schema": SCHEMA}
    tercero_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("identidad.terceros.id", ondelete="RESTRICT"), primary_key=True
    )
    lista_precio_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.listas_precios.id")


class Precio(Base, Mutable):
    __tablename__ = "precios"
    __table_args__ = (
        CheckConstraint("precio >= 0", name="precio_no_negativo"),
        CheckConstraint("vigente_hasta IS NULL OR vigente_hasta > vigente_desde", name="vigencia_orden"),
        # camino rápido del 99 % de las consultas: el precio actual (abierto)
        Index("ix_precios_vigente", "producto_id", "lista_precio_id", postgresql_where=text("vigente_hasta IS NULL")),
        {"schema": SCHEMA},  # EXCLUDE de vigencias solapadas: migración 0003
    )
    producto_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.productos.id")
    lista_precio_id: Mapped[uuid.UUID] = fk(f"{SCHEMA}.listas_precios.id")
    sede_id: Mapped[uuid.UUID | None] = fk("organizacion.sedes.id", null=True)
    precio = mapped_column(PRECIO(), nullable=False)
    vigente_desde: Mapped[datetime] = ts(null=False, server_default=text("now()"))
    vigente_hasta: Mapped[datetime | None] = ts()


class ContadorEan(Base):
    """Consecutivo de EAN-13 internos por nodo. LOCAL del nodo: no se sincroniza (cada nodo cuenta lo suyo).

    Se incrementa con `UPDATE ... RETURNING` dentro de la misma transacción que crea el código: sin huecos.
    """

    __tablename__ = "contadores_ean"
    __table_args__ = (
        CheckConstraint("ultimo >= 0", name="ultimo_no_negativo"),
        {"schema": SCHEMA, "comment": "LOCAL del nodo: no se sincroniza (consecutivo de EAN-13 internos)."},
    )
    nodo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizacion.nodos.id", ondelete="RESTRICT"), primary_key=True
    )
    ultimo: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")


class VehiculoAlias(Base, Mutable):
    """Nombre alterno de una marca o un modelo de vehículo ('chevy' -> Chevrolet, 'spark gt' -> Spark)."""

    __tablename__ = "vehiculos_alias"
    __table_args__ = (
        CheckConstraint("num_nonnulls(marca_id, modelo_id) = 1", name="un_destino"),
        Index("uq_vehiculos_alias_normalizado", "alias_normalizado", unique=True, postgresql_where=text("activo")),
        Index("ix_vehiculos_alias_marca_id", "marca_id"),
        Index("ix_vehiculos_alias_modelo_id", "modelo_id"),
        {"schema": SCHEMA},
    )
    alias: Mapped[str] = txt()
    alias_normalizado: Mapped[str] = txt()  # minúsculas, sin tildes, espacios simples (lo fija el servicio)
    marca_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.vehiculos_marcas.id", null=True)
    modelo_id: Mapped[uuid.UUID | None] = fk(f"{SCHEMA}.vehiculos_modelos.id", null=True)
    activo: Mapped[bool] = flag(True)
