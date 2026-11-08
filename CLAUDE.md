# MundoRepuestos

Sistema de punto de venta (POS) + e-commerce para una tienda de repuestos automotrices en Colombia.
Idioma del proyecto: **español** (código de dominio, tablas, columnas, docs, commits). Moneda: COP. Zona horaria: America/Bogota.

## Reglas de trabajo (OBLIGATORIAS)
- **NO hacer `git commit` ni `git push`** (ni crear ramas/tags). Los commits los hace el usuario.
- **NO instalar dependencias globales** (nada de `npm -g`, `pip` fuera de un venv, ni instaladores del sistema). Usar entornos del proyecto (`.venv`, `node_modules`) o Docker.
- **Pedir confirmación antes de cambios destructivos**: borrar archivos/carpetas, `docker compose down -v`, `DROP`/`TRUNCATE`, resetear la BD, sobrescribir archivos existentes que no se hayan leído, migraciones que pierdan datos.
- No avanzar a la siguiente fase (modelos, migraciones, API) sin aprobación explícita del usuario.
- Nunca poner secretos reales en archivos versionados; solo en `.env` (ignorado por git). `.env.example` lleva valores de ejemplo.

## Arquitectura (decidida)
Despliegue híbrido **local-first**:
- **EDGE**: servidor en la tienda (mini PC con Docker). El POS habla SOLO con este servidor y debe funcionar sin internet.
- **CLOUD**: la nube. Corre el MISMO backend y el MISMO esquema PostgreSQL.
- Un **agente de sync** replica local <-> nube con patrón **outbox/inbox**.
- La nube es fuente de verdad de catálogo, precios, clientes y pedidos web. El local es autónomo para vender (ventas, kardex, turnos, documentos fiscales POS son "propiedad" de la sede).
- Multi-sede desde el inicio (arrancamos con una).

## Stack
- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, PostgreSQL 16. Monolito modular.
- Frontends (consumen la API): tienda en línea (Next.js), backoffice, POS (PWA/Tauri en kiosko).
- Facturación electrónica DIAN vía proveedor tecnológico por API (sin elegir: Factus, Alegra e-provider, The Factory HKA). Documentos: FE, documento equivalente POS electrónico, notas crédito/débito de FE, notas de ajuste del documento equivalente. Cada caja tiene su propia resolución/prefijo.
- Hardware POS: lector de código de barras, impresora térmica ESC/POS 80 mm, cajón monedero, impresora de etiquetas.
- Infra local: `docker compose up -d db` (PostgreSQL 16, healthcheck). `docker compose --profile tools up -d adminer` para Adminer.

## Módulos = schemas de PostgreSQL
`identidad`, `organizacion`, `catalogo`, `inventario`, `compras`, `cajas`, `ventas`, `pedidos`, `fiscal`, `sync`, `auditoria` (+ `referencia` para tablas de códigos DIAN). Un módulo no escribe en tablas de otro; se comunica por servicios/eventos. Dependencias permitidas solo "hacia abajo": referencia → organizacion → identidad → catalogo → inventario → compras → cajas → ventas → pedidos → fiscal; sync y auditoria transversales.

## Convenciones de base de datos
- Nombres en español, `snake_case`, tablas en plural.
- PK `id UUID` (UUIDv7 generado por la aplicación; sin default en BD). Nunca autoincrementales como identidad.
- Columnas comunes: `created_at`, `updated_at` (timestamptz), `created_by` (FK empleado, nullable), `nodo_origen_id`, `version INTEGER` (bloqueo optimista) en tablas editables.
- Dinero: `NUMERIC(18,2)` totales; `NUMERIC(18,4)` precios/costos unitarios; cantidades `NUMERIC(14,3)`. NUNCA float.
- Snapshots en líneas de venta y documentos fiscales (precio, % IVA, costo, descuento). Nada histórico se recalcula desde maestros.
- Inmutabilidad: ventas confirmadas, movimientos de inventario y documentos fiscales emitidos NO se editan ni borran; se corrigen con documentos nuevos (devolución, ajuste, nota).
- Maestros: desactivación con `activo boolean`, sin borrado físico.
- Códigos DIAN en tablas de referencia.
- Detalle completo y justificaciones: `docs/base-de-datos/modelo.md`.

## Comandos (backend en `./backend`, gestionado con uv)
Todos desde `backend/`; `uv` crea/usa `backend/.venv` (nada global). Si `uv` falla por TLS corporativo, añadir `--system-certs`.
```bash
# Base de datos (desde la raíz del repo). Puerto del host: DB_PORT en .env (5460 por defecto; 5432-5436 suelen estar ocupados)
docker compose up -d db                      # PostgreSQL 16 (healthcheck)
docker compose --profile tools up -d adminer # opcional: Adminer en :8080

cd backend
uv sync                                      # instala dependencias del proyecto
uv run alembic upgrade head                  # migrar (usa DATABASE_URL de ../.env)
uv run alembic downgrade -1                  # revertir la última migración
uv run alembic history                       # lista de revisiones
uv run alembic check                         # modelos vs BD: no debe detectar diferencias
uv run alembic revision --autogenerate -m "descripcion"   # nueva migración (revisar a mano; ver nota)
uv run pytest                                # pruebas (crean/borran la BD `mundorepuestos_test`)
uv run ruff check .                          # lint  (añadir --fix para autocorregir)
uv run ruff format --check .                 # formato (sin --check aplica el formato; ambos deben estar limpios)

uv run uvicorn app.main:app --reload --reload-dir app --port 8000   # API en :8000 (docs: /api/v1/docs, health: /api/v1/health; docs desactivadas con ENV=produccion)
uv run python -m app.cli inicializar --nit 900000001 --razon-social "Mi Empresa SAS" --sede-codigo PRIN --sede-nombre Principal   # empresa + sede + nodo EDGE + configuración de la sede (idempotente; imprime NODO_ID)
uv run python -m app.cli crear-admin --usuario admin --documento 123 --nombres Ana --apellidos Perez   # primer admin (pide la clave sin eco)
uv run python -m app.cli nodos listar        # nodos de organizacion.nodos (para elegir NODO_ID)
uv run python -m app.cli datos-demo [--catalogo]   # empresa, sede Principal + nodo EDGE, bodegas, Caja 1 con resoluciones de prueba, 3 empleados y 5 clientes (idempotente; --catalogo añade ~340 repuestos; bloqueado con ENV=produccion)
uv run python -m app.cli importaciones limpiar [--dias 7]   # purga importaciones Excel sin confirmar (locales, no se sincronizan)
uv run python -m app.cli inventario verificar [--reparar]   # existencias vs kardex
uv run python -m app.cli importar ARCHIVO.xlsx [--confirmar] # importación Excel (sin --confirmar solo valida)
uv run python -m app.workers.fiscal [--una-vez]   # worker de facturación electrónica (FISCAL_PROVEEDOR=factus|simulado); en Docker: docker compose --profile app up -d worker-fiscal
uv run python -m app.cli fiscal rangos|verificar|vincular|estado   # rangos de Factus, conexión, id_rango_proveedor, pendientes
uv run pytest -m factus -s                   # A MANO: sandbox real de Factus; NO corren por defecto (addopts -m 'not factus'), consumen consecutivos compartidos; se omiten sin FACTUS_* en .env
uv run python -m scripts.perf_catalogo       # rendimiento con 50 000 productos (BD aparte mundorepuestos_test_perf; añadir --conservar para inspeccionarla)
uv run pytest -m rendimiento -s              # A MANO: pruebas de rendimiento (p95 de ventas, importación de 5000 filas); NO corren por defecto (addopts -m 'not factus and not rendimiento')
uv run python -m scripts.volcar_openapi > ../pos/openapi.json   # OpenAPI del backend (el POS lo usa: `npm run api:gen` en pos/)

# psql interactivo (Windows/PowerShell; las comillas simples evitan que PowerShell expanda $POSTGRES_*)
docker compose exec db sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB'
```

### Puesta en marcha inicial (paso a paso)
1. `cp .env.example .env` y completar: `DATABASE_URL`/`DB_PORT`, `JWT_SECRET` y `PIN_PEPPER` (generar con `uv run python -c "import secrets; print(secrets.token_urlsafe(48))"`), `ENV=desarrollo`. Si falta algo, la API y el CLI se detienen indicando qué falta y cómo obtenerlo.
2. `docker compose up -d db` · `cd backend` · `uv sync`.
   **Recrear la BD de desarrollo desde cero** (DESTRUCTIVO: borra todos sus datos; no toca `mundorepuestos_test`). Desde la raíz del repo, con los valores de `POSTGRES_USER`/`POSTGRES_DB` del `.env`:
   `docker compose exec db sh -c 'psql -U $POSTGRES_USER -d postgres -c "DROP DATABASE IF EXISTS $POSTGRES_DB WITH (FORCE)" -c "CREATE DATABASE $POSTGRES_DB OWNER $POSTGRES_USER"'`
   **Importante:** deja `NODO_ID=` vacío en `.env` antes de seguir. Si conserva el id del edge de una BD anterior, `crear-admin` y `datos-demo` fallan con `ForeignKeyViolation ... fk_*_nodo_origen_id_nodos` (solo usan el nodo nube cuando `NODO_ID` está vacío).
   Luego: `uv run alembic upgrade head` (`alembic current` debe mostrar `0010 (head)`).
3. `uv run python -m app.cli inicializar --nit ... --razon-social ... --sede-codigo ... --sede-nombre ...`: crea (idempotente) empresa, sede, nodo edge y las claves de `configuracion_sede` de la sede; imprime `NODO_ID (nodo edge) = ...`.
4. En `.env` poner `NODO_ID=<ese id>` y `MODE=edge` (el arranque verifica que el nodo exista, esté activo y que MODE coincida con su tipo; `nodos listar` muestra los disponibles).
5. `uv run python -m app.cli crear-admin ...` (primer administrador, con origen en el nodo edge). En modo no interactivo (scripts, CI) la clave se pasa con la variable `ADMIN_PASSWORD`; de lo contrario se pide sin eco.
6. Opcional (desarrollo): `uv run python -m app.cli datos-demo` (reutiliza `inicializar`): bodega B01, bodega de averías AV01, Caja 1 con resoluciones de prueba FE (`DEMO`) y NC (`DNC`), propietario, cajero y vendedor con PIN y 5 clientes (ver «Demo»); con `--catalogo` carga además ~340 repuestos con precios, stock, ubicaciones y EAN-13; imprime `bodega_id`, `caja_id`, etc. Luego arrancar la API con el comando uvicorn de arriba.
Todos los comandos usan los mismos servicios que la API, así que dejan eventos en `sync.outbox_eventos` y registros en `auditoria.log_acciones`.
Los comandos de arranque (`inicializar`, `nodos`, `datos-demo`) no exigen `NODO_ID` (`inicializar` y `datos-demo` crean todo con origen en el nodo edge); `crear-admin` SÍ lo exige (por eso va después de `inicializar`).
7. Verificar: `uv run alembic check`, `uv run pytest` (~4 min), `uv run ruff check .`, `uv run ruff format --check .`.

### Probar el flujo POS en Swagger (`/api/v1/docs`)
1. **Registrar dispositivo** (backoffice): `POST /auth/login` con el admin → *Authorize* con el access token → `POST /cajas/dispositivos` con `{"caja_id": "<caja_id de datos-demo>", "nombre": "POS 1"}`; guardar el `token` (solo se muestra una vez).
2. **Login por PIN**: `POST /pos/auth/pin` con la cabecera `X-Dispositivo-Token: <token>` y `{"pin": "123456"}` (el cajero demo) → devuelve el token de sesión POS; usarlo en *Authorize* para los endpoints `/pos/...`.
3. **Autorización de supervisor**: con la sesión del cajero, `POST /pos/autorizaciones` con el `pin` **del supervisor** (empleado con rol supervisor y PIN de 6 dígitos en la misma sede), la `accion` (p. ej. `inventario.ajustar`) y el `motivo`; devuelve un `autorizacion_id` de un solo uso que se pasa al ajuste o entrada que supera el umbral.

### Flujo POS: turnos, ventas y devoluciones (con la sesión POS de arriba)
1. `POST /pos/turnos` `{"base_efectivo": "50000"}` abre el turno de la caja (uno por caja y uno por cajero). Ingresos/retiros: `POST /pos/turnos/actual/movimientos` (motivos: `GET /pos/motivos-movimiento-caja`; el retiro es libre hasta el umbral de la política `retiro_caja` y por encima pide `autorizacion_id` de acción `pos.retirar_efectivo`).
2. `POST /pos/ventas` con un `id` UUIDv7 generado por el POS (clave de idempotencia): el servidor recalcula precios; descuentos sobre el tope del rol piden `autorizacion_descuento_id` (`pos.descuento_mayor`, de OTRO empleado); cambio de precio, permiso `pos.cambiar_precio` o `autorizacion_precio_id` (acción `pos.cambiar_precio`; `pos.precio_manual` ya no existe). La venta guarda `vendedor_id` (quien la armó) y `cajero_id` (quien la cobró). Pagos mixtos: efectivo con `valor_recibido` (el cambio lo calcula el servidor), tarjeta/QR/transferencia con `valor` y `referencia`. Espera: `POST/GET /pos/ventas/espera` (no exige turno; la arma cualquier sesión con `pos.vender` y se retoma en cualquier caja de la sede; `?solo_mias=true`). Filtros: `GET /pos/ventas?vendedor_id=&cajero_id=`. Consulta: `GET /pos/ventas`, `GET /pos/ventas/{id}`, `GET /pos/ventas/{id}/ticket`. Clientes: `GET/POST /pos/terceros`.
3. `POST /pos/devoluciones` (parcial o total; motivos en `GET /pos/motivos-devolucion`; autorización `pos.devolver` de un supervisor; destino `vendible` o `averias`; reembolso `efectivo` —sale del turno ACTUAL— o `medio_original`). No existe "anular venta": se corrige con devolución.
4. `POST /pos/turnos/actual/cierre` con el conteo ciego `[{"medio_pago_codigo":"10","valor_contado":"..."}]` (el efectivo es obligatorio); devuelve el informe de cierre. La diferencia de arqueo NUNCA bloquea el cierre: por defecto queda en revisión posterior. `GET /pos/turnos/{id}/informe-cierre` lo reimprime; `POST /cajas/turnos/{id}/cierre-forzado` (permiso `cajas.cierre_forzado`) cierra un turno abandonado.

### Políticas de autorización (0010)
Cada acción sensible tiene una política por sede en `configuracion_sede` (`autorizacion.<accion>`): `libre`, `revision_posterior` (se ejecuta y queda en `auditoria.revisiones`) o `requiere_autorizacion` (otro empleado: PIN de supervisor en la caja **o** aprobación remota), con `umbral` (COP) opcional. Acciones: `devolucion` (libre hasta 200 000), `descuento_mayor`, `cambiar_precio` (requieren autorización), `retiro_caja` (libre hasta 300 000), `diferencia_arqueo` (revisión posterior; no admite `requiere_autorizacion`), `ajuste_inventario` y `entrada_inventario` (aprobación por `inventario.umbral_aprobacion`). Un reembolso en efectivo mayor al efectivo del turno se rechaza siempre. Quien tiene el permiso de la acción no pide autorización. Detalle en `docs/base-de-datos/modelo.md` §4.5; permisos y roles en `docs/permisos.md`; capas y decisiones en `docs/arquitectura.md`.
* Ver/cambiar: `GET /organizacion/politicas-autorizacion/{sede_id}`, `PUT /organizacion/politicas-autorizacion/{sede_id}/{accion}` (`admin.configuracion`).
* **Aprobación remota** (sin supervisor en el local): el POS crea `POST /pos/solicitudes-autorizacion` (`accion`, `monto`, `motivo`, `contexto`, `entidad_*`) y consulta `GET /pos/solicitudes-autorizacion/{id}` cada `poll_ms` (2 s); desde el backoffice `GET /autorizaciones/solicitudes`, `POST /autorizaciones/solicitudes/{id}/aprobar|rechazar` (`autorizaciones.aprobar`). Aprobada, trae un `autorizacion_id` de un solo uso que se pasa a la acción. Vence a los 5 min (`autorizacion.solicitud_expira_min`); nadie aprueba lo suyo.
* **Revisión posterior**: `GET /revisiones`, `POST /revisiones/{id}/revisar` (comentario obligatorio), `GET /revisiones/reporte-diario?fecha=` (`revisiones.gestionar`).

### Demo (`datos-demo --catalogo`)
Solo desarrollo. Credenciales (documento = cédula; el carné y el PIN sirven en `POST /pos/auth/pin`):

| Rol | Carné | PIN | Backoffice |
|---|---|---|---|
| Propietario (`propietario`) | `PROP1` | `246810` | usuario `propietario` / clave `Demo-Propietario-2026` |
| Cajero (`cajero`) | `CAJERO1` | `123456` | — |
| Vendedor (`vendedor`) | `VENDEDOR1` | `654321` | — |

Clientes: Taller Automotriz El Pistón S.A.S. (NIT 901234567), Transportes Andinos Ltda. (NIT 800123456), Jorge Rodríguez (CC 79123456), María Fernanda Gómez (CC 52123456), Andrés Castillo (CC 1020304050). El catálogo (≈340 productos, 17 familias de repuestos por vehículo más bombillas, plumillas y fluidos, 27 marcas comerciales, 17 modelos y 30 versiones de vehículo con sus años) tiene referencias **ilustrativas, marcadas `alterna` y NO verificadas contra catálogos de fabricantes**: sirve para probar y demostrar, no para comprar. Prueba rápida: buscar «pastillas spark 2018».

## API
- SQLAlchemy **síncrono** (psycopg 3); endpoints `def` (FastAPI los corre en threadpool). Una sesión por petición (`Db` en `app/api/deps.py`): commit al final, rollback ante cualquier error; los servicios NO hacen commit. Excepción deliberada: en login/PIN/refresh el intento fallido se audita y se confirma (`persistir_si_falla`).
- Errores siempre `application/problem+json` (`type,title,status,detail,code,request_id`); servicios lanzan `NoEncontrado/Conflicto/PermisoDenegado/ReglaNegocio/NoAutenticado`, nunca `HTTPException`.
- Cada endpoint declara su permiso con `Depends(requiere_permiso("modulo.accion"))`. Auditoría: `registrar_accion()` (nunca registrar contraseñas, PIN ni tokens).
- Migración 0008: aprobación de entradas/ajustes (`solicitudes_inventario`, permiso `inventario.aprobar`, rol `propietario`), trigger de segregación en `autorizaciones`, EAN-13 por nodo (`nodos.codigo_ean`), alias de vehículos y búsqueda aproximada KNN (GiST).
- Entradas/ajustes de backoffice sobre el umbral de la sede (500 000 COP por defecto; `PUT /inventario/configuracion/{sede}`) quedan `pendiente_aprobacion` (202) hasta que OTRO empleado con `inventario.aprobar` los apruebe; el POS usa `autorizacion_id` de un supervisor distinto.
- Catálogo (`/catalogo/...`), inventario (`/inventario/...`) y escáner (`/pos/productos/codigo/{codigo}`). Paginación estándar `limit/offset` → `{items,total,limit,offset}` (`app/api/paginacion.py`). Toda escritura publica su evento con `publicar_evento()` (`app/modules/sync/servicios.py`) en la MISMA transacción. Imágenes tras la interfaz `Almacenamiento` (local en `MEDIA_DIR`; S3 después).
- Config sensible en `.env` (ver `.env.example`): `JWT_SECRET`, `PIN_PEPPER` (no cambiarla con PIN ya cargados).

## Estado actual
- [x] Infra local (docker-compose, .env.example, .gitignore).
- [x] Diseño de BD documentado en `docs/base-de-datos/modelo.md`.
- [x] **Fase 1** (84 tablas, 10 schemas): modelos SQLAlchemy + migraciones 0001-0008 + pruebas (`backend/`). Fases 2 y 3: `modelo.md` §19.
- [x] Esqueleto de API + autenticación/permisos (backoffice y POS) + administración mínima de empleados.
- [x] Catálogo e inventario por API (CRUD, precios, imágenes, búsqueda, escáner, kardex con costo promedio, ajustes, entradas, importación Excel, `inventario verificar`).
- [x] **Migración 0010**: políticas de autorización por acción (libre / revisión posterior / requiere autorización), aprobación remota, revisiones, `vendedor_id`/`cajero_id`, capa `app/aplicacion/` (casos de uso; routers delgados, sin callbacks), `pos.precio_manual` fusionado en `pos.cambiar_precio`, rol `vendedor`, `datos-demo --catalogo`, pruebas de arquitectura y de documentación de constraints.
- [x] **Migración 0009**: turnos y caja (apertura, movimientos, conteo ciego, arqueo, cierre forzado), ventas POS (idempotentes, pagos mixtos, espera, ticket), devoluciones (NC `pendiente_envio`), `inicializar`, configuración por sede (`organizacion.configuracion`). La FE/NC se crean `pendiente_envio`; sin llamadas a Factus.
- [x] **Migración 0011 + integración Factus (sandbox)**: worker fiscal, adaptador Factus y simulado, `/fiscal/...`, estado fiscal en ticket/POS/health, alertas, índices en todas las FK, permisos `cajas.turno.*` y `fiscal.gestionar`. Detalle: `docs/integraciones/factus.md`.
- [x] **Migración 0012**: `sync.outbox_eventos.alcance` (`fiscal.*` = `local`: el agente de sync solo replica `sincronizable`; registro en `app/modules/sync/tipos_evento.py`), `POST /fiscal/documentos/{id}/corregir` (FE rechazada → `anulado` + FE nueva con adquirente corregido), servicio `api` en docker-compose con el mismo volumen de archivos que `worker-fiscal`.
- [x] **POS de escritorio, parte 1** (`pos/`, ver `pos/README.md`): Tauri 2 + React/TS, cliente de API generado del OpenAPI, PIN, turno, venta con escáner HID, cobro mixto idempotente, autorizaciones (PIN o remota), FE/comprobante provisional, ESC/POS (TCP 9100 y cola de Windows RAW), Vitest + Playwright. Ajustes de backend: `POST /fiscal/documentos/{id}/corregir` acepta `actualizar_tercero` (actualiza `identidad.terceros` con evento y auditoría); el ticket trae `venta.codigo_barras` (`<caja>-<numero_interno>`, Code128); la sesión POS expone `permisos` y `redondeo_efectivo`; búsqueda y escáner devuelven `ubicacion` (principal de la sede); CORS por defecto: `tauri://localhost`, `http://tauri.localhost` y el dev server del POS (`:1420`); marcador pytest `rendimiento`.
- [ ] POS parte 2 (ventas en espera, devoluciones, movimientos de caja, cierre de turno, historial/reimpresión, kiosko, autostart, instalador), tienda en línea y backoffice, agente de sync (solo `alcance='sincronizable'`; excluye `fiscal.*`), paso a producción de Factus — NO iniciar hasta aprobación.
