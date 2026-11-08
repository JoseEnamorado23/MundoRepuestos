// Llamadas a la API que usa el POS (parte 1). Todas devuelven datos tipados o lanzan ApiError / ErrorRed.
import { ApiError, ErrorRed } from '@/lib/errores'
import { cliente, datos, normalizarUrl, tokenDispositivoHeader, type S } from './cliente'

export type Producto = S['ProductoBuscadoOut']
export type ProductoEscaneado = S['ProductoEscaneadoOut']
export type Tercero = S['TerceroOut']
export type Ticket = S['TicketOut']
export type EstadoFiscal = S['EstadoFiscalVentaOut']
export type Venta = S['VentaOut']
export type VentaIn = S['VentaIn']
export type Sesion = S['SesionPosOut']
export type Turno = S['TurnoOut']
export type Health = S['HealthOut']
export type SolicitudEstado = S['EstadoSolicitudOut']

/** /health sin autenticación y con una URL aún no guardada (prueba de conexión de la pantalla de configuración). */
export async function probarServidor(url: string): Promise<Health> {
  const base = normalizarUrl(url)
  let r: Response
  try {
    r = await fetch(`${base}/api/v1/health`, { signal: AbortSignal.timeout(8000) })
  } catch (e) {
    throw new ErrorRed(e)
  }
  if (!r.ok) throw new ApiError(r.status, {})
  return (await r.json()) as Health
}

export const health = () => datos(cliente().GET('/api/v1/health'))

export const loginPin = (cuerpo: { pin?: string; codigo_carne?: string }) =>
  datos(cliente().POST('/api/v1/pos/auth/pin', { params: { header: tokenDispositivoHeader() }, body: cuerpo }))

export async function turnoActual(): Promise<Turno | null> {
  try {
    return await datos(cliente().GET('/api/v1/pos/turnos/actual'))
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

export const abrirTurno = (baseEfectivo: number) =>
  datos(cliente().POST('/api/v1/pos/turnos', { body: { base_efectivo: String(baseEfectivo) } }))

export const buscarProductos = (q: string, versionId?: string | null) =>
  datos(
    cliente().GET('/api/v1/catalogo/productos/buscar', {
      params: { query: { q: q || undefined, vehiculo_version_id: versionId ?? undefined, limit: 30 } },
    }),
  )

/** 404 ⇒ el código no existe (null). */
export async function productoPorCodigo(codigo: string): Promise<ProductoEscaneado | null> {
  try {
    return await datos(cliente().GET('/api/v1/pos/productos/codigo/{codigo}', { params: { path: { codigo } } }))
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

export const marcasVehiculo = () =>
  datos(cliente().GET('/api/v1/catalogo/vehiculos/marcas', { params: { query: { activo: true, limit: 200 } } }))
export const modelosDeMarca = (marcaId: string) =>
  datos(cliente().GET('/api/v1/catalogo/vehiculos/marcas/{marca_id}/modelos', { params: { path: { marca_id: marcaId } } }))
export const aniosDeModelo = (modeloId: string) =>
  datos(cliente().GET('/api/v1/catalogo/vehiculos/modelos/{modelo_id}/anios', { params: { path: { modelo_id: modeloId } } }))
export const versionesDe = (modeloId: string, anio: number) =>
  datos(
    cliente().GET('/api/v1/catalogo/vehiculos/versiones', {
      params: { query: { modelo_id: modeloId, anio, activo: true, limit: 100 } },
    }),
  )

export const buscarTerceros = (documento: string) =>
  datos(cliente().GET('/api/v1/pos/terceros', { params: { query: { documento } } }))
export const crearTercero = (cuerpo: S['TerceroRapidoIn']) => datos(cliente().POST('/api/v1/pos/terceros', { body: cuerpo }))

export const crearVenta = (cuerpo: VentaIn) => datos(cliente().POST('/api/v1/pos/ventas', { body: cuerpo }))

/** Consulta una venta por id (para saber si un intento con error de red llegó a registrarse). null ⇒ no existe. */
export async function ventaPorId(id: string): Promise<Venta | null> {
  try {
    return await datos(cliente().GET('/api/v1/pos/ventas/{venta_id}', { params: { path: { venta_id: id } } }))
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

export const estadoFiscal = (ventaId: string) =>
  datos(cliente().GET('/api/v1/pos/ventas/{venta_id}/estado-fiscal', { params: { path: { venta_id: ventaId } } }))
export const ticketDeVenta = (ventaId: string) =>
  datos(cliente().GET('/api/v1/pos/ventas/{venta_id}/ticket', { params: { path: { venta_id: ventaId } } }))

export const crearAutorizacion = (cuerpo: S['AutorizacionIn']) =>
  datos(cliente().POST('/api/v1/pos/autorizaciones', { body: cuerpo }))
export const crearSolicitud = (cuerpo: S['SolicitudIn']) =>
  datos(cliente().POST('/api/v1/pos/solicitudes-autorizacion', { body: cuerpo }))
export const estadoSolicitud = (id: string) =>
  datos(cliente().GET('/api/v1/pos/solicitudes-autorizacion/{solicitud_id}', { params: { path: { solicitud_id: id } } }))
