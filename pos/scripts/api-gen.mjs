// Genera el cliente tipado de la API: openapi.json (volcado del backend) -> src/api/schema.d.ts (openapi-typescript).
// Uso: npm run api:gen            (vuelca el OpenAPI con `uv run` desde ../backend; no necesita servidor)
//      OPENAPI_URL=http://localhost:8000/api/v1/openapi.json npm run api:gen   (desde un servidor en marcha)
import { spawnSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const raiz = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const destinoJson = resolve(raiz, 'openapi.json')
const destinoTs = resolve(raiz, 'src/api/schema.d.ts')

async function obtenerOpenApi() {
  const url = process.env.OPENAPI_URL
  if (url) {
    const r = await fetch(url)
    if (!r.ok) throw new Error(`GET ${url} -> ${r.status}`)
    return JSON.stringify(await r.json(), null, 2)
  }
  const r = spawnSync(
    'uv',
    ['run', 'python', '-m', 'scripts.volcar_openapi'],
    { cwd: resolve(raiz, '../backend'), encoding: 'utf8', shell: process.platform === 'win32', maxBuffer: 64 * 1024 * 1024 },
  )
  if (r.status !== 0) throw new Error(`No se pudo volcar el OpenAPI del backend:\n${r.stderr}`)
  return r.stdout
}

const json = await obtenerOpenApi()
writeFileSync(destinoJson, json.trim() + '\n')
mkdirSync(dirname(destinoTs), { recursive: true })
const g = spawnSync('npx', ['openapi-typescript', destinoJson, '-o', destinoTs], {
  cwd: raiz, stdio: 'inherit', shell: process.platform === 'win32',
})
if (g.status !== 0) process.exit(g.status ?? 1)
console.log('Cliente generado: openapi.json y src/api/schema.d.ts')
