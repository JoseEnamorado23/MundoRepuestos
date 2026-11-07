"""Proveedor fiscal SIMULADO: se comporta como uno real (números, CUFE y QR ficticios, latencia, rechazos) sin internet.

Sirve para pruebas y para una demo. Es idempotente por `reference_code` (como Factus) dentro del proceso y calcula
los totales con las mismas fórmulas que nosotros (suma de las bases y los impuestos de los snapshots).

Controles para pruebas/demos:
* `latencia_ms`: espera artificial por llamada.
* `rechazos`: probabilidad [0,1] de rechazar un documento NUEVO; es determinista por `reference_code` (un reintento
  del mismo documento da siempre el mismo veredicto).
* `fallar_siguientes(n, error)`: las próximas `n` llamadas lanzan `error` (p. ej. un `ErrorTransitorio`).
* `rechazar(reference_code)`: fuerza el rechazo de ese documento.
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from app.modules.fiscal.proveedores.base import (
    DocumentoEmision,
    ErrorConfiguracion,
    ErrorProveedor,
    ProveedorFiscal,
    RechazoValidacion,
    RespuestaProveedor,
)

PRIMER_CONSECUTIVO = 990000000


class ProveedorFiscalSimulado(ProveedorFiscal):
    nombre = "simulado"

    def __init__(self, *, latencia_ms: int = 0, rechazos: float = 0.0) -> None:
        self.latencia_ms = latencia_ms
        self.rechazos = rechazos
        self._lock = threading.Lock()
        self._docs: dict[str, dict] = {}  # reference_code -> documento emitido
        self._por_numero: dict[str, str] = {}
        self._contadores: dict[str, int] = {}
        self._fallos: list[ErrorProveedor] = []
        self._forzar_rechazo: set[str] = set()
        self.llamadas: list[tuple[str, str]] = []  # (operación, reference_code|numero) para afirmar en pruebas

    # ------------------------------------------------------------------------------------------ controles de prueba
    def fallar_siguientes(self, n: int, error: ErrorProveedor) -> None:
        with self._lock:
            self._fallos += [error] * n

    def rechazar(self, reference_code: uuid.UUID | str) -> None:
        self._forzar_rechazo.add(str(reference_code))

    @property
    def emitidos(self) -> int:
        return len(self._docs)

    # ------------------------------------------------------------------------------------------ internos
    def _simular(self, operacion: str, clave: str) -> None:
        self.llamadas.append((operacion, clave))
        if self.latencia_ms:
            time.sleep(self.latencia_ms / 1000)
        with self._lock:
            if self._fallos:
                raise self._fallos.pop(0)

    def _rechaza(self, ref: str) -> bool:
        if ref in self._forzar_rechazo:
            return True
        if self.rechazos <= 0:
            return False
        # determinista por referencia: el mismo documento siempre da el mismo veredicto
        valor = int(hashlib.sha256(ref.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return valor < self.rechazos

    def _respuesta(self, d: dict, http_status: int = 201) -> RespuestaProveedor:
        return RespuestaProveedor(
            estado="aceptado",
            numero=d["numero"],
            cufe=d["cufe"],
            qr_url=f"https://simulado.invalid/dian/searchqr?documentkey={d['cufe']}",
            url_publica=f"https://simulado.invalid/documentos/{d['cufe'][:32]}",
            validado_at=d["validado_at"],
            subtotal=d["subtotal"],
            impuesto_total=d["impuesto_total"],
            total=d["total"],
            advertencias=["RUT01: simulado"],
            http_status=http_status,
            crudo={"simulado": True, "data": {"number": d["numero"], "reference_code": d["ref"], "is_validated": True}},
        )

    def _emitir(self, tipo: str, doc: DocumentoEmision) -> RespuestaProveedor:
        ref = str(doc.reference_code)
        self._simular(f"emitir_{tipo}", ref)
        with self._lock:
            previo = self._docs.get(ref)
            if previo is not None:  # idempotente, igual que Factus
                return self._respuesta(previo, 200)
        if not doc.lineas:
            raise RechazoValidacion("Error de validación", errores=["items: El campo items es obligatorio."])
        if tipo == "NC" and not doc.numero_documento_referenciado:
            raise RechazoValidacion("Error de validación", errores=["bill_number: es obligatorio"], http_status=422)
        if self._rechaza(ref):
            raise RechazoValidacion(
                "La DIAN rechazó el documento.",
                errores=["Regla: FAJ43b, Rechazo: documento rechazado por el proveedor simulado"],
                http_status=201,
            )
        prefijo = doc.prefijo_resolucion or ("SIMF" if tipo == "FE" else "SIMN")
        with self._lock:
            n = self._contadores.get(prefijo, PRIMER_CONSECUTIVO - 1) + 1
            self._contadores[prefijo] = n
            cufe = hashlib.sha384(f"{ref}:{n}".encode()).hexdigest()
            d = {
                "ref": ref,
                "tipo": tipo,
                "numero": f"{prefijo}{n}",
                "cufe": cufe,
                "validado_at": datetime.now(UTC),
                "subtotal": sum((ln.base_gravable for ln in doc.lineas), Decimal(0)),
                "impuesto_total": sum((ln.impuesto_valor for ln in doc.lineas), Decimal(0)),
                "total": sum((ln.total_linea for ln in doc.lineas), Decimal(0)),
            }
            self._docs[ref] = d
            self._por_numero[d["numero"]] = ref
        return self._respuesta(d)

    # ------------------------------------------------------------------------------------------ interfaz
    def emitir_factura(self, doc: DocumentoEmision) -> RespuestaProveedor:
        return self._emitir("FE", doc)

    def emitir_nota_credito(self, doc: DocumentoEmision) -> RespuestaProveedor:
        return self._emitir("NC", doc)

    def _por(self, numero: str) -> dict:
        ref = self._por_numero.get(numero)
        if ref is None:
            raise ErrorConfiguracion(f"No se encontró el documento {numero}.", http_status=404)
        return self._docs[ref]

    def consultar_documento(self, tipo: Literal["FE", "NC"], numero: str) -> RespuestaProveedor:
        self._simular("consultar", numero)
        return self._respuesta(self._por(numero), 200)

    def descargar_pdf(self, tipo: Literal["FE", "NC"], numero: str) -> bytes:
        self._simular("pdf", numero)
        d = self._por(numero)
        texto = f"Documento simulado {d['numero']} CUFE {d['cufe'][:24]} total {d['total']}"
        return (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]>>endobj\n"
            b"%% " + texto.encode() + b"\ntrailer<</Root 1 0 R>>\n%%EOF\n"
        )

    def descargar_xml(self, tipo: Literal["FE", "NC"], numero: str) -> bytes:
        self._simular("xml", numero)
        d = self._por(numero)
        return f'<?xml version="1.0" encoding="UTF-8"?><Simulado numero="{d["numero"]}" cufe="{d["cufe"]}"/>'.encode()

    def eliminar_pendiente(self, tipo: Literal["FE", "NC"], reference_code: uuid.UUID) -> bool:
        self._simular("eliminar", str(reference_code))
        return False  # el simulado valida al instante: nunca hay documentos pendientes que borrar
