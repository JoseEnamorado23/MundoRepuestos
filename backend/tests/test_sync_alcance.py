"""Alcance de los eventos del outbox: `fiscal.*` es local y el agente de sync no debe replicarlo."""

from __future__ import annotations

from sqlalchemy import text

from app.modules.sync.tipos_evento import LOCAL, SINCRONIZABLE, alcance_de


def test_registro_de_alcance():
    assert alcance_de("fiscal.emitir") == LOCAL
    assert alcance_de("fiscal.cualquier_cosa_futura") == LOCAL
    assert alcance_de("producto.creado") == SINCRONIZABLE
    assert alcance_de("documento_fiscal.aceptado") == SINCRONIZABLE  # no empieza por «fiscal.»


def test_publicar_evento_fija_el_alcance(conn, db):
    from tests.pos_helpers import construir_pos

    construir_pos(conn, db)
    from app.core.base import uuid7
    from app.modules.sync.servicios import publicar_evento

    a = publicar_evento(db, "x", uuid7(), "fiscal.emitir", {})
    b = publicar_evento(db, "x", uuid7(), "producto.creado", {})
    db.flush()
    assert (a.alcance, b.alcance) == (LOCAL, SINCRONIZABLE)


def test_ningun_evento_fiscal_es_sincronizable_y_el_defecto_de_la_bd(conn, db, client):
    from tests.pos_helpers import Cliente, construir_pos, efectivo, linea, producto

    pm = construir_pos(conn, db)
    pid = producto(conn, db, pm, "Pastillas", "10000", costo="4000")
    cajero = Cliente(client, pm, "111111")
    cajero.abrir_turno("50000")
    assert cajero.vender([linea(pid, "1")], [efectivo(11900)]).status_code == 201
    # tras una venta existe `fiscal.emitir` (y eventos de venta): el criterio de la BD y del registro coinciden
    mal = conn.execute(
        text("SELECT count(*) FROM sync.outbox_eventos WHERE (evento_tipo LIKE 'fiscal.%') <> (alcance = 'local')")
    ).scalar_one()
    assert mal == 0
    assert conn.execute(text("SELECT count(*) FROM sync.outbox_eventos WHERE alcance = 'local'")).scalar_one() >= 1
    defecto = conn.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'sync' AND table_name = 'outbox_eventos' AND column_name = 'alcance'"
        )
    ).scalar_one()
    assert "sincronizable" in defecto
