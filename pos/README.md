# MundoRepuestos POS (escritorio)

POS de mostrador: Tauri 2 + React 19 + TypeScript + Vite, Tailwind v4 + Radix (estilo shadcn), TanStack Query, Zustand y
react-router (HashRouter). Habla **solo** con el servidor EDGE de la tienda por la API del backend. Esta es la **parte 1**:
PIN, apertura de turno, venta, cobro, autorizaciones, impresión y configuración. Pendiente (parte 2): ventas en espera,
devoluciones, movimientos de caja, cierre de turno, historial/reimpresión, modo kiosko, autostart e instalador.

## Dos modos de ejecución

| | Navegador | Tauri (escritorio) |
|---|---|---|
| Comando | `npm run dev` → http://127.0.0.1:1420 | `npm run tauri dev` |
| Token del dispositivo | `localStorage` (aviso visible «solo desarrollo») | Almacén seguro del SO (Credential Manager) |
| Impresora | Vista previa 80 mm + `window.print` | ESC/POS crudo por TCP 9100 o cola de Windows |
| Cajón | Simulado (aviso en pantalla) | Pulso `ESC p` por la impresora |

Todo el hardware pasa por la interfaz `Hardware` (`src/hardware/`): `HardwareTauri` y `HardwareNavegador`. La pantalla no sabe cuál usa.
El puerto 1420 es fijo (`strictPort`): coincide con `devUrl` de Tauri y con `CORS_ORIGINS` del backend.

### Requisitos
- Node 20+ y `npm install` (todo queda en `node_modules`; nada global).
- Tauri: Rust estable (`cargo`), Visual Studio Build Tools (MSVC) y WebView2 (viene con Windows 11).
- Backend corriendo (ver `CLAUDE.md`) con `CORS_ORIGINS` que incluya `http://localhost:1420`, `http://127.0.0.1:1420`, `tauri://localhost` y `http://tauri.localhost` (es el valor por defecto).

### Primer arranque
1. `POST /cajas/dispositivos` (backoffice, Swagger) → guarda el `token` (se muestra una sola vez).
2. En el POS: URL del servidor → «Probar conexión» (`/health`) → pegar el token → Guardar.
3. Entrar con PIN o carné (demo: cajero `123456`).

## Cliente de API generado
No hay tipos de API escritos a mano. `npm run api:gen` vuelca el OpenAPI del backend
(`uv run python -m scripts.volcar_openapi`, o `OPENAPI_URL=http://…/api/v1/openapi.json` si el backend ya corre) a
`openapi.json` y genera `src/api/schema.d.ts` con `openapi-typescript`; el cliente usa `openapi-fetch`.
Regenerar tras cualquier cambio de esquemas del backend; `npm run typecheck` avisa de lo que se rompa.
TypeScript está fijado en la 5.x porque `openapi-typescript` aún no soporta TS 7.

## Pruebas
- `npm test` — Vitest: detección de escáner (ráfaga vs. tecleo humano), cálculo de cambio/redondeo, snapshot de bytes ESC/POS, reintento idempotente de la venta.
- `npm run test:e2e` — Playwright (Chromium, modo navegador). `playwright.config.ts` levanta `scripts/e2e-servidor.mjs`, que
  **recrea la BD desechable `mundorepuestos_e2e`** (nunca la de desarrollo), migra, `inicializar`, `crear-admin`,
  `datos-demo --catalogo`, y arranca la API (8010) y el worker fiscal con `FISCAL_PROVEEDOR=simulado`. Flujo: PIN → turno → buscar «pastillas spark» → escanear → descuento que pide autorización (PIN de supervisor) → pago mixto → FE aceptada → vista previa con CUFE. Capturas en `e2e/capturas/`.
  Playwright entrega cada tecla con 30–50 ms de retraso (un lector real, 1–5 ms); el E2E sube la preferencia `umbralEscanerMs` a 80 ms y teclea «a mano» a 120 ms.
- `cd src-tauri && cargo test` — URL de destino, entrega de bytes por TCP y pulso del cajón.

## Decisiones (Tauri 2)
- **Almacén seguro:** el plugin oficial Stronghold exige contraseña y snapshot propios, y los plugins de keyring son de terceros. Se usan comandos propios sobre el crate `keyring` (`secreto_leer/guardar/borrar`, Windows Credential Manager). El JWT de la sesión POS **nunca** se persiste: vive solo en memoria.
- **Capabilities:** ventana `main` con `core:default`; los comandos propios no necesitan plugin. Para la parte 2 (autostart) añadir `tauri-plugin-autostart` y los permisos `autostart:allow-enable`, `allow-disable`, `allow-is-enabled`.
- **ESC/POS:** los bytes se construyen en TypeScript (`@point-of-sale/receipt-printer-encoder`, QR nativo y Code128). Rust solo los entrega: `imprimir_raw(destino, bytes)` y `abrir_cajon(destino)` (el pulso `1B 70 00 19 FA` lo arma Rust).
- **Destinos:** `tcp://ip[:9100]` (recomendado) y `windows://Nombre de la impresora`. Este último usa el spooler en modo **RAW** (`OpenPrinter` + `StartDocPrinter` con datatype `RAW` + `WritePrinter`, crate `windows`), así que sirve para impresoras USB instaladas; si el driver diera problemas, alternativas: compartir la impresora o usar una térmica con red (TCP). El camino Windows está compilado pero **no probado con impresora física**.
- **Plantilla única:** `construirTirillaVenta` produce una representación intermedia (`Tirilla`) que consumen el renderer ESC/POS y el HTML de la vista previa.
- **Venta idempotente:** un UUIDv7 por contenido de venta; ante error de red o 5xx se reintenta con el mismo `id`; si el resultado queda incierto, el id se conserva aunque se edite el carrito.
- **Factura provisional:** si la FE no queda aceptada en N segundos (por defecto 8), se imprime un comprobante «PROVISIONAL» y la venta queda marcada en la barra de estado para reimprimir la FE.
