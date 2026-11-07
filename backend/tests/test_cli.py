"""Puntos de entrada en un proceso APARTE (sin conftest ni app.models importado por las pruebas).

Detecta el fallo "FK no resuelta" que solo aparece cuando nadie más importó el registro de modelos.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import RAIZ_BACKEND, borrar_bd, config_alembic, crear_bd

BD_CLI = "mundorepuestos_test_cli"


def _correr(*args: str, url: str | None = None, extra_env: dict | None = None, entrada: str | None = None):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **(extra_env or {})}
    if url:
        env["DATABASE_URL"] = url
    return subprocess.run(
        [sys.executable, *args],
        cwd=RAIZ_BACKEND,
        env=env,
        input=entrada,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


@pytest.fixture(scope="module")
def url_cli(url_base):
    from alembic import command

    url = crear_bd(url_base, BD_CLI)
    command.upgrade(config_alembic(url), "head")
    yield url.render_as_string(hide_password=False)
    borrar_bd(url_base, BD_CLI)


def test_cli_ayuda_de_cada_comando():
    r = _correr("-m", "app.cli", "--help")
    assert r.returncode == 0, r.stderr
    assert "crear-admin" in r.stdout
    r = _correr("-m", "app.cli", "crear-admin", "--help")
    assert r.returncode == 0, r.stderr
    assert "--usuario" in r.stdout


def test_cli_crear_admin_en_proceso_aparte(url_cli):
    r = _correr(
        "-m",
        "app.cli",
        "crear-admin",
        "--usuario",
        "admin_cli",
        "--documento",
        "900111222",
        "--nombres",
        "Ana",
        "--apellidos",
        "Perez",
        url=url_cli,
        extra_env={"ADMIN_PASSWORD": "clave-de-prueba-123"},
    )
    assert r.returncode == 0, r.stderr
    assert "Administrador creado: admin_cli" in r.stdout
    assert "could not find table" not in r.stderr

    eng = create_engine(url_cli)
    with eng.connect() as c:
        n = c.scalar(
            text(
                "SELECT count(*) FROM identidad.empleados e "
                "JOIN identidad.empleados_roles er ON er.empleado_id = e.id "
                "JOIN identidad.roles r ON r.id = er.rol_id "
                "WHERE e.usuario = 'admin_cli' AND r.codigo = 'administrador'"
            )
        )
    eng.dispose()
    assert n == 1


def test_cli_crear_admin_duplicado_falla_con_mensaje(url_cli):
    args = ["-m", "app.cli", "crear-admin", "--usuario", "admin_cli", "--documento", "900111222"]
    args += ["--nombres", "Ana", "--apellidos", "Perez"]
    r = _correr(*args, url=url_cli, extra_env={"ADMIN_PASSWORD": "clave-de-prueba-123"})
    assert r.returncode == 1
    assert "Traceback" not in r.stderr


def test_registro_completo_de_modelos_al_importar_la_app():
    """app.main (API) y app.core.db.cargar_modelos (worker) dejan el metadata completo y resoluble."""
    codigo = (
        "from sqlalchemy.orm import configure_mappers; "
        "from app.core.base import Base; "
        "from app.core.db import cargar_modelos; "
        "cargar_modelos(); configure_mappers(); "
        "[t for t in Base.metadata.sorted_tables]; "
        "print(len(Base.metadata.tables))"
    )
    r = _correr("-c", codigo)
    assert r.returncode == 0, r.stderr
    assert int(r.stdout.strip()) >= 78

    r = _correr("-c", "import app.main, app.core.base as b; print(len(b.Base.metadata.tables))")
    assert r.returncode == 0, r.stderr
    assert int(r.stdout.strip()) >= 78


def test_alembic_en_proceso_aparte(url_cli):
    r = _correr("-m", "alembic", "current", url=url_cli)
    assert r.returncode == 0, r.stderr


# ------------------------------------------------------------------------------------ configuración
VACIAS = {"JWT_SECRET": "", "PIN_PEPPER": "", "NODO_ID": "", "MODE": "edge"}


def test_config_incompleta_dice_que_falta_y_como_obtenerlo(url_cli):
    r = _correr("-m", "app.cli", "nodos", "listar", url=url_cli, extra_env=VACIAS)
    assert r.returncode == 2
    assert "JWT_SECRET" in r.stderr and "secrets.token_urlsafe" in r.stderr and "PIN_PEPPER" in r.stderr
    assert "NODO_ID" not in r.stderr  # comando de arranque: no exige nodo
    r = _correr(
        "-m",
        "app.cli",
        "inventario",
        "verificar",
        url=url_cli,
        extra_env={**VACIAS, "JWT_SECRET": "x" * 40, "PIN_PEPPER": "p"},
    )
    assert r.returncode == 2 and "NODO_ID" in r.stderr and "nodos listar" in r.stderr
    corto = _correr("-m", "app.cli", "nodos", "listar", url=url_cli, extra_env={"JWT_SECRET": "corto"})
    assert corto.returncode == 2 and "demasiado corto" in corto.stderr
    # --help no necesita configuración
    assert _correr("-m", "app.cli", "--help", extra_env=VACIAS).returncode == 0
    assert _correr("-m", "app.cli", "datos-demo", "--help", extra_env=VACIAS).returncode == 0


def test_nodos_listar_marca_el_actual(url_cli):
    r = _correr("-m", "app.cli", "nodos", "listar", url=url_cli)
    assert r.returncode == 0, r.stderr
    assert "Nube" in r.stdout and "NODO_ID actual" in r.stdout


def test_datos_demo_idempotente_e_imprime_nodo_y_caja(url_cli):
    r = _correr("-m", "app.cli", "datos-demo", url=url_cli)
    assert r.returncode == 0, r.stderr
    m_nodo = re.search(r"NODO_ID \(nodo edge\) = ([0-9a-f-]{36})", r.stdout)
    m_caja = re.search(r"caja_id\s+= ([0-9a-f-]{36})", r.stdout)
    assert m_nodo and m_caja, r.stdout
    assert "empresa" in r.stdout and "cajero" in r.stdout and "PIN 123456" in r.stdout
    eng = create_engine(url_cli)
    with eng.connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM organizacion.nodos WHERE tipo = 'edge' AND id = :i"), {"i": m_nodo.group(1)}
            )
            == 1
        )
        sede = c.execute(
            text(
                "SELECT s.nombre, s.codigo FROM organizacion.sedes s JOIN organizacion.nodos n ON n.sede_id = s.id WHERE n.id = :i"
            ),
            {"i": m_nodo.group(1)},
        ).one()
        assert tuple(sede) == ("Principal", "PRIN")
        res = c.execute(
            text(
                "SELECT tipo_documento_codigo, modo_numeracion, estado FROM fiscal.resoluciones_numeracion"
                " WHERE caja_id = :c ORDER BY tipo_documento_codigo"
            ),
            {"c": m_caja.group(1)},
        ).all()
        assert [tuple(r) for r in res] == [("FE", "proveedor", "activa"), ("NC", "proveedor", "activa")]
        assert c.scalar(text("SELECT nombre FROM cajas.cajas WHERE id = :c"), {"c": m_caja.group(1)}) == "Caja 1"
        assert c.scalar(text("SELECT count(*) FROM inventario.bodegas")) == 2  # B01 + averías
        assert (
            c.scalar(text("SELECT count(*) FROM identidad.empleados_sedes WHERE pin_hash IS NOT NULL")) == 3
        )  # propietario, cajero, vendedor
        # etapa 1: el edge es dueño de los maestros -> todo nace con origen en el nodo edge, con su código EAN
        for tabla, filtro in (
            ("organizacion.empresas", "nit = '900000001'"),
            ("organizacion.sedes", "codigo = 'PRIN'"),
            ("organizacion.nodos", f"id = '{m_nodo.group(1)}'"),
            ("inventario.bodegas", "codigo = 'B01'"),
            ("cajas.cajas", "codigo = 'C1'"),
            ("identidad.empleados", "codigo_carne = 'CAJERO1'"),
            ("identidad.empleados", "codigo_carne = 'PROP1'"),
            ("identidad.empleados", "codigo_carne = 'VENDEDOR1'"),
        ):
            origen = c.scalar(text(f"SELECT nodo_origen_id::text FROM {tabla} WHERE {filtro}"))
            assert origen == m_nodo.group(1), (tabla, origen)
        assert c.scalar(text("SELECT codigo_ean FROM organizacion.nodos WHERE id = :i"), {"i": m_nodo.group(1)}) == "01"
    eng.dispose()
    segunda = _correr("-m", "app.cli", "datos-demo", url=url_cli)
    assert segunda.returncode == 0 and "nada (ya existía todo)" in segunda.stdout
    assert m_nodo.group(1) in segunda.stdout and m_caja.group(1) in segunda.stdout  # mismos ids
    eng = create_engine(url_cli)
    with eng.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM organizacion.empresas WHERE nit = '900000001'")) == 1
        assert c.scalar(text("SELECT count(*) FROM fiscal.resoluciones_numeracion")) == 2
        assert c.scalar(text("SELECT count(*) FROM organizacion.nodos WHERE tipo = 'edge'")) == 1
        assert c.scalar(text("SELECT count(*) FROM identidad.empleados WHERE codigo_carne = 'CAJERO1'")) == 1
    eng.dispose()
    # el nodo edge sembrado sirve como NODO_ID de una instalación MODE=edge
    edge = {"NODO_ID": m_nodo.group(1), "MODE": "edge"}
    r = _correr("-m", "app.cli", "inventario", "verificar", url=url_cli, extra_env=edge)
    assert r.returncode == 0 and "consistentes" in r.stdout, (r.stdout, r.stderr)
    # un NODO_ID que no existe en organizacion.nodos se rechaza con mensaje claro
    malo = _correr(
        "-m",
        "app.cli",
        "inventario",
        "verificar",
        url=url_cli,
        extra_env={"NODO_ID": "00000000-0000-7000-8000-0000000000ff", "MODE": "edge"},
    )
    assert malo.returncode == 2 and "no existe" in malo.stderr and "nodos listar" in malo.stderr
    # MODE incoherente con el tipo del nodo
    incoherente = _correr(
        "-m", "app.cli", "inventario", "verificar", url=url_cli, extra_env={"NODO_ID": m_nodo.group(1), "MODE": "cloud"}
    )
    assert incoherente.returncode == 2 and "MODE" in incoherente.stderr


def test_datos_demo_bloqueado_en_produccion(url_cli):
    r = _correr("-m", "app.cli", "datos-demo", url=url_cli, extra_env={"ENV": "produccion"})
    assert r.returncode == 1 and "produccion" in r.stderr


def test_importar_por_cli_valida_y_confirma(url_cli, tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "productos"
    ws.append(["sku", "nombre", "categoria", "impuesto", "precio_venta", "stock_inicial", "bodega", "costo"])
    ws.append(["CLI-1", "Producto CLI", "Varios", "IVA19", 5000, 4, "B01", 2000])
    ruta = tmp_path / "lote.xlsx"
    wb.save(ruta)
    nodo = _correr("-m", "app.cli", "nodos", "listar", url=url_cli)
    edge_id = re.search(r"([0-9a-f-]{36})\s+edge", nodo.stdout).group(1)
    env = {"NODO_ID": edge_id, "MODE": "edge"}
    solo = _correr("-m", "app.cli", "importar", str(ruta), url=url_cli, extra_env=env)
    assert solo.returncode == 0 and "Solo validación" in solo.stdout, (solo.stdout, solo.stderr)
    eng = create_engine(url_cli)
    with eng.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM catalogo.productos WHERE sku = 'CLI-1'")) == 0
    # `importaciones limpiar` purga los registros locales sin confirmar con más de N días (la validación por CLI hace
    # rollback, así que se siembra uno viejo y uno reciente por SQL)
    with eng.begin() as c:
        for dias in (10, 1):
            c.execute(
                text(
                    "INSERT INTO inventario.importaciones (id, tipo, estado, nombre_archivo, sha256, resumen, reporte, datos, "
                    "nodo_origen_id, created_at) VALUES (gen_random_uuid(), 'productos', 'validada', 'x.xlsx', '0', "
                    "'{}', '[]', '[]', '00000000-0000-7000-8000-000000000001', now() - make_interval(days => :d))"
                ),
                {"d": dias},
            )
    limpia = _correr("-m", "app.cli", "importaciones", "limpiar", "--dias", "7", url=url_cli, extra_env=env)
    assert limpia.returncode == 0 and "eliminadas: 1" in limpia.stdout, (limpia.stdout, limpia.stderr)
    otra_vez = _correr("-m", "app.cli", "importaciones", "limpiar", url=url_cli, extra_env=env)
    assert "eliminadas: 0" in otra_vez.stdout
    ok = _correr("-m", "app.cli", "importar", str(ruta), "--confirmar", url=url_cli, extra_env=env)
    assert ok.returncode == 0 and "Importación aplicada" in ok.stdout, (ok.stdout, ok.stderr)
    with eng.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT cantidad FROM inventario.existencias e JOIN catalogo.productos p ON p.id = e.producto_id WHERE p.sku = 'CLI-1'"
                )
            )
            == 4
        )
    eng.dispose()
    otra = _correr("-m", "app.cli", "importar", str(ruta), "--confirmar", url=url_cli, extra_env=env)  # idempotente
    assert otra.returncode == 0
    inexistente = _correr("-m", "app.cli", "importar", str(tmp_path / "no.xlsx"), url=url_cli, extra_env=env)
    assert inexistente.returncode == 1
    for cmd in (
        ("importaciones", "limpiar", "--help"),
        ("inventario", "verificar", "--help"),
        ("importar", "--help"),
        ("nodos", "listar", "--help"),
    ):
        assert _correr("-m", "app.cli", *cmd).returncode == 0


def test_datos_demo_genera_eventos_outbox_y_auditoria(url_cli):
    """A2: el CLI usa los mismos servicios que la API, así que deja eventos de sync y auditoría."""
    r = _correr("-m", "app.cli", "datos-demo", url=url_cli)
    assert r.returncode == 0, r.stderr
    eng = create_engine(url_cli)
    with eng.connect() as c:
        tipos = {x[0] for x in c.execute(text("SELECT DISTINCT evento_tipo FROM sync.outbox_eventos"))}
        for esperado in ("empresa.creada", "sede.creada", "nodo.creado", "configuracion_sede.sembrada", "caja.creada"):
            assert esperado in tipos, tipos
        assert (
            c.scalar(text("SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'organizacion.inicializar'")) >= 1
        )
    eng.dispose()


def test_inicializar_idempotente_y_siembra_configuracion(url_cli):
    args = ["-m", "app.cli", "inicializar", "--nit", "900000017", "--razon-social", "Taller Uno SAS"]
    args += ["--sede-codigo", "S1", "--sede-nombre", "Sede Uno"]
    a = _correr(*args, url=url_cli)
    assert a.returncode == 0, a.stderr
    m = re.search(r"NODO_ID[^=]*=\s*([0-9a-f-]{36})", a.stdout)
    assert m, a.stdout
    b = _correr(*args, url=url_cli)
    assert b.returncode == 0 and m.group(1) in b.stdout
    eng = create_engine(url_cli)
    with eng.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM organizacion.empresas WHERE nit = '900000017'")) == 1
        claves = {
            x[0]
            for x in c.execute(
                text(
                    "SELECT clave FROM organizacion.configuracion_sede cs JOIN organizacion.sedes s ON s.id = cs.sede_id"
                    " WHERE s.codigo = 'S1'"
                )
            )
        }
        assert {
            "autorizacion.retiro_caja",
            "autorizacion.devolucion",
            "autorizacion.diferencia_arqueo",
            "ventas.descuento_max_pct_por_rol",
            "ventas.espera_expira_horas",
        } <= claves
    eng.dispose()
