"""Corregir y reemitir una FE rechazada (POST /fiscal/documentos/{id}/corregir) con el proveedor simulado."""

from __future__ import annotations

import random
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.almacenamiento import AlmacenamientoLocal
from app.core.config import get_settings
from app.modules.fiscal import emision
from app.modules.fiscal.proveedores.simulado import ProveedorFiscalSimulado
from app.modules.organizacion.servicios import calcular_dv
from tests.api_helpers import bearer, token_de
from tests.pos_helpers import Cliente, construir_pos, efectivo, linea, producto

API = "/api/v1"
D = Decimal
NIT = "900123456"


@pytest.fixture
def pos(conn, db, client):
    pm = construir_pos(conn, db)
    pid = producto(conn, db, pm, "Pastillas", "10000", costo="4000")
    cajero = Cliente(client, pm, "111111")
    cajero.abrir_turno("50000")
    return pm, pid, cajero


@pytest.fixture
def prov():
    return ProveedorFiscalSimulado()


@pytest.fixture
def almacen(tmp_path):
    return AlmacenamientoLocal(tmp_path)


def _uno(conn, sql, **p):
    return conn.execute(text(sql), p).scalar_one()


def _drenar(conn, db, prov, almacen, maximo=10):
    hechos = []
    for _ in range(maximo):
        conn.execute(
            text(
                "UPDATE sync.outbox_eventos SET proximo_intento_at = now() - interval '1 second' "
                "WHERE evento_tipo = 'fiscal.emitir' AND estado IN ('pendiente','enviado')"
            )
        )
        r = emision.procesar_siguiente(db, prov, get_settings(), almacen, rng=random.Random(1))
        db.flush()
        if r is None:
            break
        hechos.append(r)
    return hechos


def _venta_a_nit_con_dv_malo(conn, cajero, pid):
    """Cliente con NIT cuyo DV está mal guardado: la DIAN (simulada) rechaza la factura."""
    dv_ok = calcular_dv(NIT)
    r = cajero.post(
        "/pos/terceros",
        json={"tipo_documento_codigo": "31", "numero_documento": NIT, "razon_social": "Taller El Piston SAS"},
    )
    assert r.status_code in (200, 201), r.text
    tid = r.json()["id"]
    conn.execute(text("UPDATE identidad.terceros SET dv = :d WHERE id = :i"), {"d": (dv_ok + 1) % 10, "i": tid})
    v = cajero.vender([linea(pid, "2")], [efectivo(23800)], tercero_id=tid)
    assert v.status_code == 201, v.text
    return v.json(), dv_ok


def test_rechazo_por_nit_invalido_corregido_termina_aceptado(conn, db, pos, client, prov, almacen):
    pm, pid, cajero = pos
    venta, dv_ok = _venta_a_nit_con_dv_malo(conn, cajero, pid)
    viejo = venta["documento_fiscal"]["id"]
    assert [x.accion for x in _drenar(conn, db, prov, almacen)] == ["rechazado"]
    db.commit()

    h = bearer(token_de(client, pm.mundo.admin.usuario))
    r = client.post(
        f"{API}/fiscal/documentos/{viejo}/corregir", headers=h, json={"motivo": "DV mal digitado", "dv": dv_ok}
    )
    assert r.status_code == 201, r.text
    nuevo = r.json()
    assert nuevo["id"] != viejo and nuevo["documento_corrige_id"] == viejo and nuevo["estado"] == "pendiente_envio"
    assert nuevo["venta_id"] == venta["id"] and D(nuevo["total"]) == D(venta["total"])

    # el anterior queda anulado y deja de ser el vigente; no se crea NC
    assert _uno(conn, "SELECT estado::text FROM fiscal.documentos_fiscales WHERE id = :i", i=viejo) == "anulado"
    assert _uno(conn, "SELECT vigente FROM fiscal.documentos_fiscales WHERE id = :i", i=viejo) is False
    assert _uno(conn, "SELECT count(*) FROM fiscal.documentos_fiscales WHERE tipo_documento_codigo = 'NC'") == 0
    assert (
        _uno(
            conn, "SELECT count(*) FROM fiscal.alertas_fiscales WHERE documento_id = :i AND estado = 'abierta'", i=viejo
        )
        == 0
    )
    # mismos ítems, pagos y totales; snapshot corregido; el original conserva el suyo
    for tabla in ("documentos_fiscales_items", "documentos_fiscales_pagos", "documentos_fiscales_impuestos"):
        assert _uno(conn, f"SELECT count(*) FROM fiscal.{tabla} WHERE documento_id = :i", i=nuevo["id"]) == _uno(
            conn, f"SELECT count(*) FROM fiscal.{tabla} WHERE documento_id = :i", i=viejo
        )
    assert _uno(
        conn, "SELECT adquirente_snapshot->>'dv' FROM fiscal.documentos_fiscales WHERE id = :i", i=nuevo["id"]
    ) == str(dv_ok)
    assert _uno(
        conn, "SELECT adquirente_snapshot->>'dv' FROM fiscal.documentos_fiscales WHERE id = :i", i=viejo
    ) != str(dv_ok)
    assert _uno(conn, "SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'fiscal.documento_corregido'") == 1

    # el worker emite el nuevo con otro reference_code y queda aceptado; la venta apunta al nuevo
    assert [x.accion for x in _drenar(conn, db, prov, almacen)] == ["aceptado"]
    assert _uno(conn, "SELECT estado::text FROM fiscal.documentos_fiscales WHERE id = :i", i=nuevo["id"]) == "aceptado"
    assert ("eliminar", viejo) in prov.llamadas  # se pidió borrar el no validado anterior
    assert client.get(f"{API}/pos/ventas/{venta['id']}/estado-fiscal", headers=cajero.h).json()["estado"] == "aceptado"

    # no se corrige dos veces ni un documento aceptado
    for doc in (viejo, nuevo["id"]):
        assert (
            client.post(
                f"{API}/fiscal/documentos/{doc}/corregir", headers=h, json={"motivo": "otra vez", "dv": 1}
            ).status_code
            == 422
        )


def test_montos_e_items_no_se_pueden_cambiar_y_se_exige_permiso(conn, db, pos, client, prov, almacen):
    pm, pid, cajero = pos
    venta, dv_ok = _venta_a_nit_con_dv_malo(conn, cajero, pid)
    viejo = venta["documento_fiscal"]["id"]
    _drenar(conn, db, prov, almacen)
    db.commit()
    h = bearer(token_de(client, pm.mundo.admin.usuario))
    for campo in ("total", "items", "subtotal", "pagos", "lineas"):  # fuera del esquema: se rechaza, no se ignora
        r = client.post(f"{API}/fiscal/documentos/{viejo}/corregir", headers=h, json={"motivo": "intento", campo: 1})
        assert r.status_code == 422, (campo, r.text)
    assert (
        client.post(f"{API}/fiscal/documentos/{viejo}/corregir", headers=h, json={"motivo": "sin cambios"}).status_code
        == 422
    )
    assert client.post(
        f"{API}/fiscal/documentos/{viejo}/corregir", headers=cajero.h, json={"motivo": "yo", "dv": dv_ok}
    ).status_code in (401, 403)
    assert _uno(conn, "SELECT estado::text FROM fiscal.documentos_fiscales WHERE id = :i", i=viejo) == "rechazado"


def test_la_nc_de_una_fe_corregida_referencia_la_nueva(conn, db, pos, client, prov, almacen):
    pm, pid, cajero = pos
    venta, dv_ok = _venta_a_nit_con_dv_malo(conn, cajero, pid)
    viejo = venta["documento_fiscal"]["id"]
    _drenar(conn, db, prov, almacen)
    db.commit()
    h = bearer(token_de(client, pm.mundo.admin.usuario))
    nuevo = client.post(
        f"{API}/fiscal/documentos/{viejo}/corregir", headers=h, json={"motivo": "DV mal digitado", "dv": dv_ok}
    ).json()
    assert [x.accion for x in _drenar(conn, db, prov, almacen)] == ["aceptado"]
    from app.modules.fiscal.models import DocumentoFiscal

    assert emision._fe_vigente(db, db.get(DocumentoFiscal, uuid.UUID(viejo))).id == uuid.UUID(nuevo["id"])


def _tercero_row(conn, tid):
    return conn.execute(text("SELECT dv, version FROM identidad.terceros WHERE id = :i"), {"i": tid}).one()


def test_corregir_sin_actualizar_tercero_no_toca_el_maestro(conn, db, pos, client, prov, almacen):
    pm, pid, cajero = pos
    venta, dv_ok = _venta_a_nit_con_dv_malo(conn, cajero, pid)
    viejo = venta["documento_fiscal"]["id"]
    tid = _uno(conn, "SELECT adquirente_tercero_id FROM fiscal.documentos_fiscales WHERE id = :i", i=viejo)
    _drenar(conn, db, prov, almacen)
    db.commit()
    antes = _tercero_row(conn, tid)
    h = bearer(token_de(client, pm.mundo.admin.usuario))
    r = client.post(
        f"{API}/fiscal/documentos/{viejo}/corregir", headers=h, json={"motivo": "DV mal digitado", "dv": dv_ok}
    )
    assert r.status_code == 201, r.text
    assert _tercero_row(conn, tid) == antes  # por defecto (actualizar_tercero=false) el maestro queda igual
    assert _uno(conn, "SELECT count(*) FROM sync.outbox_eventos WHERE evento_tipo = 'tercero.actualizado'") == 0


def test_corregir_con_actualizar_tercero_actualiza_el_maestro_con_evento_y_auditoria(
    conn, db, pos, client, prov, almacen
):
    pm, pid, cajero = pos
    venta, dv_ok = _venta_a_nit_con_dv_malo(conn, cajero, pid)
    viejo = venta["documento_fiscal"]["id"]
    tid = _uno(conn, "SELECT adquirente_tercero_id FROM fiscal.documentos_fiscales WHERE id = :i", i=viejo)
    _drenar(conn, db, prov, almacen)
    db.commit()
    assert _tercero_row(conn, tid).dv != dv_ok
    h = bearer(token_de(client, pm.mundo.admin.usuario))
    r = client.post(
        f"{API}/fiscal/documentos/{viejo}/corregir",
        headers=h,
        json={"motivo": "DV mal digitado", "dv": dv_ok, "email": "taller@example.com", "actualizar_tercero": True},
    )
    assert r.status_code == 201, r.text
    fila = _tercero_row(conn, tid)
    assert fila.dv == dv_ok and fila.version >= 2
    assert _uno(conn, "SELECT email_facturacion FROM identidad.terceros WHERE id = :i", i=tid) == "taller@example.com"
    assert _uno(conn, "SELECT count(*) FROM sync.outbox_eventos WHERE evento_tipo = 'tercero.actualizado'") == 1
    assert _uno(conn, "SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'identidad.tercero_actualizado'") == 1
    # la bitácora guarda los NOMBRES de los campos, no sus valores (datos personales)
    assert "taller@example.com" not in str(
        _uno(conn, "SELECT despues FROM auditoria.log_acciones WHERE accion = 'identidad.tercero_actualizado'")
    )


def test_actualizar_tercero_con_documento_duplicado_revierte_toda_la_correccion(conn, db, pos, client, prov, almacen):
    pm, pid, cajero = pos
    venta, _ = _venta_a_nit_con_dv_malo(conn, cajero, pid)
    viejo = venta["documento_fiscal"]["id"]
    otro = cajero.post(
        "/pos/terceros",
        json={"tipo_documento_codigo": "31", "numero_documento": "800123456", "razon_social": "Otro SAS"},
    )
    assert otro.status_code in (200, 201), otro.text
    _drenar(conn, db, prov, almacen)
    db.commit()
    h = bearer(token_de(client, pm.mundo.admin.usuario))
    r = client.post(
        f"{API}/fiscal/documentos/{viejo}/corregir",
        headers=h,
        json={"motivo": "NIT mal digitado", "numero_documento": "800123456", "dv": 1, "actualizar_tercero": True},
    )
    assert r.status_code == 409, r.text
    # todo o nada: el rechazado sigue rechazado y no hay FE nueva
    assert _uno(conn, "SELECT estado::text FROM fiscal.documentos_fiscales WHERE id = :i", i=viejo) == "rechazado"
    assert _uno(conn, "SELECT count(*) FROM fiscal.documentos_fiscales WHERE documento_corrige_id = :i", i=viejo) == 0
