"""Segregación de funciones: entradas/ajustes de backoffice sobre el umbral quedan pendientes de aprobación."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests import api_helpers as h
from tests import factories as f

API = "/api/v1"
UMBRAL = "10000"


@pytest.fixture
def mundo(conn, db):
    return h.construir_mundo(conn, db)


@pytest.fixture
def admin(client, mundo):
    return h.bearer(h.token_de(client, "admin"))


@pytest.fixture
def producto(client, admin):
    cat = client.post(f"{API}/catalogo/categorias", json={"nombre": "Filtros"}, headers=admin).json()["id"]
    r = client.post(
        f"{API}/catalogo/productos",
        json={"sku": "APR-1", "nombre": "Filtro", "categoria_id": cat, "impuesto_id": f.IVA19},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def umbral_bajo(client, mundo, admin):
    r = client.put(f"{API}/inventario/configuracion/{mundo.sede}", json={"umbral_aprobacion": UMBRAL}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["umbral_aprobacion"] == "10000" and r.json()["propietario_autoaprueba"] is False


def _usuario(client, db, mundo, roles):
    e = h.crear_empleado(db, roles=roles, sedes=[uuid.UUID(mundo.sede)])
    return e, h.bearer(h.token_de(client, e.usuario))


def _entrada(client, hdr, bodega, producto, cantidad, costo):
    return client.post(
        f"{API}/inventario/entradas",
        json={
            "bodega_id": bodega,
            "lineas": [{"producto_id": producto, "cantidad": cantidad, "costo_unitario": costo}],
        },
        headers=hdr,
    )


def _ajuste(client, hdr, bodega, producto, cantidad, motivo="Ajuste de prueba de aprobación"):
    return client.post(
        f"{API}/inventario/ajustes",
        json={"bodega_id": bodega, "producto_id": producto, "cantidad": cantidad, "motivo": motivo},
        headers=hdr,
    )


def _stock(conn, bodega, producto):
    return conn.execute(
        text("SELECT coalesce(sum(cantidad), 0) FROM inventario.existencias WHERE bodega_id = :b AND producto_id = :p"),
        {"b": bodega, "p": producto},
    ).scalar_one()


def _movimientos(conn, producto):
    return conn.execute(
        text("SELECT count(*) FROM inventario.movimientos_inventario WHERE producto_id = :p"), {"p": producto}
    ).scalar_one()


def test_entrada_sobre_el_umbral_queda_pendiente_y_se_aplica_al_aprobar(
    client, conn, mundo, admin, producto, db, umbral_bajo
):
    bodega = mundo.ent["bodega"]
    bodeguero, hb = _usuario(client, db, mundo, ["bodeguero"])
    chica = _entrada(client, hb, bodega, producto, "5", "1000")  # 5 000 <= umbral: se aplica ya
    assert chica.status_code == 201, chica.text
    r = _entrada(client, hb, bodega, producto, "100", "1000")  # 100 000 > umbral
    assert r.status_code == 202, r.text
    sol = r.json()
    assert sol["estado"] == "pendiente_aprobacion" and sol["tipo"] == "entrada" and sol["valor"] == "100000.00"
    assert _stock(conn, bodega, producto) == 5 and _movimientos(conn, producto) == 1  # nada se movió

    # el bodeguero ve solo lo suyo y NO puede aprobar
    propias = client.get(f"{API}/inventario/solicitudes", headers=hb).json()
    assert propias["total"] == 1
    assert client.post(f"{API}/inventario/solicitudes/{sol['id']}/aprobar", headers=hb).status_code == 403

    # otro empleado con inventario.aprobar la aprueba: los movimientos se generan en esa misma transacción
    pendientes = client.get(f"{API}/inventario/solicitudes", params={"estado": "pendiente_aprobacion"}, headers=admin)
    assert [s["id"] for s in pendientes.json()["items"]] == [sol["id"]]
    ok = client.post(f"{API}/inventario/solicitudes/{sol['id']}/aprobar", headers=admin)
    assert ok.status_code == 200, ok.text
    res = ok.json()
    assert res["estado"] == "aprobada" and res["autoaprobado"] is False and res["resultado_tipo"] == "entrada_mercancia"
    assert _stock(conn, bodega, producto) == 105 and _movimientos(conn, producto) == 2
    # no se puede resolver dos veces
    assert client.post(f"{API}/inventario/solicitudes/{sol['id']}/aprobar", headers=admin).status_code == 409
    assert (
        client.post(
            f"{API}/inventario/solicitudes/{sol['id']}/rechazar", json={"motivo": "tarde ya"}, headers=admin
        ).status_code
        == 409
    )
    # auditoría de creación y aprobación
    acciones = {
        a
        for (a,) in conn.execute(
            text("SELECT accion FROM auditoria.log_acciones WHERE entidad_id = :i"), {"i": sol["id"]}
        )
    }
    assert {"inventario.solicitud_creada", "inventario.solicitud_aprobada"} <= acciones


def test_ajuste_pendiente_rechazado_no_mueve_nada(client, conn, mundo, admin, producto, db, umbral_bajo):
    bodega = mundo.ent["bodega"]
    assert _entrada(client, admin, bodega, producto, "8", "1000").status_code == 201  # 8 000
    sup, hs = _usuario(client, db, mundo, ["supervisor"])
    r = _ajuste(client, hs, bodega, producto, "-8")  # 8 000 <= umbral
    assert r.status_code == 201, r.text
    assert _entrada(client, admin, bodega, producto, "8", "1000").status_code == 201
    r = _ajuste(client, hs, bodega, producto, "-11")  # 11 000 > umbral (cuesta al CPP)
    assert r.status_code == 202, r.text
    sol = r.json()
    assert sol["tipo"] == "ajuste" and sol["estado"] == "pendiente_aprobacion"
    antes = (_stock(conn, bodega, producto), _movimientos(conn, producto))
    # rechazar exige motivo
    assert client.post(f"{API}/inventario/solicitudes/{sol['id']}/rechazar", json={}, headers=admin).status_code == 422
    no = client.post(
        f"{API}/inventario/solicitudes/{sol['id']}/rechazar",
        json={"motivo": "No hay evidencia del faltante"},
        headers=admin,
    )
    assert no.status_code == 200, no.text
    assert no.json()["estado"] == "rechazada" and no.json()["motivo_resolucion"] == "No hay evidencia del faltante"
    assert (_stock(conn, bodega, producto), _movimientos(conn, producto)) == antes


def test_quien_solicita_no_puede_resolver_su_propia_solicitud(client, conn, mundo, admin, producto, umbral_bajo):
    bodega = mundo.ent["bodega"]
    r = _entrada(client, admin, bodega, producto, "100", "1000")
    assert r.status_code == 202
    sid = r.json()["id"]
    a = client.post(f"{API}/inventario/solicitudes/{sid}/aprobar", headers=admin)
    assert a.status_code == 403 and a.json()["code"] == "segregacion_funciones"
    b = client.post(f"{API}/inventario/solicitudes/{sid}/rechazar", json={"motivo": "me arrepentí"}, headers=admin)
    assert b.status_code == 403 and b.json()["code"] == "segregacion_funciones"
    assert _stock(conn, bodega, producto) == 0
    # la BD también lo impide aunque se salte el servicio
    with pytest.raises(DBAPIError), conn.begin_nested():
        conn.execute(
            text(
                "UPDATE inventario.solicitudes_inventario SET estado = 'aprobada', resuelta_por_id = solicitada_por_id, "
                "resuelta_at = now() WHERE id = :i"
            ),
            {"i": sid},
        )
    with pytest.raises(DBAPIError), conn.begin_nested():  # y el rechazo exige motivo
        conn.execute(
            text(
                "UPDATE inventario.solicitudes_inventario SET estado = 'rechazada', resuelta_por_id = :o, "
                "resuelta_at = now() WHERE id = :i"
            ),
            {"i": sid, "o": str(uuid.uuid4())},
        )


def test_propietario_solo_se_autoaprueba_si_la_sede_lo_permite(client, conn, mundo, admin, producto, db, umbral_bajo):
    bodega = mundo.ent["bodega"]
    prop, hp = _usuario(client, db, mundo, ["propietario"])
    r = _entrada(client, hp, bodega, producto, "100", "1000")
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    # por defecto la sede NO lo permite
    assert client.post(f"{API}/inventario/solicitudes/{sid}/aprobar", headers=hp).status_code == 403
    # un administrador (no propietario) no se autoaprueba aunque la sede lo permita
    p = client.put(
        f"{API}/inventario/configuracion/{mundo.sede}", json={"propietario_autoaprueba": True}, headers=admin
    )
    assert p.status_code == 200 and p.json()["propietario_autoaprueba"] is True
    rr = _entrada(client, admin, bodega, producto, "100", "1000")
    assert client.post(f"{API}/inventario/solicitudes/{rr.json()['id']}/aprobar", headers=admin).status_code == 403
    # el propietario, ahora sí
    ok = client.post(f"{API}/inventario/solicitudes/{sid}/aprobar", headers=hp)
    assert ok.status_code == 200, ok.text
    assert ok.json()["autoaprobado"] is True and ok.json()["resuelta_por_id"] == ok.json()["solicitada_por_id"]
    assert _stock(conn, bodega, producto) == 100
    flag = conn.execute(
        text(
            "SELECT despues ->> 'autoaprobado' FROM auditoria.log_acciones "
            "WHERE accion = 'inventario.solicitud_aprobada' AND entidad_id = :i"
        ),
        {"i": sid},
    ).scalar_one()
    assert flag == "true"
    # un propietario NO puede rechazar la suya (solo aprobar con el flag)
    r2 = _entrada(client, hp, bodega, producto, "100", "1000")
    no = client.post(
        f"{API}/inventario/solicitudes/{r2.json()['id']}/rechazar", json={"motivo": "cancelar mía"}, headers=hp
    )
    assert no.status_code == 403


def test_el_umbral_es_por_sede_y_el_cambio_se_audita(client, conn, mundo, admin, producto):
    # sin configurar rige el valor por defecto (500 000)
    bodega = mundo.ent["bodega"]
    assert (
        client.get(f"{API}/inventario/configuracion/{mundo.sede}", headers=admin).json()["umbral_aprobacion"]
        == "500000"
    )
    assert _entrada(client, admin, bodega, producto, "400", "1000").status_code == 201  # 400 000
    client.put(f"{API}/inventario/configuracion/{mundo.sede}", json={"umbral_aprobacion": "100000"}, headers=admin)
    assert _entrada(client, admin, bodega, producto, "400", "1000").status_code == 202  # ahora supera
    # la otra sede conserva el umbral por defecto
    assert (
        client.get(f"{API}/inventario/configuracion/{mundo.sede2}", headers=admin).json()["umbral_aprobacion"]
        == "500000"
    )
    n = conn.execute(
        text("SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'inventario.configuracion_cambiada'")
    ).scalar_one()
    assert n == 1
    # cambiar la configuración exige admin.configuracion
    cajero = h.bearer(h.token_de(client, mundo.cajero.usuario))
    assert (
        client.put(
            f"{API}/inventario/configuracion/{mundo.sede}", json={"umbral_aprobacion": "1"}, headers=cajero
        ).status_code
        == 403
    )


def test_la_bd_exige_que_quien_autoriza_sea_otro_y_tenga_el_permiso(conn, mundo):
    base = dict(
        tipo="ajuste_inventario",
        permiso_codigo="inventario.ajustar",
        expira_at="2099-01-01T00:00:00Z",
    )
    ok = f.insertar(
        conn,
        "identidad.autorizaciones",
        solicitado_por_id=str(mundo.cajero.id),
        autorizado_por_id=str(mundo.supervisor.id),
        **base,
    )
    assert ok
    with pytest.raises(DBAPIError, match="no_autoautorizacion"), conn.begin_nested():
        f.insertar(
            conn,
            "identidad.autorizaciones",
            solicitado_por_id=str(mundo.supervisor.id),
            autorizado_por_id=str(mundo.supervisor.id),
            **base,
        )
    with pytest.raises(DBAPIError, match="no está activo o no tiene el permiso"), conn.begin_nested():
        f.insertar(
            conn,
            "identidad.autorizaciones",
            solicitado_por_id=str(mundo.supervisor.id),
            autorizado_por_id=str(mundo.cajero.id),  # el cajero no tiene inventario.ajustar
            **base,
        )
