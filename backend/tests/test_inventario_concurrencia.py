"""20 ajustes concurrentes sobre el mismo producto: la existencia final es la suma del kardex (sin pérdidas)."""

from __future__ import annotations

import threading
from decimal import Decimal
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.modules.inventario import servicios as inv
from app.modules.inventario.verificacion import verificar
from tests import factories as f
from tests.conftest import borrar_bd, config_alembic, crear_bd

BD = "mundorepuestos_test_conc_inv"
HILOS = 20


@pytest.fixture
def bd_concurrente(url_base):
    url = crear_bd(url_base, BD)
    command.upgrade(config_alembic(url), "head")
    eng = create_engine(url, pool_size=HILOS, max_overflow=0)
    try:
        yield eng
    finally:
        eng.dispose()
        borrar_bd(url_base, BD)


def test_20_ajustes_concurrentes_la_existencia_es_la_suma_del_kardex(bd_concurrente):
    eng = bd_concurrente
    with eng.begin() as c:
        ent = f.entorno_pos(c)
        producto = f.producto(c)
    actor = SimpleNamespace(empleado=SimpleNamespace(id=ent["empleado"]), pos=None)
    # 20 ajustes: cantidades distintas, mitad positivos y mitad negativos; valor < umbral (no piden autorización)
    cantidades = [Decimal(i) if i % 2 == 0 else Decimal(-i) for i in range(1, HILOS + 1)]
    barrera = threading.Barrier(HILOS)
    errores: list[BaseException] = []

    def trabajo(i: int) -> None:
        try:
            with Session(eng) as db:
                barrera.wait(timeout=30)  # todos a la vez sobre la misma fila de existencias
                inv.registrar_ajuste(
                    db,
                    actor,
                    bodega_id=ent["bodega"],
                    producto_id=producto,
                    cantidad=cantidades[i],
                    motivo=f"ajuste concurrente {i}",
                    costo_unitario=Decimal("100"),
                )
                db.commit()
        except BaseException as e:  # noqa: BLE001
            errores.append(e)

    hilos = [threading.Thread(target=trabajo, args=(i,)) for i in range(HILOS)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=90)
    assert not errores, errores

    with eng.connect() as c:
        suma = c.execute(
            text("SELECT sum(cantidad) FROM inventario.movimientos_inventario WHERE producto_id = :p"), {"p": producto}
        ).scalar_one()
        existencia, ultima = c.execute(
            text("SELECT cantidad, ultima_secuencia FROM inventario.existencias WHERE producto_id = :p"),
            {"p": producto},
        ).one()
        movs = c.execute(
            text(
                "SELECT secuencia, saldo_cantidad FROM inventario.movimientos_inventario "
                "WHERE producto_id = :p ORDER BY secuencia"
            ),
            {"p": producto},
        ).all()
    assert len(movs) == HILOS
    assert existencia == suma == sum(cantidades)
    assert [m[0] for m in movs] == list(range(1, HILOS + 1)) and ultima == HILOS  # sin huecos ni duplicados
    acumulado = Decimal(0)
    # el saldo de cada movimiento es la suma de los anteriores (cadena consistente)
    with eng.connect() as c:
        filas = c.execute(
            text(
                "SELECT cantidad, saldo_cantidad FROM inventario.movimientos_inventario "
                "WHERE producto_id = :p ORDER BY secuencia"
            ),
            {"p": producto},
        ).all()
    for cantidad, saldo in filas:
        acumulado += cantidad
        assert saldo == acumulado
    with Session(eng) as db:
        assert verificar(db) == []
