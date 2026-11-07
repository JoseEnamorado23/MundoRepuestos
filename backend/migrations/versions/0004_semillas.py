"""semillas: códigos DIAN, permisos, roles, nodo nube, consumidor final, IVA y lista de precios

Idempotente (INSERT ... ON CONFLICT DO NOTHING). Los UUID fijos son los únicos ids no generados por la app:
deben ser idénticos en todos los nodos (modelo.md §3 y §5).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# UUID fijos y conocidos (versión 7 nominal; no se generan en tiempo de ejecución)
NODO_NUBE_ID = "00000000-0000-7000-8000-000000000001"
TERCERO_CONSUMIDOR_FINAL_ID = "00000000-0000-7000-8000-000000000002"
LISTA_PRECIOS_GENERAL_ID = "00000000-0000-7000-8000-000000000003"
IMPUESTO_IDS = {
    "IVA19": "00000000-0000-7000-8000-000000000011",
    "IVA5": "00000000-0000-7000-8000-000000000012",
    "IVA0": "00000000-0000-7000-8000-000000000013",
    "EXCLUIDO": "00000000-0000-7000-8000-000000000014",
}
ROL_IDS = {
    "administrador": "00000000-0000-7000-8000-000000000021",
    "supervisor": "00000000-0000-7000-8000-000000000022",
    "cajero": "00000000-0000-7000-8000-000000000023",
    "bodeguero": "00000000-0000-7000-8000-000000000024",
}

# ---------------------------------------------------------------------------------------------
# referencia.*  (códigos habituales del anexo técnico DIAN; validar contra el anexo vigente y Factus)
# ---------------------------------------------------------------------------------------------
TIPOS_DOCUMENTO_IDENTIDAD = (
    ("11", "Registro civil", "RC"),
    ("12", "Tarjeta de identidad", "TI"),
    ("13", "Cédula de ciudadanía", "CC"),
    ("21", "Tarjeta de extranjería", "TE"),
    ("22", "Cédula de extranjería", "CE"),
    ("31", "NIT", "NIT"),
    ("41", "Pasaporte", "PA"),
    ("42", "Documento de identificación extranjero", "DIE"),
    ("47", "PEP", "PEP"),
    ("50", "NIT de otro país", "NITE"),
)
TIPOS_PERSONA = (("1", "Persona jurídica"), ("2", "Persona natural"))
REGIMENES = (("48", "Responsable de IVA"), ("49", "No responsable de IVA"))
RESPONSABILIDADES = (
    ("O-13", "Gran contribuyente"),
    ("O-15", "Autorretenedor"),
    ("O-23", "Agente de retención IVA"),
    ("O-47", "Régimen simple de tributación"),
    ("R-99-PN", "No aplica - Otros"),
)
TRIBUTOS = (("01", "IVA"), ("02", "IC"), ("03", "ICA"), ("04", "INC"), ("ZZ", "No aplica"))
MEDIOS_PAGO = (  # codigo, nombre, es_efectivo, requiere_referencia
    ("10", "Efectivo", True, False),
    ("20", "Cheque", False, True),
    ("42", "Consignación bancaria", False, True),
    ("47", "Transferencia", False, True),
    ("48", "Tarjeta crédito", False, True),
    ("49", "Tarjeta débito", False, True),
    ("ZZ", "Otro", False, False),
)
FORMAS_PAGO = (("1", "Contado"), ("2", "Crédito"))
UNIDADES = (  # codigo, nombre, abreviatura, permite_decimales
    ("94", "Unidad", "und", False),
    ("LTR", "Litro", "L", True),
    ("MTR", "Metro", "m", True),
    ("KGM", "Kilogramo", "kg", True),
    ("GLL", "Galón", "gal", True),
)
DEPARTAMENTOS = (
    ("05", "Antioquia"),
    ("08", "Atlántico"),
    ("11", "Bogotá D.C."),
    ("13", "Bolívar"),
    ("15", "Boyacá"),
    ("17", "Caldas"),
    ("18", "Caquetá"),
    ("19", "Cauca"),
    ("20", "Cesar"),
    ("23", "Córdoba"),
    ("25", "Cundinamarca"),
    ("27", "Chocó"),
    ("41", "Huila"),
    ("44", "La Guajira"),
    ("47", "Magdalena"),
    ("50", "Meta"),
    ("52", "Nariño"),
    ("54", "Norte de Santander"),
    ("63", "Quindío"),
    ("66", "Risaralda"),
    ("68", "Santander"),
    ("70", "Sucre"),
    ("73", "Tolima"),
    ("76", "Valle del Cauca"),
    ("81", "Arauca"),
    ("85", "Casanare"),
    ("86", "Putumayo"),
    ("88", "San Andrés, Providencia y Santa Catalina"),
    ("91", "Amazonas"),
    ("94", "Guainía"),
    ("95", "Guaviare"),
    ("97", "Vaupés"),
    ("99", "Vichada"),
)
# DIVIPOLA: SOLO capitales y municipios principales. El listado completo (~1 100) se importa aparte (pendiente).
MUNICIPIOS = (
    ("05001", "05", "Medellín"),
    ("05088", "05", "Bello"),
    ("05266", "05", "Envigado"),
    ("05360", "05", "Itagüí"),
    ("08001", "08", "Barranquilla"),
    ("08758", "08", "Soledad"),
    ("11001", "11", "Bogotá D.C."),
    ("13001", "13", "Cartagena de Indias"),
    ("15001", "15", "Tunja"),
    ("15238", "15", "Duitama"),
    ("15759", "15", "Sogamoso"),
    ("17001", "17", "Manizales"),
    ("18001", "18", "Florencia"),
    ("19001", "19", "Popayán"),
    ("20001", "20", "Valledupar"),
    ("23001", "23", "Montería"),
    ("25175", "25", "Chía"),
    ("25269", "25", "Facatativá"),
    ("25286", "25", "Funza"),
    ("25290", "25", "Fusagasugá"),
    ("25473", "25", "Mosquera"),
    ("25754", "25", "Soacha"),
    ("25899", "25", "Zipaquirá"),
    ("27001", "27", "Quibdó"),
    ("41001", "41", "Neiva"),
    ("41551", "41", "Pitalito"),
    ("44001", "44", "Riohacha"),
    ("47001", "47", "Santa Marta"),
    ("50001", "50", "Villavicencio"),
    ("52001", "52", "Pasto"),
    ("52356", "52", "Ipiales"),
    ("54001", "54", "Cúcuta"),
    ("63001", "63", "Armenia"),
    ("66001", "66", "Pereira"),
    ("68001", "68", "Bucaramanga"),
    ("68276", "68", "Floridablanca"),
    ("68307", "68", "Girón"),
    ("68547", "68", "Piedecuesta"),
    ("70001", "70", "Sincelejo"),
    ("73001", "73", "Ibagué"),
    ("76001", "76", "Cali"),
    ("76520", "76", "Palmira"),
    ("76834", "76", "Tuluá"),
    ("81001", "81", "Arauca"),
    ("85001", "85", "Yopal"),
    ("86001", "86", "Mocoa"),
    ("88001", "88", "San Andrés"),
    ("91001", "91", "Leticia"),
    ("94001", "94", "Inírida"),
    ("95001", "95", "San José del Guaviare"),
    ("97001", "97", "Mitú"),
    ("99001", "99", "Puerto Carreño"),
)
TIPOS_DOCUMENTO_FISCAL = (  # codigo, nombre, codigo_dian, requiere_referencia, usa_resolucion, activo
    ("FE", "Factura electrónica de venta", "01", False, True, True),
    ("NC", "Nota crédito electrónica", "91", True, True, True),
    ("ND", "Nota débito electrónica", "92", True, True, True),
    ("POS_E", "Documento equivalente POS electrónico", "20", False, True, False),
    ("NA", "Nota de ajuste del documento equivalente", "95", True, True, False),
    ("DS", "Documento soporte en adquisiciones", "05", False, True, False),
)
CONCEPTOS_NOTA = (
    ("NC", "1", "Devolución parcial de los bienes"),
    ("NC", "2", "Anulación de la factura"),
    ("NC", "3", "Rebaja o descuento parcial o total"),
    ("NC", "4", "Ajuste de precio"),
    ("NC", "5", "Otros"),
    ("ND", "1", "Intereses"),
    ("ND", "2", "Gastos por cobrar"),
    ("ND", "3", "Cambio del valor"),
    ("ND", "4", "Otros"),
)

# ---------------------------------------------------------------------------------------------
# identidad.permisos  (codigo, modulo, descripcion, requiere_autorizacion)
# ---------------------------------------------------------------------------------------------
PERMISOS = (
    ("pos.vender", "pos", "Registrar y confirmar ventas", False),
    ("pos.anular", "pos", "Anular o descartar una venta", True),
    ("pos.descuento_mayor", "pos", "Aplicar descuentos por encima del tope del cajero", True),
    ("pos.devolver", "pos", "Registrar devoluciones de venta", True),
    ("pos.precio_manual", "pos", "Cambiar el precio de una línea", True),
    ("pos.venta_sin_stock", "pos", "Vender con existencias insuficientes", True),
    ("pos.retirar_efectivo", "pos", "Retirar efectivo de la caja durante el turno", True),
    ("caja.abrir", "caja", "Abrir turno de caja", False),
    ("caja.cerrar", "caja", "Cerrar turno de caja", False),
    ("caja.cerrar_con_diferencia", "caja", "Cerrar turno con faltante o sobrante", True),
    ("inventario.ver", "inventario", "Consultar existencias y kardex", False),
    ("inventario.ajustar", "inventario", "Ajustar inventario manualmente", True),
    ("inventario.conteo", "inventario", "Realizar conteos físicos", False),
    ("compras.recibir", "compras", "Recibir mercancía de proveedores", False),
    ("catalogo.editar", "catalogo", "Crear y editar productos", False),
    ("catalogo.editar_precios", "catalogo", "Modificar precios y listas", False),
    ("fiscal.ver", "fiscal", "Consultar documentos fiscales", False),
    ("fiscal.reenviar", "fiscal", "Reenviar documentos al proveedor tecnológico", False),
    ("reportes.ver", "reportes", "Consultar reportes", False),
    ("admin.usuarios", "admin", "Administrar empleados, roles y permisos", False),
    ("admin.configuracion", "admin", "Administrar configuración de sede, cajas y resoluciones", False),
)
ROLES = (  # clave, nombre
    ("administrador", "Administrador"),
    ("supervisor", "Supervisor"),
    ("cajero", "Cajero"),
    ("bodeguero", "Bodeguero"),
)
ROLES_PERMISOS = {
    "administrador": [p[0] for p in PERMISOS],
    "supervisor": [p[0] for p in PERMISOS if not p[0].startswith("admin.")],
    "cajero": ["pos.vender", "caja.abrir", "caja.cerrar", "inventario.ver", "fiscal.ver"],
    "bodeguero": ["inventario.ver", "inventario.conteo", "compras.recibir", "catalogo.editar"],
}

IMPUESTOS = (  # clave, codigo, nombre, tributo, tratamiento, tarifa
    ("IVA19", "IVA19", "IVA 19 %", "01", "gravado", 19),
    ("IVA5", "IVA5", "IVA 5 %", "01", "gravado", 5),
    ("IVA0", "IVA0", "IVA 0 % (exento)", "01", "exento", 0),
    ("EXCLUIDO", "EXCLUIDO", "Excluido de IVA", "ZZ", "excluido", 0),
)


def _ins(tabla: str, cols: tuple[str, ...], filas, *, cast: dict[str, str] | None = None) -> None:
    """INSERT ... ON CONFLICT DO NOTHING fila a fila (idempotente)."""
    cast = cast or {}
    ph = ", ".join(f"CAST(:{c} AS {cast[c]})" if c in cast else f":{c}" for c in cols)
    sql = sa.text(f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({ph}) ON CONFLICT DO NOTHING")
    bind = op.get_bind()
    for fila in filas:
        bind.execute(sql, dict(zip(cols, fila)))


def upgrade() -> None:
    _ins("referencia.tipos_documento_identidad", ("codigo", "nombre", "abreviatura"), TIPOS_DOCUMENTO_IDENTIDAD)
    _ins("referencia.tipos_persona", ("codigo", "nombre"), TIPOS_PERSONA)
    _ins("referencia.regimenes", ("codigo", "nombre"), REGIMENES)
    _ins("referencia.responsabilidades_fiscales", ("codigo", "nombre"), RESPONSABILIDADES)
    _ins("referencia.tributos", ("codigo", "nombre"), TRIBUTOS)
    _ins("referencia.medios_pago", ("codigo", "nombre", "es_efectivo", "requiere_referencia"), MEDIOS_PAGO)
    _ins("referencia.formas_pago", ("codigo", "nombre"), FORMAS_PAGO)
    _ins("referencia.unidades_medida", ("codigo", "nombre", "abreviatura", "permite_decimales"), UNIDADES)
    _ins("referencia.departamentos", ("codigo", "nombre"), DEPARTAMENTOS)
    _ins("referencia.municipios", ("codigo", "departamento_codigo", "nombre"), MUNICIPIOS)
    _ins(
        "referencia.tipos_documento_fiscal",
        ("codigo", "nombre", "codigo_dian", "requiere_referencia", "usa_resolucion", "activo"),
        TIPOS_DOCUMENTO_FISCAL,
    )
    _ins("referencia.conceptos_nota", ("tipo_documento_codigo", "codigo", "nombre"), CONCEPTOS_NOTA)

    # FKs created_by / nodo_origen_id son DEFERRABLE INITIALLY DEFERRED: el nodo nube se apunta a sí mismo.
    _ins(
        "organizacion.nodos",
        ("id", "tipo", "nombre", "estado", "nodo_origen_id"),
        [(NODO_NUBE_ID, "cloud", "Nube", "activo", NODO_NUBE_ID)],
        cast={
            "id": "uuid",
            "tipo": "organizacion.nodo_tipo",
            "estado": "organizacion.nodo_estado",
            "nodo_origen_id": "uuid",
        },
    )

    _ins(
        "identidad.terceros",
        (
            "id",
            "tipo_persona_codigo",
            "tipo_documento_codigo",
            "numero_documento",
            "nombre_completo",
            "es_cliente",
            "es_consumidor_final",
            "nodo_origen_id",
        ),
        [(TERCERO_CONSUMIDOR_FINAL_ID, "2", "13", "222222222222", "Consumidor final", True, True, NODO_NUBE_ID)],
        cast={"id": "uuid", "nodo_origen_id": "uuid"},
    )

    _ins(
        "catalogo.impuestos",
        ("id", "codigo", "nombre", "tributo_codigo", "tratamiento", "tarifa_pct", "nodo_origen_id"),
        [(IMPUESTO_IDS[k], c, n, t, tr, tf, NODO_NUBE_ID) for k, c, n, t, tr, tf in IMPUESTOS],
        cast={"id": "uuid", "tratamiento": "catalogo.tratamiento_impuesto", "nodo_origen_id": "uuid"},
    )

    _ins(
        "catalogo.listas_precios",
        ("id", "codigo", "nombre", "precios_incluyen_impuesto", "es_predeterminada", "nodo_origen_id"),
        [(LISTA_PRECIOS_GENERAL_ID, "GENERAL", "Lista general (público)", True, True, NODO_NUBE_ID)],
        cast={"id": "uuid", "nodo_origen_id": "uuid"},
    )

    _ins("identidad.permisos", ("codigo", "modulo", "descripcion", "requiere_autorizacion"), PERMISOS)
    _ins(
        "identidad.roles",
        ("id", "codigo", "nombre", "es_sistema", "nodo_origen_id"),
        [(ROL_IDS[k], k, n, True, NODO_NUBE_ID) for k, n in ROLES],
        cast={"id": "uuid", "nodo_origen_id": "uuid"},
    )
    _ins(
        "identidad.roles_permisos",
        ("rol_id", "permiso_codigo"),
        [(ROL_IDS[rol], p) for rol, ps in ROLES_PERMISOS.items() for p in ps],
        cast={"rol_id": "uuid"},
    )


def downgrade() -> None:
    """Borra solo lo sembrado aquí (si ya hay datos que lo referencian, el DELETE falla por RESTRICT: es lo deseado)."""
    bind = op.get_bind()
    ids_roles = list(ROL_IDS.values())
    bind.execute(
        sa.text("DELETE FROM identidad.roles_permisos WHERE rol_id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids_roles}
    )
    bind.execute(sa.text("DELETE FROM identidad.roles WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids_roles})
    bind.execute(sa.text("DELETE FROM identidad.permisos WHERE codigo = ANY(:c)"), {"c": [p[0] for p in PERMISOS]})
    bind.execute(
        sa.text("DELETE FROM catalogo.listas_precios WHERE id = CAST(:i AS uuid)"), {"i": LISTA_PRECIOS_GENERAL_ID}
    )
    bind.execute(
        sa.text("DELETE FROM catalogo.impuestos WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": list(IMPUESTO_IDS.values())},
    )
    bind.execute(
        sa.text("DELETE FROM identidad.terceros WHERE id = CAST(:i AS uuid)"), {"i": TERCERO_CONSUMIDOR_FINAL_ID}
    )
    bind.execute(sa.text("DELETE FROM organizacion.nodos WHERE id = CAST(:i AS uuid)"), {"i": NODO_NUBE_ID})
    for tabla in (
        "referencia.conceptos_nota",
        "referencia.tipos_documento_fiscal",
        "referencia.municipios",
        "referencia.departamentos",
        "referencia.unidades_medida",
        "referencia.formas_pago",
        "referencia.medios_pago",
        "referencia.tributos",
        "referencia.responsabilidades_fiscales",
        "referencia.regimenes",
        "referencia.tipos_persona",
        "referencia.tipos_documento_identidad",
    ):
        op.execute(f"DELETE FROM {tabla}")
