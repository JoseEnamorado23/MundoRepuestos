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
uv run python -m app.cli crear-admin --usuario admin --documento 123 --nombres Ana --apellidos Perez   # primer admin (pide la clave sin eco)
uv run python -m app.cli nodos listar        # nodos de organizacion.nodos (para elegir NODO_ID)
uv run python -m app.cli datos-demo          # empresa, sede Principal + nodo EDGE, bodega, Caja 1 con resolución de prueba, cajero PIN 123456 (idempotente; bloqueado con ENV=produccion)
uv run python -m app.cli importaciones limpiar [--dias 7]   # purga importaciones Excel sin confirmar (locales, no se sincronizan)
uv run python -m app.cli inventario verificar [--reparar]   # existencias vs kardex
uv run python -m app.cli importar ARCHIVO.xlsx [--confirmar] # importación Excel (sin --confirmar solo valida)
uv run python -m scripts.perf_catalogo       # rendimiento con 50 000 productos (BD aparte mundorepuestos_test_perf; añadir --conservar para inspeccionarla)

# psql interactivo (Windows/PowerShell; las comillas simples evitan que PowerShell expanda $POSTGRES_*)
docker compose exec db sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB'
```

### Puesta en marcha inicial (paso a paso)
1. `cp .env.example .env` y completar: `DATABASE_URL`/`DB_PORT`, `JWT_SECRET` y `PIN_PEPPER` (generar con `uv run python -c "import secrets; print(secrets.token_urlsafe(48))"`), `ENV=desarrollo`. Si falta algo, la API y el CLI se detienen indicando qué falta y cómo obtenerlo.
2. `docker compose up -d db` · `cd backend` · `uv sync`.
   **Recrear la BD de desarrollo desde cero** (DESTRUCTIVO: borra todos sus datos; no toca `mundorepuestos_test`). Desde la raíz del repo, con los valores de `POSTGRES_USER`/`POSTGRES_DB` del `.env`:
   `docker compose exec db sh -c 'psql -U $POSTGRES_USER -d postgres -c "DROP DATABASE IF EXISTS $POSTGRES_DB WITH (FORCE)" -c "CREATE DATABASE $POSTGRES_DB OWNER $POSTGRES_USER"'`
   **Importante:** deja `NODO_ID=` vacío en `.env` antes de seguir. Si conserva el id del edge de una BD anterior, `crear-admin` y `datos-demo` fallan con `ForeignKeyViolation ... fk_*_nodo_origen_id_nodos` (solo usan el nodo nube cuando `NODO_ID` está vacío).
   Luego: `uv run alembic upgrade head` (`alembic current` debe mostrar `0008 (head)`).
3. `uv run python -m app.cli crear-admin ...` (primer administrador). En modo no interactivo (scripts, CI) la clave se pasa con la variable `ADMIN_PASSWORD`; de lo contrario se pide sin eco.
4. `uv run python -m app.cli datos-demo`: imprime `NODO_ID (nodo edge) = ...` y `caja_id = ...`.
5. En `.env` poner `NODO_ID=<ese id>` y `MODE=edge` (el arranque verifica que el nodo exista, esté activo y que MODE coincida con su tipo; `nodos listar` muestra los disponibles). Luego arrancar la API con el comando uvicorn de arriba.
Los comandos de arranque (`crear-admin`, `nodos`, `datos-demo`) no exigen `NODO_ID`; con `NODO_ID` vacío usan el nodo nube como origen (el admin y su auditoría); `datos-demo` crea empresa, sede, bodega, caja, resolución y cajero con origen en el nodo edge.
6. Verificar: `uv run alembic check`, `uv run pytest` (~4 min), `uv run ruff check .`, `uv run ruff format --check .`.

### Probar el flujo POS en Swagger (`/api/v1/docs`)
1. **Registrar dispositivo** (backoffice): `POST /auth/login` con el admin → *Authorize* con el access token → `POST /cajas/dispositivos` con `{"caja_id": "<caja_id de datos-demo>", "nombre": "POS 1"}`; guardar el `token` (solo se muestra una vez).
2. **Login por PIN**: `POST /pos/auth/pin` con la cabecera `X-Dispositivo-Token: <token>` y `{"pin": "123456"}` (el cajero demo) → devuelve el token de sesión POS; usarlo en *Authorize* para los endpoints `/pos/...`.
3. **Autorización de supervisor**: con la sesión del cajero, `POST /pos/autorizaciones` con el `pin` **del supervisor** (empleado con rol supervisor y PIN de 6 dígitos en la misma sede), la `accion` (p. ej. `inventario.ajustar`) y el `motivo`; devuelve un `autorizacion_id` de un solo uso que se pasa al ajuste o entrada que supera el umbral.

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
- [ ] Ventas, cajas (turnos/arqueos), frontends, integración DIAN (Factus), agente de sync — NO iniciar hasta aprobación.
