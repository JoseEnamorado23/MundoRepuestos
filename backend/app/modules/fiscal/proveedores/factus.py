"""Adaptador de Factus (API v2). Documentación y comportamiento verificado en el sandbox: docs/integraciones/factus.md.

* Autenticación OAuth2 `password`; el token (60 min) se guarda en memoria y se renueva con `refresh_token` ANTES de
  vencer (y una vez más ante un 401). Los tokens y claves se registran en el filtro de logs: nunca se imprimen.
* Cada llamada lleva timeouts. Errores de red/timeout/5xx/429 -> `ErrorTransitorio`; validación (422/400) y rechazos
  de la DIAN -> `RechazoValidacion`; credenciales/ruta/rango -> `ErrorConfiguracion`.
* Idempotencia: el `reference_code` (= id del documento fiscal) hace que reenviar un documento ya procesado devuelva el
  MISMO documento (verificado), por lo que reintentar tras un timeout nunca duplica.
"""

from __future__ import annotations

import base64
import logging
import ssl
import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx

from app.core.logs import registrar_secreto
from app.modules.fiscal.proveedores import factus_mapeo as mapeo
from app.modules.fiscal.proveedores.base import (
    ConflictoPendiente,
    DocumentoEmision,
    ErrorConfiguracion,
    ErrorProveedor,
    ErrorTransitorio,
    ProveedorFiscal,
    RechazoValidacion,
    RespuestaProveedor,
)

log = logging.getLogger("fiscal.factus")
BOGOTA = ZoneInfo("America/Bogota")
MARGEN_TOKEN_SEG = 120  # se renueva el token 2 min antes de que venza
RUTAS = {"FE": "bills", "NC": "credit-notes"}


def _contexto_ssl(sistema: bool) -> ssl.SSLContext | bool:
    """Almacén de certificados del SO (necesario tras un proxy TLS corporativo) o los de `certifi`."""
    if not sistema:
        return True
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:  # pragma: no cover - truststore es dependencia del proyecto
        return True


def _decimal(valor: Any) -> Decimal | None:
    try:
        return None if valor in (None, "") else Decimal(str(valor))
    except InvalidOperation:
        return None


def _fecha(valor: str | None) -> datetime | None:
    """Factus informa `DD-MM-YYYY hh:mm:ss AM/PM` (hora de Colombia)."""
    if not valor:
        return None
    for formato in ("%d-%m-%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(valor, formato).replace(tzinfo=BOGOTA)
        except ValueError:
            continue
    return None


def aplanar_errores(errores: Any) -> list[str]:
    """`errors` de Factus: dict regla->texto (DIAN) o campo->[textos] (validación)."""
    if not errores:
        return []
    if isinstance(errores, dict):
        out = []
        for k, v in errores.items():
            if isinstance(v, (list, tuple)):
                out += [f"{k}: {x}" for x in v]
            else:
                out.append(f"{k}: {v}" if str(k) not in str(v) else str(v))
        return out
    if isinstance(errores, (list, tuple)):
        return [str(x) for x in errores]
    return [str(errores)]


def es_rechazo_dian(texto: str) -> bool:
    """Una regla de la DIAN es RECHAZO solo si dice «Rechazo»; «Notificación» es informativa."""
    return "rechazo" in texto.lower()


class ProveedorFiscalFactus(ProveedorFiscal):
    nombre = "factus"

    def __init__(
        self,
        *,
        url: str,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        timeout_conexion: float = 10.0,
        timeout_lectura: float = 60.0,
        certificados_sistema: bool = True,
        http: httpx.Client | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self._cred = {
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password,
        }
        for v in (client_secret, password):
            registrar_secreto(v)
        self._http = http or httpx.Client(
            base_url=self.url,
            timeout=httpx.Timeout(timeout_lectura, connect=timeout_conexion),
            verify=_contexto_ssl(certificados_sistema),
            headers={"Accept": "application/json", "User-Agent": "mundorepuestos-fiscal/1"},
        )
        self._lock = threading.Lock()
        self._access: str | None = None
        self._refresh: str | None = None
        self._vence: float = 0.0  # time.monotonic()

    # ------------------------------------------------------------------------------------------ autenticación
    def _token(self, *, forzar: bool = False) -> str:
        with self._lock:
            if not forzar and self._access and time.monotonic() < self._vence - MARGEN_TOKEN_SEG:
                return self._access
            if self._refresh and not forzar:
                if self._pedir_token(
                    {
                        "grant_type": "refresh_token",
                        "client_id": self._cred["client_id"],
                        "client_secret": self._cred["client_secret"],
                        "refresh_token": self._refresh,
                    },
                    tolerar_fallo=True,
                ):
                    return self._access  # type: ignore[return-value]
            self._pedir_token({"grant_type": "password", **self._cred}, tolerar_fallo=False)
            return self._access  # type: ignore[return-value]

    def _pedir_token(self, datos: dict[str, str], *, tolerar_fallo: bool) -> bool:
        try:
            r = self._http.post("/oauth/token", data=datos)
        except httpx.HTTPError as e:
            raise ErrorTransitorio(f"No se pudo autenticar con Factus ({type(e).__name__}).") from e
        if r.status_code == 200:
            try:
                j = r.json()
                self._access = j["access_token"]
                self._refresh = j.get("refresh_token") or self._refresh
                self._vence = time.monotonic() + float(j.get("expires_in", 3600))
            except (ValueError, KeyError) as e:
                raise ErrorTransitorio("Respuesta de autenticación de Factus ilegible.") from e
            registrar_secreto(self._access)
            registrar_secreto(self._refresh)
            return True
        if tolerar_fallo and r.status_code in (400, 401, 403):
            self._refresh = None  # refresh vencido o revocado: se vuelve a la clave
            return False
        if r.status_code in (400, 401, 403):
            raise ErrorConfiguracion(
                "Factus rechazó las credenciales (revise FACTUS_* en .env).", http_status=r.status_code
            )
        if r.status_code == 429 or r.status_code >= 500:
            raise ErrorTransitorio(
                f"Factus no pudo autenticar ahora (HTTP {r.status_code}).",
                http_status=r.status_code,
                reintentar_en=self._retry_after(r),
            )
        raise ErrorConfiguracion(
            f"Respuesta inesperada de autenticación (HTTP {r.status_code}).", http_status=r.status_code
        )

    # ------------------------------------------------------------------------------------------ transporte
    @staticmethod
    def _retry_after(r: httpx.Response) -> float | None:
        for cab in ("Retry-After", "X-RateLimit-Reset"):
            try:
                v = float(r.headers.get(cab, ""))
            except ValueError:
                continue
            # X-RateLimit-Reset puede ser segundos o un timestamp: solo se acepta si es plausible como espera
            if 0 < v <= 3600:
                return v
        return None

    def _llamar(self, metodo: str, ruta: str, *, json: Any = None) -> httpx.Response:
        for intento in (1, 2):
            token = self._token(forzar=intento == 2)
            try:
                r = self._http.request(metodo, ruta, json=json, headers={"Authorization": f"Bearer {token}"})
            except httpx.TimeoutException as e:
                raise ErrorTransitorio(f"Tiempo de espera agotado hablando con Factus ({type(e).__name__}).") from e
            except httpx.HTTPError as e:
                raise ErrorTransitorio(f"Error de red hablando con Factus ({type(e).__name__}).") from e
            if r.status_code == 401 and intento == 1:
                continue  # token vencido o revocado: se pide uno nuevo y se repite UNA vez
            return r
        raise ErrorTransitorio("Factus rechazó el token de acceso renovado (401).", http_status=401)  # pragma: no cover

    @staticmethod
    def _json(r: httpx.Response) -> dict[str, Any]:
        try:
            j = r.json()
        except ValueError as e:
            raise ErrorTransitorio(
                f"Factus devolvió una respuesta que no es JSON (HTTP {r.status_code}).", http_status=r.status_code
            ) from e
        return j if isinstance(j, dict) else {"data": j}

    def _clasificar_error(self, r: httpx.Response, cuerpo: dict[str, Any]) -> ErrorProveedor:
        """Convierte una respuesta HTTP de error en la excepción que el worker sabe tratar."""
        s = r.status_code
        mensaje = str(cuerpo.get("message") or f"HTTP {s}")
        data = cuerpo.get("data") if isinstance(cuerpo.get("data"), dict) else {}
        errores = aplanar_errores(data.get("errors") or cuerpo.get("errors"))
        detalle = {"http_status": s, "message": mensaje, "errors": errores}
        if s == 409:
            return ConflictoPendiente(mensaje, http_status=s, detalle=detalle)
        if s == 429:
            return ErrorTransitorio(mensaje, http_status=s, reintentar_en=self._retry_after(r) or 60.0, detalle=detalle)
        if s in (408, 425) or s >= 500:
            return ErrorTransitorio(mensaje, http_status=s, detalle=detalle)
        if s in (400, 422):
            return RechazoValidacion(mensaje, errores=errores or [mensaje], http_status=s, detalle=detalle)
        if s in (401, 402, 403, 404):
            return ErrorConfiguracion(mensaje, http_status=s, detalle=detalle)
        return RechazoValidacion(mensaje, errores=errores or [mensaje], http_status=s, detalle=detalle)

    # ------------------------------------------------------------------------------------------ operaciones
    def _enviar(self, tipo: Literal["FE", "NC"], cuerpo: dict[str, Any]) -> RespuestaProveedor:
        ruta = f"/v2/{RUTAS[tipo]}/validate"
        r = self._llamar("POST", ruta, json=cuerpo)
        j = self._json(r)
        if r.status_code not in (200, 201):
            raise self._clasificar_error(r, j)
        return self._interpretar(j, r.status_code)

    def emitir_factura(self, doc: DocumentoEmision) -> RespuestaProveedor:
        return self._enviar("FE", mapeo.construir_factura(doc))

    def emitir_nota_credito(self, doc: DocumentoEmision) -> RespuestaProveedor:
        return self._enviar("NC", mapeo.construir_nota_credito(doc))

    def consultar_documento(self, tipo: Literal["FE", "NC"], numero: str) -> RespuestaProveedor:
        r = self._llamar("GET", f"/v2/{RUTAS[tipo]}/{numero}")
        j = self._json(r)
        if r.status_code != 200:
            raise self._clasificar_error(r, j)
        return self._interpretar(j, r.status_code)

    def _interpretar(self, j: dict[str, Any], http_status: int) -> RespuestaProveedor:
        d = j.get("data") if isinstance(j.get("data"), dict) else {}
        textos = aplanar_errores(d.get("errors"))
        rechazos = [t for t in textos if es_rechazo_dian(t)]
        if rechazos:
            raise RechazoValidacion(
                "La DIAN rechazó el documento.", errores=rechazos, http_status=http_status, detalle={"errors": textos}
            )
        totales = d.get("totals") or {}
        links = d.get("links") or {}
        validado = bool(d.get("is_validated"))
        return RespuestaProveedor(
            estado="aceptado" if validado else "pendiente",
            numero=d.get("number"),
            cufe=d.get("cufe") or d.get("cude"),
            qr_url=links.get("qr"),
            url_publica=links.get("public_url"),
            validado_at=_fecha(d.get("validated_at")),
            subtotal=_decimal(totales.get("gross_amount")),
            impuesto_total=_decimal(totales.get("tax_amount")),
            total=_decimal(totales.get("total")),
            advertencias=textos,
            http_status=http_status,
            crudo=self.sanear(j),
        )

    def _descargar(self, tipo: str, numero: str, sufijo: str, campo: str) -> bytes:
        r = self._llamar("GET", f"/v2/{RUTAS[tipo]}/{numero}/{sufijo}")
        j = self._json(r)
        if r.status_code != 200:
            raise self._clasificar_error(r, j)
        try:
            return base64.b64decode(j["data"][campo], validate=False)
        except (KeyError, TypeError, ValueError) as e:
            raise ErrorTransitorio("Factus devolvió un archivo ilegible.", http_status=r.status_code) from e

    def descargar_pdf(self, tipo: Literal["FE", "NC"], numero: str) -> bytes:
        return self._descargar(tipo, numero, "download-pdf", "pdf_base_64_encoded")

    def descargar_xml(self, tipo: Literal["FE", "NC"], numero: str) -> bytes:
        return self._descargar(tipo, numero, "download-xml", "xml_base_64_encoded")

    def eliminar_pendiente(self, tipo: Literal["FE", "NC"], reference_code: uuid.UUID) -> bool:
        ruta = (
            f"/v2/bills/destroy/reference/{reference_code}"
            if tipo == "FE"
            else f"/v2/credit-notes/reference/{reference_code}"
        )
        r = self._llamar("DELETE", ruta)
        if r.status_code in (200, 204):
            return True
        if r.status_code in (404, 409):  # no existe, o ya está validado por la DIAN (no se puede borrar)
            return False
        raise self._clasificar_error(r, self._json(r))

    # ------------------------------------------------------------------------------------------ rangos (CLI)
    def listar_rangos(self) -> list[dict[str, Any]]:
        """Rangos de numeración de la empresa en Factus (para configurar `id_rango_proveedor`)."""
        pagina, out = 1, []
        while True:
            r = self._llamar("GET", f"/v2/numbering-ranges?page={pagina}")
            j = self._json(r)
            if r.status_code != 200:
                raise self._clasificar_error(r, j)
            d = j.get("data") or {}
            out += d.get("data") or []
            pag = d.get("pagination") or {}
            if pagina >= int(pag.get("last_page") or 1):
                return out
            pagina += 1

    # ------------------------------------------------------------------------------------------ utilidades
    @staticmethod
    def sanear(j: dict[str, Any]) -> dict[str, Any]:
        """Copia de la respuesta apta para guardar: sin logos ni nada que parezca un secreto."""
        from app.core.logs import censurar_objeto

        copia = censurar_objeto(j)
        try:
            copia["data"]["company"].pop("url_logo", None)  # type: ignore[index, union-attr]
        except (KeyError, TypeError, AttributeError):
            pass
        return copia  # type: ignore[return-value]

    def cerrar(self) -> None:
        self._http.close()
