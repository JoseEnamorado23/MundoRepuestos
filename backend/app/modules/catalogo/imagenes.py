"""Imágenes de producto: validación de tipo/tamaño, almacenamiento y orden."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.base import uuid7
from app.core.config import get_settings
from app.core.errores import NoEncontrado, ReglaNegocio
from app.modules.catalogo.almacenamiento import Almacenamiento
from app.modules.catalogo.models import Producto, ProductoImagen
from app.modules.catalogo.servicios import _evento

# firma (magic bytes) -> (content-type, extensión). No se confía en el nombre ni en el Content-Type del cliente.
_TIPOS = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)


def detectar_tipo(datos: bytes) -> tuple[str, str]:
    for firma, ct, ext in _TIPOS:
        if datos.startswith(firma):
            return ct, ext
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise ReglaNegocio("Formato de imagen no permitido (use JPEG, PNG o WebP).", code="imagen_tipo_invalido")


def agregar_imagen(
    db: Session,
    almacen: Almacenamiento,
    actor_id: uuid.UUID,
    producto_id: uuid.UUID,
    datos: bytes,
    texto_alternativo: str | None,
) -> ProductoImagen:
    if db.get(Producto, producto_id) is None:
        raise NoEncontrado("Producto no encontrado.")
    maximo = get_settings().imagen_max_mb * 1024 * 1024
    if not datos:
        raise ReglaNegocio("El archivo está vacío.", code="imagen_vacia")
    if len(datos) > maximo:
        raise ReglaNegocio(
            f"La imagen supera el máximo de {get_settings().imagen_max_mb} MB.", code="imagen_muy_grande"
        )
    content_type, ext = detectar_tipo(datos)
    clave = f"productos/{producto_id}/{uuid7()}.{ext}"
    almacen.guardar(clave, datos, content_type)
    existentes = list(
        db.scalars(
            select(ProductoImagen).where(ProductoImagen.producto_id == producto_id, ProductoImagen.activo.is_(True))
        )
    )
    img = ProductoImagen(
        producto_id=producto_id,
        url=almacen.url(clave),
        texto_alternativo=texto_alternativo,
        orden=len(existentes),
        es_principal=not existentes,
        created_by=actor_id,
    )
    db.add(img)
    db.flush()
    _evento(db, "imagen", img, "agregada")
    return img


def listar_imagenes(db: Session, producto_id: uuid.UUID) -> list[ProductoImagen]:
    return list(
        db.scalars(
            select(ProductoImagen)
            .where(ProductoImagen.producto_id == producto_id, ProductoImagen.activo.is_(True))
            .order_by(ProductoImagen.orden, ProductoImagen.created_at)
        )
    )


def ordenar_imagenes(
    db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[ProductoImagen]:
    """`ids` define el nuevo orden (debe contener exactamente las imágenes activas). La primera pasa a ser la principal."""
    actuales = {i.id: i for i in listar_imagenes(db, producto_id)}
    if set(ids) != set(actuales) or len(ids) != len(actuales):
        raise ReglaNegocio(
            "La lista debe contener exactamente las imágenes activas del producto.", code="orden_invalido"
        )
    for i in actuales.values():
        i.es_principal = False
    db.flush()  # libera el índice único de la principal antes de reasignarla
    for pos, iid in enumerate(ids):
        actuales[iid].orden = pos
        actuales[iid].es_principal = pos == 0
    db.flush()
    for i in actuales.values():
        _evento(db, "imagen", i, "ordenada")
    return [actuales[i] for i in ids]


def quitar_imagen(db: Session, actor_id: uuid.UUID, producto_id: uuid.UUID, imagen_id: uuid.UUID) -> None:
    img = db.get(ProductoImagen, imagen_id)
    if img is None or img.producto_id != producto_id or not img.activo:
        raise NoEncontrado("Imagen no encontrada.")
    img.activo, img.es_principal = False, False
    db.flush()
    resto = listar_imagenes(db, producto_id)
    if resto:
        resto[0].es_principal = True
        db.flush()
    _evento(db, "imagen", img, "retirada")
