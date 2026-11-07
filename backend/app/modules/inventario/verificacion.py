"""Verificación de la proyección `existencias` contra el kardex (fuente de verdad)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.auditoria.servicios import registrar_accion

_SQL = """
WITH suma AS (
    SELECT bodega_id, producto_id, sum(cantidad) AS cantidad, max(secuencia) AS secuencia
      FROM inventario.movimientos_inventario
     {filtro_k}
     GROUP BY bodega_id, producto_id
), ultimo AS (
    SELECT DISTINCT ON (bodega_id, producto_id) bodega_id, producto_id,
           costo_promedio_resultante AS costo_promedio, saldo_cantidad
      FROM inventario.movimientos_inventario
     {filtro_k}
     ORDER BY bodega_id, producto_id, secuencia DESC
)
SELECT COALESCE(s.bodega_id, e.bodega_id) AS bodega_id, COALESCE(s.producto_id, e.producto_id) AS producto_id,
       e.cantidad AS cantidad_proyeccion, COALESCE(s.cantidad, 0) AS cantidad_kardex,
       e.costo_promedio AS costo_proyeccion, COALESCE(u.costo_promedio, 0) AS costo_kardex,
       e.ultima_secuencia AS secuencia_proyeccion, COALESCE(s.secuencia, 0) AS secuencia_kardex,
       u.saldo_cantidad AS saldo_ultimo_movimiento
  FROM suma s
  FULL JOIN inventario.existencias e ON e.bodega_id = s.bodega_id AND e.producto_id = s.producto_id
  LEFT JOIN ultimo u ON u.bodega_id = COALESCE(s.bodega_id, e.bodega_id) AND u.producto_id = COALESCE(s.producto_id, e.producto_id)
 WHERE true {filtro_e}
"""


@dataclass
class Diferencia:
    bodega_id: uuid.UUID
    producto_id: uuid.UUID
    cantidad_proyeccion: Decimal | None
    cantidad_kardex: Decimal
    costo_proyeccion: Decimal | None
    costo_kardex: Decimal
    secuencia_proyeccion: int | None
    secuencia_kardex: int


def verificar(
    db: Session, *, reparar: bool = False, actor_id: uuid.UUID | None = None, bodega_id: uuid.UUID | None = None
) -> list[Diferencia]:
    """Recalcula las existencias desde el kardex y devuelve las diferencias. Con `reparar`, corrige la proyección."""
    filtro_k = "WHERE bodega_id = :b" if bodega_id else ""
    filtro_e = "AND COALESCE(s.bodega_id, e.bodega_id) = :b" if bodega_id else ""
    filas = db.execute(
        text(_SQL.format(filtro_k=filtro_k, filtro_e=filtro_e)), {"b": bodega_id} if bodega_id else {}
    ).mappings()
    diferencias: list[Diferencia] = []
    for f in filas:
        qp, ck = f["cantidad_proyeccion"], f["cantidad_kardex"]
        sin_fila = qp is None
        igual = (
            not sin_fila
            and qp == ck
            and f["costo_proyeccion"] == f["costo_kardex"]
            and f["secuencia_proyeccion"] == f["secuencia_kardex"]
        )
        if not igual:
            diferencias.append(
                Diferencia(
                    f["bodega_id"],
                    f["producto_id"],
                    qp,
                    ck,
                    f["costo_proyeccion"],
                    f["costo_kardex"],
                    f["secuencia_proyeccion"],
                    f["secuencia_kardex"],
                )
            )
    if reparar and diferencias:
        for d in diferencias:
            # bloquea la fila para no competir con un movimiento en curso
            db.execute(
                text(
                    "INSERT INTO inventario.existencias (bodega_id, producto_id, cantidad, costo_promedio, ultima_secuencia) "
                    "VALUES (:b, :p, :q, :c, :s) "
                    "ON CONFLICT (bodega_id, producto_id) DO UPDATE SET cantidad = :q, costo_promedio = :c, ultima_secuencia = :s"
                ),
                {
                    "b": d.bodega_id,
                    "p": d.producto_id,
                    "q": d.cantidad_kardex,
                    "c": d.costo_kardex,
                    "s": d.secuencia_kardex,
                },
            )
        registrar_accion(
            db,
            "inventario.existencias_reparadas",
            actor_id=actor_id,
            actor_tipo="empleado" if actor_id else "sistema",
            despues={"filas": len(diferencias)},
            motivo="inventario verificar --reparar",
        )
    return diferencias
