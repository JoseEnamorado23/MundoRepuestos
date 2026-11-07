"""Worker fiscal con el proveedor simulado: flujo completo, reintentos, rechazo, espera de la NC y backoffice."""

from __future__ import annotations

import random
import threading
import uuid
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.almacenamiento import AlmacenamientoLocal
from app.core.config import get_settings
from app.modules.fiscal import emision
from app.modules.fiscal.proveedores.base import ErrorTransitorio
from app.modules.fiscal.proveedores.simulado import ProveedorFiscalSimulado
from tests.api_helpers import bearer, token_de
from tests.conftest import borrar_bd, config_alembic, crear_bd
from tests.pos_helpers import Cliente, construir_pos, efectivo, linea, producto, uid7

API = "/api/v1"
D = Decimal


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


def _elegibles(conn):
    """Hace elegibles ya todos los eventos pendientes (salta las esperas de backoff)."""
    conn.execute(
        text(
            "UPDATE sync.outbox_eventos SET proximo_intento_at = now() - interval '1 second' "
            "WHERE evento_tipo = 'fiscal.emitir' AND estado IN ('pendiente','enviado')"
        )
    )


def _paso(db, prov, almacen):
    r = emision.procesar_siguiente(db, prov, get_settings(), almacen, rng=random.Random(1))
    db.flush()  # las comprobaciones leen con SQL directo: los cambios del ORM deben estar en la BD
    return r


def _drenar(conn, db, prov, almacen, maximo=10):
    hechos = []
    for _ in range(maximo):
        _elegibles(conn)
        r = _paso(db, prov, almacen)
        if r is None:
            break
        hechos.append(r)
    return hechos


def _vender(cajero, pid, cantidad="2"):
    r = cajero.vender([linea(pid, cantidad)], [efectivo(int(D(cantidad) * 11900))])
    assert r.status_code == 201, r.text
    v = r.json()
    return v, v["lineas"][0]["id"]


def _devolver(cajero, venta, item, cantidad):
    r = cajero.post(
        "/pos/devoluciones",
        json={
            "id": uid7(),
            "venta_id": venta["id"],
            "motivo_codigo": "cliente_desiste",
            "reembolso": "efectivo",
            "items": [{"venta_item_id": item, "cantidad": str(cantidad), "destino": "vendible"}],
            "autorizacion_id": cajero.autorizar("999999", "pos.devolver"),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _doc(conn, **p):
    return conn.execute(
        text(
            "SELECT id, estado, intentos, numero_completo, cufe_cude, pdf_url FROM fiscal.documentos_fiscales WHERE id = :i"
        ),
        p,
    ).one()


# ------------------------------------------------------------------------------------------------ flujo
def test_flujo_completo_venta_fe_aceptada_ticket_con_cufe_devolucion_nc_aceptada(conn, db, pos, prov, almacen):
    pm, pid, cajero = pos
    venta, item = _vender(cajero, pid)
    fe_id = venta["documento_fiscal"]["id"]

    # antes de emitir: el ticket lleva la leyenda y el estado liviano no es definitivo
    est = cajero.get(f"/pos/ventas/{venta['id']}/estado-fiscal").json()
    assert est["estado"] == "pendiente_envio" and est["definitivo"] is False and est["leyenda"]

    r = _drenar(conn, db, prov, almacen)
    assert [x.accion for x in r] == ["aceptado"]
    fe = _doc(conn, i=fe_id)
    assert fe.estado == "aceptado" and fe.numero_completo and fe.cufe_cude and fe.pdf_url
    assert almacen.leer(fe.pdf_url).startswith(b"%PDF")

    t = cajero.get(f"/pos/ventas/{venta['id']}/ticket").json()["fiscal"]
    assert t["cufe"] == fe.cufe_cude and t["numero_completo"] == fe.numero_completo and t["leyenda"] is None
    est = cajero.get(f"/pos/ventas/{venta['id']}/estado-fiscal").json()
    assert est["definitivo"] is True and est["cufe"] == fe.cufe_cude

    dev = _devolver(cajero, venta, item, 1)
    nc_id = dev["documento_fiscal"]["id"]
    assert [x.accion for x in _drenar(conn, db, prov, almacen)] == ["aceptado"]
    nc = _doc(conn, i=nc_id)
    assert nc.estado == "aceptado" and nc.numero_completo and nc.cufe_cude != fe.cufe_cude
    assert prov.emitidos == 2
    # cada intento queda en la bitácora
    assert (
        _uno(
            conn,
            "SELECT count(*) FROM fiscal.documentos_fiscales_eventos WHERE documento_id = :i AND codigo_respuesta = 'aceptado'",
            i=fe_id,
        )
        == 1
    )


def test_error_transitorio_deja_pendiente_cuenta_intentos_y_luego_acepta(conn, db, pos, prov, almacen):
    pm, pid, cajero = pos
    venta, _ = _vender(cajero, pid)
    fe_id = venta["documento_fiscal"]["id"]
    prov.fallar_siguientes(1, ErrorTransitorio("timeout", http_status=None))

    _elegibles(conn)
    assert _paso(db, prov, almacen).accion == "reintento"
    fe = _doc(conn, i=fe_id)
    assert fe.estado == "pendiente_envio" and fe.intentos == 1
    assert _uno(conn, "SELECT proximo_intento_at > now() FROM fiscal.documentos_fiscales WHERE id = :i", i=fe_id)
    # con el backoff aún vigente no hay nada elegible
    assert _paso(db, prov, almacen) is None

    assert [x.accion for x in _drenar(conn, db, prov, almacen)] == ["aceptado"]
    assert _doc(conn, i=fe_id).estado == "aceptado"
    assert prov.emitidos == 1  # el reenvío no duplicó el documento


def test_reintentos_agotados_dejan_alerta(conn, db, pos, prov, almacen):
    pm, pid, cajero = pos
    venta, _ = _vender(cajero, pid)
    fe_id = venta["documento_fiscal"]["id"]
    prov.fallar_siguientes(100, ErrorTransitorio("503", http_status=503))
    acciones = [x.accion for x in _drenar(conn, db, prov, almacen, maximo=get_settings().fiscal_max_intentos + 3)]
    assert acciones[-1] == "agotado"
    assert (
        _uno(
            conn,
            "SELECT count(*) FROM fiscal.alertas_fiscales WHERE documento_id = :i AND tipo = 'reintentos_agotados' AND estado = 'abierta'",
            i=fe_id,
        )
        == 1
    )
    assert _doc(conn, i=fe_id).estado == "pendiente_envio"


def test_rechazo_de_validacion_no_se_reintenta_y_alerta(conn, db, pos, prov, almacen):
    pm, pid, cajero = pos
    venta, _ = _vender(cajero, pid)
    fe_id = venta["documento_fiscal"]["id"]
    prov.rechazar(fe_id)
    assert [x.accion for x in _drenar(conn, db, prov, almacen)] == ["rechazado"]
    fe = _doc(conn, i=fe_id)
    assert fe.estado == "rechazado" and fe.intentos == 1
    assert (
        _uno(
            conn, "SELECT count(*) FROM fiscal.alertas_fiscales WHERE documento_id = :i AND tipo = 'rechazado'", i=fe_id
        )
        == 1
    )
    assert _drenar(conn, db, prov, almacen) == []  # no hay reintento automático
    ev = _uno(
        conn,
        "SELECT mensaje FROM fiscal.documentos_fiscales_eventos WHERE documento_id = :i AND codigo_respuesta = 'rechazado'",
        i=fe_id,
    )
    assert "FAJ43b" in ev


def test_la_nc_espera_a_que_su_fe_sea_aceptada(conn, db, pos, prov, almacen):
    pm, pid, cajero = pos
    venta, item = _vender(cajero, pid)
    dev = _devolver(cajero, venta, item, 1)
    fe_id, nc_id = venta["documento_fiscal"]["id"], dev["documento_fiscal"]["id"]
    prov.fallar_siguientes(1, ErrorTransitorio("timeout"))

    _elegibles(conn)
    assert _paso(db, prov, almacen).accion == "reintento"  # la FE falla; queda con backoff
    r = _paso(db, prov, almacen)  # lo siguiente elegible es la NC: debe esperar
    assert r.accion == "esperando_factura" and r.documento_id == uuid.UUID(str(nc_id))
    assert _doc(conn, i=nc_id).estado == "pendiente_envio" and prov.emitidos == 0

    acciones = [x.accion for x in _drenar(conn, db, prov, almacen)]
    assert acciones.count("aceptado") == 2
    assert _doc(conn, i=fe_id).estado == _doc(conn, i=nc_id).estado == "aceptado"


def test_reenvio_con_el_mismo_reference_code_no_duplica(conn, db, pos, prov, almacen):
    from app.modules.fiscal.emision import armar_emision

    pm, pid, cajero = pos
    venta, _ = _vender(cajero, pid)
    from app.modules.fiscal.models import DocumentoFiscal

    doc = db.get(DocumentoFiscal, uuid.UUID(str(venta["documento_fiscal"]["id"])))
    emi = armar_emision(db, doc, None)
    a, b = prov.emitir_factura(emi), prov.emitir_factura(emi)
    assert a.numero == b.numero and a.cufe == b.cufe and prov.emitidos == 1


# ------------------------------------------------------------------------------------------------ backoffice
def test_endpoints_backoffice_listar_detalle_reintentar_y_pdf(conn, db, pos, client, prov, almacen, monkeypatch):
    import app.modules.fiscal.router as router_fiscal

    monkeypatch.setattr(router_fiscal, "get_almacenamiento", lambda: almacen)
    pm, pid, cajero = pos
    v1, _ = _vender(cajero, pid)
    v2, _ = _vender(cajero, pid)
    rechazado, aceptado = v2["documento_fiscal"]["id"], v1["documento_fiscal"]["id"]
    prov.rechazar(rechazado)
    _drenar(conn, db, prov, almacen)
    db.commit()

    h = bearer(token_de(client, pm.mundo.admin.usuario))
    lista = client.get(f"{API}/fiscal/documentos", headers=h, params={"estado": "rechazado"}).json()
    assert lista["total"] == 1 and lista["items"][0]["id"] == rechazado
    todos = client.get(f"{API}/fiscal/documentos", headers=h, params={"tipo": "FE"}).json()
    assert todos["total"] == 2

    det = client.get(f"{API}/fiscal/documentos/{rechazado}", headers=h).json()
    assert {e["tipo"] for e in det["eventos"]} >= {"creado", "respuesta_dian"} and det["alertas"][0][
        "tipo"
    ] == "rechazado"

    pdf = client.get(f"{API}/fiscal/documentos/{aceptado}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert client.get(f"{API}/fiscal/documentos/{rechazado}/pdf", headers=h).status_code == 404

    # un aceptado no se reintenta
    r = client.post(f"{API}/fiscal/documentos/{aceptado}/reintentar", headers=h, json={})
    assert r.status_code == 422 or r.status_code == 409, r.text
    r = client.post(f"{API}/fiscal/documentos/{rechazado}/reintentar", headers=h, json={"comentario": "corregido"})
    assert r.status_code == 200 and r.json()["estado"] == "pendiente_envio"
    assert _uno(conn, "SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'fiscal.reintento_manual'") == 1

    # el cajero no tiene fiscal.gestionar
    hc = cajero.h
    assert client.post(f"{API}/fiscal/documentos/{rechazado}/reintentar", headers=hc, json={}).status_code in (401, 403)


def test_health_informa_el_worker_y_los_documentos(conn, db, pos, client, prov, almacen):
    pm, pid, cajero = pos
    _vender(cajero, pid)
    db.commit()
    h = client.get(f"{API}/health").json()
    assert h["fiscal"]["pendientes"] >= 1 and h["fiscal"]["worker_activo"] is False
    assert h["estado"] == "degradado"  # hay pendientes y nadie los procesa


# ------------------------------------------------------------------------------------------------ concurrencia
def test_dos_workers_no_toman_el_mismo_evento(url_base):
    url = crear_bd(url_base, "mundorepuestos_test_fisc")
    command.upgrade(config_alembic(url), "head")
    eng = create_engine(url)
    try:
        from app.modules.sync.servicios import publicar_evento

        ids = [uuid.uuid4() for _ in range(2)]
        with Session(eng) as s, s.begin():
            for i in ids:
                publicar_evento(s, "documento_fiscal", i, "fiscal.emitir", {"documento_id": i})
        with eng.begin() as c:
            c.execute(text("UPDATE sync.outbox_eventos SET proximo_intento_at = now() - interval '1 second'"))

        tomados: list[uuid.UUID] = []
        listo, seguir = threading.Event(), threading.Event()

        def worker_a():
            with Session(eng) as s, s.begin():
                ev = emision._siguiente_evento(s)
                tomados.append(ev.agregado_id)
                listo.set()
                seguir.wait(10)  # mantiene el bloqueo mientras B pide el suyo

        t = threading.Thread(target=worker_a)
        t.start()
        assert listo.wait(10)
        with Session(eng) as s, s.begin():
            ev_b = emision._siguiente_evento(s)
            tomados.append(ev_b.agregado_id)
        seguir.set()
        t.join()
        assert len(set(tomados)) == 2
    finally:
        eng.dispose()
        borrar_bd(url_base, "mundorepuestos_test_fisc")
