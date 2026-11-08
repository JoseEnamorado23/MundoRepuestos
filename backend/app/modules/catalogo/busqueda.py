"""Búsqueda de productos y consulta rápida por código (escáner del POS).

Estrategia (todo en SQL, una consulta de candidatos + una de enriquecimiento de la página):
1. Código exacto (código de barras, SKU, referencia normalizada)  -> relevancia máxima.
2. Prefijo de referencia normalizada (con o sin guiones).
3. Texto: cada palabra (prefijo) debe estar en el documento del producto (nombre, marca, referencias, categoría,
   descripción; tsvector `simple` + `spanish`). Las palabras que son marca/modelo de vehículo ("spark") y un año
   ("2018") se convierten en un filtro de compatibilidad: el producto debe servir a alguna versión de ese vehículo
   cuyo rango de años contenga el año.
4. Si no hay resultados: tolerancia a errores de digitación con vecinos más cercanos por trigramas (índice GiST,
   `ORDER BY :q <<-> texto LIMIT n`), con `statement_timeout` corto solo para esa consulta; si se agota se devuelve
   vacío con `incompleta = True` (nunca un 500).

Vehículos: marcas, modelos y ALIAS ('chevy' -> Chevrolet, 'spark gt' -> Spark; tabla `vehiculos_alias`) se detectan
como frases dentro de la consulta, sin tildes ni mayúsculas, y con trigramas para errores leves de digitación.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import psycopg.errors
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.catalogo.servicios import ids_categoria_y_descendientes, lista_predeterminada
from app.modules.catalogo.utiles import normalizar_referencia, sin_acentos

_STOP = {"de", "del", "para", "la", "el", "los", "las", "y", "con", "en", "a", "un", "una"}


@dataclass
class Consulta:
    original: str
    tokens: list[str]  # palabras alfanuméricas en minúscula, sin tildes, sin stopwords ni año
    anio: int | None
    norm: str  # alfanumérico en mayúscula de toda la consulta (para referencias)


def analizar(q: str) -> Consulta:
    limpio = sin_acentos(q).lower()
    palabras = re.findall(r"[a-z0-9]+", limpio)
    anio = next((int(p) for p in palabras if len(p) == 4 and p.isdigit() and 1950 <= int(p) <= 2100), None)
    tokens = [p for p in palabras if p not in _STOP and not (anio is not None and p == str(anio))]
    return Consulta(q.strip(), tokens, anio, normalizar_referencia(q))


def _tsq(i: int) -> str:
    return f"(to_tsquery('simple', :t{i}) || to_tsquery('spanish', :t{i}))"


def _sql_candidatos(
    c: Consulta,
    *,
    con_codigo: bool,
    con_ref: bool,
    con_texto: bool,
    vehiculos: bool,
    tokens_texto: list[str],
):
    partes: list[str] = []
    if con_codigo:
        partes.append(
            "SELECT producto_id AS id, 100.0 AS score FROM catalogo.productos_codigos_barras "
            "WHERE activo AND codigo = :q_exacto"
        )
        partes.append("SELECT id, 99.0 FROM catalogo.productos WHERE sku IN (:q_exacto, :q_upper)")
    if con_ref and len(c.norm) >= 3:
        partes.append(
            "SELECT producto_id, 95.0 FROM catalogo.productos_referencias "
            "WHERE activo AND referencia_normalizada = :norm"
        )
    if con_ref and len(c.norm) >= 4:
        partes.append(
            "SELECT producto_id, 80.0 FROM catalogo.productos_referencias "
            "WHERE activo AND referencia_normalizada LIKE :norm_prefijo"
        )
    if con_texto and tokens_texto:
        cond = " AND ".join(f"b.documento @@ {_tsq(i)}" for i in range(len(tokens_texto)))
        rank = " + ".join(f"ts_rank(b.documento, {_tsq(i)})" for i in range(len(tokens_texto)))
        partes.append(f"SELECT b.producto_id, 10.0 + ({rank}) FROM catalogo.productos_busqueda b WHERE {cond}")
    elif con_texto and vehiculos:
        partes.append(
            "SELECT id, 5.0 FROM catalogo.productos"
        )  # solo filtro por vehículo: todos los candidatos compatibles
    return partes


_NORM_SQL = "btrim(regexp_replace(lower(public.f_unaccent({col})), '[^a-z0-9]+', ' ', 'g'))"


def _frases_de_vehiculo(db: Session, tokens: list[str]) -> list[tuple[tuple[str, ...], str, uuid.UUID]]:
    """Marcas, modelos y alias cuyas palabras están TODAS en la consulta: [(palabras, 'marca'|'modelo', id)]."""
    n_marca = _NORM_SQL.format(col="nombre")
    n_alias = _NORM_SQL.format(col="alias")
    sql = f"""
        SELECT 'modelo' AS t, id, {n_marca} AS n FROM catalogo.vehiculos_modelos WHERE activo
          AND string_to_array({n_marca}, ' ') <@ CAST(:tk AS text[])
        UNION ALL
        SELECT 'marca', id, {n_marca} FROM catalogo.vehiculos_marcas WHERE activo
          AND string_to_array({n_marca}, ' ') <@ CAST(:tk AS text[])
        UNION ALL
        SELECT CASE WHEN modelo_id IS NOT NULL THEN 'modelo' ELSE 'marca' END, COALESCE(modelo_id, marca_id),
               {n_alias} FROM catalogo.vehiculos_alias WHERE activo
          AND string_to_array({n_alias}, ' ') <@ CAST(:tk AS text[])
    """
    return [(tuple(n.split()), t, i) for t, i, n in db.execute(text(sql), {"tk": tokens}).all() if n]


def _frases_aproximadas(db: Session, tokens: list[str]) -> list[tuple[tuple[str, ...], str, uuid.UUID]]:
    """Errores leves de digitación en marcas/modelos ('chevrolt', 'sparck'): trigramas sobre nombres normalizados."""
    largos = [t for t in tokens if len(t) >= 5]
    if not largos:
        return []
    n_marca = _NORM_SQL.format(col="nombre")
    sql = f"""
        SELECT t, id, n, w FROM (
            SELECT 'modelo' AS t, id, {n_marca} AS n, w FROM catalogo.vehiculos_modelos, unnest(CAST(:tk AS text[])) w
             WHERE activo AND {n_marca} % w AND similarity({n_marca}, w) >= 0.5
            UNION ALL
            SELECT 'marca', id, {n_marca}, w FROM catalogo.vehiculos_marcas, unnest(CAST(:tk AS text[])) w
             WHERE activo AND {n_marca} % w AND similarity({n_marca}, w) >= 0.5
        ) x
    """
    # solo nombres de UNA palabra: la palabra escrita (w) toma el lugar del nombre
    return [((w,), t, i) for t, i, n, w in db.execute(text(sql), {"tk": largos}).all() if " " not in n]


def _versiones_de_vehiculo(
    db: Session, tokens: list[str], anio: int | None
) -> tuple[list[uuid.UUID] | None, list[str]]:
    """Palabras que son marca/modelo/alias de vehículo -> ids de versiones (filtradas por año). Devuelve (ids|None, resto).

    Las frases más largas ganan ('spark gt' antes que 'spark'); cada palabra se consume una sola vez.
    """
    if not tokens:
        return None, tokens
    frases = _frases_de_vehiculo(db, tokens)
    libres = [t for t in tokens]
    modelos: set[uuid.UUID] = set()
    marcas: set[uuid.UUID] = set()

    def consumir(frases_: list[tuple[tuple[str, ...], str, uuid.UUID]]) -> None:
        for palabras, tipo, id_ in sorted(frases_, key=lambda f: -len(f[0])):
            n = len(palabras)
            for k in range(len(libres) - n + 1):
                if tuple(libres[k : k + n]) == palabras:
                    del libres[k : k + n]
                    (modelos if tipo == "modelo" else marcas).add(id_)
                    break

    consumir(frases)
    if libres:  # lo que sobra puede ser un nombre mal escrito
        consumir(_frases_aproximadas(db, libres))
    if not modelos and not marcas:
        return None, tokens

    filtros, params = [], {"modelos": list(modelos), "marcas": list(marcas)}
    sql = (
        "SELECT v.id FROM catalogo.vehiculos_versiones v "
        "JOIN catalogo.vehiculos_modelos m ON m.id = v.modelo_id WHERE v.activo"
    )
    if modelos:
        filtros.append("m.id = ANY(:modelos)")
    if marcas:
        filtros.append("m.marca_id = ANY(:marcas)")
    sql += " AND (" + (" AND " if modelos and marcas else " OR ").join(filtros) + ")"
    if anio is not None:
        sql += " AND v.anios @> CAST(:anio AS integer)"
        params["anio"] = anio
    ids = [r[0] for r in db.execute(text(sql), params)]
    return ids, libres


def _busqueda_aproximada(
    db: Session, tokens_texto: list[str], filtros, params, categoria_id, marca_id, vehiculo_version_id, solo_con_stock
) -> tuple[list[dict], int, bool]:
    """Vecinos más cercanos por trigramas (GiST) con tiempo máximo; (items, total, incompleta)."""
    cfg = get_settings()
    candidatos = """
        SELECT k.producto_id AS id, (1 - k.dist)::float8 AS score FROM (
            SELECT b.producto_id, (CAST(:dq AS text) <<-> b.texto) AS dist
              FROM catalogo.productos_busqueda b
             ORDER BY CAST(:dq AS text) <<-> b.texto
             LIMIT :knn
        ) k WHERE k.dist <= :max_dist
    """
    p = {
        **params,
        "dq": " ".join(tokens_texto),
        "knn": cfg.busqueda_difusa_limite,
        "max_dist": 1 - cfg.busqueda_difusa_umbral,
    }
    anterior = db.execute(text("SELECT current_setting('statement_timeout')")).scalar_one()
    sp = db.begin_nested()
    try:
        # SET LOCAL equivalente: vale hasta el fin de la transacción o hasta que se restaure abajo
        db.execute(
            text("SELECT set_config('statement_timeout', :t, true)"), {"t": f"{cfg.busqueda_difusa_timeout_ms}ms"}
        )
        items, total = _ejecutar(
            db, candidatos, filtros, p, categoria_id, marca_id, vehiculo_version_id, solo_con_stock
        )
        sp.commit()
    except DBAPIError as e:
        if not isinstance(e.orig, psycopg.errors.QueryCanceled):
            raise
        sp.rollback()  # deshace también el set_config y deja la transacción utilizable
        return [], 0, True
    db.execute(text("SELECT set_config('statement_timeout', :t, true)"), {"t": anterior})
    return items, total, False


def buscar(
    db: Session,
    *,
    q: str | None,
    sede_id: uuid.UUID | None,
    limit: int,
    offset: int,
    vehiculo_version_id: uuid.UUID | None = None,
    categoria_id: uuid.UUID | None = None,
    marca_id: uuid.UUID | None = None,
    solo_con_stock: bool = False,
    solo_activos: bool = True,
) -> tuple[list[dict], int, bool]:
    """Devuelve (items, total, busqueda_aproximada_incompleta)."""
    params: dict = {"sede": sede_id, "lista": lista_predeterminada(db).id, "limit": limit, "offset": offset}
    filtros = ["p.activo"] if solo_activos else []

    if q and q.strip():
        c = analizar(q)
        params.update(q_exacto=c.original, q_upper=c.original.upper(), norm=c.norm, norm_prefijo=c.norm + "%")
        version_ids, tokens_texto = _versiones_de_vehiculo(db, c.tokens, c.anio)
        if version_ids is not None:
            params["versiones_q"] = version_ids
            filtros.append(
                "EXISTS (SELECT 1 FROM catalogo.productos_compatibilidades pc "
                "WHERE pc.producto_id = p.id AND pc.activo AND pc.version_id = ANY(:versiones_q))"
            )
        for i, t in enumerate(tokens_texto):
            params[f"t{i}"] = f"{t}:*"
        sin_espacios = not re.search(r"\s", c.original)
        partes = _sql_candidatos(
            c,
            con_codigo=sin_espacios,
            con_ref=any(ch.isdigit() for ch in c.original),
            con_texto=True,
            vehiculos=version_ids is not None,
            tokens_texto=tokens_texto,
        )
        if partes:
            candidatos_sql = (
                f"SELECT u.id, max(u.score) AS score FROM ({' UNION ALL '.join(partes)}) u(id, score) GROUP BY u.id"
            )
            items, total = _ejecutar(
                db, candidatos_sql, filtros, params, categoria_id, marca_id, vehiculo_version_id, solo_con_stock
            )
            if total or offset:
                return items, total, False
        if tokens_texto:
            return _busqueda_aproximada(
                db, tokens_texto, filtros, params, categoria_id, marca_id, vehiculo_version_id, solo_con_stock
            )
        return [], 0, False

    candidatos_sql = "SELECT id, 0.0 AS score FROM catalogo.productos"
    items, total = _ejecutar(
        db, candidatos_sql, filtros, params, categoria_id, marca_id, vehiculo_version_id, solo_con_stock
    )
    return items, total, False


def _extra_filtros(db, filtros, params, categoria_id, marca_id, vehiculo_version_id, solo_con_stock) -> list[str]:
    f = list(filtros)
    if categoria_id:
        params["categorias"] = ids_categoria_y_descendientes(db, categoria_id)
        f.append("p.categoria_id = ANY(:categorias)")
    if marca_id:
        params["marca"] = marca_id
        f.append("p.marca_id = :marca")
    if vehiculo_version_id:
        params["version"] = vehiculo_version_id
        f.append(
            "EXISTS (SELECT 1 FROM catalogo.productos_compatibilidades pv "
            "WHERE pv.producto_id = p.id AND pv.activo AND pv.version_id = :version)"
        )
    if solo_con_stock:
        f.append("COALESCE(st.disponible, 0) > 0")
    return f


_STOCK = (
    "LEFT JOIN LATERAL (SELECT COALESCE(sum(e.cantidad_disponible), 0) AS disponible "
    "FROM inventario.existencias e JOIN inventario.bodegas b ON b.id = e.bodega_id "
    "WHERE e.producto_id = p.id AND (CAST(:sede AS uuid) IS NULL OR b.sede_id = :sede) AND b.es_vendible AND b.activo) st ON true"
)
_PRECIO = (
    "LEFT JOIN LATERAL (SELECT pr.precio FROM catalogo.precios pr WHERE pr.producto_id = p.id "
    "AND pr.lista_precio_id = :lista AND (pr.sede_id = CAST(:sede AS uuid) OR pr.sede_id IS NULL) "
    "AND pr.vigente_desde <= clock_timestamp() AND (pr.vigente_hasta IS NULL OR pr.vigente_hasta > clock_timestamp()) "
    "ORDER BY pr.sede_id IS NULL, pr.vigente_desde DESC LIMIT 1) pr ON true"
)


def _ejecutar(db, candidatos_sql, filtros, params, categoria_id, marca_id, vehiculo_version_id, solo_con_stock):
    f = _extra_filtros(db, filtros, params, categoria_id, marca_id, vehiculo_version_id, solo_con_stock)
    where = " AND ".join(f) or "true"
    sql = f"""
        SELECT p.id, p.sku, p.nombre, p.marca_id, m.nombre AS marca, p.categoria_id, ca.nombre AS categoria,
               p.activo, p.stock_minimo, c.score,
               (SELECT cb.codigo FROM catalogo.productos_codigos_barras cb
                 WHERE cb.producto_id = p.id AND cb.activo ORDER BY cb.es_principal DESC LIMIT 1) AS codigo_barras,
               (SELECT u.codigo FROM inventario.productos_ubicaciones pu
                  JOIN inventario.ubicaciones u ON u.id = pu.ubicacion_id AND u.activo
                  JOIN inventario.bodegas bu ON bu.id = u.bodega_id
                 WHERE pu.producto_id = p.id AND (CAST(:sede AS uuid) IS NULL OR bu.sede_id = :sede)
                 ORDER BY pu.es_principal DESC, u.codigo LIMIT 1) AS ubicacion,
               pr.precio, COALESCE(st.disponible, 0) AS stock_disponible,
               count(*) OVER () AS total
          FROM ({candidatos_sql}) c
          JOIN catalogo.productos p ON p.id = c.id
          LEFT JOIN catalogo.marcas m ON m.id = p.marca_id
          LEFT JOIN catalogo.categorias ca ON ca.id = p.categoria_id
          {_PRECIO}
          {_STOCK}
         WHERE {where}
         ORDER BY c.score DESC, p.nombre, p.id
         LIMIT :limit OFFSET :offset
    """
    stmt = text(sql)
    filas = db.execute(stmt, params).mappings().all()
    total = filas[0]["total"] if filas else 0
    if not filas and params["offset"]:
        total = _contar(db, candidatos_sql, where, params, solo_con_stock)
    items = [{k: v for k, v in f.items() if k != "total"} | {"relevancia": float(f["score"])} for f in filas]
    for it in items:
        it.pop("score", None)
    return items, int(total)


def _contar(db, candidatos_sql, where, params, solo_con_stock) -> int:
    join_stock = _STOCK if solo_con_stock or "st." in where else ""
    sql = (
        f"SELECT count(*) FROM ({candidatos_sql}) c JOIN catalogo.productos p ON p.id = c.id {join_stock} WHERE {where}"
    )
    p = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    return db.execute(text(sql), p).scalar() or 0


# ---------------------------------------------------------------------------------------- escáner POS
def producto_por_codigo(db: Session, codigo: str, sede_id: uuid.UUID | None) -> dict | None:
    """Código de barras exacto o SKU. Devuelve producto + precio vigente + stock de la sede + factor por código."""
    codigo = codigo.strip()
    lista = lista_predeterminada(db).id
    sql = f"""
        SELECT p.id, p.sku, p.nombre, p.marca_id, p.categoria_id, p.activo, p.vendible_pos, p.impuesto_id,
               i.codigo AS impuesto_codigo, i.tarifa_pct, i.tratamiento,
               hit.codigo AS codigo_barras, hit.unidades_por_codigo,
               (SELECT u.codigo FROM inventario.productos_ubicaciones pu
                  JOIN inventario.ubicaciones u ON u.id = pu.ubicacion_id AND u.activo
                  JOIN inventario.bodegas bu ON bu.id = u.bodega_id
                 WHERE pu.producto_id = p.id AND (CAST(:sede AS uuid) IS NULL OR bu.sede_id = :sede)
                 ORDER BY pu.es_principal DESC, u.codigo LIMIT 1) AS ubicacion,
               pr.precio, COALESCE(st.disponible, 0) AS stock_disponible
          FROM (
                SELECT producto_id, codigo, unidades_por_codigo, 1 AS prio FROM catalogo.productos_codigos_barras
                 WHERE codigo = :codigo AND activo
                UNION ALL
                SELECT id, NULL, 1, 2 FROM catalogo.productos WHERE sku IN (:codigo, :codigo_upper)
               ) hit
          JOIN catalogo.productos p ON p.id = hit.producto_id
          JOIN catalogo.impuestos i ON i.id = p.impuesto_id
          {_PRECIO}
          {_STOCK}
         ORDER BY hit.prio LIMIT 1
    """
    fila = (
        db.execute(text(sql), {"codigo": codigo, "codigo_upper": codigo.upper(), "sede": sede_id, "lista": lista})
        .mappings()
        .first()
    )
    return dict(fila) if fila else None
