# Integración con Factus (facturación electrónica DIAN)

Proveedor tecnológico por API **v2**. Sandbox: `FACTUS_URL` (en `.env`). Código: `backend/app/modules/fiscal/` (`proveedores/`, `emision.py`, `router.py`) y `backend/app/workers/fiscal.py`. Credenciales solo en `.env` (`FACTUS_*`); un filtro de logs (`app/core/logs.py`) censura tokens y secretos en logs, excepciones y bitácora.

## 1. Arquitectura
* La venta/devolución crea el documento (`pendiente_envio`) y el evento `fiscal.emitir` en la MISMA transacción; la API nunca llama a Factus.
* `python -m app.workers.fiscal [--una-vez]` toma eventos con `FOR UPDATE SKIP LOCKED` en orden de `secuencia` (varios workers no duplican envíos). Cada documento en su transacción.
* `FISCAL_PROVEEDOR=factus|simulado`. El simulado (`ProveedorFiscalSimulado`) genera números/CUFE ficticios, con latencia (`FISCAL_SIMULADO_LATENCIA_MS`) y rechazos configurables (`FISCAL_SIMULADO_RECHAZOS`).
* Los eventos `fiscal.emitir` son locales de la sede: el agente de sync futuro NO debe replicarlos.

## 2. Autenticación
`POST /oauth/token` (password grant). El token se cachea en memoria; se renueva con `refresh_token` 120 s antes de vencer; si el refresh falla se vuelve a la clave; un 401 renueva y repite UNA vez. Credenciales inválidas → error de configuración (alerta `configuracion`).

## 3. Campos mapeados (origen en nuestro modelo)
Todo sale del SNAPSHOT del documento (`fiscal.documentos_fiscales*`), nunca de maestros.

| Factus | Origen |
|---|---|
| `reference_code` | `documentos_fiscales.id` (idempotencia) |
| `numbering_range_id` | `resoluciones_numeracion.id_rango_proveedor` (numérico; ver `fiscal rangos` / `fiscal vincular`) |
| `document` `01`, `operation_type` `10` | fijos (FE estándar) |
| `customer.*` | `adquirente_snapshot`. Consumidor final: identificación genérica + `names="Consumidor Final"`. Otro: documento, `dv` (NIT), `legal_organization_code` (1/2), `company`/`names`, email, teléfono, dirección, `municipality_code`, `tribute_code`, responsabilidades |
| `items[]` | `documentos_fiscales_items` (ver §5) |
| `payment_details[]` | `documentos_fiscales_pagos` |
| `cash_rounding_amount` | `documentos_fiscales.redondeo` |
| `observation` | «Venta POS No. {numero_interno}» |
| NC: `bill_number`, `correction_concept_code`, `customization_id="20"`, `numbering_range_id` | número aceptado de la FE original, concepto de la devolución, rango NC |

Equivalencias (`proveedores/equivalencias.py`): medio de pago `ZZ`→`ZZZ`; conceptos de nota 1–4 → 1–4 (el 5 no tiene equivalente y se rechaza antes de enviar). La v2 usa **códigos**, así que no hay tabla de IDs propios; las únicas ids propias son los rangos de numeración (se vinculan con el CLI).

## 4. Errores y clasificación
| Situación | Clase | Efecto |
|---|---|---|
| red, timeout, 5xx, 408/425, 429 (respeta `Retry-After`) | transitorio | sigue `pendiente_envio`; backoff exponencial con jitter (`FISCAL_BACKOFF_BASE_SEG`, tope `FISCAL_BACKOFF_MAX_SEG`); cuenta intentos; al llegar a `FISCAL_MAX_INTENTOS` → alerta `reintentos_agotados` |
| 400/422, o `errors` con «Rechazo» de la DIAN | rechazo de validación | `rechazado`, detalle guardado, alerta `rechazado`, sin reintento automático |
| 409 (documento pendiente sin validar bloquea el envío) | conflicto | se intenta borrar el pendiente remoto por `reference_code` y se reintenta como transitorio |
| 401/402/403/404 | configuración | reintentos espaciados + alerta `configuracion` |
| Reenvío del mismo `reference_code` | idempotente | Factus devuelve el documento existente; nunca se emite duplicado |

Las «Notificaciones» de la DIAN (p. ej. FAJ43b, RUT01) NO son rechazo: se guardan como advertencias. Una NC espera (15 s, o 300 s si la FE fue rechazada, con alerta `nota_sin_factura`) a que su FE esté aceptada. Cada intento y respuesta va a `documentos_fiscales_eventos` (saneado, sin secretos ni logos).

## 5. Totales (precio con o sin IVA)
Factus: `price` es **neto de IVA y antes de descuento**, máx. 2 decimales (cantidad también); el IVA se calcula sobre `cantidad×precio − descuento`. Nuestro snapshot guarda `base_gravable` ya calculada. Para que Factus parta de la MISMA base: `precio = ⌈neto/cantidad⌉` a 2 decimales y `descuento = cantidad×precio − base_gravable` (≥ 0), de modo que `cantidad×precio − descuento = base_gravable` exacto. Consecuencia aceptada: líneas sin descuento real pueden llevar un descuento de centavos. Cantidades con más de 2 decimales se envían como cantidad 1 con el neto de la línea y la cantidad real en el nombre.

**Verificado en el sandbox al peso** (FE consumidor final, FE con NIT, NC parcial): sin `totales_descuadrados`. Si algún día difieren, el worker abre la alerta `totales_descuadrados` y NO ajusta nada solo.

## 6. Aceptación
Se guardan prefijo, consecutivo, `numero_completo`, CUFE/CUDE, QR, fechas y `proveedor_documento_id`; el PDF y el XML se bajan al `Almacenamiento` (`fiscal/{empresa}/{año}/{id}.pdf|xml`; si falla la descarga se reintenta en cada ciclo). El contador de la resolución solo avanza y un número fuera de rango abre una alerta.

## 7. Backoffice y POS
`GET /fiscal/documentos` (estado, tipo, desde, hasta, cliente), `GET /fiscal/documentos/{id}` (eventos y alertas), `POST /fiscal/documentos/{id}/reintentar` (`fiscal.gestionar`; solo rechazados o reintentos agotados; auditado; no crea otro documento), `GET /fiscal/documentos/{id}/pdf`, `GET /fiscal/alertas`, `POST /fiscal/alertas/{id}/resolver`. POS: la tirilla trae número/CUFE/QR cuando está aceptado y una leyenda por estado; `GET /pos/ventas/{id}/estado-fiscal` es la consulta liviana (el POS repite hasta `definitivo=true`). `GET /health` incluye `fiscal` (worker activo según el latido, pendientes, rechazados) y queda `degradado` si hay pendientes y el worker no late.

## 8. CLI y operación
`python -m app.cli fiscal rangos | verificar | vincular <resolucion_id> <rango_id> | estado`. Rangos del sandbox: FE `389` (SETP 990000000–995000000), NC `390` (`NC`) o `1776` (`CRTE`); los rangos de NC no traen desde/hasta, por eso la resolución NC local usa 1..99999999. Hay dos rangos NC activos: el id es obligatorio. Docker: `docker compose --profile app up -d worker-fiscal`.

## 9. Pruebas
Unitarias con `respx` (sin red) y flujo simulado completo; `pytest -m factus -s` corre contra el sandbox real (se omite sin credenciales) y consume consecutivos del sandbox compartido.

## 10. Dudas abiertas
1. Forma exacta de la respuesta 409 «pendiente» real: no se pudo provocar en el sandbox; hoy se trata por código HTTP.
2. Unidad de `X-RateLimit-Reset` (se acepta solo si parece una espera ≤ 1 h; si no, 60 s). Límite observado: 120 solicitudes/min.
3. El sandbox emite la notificación CBF02 («no se informó la factura referenciada») en NC aunque `bill_number` es correcto: informativa.
4. Las listas de municipios y unidades de medida de Factus no se contrastaron completas con las nuestras.
5. Confirmar con contabilidad que los descuentos de centavos de §5 son aceptables en la representación gráfica.
6. El PDF se guarda en el `Almacenamiento` del worker; con contenedores, API y worker deben compartir almacenamiento (S3 en la etapa 2).
