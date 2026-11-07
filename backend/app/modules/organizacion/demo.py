"""Datos de demostración (idempotentes) para arrancar un equipo de desarrollo: `python -m app.cli datos-demo`.

Crea, solo si no existen: una empresa, la sede "Principal" con su nodo EDGE, una bodega, "Caja 1" con una resolución
de prueba (modo proveedor) y un cajero con PIN 123456 en esa sede. Bloqueado cuando ENV=produccion.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.base import uuid7
from app.core.config import get_settings
from app.core.errores import ReglaNegocio
from app.modules.auditoria.servicios import registrar_accion
from app.modules.cajas.models import Caja
from app.modules.fiscal.models import ResolucionNumeracion
from app.modules.identidad import empleados as svc_emp
from app.modules.identidad.models import Empleado, EmpleadoSede
from app.modules.inventario.models import Bodega
from app.modules.organizacion.models import Empresa, Nodo, Sede
from app.modules.organizacion.nodos import siguiente_codigo_ean

PIN_DEMO = "123456"
NIT_DEMO = "900000001"
DOC_CAJERO = "1000000001"
CARNE_CAJERO = "CAJERO1"


@dataclass
class ResultadoDemo:
    nodo_edge_id: uuid.UUID
    sede_id: uuid.UUID
    bodega_id: uuid.UUID
    caja_id: uuid.UUID
    cajero_id: uuid.UUID
    creados: list[str]


def sembrar(db: Session) -> ResultadoDemo:
    if get_settings().es_produccion:
        raise ReglaNegocio("datos-demo está bloqueado cuando ENV=produccion.", code="bloqueado_en_produccion")
    creados: list[str] = []
    # Etapa 1 (sin nube): el nodo EDGE es el dueño de escritura de los maestros (modelo.md §13.5). Los datos de demo
    # nacen con origen en el edge; su id se fija de antemano (las FK `nodo_origen_id` son diferidas).
    edge_existente = db.scalar(
        select(Nodo)
        .join(Sede, Sede.id == Nodo.sede_id)
        .join(Empresa, Empresa.id == Sede.empresa_id)
        .where(Empresa.nit == NIT_DEMO, Sede.codigo == "PRIN", Nodo.tipo == "edge", Nodo.estado == "activo")
    )
    origen = edge_existente.id if edge_existente else uuid7()

    empresa = db.scalar(select(Empresa).where(Empresa.nit == NIT_DEMO))
    if empresa is None:
        empresa = Empresa(
            nit=NIT_DEMO,
            dv=1,
            razon_social="Repuestos Demo S.A.S.",
            nombre_comercial="MundoRepuestos (demo)",
            tipo_persona_codigo="1",
            regimen_codigo="48",
            municipio_codigo="11001",
            direccion="Calle 1 # 2-3",
            nodo_origen_id=origen,
        )
        db.add(empresa)
        db.flush()
        creados.append("empresa")

    sede = db.scalar(select(Sede).where(Sede.empresa_id == empresa.id, Sede.codigo == "PRIN"))
    if sede is None:
        sede = Sede(
            empresa_id=empresa.id,
            codigo="PRIN",
            nombre="Principal",
            municipio_codigo="11001",
            direccion="Calle 1 # 2-3",
            nodo_origen_id=origen,
        )
        db.add(sede)
        db.flush()
        creados.append("sede")

    nodo = db.scalar(select(Nodo).where(Nodo.sede_id == sede.id, Nodo.tipo == "edge", Nodo.estado == "activo"))
    if nodo is None:
        nodo = Nodo(
            id=origen,
            tipo="edge",
            sede_id=sede.id,
            nombre="Edge Principal",
            codigo_ean=siguiente_codigo_ean(db),
            nodo_origen_id=origen,
        )
        db.add(nodo)
        db.flush()
        creados.append("nodo edge")

    bodega = db.scalar(select(Bodega).where(Bodega.sede_id == sede.id, Bodega.codigo == "B01"))
    if bodega is None:
        bodega = Bodega(sede_id=sede.id, codigo="B01", nombre="Bodega principal", nodo_origen_id=origen)
        db.add(bodega)
        db.flush()
        creados.append("bodega")

    caja = db.scalar(select(Caja).where(Caja.sede_id == sede.id, Caja.codigo == "C1"))
    if caja is None:
        caja = Caja(sede_id=sede.id, codigo="C1", nombre="Caja 1", bodega_id=bodega.id, nodo_origen_id=origen)
        db.add(caja)
        db.flush()
        creados.append("caja")

    resolucion = db.scalar(
        select(ResolucionNumeracion).where(
            ResolucionNumeracion.caja_id == caja.id, ResolucionNumeracion.tipo_documento_codigo == "POS_E"
        )
    )
    if resolucion is None:
        hoy = date.today()
        db.add(
            ResolucionNumeracion(
                empresa_id=empresa.id,
                sede_id=sede.id,
                caja_id=caja.id,
                modo_numeracion="proveedor",
                id_rango_proveedor="DEMO-1",
                tipo_documento_codigo="POS_E",
                numero_resolucion="DEMO-0000001",
                fecha_resolucion=hoy,
                prefijo="DEMO",
                rango_desde=1,
                rango_hasta=100000,
                consecutivo_actual=0,
                vigente_desde=hoy,
                vigente_hasta=hoy + timedelta(days=365),
                estado="activa",
                nodo_origen_id=origen,
            )
        )
        db.flush()
        creados.append("resolución de prueba (modo proveedor)")

    cajero = db.scalar(
        select(Empleado).where(Empleado.tipo_documento_codigo == "13", Empleado.numero_documento == DOC_CAJERO)
    )
    if cajero is None:
        cajero = svc_emp.crear(
            db,
            datos=dict(
                tipo_documento_codigo="13",
                numero_documento=DOC_CAJERO,
                nombres="Carlos",
                apellidos="Cajero Demo",
                codigo_carne=CARNE_CAJERO,
                nodo_origen_id=origen,
            ),
            password=None,
            roles=["cajero"],
            sedes=[sede.id],
            actor_id=None,
        )
        creados.append("cajero")
    asign = db.get(EmpleadoSede, (cajero.id, sede.id))
    if asign is None:
        svc_emp.asignar_sedes(db, cajero.id, [sede.id], sede.id, None)
        asign = db.get(EmpleadoSede, (cajero.id, sede.id))
    if asign.pin_hash is None:
        svc_emp.cambiar_pin(db, cajero.id, PIN_DEMO, sede.id, None)
        creados.append("PIN del cajero")

    if creados:
        registrar_accion(
            db, "organizacion.datos_demo", despues={"creados": creados}, entidad_tipo="sede", entidad_id=sede.id
        )
    return ResultadoDemo(nodo.id, sede.id, bodega.id, caja.id, cajero.id, creados)
