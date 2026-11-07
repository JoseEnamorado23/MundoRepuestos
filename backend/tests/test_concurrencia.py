"""Numeración interna por caja bajo concurrencia real (varias conexiones y transacciones simultáneas)."""

from __future__ import annotations

import threading
from collections import Counter

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from tests import factories as f
from tests.conftest import borrar_bd, config_alembic, crear_bd

BD_CONCURRENCIA = "mundorepuestos_test_conc"
HILOS = 20
ROLLBACKS = {3, 7, 11, 15, 19}  # hilos que abortan su transacción tras pedir el número


@pytest.fixture
def bd_concurrente(url_base):
    """BD propia (las transacciones aquí SÍ se confirman); se elimina al terminar."""
    url = crear_bd(url_base, BD_CONCURRENCIA)
    command.upgrade(config_alembic(url), "head")
    eng = create_engine(url, pool_size=HILOS, max_overflow=0)
    try:
        yield eng
    finally:
        eng.dispose()
        borrar_bd(url_base, BD_CONCURRENCIA)


def test_numero_interno_20_transacciones_concurrentes_sin_huecos_ni_duplicados(bd_concurrente):
    eng = bd_concurrente
    with eng.begin() as c:
        ent = f.entorno_pos(c)

    barrera = threading.Barrier(HILOS)
    resultados: dict[int, int | None] = {}
    errores: list[BaseException] = []

    def trabajo(i: int) -> None:
        try:
            with eng.connect() as c:
                tx = c.begin()
                barrera.wait(timeout=30)  # todos piden número a la vez
                n = c.execute(text("SELECT cajas.siguiente_numero_interno(:c)"), {"c": ent["caja"]}).scalar_one()
                if i in ROLLBACKS:
                    tx.rollback()
                    resultados[i] = None
                else:
                    c.execute(
                        text(
                            "INSERT INTO ventas.ventas (id, canal, sede_id, caja_id, turno_id, tercero_id, "
                            "numero_interno, subtotal, descuento_total, impuesto_total, redondeo, total, nodo_origen_id) "
                            "VALUES (gen_random_uuid(), 'pos', :s, :c, :t, :cf, :n, 0, 0, 0, 0, 0, :nodo)"
                        ),
                        {
                            "s": ent["sede"],
                            "c": ent["caja"],
                            "t": ent["turno"],
                            "cf": f.TERCERO_CONSUMIDOR_FINAL,
                            "n": n,
                            "nodo": f.NODO_NUBE,
                        },
                    )
                    tx.commit()
                    resultados[i] = n
        except BaseException as e:  # noqa: BLE001
            errores.append(e)

    hilos = [threading.Thread(target=trabajo, args=(i,)) for i in range(HILOS)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    assert not errores, errores

    confirmados = sorted(n for n in resultados.values() if n is not None)
    assert len(confirmados) == HILOS - len(ROLLBACKS)
    assert not [k for k, v in Counter(confirmados).items() if v > 1], "números duplicados"
    assert confirmados == list(range(1, len(confirmados) + 1)), "hay huecos"  # rollback no deja huecos

    with eng.connect() as c:
        assert c.execute(
            text("SELECT ultimo_numero_interno FROM cajas.cajas WHERE id = :c"), {"c": ent["caja"]}
        ).scalar_one() == len(confirmados)
        en_bd = [
            r[0]
            for r in c.execute(
                text("SELECT numero_interno FROM ventas.ventas WHERE caja_id = :c ORDER BY 1"), {"c": ent["caja"]}
            )
        ]
        assert en_bd == confirmados
