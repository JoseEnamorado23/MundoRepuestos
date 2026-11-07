# Arquitectura del backend

Monolito modular (FastAPI + SQLAlchemy síncrono + PostgreSQL). Cada módulo es un schema de PostgreSQL
(ver `base-de-datos/modelo.md`). Este documento fija **las capas, las reglas de importación y las decisiones de
diseño** que `backend/tests/test_arquitectura.py` hace cumplir.

## Capas

```
api  ->  aplicacion  ->  modules (servicios)  ->  core
```

| Capa | Dónde | Qué hace | No puede |
|------|-------|----------|----------|
| `core` | `app/core/` | Configuración, errores, dinero, seguridad, base de modelos, utilidades | Importar `modules`, `aplicacion` ni `api` (única excepción: el registro `app.models` de `core/db.py`) |
| servicios de módulo | `app/modules/<m>/` (todo salvo `router*.py` y `schemas.py`) | Reglas de negocio de UN módulo; no hacen `commit` | Importar `api`, `aplicacion`, `main`, `cli` |
| bordes HTTP de módulo | `app/modules/<m>/router*.py`, `schemas.py` | Validar la entrada, llamar a un caso de uso y responder | Contener reglas de negocio ni coordinar módulos |
| `aplicacion` | `app/aplicacion/` | **Casos de uso**: coordinan varios módulos en UNA transacción | Importar `api`, `main`, `cli` |
| `api` | `app/api/` | Dependencias HTTP (sesión por petición, autenticación, permisos, paginación, errores) | Importar `aplicacion` |

### Casos de uso (`app/aplicacion/`)

| Archivo | Casos de uso | Coordina |
|---------|--------------|----------|
| `ventas.py` | `confirmar_venta` (venta + factura electrónica `pendiente_envio`), `suspender_venta`, `retomar_espera`, `detalle_venta`, `ticket` | ventas + fiscal |
| `workers/fiscal.py` (fuera de `aplicacion/`) | worker fiscal: envía los documentos `pendiente_envio` al proveedor (`modules/fiscal/emision.py`) | fiscal + sync |
| `devoluciones.py` | `registrar_devolucion` (kardex, reembolso y nota crédito `pendiente_envio`), `detalle_devolucion` | ventas + fiscal |
| `turnos.py` | `abrir_turno`, `registrar_movimiento_caja`, `cerrar_turno`, `cierre_forzado`, `informe_cierre` | cajas + ventas (totales del turno) |
| `demo.py`, `catalogo_demo.py` | `datos-demo [--catalogo]` | organizacion + identidad + cajas + fiscal + inventario + catalogo + ventas |

Los servicios **devuelven datos** y el caso de uso decide qué sigue: por ejemplo `ventas.confirmar_venta` devuelve la
venta confirmada y es `aplicacion.ventas.confirmar_venta` quien crea el documento fiscal; `cajas.turnos` recibe los
totales del turno como un dato (`TotalesTurno`) en vez de un *callback* inyectado por el router. Ya no existe ningún
callback construido en un router.

Por simplicidad, un router puede llamar directamente a un servicio de SU PROPIO módulo cuando la operación no coordina
nada (p. ej. listar ventas en espera, buscar clientes). En cuanto una operación toca dos módulos, es un caso de uso.

## Dependencias entre módulos

Solo "hacia abajo": `referencia → organizacion → identidad → catalogo → inventario → compras → cajas → ventas →
pedidos → fiscal`. `sync` y `auditoria` son transversales (los usa cualquiera; ellos no dependen de módulos de negocio).

Lista **congelada** de bordes permitidos (cada fila: el módulo que importa y los módulos de los que importa). Una
dependencia nueva exige editar `DEPENDENCIAS` en `tests/test_arquitectura.py` y esta tabla, a propósito:

| Módulo | Importa de |
|--------|-----------|
| `referencia` | — |
| `organizacion` | `auditoria`, `sync` |
| `identidad` | `auditoria`, `organizacion`, `sync` |
| `catalogo` | `auditoria`, `organizacion`, `sync` |
| `inventario` | `auditoria`, `catalogo`, `identidad`, `organizacion`, `sync` |
| `compras` | — |
| `cajas` | `auditoria`, `identidad`, `inventario`, `organizacion`, `referencia`, `sync` |
| `ventas` | `auditoria`, `cajas`, `catalogo`, `identidad`, `inventario`, `organizacion`, `referencia`, `sync` |
| `pedidos` | — |
| `fiscal` | `auditoria`, `cajas`, `identidad`, `organizacion`, `sync`, `ventas` |
| `auditoria` | `sync` |
| `sync` | — |

> **Desviación consciente de la regla "los módulos no se importan entre sí"**: prohibirlo del todo obligaría a
> duplicar modelos o a pasar todo por eventos, un refactor grande sin beneficio hoy. Se aplica una regla verificable:
> solo hacia abajo y solo los bordes de la tabla (lecturas y servicios documentados). Ejemplo corregido en 0010:
> `inventario` importaba `cajas` (hacia arriba) para consumir autorizaciones; ahora esa función vive en
> `identidad.autorizaciones`, que es donde está la tabla.

## Políticas de autorización (0010)

`organizacion.politicas` evalúa la política de cada acción sensible (clave `autorizacion.<accion>` en
`configuracion_sede`) y `cajas.politicas_pos.aplicar_politica` la aplica: `libre` (nada), `revision_posterior`
(queda en `auditoria.revisiones`) o `requiere_autorizacion` (autorización de OTRO empleado, por PIN de supervisor en la
caja o por aprobación remota). Ver `base-de-datos/modelo.md` §9.4 y `permisos.md`.

## Aprobación remota: ¿polling, long-poll o SSE?

**Decisión: polling corto cada 2 s** (`GET /pos/solicitudes-autorizacion/{id}`; el servidor devuelve `poll_ms`).

* SQLAlchemy es **síncrono** y los endpoints son `def`: FastAPI los ejecuta en un *threadpool* (por defecto ~40 hilos).
  Un *long-poll* o un SSE mantienen un hilo (y una conexión de la sesión por petición) **ocupado** mientras el cajero
  espera; con varias cajas esperando se agotaría el pool y se frenarían ventas. El polling usa una petición corta
  (una consulta indexada) y libera el hilo de inmediato.
* Hay un solo establecimiento y pocas cajas: ~0,5 consultas/s por solicitud pendiente, irrelevante para PostgreSQL.
* El POS debe funcionar bien en red local inestable: el polling no requiere conexiones largas ni reconexión.
* El vencimiento (por defecto 5 min, `autorizacion.solicitud_expira_min`) se aplica de forma perezosa al consultar o
  listar, así que no hace falta un proceso en segundo plano.
* Si algún día hay decenas de cajas esperando a la vez, el cambio natural es SSE sobre un servidor asíncrono (o
  `LISTEN/NOTIFY`), sin tocar el contrato de las solicitudes.

## Convenciones de transacción

Una sesión por petición (`Db`): *commit* al final, *rollback* ante cualquier error; ni los servicios ni los casos de
uso hacen *commit*. Cuando un error de dominio debe dejar rastro (intento rechazado, solicitud vencida) el router
envuelve el caso de uso en `persistir_si_falla(db)`.
