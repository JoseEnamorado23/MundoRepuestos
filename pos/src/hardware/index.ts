import { enTauri } from '@/storage/almacenamiento'
import { HardwareNavegador } from './navegador'
import { HardwareTauri } from './tauri'
import type { Hardware } from './tipos'

/** Implementación según el entorno: la app de escritorio (Tauri) o el navegador (desarrollo y demo). */
export const hardware: Hardware = enTauri() ? HardwareTauri : HardwareNavegador

export * from './tipos'
