// Dinero en COP: se muestra SIN decimales (es-CO). La API entrega decimales como texto ("12500.00"); el servidor es
// quien calcula los totales definitivos, aquí solo hay estimaciones para mostrar y el cambio del cobro.

const fmt = new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 })
const fmtNum = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 3 })

export function aNumero(v: string | number | null | undefined): number {
  if (v === null || v === undefined || v === '') return 0
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

/** "$ 12.500" (sin decimales). */
export function formatoCOP(v: string | number | null | undefined): string {
  return fmt.format(Math.round(aNumero(v))).replace(/ /g, ' ')
}

export function formatoCantidad(v: string | number): string {
  return fmtNum.format(aNumero(v))
}

/** Redondeo half-up a 2 decimales (centavos), igual que `r2` del backend. */
export function r2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100
}

export interface LineaCalculable {
  cantidad: number
  /** Precio unitario de venta, con IVA incluido (D-10 del modelo). */
  precio: number
  descuentoPct: number
}

/** Mismo orden de operaciones que `armar` del backend: d1 sobre el bruto, d2 (global) sobre lo que queda. */
export function calcularLinea(l: LineaCalculable, descuentoGlobalPct: number) {
  const bruto = r2(l.cantidad * l.precio)
  const d1 = r2((bruto * l.descuentoPct) / 100)
  const d2 = r2(((bruto - d1) * descuentoGlobalPct) / 100)
  return { bruto, descuento: r2(d1 + d2), total: r2(bruto - d1 - d2) }
}

export function calcularCarrito(lineas: LineaCalculable[], descuentoGlobalPct: number) {
  let bruto = 0
  let descuento = 0
  let total = 0
  for (const l of lineas) {
    const c = calcularLinea(l, descuentoGlobalPct)
    bruto += c.bruto
    descuento += c.descuento
    total += c.total
  }
  return { bruto: r2(bruto), descuento: r2(descuento), total: r2(total) }
}

/** Redondeo del total cuando TODO el pago es en efectivo: half-up a `unidad` (0 = sin redondeo, 50 o 100). */
export function redondearEfectivo(total: number, unidad: number): { redondeo: number; total: number } {
  if (!unidad) return { redondeo: 0, total }
  const redondeado = Math.round(total / unidad) * unidad
  return { redondeo: r2(redondeado - total), total: redondeado }
}

/** Cambio a devolver: lo recibido por encima de lo que se debe en efectivo (nunca negativo). */
export function calcularCambio(totalAPagar: number, recibido: number): number {
  return Math.max(0, r2(recibido - totalAPagar))
}

export interface PagoBorrador {
  medio: 'efectivo' | 'tarjeta' | 'transferencia'
  /** efectivo: lo recibido; otros: el valor a cobrar. */
  valor: number
}

/** Resumen del cobro: redondeo (solo si todo es efectivo), lo pagado, lo que falta y el cambio. */
export function resumenCobro(totalSinRedondeo: number, pagos: PagoBorrador[], unidadRedondeo: number) {
  const soloEfectivo = pagos.length > 0 && pagos.every((p) => p.medio === 'efectivo')
  const { redondeo, total } = soloEfectivo
    ? redondearEfectivo(totalSinRedondeo, unidadRedondeo)
    : { redondeo: 0, total: totalSinRedondeo }
  const noEfectivo = pagos.filter((p) => p.medio !== 'efectivo').reduce((s, p) => s + p.valor, 0)
  const efectivoRecibido = pagos.filter((p) => p.medio === 'efectivo').reduce((s, p) => s + p.valor, 0)
  const efectivoDebido = Math.max(0, r2(total - noEfectivo))
  const pagado = r2(noEfectivo + efectivoRecibido)
  const cambio = efectivoRecibido > 0 ? calcularCambio(efectivoDebido, efectivoRecibido) : 0
  return {
    soloEfectivo,
    redondeo,
    total,
    pagado,
    falta: Math.max(0, r2(total - pagado)),
    efectivoDebido,
    cambio,
    suficiente: pagado >= total && noEfectivo <= total,
  }
}
