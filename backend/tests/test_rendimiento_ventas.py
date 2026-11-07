"""Rendimiento: confirmar una venta de 10 ítems (HTTP + BD con commits); objetivo p95 < 200 ms (ver LIMITE_P95_MS)."""

from __future__ import annotations

import os
import statistics
import time

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from tests.conftest import borrar_bd, config_alembic, crear_bd
from tests.pos_helpers import Cliente, construir_pos, efectivo, linea, producto, uid7

BD = "mundorepuestos_test_perf_ventas"
MUESTRAS = 60
# Objetivo de producto: p95 < 200 ms. Con PostgreSQL en Docker Desktop (Windows) cada ida y vuelta cuesta ~1,3 ms y la
# venta de 10 ítems hace ~78 sentencias, así que aquí el piso es ~100 ms solo de latencia; por eso el umbral por
# defecto de la suite (guardia contra regresiones) es más holgado. En el mini PC (BD local) exigir 200:
#   RENDIMIENTO_P95_MS=200 uv run pytest tests/test_rendimiento_ventas.py -s
LIMITE_P95_MS = float(os.environ.get("RENDIMIENTO_P95_MS", "300"))


@pytest.fixture
def bd(url_base, monkeypatch):
    url = crear_bd(url_base, BD)
    command.upgrade(config_alembic(url), "head")
    eng = create_engine(url, pool_size=5)
    import app.core.db as db_mod

    monkeypatch.setattr(db_mod, "_Session", sessionmaker(bind=eng, expire_on_commit=False))
    try:
        yield eng
    finally:
        eng.dispose()
        borrar_bd(url_base, BD)


def test_confirmar_venta_de_10_items_p95(bd):
    with bd.begin() as c, Session(bind=c, join_transaction_mode="create_savepoint", expire_on_commit=False) as db:
        pm = construir_pos(c, db)
        pids = [producto(c, db, pm, f"Repuesto {i}", "10000", stock="100000") for i in range(10)]
    cliente = Cliente(TestClient(create_app(), raise_server_exceptions=False), pm, "111111")
    cliente.abrir_turno("0")
    lineas = [linea(p) for p in pids]
    # calentamiento (conexiones, caches de plan)
    for _ in range(3):
        assert cliente.vender(lineas, [efectivo(100000)]).status_code == 201
    tiempos = []
    for _ in range(MUESTRAS):
        t0 = time.perf_counter()
        r = cliente.vender(lineas, [efectivo(100000)], vid=uid7())
        tiempos.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 201, r.text
    tiempos.sort()
    p95 = tiempos[int(len(tiempos) * 0.95) - 1]
    print(
        f"\n[rendimiento] confirmar venta de 10 ítems, {MUESTRAS} muestras: "
        f"p50={statistics.median(tiempos):.1f} ms  p95={p95:.1f} ms  máx={tiempos[-1]:.1f} ms"
    )
    assert p95 < LIMITE_P95_MS, f"p95 = {p95:.1f} ms"
