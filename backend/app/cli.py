"""CLI de administración: `python -m app.cli --help`.

Comandos: inicializar, crear-admin, nodos listar, datos-demo, inventario verificar, importar, fiscal.
Todos validan la configuración al arrancar (qué falta y cómo obtenerlo).

Orden de arranque de una instalación nueva:
  1. `inicializar` (empresa, sede y nodo EDGE; imprime NODO_ID) -> copiar NODO_ID a .env (MODE=edge);
  2. `crear-admin` (exige NODO_ID: el admin queda con origen en el edge);
  3. opcional, solo desarrollo: `datos-demo`.
`inicializar`, `nodos` y `datos-demo` no exigen NODO_ID (crean o listan los nodos). Todos los comandos usan los
MISMOS servicios que la API: publican sus eventos en el outbox y dejan su auditoría.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import NODO_NUBE_ID, ConfiguracionInvalida, get_settings, validar_configuracion
from app.core.db import cargar_modelos, sesion
from app.core.errores import ErrorDominio

# comandos que pueden correr antes de que exista el nodo de la sede
ARRANQUE = {"inicializar", "nodos", "datos-demo"}


def _error(msg: str, codigo: int = 1) -> int:
    print(msg, file=sys.stderr)
    return codigo


def crear_admin(args: argparse.Namespace) -> int:
    from app.modules.identidad import empleados as svc_emp
    from app.modules.organizacion.models import Nodo, Sede

    password = args.password or os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Contraseña del administrador: ")
    if (
        not args.password
        and not os.environ.get("ADMIN_PASSWORD")
        and password != getpass.getpass("Repita la contraseña: ")
    ):
        return _error("Las contraseñas no coinciden.")
    try:
        with sesion() as db:
            sedes = list(db.scalars(select(Sede.id).where(Sede.codigo.in_(args.sede)))) if args.sede else []
            if len(sedes) != len(args.sede):
                return _error("Alguna sede indicada no existe (use el código de sede).")
            if not sedes:  # por defecto, la sede del nodo edge de esta instalación
                nodo = db.get(Nodo, get_settings().nodo_id)
                if nodo is not None and nodo.sede_id is not None:
                    sedes = [nodo.sede_id]
            emp = svc_emp.crear(
                db,
                datos=dict(
                    tipo_documento_codigo=args.tipo_documento,
                    numero_documento=args.documento,
                    nombres=args.nombres,
                    apellidos=args.apellidos,
                    email=args.email,
                    usuario=args.usuario,
                ),
                password=password,
                roles=["administrador"],
                sedes=sedes,
                actor_id=None,
            )
            print(f"Administrador creado: {emp.usuario} ({emp.id})")
    except ErrorDominio as e:
        return _error(f"Error: {e.detail}")
    except Exception as e:  # noqa: BLE001
        return _error(f"No se pudo crear el administrador: {e}")
    return 0


def nodos_listar(args: argparse.Namespace) -> int:
    from app.modules.organizacion.nodos import listar_nodos

    cfg = get_settings()
    actual = cfg.nodo_id or (NODO_NUBE_ID if cfg.mode == "cloud" else None)
    with sesion() as db:
        filas = listar_nodos(db)
    print(f"{'NODO_ID':36}  {'tipo':5}  {'ean':3}  {'estado':8}  {'nombre':24}  sede")
    for n, sede in filas:
        marca = "  <- NODO_ID actual" if n.id == actual else ""
        print(f"{n.id!s:36}  {n.tipo:5}  {n.codigo_ean:3}  {n.estado:8}  {n.nombre:24}  {sede or '-'}{marca}")
    if actual is None:
        print("\nNODO_ID no está definido: copie en .env el id del nodo 'edge' de su sede.")
    return 0


def inicializar(args: argparse.Namespace) -> int:
    from app.modules.organizacion.servicios import inicializar as svc_inicializar

    try:
        with sesion() as db:
            r = svc_inicializar(
                db,
                nit=args.nit,
                dv=args.dv,
                razon_social=args.razon_social,
                nombre_comercial=args.nombre_comercial,
                sede_codigo=args.sede_codigo,
                sede_nombre=args.sede_nombre,
                municipio_codigo=args.municipio,
                direccion=args.direccion,
                nodo_nombre=args.nodo_nombre,
            )
    except ErrorDominio as e:
        return _error(f"Error: {e.detail}")
    print("Creado ahora: " + (", ".join(r.creados) if r.creados else "nada (ya existía todo)"))
    print(f"NODO_ID (nodo edge) = {r.nodo_edge_id}")
    print(f"sede_id             = {r.sede_id}")
    print("Copie NODO_ID en .env (y deje MODE=edge); después ejecute `crear-admin`.")
    return 0


def datos_demo(args: argparse.Namespace) -> int:
    from app.aplicacion.demo import EMPLEADOS_DEMO, sembrar

    try:
        with sesion() as db:
            r = sembrar(db, catalogo=args.catalogo)
    except ErrorDominio as e:
        return _error(f"Error: {e.detail}")
    print("Creado ahora: " + (", ".join(r.creados) if r.creados else "nada (ya existía todo)"))
    print(f"NODO_ID (nodo edge) = {r.nodo_edge_id}")
    print(f"caja_id             = {r.caja_id}")
    print(f"sede_id             = {r.sede_id}")
    print(f"bodega_id           = {r.bodega_id}  (averías: {r.bodega_averias_id})")
    actual = get_settings().nodo_id
    if actual is not None and actual != r.nodo_edge_id:
        print(f"AVISO: el NODO_ID de .env ({actual}) no es el de esta base de datos; actualícelo.")
    for e in EMPLEADOS_DEMO:
        acceso = f", usuario {e.usuario} / clave {e.password}" if e.usuario else ""
        print(f"{e.rol.capitalize()} demo: carné {e.carne}, PIN {e.pin}{acceso}")
    if r.catalogo is not None:
        c = r.catalogo
        print(
            f"Catálogo demo: {c.productos_nuevos} productos nuevos ({c.productos_existentes} ya existían); "
            f"{c.con_stock} con stock ({c.bajo_minimo} bajo el mínimo), {c.sin_stock} agotados"
        )
    print("Copie NODO_ID en .env (y deje MODE=edge) para usar este nodo en la API.")
    return 0


def inventario_verificar(args: argparse.Namespace) -> int:
    from app.modules.inventario.verificacion import verificar

    with sesion() as db:
        dif = verificar(db, reparar=args.reparar, actor_id=None)
    if not dif:
        print("Existencias consistentes con el kardex.")
        return 0
    print(f"{len(dif)} diferencia(s) entre la proyección y el kardex:")
    for d in dif:
        print(
            f"  bodega={d.bodega_id} producto={d.producto_id} proyección={d.cantidad_proyeccion} "
            f"kardex={d.cantidad_kardex} costo_proy={d.costo_proyeccion} costo_kardex={d.costo_kardex}"
        )
    if args.reparar:
        print("Reparadas.")
        return 0
    print("Use --reparar para corregirlas.")
    return 1


def importaciones_limpiar(args: argparse.Namespace) -> int:
    from app.modules.inventario import importacion as imp

    if args.dias < 0:
        return _error("--dias debe ser 0 o mayor.")
    with sesion() as db:
        n = imp.limpiar(db, args.dias)
    print(f"Importaciones sin confirmar con más de {args.dias} día(s) eliminadas: {n}")
    return 0


def importar(args: argparse.Namespace) -> int:
    from app.modules.inventario import importacion as imp

    ruta = Path(args.archivo)
    if not ruta.is_file():
        return _error(f"No existe el archivo: {ruta}")
    try:
        with sesion() as db:
            reg = imp.validar(db, ruta.name, ruta.read_bytes(), actor_id=None)
            r = reg.resumen
            print(f"Validación ({reg.tipo}): {r}")
            errores = [f for f in reg.reporte if f["estado"] == "error"]
            for f in errores[:50]:
                print(f"  fila {f['fila']}: {f['detalle']}")
            if len(errores) > 50:
                print(f"  ... y {len(errores) - 50} errores más")
            if errores:
                db.rollback()
                return _error("Hay filas con error: no se importó nada.")
            if not args.confirmar:
                db.rollback()
                print("Solo validación (nada escrito). Use --confirmar para aplicar.")
                return 0
            imp.confirmar(db, reg.id, actor_id=None)
            print("Importación aplicada.")
    except ErrorDominio as e:
        return _error(f"Error: {e.detail}")
    return 0


# ------------------------------------------------------------------------------------------------ fiscal
def _proveedor_factus():
    from app.modules.fiscal.proveedores import crear_proveedor
    from app.modules.fiscal.proveedores.factus import ProveedorFiscalFactus

    cfg = get_settings()
    cfg_f = cfg.model_copy(update={"fiscal_proveedor": "factus"})
    prov = crear_proveedor(cfg_f)
    assert isinstance(prov, ProveedorFiscalFactus)
    return prov


def fiscal_rangos(args: argparse.Namespace) -> int:
    """Rangos de numeración de la empresa en Factus (los `id` se guardan en `resoluciones_numeracion.id_rango_proveedor`)."""
    from app.modules.fiscal.proveedores.base import ErrorProveedor

    prov = _proveedor_factus()
    try:
        rangos = prov.listar_rangos()
    except ErrorProveedor as e:
        return _error(f"No se pudieron leer los rangos de Factus: {e.mensaje}")
    finally:
        prov.cerrar()
    print(f"{'id':>6}  {'documento':<28} {'prefijo':<8} {'desde':>12} {'hasta':>12} {'actual':>12}  activo")
    for r in rangos:
        print(
            f"{r.get('id')!s:>6}  {str(r.get('document'))[:28]:<28} {str(r.get('prefix')):<8} "
            f"{r.get('from')!s:>12} {r.get('to')!s:>12} {r.get('current')!s:>12}  "
            f"{'si' if r.get('is_active') in (1, True) else 'no'}"
        )
    return 0


def fiscal_verificar(args: argparse.Namespace) -> int:
    """Comprueba la conexión con Factus y que cada resolución activa apunte a un rango existente y activo."""
    from sqlalchemy import select as _select

    from app.modules.fiscal.models import ResolucionNumeracion
    from app.modules.fiscal.proveedores.base import ErrorProveedor

    prov = _proveedor_factus()
    try:
        rangos = {str(r.get("id")): r for r in prov.listar_rangos()}
    except ErrorProveedor as e:
        return _error(f"Sin conexión con Factus: {e.mensaje}")
    finally:
        prov.cerrar()
    print(f"Conexión con Factus correcta ({len(rangos)} rangos).")
    problemas = 0
    with sesion() as db:
        for r in db.scalars(_select(ResolucionNumeracion).where(ResolucionNumeracion.estado == "activa")):
            rango = rangos.get(str(r.id_rango_proveedor))
            if rango is None:
                estado = "SIN RANGO EN FACTUS" if r.id_rango_proveedor else "SIN id_rango_proveedor"
            elif rango.get("is_active") not in (1, True):
                estado = "RANGO INACTIVO EN FACTUS"
            else:
                estado = "ok"
            problemas += estado != "ok"
            print(
                f"  {r.tipo_documento_codigo} {r.prefijo:<6} resolución {r.id} -> rango {r.id_rango_proveedor}: {estado}"
            )
    return 1 if problemas else 0


def fiscal_vincular(args: argparse.Namespace) -> int:
    """Asigna a una resolución local el id de rango de Factus (verifica que el rango exista y sea del mismo tipo)."""
    import uuid as _uuid

    from app.modules.fiscal.models import ResolucionNumeracion
    from app.modules.fiscal.proveedores.base import ErrorProveedor

    prov = _proveedor_factus()
    try:
        rangos = {str(r.get("id")): r for r in prov.listar_rangos()}
    except ErrorProveedor as e:
        return _error(f"Sin conexión con Factus: {e.mensaje}")
    finally:
        prov.cerrar()
    rango = rangos.get(str(args.rango_id))
    if rango is None:
        return _error(f"El rango {args.rango_id} no existe en Factus (use `fiscal rangos`).")
    with sesion() as db:
        res = db.get(ResolucionNumeracion, _uuid.UUID(args.resolucion_id))
        if res is None:
            return _error("Resolución no encontrada.")
        res.id_rango_proveedor = str(args.rango_id)
        db.commit()
        print(
            f"Resolución {res.id} ({res.tipo_documento_codigo} {res.prefijo}) vinculada al rango {args.rango_id} de Factus."
        )
    return 0


def fiscal_estado(args: argparse.Namespace) -> int:
    """Documentos por atender, rechazados, alertas abiertas y latido del worker."""
    from sqlalchemy import func as _func

    from app.modules.fiscal import emision
    from app.modules.fiscal.models import AlertaFiscal, WorkerLatido

    with sesion() as db:
        c = emision.contadores(db)
        latido = db.get(WorkerLatido, "fiscal")
        abiertas = db.scalar(select(_func.count()).select_from(AlertaFiscal).where(AlertaFiscal.estado == "abierta"))
    print(f"Proveedor: {get_settings().fiscal_proveedor}")
    print(f"Pendientes: {c['pendientes']}  Rechazados: {c['rechazados']}  Alertas abiertas: {abiertas}")
    print(
        "Worker: " + (f"último latido {latido.ultimo_latido_at:%Y-%m-%d %H:%M:%S %Z}" if latido else "nunca ha corrido")
    )
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Administración de MundoRepuestos")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("inicializar", help="Crea empresa, sede y nodo EDGE con su configuración (idempotente)")
    p.add_argument("--nit", required=True, help="NIT sin dígito de verificación (el DV se calcula)")
    p.add_argument("--dv", type=int, help="Opcional: se valida contra el calculado")
    p.add_argument("--razon-social", required=True)
    p.add_argument("--nombre-comercial")
    p.add_argument("--sede-codigo", required=True, help="Código de la sede (2-6 caracteres A-Z/0-9)")
    p.add_argument("--sede-nombre", required=True)
    p.add_argument("--municipio", default="11001", help="Código DANE del municipio (por defecto Bogotá)")
    p.add_argument("--direccion", default="Sin dirección")
    p.add_argument("--nodo-nombre")
    p.set_defaults(func=inicializar)

    p = sub.add_parser("crear-admin", help="Crea el primer administrador (exige NODO_ID: tras `inicializar`)")
    p.add_argument("--usuario", required=True)
    p.add_argument("--documento", required=True, help="Número de documento")
    p.add_argument("--tipo-documento", default="13", help="Código DIAN (13 = cédula)")
    p.add_argument("--nombres", required=True)
    p.add_argument("--apellidos", required=True)
    p.add_argument("--email")
    p.add_argument("--sede", action="append", default=[], help="Código de sede (repetible)")
    p.add_argument("--password", help="Mejor omitir: se toma de ADMIN_PASSWORD o se pregunta sin eco")
    p.set_defaults(func=crear_admin)

    p = sub.add_parser("nodos", help="Gestión de nodos")
    ns = p.add_subparsers(dest="accion", required=True)
    q = ns.add_parser("listar", help="Lista los nodos y marca el NODO_ID actual")
    q.set_defaults(func=nodos_listar)

    p = sub.add_parser(
        "datos-demo",
        help="Siembra empresa, sede, nodo edge, bodega, caja, 3 empleados y 5 clientes (idempotente)",
    )
    p.add_argument("--catalogo", action="store_true", help="Carga además ~300 repuestos realistas con stock y precios")
    p.set_defaults(func=datos_demo)

    p = sub.add_parser("inventario", help="Herramientas de inventario")
    ns = p.add_subparsers(dest="accion", required=True)
    q = ns.add_parser("verificar", help="Recalcula las existencias desde el kardex y reporta diferencias")
    q.add_argument("--reparar", action="store_true", help="Corrige la proyección con lo que dice el kardex")
    q.set_defaults(func=inventario_verificar)

    p = sub.add_parser("importaciones", help="Mantenimiento de importaciones Excel")
    ns = p.add_subparsers(dest="accion", required=True)
    q = ns.add_parser("limpiar", help="Borra las importaciones validadas que nunca se confirmaron")
    q.add_argument("--dias", type=int, default=7, help="Antigüedad mínima en días (por defecto 7)")
    q.set_defaults(func=importaciones_limpiar)

    p = sub.add_parser("importar", help="Importa productos o compatibilidades desde Excel (valida; --confirmar aplica)")
    p.add_argument("archivo", help="Archivo .xlsx con la hoja 'productos' o 'compatibilidades'")
    p.add_argument("--confirmar", action="store_true", help="Aplica la importación si la validación no tiene errores")
    p.set_defaults(func=importar)

    p = sub.add_parser("fiscal", help="Facturación electrónica: rangos de Factus, verificación y estado")
    ns = p.add_subparsers(dest="accion", required=True)
    q = ns.add_parser("rangos", help="Lista los rangos de numeración de Factus (ids para las resoluciones)")
    q.set_defaults(func=fiscal_rangos)
    q = ns.add_parser("verificar", help="Prueba la conexión y que las resoluciones activas apunten a rangos válidos")
    q.set_defaults(func=fiscal_verificar)
    q = ns.add_parser("vincular", help="Asigna el id de rango de Factus a una resolución local")
    q.add_argument("resolucion_id", help="id (UUID) de fiscal.resoluciones_numeracion")
    q.add_argument("rango_id", help="id del rango en Factus (ver `fiscal rangos`)")
    q.set_defaults(func=fiscal_vincular)
    q = ns.add_parser("estado", help="Pendientes, rechazados, alertas y latido del worker")
    q.set_defaults(func=fiscal_estado)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()  # --help funciona aunque falte configuración
    args = parser.parse_args(argv)
    cargar_modelos()
    try:
        arranque = args.comando in ARRANQUE
        cfg = validar_configuracion(requiere_nodo=not arranque)
        if arranque and cfg.nodo_id is None:
            cfg.nodo_id = NODO_NUBE_ID  # solo para listar: `inicializar` y `datos-demo` fijan el nodo edge que crean
        elif not arranque:
            from app.modules.organizacion.nodos import verificar_nodo

            verificar_nodo()
        return args.func(args)
    except ConfiguracionInvalida as e:
        return _error(str(e), 2)


if __name__ == "__main__":
    raise SystemExit(main())
