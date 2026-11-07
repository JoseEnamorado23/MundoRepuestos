"""Backoffice: login, refresh con rotación, logout, permisos, tokens vencidos y administración de empleados."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.seguridad import crear_jwt
from tests import api_helpers as h

API = "/api/v1"


@pytest.fixture
def mundo(conn, db):
    return h.construir_mundo(conn, db)


def test_login_correcto_y_me(client, mundo):
    r = h.login(client, "admin")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["token_type"] == "bearer" and cuerpo["expira_en"] == 900
    assert cuerpo["access_token"] and cuerpo["refresh_token"]

    me = client.get(f"{API}/auth/me", headers=h.bearer(cuerpo["access_token"]))
    assert me.status_code == 200
    datos = me.json()
    assert datos["empleado"]["usuario"] == "admin"
    assert datos["empleado"]["roles"] == ["administrador"]
    assert "admin.usuarios" in datos["permisos"] and "cajas.dispositivos.gestionar" in datos["permisos"]
    assert [s["sede_id"] for s in datos["empleado"]["sedes"]] == [mundo.sede]
    assert "password_hash" not in me.text and "pin" not in me.text.replace("tiene_pin", "")


def test_login_incorrecto_no_revela_si_el_usuario_existe(client, mundo):
    malo_pass = h.login(client, "admin", "otra-clave")
    no_existe = h.login(client, "fantasma", "otra-clave")
    assert malo_pass.status_code == no_existe.status_code == 401
    assert malo_pass.json()["detail"] == no_existe.json()["detail"]
    assert malo_pass.json()["code"] == "credenciales_invalidas"


def test_login_se_bloquea_tras_n_intentos_fallidos(client, mundo):
    for _ in range(3):
        assert h.login(client, "admin", "mala").status_code == 401
    r = h.login(client, "admin")  # incluso con la clave correcta
    assert r.status_code == 429
    assert r.json()["code"] == "bloqueo_temporal"
    assert int(r.headers["Retry-After"]) > 0


def test_refresh_rota_y_el_viejo_no_sirve_dos_veces(client, mundo):
    t1 = h.login(client, "admin").json()
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 200
    t2 = r.json()
    assert t2["refresh_token"] != t1["refresh_token"]
    assert client.get(f"{API}/auth/me", headers=h.bearer(t2["access_token"])).status_code == 200


def test_reutilizar_refresh_rotado_revoca_toda_la_familia(client, mundo, conn):
    t1 = h.login(client, "admin").json()
    t2 = client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]}).json()
    # alguien presenta de nuevo el token ya rotado (robo): 401 y se revoca la cadena completa
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 401 and r.json()["code"] == "refresh_reutilizado"
    # el token legítimo más reciente también quedó revocado
    r2 = client.post(f"{API}/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert r2.status_code == 401
    sin_revocar = conn.execute(
        text("SELECT count(*) FROM identidad.sesiones_refresh WHERE revocado_at IS NULL")
    ).scalar()
    assert sin_revocar == 0
    # el intento quedó auditado
    assert (
        conn.execute(
            text("SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'identidad.refresh_reutilizado'")
        ).scalar()
        == 1
    )


def test_logout_revoca_la_sesion_y_es_idempotente(client, mundo):
    t = h.login(client, "admin").json()
    assert client.post(f"{API}/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 204
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert client.post(f"{API}/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 204


def test_sin_token_401_y_token_vencido_401(client, mundo):
    sin = client.get(f"{API}/auth/me")
    assert sin.status_code == 401 and sin.json()["code"] == "token_ausente"
    vencido, _ = crear_jwt({"sub": str(mundo.admin.id), "typ": "access"}, timedelta(seconds=-5))
    r = client.get(f"{API}/auth/me", headers=h.bearer(vencido))
    assert r.status_code == 401 and r.json()["code"] == "token_expirado"
    basura = client.get(f"{API}/auth/me", headers=h.bearer("no.es.un.jwt"))
    assert basura.status_code == 401 and basura.json()["code"] == "token_invalido"


def test_endpoint_sin_el_permiso_da_403(client, mundo):
    cajero = h.token_de(client, mundo.cajero.usuario)
    r = client.get(f"{API}/empleados", headers=h.bearer(cajero))
    assert r.status_code == 403
    assert r.json()["code"] == "permiso_denegado" and r.json()["permiso"] == "admin.usuarios"


def test_empleado_desactivado_pierde_acceso_y_sesiones(client, mundo):
    t = h.login(client, mundo.cajero.usuario).json()
    admin = h.token_de(client, "admin")
    r = client.patch(f"{API}/empleados/{mundo.cajero.id}/activo", json={"activo": False}, headers=h.bearer(admin))
    assert r.status_code == 200 and r.json()["activo"] is False
    assert client.get(f"{API}/auth/me", headers=h.bearer(t["access_token"])).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert h.login(client, mundo.cajero.usuario).status_code == 401


# ------------------------------------------------------------------------------ administración
def test_admin_crea_lista_y_asigna_roles_y_sedes(client, mundo, conn):
    admin = h.bearer(h.token_de(client, "admin"))
    nuevo = {
        "tipo_documento_codigo": "13",
        "numero_documento": "555000111",
        "nombres": "Laura",
        "apellidos": "Gómez",
        "usuario": "laura",
        "password": "otra-clave-1234",
        "roles": ["cajero"],
        "sedes": [mundo.sede],
    }
    r = client.post(f"{API}/empleados", json=nuevo, headers=admin)
    assert r.status_code == 201, r.text
    emp = r.json()
    assert emp["roles"] == ["cajero"] and emp["sedes"][0]["es_sede_principal"] is True and "password" not in r.text

    listado = client.get(f"{API}/empleados", params={"q": "laura"}, headers=admin).json()
    assert [e["usuario"] for e in listado] == ["laura"]

    r = client.put(f"{API}/empleados/{emp['id']}/roles", json={"roles": ["supervisor", "bodeguero"]}, headers=admin)
    assert sorted(r.json()["roles"]) == ["bodeguero", "supervisor"]
    r = client.put(
        f"{API}/empleados/{emp['id']}/sedes",
        json={"sedes": [mundo.sede, mundo.sede2], "sede_principal": mundo.sede2},
        headers=admin,
    )
    principales = [s["sede_id"] for s in r.json()["sedes"] if s["es_sede_principal"]]
    assert principales == [mundo.sede2]

    # la nueva contraseña funciona; el cambio de roles quedó auditado
    assert (
        client.post(
            f"{API}/empleados/{emp['id']}/password", json={"password": "clave-nueva-9999"}, headers=admin
        ).status_code
        == 204
    )
    assert h.login(client, "laura", "clave-nueva-9999").status_code == 200
    assert (
        conn.execute(
            text(
                "SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'identidad.roles_cambiados' "
                "AND antes->'roles' = '[\"cajero\"]'::jsonb"
            )
        ).scalar()
        == 1
    )


def test_admin_validaciones_y_conflictos(client, mundo):
    admin = h.bearer(h.token_de(client, "admin"))
    base = {
        "tipo_documento_codigo": "13",
        "numero_documento": "888",
        "nombres": "A",
        "apellidos": "B",
        "usuario": "dup",
        "password": "clave-larga-1",
        "roles": [],
        "sedes": [],
    }
    assert client.post(f"{API}/empleados", json=base, headers=admin).status_code == 201
    # usuario repetido (con otro documento): lo detecta la BD y la API lo traduce
    r = client.post(f"{API}/empleados", json={**base, "numero_documento": "889", "usuario": "DUP"}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "duplicado"
    assert r.json()["detail"] == "Ya existe un empleado con ese usuario."
    # contraseña débil, rol inexistente, PIN inválido
    assert (
        client.post(
            f"{API}/empleados",
            json={**base, "numero_documento": "890", "usuario": "x1y2", "password": "corta"},
            headers=admin,
        ).json()["code"]
        == "password_debil"
    )
    assert (
        client.post(
            f"{API}/empleados",
            json={**base, "numero_documento": "891", "usuario": "x3y4", "roles": ["inventado"]},
            headers=admin,
        ).json()["code"]
        == "rol_invalido"
    )
    emp = client.get(f"{API}/empleados", params={"q": "dup"}, headers=admin).json()[0]
    for malo in ("12ab", "1234", "1234567"):  # el schema exige exactamente 6 dígitos
        r = client.post(f"{API}/empleados/{emp['id']}/pin", json={"pin": malo}, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == "validacion"
    assert client.get(f"{API}/empleados/00000000-0000-0000-0000-000000000000", headers=admin).status_code == 404
