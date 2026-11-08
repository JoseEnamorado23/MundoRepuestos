// Impresión de la venta: arma la tirilla desde el ticket de la API y la manda al hardware activo.
import { ticketDeVenta, type Ticket } from '@/api/pos'
import { hardware } from '@/hardware'
import { construirTirillaVenta } from '@/hardware/tirilla'
import { useConfig } from '@/stores/config'

export async function imprimirTicket(t: Ticket): Promise<void> {
  const cfg = useConfig.getState().impresora
  await hardware.imprimir(construirTirillaVenta(t, { ancho: cfg.ancho }), cfg)
}

export async function imprimirVenta(ventaId: string): Promise<Ticket> {
  const t = await ticketDeVenta(ventaId)
  await imprimirTicket(t)
  return t
}

export async function abrirCajonSiHayEfectivo(hayEfectivo: boolean): Promise<void> {
  const cfg = useConfig.getState().impresora
  if (hayEfectivo && cfg.abrirCajon) await hardware.abrirCajon(cfg)
}
