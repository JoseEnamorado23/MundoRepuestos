// Detección de escáner HID (el lector se comporta como un teclado): una ráfaga de caracteres con menos de
// `umbralMs` entre teclas, terminada en Enter, es un escaneo; la escritura humana es más lenta.

export interface OpcionesEscaner {
  /** Máximo entre teclas consecutivas de una ráfaga (ms). */
  umbralMs: number
  /** Longitud mínima del código para considerarlo escaneo (evita Enter suelto o 1-2 teclas rápidas). */
  longitudMinima: number
}

export const ESCANER_POR_DEFECTO: OpcionesEscaner = { umbralMs: 30, longitudMinima: 4 }

export class DetectorEscaner {
  private buffer = ''
  private ultimo = 0

  constructor(private readonly op: OpcionesEscaner = ESCANER_POR_DEFECTO) {}

  /** Caracteres acumulados en la ráfaga actual (para limpiar el campo si resulta ser un escaneo). */
  get longitudBuffer(): number {
    return this.buffer.length
  }

  /**
   * Procesa una tecla. `tecla` es `KeyboardEvent.key`; `t` el instante en ms.
   * Devuelve el código si esta tecla (Enter) cierra un escaneo; `null` en cualquier otro caso.
   */
  procesar(tecla: string, t: number): string | null {
    if (tecla === 'Enter') {
      const codigo = this.buffer
      // el Enter del lector llega pegado al último carácter; un Enter humano tras una pausa no es escaneo
      const esEscaneo = codigo.length >= this.op.longitudMinima && t - this.ultimo <= this.op.umbralMs
      this.reiniciar()
      return esEscaneo ? codigo : null
    }
    if (tecla.length !== 1) return null // Shift, Tab, flechas, etc. no cortan ni forman parte de la ráfaga
    if (this.buffer.length > 0 && t - this.ultimo > this.op.umbralMs) {
      this.buffer = '' // pausa larga: lo anterior era escritura humana; esta tecla inicia un candidato nuevo
    }
    this.buffer += tecla
    this.ultimo = t
    return null
  }

  reiniciar(): void {
    this.buffer = ''
    this.ultimo = 0
  }
}
