import { useMutation } from '@tanstack/react-query'
import { Delete, ScanLine } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { loginPin, turnoActual } from '@/api/pos'
import { Aviso, Button, Cargando } from '@/components/ui'
import { useEscaner } from '@/hooks'
import { mensajeHumano } from '@/lib/errores'
import { useSesion } from '@/stores/sesion'

const LARGO_PIN = 6

/** Pantalla de PIN: teclado numérico grande (táctil y físico) o escaneo del carné. */
export function Pin() {
  const navegar = useNavigate()
  const { iniciar, fijarTurno, aviso } = useSesion()
  const [pin, setPin] = useState('')

  const entrar = useMutation({
    mutationFn: async (cuerpo: { pin?: string; codigo_carne?: string }) => {
      const sesion = await loginPin(cuerpo)
      iniciar(sesion)
      fijarTurno(await turnoActual())
    },
    onSuccess: () => navegar('/', { replace: true }),
    onError: () => setPin(''),
  })

  const enviar = useCallback(
    (p: string) => {
      if (p.length >= 4 && !entrar.isPending) entrar.mutate({ pin: p })
    },
    [entrar],
  )

  // Teclado físico: dígitos, Retroceso y Enter (sin envío automático, para no chocar con el escáner de carné).
  useEffect(() => {
    const alTecla = (e: KeyboardEvent) => {
      if (/^\d$/.test(e.key)) setPin((p) => (p.length < LARGO_PIN ? p + e.key : p))
      else if (e.key === 'Backspace') setPin((p) => p.slice(0, -1))
      else if (e.key === 'Escape') setPin('')
      else if (e.key === 'Enter') enviar(pin)
    }
    window.addEventListener('keydown', alTecla)
    return () => window.removeEventListener('keydown', alTecla)
  }, [pin, enviar])

  // Carné escaneado: ráfaga + Enter, aunque ya se hubieran acumulado dígitos.
  useEscaner((codigo) => {
    setPin('')
    entrar.mutate({ codigo_carne: codigo })
  })

  const teclas = ['1', '2', '3', '4', '5', '6', '7', '8', '9']
  return (
    <main className="mx-auto flex max-w-md flex-col items-center gap-6 p-6">
      <div className="text-center">
        <h1 className="text-3xl font-bold">Ingrese su PIN</h1>
        <p className="mt-1 flex items-center justify-center gap-2 text-suave">
          <ScanLine className="size-5" aria-hidden /> o escanee su carné
        </p>
      </div>

      <div className="flex gap-3" role="img" aria-label={`${pin.length} de ${LARGO_PIN} dígitos`} data-testid="pin-puntos">
        {Array.from({ length: LARGO_PIN }, (_, i) => (
          <span key={i} className={`size-5 rounded-full border-2 border-texto ${i < pin.length ? 'bg-texto' : ''}`} />
        ))}
      </div>

      {aviso && !entrar.isError && <Aviso tipo="aviso" className="w-full">{aviso}</Aviso>}
      {entrar.isError && (
        <Aviso tipo="error" className="w-full">
          <span data-testid="pin-error">{mensajeHumano(entrar.error)}</span>
        </Aviso>
      )}
      {entrar.isPending && <Cargando texto="Verificando…" />}

      <div className="grid w-full grid-cols-3 gap-3">
        {teclas.map((t) => (
          <Button key={t} tamano="grande" className="h-20 text-3xl" onClick={() => setPin((p) => (p.length < LARGO_PIN ? p + t : p))}>
            {t}
          </Button>
        ))}
        <Button tamano="grande" variante="fantasma" className="h-20" onClick={() => setPin((p) => p.slice(0, -1))} aria-label="Borrar">
          <Delete className="size-8" />
        </Button>
        <Button tamano="grande" className="h-20 text-3xl" onClick={() => setPin((p) => (p.length < LARGO_PIN ? p + '0' : p))}>
          0
        </Button>
        <Button tamano="grande" variante="primario" className="h-20" onClick={() => enviar(pin)} disabled={pin.length < 4 || entrar.isPending} data-testid="pin-entrar">
          Entrar
        </Button>
      </div>

      <Link to="/config" className="text-sm text-suave underline">
        Configurar este equipo
      </Link>
    </main>
  )
}
