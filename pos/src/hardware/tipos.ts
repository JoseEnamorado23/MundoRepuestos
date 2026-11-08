// Interfaz de hardware: TODO acceso a impresora y cajón pasa por aquí. Dos implementaciones:
// HardwareTauri (ESC/POS por Rust) y HardwareNavegador (vista previa HTML + window.print).
import type { Tirilla } from './tirilla'

export type TipoImpresora = 'ninguna' | 'red' | 'windows'

export interface ConfigImpresora {
  tipo: TipoImpresora
  /** red: "192.168.1.50:9100" (puerto 9100 si se omite). windows: nombre exacto de la impresora instalada. */
  destino: string
  ancho: 80 | 58
  /** Si la impresora no soporta la página de códigos con tildes, imprime sin ellas (á→a, ñ→n). */
  sinTildes: boolean
  /** Abrir el cajón al cobrar en efectivo (pulso ESC p por la impresora). */
  abrirCajon: boolean
}

export const IMPRESORA_POR_DEFECTO: ConfigImpresora = {
  tipo: 'ninguna',
  destino: '',
  ancho: 80,
  sinTildes: false,
  abrirCajon: true,
}

export interface Hardware {
  readonly nombre: 'tauri' | 'navegador'
  /** Imprime la tirilla. En el navegador abre la vista previa y luego `window.print`. */
  imprimir(tirilla: Tirilla, cfg: ConfigImpresora): Promise<void>
  /** Pulso del cajón monedero. En el navegador es un aviso en pantalla. */
  abrirCajon(cfg: ConfigImpresora): Promise<void>
}

export class ErrorHardware extends Error {}
