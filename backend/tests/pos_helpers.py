"""Mundo de pruebas del POS: sede con caja, bodegas (vendible y averías), resoluciones FE/NC, empleados, productos y stock.

Todo por los servicios reales o SQL directo; sin turno abierto (cada prueba lo abre por la API).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.cajas import servicios as svc_cajas
from app.modules.inventario import servicios as inv
from app.modules.organizacion.configuracion import sembrar_configuracion
from tests import factories as f
from tests.api_helpers import Mundo, bearer, crear_empleado, sesion_pos, token_de

IVA19 = f.IVA19
IVA5 = "00000000-0000-7000-8000-000000000012"
EXCLUIDO = "00000000-0000-7000-8000-000000000014"
CONSUMIDOR_FINAL = f.TERCERO_CONSUMIDOR_FINAL
API = "/api/v1"
_s = 0


def uid7() -> str:
    from app.core.base import uuid7

    return str(uuid7())


@dataclass
class PosMundo:
    mundo: Mundo
    bodega: str
    averias: str
    cajero2: object = None
    vendedor: object = None
    productos: dict = field(default_factory=dict)
    extras: int = 0  # cajas adicionales creadas (para prefijos fiscales distintos: TFB, TFC...)

    @property
    def sede(self) -> str:
        return self.mundo.sede

    @property
    def caja(self) -> str:
        return self.mundo.caja


def resoluciones(conn, empresa: str, sede: str, caja: str, sufijo: str = "") -> None:
    """Resoluciones FE (prefijo TF) y NC (prefijo TN) de la caja, en modo proveedor."""
    for tipo, pref in (("FE", f"TF{sufijo}"), ("NC", f"TN{sufijo}")):
        f.insertar(
            conn,
            "fiscal.resoluciones_numeracion",
            empresa_id=empresa,
            sede_id=sede,
            caja_id=caja,
            modo_numeracion="proveedor",
            id_rango_proveedor=f"R-{tipo}-{f.n()}",
            tipo_documento_codigo=tipo,
            numero_resolucion=f"RES-{f.n()}",
            fecha_resolucion=f.hoy(),
            prefijo=pref,
            rango_desde=1,
            rango_hasta=100000,
            consecutivo_actual=0,
            vigente_desde=f.hoy(),
            vigente_hasta=f.hoy().replace(year=f.hoy().year + 1),
            estado="activa",
        )


def agregar_caja(conn, db: Session, pm: PosMundo) -> PosMundo:
    """Segunda caja en la MISMA bodega y sede, con dispositivo y resoluciones propios."""
    import dataclasses

    c2 = f.caja(conn, pm.sede, pm.bodega)
    resoluciones(conn, pm.mundo.ent["empresa"], pm.sede, c2, sufijo=chr(ord("A") + pm.extras + 1))
    disp, token = svc_cajas.crear_dispositivo(db, uuid.UUID(c2), "POS 2", pm.mundo.admin.id)
    db.commit()
    m2 = dataclasses.replace(
        pm.mundo, ent={**pm.mundo.ent, "caja": c2}, dispositivo_id=disp.id, token_dispositivo=token
    )
    return PosMundo(m2, pm.bodega, pm.averias, pm.cajero2, pm.vendedor, extras=pm.extras + 1)


def construir_pos(conn, db: Session, *, con_resoluciones: bool = True) -> PosMundo:
    e = f.empresa(conn)
    s = f.sede(conn, e)
    b = f.bodega(conn, s)
    av = f.insertar(
        conn, "inventario.bodegas", sede_id=s, codigo=f"AV{f.n()}", nombre="Averías", tipo="averias", es_vendible=False
    )
    c = f.caja(conn, s, b)
    if con_resoluciones:
        resoluciones(conn, e, s, c)
    sede = uuid.UUID(s)
    sembrar_configuracion(db, sede)
    admin = crear_empleado(db, roles=["administrador"], sedes=[sede], usuario=f"adm{f.n()}")
    cajero = crear_empleado(db, roles=["cajero"], sedes=[sede], pin="111111", carne=f"CJ{f.n()}")
    cajero2 = crear_empleado(db, roles=["cajero"], sedes=[sede], pin="222222", carne=f"CK{f.n()}")
    supervisor = crear_empleado(db, roles=["supervisor"], sedes=[sede], pin="999999")
    vendedor = crear_empleado(db, roles=["vendedor"], sedes=[sede], pin="333333", carne=f"VD{f.n()}")
    disp, token = svc_cajas.crear_dispositivo(db, uuid.UUID(c), "POS 1", admin.id)
    db.commit()
    ent = dict(empresa=e, sede=s, bodega=b, caja=c, empleado=str(cajero.id))
    m = Mundo(ent, s, disp.id, token, admin, cajero, supervisor)
    return PosMundo(m, b, av, cajero2, vendedor)


def producto(
    conn,
    db: Session,
    pm: PosMundo,
    nombre: str,
    precio: str,
    *,
    impuesto: str = IVA19,
    stock: str | None = "100",
    costo: str = "50",
):
    """Producto con precio general vigente y stock inicial en la bodega de la caja (stock=None: sin existencias)."""
    pid = f.insertar(
        conn,
        "catalogo.productos",
        sku=f"POS{f.n():05d}",
        nombre=nombre,
        categoria_id=f.categoria(conn),
        impuesto_id=impuesto,
    )
    f.insertar(conn, "catalogo.precios", producto_id=pid, lista_precio_id=f.LISTA_GENERAL, precio=Decimal(precio))
    if stock is not None:
        inv.stock_inicial(
            db,
            None,
            bodega_id=uuid.UUID(pm.bodega),
            producto_id=uuid.UUID(pid),
            cantidad=Decimal(stock),
            costo=Decimal(costo),
        )
        db.commit()
    pm.productos[nombre] = pid
    return pid


class Cliente:
    """Atajos HTTP con la sesión POS de un empleado."""

    def __init__(self, client, pm: PosMundo, pin: str):
        self.c = client
        self.pm = pm
        self.h = bearer(sesion_pos(client, pm.mundo, pin))

    def post(self, ruta, **kw):
        return self.c.post(f"{API}{ruta}", headers=self.h, **kw)

    def get(self, ruta, **kw):
        return self.c.get(f"{API}{ruta}", headers=self.h, **kw)

    def delete(self, ruta, **kw):
        return self.c.delete(f"{API}{ruta}", headers=self.h, **kw)

    def abrir_turno(self, base="50000"):
        r = self.post("/pos/turnos", json={"base_efectivo": base})
        assert r.status_code == 201, r.text
        return r.json()

    def autorizar(self, supervisor_pin: str, accion: str, entidad_tipo=None, entidad_id=None, motivo="prueba"):
        r = self.post(
            "/pos/autorizaciones",
            json={
                "pin": supervisor_pin,
                "accion": accion,
                "entidad_tipo": entidad_tipo,
                "entidad_id": entidad_id,
                "motivo": motivo,
            },
        )
        assert r.status_code == 201, r.text
        return r.json()["autorizacion_id"]

    def vender(self, lineas, pagos, *, vid=None, **extra):
        cuerpo = {"id": vid or uid7(), "lineas": lineas, "pagos": pagos, **extra}
        return self.post("/pos/ventas", json=cuerpo)


def linea(producto_id, cantidad="1", **kw):
    return {"producto_id": producto_id, "cantidad": cantidad, **kw}


def efectivo(recibido):
    return {"medio_pago_codigo": "10", "valor_recibido": str(recibido)}


__all__ = [
    "PosMundo",
    "construir_pos",
    "agregar_caja",
    "resoluciones",
    "producto",
    "Cliente",
    "linea",
    "efectivo",
    "uid7",
    "token_de",
    "bearer",
    "IVA5",
    "EXCLUIDO",
]
