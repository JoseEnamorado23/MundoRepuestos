// HardwareNavegador: vista previa de la tirilla (HTML a 80/58 mm) e impresión con window.print; el cajón se simula.
import { useCajonSimulado, useVistaPrevia } from '@/stores/vistaPrevia'
import type { ConfigImpresora, Hardware } from './tipos'
import type { Tirilla } from './tirilla'

export const HardwareNavegador: Hardware = {
  nombre: 'navegador',
  async imprimir(tirilla: Tirilla, cfg: ConfigImpresora) {
    // La vista previa se muestra SIEMPRE; el usuario decide si manda a imprimir (botón o Enter).
    useVistaPrevia.getState().mostrar(tirilla, cfg.ancho)
  },
  async abrirCajon() {
    useCajonSimulado.getState().disparar()
  },
}
