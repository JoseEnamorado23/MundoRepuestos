"""Esquemas de entrada/salida del catálogo."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.paginacion import Pagina

TipoCodigo = Literal["ean13", "ean8", "upc", "code128", "interno"]
TipoRef = Literal["oem", "original", "alterna", "equivalente"]
Combustible = Literal["gasolina", "diesel", "gas", "hibrido", "electrico", "flex"]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -------------------------------------------------------------------------------- categorías
class CategoriaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    orden: int = Field(0, ge=0, le=32000)


class CategoriaPatch(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    orden: int | None = Field(None, ge=0, le=32000)
    activo: bool | None = None


class CategoriaOut(_Out):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    nombre: str
    slug: str
    orden: int
    activo: bool
    version: int


class CategoriaNodo(BaseModel):
    id: uuid.UUID
    nombre: str
    slug: str
    orden: int
    activo: bool
    hijos: list[CategoriaNodo] = []


# -------------------------------------------------------------------------------- marcas
class MarcaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    es_fabricante_oem: bool = False
    pais_origen: str | None = None
    logo_url: str | None = None


class MarcaPatch(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=120)
    es_fabricante_oem: bool | None = None
    pais_origen: str | None = None
    logo_url: str | None = None
    activo: bool | None = None


class MarcaOut(_Out):
    id: uuid.UUID
    nombre: str
    slug: str
    es_fabricante_oem: bool
    pais_origen: str | None
    activo: bool
    version: int


# -------------------------------------------------------------------------------- vehículos
class VehiculoMarcaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    codigo_externo: str | None = None


class VehiculoMarcaPatch(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=120)
    codigo_externo: str | None = None
    activo: bool | None = None


class VehiculoMarcaOut(_Out):
    id: uuid.UUID
    nombre: str
    slug: str
    codigo_externo: str | None
    activo: bool


class VehiculoModeloIn(BaseModel):
    marca_id: uuid.UUID
    nombre: str = Field(min_length=1, max_length=120)
    codigo_externo: str | None = None


class VehiculoModeloPatch(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=120)
    codigo_externo: str | None = None
    activo: bool | None = None


class VehiculoModeloOut(_Out):
    id: uuid.UUID
    marca_id: uuid.UUID
    nombre: str
    slug: str
    activo: bool


class VehiculoVersionIn(BaseModel):
    modelo_id: uuid.UUID
    nombre: str = Field(min_length=1, max_length=160)
    anio_desde: int = Field(ge=1950, le=2100)
    anio_hasta: int | None = Field(None, ge=1950, le=2100)
    motor: str | None = None
    cilindraje_cc: int | None = Field(None, gt=0)
    combustible: Combustible | None = None
    transmision: str | None = None
    codigo_externo: str | None = None


class VehiculoVersionPatch(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=160)
    anio_desde: int | None = Field(None, ge=1950, le=2100)
    anio_hasta: int | None = Field(None, ge=1950, le=2100)
    motor: str | None = None
    cilindraje_cc: int | None = Field(None, gt=0)
    combustible: Combustible | None = None
    transmision: str | None = None
    activo: bool | None = None


class VehiculoVersionOut(_Out):
    id: uuid.UUID
    modelo_id: uuid.UUID
    nombre: str
    anio_desde: int
    anio_hasta: int | None
    motor: str | None
    cilindraje_cc: int | None
    combustible: str | None
    activo: bool


class VehiculoAliasIn(BaseModel):
    alias: str = Field(min_length=2, max_length=80, description="Ej.: 'chevy', 'spark gt', 'spark life'")
    marca_id: uuid.UUID | None = None
    modelo_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _un_destino(self):
        if (self.marca_id is None) == (self.modelo_id is None):
            raise ValueError("Indique exactamente uno: marca_id o modelo_id.")
        return self


class VehiculoAliasPatch(BaseModel):
    alias: str | None = Field(None, min_length=2, max_length=80)
    activo: bool | None = None


class VehiculoAliasOut(_Out):
    id: uuid.UUID
    alias: str
    alias_normalizado: str
    marca_id: uuid.UUID | None
    modelo_id: uuid.UUID | None
    activo: bool


class AniosModeloOut(BaseModel):
    modelo_id: uuid.UUID
    anios: list[int]


class ImpuestoOut(_Out):
    id: uuid.UUID
    codigo: str
    nombre: str
    tributo_codigo: str
    tratamiento: str
    tarifa_pct: Decimal
    activo: bool


# -------------------------------------------------------------------------------- productos
class CodigoBarrasIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=48)
    tipo: TipoCodigo = "ean13"
    unidades_por_codigo: Decimal = Field(Decimal(1), gt=0)
    es_principal: bool | None = None


class CodigoBarrasOut(_Out):
    id: uuid.UUID
    codigo: str
    tipo: str
    unidades_por_codigo: Decimal
    es_principal: bool
    activo: bool


class ReferenciaIn(BaseModel):
    tipo: TipoRef
    referencia: str = Field(min_length=1, max_length=80)
    marca_id: uuid.UUID | None = None
    notas: str | None = None


class ReferenciaOut(_Out):
    id: uuid.UUID
    tipo: str
    referencia: str
    referencia_normalizada: str
    marca_id: uuid.UUID | None
    notas: str | None
    activo: bool


class ProductoIn(BaseModel):
    sku: str = Field(min_length=1, max_length=60)
    nombre: str = Field(min_length=1, max_length=200)
    categoria_id: uuid.UUID
    impuesto_id: uuid.UUID
    descripcion: str | None = None
    marca_id: uuid.UUID | None = None
    unidad_codigo: str = "94"
    es_inventariable: bool = True
    vendible_pos: bool = True
    publicado_web: bool = False
    slug: str | None = None
    peso_kg: Decimal | None = Field(None, ge=0)
    alto_cm: Decimal | None = Field(None, ge=0)
    ancho_cm: Decimal | None = Field(None, ge=0)
    largo_cm: Decimal | None = Field(None, ge=0)
    stock_minimo: Decimal = Field(Decimal(0), ge=0)
    stock_seguridad_web: Decimal | None = Field(None, ge=0)
    codigos_barras: list[CodigoBarrasIn] = []
    referencias: list[ReferenciaIn] = []


class ProductoPatch(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=200)
    descripcion: str | None = None
    marca_id: uuid.UUID | None = None
    categoria_id: uuid.UUID | None = None
    unidad_codigo: str | None = None
    impuesto_id: uuid.UUID | None = None
    es_inventariable: bool | None = None
    vendible_pos: bool | None = None
    publicado_web: bool | None = None
    slug: str | None = None
    peso_kg: Decimal | None = Field(None, ge=0)
    alto_cm: Decimal | None = Field(None, ge=0)
    ancho_cm: Decimal | None = Field(None, ge=0)
    largo_cm: Decimal | None = Field(None, ge=0)
    stock_minimo: Decimal | None = Field(None, ge=0)
    stock_seguridad_web: Decimal | None = Field(None, ge=0)


class ProductoOut(_Out):
    id: uuid.UUID
    sku: str
    nombre: str
    descripcion: str | None
    marca_id: uuid.UUID | None
    categoria_id: uuid.UUID
    unidad_codigo: str
    impuesto_id: uuid.UUID
    es_inventariable: bool
    vendible_pos: bool
    publicado_web: bool
    stock_minimo: Decimal
    activo: bool
    version: int
    created_at: datetime


class ProductoDetalleOut(ProductoOut):
    codigos_barras: list[CodigoBarrasOut] = []
    referencias: list[ReferenciaOut] = []


class GenerarCodigosIn(BaseModel):
    producto_ids: list[uuid.UUID] | None = Field(
        None, description="Si se omite: todos los productos activos sin código (hasta `limite`)"
    )
    limite: int = Field(500, ge=1, le=5000)


class CodigoGeneradoOut(BaseModel):
    producto_id: uuid.UUID
    sku: str
    codigo: str


# -------------------------------------------------------------------------------- compatibilidades
class CompatibilidadIn(BaseModel):
    version_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    posicion: str | None = None
    notas: str | None = None


class CompatibilidadOut(_Out):
    producto_id: uuid.UUID
    version_id: uuid.UUID
    posicion: str | None
    notas: str | None
    activo: bool


# -------------------------------------------------------------------------------- precios
class PrecioIn(BaseModel):
    precio: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    lista_precio_id: uuid.UUID | None = None
    sede_id: uuid.UUID | None = None
    motivo: str | None = Field(None, max_length=300)


class PrecioOut(_Out):
    id: uuid.UUID
    producto_id: uuid.UUID
    lista_precio_id: uuid.UUID
    sede_id: uuid.UUID | None
    precio: Decimal
    vigente_desde: datetime
    vigente_hasta: datetime | None


# -------------------------------------------------------------------------------- imágenes
class ImagenOut(_Out):
    id: uuid.UUID
    producto_id: uuid.UUID
    url: str
    texto_alternativo: str | None
    orden: int
    es_principal: bool


class OrdenImagenesIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1)


# -------------------------------------------------------------------------------- búsqueda / escáner
class ProductoBuscadoOut(BaseModel):
    id: uuid.UUID
    sku: str
    nombre: str
    marca_id: uuid.UUID | None
    marca: str | None
    categoria_id: uuid.UUID
    categoria: str | None
    codigo_barras: str | None
    precio: Decimal | None = Field(description="Precio vigente (lista predeterminada y sede; IVA incluido)")
    stock_disponible: Decimal
    stock_minimo: Decimal
    relevancia: float
    ubicacion: str | None = Field(None, description="Código de la ubicación principal en la sede (estante/pasillo)")


class PaginaProductos(Pagina[ProductoBuscadoOut]):
    """Página de resultados de búsqueda. `busqueda_aproximada_incompleta`: la búsqueda por errores de digitación
    agotó su tiempo máximo y se devuelve vacía en lugar de un error."""

    busqueda_aproximada_incompleta: bool = False


class ProductoEscaneadoOut(BaseModel):
    id: uuid.UUID
    sku: str
    nombre: str
    marca_id: uuid.UUID | None
    categoria_id: uuid.UUID
    activo: bool
    vendible_pos: bool
    codigo_barras: str | None
    unidades_por_codigo: Decimal
    impuesto_id: uuid.UUID
    impuesto_codigo: str
    tarifa_pct: Decimal
    tratamiento: str
    precio: Decimal | None
    stock_disponible: Decimal
    ubicacion: str | None = Field(None, description="Código de la ubicación principal en la sede")


CategoriaNodo.model_rebuild()
