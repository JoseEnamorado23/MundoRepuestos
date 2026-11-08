// Confirmación de la venta: cuerpo del POST /pos/ventas, reintento IDEMPOTENTE y espera del estado fiscal.
import type { EstadoFiscal, Venta, VentaIn } from '@/api/pos'
import { ApiError, ErrorRed } from './errores'
import type { PagoBorrador } from './dinero'

export interface PagoCobro extends PagoBorrador {
  /** Código DIAN del medio: 10 efectivo, 48 tarjeta crédito, 49 tarjeta débito, 47 transferencia/QR. */
  codigo: '10' | '48' | '49' | '47'
  referencia?: string
  canal?: 'manual' | 'datafono' | 'qr'
}

export interface Autorizaciones {
  descuentoId?: string
  precioId?: string
}

export interface EntradaVenta {
  id: string
  terceroId: string | null
  placa?: string | null
  descuentoGlobalPct: number
  lineas: { productoId: string; cantidad: number; descuentoPct: number; precioManual: number | null }[]
  pagos: PagoCobro[]
  autorizaciones?: Autorizaciones
}

/** Cuerpo de POST /pos/ventas. Dinero como texto para no perder precisión. */
export function construirCuerpoVenta(e: EntradaVenta): VentaIn {
  return {
    id: e.id,
    tercero_id: e.terceroId,
    placa_vehiculo: e.placa || null,
    descuento_global_pct: String(e.descuentoGlobalPct),
    lineas: e.lineas.map((l) => ({
      producto_id: l.productoId,
      cantidad: String(l.cantidad),
      descuento_pct: String(l.descuentoPct),
      ...(l.precioManual != null ? { precio_manual: String(l.precioManual) } : {}),
    })),
    pagos: e.pagos.map((p) =>
      p.codigo === '10'
        ? { medio_pago_codigo: '10', valor_recibido: String(p.valor), canal_pago: 'manual' as const }
        : {
            medio_pago_codigo: p.codigo,
            valor: String(p.valor),
            referencia: p.referencia || null,
            canal_pago: p.canal ?? 'manual',
          },
    ),
    autorizacion_descuento_id: e.autorizaciones?.descuentoId ?? null,
    autorizacion_precio_id: e.autorizaciones?.precioId ?? null,
  }
}

/** Huella del contenido de la venta (sin pagos ni autorizaciones): si no cambia, el id de la venta se conserva. */
export function huellaVenta(e: Pick<EntradaVenta, 'terceroId' | 'descuentoGlobalPct' | 'lineas' | 'placa'>): string {
  return JSON.stringify([e.terceroId, e.descuentoGlobalPct, e.placa ?? null, e.lineas])
}

export interface DepsEnvio {
  crear: (cuerpo: VentaIn) => Promise<Venta>
  esperar: (ms: number) => Promise<void>
  /** Intentos totales ante errores de red / 5xx. */
  intentos?: number
  alReintentar?: (intento: number, error: unknown) => void
}

const esReintentable = (e: unknown) => e instanceof ErrorRed || (e instanceof ApiError && e.status >= 500)

/**
 * Envía la venta. Ante un error de red o un 5xx reintenta con EL MISMO cuerpo (mismo `id`): el servidor es
 * idempotente por `id`, así que si el primer intento sí llegó, el reintento devuelve esa misma venta
 * (`repetida: true`) en lugar de crear otra. NUNCA se genera un id nuevo aquí.
 * Un error de negocio (4xx) no se reintenta: se propaga para mostrarlo.
 */
export async function enviarVentaIdempotente(cuerpo: VentaIn, deps: DepsEnvio): Promise<Venta> {
  const max = deps.intentos ?? 5
  let ultimo: unknown
  for (let n = 1; n <= max; n++) {
    try {
      return await deps.crear(cuerpo)
    } catch (e) {
      if (!esReintentable(e)) throw e
      ultimo = e
      if (n < max) {
        deps.alReintentar?.(n, e)
        await deps.esperar(Math.min(4000, 400 * 2 ** (n - 1)))
      }
    }
  }
  throw ultimo
}

export interface DepsFiscal {
  consultar: (ventaId: string) => Promise<EstadoFiscal>
  esperar: (ms: number) => Promise<void>
  ahora: () => number
}

/**
 * Consulta el estado fiscal cada `cadaMs` hasta que sea definitivo (aceptado), la DIAN rechace o pasen `segundos`.
 * Devuelve el último estado conocido (null si nunca pudo consultar). Un error de red no aborta la espera.
 */
export async function esperarEstadoFiscal(
  ventaId: string,
  segundos: number,
  deps: DepsFiscal,
  cadaMs = 1000,
): Promise<EstadoFiscal | null> {
  const limite = deps.ahora() + segundos * 1000
  let ultimo: EstadoFiscal | null = null
  for (;;) {
    try {
      ultimo = await deps.consultar(ventaId)
      if (ultimo.definitivo || ultimo.estado === 'rechazado') return ultimo
    } catch {
      /* se sigue intentando hasta el límite */
    }
    if (deps.ahora() + cadaMs > limite) return ultimo
    await deps.esperar(cadaMs)
  }
}
