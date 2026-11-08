// Backend para las pruebas E2E del POS (lo arranca Playwright, ver playwright.config.ts).
//  1. Recrea la BD DESECHABLE `mundorepuestos_e2e` (nunca toca la BD de desarrollo).
//  2. Migra, inicializa la sede, crea el admin y carga `datos-demo --catalogo`.
//  3. Levanta la API (puerto 8010) y el worker fiscal con FISCAL_PROVEEDOR=simulado.
// Uso manual: node scripts/e2e-servidor.mjs [--solo-preparar]
import { spawn, spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const raiz = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const backend = resolve(raiz, 'backend')
const PUERTO = process.env.E2E_API_PUERTO ?? '8010'
const BD = 'mundorepuestos_e2e'
export const ADMIN = { usuario: 'admin', clave: 'E2E-Admin-Clave-2026!' }

function leerEnv() {
  const env = {}
  for (const l of readFileSync(resolve(raiz, '.env'), 'utf8').split(/\r?\n/)) {
    const m = l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/)
    if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '').replace(/\s+#.*$/, '')
  }
  return env
}
const base = leerEnv()
const urlBd = base.DATABASE_URL.replace(/\/[^/]+$/, `/${BD}`)

function ejecutar(cmd, args, { cwd = backend, env = {}, entrada } = {}) {
  const r = spawnSync(cmd, args, {
    cwd,
    env: { ...process.env, ...env },
    encoding: 'utf8',
    shell: process.platform === 'win32',
    input: entrada,
    maxBuffer: 32 * 1024 * 1024,
  })
  if (r.status !== 0) throw new Error(`${cmd} ${args.join(' ')} falló (${r.status}):\n${r.stdout}\n${r.stderr}`)
  return r.stdout + r.stderr
}

const entornoApi = {
  DATABASE_URL: urlBd,
  MODE: 'edge',
  ENV: 'desarrollo',
  FISCAL_PROVEEDOR: 'simulado',
  FISCAL_SIMULADO_LATENCIA_MS: '50',
  FISCAL_SIMULADO_RECHAZOS: '0',
  MEDIA_DIR: resolve(backend, '.e2e-media'),
  NODO_ID: '',
}

function preparar() {
  console.log(`[e2e] recreando ${BD}…`)
  const u = base.POSTGRES_USER
  ejecutar(
    'docker',
    ['compose', 'exec', '-T', 'db', 'psql', '-U', u, '-d', 'postgres',
      '-c', `"DROP DATABASE IF EXISTS ${BD} WITH (FORCE)"`, '-c', `"CREATE DATABASE ${BD} OWNER ${u}"`],
    { cwd: raiz },
  )
  ejecutar('uv', ['run', 'alembic', 'upgrade', 'head'], { env: entornoApi })
  const ini = ejecutar(
    'uv',
    ['run', 'python', '-m', 'app.cli', 'inicializar', '--nit', '900000001', '--razon-social', '"Mi Empresa SAS"', '--sede-codigo', 'PRIN', '--sede-nombre', 'Principal'],
    { env: entornoApi },
  )
  const nodo = ini.match(/NODO_ID[^=]*=\s*([0-9a-f-]{36})/i)?.[1]
  if (!nodo) throw new Error(`No se encontró NODO_ID en la salida de inicializar:\n${ini}`)
  entornoApi.NODO_ID = nodo
  ejecutar(
    'uv',
    ['run', 'python', '-m', 'app.cli', 'crear-admin', '--usuario', ADMIN.usuario, '--documento', '123', '--nombres', 'Ana', '--apellidos', 'Perez'],
    { env: { ...entornoApi, ADMIN_PASSWORD: ADMIN.clave } },
  )
  const demo = ejecutar('uv', ['run', 'python', '-m', 'app.cli', 'datos-demo', '--catalogo'], { env: entornoApi })
  const caja = demo.match(/caja_id[^0-9a-f]*([0-9a-f-]{36})/i)?.[1]
  if (!caja) throw new Error(`No se encontró caja_id en la salida de datos-demo:\n${demo}`)
  writeFileSync(
    resolve(dirname(fileURLToPath(import.meta.url)), '../e2e/.estado-backend.json'),
    JSON.stringify({ cajaId: caja, nodoId: nodo, apiUrl: `http://127.0.0.1:${PUERTO}`, admin: ADMIN }, null, 2),
  )
  console.log(`[e2e] listo: caja ${caja}, nodo ${nodo}`)
}

preparar()
if (process.argv.includes('--solo-preparar')) process.exit(0)

const hijos = []
const lanzar = (args) => {
  const h = spawn('uv', ['run', ...args], { cwd: backend, env: { ...process.env, ...entornoApi }, stdio: 'inherit', shell: process.platform === 'win32' })
  hijos.push(h)
  return h
}
lanzar(['uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', PUERTO])
lanzar(['python', '-m', 'app.workers.fiscal'])

function limpiar() {
  for (const h of hijos) {
    if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(h.pid), '/T', '/F'])
    else h.kill('SIGTERM')
  }
}
process.on('exit', limpiar)
for (const s of ['SIGINT', 'SIGTERM']) process.on(s, () => process.exit(0))
setInterval(() => {}, 1 << 30)
