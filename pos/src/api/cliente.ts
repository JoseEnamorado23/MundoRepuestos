// Cliente de la API tipado con openapi-fetch. Los tipos salen de `schema.d.ts`, generado con `npm run api:gen`.
import createClient, { type Middleware } from 'openapi-fetch'
import { ApiError, ErrorRed, type Problema } from '@/lib/errores'
import type { components, paths } from './schema'

export type S = components['schemas']

/** Lo que el cliente necesita saber del estado de la app, inyectado para no acoplar con los stores. */
export interface Contexto {
  urlServidor: () => string
  tokenSesion: () => string | null
  tokenDispositivo: () => string | null
  /** Se llama cuando el servidor responde 401 a una petición con sesión (la sesión expiró o se revocó). */
  alExpirarSesion: () => void
}

let ctx: Contexto = {
  urlServidor: () => '',
  tokenSesion: () => null,
  tokenDispositivo: () => null,
  alExpirarSesion: () => {},
}
export function configurarContexto(c: Contexto) {
  ctx = c
}

/** La URL guardada puede venir con `/api/v1` o con `/` al final; las rutas del cliente ya incluyen `/api/v1`. */
export function normalizarUrl(url: string): string {
  return url.trim().replace(/\/+$/, '').replace(/\/api\/v1$/, '')
}

const TIMEOUT_MS = 15_000

/** fetch con tiempo límite; un fallo de red se convierte en `ErrorRed` (la operación pudo haber llegado). */
async function miFetch(entrada: Request): Promise<Response> {
  try {
    return await fetch(new Request(entrada, { signal: AbortSignal.timeout(TIMEOUT_MS) }))
  } catch (e) {
    throw new ErrorRed(e)
  }
}

const auth: Middleware = {
  onRequest({ request }) {
    const t = ctx.tokenSesion()
    if (t && !request.headers.has('Authorization')) request.headers.set('Authorization', `Bearer ${t}`)
    return request
  },
  onResponse({ request, response }) {
    // 401 con sesión POS: expiró o se revocó. El login por PIN también responde 401 (PIN malo): ahí no hay sesión.
    if (response.status === 401 && ctx.tokenSesion() && !request.url.endsWith('/pos/auth/pin')) ctx.alExpirarSesion()
    return response
  },
}

export function cliente() {
  const c = createClient<paths>({ baseUrl: normalizarUrl(ctx.urlServidor()), fetch: miFetch })
  c.use(auth)
  return c
}

export function tokenDispositivoHeader(): { 'X-Dispositivo-Token'?: string } {
  const t = ctx.tokenDispositivo()
  return t ? { 'X-Dispositivo-Token': t } : {}
}

type Resultado<T> = { data?: T; error?: unknown; response: Response }

/** Desenvuelve la respuesta: devuelve `data` o lanza `ApiError` con el problem+json. */
export async function datos<T>(p: Promise<Resultado<T>>): Promise<T> {
  const r = await p
  if (r.response.ok) return r.data as T
  const problema =
    r.error && typeof r.error === 'object' ? (r.error as Problema) : ({ detail: undefined } as Problema)
  throw new ApiError(r.response.status, problema)
}
