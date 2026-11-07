"""Rendimiento de búsqueda y escáner con 50.000 productos (BD aparte `mundorepuestos_test_perf`, se recrea).

Uso (desde backend/, con la BD arriba):
    uv run python -m scripts.perf_catalogo [--productos 50000] [--repeticiones 200]

Mide la latencia de la aplicación completa (auth + permisos + SQL + serialización) con TestClient sobre la BD real,
sin red. Objetivos: p95 búsqueda < 150 ms, p95 escáner < 30 ms.
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
import time
import uuid

os.environ.setdefault("ENV", "pruebas")
os.environ["MODE"] = "cloud"
os.environ["NODO_ID"] = "00000000-0000-7000-8000-000000000001"

from alembic import command  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from tests import factories as f  # noqa: E402
from tests.api_helpers import crear_empleado  # noqa: E402
from tests.conftest import borrar_bd, config_alembic, crear_bd  # noqa: E402

BD = "mundorepuestos_test_perf"
PIEZAS = ["Pastilla", "Filtro", "Disco", "Bujía", "Amortiguador", "Correa", "Bomba", "Rodamiento", "Sensor", "Empaque"]
SISTEMAS = ["freno", "aceite", "aire", "combustible", "suspensión", "motor", "transmisión", "dirección", "eléctrico"]
POSICION = ["delantera", "trasera", "izquierda", "derecha", "universal", "superior", "inferior"]


def sembrar(eng, n: int) -> dict:
    with eng.begin() as c:
        ent = f.entorno_pos(c)
    with Session(eng) as db:
        admin = crear_empleado(db, roles=["administrador"], sedes=[uuid.UUID(ent["sede"])], usuario="admin")
    nodo = f.NODO_NUBE
    t0 = time.perf_counter()
    with eng.begin() as c:
        c.execute(text("SET LOCAL synchronous_commit = off"))
        c.execute(
            text(
                "INSERT INTO catalogo.categorias (id, nombre, slug, nodo_origen_id) "
                "SELECT gen_random_uuid(), 'Categoría ' || g, 'categoria-' || g, :n FROM generate_series(1, 40) g"
            ),
            {"n": nodo},
        )
        c.execute(
            text(
                "INSERT INTO catalogo.marcas (id, nombre, slug, nodo_origen_id) "
                "SELECT gen_random_uuid(), 'Marca ' || g, 'marca-' || g, :n FROM generate_series(1, 30) g"
            ),
            {"n": nodo},
        )
        c.execute(
            text(
                "INSERT INTO catalogo.productos (id, sku, nombre, categoria_id, marca_id, impuesto_id, nodo_origen_id) "
                "SELECT gen_random_uuid(), 'SKU' || lpad(g::text, 7, '0'), "
                "  (CAST(:piezas AS text[]))[1 + g % :np] || ' ' || (CAST(:sistemas AS text[]))[1 + (g / 7) % :ns] || ' ' "
                "  || (CAST(:pos AS text[]))[1 + (g / 3) % :nq] || ' modelo ' || g, "
                "  (SELECT id FROM catalogo.categorias ORDER BY id OFFSET g % 40 LIMIT 1), "
                "  (SELECT id FROM catalogo.marcas ORDER BY id OFFSET g % 30 LIMIT 1), "
                "  :iva, :n "
                "FROM generate_series(1, :cant) g"
            ).bindparams(),
            {
                "piezas": PIEZAS,
                "np": len(PIEZAS),
                "sistemas": SISTEMAS,
                "ns": len(SISTEMAS),
                "pos": POSICION,
                "nq": len(POSICION),
                "iva": f.IVA19,
                "n": nodo,
                "cant": n,
            },
        )
        c.execute(
            text(
                "INSERT INTO catalogo.productos_codigos_barras (id, producto_id, codigo, tipo, es_principal, nodo_origen_id) "
                "SELECT gen_random_uuid(), p.id, '77' || lpad(substring(p.sku from 4)::text, 11, '0'), 'ean13', true, :n "
                "FROM catalogo.productos p"
            ),
            {"n": nodo},
        )
        c.execute(
            text(
                "INSERT INTO catalogo.productos_referencias (id, producto_id, tipo, referencia, nodo_origen_id) "
                "SELECT gen_random_uuid(), p.id, 'oem', 'AB-' || substring(p.sku from 4) || '-X', :n "
                "FROM catalogo.productos p"
            ),
            {"n": nodo},
        )
        c.execute(
            text(
                "INSERT INTO catalogo.precios (id, producto_id, lista_precio_id, precio, nodo_origen_id, vigente_desde) "
                "SELECT gen_random_uuid(), p.id, :l, 10000 + (random() * 90000)::int, :n, now() - interval '1 day' "
                "FROM catalogo.productos p"
            ),
            {"l": f.LISTA_GENERAL, "n": nodo},
        )
        c.execute(
            text(
                "INSERT INTO inventario.existencias (bodega_id, producto_id, cantidad) "
                "SELECT :b, p.id, (random() * 20)::int FROM catalogo.productos p"
            ),
            {"b": ent["bodega"]},
        )
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("VACUUM ANALYZE"))  # estadísticas y visibility map listos: mide la consulta, no el autovacuum
    time.sleep(3)
    print(f"Sembrados {n} productos (con código, referencia, precio y stock) en {time.perf_counter() - t0:.1f} s")
    return dict(ent=ent, admin=admin)


def pctl(v: list[float], p: float) -> float:
    s = sorted(v)
    return s[min(len(s) - 1, int(len(s) * p))]


def medir(nombre: str, llamadas: list, objetivo_ms: float) -> bool:
    for ll in llamadas[:10]:  # calentamiento
        ll()
    t = []
    for ll in llamadas:
        t0 = time.perf_counter()
        r = ll()
        t.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200, (r.status_code, r.text[:300])
    p95 = pctl(t, 0.95)
    ok = p95 < objetivo_ms
    print(
        f"{nombre:<34} n={len(t):<4} media={statistics.mean(t):6.1f} ms  p50={pctl(t, 0.5):6.1f}  "
        f"p95={p95:6.1f}  máx={max(t):6.1f}   objetivo p95 < {objetivo_ms:.0f} ms  {'OK' if ok else 'NO CUMPLE'}"
    )
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--productos", type=int, default=50000)
    ap.add_argument("--repeticiones", type=int, default=200)
    ap.add_argument("--conservar", action="store_true", help="no borrar la BD al terminar")
    a = ap.parse_args()

    base = get_settings().database_url
    url = crear_bd(base, BD)
    command.upgrade(config_alembic(url), "head")
    eng = create_engine(url)
    datos = sembrar(eng, a.productos)
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    get_settings.cache_clear()

    from fastapi.testclient import TestClient

    from app.main import create_app

    n = a.productos
    rnd = random.Random(7)
    with TestClient(create_app()) as cli:
        r = cli.post("/api/v1/auth/login", json={"usuario": "admin", "password": "Clave-Segura-123"})
        assert r.status_code == 200, r.text
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        sede = datos["ent"]["sede"]

        def buscar(q: str, **extra):
            return lambda: cli.get(
                "/api/v1/catalogo/productos/buscar", params={"q": q, "sede_id": sede, **extra}, headers=h
            )

        def escanear(cod: str):
            return lambda: cli.get(f"/api/v1/pos/productos/codigo/{cod}", params={"sede_id": sede}, headers=h)

        k = a.repeticiones
        ok = True
        print("Líneas base (suelo del entorno: HTTP + auth + 1 consulta trivial):")
        medir("base: /health", [lambda: cli.get("/api/v1/health") for _ in range(k)], 1000)
        medir(
            "base: auth + permiso + 1 SELECT",
            [lambda: cli.get("/api/v1/catalogo/categorias", params={"limit": 1}, headers=h) for _ in range(k)],
            1000,
        )
        consultas = [
            ("búsqueda: texto (2 palabras)", lambda: buscar(f"{rnd.choice(PIEZAS)} {rnd.choice(SISTEMAS)}".lower())),
            (
                "búsqueda: texto + stock",
                lambda: buscar(f"{rnd.choice(PIEZAS)} {rnd.choice(POSICION)}".lower(), solo_con_stock="true"),
            ),
            ("búsqueda: SKU exacto", lambda: buscar(f"SKU{rnd.randint(1, n):07d}")),
            ("búsqueda: referencia con guiones", lambda: buscar(f"AB-{rnd.randint(1, n):07d}-X")),
            ("búsqueda: referencia sin guiones", lambda: buscar(f"AB{rnd.randint(1, n):07d}X")),
            (
                "búsqueda: con error de tipeo",
                lambda: buscar(f"{rnd.choice(PIEZAS)[:-1].lower()}x {rnd.choice(SISTEMAS)}"),
            ),
        ]
        for nombre, gen in consultas:
            ok &= medir(nombre, [gen() for _ in range(k)], 150)
        ok &= medir(
            "escáner: código de barras",
            [escanear(f"77{rnd.randint(1, n):011d}") for _ in range(k)],
            30,
        )
        ok &= medir("escáner: SKU", [escanear(f"SKU{rnd.randint(1, n):07d}") for _ in range(k)], 30)
    eng.dispose()
    if not a.conservar:
        borrar_bd(base, BD)
    print("\nRESULTADO:", "todos los objetivos se cumplen" if ok else "hay objetivos incumplidos")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
