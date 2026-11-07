"""Sistema: health, formato problem+json, X-Request-ID, logging JSON y CLI crear-admin."""

from __future__ import annotations

import json
import logging
import re
import uuid

from sqlalchemy import text

from app.cli import main as cli_main
from app.core.logs import FormatoJson
from tests import api_helpers as h

API = "/api/v1"
CLAVES_PROBLEMA = {"type", "title", "status", "detail", "code", "request_id"}


def test_health(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    d = r.json()
    assert d["estado"] == "ok" and d["bd"]["ok"] is True and d["bd"]["latencia_ms"] >= 0
    assert d["modo"] in ("edge", "cloud")
    assert d["nodo_id"] == "00000000-0000-7000-8000-000000000001" and d["nodo_nombre"] == "Nube"
    assert re.fullmatch(r"\d{4}", d["version_migracion"])


def test_health_degradado_si_la_bd_falla(client, monkeypatch):
    import app.core.db as db_mod

    def roto():
        raise RuntimeError("sin bd")

    monkeypatch.setattr(db_mod, "_Session", roto)
    r = client.get(f"{API}/health")
    assert r.status_code == 503 and r.json()["estado"] == "degradado" and r.json()["bd"]["ok"] is False


def test_errores_en_problem_json_con_request_id(client, conn, db):
    mundo = h.construir_mundo(conn, db)
    casos = [
        client.get(f"{API}/no-existe"),  # 404 de ruta
        client.get(f"{API}/auth/me"),  # 401 dominio
        client.post(f"{API}/auth/login", json={"usuario": ""}),  # 422 validación
        h.login(client, "admin", "mala"),  # 401 credenciales
        client.get(
            f"{API}/empleados/00000000-0000-0000-0000-000000000000", headers=h.bearer(h.token_de(client, "admin"))
        ),  # 404 dominio
    ]
    for r in casos:
        assert r.headers["content-type"].startswith("application/problem+json"), r.text
        cuerpo = r.json()
        assert CLAVES_PROBLEMA <= set(cuerpo), cuerpo
        assert cuerpo["status"] == r.status_code
        assert cuerpo["request_id"] == r.headers["X-Request-ID"]
        assert cuerpo["type"].endswith(cuerpo["code"])
    assert [r.status_code for r in casos] == [404, 401, 422, 401, 404]
    val = casos[2].json()
    assert val["code"] == "validacion" and {e["campo"] for e in val["errores"]} == {"usuario", "password"}
    assert mundo.admin.id


def test_x_request_id_se_respeta_o_se_genera(client):
    r = client.get(f"{API}/health", headers={"X-Request-ID": "mi-id-de-traza-123"})
    assert r.headers["X-Request-ID"] == "mi-id-de-traza-123"
    generado = client.get(f"{API}/health").headers["X-Request-ID"]
    assert uuid.UUID(generado)
    invalido = client.get(f"{API}/health", headers={"X-Request-ID": "x y<script>"}).headers["X-Request-ID"]
    assert invalido != "x y<script>" and uuid.UUID(invalido)


def test_el_request_id_llega_a_la_auditoria(client, conn, db):
    h.construir_mundo(conn, db)
    r = h.login(client, "admin", "mala")
    rid = r.headers["X-Request-ID"]
    guardado = conn.execute(
        text(
            "SELECT request_id::text FROM auditoria.log_acciones "
            "WHERE accion = 'identidad.login_fallido' ORDER BY ocurrido_at DESC LIMIT 1"
        )
    ).scalar()
    assert guardado == rid


def test_log_en_json():
    registro = logging.LogRecord("app.http", logging.INFO, __file__, 1, "petición", (), None)
    registro.estado = 200
    linea = FormatoJson().format(registro)
    datos = json.loads(linea)
    assert datos["mensaje"] == "petición" and datos["estado"] == 200 and "ts" in datos and "request_id" in datos


def test_cli_crear_admin(client, conn, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "una-clave-larga-1")
    codigo = cli_main(
        ["crear-admin", "--usuario", "root", "--documento", "123456789", "--nombres", "Ada", "--apellidos", "Lovelace"]
    )
    assert codigo == 0
    r = h.login(client, "root", "una-clave-larga-1")
    assert r.status_code == 200
    me = client.get(f"{API}/auth/me", headers=h.bearer(r.json()["access_token"])).json()
    assert me["empleado"]["roles"] == ["administrador"]
    # repetir falla con mensaje claro y código != 0
    assert (
        cli_main(
            ["crear-admin", "--usuario", "root", "--documento", "123456789", "--nombres", "Ada", "--apellidos", "L"]
        )
        == 1
    )
