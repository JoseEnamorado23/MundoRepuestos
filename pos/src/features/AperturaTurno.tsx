import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { abrirTurno } from '@/api/pos'
import { Aviso, Button, Campo, Input, Kbd } from '@/components/ui'
import { formatoCOP } from '@/lib/dinero'
import { mensajeHumano } from '@/lib/errores'
import { useSesion } from '@/stores/sesion'

/** No hay turno abierto en la caja: se pide la base de efectivo. */
export function AperturaTurno() {
  const { sesion, fijarTurno } = useSesion()
  const [base, setBase] = useState('')
  const valor = Number(base.replace(/\D/g, '')) || 0
  const abrir = useMutation({ mutationFn: () => abrirTurno(valor), onSuccess: fijarTurno })

  function enviar(e: FormEvent) {
    e.preventDefault()
    if (!abrir.isPending) abrir.mutate()
  }

  return (
    <main className="mx-auto flex max-w-lg flex-col gap-5 p-6">
      <div>
        <h1 className="text-3xl font-bold">Abrir turno</h1>
        <p className="text-suave">Hola, {sesion?.empleado_nombre}. No hay un turno abierto en esta caja.</p>
      </div>
      <form onSubmit={enviar} className="flex flex-col gap-5 rounded-xl border-2 border-borde bg-superficie p-5">
        <Campo etiqueta="Base de efectivo en la caja" ayuda="Cuente el efectivo con el que inicia el turno.">
          <Input
            autoFocus
            inputMode="numeric"
            value={base ? Number(base.replace(/\D/g, '')).toLocaleString('es-CO') : ''}
            onChange={(e) => setBase(e.target.value)}
            placeholder="0"
            className="h-16 text-right text-4xl font-bold num"
            aria-label="Base de efectivo"
            data-testid="turno-base"
          />
        </Campo>
        <p className="text-center text-2xl font-bold num">{formatoCOP(valor)}</p>
        {abrir.isError && <Aviso tipo="error">{mensajeHumano(abrir.error)}</Aviso>}
        <Button type="submit" variante="primario" tamano="grande" disabled={abrir.isPending} data-testid="turno-abrir">
          Abrir turno <Kbd>Enter</Kbd>
        </Button>
      </form>
    </main>
  )
}
