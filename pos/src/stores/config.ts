import { create } from 'zustand'
import { IMPRESORA_POR_DEFECTO, type ConfigImpresora } from '@/hardware/tipos'
import { borrarSecreto, guardarJson, guardarSecreto, leerJson, leerSecreto } from '@/storage/almacenamiento'

const CLAVE = 'mr.config'
const SECRETO_DISPOSITIVO = 'dispositivo_token'

export interface Preferencias {
  servidorUrl: string
  impresora: ConfigImpresora
  /** Minutos sin actividad para bloquear (volver al PIN). 0 = nunca. */
  inactividadMin: number
  /** Segundos máximos esperando que la FE quede aceptada antes de imprimir el comprobante provisional. */
  esperaFiscalSeg: number
  /** Máximo entre teclas (ms) para considerar una ráfaga como escaneo. */
  umbralEscanerMs: number
  sonido: boolean
  tema: 'sistema' | 'claro' | 'oscuro'
}

export const PREFERENCIAS_POR_DEFECTO: Preferencias = {
  servidorUrl: '',
  impresora: IMPRESORA_POR_DEFECTO,
  inactividadMin: 5,
  esperaFiscalSeg: 8,
  umbralEscanerMs: 30,
  sonido: true,
  tema: 'sistema',
}

interface Estado extends Preferencias {
  cargado: boolean
  /** Token del dispositivo (secreto): llavero del sistema en Tauri; localStorage en el navegador. */
  tokenDispositivo: string | null
  cargar: () => Promise<void>
  actualizar: (cambios: Partial<Preferencias>) => void
  guardarServidor: (url: string, token: string) => Promise<void>
  olvidarDispositivo: () => Promise<void>
}

function aplicarTema(tema: Preferencias['tema']) {
  const oscuro = tema === 'oscuro' || (tema === 'sistema' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', oscuro)
}

export const useConfig = create<Estado>((set, get) => ({
  ...PREFERENCIAS_POR_DEFECTO,
  cargado: false,
  tokenDispositivo: null,

  async cargar() {
    const p = leerJson<Preferencias>(CLAVE, PREFERENCIAS_POR_DEFECTO)
    const impresora = { ...IMPRESORA_POR_DEFECTO, ...p.impresora }
    let tokenDispositivo: string | null = null
    try {
      tokenDispositivo = await leerSecreto(SECRETO_DISPOSITIVO)
    } catch {
      tokenDispositivo = null
    }
    set({ ...p, impresora, tokenDispositivo, cargado: true })
    aplicarTema(p.tema)
  },

  actualizar(cambios) {
    set(cambios)
    const { cargado: _c, tokenDispositivo: _t, ...resto } = get() as Estado
    const prefs: Preferencias = {
      servidorUrl: resto.servidorUrl,
      impresora: resto.impresora,
      inactividadMin: resto.inactividadMin,
      esperaFiscalSeg: resto.esperaFiscalSeg,
      umbralEscanerMs: resto.umbralEscanerMs,
      sonido: resto.sonido,
      tema: resto.tema,
    }
    guardarJson(CLAVE, prefs)
    if (cambios.tema) aplicarTema(cambios.tema)
  },

  async guardarServidor(url, token) {
    await guardarSecreto(SECRETO_DISPOSITIVO, token)
    set({ tokenDispositivo: token })
    get().actualizar({ servidorUrl: url })
  },

  async olvidarDispositivo() {
    await borrarSecreto(SECRETO_DISPOSITIVO)
    set({ tokenDispositivo: null })
  },
}))

export const estaConfigurado = (s: { servidorUrl: string; tokenDispositivo: string | null }) =>
  !!s.servidorUrl && !!s.tokenDispositivo
