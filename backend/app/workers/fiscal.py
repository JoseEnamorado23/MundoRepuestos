"""Worker fiscal: `uv run python -m app.workers.fiscal [--una-vez]`.

Procesa los eventos `fiscal.emitir` del outbox (ver `app/modules/fiscal/emision.py`): cada documento en su propia
transacción con `FOR UPDATE SKIP LOCKED`, así que se pueden correr varios workers a la vez sin duplicar envíos.
Cada ciclo anota su latido en `fiscal.worker_latidos` (lo lee `GET /api/v1/health`).

  --una-vez       procesa todo lo elegible y termina (cron, pruebas, demo)
  --intervalo S   segundos de espera entre ciclos cuando no hay nada que hacer (por defecto FISCAL_WORKER_INTERVALO_SEG)
"""

from __future__ import annotations

import argparse
import logging
import random
import signal
import sys
import threading
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from app import __version__
from app.core.almacenamiento import Almacenamiento, get_almacenamiento
from app.core.config import ConfiguracionInvalida, Settings, validar_configuracion
from app.core.db import cargar_modelos, get_sessionmaker
from app.core.logs import configurar_logging
from app.modules.fiscal import emision
from app.modules.fiscal.models import WorkerLatido
from app.modules.fiscal.proveedores import crear_proveedor
from app.modules.fiscal.proveedores.base import ProveedorFiscal

log = logging.getLogger("fiscal.worker")
NOMBRE = "fiscal"
MAX_POR_CICLO = 50  # tope de documentos por ciclo: así el latido se actualiza aunque haya una avalancha


def _latido(error: str | None = None, *, ciclo: bool = False, procesados: int = 0) -> None:
    """Anota que el worker está vivo (transacción propia: sobrevive al rollback del documento que falló)."""
    with get_sessionmaker()() as s, s.begin():
        valores = dict(
            nombre=NOMBRE,
            ultimo_latido_at=datetime.now(UTC),
            ultimo_error=(error or None),
            version_app=__version__,
            ciclos=1 if ciclo else 0,
            procesados=procesados,
            ultimo_ciclo_at=datetime.now(UTC) if ciclo else None,
        )
        ins = insert(WorkerLatido).values(**valores)
        set_ = dict(
            ultimo_latido_at=ins.excluded.ultimo_latido_at,
            ultimo_error=ins.excluded.ultimo_error,
            version_app=ins.excluded.version_app,
            ciclos=WorkerLatido.ciclos + valores["ciclos"],
            procesados=WorkerLatido.procesados + procesados,
        )
        if ciclo:
            set_["ultimo_ciclo_at"] = ins.excluded.ultimo_ciclo_at
        s.execute(ins.on_conflict_do_update(index_elements=[WorkerLatido.nombre], set_=set_))


def ejecutar_ciclo(
    proveedor: ProveedorFiscal,
    cfg: Settings,
    almacen: Almacenamiento,
    *,
    rng: random.Random | None = None,
    maximo: int = MAX_POR_CICLO,
) -> list[emision.Resultado]:
    """Procesa documentos hasta vaciar lo elegible (o `maximo`). Cada uno en su transacción: si uno falla por la BD,
    se revierte solo ese y el ciclo continúa con el siguiente en el siguiente ciclo."""
    hechos: list[emision.Resultado] = []
    Sesion = get_sessionmaker()
    for _ in range(maximo):
        with Sesion() as s:
            try:
                r = emision.procesar_siguiente(s, proveedor, cfg, almacen, rng=rng)
                if r is None:
                    s.rollback()
                    break
                s.commit()
            except Exception:
                s.rollback()
                raise
        hechos.append(r)
        log.info("documento procesado", extra={"documento_id": str(r.documento_id), "resultado": r.accion})
    with Sesion() as s:
        try:
            emision.completar_archivos(s, proveedor, almacen)
            s.commit()
        except Exception:  # un PDF que no baja no debe tumbar el ciclo
            s.rollback()
            log.exception("no se pudieron completar los archivos pendientes")
    return hechos


def correr(*, una_vez: bool, intervalo: float | None, parar: threading.Event | None = None) -> int:
    cfg = validar_configuracion()
    cargar_modelos()
    parar = parar or threading.Event()
    proveedor = crear_proveedor(cfg)
    almacen = get_almacenamiento()
    espera = intervalo if intervalo is not None else cfg.fiscal_worker_intervalo_seg
    log.info("worker fiscal iniciado", extra={"proveedor": proveedor.nombre, "una_vez": una_vez})
    try:
        while not parar.is_set():
            error = None
            hechos: list[emision.Resultado] = []
            try:
                hechos = ejecutar_ciclo(proveedor, cfg, almacen)
            except Exception as e:  # noqa: BLE001  (el worker no muere por un fallo de BD o un bug: lo anota y sigue)
                error = f"{type(e).__name__}: {e}"[:500]
                log.exception("fallo en el ciclo del worker fiscal")
            try:
                _latido(error, ciclo=True, procesados=len(hechos))
            except Exception:  # noqa: BLE001
                log.exception("no se pudo anotar el latido")
            if una_vez:
                return 1 if error else 0
            if not hechos:
                parar.wait(espera)
    finally:
        proveedor.cerrar()
        log.info("worker fiscal detenido")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.workers.fiscal", description=__doc__.split("\n")[0])
    ap.add_argument("--una-vez", action="store_true", help="procesa lo elegible y termina")
    ap.add_argument("--intervalo", type=float, default=None, help="segundos de espera cuando no hay trabajo")
    args = ap.parse_args(argv)
    try:
        cfg = validar_configuracion()
    except ConfiguracionInvalida as e:
        print(e, file=sys.stderr)
        return 2
    configurar_logging(cfg.log_level)
    parar = threading.Event()
    for senal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(senal, lambda *_: parar.set())
    try:
        return correr(una_vez=args.una_vez, intervalo=args.intervalo, parar=parar)
    except ConfiguracionInvalida as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
