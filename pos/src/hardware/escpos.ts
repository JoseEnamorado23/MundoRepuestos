// Renderizador ESC/POS: Tirilla -> bytes, con @point-of-sale/receipt-printer-encoder (librería mantenida).
import ReceiptPrinterEncoder from '@point-of-sale/receipt-printer-encoder'
import { sinTildes as quitarTildes, type Bloque, type Tirilla } from './tirilla'

export interface OpcionesEscPos {
  sinTildes?: boolean
  /** Añade el pulso de apertura de cajón (ESC p) al inicio. */
  abrirCajon?: boolean
}

/** Una fila «izq … der» ajustada a `cols`: si no cabe, se recorta la izquierda para conservar el valor de la derecha. */
export function formatearFila(izq: string, der: string, cols: number): string {
  const disponible = cols - der.length - 1
  const i = izq.length > disponible ? izq.slice(0, Math.max(0, disponible - 1)) + '…' : izq
  return i + ' '.repeat(Math.max(1, cols - i.length - der.length)) + der
}

function aplicar(e: ReceiptPrinterEncoder, b: Bloque, cols: number, t: (s: string) => string): void {
  switch (b.t) {
    case 'texto': {
      e.align(b.alinear === 'centro' ? 'center' : b.alinear === 'der' ? 'right' : 'left')
      if (b.negrita) e.bold(true)
      if (b.grande) e.size(2, 2)
      e.line(t(b.s))
      if (b.grande) e.size('normal')
      if (b.negrita) e.bold(false)
      e.align('left')
      break
    }
    case 'fila': {
      if (b.negrita) e.bold(true)
      if (b.grande) e.size(1, 2) // doble alto, ancho normal: no se pierde la mitad de la línea
      e.line(t(formatearFila(b.izq, b.der, cols)))
      if (b.grande) e.size('normal')
      if (b.negrita) e.bold(false)
      break
    }
    case 'sep':
      e.line((b.doble ? '=' : '-').repeat(cols))
      break
    case 'qr':
      e.align('center').qrcode(b.datos, { model: 2, size: 6, errorlevel: 'm' }).align('left')
      break
    case 'barras':
      e.align('center').barcode(b.datos, 'code128', { height: 60, text: true }).align('left')
      break
    case 'espacio':
      e.newline(b.n ?? 1)
      break
    case 'corte':
      e.cut('partial')
      break
  }
}

/** Bytes ESC/POS de la tirilla. Determinista: la misma entrada da los mismos bytes (se prueba con snapshot). */
export function tirillaAEscPos(tirilla: Tirilla, op: OpcionesEscPos = {}): Uint8Array {
  const e = new ReceiptPrinterEncoder({ language: 'esc-pos', columns: tirilla.columnas, codepageMapping: 'epson',
    // strict: si algo no se puede codificar (símbolo no soportado, etc.) se lanza un error en vez de omitirlo en silencio
    errors: 'strict',
  })
  e.initialize()
  if (!op.sinTildes) e.codepage('auto')
  if (op.abrirCajon) e.pulse()
  const t = op.sinTildes ? quitarTildes : (s: string) => s
  for (const b of tirilla.bloques) aplicar(e, b, tirilla.columnas, t)
  return e.encode()
}

/** Solo el pulso del cajón (ESC p m t1 t2). */
export function pulsoCajon(): Uint8Array {
  return new ReceiptPrinterEncoder({ language: 'esc-pos' }).initialize().pulse().encode()
}

export const aHex = (b: Uint8Array): string => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join(' ')
