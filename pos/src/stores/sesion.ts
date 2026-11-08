import { create } from 'zustand'
import type { Sesion, Turno } from '@/api/pos'

// La sesión POS (JWT) vive SOLO en memoria: cerrar la app, bloquear o expirar la descarta.
interface Estado {
  sesion: Sesion | null
  turno: Turno | null
  /** Mensaje para mostrar en la pantalla de PIN (p. ej. «La sesión expiró»). */
  aviso: string | null
  iniciar: (s: Sesion) => void
  fijarTurno: (t: Turno | null) => void
  cerrar: (aviso?: string) => void
  tiene: (permiso: string) => boolean
}

export const useSesion = create<Estado>((set, get) => ({
  sesion: null,
  turno: null,
  aviso: null,
  iniciar: (sesion) => set({ sesion, aviso: null }),
  fijarTurno: (turno) => set({ turno }),
  cerrar: (aviso) => set({ sesion: null, turno: null, aviso: aviso ?? null }),
  tiene: (permiso) => !!get().sesion?.permisos?.includes(permiso),
}))
