import { describe, expect, it } from 'vitest'
import {
  calcularCambio,
  calcularCarrito,
  calcularLinea,
  formatoCOP,
  redondearEfectivo,
  resumenCobro,
} from './dinero'

describe('formatoCOP', () => {
  it('sin decimales y con separador de miles es-CO', () => {
    expect(formatoCOP('12500.00')).toBe('$ 12.500')
    expect(formatoCOP(1234567.4)).toBe('$ 1.234.567')
    expect(formatoCOP(null)).toBe('$ 0')
  })
})

describe('calcularCambio', () => {
  it('devuelve lo recibido por encima del total', () => {
    expect(calcularCambio(23800, 50000)).toBe(26200)
    expect(calcularCambio(23800, 23800)).toBe(0)
  })
  it('nunca es negativo si falta dinero', () => {
    expect(calcularCambio(23800, 20000)).toBe(0)
  })
})

describe('redondeo en efectivo', () => {
  it('half-up a 50 y a 100; 0 = sin redondeo', () => {
    expect(redondearEfectivo(23830, 50)).toEqual({ redondeo: 20, total: 23850 })
    expect(redondearEfectivo(23820, 50)).toEqual({ redondeo: -20, total: 23800 })
    expect(redondearEfectivo(23824, 50)).toEqual({ redondeo: -24, total: 23800 })
    expect(redondearEfectivo(23850, 100)).toEqual({ redondeo: 50, total: 23900 })
    expect(redondearEfectivo(23820, 0)).toEqual({ redondeo: 0, total: 23820 })
  })
})

describe('resumenCobro', () => {
  it('redondea solo cuando TODO el pago es en efectivo', () => {
    const efectivo = resumenCobro(23830, [{ medio: 'efectivo', valor: 50000 }], 50)
    expect(efectivo).toMatchObject({ soloEfectivo: true, redondeo: 20, total: 23850, cambio: 26150, suficiente: true })

    const mixto = resumenCobro(
      23820,
      [
        { medio: 'tarjeta', valor: 10000 },
        { medio: 'efectivo', valor: 20000 },
      ],
      50,
    )
    expect(mixto).toMatchObject({ soloEfectivo: false, redondeo: 0, total: 23820, efectivoDebido: 13820, cambio: 6180 })
  })

  it('indica lo que falta y no es suficiente mientras no se cubra el total', () => {
    const r = resumenCobro(20000, [{ medio: 'tarjeta', valor: 5000 }], 0)
    expect(r).toMatchObject({ falta: 15000, suficiente: false, cambio: 0 })
  })

  it('un pago no efectivo por encima del total no es válido', () => {
    expect(resumenCobro(20000, [{ medio: 'tarjeta', valor: 25000 }], 0).suficiente).toBe(false)
  })
})

describe('calcularCarrito (mismo orden que el backend)', () => {
  it('aplica el descuento de línea y luego el global sobre lo que queda', () => {
    // bruto 2 x 10.000 = 20.000; d1 10% = 2.000; d2 5% de 18.000 = 900
    expect(calcularLinea({ cantidad: 2, precio: 10000, descuentoPct: 10 }, 5)).toEqual({
      bruto: 20000,
      descuento: 2900,
      total: 17100,
    })
    expect(calcularCarrito([{ cantidad: 1, precio: 5000, descuentoPct: 0 }], 0).total).toBe(5000)
  })
})
