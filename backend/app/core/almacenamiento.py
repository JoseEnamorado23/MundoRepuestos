"""Almacenamiento de archivos (imágenes, PDF fiscales) detrás de una interfaz: hoy disco local; en la etapa 2, S3."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import RAIZ_REPO, get_settings
from app.core.errores import NoEncontrado


class Almacenamiento(ABC):
    @abstractmethod
    def guardar(self, clave: str, datos: bytes, content_type: str) -> None: ...

    @abstractmethod
    def leer(self, clave: str) -> bytes: ...

    @abstractmethod
    def borrar(self, clave: str) -> None: ...

    @abstractmethod
    def url(self, clave: str) -> str:
        """URL pública/relativa con la que el cliente obtiene el archivo."""


class AlmacenamientoLocal(Almacenamiento):
    """Guarda bajo MEDIA_DIR (relativo a la raíz del repo si no es absoluto). Protege contra path traversal."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz.resolve()

    def _ruta(self, clave: str) -> Path:
        ruta = (self.raiz / clave).resolve()
        if self.raiz not in ruta.parents:
            raise NoEncontrado("Archivo no encontrado.")
        return ruta

    def guardar(self, clave: str, datos: bytes, content_type: str) -> None:
        ruta = self._ruta(clave)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)

    def leer(self, clave: str) -> bytes:
        ruta = self._ruta(clave)
        if not ruta.is_file():
            raise NoEncontrado("Archivo no encontrado.")
        return ruta.read_bytes()

    def borrar(self, clave: str) -> None:
        ruta = self._ruta(clave)
        if ruta.is_file():
            ruta.unlink()

    def url(self, clave: str) -> str:
        return f"/api/v1/catalogo/archivos/{clave}"


def get_almacenamiento() -> Almacenamiento:
    media = Path(get_settings().media_dir)
    return AlmacenamientoLocal(media if media.is_absolute() else RAIZ_REPO / media)
