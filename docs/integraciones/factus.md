# Integración con Factus (facturación electrónica DIAN)

Proveedor tecnológico por API **v2**. Sandbox: `FACTUS_URL` (en `.env`). Código: `backend/app/modules/fiscal/` (`proveedores/`, `emision.py`, `router.py`) y `backend/app/workers/fiscal.py`. Credenciales solo en `.env` (`FACTUS_*`); un filtro de logs (`app/core/logs.py`) censura tokens y secretos en logs, excepciones y bitácora.

## 1. Arquitectura
* La venta/devolución crea el documento (`pendiente_envio`) y el evento `fiscal.emitir` en la MISMA transacción; la API nunca llama a Factus.
* `python -m app.workers.fiscal [--una-vez]` toma eventos con `FOR UPDATE SKIP LOCKED` en orden de `secuencia` (varios workers no duplican envíos). Cada documento en su transacción.
* `FISCAL_PROVEEDOR=factus|simulado`. El simulado (`ProveedorFiscalSimulado`) genera números/CUFE ficticios, con latencia (`FISCAL_SIMULADO_LATENCIA_MS`) y rechazos configurables (`FISCAL_SIMULADO_RECHAZOS`).
* Todo evento `fiscal.*` (p. ej. `fiscal.emitir`) es **local** de la sede (`sync.outbox_eventos.alcance = 'local'`, migración 0012, registro en `app/modules/sync/tipos_evento.py`): el agente de sync futuro solo replica `alcance = 'sincronizable'` y por tanto nunca los envía.

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

### 7.1 Corregir y reemitir una FE rechazada
`POST /fiscal/documentos/{id}/corregir` (`fiscal.gestionar`, auditado) cuando la DIAN rechazó la FE por datos del adquirente (p. ej. NIT/DV inválido). Cuerpo: `motivo` (obligatorio) y los campos del adquirente a cambiar: `tipo_documento_codigo, numero_documento, dv, tipo_persona_codigo, nombre_completo, razon_social, regimen_codigo, responsabilidades, email, telefono, direccion, municipio_codigo`. Montos, ítems, pagos y resolución NO se aceptan (422).
* Solo FE de venta en estado `rechazado`, nunca aceptada (sin CUFE) y aún no corregida. Una aceptada se corrige con NC.
* La rechazada pasa a `anulado` (`vigente=false`, sin NC) y se crea una FE nueva `pendiente_envio` para la misma venta: mismos ítems/impuestos/pagos/totales, snapshot del adquirente corregido, `documento_corrige_id` → la anterior y un `reference_code` nuevo (su `id`).
* Antes de enviar la nueva, el worker pide borrar en Factus el no validado anterior (`DELETE /v2/bills/destroy/reference/{ref}`; el 409 «factura pendiente por enviar» se resuelve igual). Es el flujo que documenta Factus: eliminar la no validada y crear una nueva.
* **Qué campos admite Factus cambiar:** la documentación de Factus no define cuáles campos de `customer` son editables en un reenvío; como se crea un documento nuevo (otro `reference_code`) cualquier dato del cliente puede cambiar. No se actualiza el maestro `identidad.terceros` (otro módulo): corríjalo aparte para próximas ventas.
* Las NC que esperaban la FE rechazada se emiten contra la nueva (el worker sigue `documento_corrige_id`).

## 8. CLI y operación
`python -m app.cli fiscal rangos | verificar | vincular <resolucion_id> <rango_id> | estado`. Rangos del sandbox: FE `389` (SETP 990000000–995000000), NC `390` (`NC`) o `1776` (`CRTE`); los rangos de NC no traen desde/hasta, por eso la resolución NC local usa 1..99999999. Hay dos rangos NC activos: el id es obligatorio. Docker: `docker compose --profile app up -d worker-fiscal`.

## 9. Pruebas
Unitarias con `respx` (sin red) y flujo simulado completo. Las pruebas del sandbox real llevan la marca `factus` y **no corren por defecto** (`addopts = -m 'not factus'` en `pyproject.toml`): consumen consecutivos del sandbox compartido. A mano, desde `backend/`, con `FACTUS_*` en `.env`: `uv run pytest -m factus -s` (se omiten sin credenciales).

## 10. Redondeo de centavos (§5) — investigación en la documentación de Factus
Se revisó developers.factus.com.co (facturas, redondeo, notas crédito, cambios v1→v2). Conclusión: **no es posible eliminar los descuentos de centavos desde nuestro lado**.
* `cash_rounding_amount` (opcional, máx. ±500.00) NO redondea el documento: solo concilia la diferencia entre la suma de `payment_details[].amount` y el `total`. Ya lo usamos para el redondeo de pago en efectivo (`documentos_fiscales.redondeo`). No existe `PayableRoundingAmount` ni otro campo de redondeo de líneas; las notas crédito ni siquiera aceptan `cash_rounding_amount`.
* `price`, `quantity`, `discount_rate`, `discount_amount` y `rate`: «máximo dos decimales». No hay forma documentada de enviar más decimales.
* En v2 `price` es neto de IVA; no existe un precio con IVA incluido (en v1 sí se manejaba bruto).
Por eso se deja el mapeo como está (§5: precio redondeado hacia arriba + descuento = diferencia). Como el desvío es de centavos por línea, queda como pregunta para el contador (§11, punto 1) y para soporte de Factus (§12). Las 3 pruebas del sandbox no se volvieron a correr: no hubo cambio de código en el mapeo.

## 11. Dudas abiertas
1. **Contador:** ¿son aceptables en la representación gráfica de la FE los descuentos de centavos en líneas sin descuento real (§5)? Es consecuencia del límite de 2 decimales de `price` y de que Factus no ofrece precio con IVA incluido ni redondeo de líneas (§10).
2. Forma exacta de la respuesta 409 «pendiente» real: no se pudo provocar en el sandbox; hoy se trata por código HTTP (preguntas para soporte, §12).
3. Unidad de `X-RateLimit-Reset` (§12).
4. Aviso CBF02 en la NC (§12): informativo.
5. Las listas de municipios y unidades de medida de Factus no se contrastaron completas con las nuestras.
6. Archivos: API y `worker-fiscal` montan el MISMO volumen nombrado `mundorepuestos_media` en `/data/media` (`docker-compose.yml`, servicios `api` y `worker-fiscal`, ambos con `MEDIA_DIR=/data/media`; `tests/test_compose_almacenamiento.py` lo vigila). Verificado con dos contenedores sobre un volumen nombrado: lo que escribe uno lo lee el otro. Con varios nodos o la nube se usará S3 (etapa 2).

## 12. Preguntas para soporte de Factus
Listas para enviar (sandbox `api-sandbox.factus.com.co`, API v2):

1. **Error 409 «factura pendiente por enviar a la DIAN».** La documentación indica eliminar la factura por `reference_code` y crear una nueva, pero no muestra el cuerpo exacto del 409 ni cómo reproducirlo. (a) ¿Cuál es el JSON completo de esa respuesta (campos `message`, `data`, `is_validated`)? (b) ¿En qué casos concretos aparece: documento creado sin validar tras un timeout, rechazo de la DIAN, o ambos? (c) Tras `DELETE /v2/bills/destroy/reference/{reference_code}` ¿podemos reutilizar el mismo `reference_code`, o debemos generar uno nuevo? Nosotros usamos uno nuevo al corregir un rechazo. (d) En notas crédito el texto habla de «documento soporte»: ¿es un error de copia de la documentación?
2. **Unidad de `X-RateLimit-Reset`.** La documentación dice «segundos o timestamp». ¿Es una cantidad de segundos restantes o un timestamp (Unix en segundos, milisegundos o fecha)? ¿Es igual en todos los endpoints? Además, la documentación indica 80 solicitudes por minuto por usuario y en el sandbox observamos 120: ¿cuál es el límite vigente en sandbox y en producción?
3. **Aviso «factura referenciada» en la nota crédito (CBF02).** Al validar una NC con `bill_number` correcto (factura aceptada y ya consultable) el sandbox devuelve la notificación «no se informó la factura referenciada». (a) ¿Es esperado en habilitación, o falta algún campo (p. ej. datos del documento referenciado distintos de `bill_number`)? (b) ¿Se repetirá en producción? (c) ¿Afecta de algún modo la validez de la NC ante la DIAN?
4. **Redondeo y decimales.** (a) ¿Existe, o está previsto, precio unitario con más de 2 decimales o con IVA incluido, o un redondeo a nivel de documento/línea distinto de `cash_rounding_amount`? (b) ¿`cash_rounding_amount` modifica el total a pagar o solo concilia pagos y total? (c) ¿Se admite en notas crédito?
5. **Reenvío tras rechazo.** Al corregir datos del `customer` de una factura rechazada por la DIAN, ¿es válido eliminarla por referencia y emitir otra con un `reference_code` nuevo, o hay un flujo preferido? ¿Se consume consecutivo del rango por cada intento rechazado?
