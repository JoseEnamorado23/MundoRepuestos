import { describe, expect, it } from 'vitest'
import { ticketEjemplo } from '@/test/ticketEjemplo'
import { aHex, formatearFila, tirillaAEscPos } from './escpos'
import { aTextoPlano, construirTirillaPrueba, construirTirillaVenta, envolver, sinTildes } from './tirilla'

describe('plantilla de la tirilla', () => {
  it('FE aceptada: número, resolución, CUFE y QR', () => {
    const t = construirTirillaVenta(ticketEjemplo(), { ancho: 80 })
    const txt = aTextoPlano(t)
    expect(txt).toContain('FACTURA ELECTRÓNICA DE VENTA')
    expect(txt).toContain('SETP990000123')
    expect(txt).toContain('CUFE:')
    expect(txt).toContain('[QR https://catalogo-vpfe-hab.dian.gov.co')
    expect(txt).toContain('[CODE128 C1-000007]')
    expect(txt).not.toContain('PROVISIONAL')
  })

  it('sin FE aceptada: comprobante PROVISIONAL claro, sin CUFE ni QR', () => {
    const t = construirTirillaVenta(
      ticketEjemplo({ estado: 'pendiente_envio', numero_completo: null, cufe: null, qr_data: null, definitivo: false, leyenda: 'Factura electrónica pendiente de validación ante la DIAN' }),
      { ancho: 80 },
    )
    const txt = aTextoPlano(t)
    expect(txt).toContain('COMPROBANTE DE VENTA')
    expect(txt).toContain('PROVISIONAL - NO ES FACTURA')
    expect(txt).toContain('pendiente de validación')
    expect(txt).not.toContain('CUFE')
    expect(txt).not.toContain('[QR')
    expect(txt).toContain('[CODE128 C1-000007]') // el código de barras para devoluciones va siempre
  })

  it('ninguna línea de texto excede las columnas del papel (58 mm = 32)', () => {
    const t = construirTirillaVenta(ticketEjemplo(), { ancho: 58 })
    for (const l of aTextoPlano(t).split('\n')) if (!l.startsWith('[')) expect(l.length).toBeLessThanOrEqual(32)
  })

  it('envolver corta por palabras y trocea palabras largas', () => {
    expect(envolver('uno dos tres cuatro', 9)).toEqual(['uno dos', 'tres', 'cuatro'])
    expect(envolver('abcdefghij', 4)).toEqual(['abcd', 'efgh', 'ij'])
  })

  it('formatearFila conserva el valor de la derecha', () => {
    expect(formatearFila('Total', '$ 5.000', 20)).toHaveLength(20)
    const larga = formatearFila('Descripción larguísima del producto', '$ 5.000', 20)
    expect(larga).toHaveLength(20)
    expect(larga.endsWith('$ 5.000')).toBe(true)
  })

  it('sinTildes', () => {
    expect(sinTildes('Pastillas ñandú áéíóú ¿?')).toBe('Pastillas nandu aeiou ?')
  })
})

describe('codificación ESC/POS (snapshot de bytes)', () => {
  it('tirilla de FE aceptada a 80 mm', () => {
    const bytes = tirillaAEscPos(construirTirillaVenta(ticketEjemplo(), { ancho: 80 }))
    expect(aHex(bytes)).toMatchSnapshot()
  })

  it('comprobante provisional a 58 mm sin tildes', () => {
    const t = ticketEjemplo({ estado: 'pendiente_envio', numero_completo: null, cufe: null, qr_data: null, definitivo: false, leyenda: 'Pendiente' })
    expect(aHex(tirillaAEscPos(construirTirillaVenta(t, { ancho: 58 }), { sinTildes: true }))).toMatchSnapshot()
  })

  it('impresión de prueba con pulso de cajón', () => {
    expect(aHex(tirillaAEscPos(construirTirillaPrueba({ ancho: 80 }), { abrirCajon: true }))).toMatchSnapshot()
  })

  it('contiene los comandos clave: init, QR nativo (GS ( k), Code128 (GS k), corte (GS V) y pulso (ESC p)', () => {
    const hex = aHex(tirillaAEscPos(construirTirillaVenta(ticketEjemplo(), { ancho: 80 }), { abrirCajon: true }))
    expect(hex.startsWith('1b 40')).toBe(true) // ESC @
    expect(hex).toContain('1d 28 6b') // GS ( k  → QR
    expect(hex).toContain('1d 6b 49') // GS k 73 → Code128
    expect(hex).toContain('7b 42 43 31 2d 30 30 30 30 30 37') // «{B» + «C1-000007»
    expect(hex).toContain('1d 56') // GS V → corte
    expect(hex).toContain('1b 70') // ESC p → cajón
  })

  it('es determinista', () => {
    const t = construirTirillaVenta(ticketEjemplo(), { ancho: 80 })
    expect(aHex(tirillaAEscPos(t))).toBe(aHex(tirillaAEscPos(t)))
  })
})
