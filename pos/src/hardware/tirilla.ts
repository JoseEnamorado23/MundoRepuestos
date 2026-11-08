// Plantilla de la tirilla: UNA fuente de datos (el ticket de la API) → un documento intermedio (`Tirilla`) que dos
// renderizadores convierten: ESC/POS (bytes, `escpos.ts`) y HTML (vista previa, `VistaTirilla.tsx`).
import type { Ticket } from '@/api/pos'
import { aNumero, formatoCantidad, formatoCOP } from '@/lib/dinero'

export type Alineacion = 'izq' | 'centro' | 'der'

export type Bloque =
  | { t: 'texto'; s: string; alinear?: Alineacion; negrita?: boolean; grande?: boolean }
  | { t: 'fila'; izq: string; der: string; negrita?: boolean; grande?: boolean }
  | { t: 'sep'; doble?: boolean }
  | { t: 'qr'; datos: string }
  | { t: 'barras'; datos: string }
  | { t: 'espacio'; n?: number }
  | { t: 'corte' }

export interface Tirilla {
  /** Caracteres por línea con la fuente normal: 48 (80 mm) o 32 (58 mm). */
  columnas: number
  bloques: Bloque[]
}

export const columnasDe = (ancho: 80 | 58): number => (ancho === 80 ? 48 : 32)

/** Parte un texto en líneas de máximo `n` caracteres, cortando por palabras (y por caracteres si una palabra no cabe). */
export function envolver(texto: string, n: number): string[] {
  const salida: string[] = []
  let actual = ''
  for (const palabra of texto.split(/\s+/).filter(Boolean)) {
    let p = palabra
    while (p.length > n) {
      if (actual) {
        salida.push(actual)
        actual = ''
      }
      salida.push(p.slice(0, n))
      p = p.slice(n)
    }
    if (!actual) actual = p
    else if (actual.length + 1 + p.length <= n) actual += ' ' + p
    else {
      salida.push(actual)
      actual = p
    }
  }
  if (actual) salida.push(actual)
  return salida.length ? salida : ['']
}

/** Quita tildes y eñes para impresoras sin la página de códigos adecuada. */
export function sinTildes(s: string): string {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[¿¡]/g, '')
}

const fecha = (iso: string | null | undefined): string => {
  if (!iso) return ''
  return new Intl.DateTimeFormat('es-CO', {
    timeZone: 'America/Bogota',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
    .format(new Date(iso))
    .replace(',', '')
}
const soloFecha = (iso: string | null | undefined) => fecha(iso).split(' ')[0] ?? ''

export interface OpcionesTirilla {
  ancho: 80 | 58
}

/** Un ítem: descripción (envuelta) y debajo «cant x precio ........ total». */
function bloquesLinea(l: Ticket['lineas'][number], cols: number): Bloque[] {
  const b: Bloque[] = envolver(`${l.sku ? l.sku + ' ' : ''}${l.descripcion}`, cols).map(
    (s): Bloque => ({ t: 'texto', s }),
  )
  const detalle = `${formatoCantidad(l.cantidad)} x ${formatoCOP(l.precio_unitario)}`
  b.push({ t: 'fila', izq: '  ' + detalle, der: formatoCOP(l.total_linea) })
  if (aNumero(l.descuento_valor) > 0) b.push({ t: 'fila', izq: '  Descuento', der: '-' + formatoCOP(l.descuento_valor) })
  return b
}

/**
 * Tirilla de una venta. `fiscal.estado === 'aceptado'` ⇒ factura electrónica completa (número, CUFE, QR);
 * en cualquier otro estado es un COMPROBANTE DE VENTA provisional que lo dice claramente.
 */
export function construirTirillaVenta(t: Ticket, op: OpcionesTirilla): Tirilla {
  const cols = columnasDe(op.ancho)
  const aceptada = t.fiscal.estado === 'aceptado'
  const b: Bloque[] = []

  const nombre = t.empresa.nombre_comercial || t.empresa.razon_social
  for (const s of envolver(nombre, cols)) b.push({ t: 'texto', s, alinear: 'centro', negrita: true })
  if (t.empresa.nombre_comercial && t.empresa.nombre_comercial !== t.empresa.razon_social)
    for (const s of envolver(t.empresa.razon_social, cols)) b.push({ t: 'texto', s, alinear: 'centro' })
  b.push({ t: 'texto', s: `NIT ${t.empresa.nit}`, alinear: 'centro' })
  for (const s of envolver(`Sede ${t.sede.nombre}`, cols)) b.push({ t: 'texto', s, alinear: 'centro' })
  const dir = t.sede.direccion || t.empresa.direccion
  if (dir) for (const s of envolver(dir, cols)) b.push({ t: 'texto', s, alinear: 'centro' })
  const tel = t.sede.telefono || t.empresa.telefono
  if (tel) b.push({ t: 'texto', s: `Tel. ${tel}`, alinear: 'centro' })
  b.push({ t: 'sep' })

  if (aceptada) {
    b.push({ t: 'texto', s: 'FACTURA ELECTRÓNICA DE VENTA', alinear: 'centro', negrita: true })
    b.push({ t: 'texto', s: `No. ${t.fiscal.numero_completo ?? ''}`, alinear: 'centro', negrita: true })
    const r = t.resolucion
    if (r) {
      const txt =
        `Autorización DIAN No. ${r.numero_resolucion ?? ''} del ${soloFecha(r.fecha_resolucion)}` +
        ` prefijo ${r.prefijo ?? ''} del ${r.rango_desde ?? ''} al ${r.rango_hasta ?? ''}` +
        (r.vigente_hasta ? ` vigente hasta ${soloFecha(r.vigente_hasta)}` : '')
      for (const s of envolver(txt, cols)) b.push({ t: 'texto', s, alinear: 'centro' })
    }
  } else {
    b.push({ t: 'texto', s: 'COMPROBANTE DE VENTA', alinear: 'centro', negrita: true, grande: true })
    b.push({ t: 'texto', s: 'PROVISIONAL - NO ES FACTURA', alinear: 'centro', negrita: true })
    for (const s of envolver(
      t.fiscal.leyenda ?? 'La factura electrónica está pendiente de validación ante la DIAN.',
      cols,
    ))
      b.push({ t: 'texto', s, alinear: 'centro' })
    b.push({ t: 'texto', s: 'Conserve este comprobante: la factura se imprimirá cuando sea aceptada.', alinear: 'centro' })
  }
  b.push({ t: 'sep' })

  b.push({ t: 'fila', izq: 'Ticket', der: t.venta.numero_ticket })
  b.push({ t: 'fila', izq: 'Fecha', der: fecha(t.venta.fecha) })
  b.push({ t: 'fila', izq: 'Caja', der: t.caja.nombre })
  if (t.cajero) b.push({ t: 'fila', izq: 'Cajero', der: t.cajero })
  if (t.vendedor && t.vendedor !== t.cajero) b.push({ t: 'fila', izq: 'Vendedor', der: t.vendedor })
  if (t.venta.placa_vehiculo) b.push({ t: 'fila', izq: 'Placa', der: t.venta.placa_vehiculo })
  for (const s of envolver(`Cliente: ${t.cliente.nombre}`, cols)) b.push({ t: 'texto', s })
  if (!t.cliente.es_consumidor_final) b.push({ t: 'texto', s: `${t.cliente.tipo_documento === '31' ? 'NIT' : 'Doc.'} ${t.cliente.documento}` })
  b.push({ t: 'sep' })

  for (const l of t.lineas) b.push(...bloquesLinea(l, cols))
  b.push({ t: 'sep' })

  b.push({ t: 'fila', izq: 'Subtotal', der: formatoCOP(t.totales.subtotal) })
  if (aNumero(t.totales.descuento_total) > 0)
    b.push({ t: 'fila', izq: 'Descuentos', der: '-' + formatoCOP(t.totales.descuento_total) })
  for (const i of t.impuestos) b.push({ t: 'fila', izq: `IVA ${formatoCantidad(i.tarifa_pct)}%`, der: formatoCOP(i.impuesto) })
  if (aNumero(t.totales.redondeo) !== 0) b.push({ t: 'fila', izq: 'Redondeo', der: formatoCOP(t.totales.redondeo) })
  b.push({ t: 'fila', izq: 'TOTAL', der: formatoCOP(t.totales.total), negrita: true, grande: true })
  b.push({ t: 'sep' })

  for (const p of t.pagos) {
    const nombrePago = p.medio_pago ?? p.medio_pago_codigo
    b.push({ t: 'fila', izq: nombrePago + (p.referencia ? ` ${p.referencia}` : ''), der: formatoCOP(p.valor_recibido ?? p.valor) })
  }
  if (aNumero(t.cambio_total) > 0) b.push({ t: 'fila', izq: 'Cambio', der: formatoCOP(t.cambio_total), negrita: true })
  b.push({ t: 'sep' })

  if (aceptada) {
    if (t.fiscal.cufe) {
      b.push({ t: 'texto', s: 'CUFE:', negrita: true })
      for (const s of envolver(t.fiscal.cufe, cols)) b.push({ t: 'texto', s })
    }
    if (t.fiscal.qr_data) b.push({ t: 'espacio' }, { t: 'qr', datos: t.fiscal.qr_data })
  }
  b.push({ t: 'espacio' }, { t: 'barras', datos: t.venta.codigo_barras }, { t: 'espacio' })
  b.push({ t: 'texto', s: '¡Gracias por su compra!', alinear: 'centro', negrita: true })
  b.push({ t: 'texto', s: 'MundoRepuestos', alinear: 'centro' })
  b.push({ t: 'espacio', n: 3 }, { t: 'corte' })
  return { columnas: cols, bloques: b }
}

/** Impresión de prueba de la pantalla de configuración. */
export function construirTirillaPrueba(op: OpcionesTirilla): Tirilla {
  const cols = columnasDe(op.ancho)
  return {
    columnas: cols,
    bloques: [
      { t: 'texto', s: 'MundoRepuestos', alinear: 'centro', negrita: true, grande: true },
      { t: 'texto', s: 'Impresión de prueba', alinear: 'centro' },
      { t: 'sep' },
      { t: 'texto', s: `Papel ${op.ancho} mm - ${cols} columnas` },
      { t: 'texto', s: 'Tildes y eñes: áéíóú ñ ¿? ¡!' },
      { t: 'fila', izq: 'Total de prueba', der: formatoCOP(123456) },
      { t: 'sep', doble: true },
      { t: 'barras', datos: 'CAJA1-000001' },
      { t: 'espacio' },
      { t: 'qr', datos: 'https://mundorepuestos.example/prueba' },
      { t: 'espacio', n: 3 },
      { t: 'corte' },
    ],
  }
}

/** Texto plano de la tirilla con el ancho exacto (útil para pruebas y para depurar). */
export function aTextoPlano(t: Tirilla): string {
  const c = t.columnas
  const out: string[] = []
  for (const b of t.bloques) {
    if (b.t === 'texto') {
      const s = b.s
      out.push(b.alinear === 'centro' ? s.padStart(Math.floor((c + s.length) / 2)) : b.alinear === 'der' ? s.padStart(c) : s)
    } else if (b.t === 'fila') out.push(b.izq.padEnd(c - b.der.length) + b.der)
    else if (b.t === 'sep') out.push((b.doble ? '=' : '-').repeat(c))
    else if (b.t === 'qr') out.push(`[QR ${b.datos}]`)
    else if (b.t === 'barras') out.push(`[CODE128 ${b.datos}]`)
    else if (b.t === 'espacio') for (let i = 0; i < (b.n ?? 1); i++) out.push('')
  }
  return out.join('\n')
}
