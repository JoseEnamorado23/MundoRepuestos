// Renderizador HTML de la tirilla (80/58 mm): MISMA fuente de datos que el ESC/POS (`Tirilla`), otro renderizador.
import JsBarcode from 'jsbarcode'
import QRCode from 'qrcode'
import { Printer } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button, Kbd, Modal } from '@/components/ui'
import { formatearFila } from '@/hardware/escpos'
import type { Bloque, Tirilla } from '@/hardware/tirilla'
import { useCajonSimulado, useVistaPrevia } from '@/stores/vistaPrevia'
import { cn } from '@/lib/utils'

function Qr({ datos }: { datos: string }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    void QRCode.toDataURL(datos, { margin: 1, width: 180 }).then(setUrl)
  }, [datos])
  return url ? <img src={url} alt="Código QR de la factura" className="mx-auto my-1 size-36" /> : null
}

function Barras({ datos }: { datos: string }) {
  const ref = useRef<SVGSVGElement>(null)
  useEffect(() => {
    if (ref.current)
      JsBarcode(ref.current, datos, { format: 'CODE128', height: 44, displayValue: true, fontSize: 12, margin: 0 })
  }, [datos])
  return <svg ref={ref} role="img" aria-label={`Código de barras ${datos}`} className="mx-auto my-1 max-w-full" />
}

function Linea({ b, cols }: { b: Bloque; cols: number }) {
  switch (b.t) {
    case 'texto':
      return (
        <div
          className={cn('whitespace-pre-wrap break-words', b.negrita && 'font-bold', b.grande && 'text-base leading-tight')}
          style={{ textAlign: b.alinear === 'centro' ? 'center' : b.alinear === 'der' ? 'right' : 'left' }}
        >
          {b.s}
        </div>
      )
    case 'fila':
      return (
        <div className={cn('whitespace-pre', b.negrita && 'font-bold', b.grande && 'text-base')}>
          {formatearFila(b.izq, b.der, b.grande ? Math.floor(cols * 0.75) : cols)}
        </div>
      )
    case 'sep':
      return <div className="overflow-hidden whitespace-nowrap">{(b.doble ? '=' : '-').repeat(cols)}</div>
    case 'qr':
      return <Qr datos={b.datos} />
    case 'barras':
      return <Barras datos={b.datos} />
    case 'espacio':
      return <div style={{ height: `${(b.n ?? 1) * 0.9}em` }} />
    case 'corte':
      return <div className="my-2 border-t-2 border-dashed border-neutral-400 text-center text-[10px] text-neutral-500">✂ corte</div>
  }
}

export function VistaTirilla({ tirilla, ancho }: { tirilla: Tirilla; ancho: 80 | 58 }) {
  return (
    <div className={cn('tirilla', ancho === 80 ? 'w80' : 'w58')} data-testid="tirilla">
      {tirilla.bloques.map((b, i) => (
        <Linea key={i} b={b} cols={tirilla.columnas} />
      ))}
    </div>
  )
}

/** Vista previa en pantalla (modo navegador) con impresión por window.print. */
export function VistaPreviaModal() {
  const { tirilla, ancho, cerrar } = useVistaPrevia()
  return (
    <Modal abierto={!!tirilla} onCerrar={cerrar} titulo="Vista previa de la tirilla" descripcion={`Papel de ${ancho} mm`} ancho="md">
      {tirilla && (
        <>
          <div className="max-h-[60vh] overflow-auto rounded-lg border-2 border-borde bg-neutral-200 p-3" id="zona-impresion">
            <VistaTirilla tirilla={tirilla} ancho={ancho} />
          </div>
          <div className="mt-4 flex justify-end gap-3">
            <Button variante="secundario" onClick={cerrar}>
              Cerrar <Kbd>Esc</Kbd>
            </Button>
            <Button variante="primario" autoFocus onClick={() => window.print()}>
              <Printer className="size-5" aria-hidden /> Imprimir
            </Button>
          </div>
        </>
      )}
    </Modal>
  )
}

/** Aviso del cajón simulado (modo navegador). */
export function CajonSimulado() {
  const { visible, ocultar } = useCajonSimulado()
  useEffect(() => {
    if (!visible) return
    const t = window.setTimeout(ocultar, 4000)
    return () => window.clearTimeout(t)
  }, [visible, ocultar])
  if (!visible) return null
  return (
    <div role="status" data-testid="cajon-abierto" className="fixed bottom-4 left-1/2 z-[60] -translate-x-1/2 rounded-xl border-2 border-ok bg-superficie px-5 py-3 text-lg font-bold shadow-xl">
      💰 Cajón monedero abierto (simulado)
    </div>
  )
}
