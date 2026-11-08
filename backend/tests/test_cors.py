"""CORS: el POS de escritorio (Tauri 2) y su servidor de desarrollo pueden llamar a la API; un origen cualquiera no."""

from __future__ import annotations

import pytest

API = "/api/v1"
ORIGENES_POS = ["tauri://localhost", "http://tauri.localhost", "http://localhost:1420"]


@pytest.mark.parametrize("origen", ORIGENES_POS)
def test_preflight_de_los_origenes_del_pos(client, origen):
    r = client.options(
        f"{API}/pos/auth/pin",
        headers={
            "Origin": origen,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-dispositivo-token,authorization",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == origen
    assert "x-dispositivo-token" in r.headers["access-control-allow-headers"].lower()


def test_origen_desconocido_no_recibe_cabecera_cors(client):
    r = client.get(f"{API}/health", headers={"Origin": "https://sitio-malicioso.example"})
    assert "access-control-allow-origin" not in r.headers


def test_la_respuesta_expone_request_id_a_los_origenes_permitidos(client):
    r = client.get(f"{API}/health", headers={"Origin": "tauri://localhost"})
    assert r.headers["access-control-allow-origin"] == "tauri://localhost"
    assert "x-request-id" in r.headers["access-control-expose-headers"].lower()
