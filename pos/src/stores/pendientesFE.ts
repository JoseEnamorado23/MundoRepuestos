import { create } from 'zustand'
import { guardarJson, leerJson } from '@/storage/almacenamiento'

const CLAVE = 'mr.fe_pendientes'

/**
 * Ventas cuyo comprobante impreso fue PROVISIONAL (la FE no estaba aceptada). Quedan marcadas para reimprimir la
 * factura electrónica completa cuando la DIAN la acepte (la barra de estado lo avisa y permite imprimirla).
 */
interface Estado {
  ids: string[]
  marcar: (ventaId: string) => void
  quitar: (ventaId: string) => void
}

export const usePendientesFE = create<Estado>((set, get) => ({
  ids: leerJson<{ ids: string[] }>(CLAVE, { ids: [] }).ids,
  marcar: (id) => {
    if (get().ids.includes(id)) return
    const ids = [...get().ids, id]
    guardarJson(CLAVE, { ids })
    set({ ids })
  },
  quitar: (id) => {
    const ids = get().ids.filter((x) => x !== id)
    guardarJson(CLAVE, { ids })
    set({ ids })
  },
}))
