import { create } from 'zustand'
import type { Tirilla } from '@/hardware/tirilla'

/** Tirilla mostrada en la vista previa (modo navegador). La imprime `window.print` desde el modal. */
interface Estado {
  tirilla: Tirilla | null
  ancho: 80 | 58
  mostrar: (t: Tirilla, ancho: 80 | 58) => void
  cerrar: () => void
}

export const useVistaPrevia = create<Estado>((set) => ({
  tirilla: null,
  ancho: 80,
  mostrar: (tirilla, ancho) => set({ tirilla, ancho }),
  cerrar: () => set({ tirilla: null }),
}))

/** Aviso del cajón simulado (modo navegador). */
interface Cajon {
  visible: boolean
  disparar: () => void
  ocultar: () => void
}
export const useCajonSimulado = create<Cajon>((set) => ({
  visible: false,
  disparar: () => set({ visible: true }),
  ocultar: () => set({ visible: false }),
}))
