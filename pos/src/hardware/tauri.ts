// HardwareTauri: ESC/POS armado en TypeScript y enviado por comandos de Rust (imprimir_raw / abrir_cajon).
import { tirillaAEscPos } from './escpos'
import { ErrorHardware, type ConfigImpresora, type Hardware } from './tipos'
import type { Tirilla } from './tirilla'

/** Destino que entiende Rust: «tcp://host:puerto» o «windows://Nombre de la impresora». */
export function destinoDe(cfg: ConfigImpresora): string {
  if (cfg.tipo === 'ninguna' || !cfg.destino.trim())
    throw new ErrorHardware('No hay impresora configurada. Configúrela en Ajustes → Impresora.')
  if (cfg.tipo === 'red') {
    const d = cfg.destino.trim()
    return `tcp://${d.includes(':') ? d : d + ':9100'}`
  }
  return `windows://${cfg.destino.trim()}`
}

async function invocar(comando: string, args: Record<string, unknown>): Promise<void> {
  const { invoke } = await import('@tauri-apps/api/core')
  try {
    await invoke(comando, args)
  } catch (e) {
    throw new ErrorHardware(typeof e === 'string' ? e : 'No se pudo comunicar con la impresora.')
  }
}

export const HardwareTauri: Hardware = {
  nombre: 'tauri',
  async imprimir(tirilla: Tirilla, cfg: ConfigImpresora) {
    const bytes = tirillaAEscPos(tirilla, { sinTildes: cfg.sinTildes })
    await invocar('imprimir_raw', { destino: destinoDe(cfg), bytes: Array.from(bytes) })
  },
  async abrirCajon(cfg: ConfigImpresora) {
    // el pulso (ESC p) lo arma Rust: así el cajón se abre sin depender de la capa web
    await invocar('abrir_cajon', { destino: destinoDe(cfg) })
  },
}
