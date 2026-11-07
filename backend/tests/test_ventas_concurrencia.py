"""Concurrencia real (BD con commits): misma venta en paralelo, dos cajas con la última unidad, cierre vs. venta."""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from tests.conftest import borrar_bd, config_alembic, crear_bd
from tests.pos_helpers import Cliente, agregar_caja, construir_pos, efectivo, linea, producto, uid7

BD = "mundorepuestos_test_conc_ventas"
D = Decimal


@pytest.fixture
def bd(url_base, monkeypatch):
    url = crear_bd(url_base, BD)
    command.upgrade(config_alembic(url), "head")
    eng = create_engine(url, pool_size=20, max_overflow=10)
    import app.core.db as db_mod

    monkeypatch.setattr(db_mod, "_Session", sessionmaker(bind=eng, expire_on_commit=False))
    try:
        yield eng
    finally:
        eng.dispose()
        borrar_bd(url_base, BD)


def _montar(eng, *, stock="100", cajas=1):
    """Mundo POS confirmado en BD: devuelve (pm de cada caja, producto)."""
    with eng.begin() as c, Session(bind=c, join_transaction_mode="create_savepoint", expire_on_commit=False) as db:
        pm = construir_pos(c, db)
        pid = producto(c, db, pm, "Último filtro", "10000", stock=stock)
        mundos = [pm] + [agregar_caja(c, db, pm) for _ in range(cajas - 1)]
    return mundos, pid


def _paralelo(trabajos):
    """Ejecuta funciones en hilos que arrancan a la vez (barrera). Devuelve sus resultados o excepciones."""
    barrera = threading.Barrier(len(trabajos))
    salida: list = [None] * len(trabajos)

    def correr(i, fn):
        try:
            salida[i] = fn(barrera)
        except BaseException as e:  # noqa: BLE001
            salida[i] = e

    hilos = [threading.Thread(target=correr, args=(i, fn)) for i, fn in enumerate(trabajos)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=120)
    return salida


def _cliente(pm, pin):
    c = TestClient(create_app(), raise_server_exceptions=False)
    return Cliente(c, pm, pin)


def test_la_misma_venta_en_paralelo_crea_una_sola_venta(bd):
    (pm,), pid = _montar(bd)
    _cliente(pm, "111111").abrir_turno("50000")
    vid = uid7()
    n = 8

    def vender(barrera):
        cli = _cliente(pm, "111111")
        barrera.wait(timeout=60)
        return cli.vender([linea(pid)], [efectivo(10000)], vid=vid)

    res = _paralelo([vender] * n)
    assert all(not isinstance(r, BaseException) for r in res), res
    codigos = sorted(r.status_code for r in res)
    assert codigos == [200] * (n - 1) + [201], codigos
    with bd.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM ventas.ventas WHERE id = :i"), {"i": vid}) == 1
        assert c.scalar(text("SELECT count(*) FROM inventario.movimientos_inventario WHERE tipo = 'venta'")) == 1
        assert c.scalar(text("SELECT count(*) FROM fiscal.documentos_fiscales WHERE venta_id = :i"), {"i": vid}) == 1
        assert c.scalar(text("SELECT cantidad FROM inventario.existencias WHERE producto_id = :p"), {"p": pid}) == D(
            "99"
        )
        assert c.scalar(text("SELECT count(*) FROM sync.outbox_eventos WHERE evento_tipo = 'venta.confirmada'")) == 1


def test_dos_cajas_venden_la_ultima_unidad_stock_menos_uno_y_alerta(bd):
    (pm1, pm2), pid = _montar(bd, stock="1", cajas=2)
    c1, c2 = _cliente(pm1, "111111"), _cliente(pm2, "222222")
    c1.abrir_turno("0")
    c2.abrir_turno("0")

    def vender(cli):
        def f(barrera):
            barrera.wait(timeout=60)
            return cli.vender([linea(pid)], [efectivo(10000)])

        return f

    res = _paralelo([vender(c1), vender(c2)])
    assert [r.status_code for r in res] == [201, 201], [getattr(r, "text", r) for r in res]
    with bd.connect() as c:
        assert c.scalar(text("SELECT cantidad FROM inventario.existencias WHERE producto_id = :p"), {"p": pid}) == D(
            "-1"
        )
        movs = (
            c.execute(
                text(
                    "SELECT saldo_cantidad FROM inventario.movimientos_inventario WHERE tipo = 'venta' ORDER BY secuencia"
                )
            )
            .scalars()
            .all()
        )
        assert movs == [D("0"), D("-1")]  # cadena consistente: la segunda vio el saldo de la primera
        assert (
            c.scalar(
                text("SELECT count(*) FROM inventario.alertas_stock WHERE producto_id = :p AND estado <> 'resuelta'"),
                {"p": pid},
            )
            == 1
        )
        assert (
            c.scalar(text("SELECT count(*) FROM sync.outbox_eventos WHERE evento_tipo = 'alerta_stock.stock_negativo'"))
            >= 1
        )
        # cada caja numera lo suyo, sin huecos
        assert c.scalar(text("SELECT count(DISTINCT caja_id) FROM ventas.ventas WHERE numero_interno = 1")) == 2


def test_cierre_y_venta_a_la_vez_no_dejan_ventas_fuera_del_arqueo(bd):
    for _ in range(3):
        _carrera_cierre(bd)


def _carrera_cierre(eng):
    (pm,), pid = _montar(eng, stock="1000")
    cajero = _cliente(pm, "111111")
    cajero.abrir_turno("50000")
    auth = cajero.autorizar("999999", "caja.cerrar_con_diferencia")  # el conteo no importa: solo la carrera
    ventas = 6

    def vender(barrera):
        cli = _cliente(pm, "111111")
        barrera.wait(timeout=60)
        return cli.vender([linea(pid)], [efectivo(10000)])

    def cerrar(barrera):
        barrera.wait(timeout=60)
        return cajero.post(
            "/pos/turnos/actual/cierre",
            json={"conteo": [{"medio_pago_codigo": "10", "valor_contado": "0"}], "autorizacion_id": auth},
        )

    res = _paralelo([vender] * ventas + [cerrar])
    assert all(not isinstance(r, BaseException) for r in res), res
    *rv, rc = res
    assert rc.status_code == 200, rc.text
    ok = [r for r in rv if r.status_code == 201]
    rechazadas = [r for r in rv if r.status_code != 201]
    assert all(r.status_code == 422 and r.json()["code"] == "sin_turno_abierto" for r in rechazadas), [
        r.text for r in rechazadas
    ]
    informe = rc.json()
    # todo lo que se confirmó quedó DENTRO del arqueo; nada se confirmó después del cierre
    assert informe["resumen"]["num_ventas"] == len(ok)
    with eng.connect() as c:
        assert c.scalar(
            text("SELECT count(*) FROM ventas.ventas WHERE estado = 'confirmada' AND caja_id = :c"), {"c": pm.caja}
        ) == len(ok)
        despues = c.scalar(
            text(
                "SELECT count(*) FROM ventas.ventas v JOIN cajas.turnos t ON t.id = v.turno_id"
                " WHERE v.estado = 'confirmada' AND v.caja_id = :c AND v.confirmada_at > t.cerrado_at"
            ),
            {"c": pm.caja},
        )
        assert despues == 0
