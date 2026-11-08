// Errores de la API (application/problem+json) -> mensajes humanos. Nunca se muestra JSON crudo.

export interface Problema {
  type?: string
  title?: string
  status?: number
  detail?: string
  code?: string
  request_id?: string
  [extra: string]: unknown
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly problema: Problema,
  ) {
    super(problema.detail || problema.title || `Error ${status}`)
  }
  get code(): string | undefined {
    return this.problema.code
  }
}

/** No hubo respuesta del servidor (sin red, caída, timeout). La operación PUDO haber llegado: ver idempotencia. */
export class ErrorRed extends Error {
  constructor(public readonly causa?: unknown) {
    super('Sin conexión con el servidor.')
  }
}

const POR_CODIGO: Record<string, string> = {
  dispositivo_invalido: 'Este equipo no está registrado o fue revocado. Pida al administrador un nuevo token.',
  credenciales_invalidas: 'PIN o carné incorrecto.',
  pin_invalido: 'PIN o carné incorrecto.',
  cuenta_bloqueada: 'Demasiados intentos fallidos. Espere unos minutos o pida ayuda a un supervisor.',
  no_autenticado: 'La sesión expiró. Ingrese de nuevo con su PIN.',
  permiso_denegado: 'No tiene permiso para esta acción.',
  turno_cerrado: 'No hay un turno abierto. Abra el turno para vender.',
  turno_no_abierto: 'No hay un turno abierto. Abra el turno para vender.',
  turno_ya_abierto: 'Ya hay un turno abierto en esta caja.',
  sin_precio: 'El producto no tiene precio vigente en esta sede.',
  producto_no_vendible: 'El producto no está disponible para la venta.',
  stock_insuficiente: 'No hay existencias suficientes de uno de los productos.',
  pagos_insuficientes: 'Los pagos no cubren el total de la venta.',
  total_invalido: 'El total de la venta debe ser mayor que cero.',
  nombre_requerido: 'Falta el nombre del cliente.',
  autorizacion_requerida: 'Esta acción necesita la autorización de un supervisor.',
  autorizacion_otra_entidad: 'La autorización es para otra venta.',
  busqueda_vacia: 'Escriba un documento o un nombre para buscar.',
}

const POR_ESTADO: Record<number, string> = {
  400: 'La solicitud no es válida.',
  401: 'La sesión expiró. Ingrese de nuevo con su PIN.',
  403: 'No tiene permiso para esta acción.',
  404: 'No se encontró lo que busca.',
  409: 'La operación entra en conflicto con otra. Actualice e intente de nuevo.',
  422: 'Hay datos que no son válidos. Revíselos e intente de nuevo.',
  429: 'Demasiadas solicitudes. Espere un momento.',
  500: 'Error interno del servidor. Intente de nuevo o avise a soporte.',
  502: 'El servidor no está disponible.',
  503: 'El servidor no está disponible.',
}

/** Mensaje para el usuario. Prefiere el `detail` del servidor (ya viene en español) y, si no, el código/estado. */
export function mensajeHumano(e: unknown): string {
  if (e instanceof ErrorRed) return 'No hay conexión con el servidor de la tienda. Verifique la red e intente de nuevo.'
  if (e instanceof ApiError) {
    const { code, detail } = e.problema
    if (code && POR_CODIGO[code]) return POR_CODIGO[code]
    if (typeof detail === 'string' && detail && !detail.startsWith('{') && !detail.startsWith('[')) return detail
    return POR_ESTADO[e.status] ?? `El servidor respondió con un error (${e.status}).`
  }
  if (e instanceof Error && e.message && !e.message.startsWith('{')) return e.message
  return 'Ocurrió un error inesperado.'
}

/** Es el 403 `autorizacion_requerida`: trae `permiso_autorizacion`, `accion`, `monto` y `vias`. */
export interface AutorizacionRequerida {
  accion: string
  permiso: string
  monto: string | null
  vias: string[]
}
export function comoAutorizacionRequerida(e: unknown): AutorizacionRequerida | null {
  if (!(e instanceof ApiError) || e.status !== 403 || e.code !== 'autorizacion_requerida') return null
  const p = e.problema
  return {
    accion: String(p.accion ?? ''),
    permiso: String(p.permiso_autorizacion ?? ''),
    monto: p.monto == null ? null : String(p.monto),
    vias: Array.isArray(p.vias) ? (p.vias as string[]) : ['pin_supervisor', 'solicitud_remota'],
  }
}
