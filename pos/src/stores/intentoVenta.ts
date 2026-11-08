import { create } from 'zustand'
import type { VentaIn } from '@/api/pos'
import { nuevoId } from '@/lib/id'

/**
 * Identidad de la venta en curso. El `id` (UUIDv7) se genera UNA vez por contenido de venta y se conserva en todos los
 * reintentos: así un error de red nunca produce una segunda venta. `pendiente` guarda el cuerpo exacto de un envío
 * cuyo resultado se desconoce (red caída); mientras exista, el carrito no se puede alterar sin resolverlo.
 */
interface Estado {
  id: string | null
  huella: string | null
  pendiente: VentaIn | null
  /** Devuelve el id vigente para esta huella; si el contenido cambió, uno nuevo. */
  idPara: (huella: string) => string
  marcarPendiente: (cuerpo: VentaIn | null) => void
  reiniciar: () => void
}

export const useIntentoVenta = create<Estado>((set, get) => ({
  id: null,
  huella: null,
  pendiente: null,
  idPara(huella) {
    const s = get()
    // con un envío de resultado desconocido, el id NO cambia aunque se haya tocado el carrito
    if (s.id && (s.pendiente || s.huella === huella)) return s.id
    const id = nuevoId()
    set({ id, huella, pendiente: null })
    return id
  },
  marcarPendiente: (pendiente) => set({ pendiente }),
  reiniciar: () => set({ id: null, huella: null, pendiente: null }),
}))
