"""turnos, ventas POS y devoluciones: bodega de averías, tolerancia de arqueo, permisos, motivos y configuración

* `inventario.bodegas.tipo` ('general' | 'averias'): destino no vendible de las devoluciones defectuosas; una sola
  bodega de averías activa por sede;
* `cajas.turnos`: `umbral_diferencia` (tolerancia vigente al cerrar), `cierre_forzado` y `motivo_cierre_forzado`;
  CHECK `diferencia_autorizada`: una diferencia fuera de tolerancia exige supervisor + autorización (o cierre forzado);
* permisos nuevos (cajas.turno.abrir, cajas.turno.cerrar, cajas.movimientos, cajas.cierre_forzado,
  pos.cambiar_precio, ventas.ver) y sus asignaciones por rol;
* semillas de `cajas.motivos_movimiento_caja` y `ventas.motivos_devolucion`;
* una fila de `organizacion.configuracion_sede` por clave y por sede existente (valores por defecto documentados en
  `app/modules/organizacion/configuracion.py`).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-07
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NODO_NUBE_ID = "00000000-0000-7000-8000-000000000001"

PERMISOS_NUEVOS = (  # codigo, modulo, descripcion, requiere_autorizacion
    ("cajas.turno.abrir", "cajas", "Abrir turno de caja", False),
    ("cajas.turno.cerrar", "cajas", "Cerrar el propio turno de caja (conteo ciego)", False),
    ("cajas.movimientos", "cajas", "Registrar ingresos y retiros de efectivo del turno", False),
    ("cajas.cierre_forzado", "cajas", "Cerrar a la fuerza el turno abandonado de otro cajero", False),
    ("pos.cambiar_precio", "pos", "Cambiar el precio de una línea sin autorización de supervisor", False),
    ("ventas.ver", "ventas", "Consultar ventas, tirillas e informes de cierre", False),
)
CODIGOS = [p[0] for p in PERMISOS_NUEVOS]
GRANTS = {
    "administrador": CODIGOS,
    "supervisor": CODIGOS,
    "propietario": CODIGOS,
    "cajero": ["cajas.turno.abrir", "cajas.turno.cerrar", "cajas.movimientos", "ventas.ver"],
}

MOTIVOS_CAJA = (  # id, codigo, nombre, tipo, requiere_autorizacion
    ("00000000-0000-7000-8000-000000000031", "retiro_seguridad", "Retiro de seguridad", "retiro", False),
    ("00000000-0000-7000-8000-000000000032", "pago_proveedor", "Pago a proveedor", "retiro", True),
    ("00000000-0000-7000-8000-000000000033", "gasto_menor", "Gasto menor", "retiro", False),
    ("00000000-0000-7000-8000-000000000034", "reposicion_cambio", "Reposición de sencillo", "ingreso", False),
    ("00000000-0000-7000-8000-000000000035", "otro", "Otro (describa el motivo)", "ambos", False),
)
MOTIVOS_DEVOLUCION = (  # id, codigo, nombre, reintegra_stock_por_defecto, requiere_autorizacion
    ("00000000-0000-7000-8000-000000000041", "pieza_equivocada", "Pieza equivocada", True, True),
    ("00000000-0000-7000-8000-000000000042", "defectuosa", "Pieza defectuosa", True, True),
    ("00000000-0000-7000-8000-000000000043", "no_compatible", "No es compatible con el vehículo", True, True),
    ("00000000-0000-7000-8000-000000000044", "cliente_desiste", "El cliente desiste", True, True),
    ("00000000-0000-7000-8000-000000000045", "garantia", "Garantía", True, True),
    (
        "00000000-0000-7000-8000-000000000046",
        "cambio_de_documento",
        "Cambio de documento (la pieza no regresa)",
        False,
        True,
    ),
)
# Debe coincidir con CONFIG_POR_DEFECTO de app/modules/organizacion/configuracion.py (copia congelada en la migración).
CONFIG_SEDE = (  # clave, valor, descripcion
    ("inventario.umbral_aprobacion", 500000, "Valor (COP) desde el cual una entrada o ajuste necesita aprobación"),
    ("inventario.propietario_autoaprueba", False, "El rol propietario puede aprobar sus propias solicitudes"),
    (
        "ventas.descuento_max_pct_por_rol",
        {"cajero": 5, "supervisor": 15, "administrador": 100, "propietario": 100},
        "Descuento máximo (%) sin autorización de otro empleado, por rol; un rol ausente tiene tope 0",
    ),
    ("cajas.umbral_retiro_efectivo", 200000, "Retiro de efectivo (COP) desde el cual se exige autorización"),
    ("cajas.umbral_diferencia_arqueo", 5000, "Diferencia (COP) por medio de pago tolerada al cerrar sin autorización"),
    ("ventas.devolucion_requiere_autorizacion", True, "Toda devolución exige autorización de supervisor"),
    ("ventas.espera_expira_horas", 24, "Horas tras las que una venta en espera se descarta"),
    ("ventas.redondeo_efectivo", 0, "Redondeo del total en ventas pagadas solo en efectivo: 0 (ninguno), 50 o 100"),
)


def _uuid7() -> str:
    try:
        from uuid_utils.compat import uuid7
    except ImportError:  # pragma: no cover
        from uuid import uuid4 as uuid7
    return str(uuid7())


def upgrade() -> None:
    # --- bodega de averías -------------------------------------------------------------------------------------
    op.add_column(
        "bodegas", sa.Column("tipo", sa.Text(), server_default="general", nullable=False), schema="inventario"
    )
    op.create_check_constraint(
        op.f("ck_bodegas_tipo_valido"), "bodegas", "tipo IN ('general','averias')", schema="inventario"
    )
    op.create_check_constraint(
        op.f("ck_bodegas_averias_no_vendible"), "bodegas", "tipo <> 'averias' OR NOT es_vendible", schema="inventario"
    )
    op.create_index(
        "uq_bodegas_averias_sede",
        "bodegas",
        ["sede_id"],
        unique=True,
        schema="inventario",
        postgresql_where=sa.text("tipo = 'averias' AND activo"),
    )

    # --- turnos: tolerancia de arqueo y cierre forzado ---------------------------------------------------------------
    op.add_column("turnos", sa.Column("umbral_diferencia", sa.Numeric(18, 2), nullable=True), schema="cajas")
    op.add_column(
        "turnos",
        sa.Column("cierre_forzado", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="cajas",
    )
    op.add_column("turnos", sa.Column("motivo_cierre_forzado", sa.Text(), nullable=True), schema="cajas")
    op.create_check_constraint(
        op.f("ck_turnos_diferencia_autorizada"),
        "turnos",
        "diferencia IS NULL OR diferencia = 0 OR cierre_forzado "
        "OR (umbral_diferencia IS NOT NULL AND abs(diferencia) <= umbral_diferencia) "
        "OR (supervisor_cierre_id IS NOT NULL AND autorizacion_cierre_id IS NOT NULL)",
        schema="cajas",
    )
    op.create_check_constraint(
        op.f("ck_turnos_forzado_con_motivo"),
        "turnos",
        "NOT cierre_forzado OR motivo_cierre_forzado IS NOT NULL",
        schema="cajas",
    )

    bind = op.get_bind()

    # --- permisos y roles --------------------------------------------------------------------------------------------
    for codigo, modulo, desc, req in PERMISOS_NUEVOS:
        bind.execute(
            sa.text(
                "INSERT INTO identidad.permisos (codigo, modulo, descripcion, requiere_autorizacion) "
                "VALUES (:c, :m, :d, :r) ON CONFLICT DO NOTHING"
            ),
            dict(c=codigo, m=modulo, d=desc, r=req),
        )
    for rol, codigos in GRANTS.items():
        for codigo in codigos:
            bind.execute(
                sa.text(
                    "INSERT INTO identidad.roles_permisos (rol_id, permiso_codigo) "
                    "SELECT id, :p FROM identidad.roles WHERE codigo = :r ON CONFLICT DO NOTHING"
                ),
                dict(p=codigo, r=rol),
            )

    # --- catálogos de motivos ----------------------------------------------------------------------------------------
    for i, codigo, nombre, tipo, req in MOTIVOS_CAJA:
        bind.execute(
            sa.text(
                "INSERT INTO cajas.motivos_movimiento_caja (id, codigo, nombre, tipo, requiere_autorizacion, nodo_origen_id) "
                "VALUES (CAST(:i AS uuid), :c, :n, :t, :r, CAST(:o AS uuid)) ON CONFLICT DO NOTHING"
            ),
            dict(i=i, c=codigo, n=nombre, t=tipo, r=req, o=NODO_NUBE_ID),
        )
    for i, codigo, nombre, reintegra, req in MOTIVOS_DEVOLUCION:
        bind.execute(
            sa.text(
                "INSERT INTO ventas.motivos_devolucion "
                "(id, codigo, nombre, reintegra_stock_por_defecto, requiere_autorizacion, nodo_origen_id) "
                "VALUES (CAST(:i AS uuid), :c, :n, :g, :r, CAST(:o AS uuid)) ON CONFLICT DO NOTHING"
            ),
            dict(i=i, c=codigo, n=nombre, g=reintegra, r=req, o=NODO_NUBE_ID),
        )

    # --- configuración por sede: una fila por clave para cada sede ya existente ---------------------------------------
    sedes = bind.execute(sa.text("SELECT id, nodo_origen_id FROM organizacion.sedes")).all()
    for sede_id, nodo in sedes:
        for clave, valor, desc in CONFIG_SEDE:
            bind.execute(
                sa.text(
                    "INSERT INTO organizacion.configuracion_sede (id, sede_id, clave, valor, descripcion, nodo_origen_id) "
                    "VALUES (CAST(:i AS uuid), :s, :k, CAST(:v AS jsonb), :d, :o) ON CONFLICT DO NOTHING"
                ),
                dict(i=_uuid7(), s=sede_id, k=clave, v=json.dumps(valor), d=desc, o=nodo),
            )


def downgrade() -> None:
    bind = op.get_bind()
    claves = [c[0] for c in CONFIG_SEDE]
    bind.execute(
        sa.text("DELETE FROM organizacion.configuracion_sede WHERE sede_id IS NOT NULL AND clave = ANY(:c)"),
        {"c": claves},
    )
    bind.execute(
        sa.text("DELETE FROM ventas.motivos_devolucion WHERE id = ANY(CAST(:i AS uuid[]))"),
        {"i": [m[0] for m in MOTIVOS_DEVOLUCION]},
    )
    bind.execute(
        sa.text("DELETE FROM cajas.motivos_movimiento_caja WHERE id = ANY(CAST(:i AS uuid[]))"),
        {"i": [m[0] for m in MOTIVOS_CAJA]},
    )
    bind.execute(sa.text("DELETE FROM identidad.roles_permisos WHERE permiso_codigo = ANY(:c)"), {"c": CODIGOS})
    bind.execute(sa.text("DELETE FROM identidad.permisos WHERE codigo = ANY(:c)"), {"c": CODIGOS})
    op.drop_constraint(op.f("ck_turnos_forzado_con_motivo"), "turnos", schema="cajas", type_="check")
    op.drop_constraint(op.f("ck_turnos_diferencia_autorizada"), "turnos", schema="cajas", type_="check")
    op.drop_column("turnos", "motivo_cierre_forzado", schema="cajas")
    op.drop_column("turnos", "cierre_forzado", schema="cajas")
    op.drop_column("turnos", "umbral_diferencia", schema="cajas")
    op.drop_index("uq_bodegas_averias_sede", table_name="bodegas", schema="inventario")
    op.drop_constraint(op.f("ck_bodegas_averias_no_vendible"), "bodegas", schema="inventario", type_="check")
    op.drop_constraint(op.f("ck_bodegas_tipo_valido"), "bodegas", schema="inventario", type_="check")
    op.drop_column("bodegas", "tipo", schema="inventario")
