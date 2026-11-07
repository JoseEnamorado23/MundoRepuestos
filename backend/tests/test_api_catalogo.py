"""Catálogo por API: permisos, CRUD, códigos de barras, precios, imágenes, compatibilidades, búsqueda y outbox."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.modules.catalogo.utiles import digito_verificador, gs1_valido
from tests import api_helpers as h
from tests import factories as f

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def ean13(base12: str) -> str:
    return base12 + str(digito_verificador(base12))


@pytest.fixture
def mundo(conn, db):
    return h.construir_mundo(conn, db)


@pytest.fixture
def admin(client, mundo):
    return h.bearer(h.token_de(client, "admin"))


def post(client, url, hdr, **json):
    return client.post(f"{API}{url}", json=json, headers=hdr)


def crear_producto(client, admin, sku, nombre, cat_id, **extra):
    r = post(
        client, "/catalogo/productos", admin, sku=sku, nombre=nombre, categoria_id=cat_id, impuesto_id=f.IVA19, **extra
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def categoria(client, admin):
    r = post(client, "/catalogo/categorias", admin, nombre="Frenos")
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ------------------------------------------------------------------------------------ permisos
def test_permisos_403_401_y_lectura(client, mundo, admin, db, categoria):
    cajero = h.bearer(h.token_de(client, mundo.cajero.usuario))
    assert client.get(f"{API}/catalogo/categorias", headers=cajero).status_code == 200  # catalogo.ver
    assert post(client, "/catalogo/categorias", cajero, nombre="X").status_code == 403  # sin catalogo.editar
    assert post(client, "/catalogo/marcas", cajero, nombre="X").status_code == 403
    p = crear_producto(client, admin, "S1", "Producto uno", categoria)
    assert post(client, f"/catalogo/productos/{p['id']}/precios", cajero, precio="1000").status_code == 403
    bodeguero = h.crear_empleado(db, roles=["bodeguero"], sedes=[uuid.UUID(mundo.sede)])
    bod = h.bearer(h.token_de(client, bodeguero.usuario))
    assert (
        post(client, f"/catalogo/productos/{p['id']}/precios", bod, precio="1000").status_code == 403
    )  # sin precios.editar
    assert client.get(f"{API}/catalogo/categorias").status_code == 401
    r = post(client, "/catalogo/categorias", cajero, nombre="X")
    assert r.headers["content-type"].startswith("application/problem+json") and r.json()["code"] == "permiso_denegado"


def test_paginacion_filtros_y_orden(client, admin, categoria):
    for i in range(5):
        crear_producto(client, admin, f"P{i}", f"Producto {i}", categoria)
    r = client.get(f"{API}/catalogo/productos", params={"limit": 2, "offset": 0, "orden": "-sku"}, headers=admin).json()
    assert r["total"] == 5 and r["limit"] == 2 and [x["sku"] for x in r["items"]] == ["P4", "P3"]
    r2 = client.get(f"{API}/catalogo/productos", params={"limit": 2, "offset": 4, "orden": "sku"}, headers=admin).json()
    assert [x["sku"] for x in r2["items"]] == ["P4"]
    assert client.get(f"{API}/catalogo/productos", params={"q": "producto 3"}, headers=admin).json()["total"] == 1
    mala = client.get(f"{API}/catalogo/productos", params={"orden": "inexistente"}, headers=admin)
    assert mala.status_code == 422 and mala.json()["code"] == "orden_invalido"
    assert client.get(f"{API}/catalogo/productos", params={"limit": 500}, headers=admin).status_code == 422


# ------------------------------------------------------------------------------------ categorías
def test_categorias_arbol_y_ciclos(client, admin):
    a = post(client, "/catalogo/categorias", admin, nombre="A").json()["id"]
    b = post(client, "/catalogo/categorias", admin, nombre="B", parent_id=a).json()["id"]
    c = post(client, "/catalogo/categorias", admin, nombre="C", parent_id=b).json()["id"]
    arbol = client.get(f"{API}/catalogo/categorias/arbol", headers=admin).json()
    raiz = next(n for n in arbol if n["id"] == a)
    assert raiz["hijos"][0]["id"] == b and raiz["hijos"][0]["hijos"][0]["id"] == c
    for padre in (c, b, a):  # A bajo su descendiente, bajo sí misma
        r = client.patch(f"{API}/catalogo/categorias/{a}", json={"parent_id": padre}, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == "categoria_ciclo", padre
    ok = client.patch(f"{API}/catalogo/categorias/{c}", json={"parent_id": a}, headers=admin)  # mover sin ciclo
    assert ok.status_code == 200 and ok.json()["parent_id"] == a
    dup = post(client, "/catalogo/categorias", admin, nombre="a")  # mismo nivel, mismo nombre
    assert dup.status_code == 409


def test_marcas_y_vehiculos(client, admin):
    m = post(client, "/catalogo/marcas", admin, nombre="Bosch")
    assert m.status_code == 201 and m.json()["slug"] == "bosch"
    assert post(client, "/catalogo/marcas", admin, nombre="BOSCH").status_code == 409
    vm = post(client, "/catalogo/vehiculos/marcas", admin, nombre="Chevrolet").json()["id"]
    mod = post(client, "/catalogo/vehiculos/modelos", admin, marca_id=vm, nombre="Spark").json()["id"]
    v = post(
        client,
        "/catalogo/vehiculos/versiones",
        admin,
        modelo_id=mod,
        nombre="Spark GT",
        anio_desde=2016,
        anio_hasta=2020,
    )
    assert v.status_code == 201, v.text
    en_2018 = client.get(
        f"{API}/catalogo/vehiculos/versiones", params={"modelo_id": mod, "anio": 2018}, headers=admin
    ).json()
    en_2010 = client.get(
        f"{API}/catalogo/vehiculos/versiones", params={"modelo_id": mod, "anio": 2010}, headers=admin
    ).json()
    assert en_2018["total"] == 1 and en_2010["total"] == 0
    imp = client.get(f"{API}/catalogo/impuestos", headers=admin).json()
    assert any(i["codigo"].upper().startswith("IVA") for i in imp["items"])
    assert post(client, "/catalogo/impuestos", admin, codigo="X").status_code == 405  # solo lectura


# ------------------------------------------------------------------------------------ productos y códigos de barras
def test_codigo_de_barras_duplicado_409_y_validacion(client, admin, categoria):
    cod = ean13("770123456789")
    p1 = crear_producto(client, admin, "A1", "Uno", categoria, codigos_barras=[{"codigo": cod}])
    assert p1["codigos_barras"][0]["es_principal"] is True
    r = post(
        client,
        "/catalogo/productos",
        admin,
        sku="A2",
        nombre="Dos",
        categoria_id=categoria,
        impuesto_id=f.IVA19,
        codigos_barras=[{"codigo": cod}],
    )
    assert r.status_code == 409 and r.json()["code"] == "codigo_barras_duplicado"
    p2 = crear_producto(client, admin, "A2", "Dos", categoria)
    r = post(client, f"/catalogo/productos/{p2['id']}/codigos-barras", admin, codigo=cod)
    assert r.status_code == 409 and r.json()["code"] == "codigo_barras_duplicado"
    malo = post(
        client, f"/catalogo/productos/{p2['id']}/codigos-barras", admin, codigo="7701234567891"
    )  # dígito inválido
    assert malo.status_code == 422 and malo.json()["code"] == "codigo_invalido"
    sku = post(
        client, "/catalogo/productos", admin, sku="A1", nombre="Otro", categoria_id=categoria, impuesto_id=f.IVA19
    )
    assert sku.status_code == 409 and sku.json()["code"] == "sku_duplicado"


def test_generar_ean13_internos_validos_y_unicos(client, admin, categoria, conn):
    ids = [crear_producto(client, admin, f"G{i}", f"Gen {i}", categoria)["id"] for i in range(6)]
    r = post(client, "/catalogo/productos/codigos-barras/generar", admin, producto_ids=ids)
    assert r.status_code == 200, r.text
    codigos = [x["codigo"] for x in r.json()]
    assert len(codigos) == 6 and len(set(codigos)) == 6
    for c in codigos:
        assert len(c) == 13 and c.startswith("2") and gs1_valido(c, 13)
    assert post(client, "/catalogo/productos/codigos-barras/generar", admin, producto_ids=ids).json() == []  # ya tienen
    d = client.get(f"{API}/catalogo/productos/{ids[0]}", headers=admin).json()
    assert d["codigos_barras"][0]["tipo"] == "interno" and d["codigos_barras"][0]["es_principal"]
    n = conn.execute(
        text("SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'catalogo.codigos_generados'")
    ).scalar()
    assert n == 1


def test_activar_desactivar_y_referencias(client, admin, categoria):
    p = crear_producto(client, admin, "R1", "Con ref", categoria, publicado_web=True)
    ref = post(client, f"/catalogo/productos/{p['id']}/referencias", admin, tipo="oem", referencia="96 534-653")
    assert ref.status_code == 201 and ref.json()["referencia_normalizada"] == "96534653"
    assert (
        post(client, f"/catalogo/productos/{p['id']}/referencias", admin, tipo="oem", referencia="96534653").status_code
        == 409
    )
    d = post(client, f"/catalogo/productos/{p['id']}/desactivar", admin)
    assert d.status_code == 200 and d.json()["activo"] is False and d.json()["publicado_web"] is False
    assert client.get(f"{API}/catalogo/productos", headers=admin).json()["total"] == 0  # filtra activos por defecto
    assert post(client, f"/catalogo/productos/{p['id']}/activar", admin).json()["activo"] is True
    quitar = client.delete(f"{API}/catalogo/productos/{p['id']}/referencias/{ref.json()['id']}", headers=admin)
    assert quitar.status_code == 204
    assert client.get(f"{API}/catalogo/productos/{p['id']}", headers=admin).json()["referencias"] == []


# ------------------------------------------------------------------------------------ compatibilidades
def test_compatibilidades(client, admin, categoria):
    vm = post(client, "/catalogo/vehiculos/marcas", admin, nombre="Renault").json()["id"]
    mod = post(client, "/catalogo/vehiculos/modelos", admin, marca_id=vm, nombre="Logan").json()["id"]
    v1 = post(
        client,
        "/catalogo/vehiculos/versiones",
        admin,
        modelo_id=mod,
        nombre="Logan 1.6",
        anio_desde=2010,
        anio_hasta=2015,
    ).json()["id"]
    v2 = post(
        client, "/catalogo/vehiculos/versiones", admin, modelo_id=mod, nombre="Logan 1.6 II", anio_desde=2016
    ).json()["id"]
    p = crear_producto(client, admin, "C1", "Bujía", categoria)
    r = post(client, f"/catalogo/productos/{p['id']}/compatibilidades", admin, version_ids=[v1, v2])
    assert r.status_code == 201 and len(r.json()) == 2
    assert len(client.get(f"{API}/catalogo/productos/{p['id']}/compatibilidades", headers=admin).json()) == 2
    prods = client.get(f"{API}/catalogo/vehiculos/versiones/{v1}/productos", headers=admin).json()
    assert prods["total"] == 1 and prods["items"][0]["sku"] == "C1"
    assert client.delete(f"{API}/catalogo/productos/{p['id']}/compatibilidades/{v1}", headers=admin).status_code == 204
    assert client.get(f"{API}/catalogo/vehiculos/versiones/{v1}/productos", headers=admin).json()["total"] == 0
    assert client.delete(f"{API}/catalogo/productos/{p['id']}/compatibilidades/{v1}", headers=admin).status_code == 404
    assert (
        post(
            client, f"/catalogo/productos/{p['id']}/compatibilidades", admin, version_ids=[str(uuid.uuid4())]
        ).status_code
        == 422
    )


# ------------------------------------------------------------------------------------ precios
def test_fijar_precio_cierra_la_vigencia_anterior(client, admin, categoria):
    p = crear_producto(client, admin, "PR1", "Precio", categoria)["id"]
    assert client.get(f"{API}/catalogo/productos/{p}/precios/vigente", headers=admin).status_code == 404
    p1 = post(client, f"/catalogo/productos/{p}/precios", admin, precio="10000")
    p2 = post(client, f"/catalogo/productos/{p}/precios", admin, precio="12500.50", motivo="alza")
    assert p1.status_code == 201 and p2.status_code == 201, (p1.text, p2.text)
    hist = client.get(f"{API}/catalogo/productos/{p}/precios", headers=admin).json()
    assert hist["total"] == 2
    nuevo, viejo = hist["items"]  # más reciente primero
    assert viejo["vigente_hasta"] == nuevo["vigente_desde"] and nuevo["vigente_hasta"] is None
    vig = client.get(f"{API}/catalogo/productos/{p}/precios/vigente", headers=admin).json()
    assert vig["precio"] == "12500.5000"
    desde_v = datetime.fromisoformat(viejo["vigente_desde"])
    hasta_v = datetime.fromisoformat(viejo["vigente_hasta"])
    medio = (desde_v + (hasta_v - desde_v) / 2).isoformat()
    en_medio = client.get(f"{API}/catalogo/productos/{p}/precios/vigente", params={"en": medio}, headers=admin).json()
    assert en_medio["precio"] == "10000.0000"
    antes = (desde_v - timedelta(seconds=5)).isoformat()
    assert (
        client.get(f"{API}/catalogo/productos/{p}/precios/vigente", params={"en": antes}, headers=admin).status_code
        == 404
    )


def test_precio_por_sede_tiene_prioridad(client, admin, categoria, mundo):
    p = crear_producto(client, admin, "PR2", "Precio sede", categoria)["id"]
    post(client, f"/catalogo/productos/{p}/precios", admin, precio="5000")
    post(client, f"/catalogo/productos/{p}/precios", admin, precio="4000", sede_id=mundo.sede)
    base = client.get(f"{API}/catalogo/productos/{p}/precios/vigente", headers=admin).json()
    en_sede = client.get(
        f"{API}/catalogo/productos/{p}/precios/vigente", params={"sede_id": mundo.sede}, headers=admin
    ).json()
    otra = client.get(
        f"{API}/catalogo/productos/{p}/precios/vigente", params={"sede_id": mundo.sede2}, headers=admin
    ).json()
    assert base["precio"] == "5000.0000" and en_sede["precio"] == "4000.0000" and otra["precio"] == "5000.0000"
    assert post(client, f"/catalogo/productos/{p}/precios", admin, precio="-1").status_code == 422


# ------------------------------------------------------------------------------------ imágenes
def test_imagenes(client, admin, categoria, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "media_dir", str(tmp_path))
    p = crear_producto(client, admin, "IM1", "Con foto", categoria)["id"]
    url = f"{API}/catalogo/productos/{p}/imagenes"
    ok = client.post(
        url, files={"archivo": ("a.png", PNG, "image/png")}, data={"texto_alternativo": "frente"}, headers=admin
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["es_principal"] is True and ok.json()["orden"] == 0
    segunda = client.post(url, files={"archivo": ("b.png", PNG, "image/png")}, headers=admin).json()
    # el tipo se detecta por contenido, no por nombre ni Content-Type declarado
    falso = client.post(url, files={"archivo": ("x.png", b"<html>no soy imagen</html>", "image/png")}, headers=admin)
    assert falso.status_code == 422 and falso.json()["code"] == "imagen_tipo_invalido"
    monkeypatch.setattr(get_settings(), "imagen_max_mb", 1)
    grande = client.post(
        url, files={"archivo": ("g.png", PNG + b"\x00" * (1024 * 1024 + 1), "image/png")}, headers=admin
    )
    assert grande.status_code == 422 and grande.json()["code"] == "imagen_muy_grande"
    ordenadas = client.put(f"{url}/orden", json={"ids": [segunda["id"], ok.json()["id"]]}, headers=admin).json()
    assert [i["id"] for i in ordenadas] == [segunda["id"], ok.json()["id"]] and ordenadas[0]["es_principal"] is True
    assert client.put(f"{url}/orden", json={"ids": [segunda["id"]]}, headers=admin).status_code == 422
    archivo = client.get(ok.json()["url"].replace("/api/v1", API))
    assert archivo.status_code == 200 and archivo.content == PNG and archivo.headers["content-type"] == "image/png"
    assert client.get(f"{API}/catalogo/archivos/..%2F..%2F.env").status_code in (404, 422)
    assert client.delete(f"{url}/{segunda['id']}", headers=admin).status_code == 204
    assert [i["es_principal"] for i in client.get(url, headers=admin).json()] == [True]


# ------------------------------------------------------------------------------------ búsqueda
@pytest.fixture
def surtido(client, admin, categoria, mundo):
    """Spark 2016-2020 y 2010-2014; pastillas delanteras (Spark 2016-20), traseras (Spark 2010-14), filtro (ambas)."""
    vm = post(client, "/catalogo/vehiculos/marcas", admin, nombre="Chevrolet").json()["id"]
    mod = post(client, "/catalogo/vehiculos/modelos", admin, marca_id=vm, nombre="Spark").json()["id"]
    nuevo = post(
        client,
        "/catalogo/vehiculos/versiones",
        admin,
        modelo_id=mod,
        nombre="Spark GT",
        anio_desde=2016,
        anio_hasta=2020,
    ).json()["id"]
    viejo = post(
        client,
        "/catalogo/vehiculos/versiones",
        admin,
        modelo_id=mod,
        nombre="Spark Life",
        anio_desde=2010,
        anio_hasta=2014,
    ).json()["id"]
    bosch = post(client, "/catalogo/marcas", admin, nombre="Bosch").json()["id"]
    cod = ean13("770999000111")
    delant = crear_producto(
        client,
        admin,
        "PF-D",
        "Pastilla de freno delantera",
        categoria,
        marca_id=bosch,
        codigos_barras=[{"codigo": cod}],
        referencias=[{"tipo": "oem", "referencia": "96 534-653"}],
    )
    trasera = crear_producto(client, admin, "PF-T", "Pastilla de freno trasera", categoria, marca_id=bosch)
    filtro = crear_producto(client, admin, "FA-1", "Filtro de aceite", categoria)
    post(client, f"/catalogo/productos/{delant['id']}/compatibilidades", admin, version_ids=[nuevo])
    post(client, f"/catalogo/productos/{trasera['id']}/compatibilidades", admin, version_ids=[viejo])
    post(client, f"/catalogo/productos/{filtro['id']}/compatibilidades", admin, version_ids=[nuevo, viejo])
    for p in (delant, trasera, filtro):
        post(client, f"/catalogo/productos/{p['id']}/precios", admin, precio="25000")
    # stock en la sede del usuario: solo la pastilla delantera
    ent = post(
        client,
        "/inventario/entradas",
        admin,
        bodega_id=mundo.ent["bodega"],
        lineas=[{"producto_id": delant["id"], "cantidad": "7", "costo_unitario": "15000"}],
    )
    assert ent.status_code == 201, ent.text
    return dict(
        delant=delant,
        trasera=trasera,
        filtro=filtro,
        nuevo=nuevo,
        viejo=viejo,
        cod=cod,
        categoria=categoria,
        bosch=bosch,
    )


def buscar(client, hdr, q=None, **p):
    params = {k: v for k, v in {"q": q, **p}.items() if v is not None}
    r = client.get(f"{API}/catalogo/productos/buscar", params=params, headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


def test_busqueda_pastilla_freno_spark_2018(client, admin, surtido, mundo):
    r = buscar(client, admin, "pastilla freno spark 2018", sede_id=mundo.sede)
    skus = [x["sku"] for x in r["items"]]
    assert skus == ["PF-D"], skus  # solo la compatible con Spark en 2018
    item = r["items"][0]
    assert item["precio"] == "25000.0000" and item["stock_disponible"] == "7.000" and item["marca"] == "Bosch"
    skus_2012 = [x["sku"] for x in buscar(client, admin, "pastilla freno spark 2012", sede_id=mundo.sede)["items"]]
    assert skus_2012 == ["PF-T"]
    ambos = [x["sku"] for x in buscar(client, admin, "spark 2018", sede_id=mundo.sede)["items"]]
    assert sorted(ambos) == ["FA-1", "PF-D"]


def test_busqueda_por_referencia_con_o_sin_guiones(client, admin, surtido):
    for q in ("96534653", "96-534-653", "96 534-653", "96.534.653"):
        skus = [x["sku"] for x in buscar(client, admin, q)["items"]]
        assert "PF-D" in skus, q
    assert buscar(client, admin, "96534")["items"][0]["sku"] == "PF-D"  # prefijo de la referencia


def test_busqueda_por_codigo_sku_y_relevancia(client, admin, surtido):
    r = buscar(client, admin, surtido["cod"])
    assert [x["sku"] for x in r["items"]] == ["PF-D"] and r["items"][0]["relevancia"] >= 99
    assert buscar(client, admin, "pf-d")["items"][0]["sku"] == "PF-D"
    pastillas = buscar(client, admin, "pastilla")["items"]
    assert {x["sku"] for x in pastillas} == {"PF-D", "PF-T"}
    assert buscar(client, admin, "freno bosch")["total"] == 2
    assert buscar(client, admin, "pastillas")["total"] == 2  # plural: raíz 'spanish'


def test_busqueda_tolera_errores_de_digitacion(client, admin, surtido):
    for q in ("pastila freno", "pastilla frenno", "filtro de aseite", "pasitlla"):
        r = buscar(client, admin, q)
        assert r["total"] >= 1, q
    assert {x["sku"] for x in buscar(client, admin, "pastila freno")["items"]} == {"PF-D", "PF-T"}
    assert buscar(client, admin, "xyzqwerty")["total"] == 0


def test_busqueda_filtros(client, admin, surtido, mundo):
    con_stock = buscar(client, admin, "pastilla", solo_con_stock=True, sede_id=mundo.sede)
    assert [x["sku"] for x in con_stock["items"]] == ["PF-D"]
    sin_stock_otra_sede = buscar(client, admin, "pastilla", solo_con_stock=True, sede_id=mundo.sede2)
    assert sin_stock_otra_sede["total"] == 0
    por_version = buscar(client, admin, None, vehiculo_version_id=surtido["viejo"])
    assert {x["sku"] for x in por_version["items"]} == {"PF-T", "FA-1"}
    assert buscar(client, admin, None, marca_id=surtido["bosch"])["total"] == 2
    assert buscar(client, admin, None, categoria_id=surtido["categoria"])["total"] == 3
    pag = buscar(client, admin, None, limit=2, offset=2)
    assert pag["total"] == 3 and len(pag["items"]) == 1


def test_escaner_pos_por_codigo_y_sku(client, mundo, surtido, db):
    cajero = h.bearer(h.sesion_pos(client, mundo, "111111"))
    r = client.get(f"{API}/pos/productos/codigo/{surtido['cod']}", headers=cajero)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["sku"] == "PF-D" and d["precio"] == "25000.0000" and d["stock_disponible"] == "7.000"
    assert d["codigo_barras"] == surtido["cod"] and d["tarifa_pct"] and d["unidades_por_codigo"] == "1.000"
    assert client.get(f"{API}/pos/productos/codigo/PF-D", headers=cajero).json()["id"] == surtido["delant"]["id"]
    assert client.get(f"{API}/pos/productos/codigo/pf-d", headers=cajero).json()["id"] == surtido["delant"]["id"]
    nf = client.get(f"{API}/pos/productos/codigo/0000000000000", headers=cajero)
    assert nf.status_code == 404 and nf.json()["code"] == "producto_no_encontrado"
    assert client.get(f"{API}/pos/productos/codigo/PF-D").status_code == 401


# ------------------------------------------------------------------------------------ outbox
def test_toda_escritura_genera_su_evento_en_el_outbox(client, admin, categoria, conn, mundo):
    def eventos():
        return {r[0] for r in conn.execute(text("SELECT evento_tipo FROM sync.outbox_eventos"))}

    p = crear_producto(
        client,
        admin,
        "OB1",
        "Outbox",
        categoria,
        referencias=[{"tipo": "oem", "referencia": "X1"}],
        codigos_barras=[{"codigo": ean13("770111222333")}],
    )
    post(client, f"/catalogo/productos/{p['id']}/precios", admin, precio="1000")
    post(client, "/catalogo/marcas", admin, nombre="MarcaOB")
    client.patch(f"{API}/catalogo/productos/{p['id']}", json={"nombre": "Outbox 2"}, headers=admin)
    post(
        client,
        "/inventario/entradas",
        admin,
        bodega_id=mundo.ent["bodega"],
        lineas=[{"producto_id": p["id"], "cantidad": "2", "costo_unitario": "500"}],
    )
    esperados = {
        "categoria.creada", "producto.creado", "producto.actualizado", "precio.fijado", "marca.creada", "referencia.agregada",
        "codigo_barras.agregado", "movimiento_inventario.registrado", "entrada_mercancia.registrada",
    }  # fmt: skip
    assert esperados <= eventos(), esperados - eventos()
    fila = conn.execute(
        text(
            "SELECT version_agregado, payload->>'sku', estado, nodo_origen_id::text FROM sync.outbox_eventos WHERE evento_tipo = 'producto.creado'"
        )
    ).one()
    assert fila[1] == "OB1" and fila[2] == "pendiente" and fila[3] == f.NODO_NUBE


def test_busqueda_con_palabras_de_cuatro_letras_no_falla(client, admin, surtido, mundo):
    """Regresión: una palabra de 4 letras ('aire', 'seco') no debe tratarse como año."""
    r = client.get(
        f"{API}/catalogo/productos/buscar", params={"q": "filtro aire", "sede_id": mundo.sede}, headers=admin
    )
    assert r.status_code == 200, r.text
