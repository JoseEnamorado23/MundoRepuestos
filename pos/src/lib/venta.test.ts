import { describe, expect, it, vi } from 'vitest'
import type { EstadoFiscal, Venta, VentaIn } from '@/api/pos'
import { ApiError, ErrorRed } from './errores'
import { construirCuerpoVenta, enviarVentaIdempotente, esperarEstadoFiscal, huellaVenta, type EntradaVenta } from './venta'

const entrada: EntradaVenta = {
  id: '01932c3e-0000-7000-8000-000000000001',
  terceroId: null,
  descuentoGlobalPct: 0,
  lineas: [{ productoId: 'p1', cantidad: 2, descuentoPct: 10, precioManual: null }],
  pagos: [
    { medio: 'efectivo', codigo: '10', valor: 50000 },
    { medio: 'tarjeta', codigo: '48', valor: 10000, referencia: 'AP123' },
  ],
}
const venta = (extra: Partial<Venta> = {}) => ({ id: entrada.id, estado: 'confirmada', ...extra }) as Venta
const sinEspera = async () => {}

describe('construirCuerpoVenta', () => {
  it('efectivo viaja como valor_recibido; tarjeta con valor y referencia', () => {
    const c = construirCuerpoVenta(entrada)
    expect(c.id).toBe(entrada.id)
    expect(c.pagos[0]).toEqual({ medio_pago_codigo: '10', valor_recibido: '50000', canal_pago: 'manual' })
    expect(c.pagos[1]).toMatchObject({ medio_pago_codigo: '48', valor: '10000', referencia: 'AP123' })
    expect(c.lineas[0]).toMatchObject({ producto_id: 'p1', cantidad: '2', descuento_pct: '10' })
    expect('precio_manual' in c.lineas[0]).toBe(false)
  })
  it('incluye la autorización de descuento cuando existe', () => {
    const c = construirCuerpoVenta({ ...entrada, autorizaciones: { descuentoId: 'aut-1' } })
    expect(c.autorizacion_descuento_id).toBe('aut-1')
  })
})

describe('enviarVentaIdempotente', () => {
  it('ante errores de red reintenta con EL MISMO id y el mismo cuerpo, y nunca crea un id nuevo', async () => {
    const cuerpo = construirCuerpoVenta(entrada)
    const recibidos: VentaIn[] = []
    const crear = vi
      .fn<(c: VentaIn) => Promise<Venta>>()
      .mockImplementationOnce(async (c) => {
        recibidos.push(c)
        throw new ErrorRed()
      })
      .mockImplementationOnce(async (c) => {
        recibidos.push(c)
        throw new ErrorRed()
      })
      .mockImplementationOnce(async (c) => {
        recibidos.push(c)
        return venta({ repetida: true })
      })
    const r = await enviarVentaIdempotente(cuerpo, { crear, esperar: sinEspera })
    expect(crear).toHaveBeenCalledTimes(3)
    expect(new Set(recibidos.map((c) => c.id))).toEqual(new Set([entrada.id]))
    expect(recibidos.every((c) => c === cuerpo)).toBe(true)
    expect(r.repetida).toBe(true)
  })

  it('un 5xx también se reintenta (el servidor es idempotente)', async () => {
    const crear = vi
      .fn<(c: VentaIn) => Promise<Venta>>()
      .mockRejectedValueOnce(new ApiError(503, {}))
      .mockResolvedValueOnce(venta())
    await enviarVentaIdempotente(construirCuerpoVenta(entrada), { crear, esperar: sinEspera })
    expect(crear).toHaveBeenCalledTimes(2)
  })

  it('un error de negocio (4xx) NO se reintenta', async () => {
    const crear = vi.fn<(c: VentaIn) => Promise<Venta>>().mockRejectedValue(new ApiError(422, { code: 'sin_precio' }))
    await expect(enviarVentaIdempotente(construirCuerpoVenta(entrada), { crear, esperar: sinEspera })).rejects.toBeInstanceOf(
      ApiError,
    )
    expect(crear).toHaveBeenCalledTimes(1)
  })

  it('agotados los intentos propaga el error de red (la venta queda pendiente de confirmar)', async () => {
    const crear = vi.fn<(c: VentaIn) => Promise<Venta>>().mockRejectedValue(new ErrorRed())
    await expect(
      enviarVentaIdempotente(construirCuerpoVenta(entrada), { crear, esperar: sinEspera, intentos: 3 }),
    ).rejects.toBeInstanceOf(ErrorRed)
    expect(crear).toHaveBeenCalledTimes(3)
  })
})

describe('huellaVenta', () => {
  it('es estable si el contenido no cambia y distinta si cambia una línea', () => {
    const h = huellaVenta(entrada)
    expect(huellaVenta({ ...entrada })).toBe(h)
    expect(huellaVenta({ ...entrada, lineas: [{ ...entrada.lineas[0], cantidad: 3 }] })).not.toBe(h)
  })
})

describe('esperarEstadoFiscal', () => {
  const estado = (e: string, definitivo = false) => ({ estado: e, definitivo }) as EstadoFiscal

  it('termina en cuanto queda aceptada', async () => {
    const consultar = vi
      .fn()
      .mockResolvedValueOnce(estado('pendiente_envio'))
      .mockResolvedValueOnce(estado('aceptado', true))
    let t = 0
    const r = await esperarEstadoFiscal('v', 8, { consultar, esperar: async (ms) => void (t += ms), ahora: () => t })
    expect(r?.estado).toBe('aceptado')
    expect(consultar).toHaveBeenCalledTimes(2)
  })

  it('al agotar el tiempo devuelve el último estado (sigue pendiente)', async () => {
    const consultar = vi.fn().mockResolvedValue(estado('pendiente_envio'))
    let t = 0
    const r = await esperarEstadoFiscal('v', 3, { consultar, esperar: async (ms) => void (t += ms), ahora: () => t })
    expect(r?.estado).toBe('pendiente_envio')
    expect(t).toBeLessThanOrEqual(3000)
  })

  it('un fallo de red no aborta la espera', async () => {
    const consultar = vi.fn().mockRejectedValueOnce(new ErrorRed()).mockResolvedValueOnce(estado('aceptado', true))
    let t = 0
    const r = await esperarEstadoFiscal('v', 8, { consultar, esperar: async (ms) => void (t += ms), ahora: () => t })
    expect(r?.definitivo).toBe(true)
  })

  it('se detiene si la DIAN rechaza', async () => {
    const consultar = vi.fn().mockResolvedValue(estado('rechazado'))
    let t = 0
    const r = await esperarEstadoFiscal('v', 8, { consultar, esperar: async (ms) => void (t += ms), ahora: () => t })
    expect(r?.estado).toBe('rechazado')
    expect(consultar).toHaveBeenCalledTimes(1)
  })
})
