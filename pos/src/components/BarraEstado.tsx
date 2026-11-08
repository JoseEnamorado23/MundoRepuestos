import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleAlert, Lock, Moon, Printer, Receipt, Settings, Sun, Wifi, WifiOff } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { estadoFiscal } from '@/api/pos'
import { Button } from '@/components/ui'
import { imprimirVenta } from '@/features/imprimir'
import { useSalud } from '@/hooks'
import { mensajeHumano } from '@/lib/errores'
import { cn } from '@/lib/utils'
import { useConfig } from '@/stores/config'
import { usePendientesFE } from '@/stores/pendientesFE'
import { useSesion } from '@/stores/sesion'
import { enTauri } from '@/storage/almacenamiento'

function Pastilla({ ok, aviso, icono, children, ...p }: { ok?: boolean; aviso?: boolean; icono: React.ReactNode; children: React.ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...p}
      className={cn(
        'flex min-h-9 items-center gap-1.5 rounded-full border-2 px-3 text-sm font-semibold',
        ok ? 'border-ok text-ok' : aviso ? 'border-aviso text-aviso' : 'border-error text-error',
      )}
    >
      {icono}
      {children}
    </div>
  )
}

/** Facturas que salieron como comprobante provisional: cuando la DIAN las acepta, se avisa y se imprime la FE. */
function FePorReimprimir() {
  const ids = usePendientesFE((s) => s.ids)
  const quitar = usePendientesFE((s) => s.quitar)
  const activo = useSesion((s) => !!s.sesion)
  const [imprimiendo, setImprimiendo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['fe-pendientes', ids],
    queryFn: async () => Promise.all(ids.map(async (id) => ({ id, e: await estadoFiscal(id).catch(() => null) }))),
    enabled: ids.length > 0 && activo,
    refetchInterval: 10_000,
  })
  if (!ids.length) return null
  const listas = (data ?? []).filter((x) => x.e?.definitivo).map((x) => x.id)
  async function imprimirListas() {
    setImprimiendo(true)
    setError(null)
    try {
      for (const id of listas) {
        await imprimirVenta(id)
        quitar(id)
      }
      void qc.invalidateQueries({ queryKey: ['fe-pendientes'] })
    } catch (e) {
      setError(mensajeHumano(e))
    } finally {
      setImprimiendo(false)
    }
  }
  return (
    <div className="flex items-center gap-2" data-testid="fe-pendientes">
      <Pastilla aviso icono={<Receipt className="size-4" aria-hidden />}>
        {ids.length} FE por reimprimir{listas.length ? ` · ${listas.length} lista(s)` : ''}
      </Pastilla>
      {listas.length > 0 && (
        <Button variante="primario" onClick={imprimirListas} disabled={imprimiendo}>
          <Printer className="size-4" aria-hidden /> Imprimir FE
        </Button>
      )}
      {error && <span className="text-sm text-error">{error}</span>}
    </div>
  )
}

export function BarraEstado() {
  const { data: salud, isError, isPending } = useSalud()
  const sesion = useSesion((s) => s.sesion)
  const cerrar = useSesion((s) => s.cerrar)
  const tema = useConfig((s) => s.tema)
  const actualizar = useConfig((s) => s.actualizar)
  const puedeAjustar = useSesion((s) => s.tiene('admin.configuracion'))
  const conectado = !!salud && !isError
  const f = salud?.fiscal
  const fiscalOk = !!f && f.worker_activo && !(f.rechazados ?? 0)
  const oscuro = document.documentElement.classList.contains('dark')

  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b-2 border-borde bg-superficie px-4 py-2">
      <Link to="/" className="text-xl font-extrabold tracking-tight">
        Mundo<span className="text-marca">Repuestos</span>
        <span className="ml-2 text-sm font-semibold text-suave">POS</span>
      </Link>
      <div className="flex flex-1 flex-wrap items-center gap-2">
        <Pastilla
          data-testid="estado-conexion"
          ok={conectado}
          aviso={isPending}
          icono={conectado ? <Wifi className="size-4" aria-hidden /> : <WifiOff className="size-4" aria-hidden />}
        >
          {isPending ? 'Conectando…' : conectado ? 'Servidor conectado' : 'Sin conexión con el servidor'}
        </Pastilla>
        {conectado && (
          <Pastilla
            data-testid="estado-fiscal"
            ok={fiscalOk}
            aviso={!!f && (!f.worker_activo || (f.pendientes ?? 0) > 0) && !(f.rechazados ?? 0)}
            icono={<CircleAlert className="size-4" aria-hidden />}
          >
            {f
              ? `Fiscal: ${f.worker_activo ? 'activo' : 'detenido'} · ${f.pendientes ?? 0} pendientes · ${f.rechazados ?? 0} rechazados`
              : 'Fiscal: sin datos'}
          </Pastilla>
        )}
        <FePorReimprimir />
      </div>
      <div className="flex items-center gap-2">
        {sesion && <span className="hidden text-sm text-suave sm:inline">{sesion.empleado_nombre}</span>}
        {sesion && puedeAjustar && (
          <Button variante="fantasma" tamano="icono" asChild aria-label="Ajustes">
            <Link to="/ajustes">
              <Settings className="size-5" />
            </Link>
          </Button>
        )}
        <Button
          variante="fantasma"
          tamano="icono"
          aria-label={oscuro ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
          onClick={() => actualizar({ tema: oscuro ? 'claro' : 'oscuro' })}
          data-tema={tema}
        >
          {oscuro ? <Sun className="size-5" /> : <Moon className="size-5" />}
        </Button>
        {sesion && (
          <Button variante="secundario" onClick={() => cerrar()} aria-label="Bloquear">
            <Lock className="size-4" aria-hidden /> Bloquear
          </Button>
        )}
      </div>
      {!enTauri() && (
        <p className="basis-full text-xs font-semibold text-aviso" data-testid="aviso-navegador">
          Modo navegador — solo desarrollo y demostración: el token del dispositivo se guarda en localStorage y la impresora es una vista previa.
        </p>
      )}
    </header>
  )
}
