// Almacenamiento. Secretos (token del dispositivo): llavero del sistema operativo en Tauri (comandos de Rust
// `secreto_*`, crate `keyring` → Administrador de credenciales de Windows); en modo navegador, localStorage
// (SOLO DESARROLLO). Preferencias no secretas: localStorage en ambos modos.

export const enTauri = (): boolean => typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

async function invocar<T>(comando: string, args: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(comando, args)
}

export async function leerSecreto(clave: string): Promise<string | null> {
  if (enTauri()) return (await invocar<string | null>('secreto_leer', { clave })) ?? null
  try {
    return localStorage.getItem(`mr.secreto.${clave}`)
  } catch {
    return null
  }
}

export async function guardarSecreto(clave: string, valor: string): Promise<void> {
  if (enTauri()) return invocar<void>('secreto_guardar', { clave, valor })
  localStorage.setItem(`mr.secreto.${clave}`, valor)
}

export async function borrarSecreto(clave: string): Promise<void> {
  if (enTauri()) return invocar<void>('secreto_borrar', { clave })
  localStorage.removeItem(`mr.secreto.${clave}`)
}

export function leerJson<T>(clave: string, porDefecto: T): T {
  try {
    const crudo = localStorage.getItem(clave)
    return crudo ? ({ ...porDefecto, ...JSON.parse(crudo) } as T) : porDefecto
  } catch {
    return porDefecto
  }
}

export function guardarJson(clave: string, valor: unknown): void {
  try {
    localStorage.setItem(clave, JSON.stringify(valor))
  } catch {
    /* almacenamiento lleno o bloqueado: la app sigue funcionando con los valores en memoria */
  }
}
