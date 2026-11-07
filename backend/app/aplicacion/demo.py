"""Datos de demostración (idempotentes) para arrancar un equipo de desarrollo: `python -m app.cli datos-demo [--catalogo]`.

Reutiliza `inicializar` (empresa, sede y nodo EDGE con su configuración) y agrega, solo si no existen: bodega principal,
bodega de averías, "Caja 1" con resoluciones de prueba FE y NC (modo proveedor), tres empleados (propietario, cajero y
vendedor, con PIN) y cinco clientes. Con `--catalogo` carga además ~300 repuestos (ver `catalogo_demo`). Todo pasa por
los mismos servicios que la API (eventos del outbox y auditoría). Bloqueado cuando ENV=produccion.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aplicacion import catalogo_demo
from app.core.config import get_settings
from app.core.errores import ReglaNegocio
from app.modules.auditoria.servicios import registrar_accion
from app.modules.cajas import servicios as svc_cajas
from app.modules.cajas.models import Caja
from app.modules.fiscal import servicios as svc_fiscal
from app.modules.fiscal.models import ResolucionNumeracion
from app.modules.identidad import empleados as svc_emp
from app.modules.identidad.models import Empleado, EmpleadoSede
from app.modules.inventario import servicios as svc_inv
from app.modules.inventario.models import Bodega
from app.modules.organizacion.servicios import inicializar, nodo_como
from app.modules.ventas import servicios as svc_ventas
from app.modules.ventas.schemas import TerceroRapidoIn

NIT_DEMO = "900000001"
PIN_DEMO = "123456"  # el del cajero (compatibilidad con la versión anterior)


@dataclass(frozen=True)
class EmpleadoDemo:
    clave: str
    documento: str
    nombres: str
    apellidos: str
    carne: str
    pin: str
    rol: str
    usuario: str | None = None
    password: str | None = None


EMPLEADOS_DEMO = (
    EmpleadoDemo(
        "propietario", "1000000003", "Patricia", "Propietaria Demo", "PROP1", "246810", "propietario",
        usuario="propietario", password="Demo-Propietario-2026",
    ),
    EmpleadoDemo("cajero", "1000000001", "Carlos", "Cajero Demo", "CAJERO1", "123456", "cajero"),
    EmpleadoDemo("vendedor", "1000000002", "Valentina", "Vendedora Demo", "VENDEDOR1", "654321", "vendedor"),
)  # fmt: skip

CLIENTES_DEMO = (
    dict(tipo_documento_codigo="31", numero_documento="901234567", razon_social="Taller Automotriz El Pistón S.A.S.",
         email_facturacion="compras@elpiston.example.com", telefono="3101234567", municipio_codigo="11001"),
    dict(tipo_documento_codigo="31", numero_documento="800123456", razon_social="Transportes Andinos Ltda.",
         email_facturacion="flota@andinos.example.com", telefono="6012345678", municipio_codigo="11001"),
    dict(tipo_documento_codigo="13", numero_documento="79123456", primer_nombre="Jorge", primer_apellido="Rodríguez",
         segundo_apellido="Pardo", telefono="3115550101", municipio_codigo="11001"),
    dict(tipo_documento_codigo="13", numero_documento="52123456", primer_nombre="María", segundo_nombre="Fernanda",
         primer_apellido="Gómez", email_facturacion="mfgomez@example.com", municipio_codigo="11001"),
    dict(tipo_documento_codigo="13", numero_documento="1020304050", primer_nombre="Andrés", primer_apellido="Castillo",
         telefono="3205550202", municipio_codigo="11001"),
)  # fmt: skip


@dataclass
class ResultadoDemo:
    nodo_edge_id: uuid.UUID
    sede_id: uuid.UUID
    bodega_id: uuid.UUID
    bodega_averias_id: uuid.UUID
    caja_id: uuid.UUID
    cajero_id: uuid.UUID
    propietario_id: uuid.UUID
    vendedor_id: uuid.UUID
    creados: list[str]
    catalogo: catalogo_demo.ResumenCatalogo | None = None


def _empleado(db: Session, e: EmpleadoDemo, sede_id: uuid.UUID, creados: list[str]) -> Empleado:
    emp = db.scalar(
        select(Empleado).where(Empleado.tipo_documento_codigo == "13", Empleado.numero_documento == e.documento)
    )
    if emp is None:
        datos = dict(
            tipo_documento_codigo="13", numero_documento=e.documento, nombres=e.nombres, apellidos=e.apellidos,
            codigo_carne=e.carne,
        )  # fmt: skip
        if e.usuario:
            datos["usuario"] = e.usuario
        emp = svc_emp.crear(db, datos=datos, password=e.password, roles=[e.rol], sedes=[sede_id], actor_id=None)
        creados.append(e.clave)
    asign = db.get(EmpleadoSede, (emp.id, sede_id))
    if asign is None:
        svc_emp.asignar_sedes(db, emp.id, [sede_id], sede_id, None)
        asign = db.get(EmpleadoSede, (emp.id, sede_id))
    if asign.pin_hash is None:
        svc_emp.cambiar_pin(db, emp.id, e.pin, sede_id, None)
        creados.append(f"PIN del {e.clave}")
    return emp


def sembrar(db: Session, *, catalogo: bool = False) -> ResultadoDemo:
    if get_settings().es_produccion:
        raise ReglaNegocio("datos-demo está bloqueado cuando ENV=produccion.", code="bloqueado_en_produccion")
    base = inicializar(
        db,
        nit=NIT_DEMO,
        razon_social="Repuestos Demo S.A.S.",
        nombre_comercial="MundoRepuestos (demo)",
        sede_codigo="PRIN",
        sede_nombre="Principal",
        direccion="Calle 1 # 2-3",
        nodo_nombre="Edge Principal",
    )
    creados = list(base.creados)
    resumen = None
    with nodo_como(base.nodo_edge_id):
        sede_id = base.sede_id

        bodega = db.scalar(select(Bodega).where(Bodega.sede_id == sede_id, Bodega.codigo == "B01"))
        if bodega is None:
            bodega = svc_inv.crear_bodega(db, None, dict(sede_id=sede_id, codigo="B01", nombre="Bodega principal"))
            creados.append("bodega")
        averias = db.scalar(select(Bodega).where(Bodega.sede_id == sede_id, Bodega.codigo == "AV01"))
        if averias is None:
            averias = svc_inv.crear_bodega(
                db, None, dict(sede_id=sede_id, codigo="AV01", nombre="Bodega de averías", tipo="averias")
            )
            creados.append("bodega de averías")

        caja = db.scalar(select(Caja).where(Caja.sede_id == sede_id, Caja.codigo == "C1"))
        if caja is None:
            caja = svc_cajas.crear_caja(db, sede_id, "C1", "Caja 1", bodega.id, actor_id=None)
            creados.append("caja")

        hoy = date.today()
        for tipo, prefijo in (("FE", "DEMO"), ("NC", "DNC")):
            existe = db.scalar(
                select(ResolucionNumeracion.id).where(
                    ResolucionNumeracion.caja_id == caja.id, ResolucionNumeracion.tipo_documento_codigo == tipo
                )
            )
            if existe is None:
                svc_fiscal.crear_resolucion(
                    db,
                    empresa_id=base.empresa_id,
                    sede_id=sede_id,
                    caja_id=caja.id,
                    tipo=tipo,
                    prefijo=prefijo,
                    rango_desde=1,
                    rango_hasta=100000,
                    numero_resolucion=f"DEMO-{tipo}-0000001",
                    id_rango_proveedor=f"DEMO-{tipo}",
                    vigente_desde=hoy,
                    vigente_hasta=hoy + timedelta(days=365),
                )
                creados.append(f"resolución de prueba {tipo} (modo proveedor)")

        emp = {e.clave: _empleado(db, e, sede_id, creados) for e in EMPLEADOS_DEMO}

        actor = SimpleNamespace(empleado=emp["propietario"], pos=None)  # alta rápida de clientes
        nuevos_clientes = 0
        for c in CLIENTES_DEMO:
            _, creado = svc_ventas.crear_tercero_rapido(db, actor, TerceroRapidoIn(**c))
            nuevos_clientes += int(creado)
        if nuevos_clientes:
            creados.append(f"{nuevos_clientes} clientes")

        if catalogo:
            resumen = catalogo_demo.sembrar_catalogo(db, emp["propietario"].id, bodega.id)
            if resumen.productos_nuevos:
                creados.append(f"catálogo demo ({resumen.productos_nuevos} productos)")

        nuevos = creados[len(base.creados) :]
        if nuevos:
            registrar_accion(
                db, "organizacion.datos_demo", despues={"creados": nuevos}, entidad_tipo="sede", entidad_id=sede_id
            )
    return ResultadoDemo(
        base.nodo_edge_id,
        sede_id,
        bodega.id,
        averias.id,
        caja.id,
        emp["cajero"].id,
        emp["propietario"].id,
        emp["vendedor"].id,
        creados,
        resumen,
    )
