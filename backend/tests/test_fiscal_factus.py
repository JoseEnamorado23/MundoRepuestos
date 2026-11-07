"""Adaptador de Factus con respx (sin red): autenticación y renovación, respuestas, clasificación de errores, mapeo."""

from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from app.core import logs
from app.modules.fiscal.proveedores import factus_mapeo as mapeo
from app.modules.fiscal.proveedores.base import (
    ConflictoPendiente,
    DocumentoEmision,
    ErrorConfiguracion,
    ErrorTransitorio,
    LineaEmision,
    PagoEmision,
    RechazoValidacion,
)
from app.modules.fiscal.proveedores.factus import ProveedorFiscalFactus

D = Decimal
BASE = "https://factus.test"
SECRETO = "super-secreto-de-prueba-123"
TOKEN = "tok-acceso-aaaaaaaaaaaaaaaaaaaaaaaa"


def _linea(precio="10000", cantidad="2", tarifa="19"):
    """Línea con IVA 19 %: total 23 800 (2 x 11 900); base 20 000; IVA 3 800."""
    tot = D(precio) * D(cantidad) * (1 + D(tarifa) / 100)
    base = D(precio) * D(cantidad)
    return LineaEmision(
        codigo="SKU1",
        descripcion="Pastillas",
        unidad_codigo="94",
        cantidad=D(cantidad),
        precio_unitario=(D(precio) * (1 + D(tarifa) / 100)),
        descuento_valor=D("0"),
        base_gravable=base,
        impuesto_valor=tot - base,
        total_linea=tot,
        tributo_codigo="01",
        tarifa_pct=D(tarifa),
    )


def _doc(tipo="FE", **kw) -> DocumentoEmision:
    ln = _linea()
    base = dict(
        reference_code=uuid.uuid4(),
        tipo=tipo,
        fecha=datetime.now(UTC),
        rango_proveedor_id="389",
        prefijo_resolucion="SETP",
        adquirente={
            "tipo_documento_codigo": "13",
            "numero_documento": "222222222222",
            "es_consumidor_final": True,
            "nombre_completo": "Consumidor final",
        },
        lineas=[ln],
        pagos=[PagoEmision("10", ln.total_linea)],
        forma_pago_codigo="1",
        subtotal=ln.base_gravable,
        impuesto_total=ln.impuesto_valor,
        redondeo=D("0"),
        total=ln.total_linea,
    )
    if tipo == "NC":
        base.update(numero_documento_referenciado="SETP990001", concepto_nota_codigo="2", rango_proveedor_id="390")
    base.update(kw)
    return DocumentoEmision(**base)


def _ok(numero="SETP990001", validado=True, errors=None):
    return {
        "status": "Created",
        "message": "ok",
        "data": {
            "number": numero,
            "cufe": "c" * 96,
            "is_validated": validado,
            "validated_at": "07-11-2026 10:30:45 AM",
            "errors": errors or {},
            "totals": {"gross_amount": "20000.00", "tax_amount": "3800.00", "total": "23800.00"},
            "links": {"qr": "https://qr.test/x", "public_url": "https://pub.test/x"},
        },
    }


@pytest.fixture
def mock():
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        yield m


@pytest.fixture
def prov(mock):
    p = ProveedorFiscalFactus(
        url=BASE,
        client_id="cid",
        client_secret=SECRETO,
        username="u@x.co",
        password="clave-x",
        certificados_sistema=False,
    )
    yield p
    p.cerrar()


def _token_ok(mock, expires=3600, refresh="ref-1"):
    return mock.post("/oauth/token").respond(
        200, json={"access_token": TOKEN, "refresh_token": refresh, "expires_in": expires, "token_type": "Bearer"}
    )


# ------------------------------------------------------------------------------------------------ autenticación
def test_el_token_se_pide_una_vez_y_se_reutiliza(mock, prov):
    tok = _token_ok(mock)
    mock.post("/v2/bills/validate").respond(201, json=_ok())
    prov.emitir_factura(_doc())
    prov.emitir_factura(_doc())
    assert tok.call_count == 1
    assert mock.calls[1].request.headers["Authorization"] == f"Bearer {TOKEN}"


def test_el_token_vencido_se_renueva_con_refresh_token(mock, prov):
    tok = _token_ok(mock, expires=1)  # vence (con margen) de inmediato
    mock.post("/v2/bills/validate").respond(201, json=_ok())
    prov.emitir_factura(_doc())
    prov.emitir_factura(_doc())
    cuerpos = [c.request.content.decode() for c in tok.calls]
    assert "grant_type=password" in cuerpos[0] and "grant_type=refresh_token" in cuerpos[1]
    assert "refresh_token=ref-1" in cuerpos[1]


def test_401_renueva_el_token_y_repite_una_sola_vez(mock, prov):
    tok = _token_ok(mock)
    ruta = mock.post("/v2/bills/validate")
    ruta.side_effect = [httpx.Response(401, json={"message": "Unauthenticated."}), httpx.Response(201, json=_ok())]
    r = prov.emitir_factura(_doc())
    assert r.estado == "aceptado" and ruta.call_count == 2 and tok.call_count == 2


def test_credenciales_invalidas_son_error_de_configuracion(mock, prov):
    mock.post("/oauth/token").respond(401, json={"message": "invalid_client"})
    with pytest.raises(ErrorConfiguracion):
        prov.emitir_factura(_doc())


# ------------------------------------------------------------------------------------------------ respuestas
def test_factura_aceptada_trae_numero_cufe_qr_y_totales(mock, prov):
    _token_ok(mock)
    mock.post("/v2/bills/validate").respond(201, json=_ok())
    r = prov.emitir_factura(_doc())
    assert (r.estado, r.numero, r.cufe) == ("aceptado", "SETP990001", "c" * 96)
    assert r.qr_url == "https://qr.test/x" and (r.subtotal, r.impuesto_total, r.total) == (
        D("20000"),
        D("3800"),
        D("23800"),
    )


def test_las_notificaciones_de_la_dian_no_son_rechazo(mock, prov):
    _token_ok(mock)
    mock.post("/v2/bills/validate").respond(
        201,
        json=_ok(
            errors={"FAJ43b": "Regla: FAJ43b, Notificación: Nombre informado No corresponde al registrado en el RUT"}
        ),
    )
    r = prov.emitir_factura(_doc())
    assert r.estado == "aceptado" and r.advertencias


def test_regla_de_rechazo_de_la_dian_es_rechazo_de_validacion(mock, prov):
    _token_ok(mock)
    mock.post("/v2/bills/validate").respond(
        201, json=_ok(validado=False, errors={"FAD09": "Regla: FAD09, Rechazo: Documento de referencia no válido"})
    )
    with pytest.raises(RechazoValidacion) as e:
        prov.emitir_factura(_doc())
    assert "FAD09" in e.value.errores[0]


def test_enviado_sin_validar_queda_pendiente(mock, prov):
    _token_ok(mock)
    mock.post("/v2/bills/validate").respond(201, json=_ok(validado=False))
    assert prov.emitir_factura(_doc()).estado == "pendiente"


# ------------------------------------------------------------------------------------------------ clasificación
@pytest.mark.parametrize(
    ("status", "clase"),
    [
        (409, ConflictoPendiente),
        (429, ErrorTransitorio),
        (500, ErrorTransitorio),
        (503, ErrorTransitorio),
        (422, RechazoValidacion),
        (400, RechazoValidacion),
        (403, ErrorConfiguracion),
        (404, ErrorConfiguracion),
    ],
)
def test_clasificacion_de_errores_http(mock, prov, status, clase):
    _token_ok(mock)
    mock.post("/v2/bills/validate").respond(
        status, json={"message": "falla", "data": {"errors": {"items.0.price": ["El precio es inválido"]}}}
    )
    with pytest.raises(clase) as e:
        prov.emitir_factura(_doc())
    assert type(e.value) is clase  # ConflictoPendiente es un transitorio, pero debe distinguirse


def test_429_respeta_retry_after(mock, prov):
    _token_ok(mock)
    mock.post("/v2/bills/validate").respond(429, headers={"Retry-After": "42"}, json={"message": "Too Many Attempts."})
    with pytest.raises(ErrorTransitorio) as e:
        prov.emitir_factura(_doc())
    assert e.value.reintentar_en == 42


def test_timeout_y_error_de_red_son_transitorios(mock, prov):
    _token_ok(mock)
    ruta = mock.post("/v2/bills/validate")
    ruta.side_effect = httpx.ReadTimeout("lento")
    with pytest.raises(ErrorTransitorio):
        prov.emitir_factura(_doc())
    ruta.side_effect = httpx.ConnectError("sin red")
    with pytest.raises(ErrorTransitorio):
        prov.emitir_factura(_doc())


def test_timeout_luego_exito_con_el_mismo_reference_code(mock, prov):
    _token_ok(mock)
    ruta = mock.post("/v2/bills/validate")
    ruta.side_effect = [httpx.ReadTimeout("lento"), httpx.Response(200, json=_ok())]
    doc = _doc()
    with pytest.raises(ErrorTransitorio):
        prov.emitir_factura(doc)
    assert prov.emitir_factura(doc).estado == "aceptado"
    enviados = {json.loads(c.request.content)["reference_code"] for c in ruta.calls}
    assert enviados == {str(doc.reference_code)}  # el reenvío es idempotente por reference_code


def test_respuesta_que_no_es_json_es_transitoria(mock, prov):
    _token_ok(mock)
    mock.post("/v2/bills/validate").respond(200, text="<html>mantenimiento</html>")
    with pytest.raises(ErrorTransitorio):
        prov.emitir_factura(_doc())


# ------------------------------------------------------------------------------------------------ archivos y nota
def test_descarga_de_pdf_y_xml_decodifica_base64(mock, prov):
    _token_ok(mock)
    mock.get("/v2/bills/SETP990001/download-pdf").respond(
        200, json={"data": {"pdf_base_64_encoded": base64.b64encode(b"%PDF-1.4 x").decode()}}
    )
    mock.get("/v2/bills/SETP990001/download-xml").respond(
        200, json={"data": {"xml_base_64_encoded": base64.b64encode(b"<xml/>").decode()}}
    )
    assert prov.descargar_pdf("FE", "SETP990001") == b"%PDF-1.4 x"
    assert prov.descargar_xml("FE", "SETP990001") == b"<xml/>"


def test_nota_credito_envia_factura_referenciada_y_rango(mock, prov):
    _token_ok(mock)
    ruta = mock.post("/v2/credit-notes/validate").respond(201, json=_ok("NC1"))
    prov.emitir_nota_credito(_doc("NC"))
    j = json.loads(ruta.calls[0].request.content)
    assert (j["bill_number"], j["numbering_range_id"], j["correction_concept_code"]) == ("SETP990001", 390, "2")


def test_eliminar_pendiente(mock, prov):
    _token_ok(mock)
    ref = uuid.uuid4()
    mock.delete(f"/v2/bills/destroy/reference/{ref}").respond(200, json={"status": "OK"})
    assert prov.eliminar_pendiente("FE", ref) is True
    otro = uuid.uuid4()
    mock.delete(f"/v2/bills/destroy/reference/{otro}").respond(404, json={"message": "no existe"})
    assert prov.eliminar_pendiente("FE", otro) is False


# ------------------------------------------------------------------------------------------------ mapeo
def test_mapeo_factura_consumidor_final():
    j = mapeo.construir_factura(_doc())
    assert j["reference_code"] and j["document"] == "01" and j["numbering_range_id"] == 389
    assert j["customer"]["names"] == "Consumidor Final" and j["customer"]["identification"] == "222222222222"
    it = j["items"][0]
    assert (it["quantity"], it["price"]) == ("2.00", "10000.00") and it["taxes"] == [{"code": "01", "rate": "19.00"}]
    assert j["payment_details"][0]["amount"] == "23800.00"


def test_mapeo_cliente_juridico_lleva_datos_fiscales_completos():
    c = mapeo.mapear_cliente(
        {
            "tipo_documento_codigo": "31",
            "numero_documento": "901234567",
            "dv": "8",
            "tipo_persona_codigo": "1",
            "razon_social": "Taller El Pistón S.A.S.",
            "email": "a@b.co",
            "municipio_codigo": "11001",
            "regimen_codigo": "48",
        }
    )
    assert c["company"] == "Taller El Pistón S.A.S." and c["dv"] == "8" and c["legal_organization_code"] == "1"
    assert c["municipality_code"] == "11001" and c["tribute_code"] == "01"


def test_mapeo_cantidad_x_precio_menos_descuento_es_la_base_exacta():
    # precio con IVA 3 333 x 3 con descuento: la base nuestra debe reproducirse al centavo
    ln = LineaEmision(
        codigo="X", descripcion="X", unidad_codigo="94", cantidad=D("3"), precio_unitario=D("3333"),
        descuento_valor=D("500"), base_gravable=D("7981.51"), impuesto_valor=D("1516.49"), total_linea=D("9498"),
        tributo_codigo="01", tarifa_pct=D("19"),
    )  # fmt: skip
    it = mapeo.mapear_linea(ln)
    descuento = D(it["discount_amount"]) if "discount_amount" in it else D("0")
    assert D(it["quantity"]) * D(it["price"]) - descuento == ln.base_gravable
    assert descuento >= 0


def test_nc_sin_factura_referenciada_o_con_concepto_sin_equivalente_se_rechaza_antes_de_enviar():
    with pytest.raises(RechazoValidacion):
        mapeo.construir_nota_credito(_doc("NC", numero_documento_referenciado=None))
    with pytest.raises(RechazoValidacion):
        mapeo.construir_nota_credito(_doc("NC", concepto_nota_codigo="5"))


def test_rango_no_numerico_se_rechaza():
    with pytest.raises(RechazoValidacion):
        mapeo.construir_factura(_doc(rango_proveedor_id="R-FE-1"))


# ------------------------------------------------------------------------------------------------ secretos en logs
def test_el_filtro_de_logs_oculta_tokens_y_secretos(mock, prov, caplog):
    _token_ok(mock)
    mock.post("/v2/bills/validate").respond(201, json=_ok())
    prov.emitir_factura(_doc())  # registra token y secreto
    logger = logging.getLogger("prueba.secretos")
    logger.addFilter(logs.FiltroSecretos())
    with caplog.at_level(logging.INFO, logger="prueba.secretos"):
        logger.info("Authorization: Bearer %s secreto=%s", TOKEN, SECRETO)
    texto = caplog.text
    assert TOKEN not in texto and SECRETO not in texto and logs.CENSURA in texto
    assert logs.censurar_objeto({"access_token": "abc", "password": "x", "n": 1}) == {
        "access_token": logs.CENSURA,
        "password": logs.CENSURA,
        "n": 1,
    }
