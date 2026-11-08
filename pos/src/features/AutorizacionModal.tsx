import { useMutation, useQuery } from '@tanstack/react-query'
import { Hourglass, KeyRound, ShieldCheck } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { crearAutorizacion, crearSolicitud, estadoSolicitud } from '@/api/pos'
import { Aviso, Button, Campo, Cargando, Input, Kbd, Modal } from '@/components/ui'
import { formatoCOP } from '@/lib/dinero'
import { mensajeHumano, type AutorizacionRequerida } from '@/lib/errores'
import { cn } from '@/lib/utils'

const NOMBRES: Record<string, string> = {
  'pos.descuento_mayor': 'Descuento mayor al permitido',
  'pos.cambiar_precio': 'Cambio de precio',
  'pos.devolver': 'Devolución',
  'pos.retirar_efectivo': 'Retiro de efectivo',
}

interface Props {
  requerida: AutorizacionRequerida | null
  /** La autorización se liga a este documento (la venta): debe ser el MISMO id con el que se repite la operación. */
  entidadTipo: string
  entidadId: string
  detalle?: Record<string, unknown>
  onAutorizada: (autorizacionId: string) => void
  onCancelar: () => void
}

type Via = 'pin_supervisor' | 'solicitud_remota'

/**
 * Se abre cuando la API responde 403 `autorizacion_requerida`. Ofrece las vías que indica la respuesta:
 * PIN de un supervisor presente o solicitud remota (espera la aprobación con cuenta regresiva).
 */
export function AutorizacionModal({ requerida, entidadTipo, entidadId, detalle, onAutorizada, onCancelar }: Props) {
  const vias = (requerida?.vias ?? []) as Via[]
  const [via, setVia] = useState<Via>('pin_supervisor')
  useEffect(() => {
    if (requerida) setVia(vias.includes('pin_supervisor') ? 'pin_supervisor' : 'solicitud_remota')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requerida])

  const titulo = requerida ? (NOMBRES[requerida.permiso] ?? 'Autorización requerida') : ''
  return (
    <Modal
      abierto={!!requerida}
      onCerrar={onCancelar}
      titulo={`Autorización: ${titulo}`}
      descripcion={
        requerida?.monto ? `Esta acción necesita la aprobación de otro empleado (${formatoCOP(requerida.monto)}).` : 'Esta acción necesita la aprobación de otro empleado.'
      }
      ancho="md"
    >
      {requerida && (
        <div className="flex flex-col gap-4" data-testid="modal-autorizacion">
          {vias.length > 1 && (
            <div role="tablist" className="grid grid-cols-2 gap-2">
              {(['pin_supervisor', 'solicitud_remota'] as Via[])
                .filter((v) => vias.includes(v))
                .map((v) => (
                  <Button
                    key={v}
                    role="tab"
                    aria-selected={via === v}
                    variante={via === v ? 'primario' : 'secundario'}
                    onClick={() => setVia(v)}
                    data-testid={`via-${v}`}
                  >
                    {v === 'pin_supervisor' ? <KeyRound className="size-5" aria-hidden /> : <Hourglass className="size-5" aria-hidden />}
                    {v === 'pin_supervisor' ? 'PIN de supervisor' : 'Aprobación remota'}
                  </Button>
                ))}
            </div>
          )}
          {via === 'pin_supervisor' ? (
            <PorPin requerida={requerida} entidadTipo={entidadTipo} entidadId={entidadId} detalle={detalle} onAutorizada={onAutorizada} onCancelar={onCancelar} />
          ) : (
            <Remota requerida={requerida} entidadTipo={entidadTipo} entidadId={entidadId} detalle={detalle} onAutorizada={onAutorizada} onCancelar={onCancelar} />
          )}
        </div>
      )}
    </Modal>
  )
}

type Interno = Omit<Props, 'requerida'> & { requerida: AutorizacionRequerida }

function PorPin({ requerida, entidadTipo, entidadId, detalle, onAutorizada, onCancelar }: Interno) {
  const [pin, setPin] = useState('')
  const [motivo, setMotivo] = useState('')
  const m = useMutation({
    mutationFn: () =>
      crearAutorizacion({
        pin,
        accion: requerida.permiso,
        entidad_tipo: entidadTipo,
        entidad_id: entidadId,
        detalle: { ...detalle, monto: requerida.monto },
        motivo: motivo.trim() || undefined,
      }),
    onSuccess: (a) => onAutorizada(a.autorizacion_id),
    onError: () => setPin(''),
  })
  function enviar(e: FormEvent) {
    e.preventDefault()
    if (pin.length >= 4 && !m.isPending) m.mutate()
  }
  return (
    <form onSubmit={enviar} className="flex flex-col gap-4">
      <Campo etiqueta="PIN del supervisor" ayuda="El supervisor debe ser otro empleado, presente en la tienda.">
        <Input
          type="password"
          inputMode="numeric"
          autoFocus
          autoComplete="off"
          maxLength={6}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
          className="text-center text-3xl tracking-[0.5em]"
          aria-label="PIN del supervisor"
          data-testid="aut-pin"
        />
      </Campo>
      <Campo etiqueta="Motivo (opcional)">
        <Input value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={300} aria-label="Motivo" />
      </Campo>
      {m.isError && <Aviso tipo="error">{mensajeHumano(m.error)}</Aviso>}
      <div className="flex justify-end gap-3">
        <Button onClick={onCancelar}>
          Cancelar <Kbd>Esc</Kbd>
        </Button>
        <Button type="submit" variante="primario" disabled={pin.length < 4 || m.isPending} data-testid="aut-confirmar">
          <ShieldCheck className="size-5" aria-hidden /> Autorizar
        </Button>
      </div>
    </form>
  )
}

function Remota({ requerida, entidadTipo, entidadId, detalle, onAutorizada, onCancelar }: Interno) {
  const [motivo, setMotivo] = useState('')
  const crear = useMutation({
    mutationFn: () =>
      crearSolicitud({
        accion: requerida.permiso,
        monto: requerida.monto,
        motivo: motivo.trim(),
        contexto: { ...detalle },
        entidad_tipo: entidadTipo,
        entidad_id: entidadId,
      }),
  })
  const sol = crear.data
  const consulta = useQuery({
    queryKey: ['solicitud-aut', sol?.id],
    queryFn: () => estadoSolicitud(sol!.id),
    enabled: !!sol,
    refetchInterval: (q) => (q.state.data && q.state.data.estado !== 'pendiente' ? false : (sol?.poll_ms ?? 2000)),
    retry: true,
  })
  const actual = consulta.data ?? sol
  const resuelta = actual && actual.estado !== 'pendiente'
  const cuenta = useCuentaRegresiva(actual?.expira_at, !!actual && !resuelta)

  useEffect(() => {
    if (actual?.estado === 'aprobada' && actual.autorizacion_id) onAutorizada(actual.autorizacion_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actual?.estado, actual?.autorizacion_id])

  if (!sol) {
    return (
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (motivo.trim().length >= 3 && !crear.isPending) crear.mutate()
        }}
      >
        <p className="text-base text-suave">Se enviará la solicitud al backoffice para que otro empleado la apruebe.</p>
        <Campo etiqueta="Motivo (obligatorio)">
          <Input autoFocus value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={300} aria-label="Motivo de la solicitud" data-testid="sol-motivo" />
        </Campo>
        {crear.isError && <Aviso tipo="error">{mensajeHumano(crear.error)}</Aviso>}
        <div className="flex justify-end gap-3">
          <Button onClick={onCancelar}>Cancelar</Button>
          <Button type="submit" variante="primario" disabled={motivo.trim().length < 3 || crear.isPending} data-testid="sol-enviar">
            Solicitar aprobación
          </Button>
        </div>
      </form>
    )
  }

  return (
    <div className="flex flex-col gap-4" data-testid="sol-espera">
      {actual?.estado === 'pendiente' && (
        <>
          <div className="flex flex-col items-center gap-2 rounded-lg border-2 border-borde p-6 text-center">
            <Cargando texto="Esperando aprobación…" />
            <p className={cn('text-5xl font-extrabold num', cuenta.restanteSeg <= 30 && 'text-error')} data-testid="sol-cuenta">
              {cuenta.texto}
            </p>
            <p className="text-sm text-suave">La solicitud vence automáticamente.</p>
          </div>
          <div className="flex justify-end">
            <Button onClick={onCancelar}>Cancelar</Button>
          </div>
        </>
      )}
      {actual?.estado === 'aprobada' && <Aviso tipo="ok">Aprobada. Continuando…</Aviso>}
      {actual?.estado === 'rechazada' && (
        <>
          <Aviso tipo="error">La solicitud fue rechazada{actual.comentario ? `: ${actual.comentario}` : '.'}</Aviso>
          <div className="flex justify-end">
            <Button variante="primario" onClick={onCancelar}>Cerrar</Button>
          </div>
        </>
      )}
      {actual?.estado === 'expirada' && (
        <>
          <Aviso tipo="aviso">La solicitud venció sin respuesta. Intente de nuevo o use el PIN de un supervisor.</Aviso>
          <div className="flex justify-end">
            <Button variante="primario" onClick={onCancelar}>Cerrar</Button>
          </div>
        </>
      )}
    </div>
  )
}

function useCuentaRegresiva(expiraAt: string | undefined, activo: boolean) {
  const [ahora, setAhora] = useState(() => Date.now())
  useEffect(() => {
    if (!activo) return
    const t = window.setInterval(() => setAhora(Date.now()), 500)
    return () => window.clearInterval(t)
  }, [activo])
  const restanteSeg = expiraAt ? Math.max(0, Math.ceil((new Date(expiraAt).getTime() - ahora) / 1000)) : 0
  const texto = `${String(Math.floor(restanteSeg / 60)).padStart(2, '0')}:${String(restanteSeg % 60).padStart(2, '0')}`
  return { restanteSeg, texto }
}
