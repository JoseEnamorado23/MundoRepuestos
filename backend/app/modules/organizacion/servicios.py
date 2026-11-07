"""Alta de la estructura de una instalación: empresa, sede y nodo EDGE (`python -m app.cli inicializar`).

Usa los mismos mecanismos que la API: cada alta publica su evento en el outbox y deja su auditoría. Idempotente:
si la empresa (NIT), la sede (código) o el nodo edge activo de la sede ya existen, los reutiliza.
Los datos nacen con origen en el nodo EDGE (etapa 1, sin nube); su id se fija de antemano porque las FK
`nodo_origen_id` son diferidas.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.base import uuid7
from app.core.config import get_settings
from app.core.errores import ReglaNegocio
from app.core.utiles import snapshot
from app.modules.auditoria.servicios import registrar_accion
from app.modules.organizacion import configuracion as cfg_sede
from app.modules.organizacion.models import Empresa, Nodo, Sede
from app.modules.organizacion.nodos import siguiente_codigo_ean
from app.modules.sync.servicios import publicar_evento


def calcular_dv(nit: str) -> int:
    """Dígito de verificación del NIT (módulo 11, pesos DIAN)."""
    pesos = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)
    suma = sum(int(d) * p for d, p in zip(reversed(nit), pesos, strict=False))
    r = suma % 11
    return r if r < 2 else 11 - r


@contextmanager
def nodo_como(nodo_id: uuid.UUID) -> Iterator[None]:
    """Fija temporalmente el nodo actual (NODO_ID) para que modelos y eventos usen ese origen."""
    cfg = get_settings()
    previo = cfg.nodo_id
    cfg.nodo_id = nodo_id
    try:
        yield
    finally:
        cfg.nodo_id = previo


def _evento(db: Session, agregado: str, obj, tipo: str) -> None:
    publicar_evento(db, agregado, obj.id, f"{agregado}.{tipo}", snapshot(obj), version=getattr(obj, "version", 1))


@dataclass
class ResultadoInicializar:
    nodo_edge_id: uuid.UUID
    sede_id: uuid.UUID
    empresa_id: uuid.UUID
    creados: list[str] = field(default_factory=list)


def inicializar(
    db: Session,
    *,
    nit: str,
    razon_social: str,
    sede_codigo: str,
    sede_nombre: str,
    dv: int | None = None,
    nombre_comercial: str | None = None,
    tipo_persona_codigo: str = "1",
    regimen_codigo: str = "48",
    municipio_codigo: str = "11001",
    direccion: str = "Sin dirección",
    nodo_nombre: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> ResultadoInicializar:
    nit = nit.strip()
    if not (nit.isdigit() and 6 <= len(nit) <= 12):
        raise ReglaNegocio("El NIT debe tener entre 6 y 12 dígitos, sin dígito de verificación.", code="nit_invalido")
    dv_calculado = calcular_dv(nit)
    if dv is not None and dv != dv_calculado:
        raise ReglaNegocio(f"El DV del NIT {nit} es {dv_calculado}, no {dv}.", code="dv_invalido")
    creados: list[str] = []
    pendientes: list[tuple] = []  # eventos: el outbox exige que el nodo origen ya exista

    sede_existente = db.scalar(
        select(Sede).join(Empresa, Empresa.id == Sede.empresa_id).where(Empresa.nit == nit, Sede.codigo == sede_codigo)
    )
    edge = None
    if sede_existente is not None:
        edge = db.scalar(
            select(Nodo).where(Nodo.sede_id == sede_existente.id, Nodo.tipo == "edge", Nodo.estado == "activo")
        )
    origen = edge.id if edge is not None else uuid7()
    with nodo_como(origen):
        empresa = db.scalar(select(Empresa).where(Empresa.nit == nit))
        if empresa is None:
            empresa = Empresa(
                nit=nit,
                dv=dv_calculado,
                razon_social=razon_social,
                nombre_comercial=nombre_comercial,
                tipo_persona_codigo=tipo_persona_codigo,
                regimen_codigo=regimen_codigo,
                municipio_codigo=municipio_codigo,
                direccion=direccion,
                nodo_origen_id=origen,
                created_by=actor_id,
            )
            db.add(empresa)
            db.flush()
            pendientes.append(("empresa", empresa, "creada"))
            creados.append("empresa")

        sede = db.scalar(select(Sede).where(Sede.empresa_id == empresa.id, Sede.codigo == sede_codigo))
        if sede is None:
            sede = Sede(
                empresa_id=empresa.id,
                codigo=sede_codigo,
                nombre=sede_nombre,
                municipio_codigo=municipio_codigo,
                direccion=direccion,
                nodo_origen_id=origen,
                created_by=actor_id,
            )
            db.add(sede)
            db.flush()
            pendientes.append(("sede", sede, "creada"))
            creados.append("sede")

        nodo = edge or db.scalar(
            select(Nodo).where(Nodo.sede_id == sede.id, Nodo.tipo == "edge", Nodo.estado == "activo")
        )
        if nodo is None:
            nodo = Nodo(
                id=origen,
                tipo="edge",
                sede_id=sede.id,
                nombre=nodo_nombre or f"Edge {sede.nombre}",
                codigo_ean=siguiente_codigo_ean(db),
                nodo_origen_id=origen,
                created_by=actor_id,
            )
            db.add(nodo)
            db.flush()
            pendientes.append(("nodo", nodo, "creado"))
            creados.append("nodo edge")

        for agregado, obj, tipo in pendientes:
            _evento(db, agregado, obj, tipo)
        claves = cfg_sede.sembrar_configuracion(db, sede.id, actor_id)
        if claves:
            publicar_evento(
                db,
                "configuracion_sede",
                sede.id,
                "configuracion_sede.sembrada",
                {"sede_id": sede.id, "claves": claves},
            )
            creados.append(f"configuración de la sede ({len(claves)} claves)")

        if creados:
            registrar_accion(
                db,
                "organizacion.inicializar",
                actor_id=actor_id,
                sede_id=sede.id,
                entidad_tipo="sede",
                entidad_id=sede.id,
                despues={"creados": creados, "nit": nit, "sede": sede_codigo, "nodo_id": str(nodo.id)},
            )
    return ResultadoInicializar(nodo.id, sede.id, empresa.id, creados)
