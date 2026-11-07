"""Genera docs/permisos.md (código, descripción y roles que tienen cada permiso) desde la BD migrada.

Uso (desde backend/, con la BD arriba):  uv run python -m scripts.permisos_doc
La prueba `tests/test_permisos_doc.py` verifica que el archivo esté al día con la BD de pruebas.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

DESTINO = Path(__file__).resolve().parents[2] / "docs" / "permisos.md"

ENCABEZADO = """# Permisos y roles

> **Generado** por `uv run python -m scripts.permisos_doc` desde la base de datos migrada; no editar a mano
> (`backend/tests/test_permisos_doc.py` falla si queda desactualizado). Los permisos y roles se siembran en las
> migraciones (0004, 0006, 0008, 0009, 0010).

* **Req. aut.**: la acción puede exigir la autorización de OTRO empleado (PIN de supervisor o aprobación remota; ver
  `base-de-datos/modelo.md` §4.5 «Políticas de autorización»). Quien tiene el permiso no necesita pedirla.
* Un empleado tiene la unión de los permisos de sus roles activos.

"""


def generar(conn) -> str:
    roles = conn.execute(text("SELECT codigo FROM identidad.roles WHERE activo ORDER BY codigo")).scalars().all()
    permisos = conn.execute(
        text(
            "SELECT p.codigo, p.modulo, p.descripcion, p.requiere_autorizacion, "
            "COALESCE(array_agg(r.codigo ORDER BY r.codigo) FILTER (WHERE r.codigo IS NOT NULL), '{}') "
            "FROM identidad.permisos p "
            "LEFT JOIN identidad.roles_permisos rp ON rp.permiso_codigo = p.codigo "
            "LEFT JOIN identidad.roles r ON r.id = rp.rol_id AND r.activo "
            "GROUP BY p.codigo, p.modulo, p.descripcion, p.requiere_autorizacion "
            "ORDER BY p.modulo, p.codigo"
        )
    ).all()
    out = [ENCABEZADO, "## Roles\n\n", "| Rol | Permisos |\n|---|---|\n"]
    por_rol = {r: 0 for r in roles}
    for _c, _m, _d, _q, rs in permisos:
        for r in rs:
            por_rol[r] = por_rol.get(r, 0) + 1
    out += [f"| `{r}` | {n} |\n" for r, n in por_rol.items()]
    out.append(
        "\n## Permisos\n\n| Código | Módulo | Descripción | Req. aut. | Roles que lo tienen |\n|---|---|---|---|---|\n"
    )
    for codigo, modulo, desc, req, rs in permisos:
        roles_txt = ", ".join(f"`{r}`" for r in rs) or "—"
        out.append(f"| `{codigo}` | {modulo} | {desc} | {'sí' if req else 'no'} | {roles_txt} |\n")
    return "".join(out)


def main() -> None:
    from sqlalchemy import create_engine

    from app.core.config import get_settings

    eng = create_engine(get_settings().database_url)
    with eng.connect() as conn:
        DESTINO.write_text(generar(conn), encoding="utf-8", newline="\n")
    print(f"Escrito {DESTINO}")


if __name__ == "__main__":
    main()
