import { describe, expect, it } from 'vitest'
import { DetectorEscaner } from './escaner'

/** Teclea `texto` con `intervalo` ms entre teclas empezando en `t0`; devuelve lo último que emitió el detector. */
function teclear(d: DetectorEscaner, texto: string, intervalo: number, t0 = 1000, conEnter = true) {
  let t = t0
  let salida: string | null = null
  for (const c of texto) {
    salida = d.procesar(c, t) ?? salida
    t += intervalo
  }
  if (conEnter) salida = d.procesar('Enter', t - intervalo + Math.min(intervalo, 10))
  return salida
}

describe('DetectorEscaner', () => {
  it('detecta una ráfaga rápida (5 ms entre teclas) terminada en Enter como escaneo', () => {
    expect(teclear(new DetectorEscaner(), '7701234567890', 5)).toBe('7701234567890')
  })

  it('detecta el escaneo justo en el límite del umbral (30 ms)', () => {
    expect(teclear(new DetectorEscaner(), '770123', 30)).toBe('770123')
  })

  it('NO toma como escaneo la escritura humana (120 ms entre teclas)', () => {
    expect(teclear(new DetectorEscaner(), '7701234567890', 120)).toBeNull()
  })

  it('NO es escaneo si es rápido pero demasiado corto (menos de 4 caracteres)', () => {
    expect(teclear(new DetectorEscaner(), '123', 5)).toBeNull()
  })

  it('un Enter humano tras una pausa no cierra un escaneo aunque haya caracteres en el buffer', () => {
    const d = new DetectorEscaner()
    teclear(d, '770123', 5, 1000, false)
    expect(d.procesar('Enter', 1000 + 6 * 5 + 2000)).toBeNull()
  })

  it('una ráfaga después de escritura lenta cuenta solo desde la pausa', () => {
    const d = new DetectorEscaner()
    teclear(d, 'ab', 200, 1000, false) // humano
    expect(teclear(d, 'CODIGO123', 4, 5000)).toBe('CODIGO123')
  })

  it('ignora teclas no imprimibles (Shift, flechas) dentro de la ráfaga', () => {
    const d = new DetectorEscaner()
    let t = 100
    for (const k of ['A', 'Shift', 'B', 'ArrowLeft', 'C', 'D', 'E']) {
      d.procesar(k, t)
      t += 5
    }
    expect(d.procesar('Enter', t)).toBe('ABCDE')
  })

  it('reinicia entre escaneos consecutivos', () => {
    const d = new DetectorEscaner()
    expect(teclear(d, 'AAAA1111', 5, 1000)).toBe('AAAA1111')
    expect(teclear(d, 'BBBB2222', 5, 2000)).toBe('BBBB2222')
  })

  it('respeta un umbral configurable', () => {
    const lento = new DetectorEscaner({ umbralMs: 80, longitudMinima: 4 })
    expect(teclear(lento, '12345678', 60)).toBe('12345678')
  })
})
