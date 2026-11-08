"""docker-compose: API y worker-fiscal montan el MISMO volumen nombrado de archivos (el PDF que baja el worker se
descarga desde la API)."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _montaje(servicio: dict) -> tuple[str, str]:
    (m,) = [v for v in servicio["volumes"] if v.split(":")[1].startswith("/data/media")]
    nombre, destino = m.split(":")[:2]
    return nombre, destino


def test_api_y_worker_fiscal_comparten_el_volumen_de_archivos():
    c = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    api, worker = c["services"]["api"], c["services"]["worker-fiscal"]
    assert _montaje(api) == _montaje(worker)
    nombre, destino = _montaje(api)
    assert nombre in c["volumes"], "debe ser un volumen NOMBRADO declarado, no un bind mount"
    assert api["environment"]["MEDIA_DIR"] == worker["environment"]["MEDIA_DIR"] == destino
