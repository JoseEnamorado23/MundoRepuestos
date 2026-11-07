"""Pruebas contra el SANDBOX REAL de Factus (`pytest -m factus -s`). Se omiten si faltan credenciales en .env.

Recorren el camino completo: venta POS -> FE `pendiente_envio` -> worker (proveedor Factus real) -> aceptada -> NC parcial.
Comprueban que los totales de Factus coinciden con los nuestros AL PESO (el worker abre la alerta
`totales_descuadrados` si no) y escriben número y CUFE (salida de `-s`) para revisión manual.
Cada ejecución consume consecutivos del sandbox (compartido).
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.almacenamiento import AlmacenamientoLocal
from app.core.config import get_settings
from app.modules.fiscal import emision
from app.modules.fiscal.proveedores.factus import ProveedorFiscalFactus
from app.modules.organizacion.servicios import calcular_dv
from tests.pos_helpers import Cliente, construir_pos, efectivo, linea, producto, uid7

D = Decimal
pytestmark = pytest.mark.factus
RANGO_FE, RANGO_NC = "389", "390"  # ids de los rangos del sandbox (ver docs/integraciones/factus.md; `fiscal rangos`)


@pytest.fixture(scope="module")
def factus():
    cfg = get_settings()
    if not all(
        (cfg.factus_url, cfg.factus_client_id, cfg.factus_client_secret, cfg.factus_username, cfg.factus_password)
    ):
        pytest.skip("Sin credenciales FACTUS_* en .env")
    p = ProveedorFiscalFactus(
        url=cfg.factus_url,
        client_id=cfg.factus_client_id,
        client_secret=cfg.factus_client_secret,
        username=cfg.factus_username,
        password=cfg.factus_password,
        certificados_sistema=cfg.fiscal_certificados_sistema,
    )
    yield p
    p.cerrar()


@pytest.fixture
def pos(conn, db, client):
    pm = construir_pos(conn, db)
    # resoluciones reales del sandbox: FE SETP (990000000-995000000) y NC con el rango de Factus
    conn.execute(
        text(
            "UPDATE fiscal.resoluciones_numeracion SET id_rango_proveedor = :r, prefijo = :p, rango_desde = :d, "
            "rango_hasta = :h, consecutivo_actual = :d - 1 WHERE caja_id = :c AND tipo_documento_codigo = :t"
        ),
        {"r": RANGO_FE, "p": "SETP", "d": 990000000, "h": 995000000, "c": pm.caja, "t": "FE"},
    )
    conn.execute(
        text(
            "UPDATE fiscal.resoluciones_numeracion SET id_rango_proveedor = :r, prefijo = :p, rango_desde = 1, "
            "rango_hasta = 99999999, consecutivo_actual = 0 WHERE caja_id = :c AND tipo_documento_codigo = :t"
        ),
        {"r": RANGO_NC, "p": "NC", "c": pm.caja, "t": "NC"},
    )
    cajero = Cliente(client, pm, "111111")
    cajero.abrir_turno("50000")
    return pm, cajero


def _enviar_todo(db, conn, factus, tmp_path, maximo=6):
    almacen = AlmacenamientoLocal(tmp_path)
    cfg = get_settings()
    hechos = []
    for _ in range(maximo):
        conn.execute(
            text(
                "UPDATE sync.outbox_eventos SET proximo_intento_at = now() - interval '1 second' "
                "WHERE evento_tipo = 'fiscal.emitir' AND estado IN ('pendiente','enviado')"
            )
        )
        r = emision.procesar_siguiente(db, factus, cfg, almacen, rng=random.Random(1))
        db.flush()
        if r is None:
            break
        hechos.append(r)
    return hechos


def _informe(conn, doc_id, etiqueta):
    fila = conn.execute(
        text(
            "SELECT estado, numero_completo, cufe_cude, subtotal, impuesto_total, total, redondeo, ultimo_error "
            "FROM fiscal.documentos_fiscales WHERE id = :i"
        ),
        {"i": doc_id},
    ).one()
    desc = conn.execute(
        text("SELECT count(*) FROM fiscal.alertas_fiscales WHERE documento_id = :i AND tipo = 'totales_descuadrados'"),
        {"i": doc_id},
    ).scalar_one()
    print(
        f"\n[SANDBOX {etiqueta}] estado={fila.estado} numero={fila.numero_completo} cufe={(fila.cufe_cude or '')[:24]}… "
        f"subtotal={fila.subtotal} iva={fila.impuesto_total} total={fila.total} redondeo={fila.redondeo} "
        f"totales_descuadrados={'SI' if desc else 'no'}"
    )
    assert fila.estado == "aceptado", fila.ultimo_error
    assert fila.numero_completo and fila.cufe_cude
    assert desc == 0, (
        "Los totales de Factus no coinciden con los nuestros: documentar el caso (ver docs/integraciones/factus.md)"
    )
    return fila


def test_fe_a_consumidor_final(conn, db, pos, factus, tmp_path):
    pm, cajero = pos
    a = producto(conn, db, pm, "Pastillas freno", "45900", costo="20000")
    b = producto(conn, db, pm, "Filtro aceite", "18750", costo="8000")
    r = cajero.vender([linea(a, "2"), linea(b, "3")], [efectivo(200000)])
    assert r.status_code == 201, r.text
    doc_id = r.json()["documento_fiscal"]["id"]
    assert [x.accion for x in _enviar_todo(db, conn, factus, tmp_path)] == ["aceptado"]
    _informe(conn, doc_id, "FE consumidor final")


def test_fe_a_cliente_con_nit(conn, db, pos, factus, tmp_path):
    pm, cajero = pos
    nit = "900123456"
    t = cajero.post(
        "/pos/terceros",
        json={
            "tipo_documento_codigo": "31",
            "numero_documento": f"{nit}",
            "razon_social": "Taller Automotriz Prueba S.A.S.",
            "email_facturacion": "taller@example.com",
            "telefono": "3001234567",
            "direccion_fiscal": "Calle 10 # 5-20",
            "municipio_codigo": "11001",
        },
    )
    assert t.status_code in (200, 201), t.text
    assert t.json()["dv"] == calcular_dv(nit)
    a = producto(conn, db, pm, "Amortiguador", "189900", costo="90000")
    r = cajero.vender([linea(a, "1")], [efectivo(200000)], tercero_id=t.json()["id"])
    assert r.status_code == 201, r.text
    doc_id = r.json()["documento_fiscal"]["id"]
    assert [x.accion for x in _enviar_todo(db, conn, factus, tmp_path)] == ["aceptado"]
    _informe(conn, doc_id, "FE cliente NIT")


def test_nota_credito_parcial(conn, db, pos, factus, tmp_path):
    pm, cajero = pos
    a = producto(conn, db, pm, "Bujías", "12500", costo="6000")
    v = cajero.vender([linea(a, "4")], [efectivo(60000)]).json()
    fe_id = v["documento_fiscal"]["id"]
    d = cajero.post(
        "/pos/devoluciones",
        json={
            "id": uid7(),
            "venta_id": v["id"],
            "motivo_codigo": "cliente_desiste",
            "reembolso": "efectivo",
            "items": [{"venta_item_id": v["lineas"][0]["id"], "cantidad": "1", "destino": "vendible"}],
            "autorizacion_id": cajero.autorizar("999999", "pos.devolver"),
        },
    )
    assert d.status_code == 201, d.text
    nc_id = d.json()["documento_fiscal"]["id"]
    assert [x.accion for x in _enviar_todo(db, conn, factus, tmp_path)] == ["aceptado", "aceptado"]
    _informe(conn, fe_id, "FE (base de la NC)")
    _informe(conn, nc_id, "NC parcial")
