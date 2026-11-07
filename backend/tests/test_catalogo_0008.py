"""Migración 0008: EAN-13 determinístico por nodo, alias y selector de vehículos, búsqueda aproximada KNN, limpieza."""

from __future__ import annotations

import threading
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.catalogo import busqueda
from app.modules.catalogo import servicios as cat
from app.modules.catalogo.utiles import ean13_interno, gs1_valido
from app.modules.inventario import importacion
from app.modules.organizacion.nodos import siguiente_codigo_ean
from tests import api_helpers as h
from tests import factories as f
from tests.conftest import borrar_bd, config_alembic, crear_bd
from tests.test_api_catalogo import (  # noqa: F401  (fixtures compartidas)
    API,
    admin,
    buscar,
    categoria,
    crear_producto,
    mundo,
    post,
    surtido,
)


# ------------------------------------------------------------------------------------ EAN-13 por nodo
def test_ean13_interno_formato_y_digito_verificador():
    c = ean13_interno("07", 123)
    assert c[0] == "2" and c[1:3] == "07" and c[3:12] == "000000123" and len(c) == 13 and gs1_valido(c, 13)
    with pytest.raises(ValueError):
        ean13_interno("7", 1)
    with pytest.raises(ValueError):
        ean13_interno("00", 0)
    with pytest.raises(ValueError):
        ean13_interno("00", 1_000_000_000)


def test_ean_consecutivo_por_nodo_sin_huecos_y_unico_entre_nodos(client, admin, categoria, conn, db, monkeypatch):
    ids = [crear_producto(client, admin, f"E{i}", f"Ean {i}", categoria)["id"] for i in range(3)]
    r = post(client, "/catalogo/productos/codigos-barras/generar", admin, producto_ids=ids)
    codigos = sorted(x["codigo"] for x in r.json())
    assert [c[:3] for c in codigos] == ["200"] * 3  # nodo nube = 00
    assert [c[3:12] for c in codigos] == ["000000001", "000000002", "000000003"]
    assert all(gs1_valido(c, 13) for c in codigos)

    # una transacción revertida NO deja huecos: el consecutivo vuelve atrás con ella
    sp = db.begin_nested()
    assert cat._siguiente_ean_interno(db, "00")[3:12] == "000000004"
    sp.rollback()
    assert cat._siguiente_ean_interno(db, "00")[3:12] == "000000004"

    # segundo nodo (edge '01'): contador propio, mismos consecutivos, códigos distintos
    sede = f.sede(conn)
    nodo2 = f.insertar(conn, "organizacion.nodos", tipo="edge", sede_id=sede, nombre="Edge 2", codigo_ean="01")
    assert siguiente_codigo_ean(db) == "02"
    monkeypatch.setattr(get_settings(), "nodo_id", uuid.UUID(nodo2))
    assert cat.codigo_ean_del_nodo(db) == "01"
    c2 = cat._siguiente_ean_interno(db, "01")
    assert c2[:3] == "201" and c2[3:12] == "000000001" and gs1_valido(c2, 13)
    assert c2 not in codigos


def test_codigo_ean_de_nodo_es_unico_y_de_dos_digitos(conn):
    sede = f.sede(conn)
    with pytest.raises(DBAPIError), conn.begin_nested():  # '00' ya es de la nube
        f.insertar(conn, "organizacion.nodos", tipo="edge", sede_id=sede, nombre="Dup", codigo_ean="00")
    for malo in ("1", "abc", "123"):
        with pytest.raises(DBAPIError), conn.begin_nested():
            f.insertar(conn, "organizacion.nodos", tipo="edge", sede_id=sede, nombre="Mal", codigo_ean=malo)


def test_20_generaciones_concurrentes_no_duplican(url_base):
    nombre = "mundorepuestos_test_conc_ean"
    url = crear_bd(url_base, nombre)
    try:
        command.upgrade(config_alembic(url), "head")
        eng = create_engine(url, pool_size=20, max_overflow=0)
        barrera = threading.Barrier(20)
        codigos: list[str] = []
        errores: list[BaseException] = []

        def trabajo() -> None:
            try:
                with Session(eng) as db:
                    barrera.wait(timeout=30)
                    c = cat._siguiente_ean_interno(db, cat.codigo_ean_del_nodo(db))
                    db.commit()  # el UPDATE del contador retiene el candado hasta aquí
                    codigos.append(c)
            except BaseException as e:  # noqa: BLE001
                errores.append(e)

        hilos = [threading.Thread(target=trabajo) for _ in range(20)]
        for t in hilos:
            t.start()
        for t in hilos:
            t.join(timeout=60)
        assert not errores, errores
        assert len(codigos) == len(set(codigos)) == 20
        assert sorted(int(c[3:12]) for c in codigos) == list(range(1, 21))  # sin duplicados ni huecos
        assert all(gs1_valido(c, 13) for c in codigos)
        eng.dispose()
    finally:
        borrar_bd(url_base, nombre)


# ------------------------------------------------------------------------------------ alias y selector
def _ids(client, admin):
    marca = next(
        m
        for m in client.get(f"{API}/catalogo/vehiculos/marcas", headers=admin).json()["items"]
        if m["nombre"] == "Chevrolet"
    )
    modelos = client.get(f"{API}/catalogo/vehiculos/marcas/{marca['id']}/modelos", headers=admin).json()
    return marca["id"], next(m["id"] for m in modelos if m["nombre"] == "Spark")


def test_alias_crud_permisos_y_unicidad(client, admin, surtido, mundo):
    marca, modelo = _ids(client, admin)
    ok = post(client, "/catalogo/vehiculos/alias", admin, alias="Chévy", marca_id=marca)
    assert ok.status_code == 201, ok.text
    assert ok.json()["alias_normalizado"] == "chevy"  # minúsculas y sin tildes
    assert post(client, "/catalogo/vehiculos/alias", admin, alias="CHEVY", modelo_id=modelo).status_code == 409
    assert post(client, "/catalogo/vehiculos/alias", admin, alias="x", marca_id=marca).status_code == 422
    assert post(client, "/catalogo/vehiculos/alias", admin, alias="sin destino").status_code == 422
    assert (
        post(client, "/catalogo/vehiculos/alias", admin, alias="dos", marca_id=marca, modelo_id=modelo).status_code
        == 422
    )
    cajero = h.bearer(h.token_de(client, mundo.cajero.usuario))
    assert post(client, "/catalogo/vehiculos/alias", cajero, alias="otro", marca_id=marca).status_code == 403
    lista = client.get(f"{API}/catalogo/vehiculos/alias", params={"q": "CHÉV"}, headers=cajero).json()
    assert lista["total"] == 1
    # desactivar libera el nombre
    assert (
        client.patch(
            f"{API}/catalogo/vehiculos/alias/{ok.json()['id']}", json={"activo": False}, headers=admin
        ).status_code
        == 200
    )
    assert post(client, "/catalogo/vehiculos/alias", admin, alias="chevy", modelo_id=modelo).status_code == 201


def test_busqueda_con_alias_chevy_spark_2018_pastillas_y_spark_gt_freno(client, admin, surtido, mundo):
    marca, modelo = _ids(client, admin)
    for alias, destino in (
        ("chevy", {"marca_id": marca}),
        ("spark gt", {"modelo_id": modelo}),
        ("spark life", {"modelo_id": modelo}),
    ):
        assert post(client, "/catalogo/vehiculos/alias", admin, alias=alias, **destino).status_code == 201
    r = buscar(client, admin, "chevy spark 2018 pastillas", sede_id=mundo.sede)
    assert [x["sku"] for x in r["items"]] == ["PF-D"]  # Spark 2018 -> solo la delantera (2016-2020)
    assert r["busqueda_aproximada_incompleta"] is False
    r = buscar(client, admin, "spark gt freno", sede_id=mundo.sede)
    # el alias 'spark gt' apunta al modelo Spark; todos los productos de la categoría Frenos compatibles con él (el filtro
    # de aceite también está en esa categoría y es compatible con ambas versiones)
    assert {x["sku"] for x in r["items"]} == {"PF-D", "PF-T", "FA-1"}
    r = buscar(client, admin, "Chévy SPARK 2012 pastillas", sede_id=mundo.sede)  # mayúsculas y tildes no importan
    assert [x["sku"] for x in r["items"]] == ["PF-T"]


def test_busqueda_tolera_marca_de_vehiculo_mal_escrita(client, admin, surtido, mundo):
    r = buscar(client, admin, "chevrolt spark 2018 pastillas", sede_id=mundo.sede)
    assert [x["sku"] for x in r["items"]] == ["PF-D"]


def test_selector_marca_modelo_anio_version(client, admin, surtido, mundo):
    marca, modelo = _ids(client, admin)
    marcas = client.get(f"{API}/catalogo/vehiculos/marcas", headers=admin).json()["items"]
    assert "Chevrolet" in [m["nombre"] for m in marcas]
    modelos = client.get(f"{API}/catalogo/vehiculos/marcas/{marca}/modelos", headers=admin).json()
    assert [m["nombre"] for m in modelos] == ["Spark"]
    anios = client.get(f"{API}/catalogo/vehiculos/modelos/{modelo}/anios", headers=admin).json()
    assert anios["anios"] == [2020, 2019, 2018, 2017, 2016, 2014, 2013, 2012, 2011, 2010]  # 2015 no tiene versión
    v = client.get(
        f"{API}/catalogo/vehiculos/versiones", params={"modelo_id": modelo, "anio": 2018}, headers=admin
    ).json()
    assert (
        [x["nombre"] for x in v["items"]] == ["Spark GT"]
        and "motor" in v["items"][0]
        and "cilindraje_cc" in v["items"][0]
    )
    # esa versión alimenta el filtro vehiculo_version_id de la búsqueda
    r = buscar(client, admin, "freno", vehiculo_version_id=v["items"][0]["id"], sede_id=mundo.sede)
    assert {x["sku"] for x in r["items"]} == {"PF-D", "FA-1"}  # FA-1 está en la categoría Frenos y es compatible
    assert client.get(f"{API}/catalogo/vehiculos/marcas/{uuid.uuid4()}/modelos", headers=admin).status_code == 404
    assert client.get(f"{API}/catalogo/vehiculos/modelos/{uuid.uuid4()}/anios", headers=admin).status_code == 404


# ------------------------------------------------------------------------------------ búsqueda aproximada
def test_busqueda_aproximada_usa_knn_y_respeta_limite_y_umbral(client, admin, surtido, mundo, monkeypatch):
    cfg = get_settings()
    r = buscar(client, admin, "pastilal freno", sede_id=mundo.sede)  # letras cambiadas
    assert {x["sku"] for x in r["items"]} >= {"PF-D", "PF-T"} and r["busqueda_aproximada_incompleta"] is False
    monkeypatch.setattr(cfg, "busqueda_difusa_limite", 1)
    assert len(buscar(client, admin, "pastilal freno", sede_id=mundo.sede)["items"]) == 1  # n configurable
    monkeypatch.setattr(cfg, "busqueda_difusa_limite", 20)
    monkeypatch.setattr(cfg, "busqueda_difusa_umbral", 1.0)  # umbral en configuración: nada es "casi igual"
    assert buscar(client, admin, "pastilal freno", sede_id=mundo.sede)["items"] == []


def test_busqueda_aproximada_agotada_devuelve_vacio_con_flag_no_500(client, admin, surtido, mundo, monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "busqueda_difusa_timeout_ms", 50)
    original = busqueda._ejecutar

    def lenta(db, candidatos_sql, *a, **kw):
        if "<<->" in candidatos_sql:  # solo la consulta aproximada
            db.execute(text("SELECT pg_sleep(2)"))
        return original(db, candidatos_sql, *a, **kw)

    monkeypatch.setattr(busqueda, "_ejecutar", lenta)
    r = client.get(
        f"{API}/catalogo/productos/buscar", params={"q": "pastilal freno", "sede_id": mundo.sede}, headers=admin
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == [] and r.json()["total"] == 0 and r.json()["busqueda_aproximada_incompleta"] is True
    # la transacción sigue utilizable y el timeout NO se quedó puesto
    monkeypatch.setattr(busqueda, "_ejecutar", original)
    ok = buscar(client, admin, "pastilal freno", sede_id=mundo.sede)
    assert ok["items"] and ok["busqueda_aproximada_incompleta"] is False


# ------------------------------------------------------------------------------------ importaciones locales
def test_importaciones_sin_confirmar_se_limpian_y_estan_marcadas_como_locales(conn, db):
    def fila(estado, dias):
        return f.insertar(
            conn,
            "inventario.importaciones",
            tipo="productos",
            estado=estado,
            nombre_archivo=f"{estado}-{dias}.xlsx",
            sha256="0" * 64,
            resumen={},
            reporte=[],
            datos=[],
        )

    ids = {}
    for estado, dias in (("validada", 10), ("descartada", 9), ("confirmada", 30), ("validada", 1)):
        i = fila(estado, dias)
        conn.execute(
            text("UPDATE inventario.importaciones SET created_at = now() - make_interval(days => :d) WHERE id = :i"),
            {"d": dias, "i": i},
        )
        ids[(estado, dias)] = i
    assert importacion.limpiar(db, 7) == 2  # validada de 10 días y descartada de 9
    restantes = {r for (r,) in conn.execute(text("SELECT id::text FROM inventario.importaciones"))}
    assert restantes == {ids[("confirmada", 30)], ids[("validada", 1)]}
    assert importacion.limpiar(db, 7) == 0
    for tabla in ("inventario.importaciones", "catalogo.contadores_ean"):
        c = conn.execute(text("SELECT obj_description(CAST(:t AS regclass), 'pg_class')"), {"t": tabla}).scalar_one()
        assert c.startswith("LOCAL del nodo: no se sincroniza")
