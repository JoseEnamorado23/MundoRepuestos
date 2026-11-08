// Hooks transversales: escáner HID global, bloqueo por inactividad, atajos de teclado y salud del servidor.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { health } from '@/api/pos'
import { DetectorEscaner } from '@/lib/escaner'
import { useConfig } from '@/stores/config'
import { useSesion } from '@/stores/sesion'

/** Escribe un valor en un input controlado por React (el setter nativo + evento `input`). */
export function fijarValorInput(el: HTMLInputElement | HTMLTextAreaElement, valor: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value')?.set?.call(el, valor)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

/**
 * Escáner de código de barras (teclado HID): detecta ráfagas rápidas terminadas en Enter en CUALQUIER parte de la
 * pantalla, aunque el foco no esté en el buscador. Si el foco estaba en un campo de texto, se le devuelve el valor
 * que tenía antes de la ráfaga (los caracteres del lector no deben quedar escritos ahí).
 */
export function useEscaner(alEscanear: (codigo: string) => void, activo = true) {
  const umbral = useConfig((s) => s.umbralEscanerMs)
  const cb = useRef(alEscanear)
  cb.current = alEscanear

  useEffect(() => {
    if (!activo) return
    const detector = new DetectorEscaner({ umbralMs: umbral, longitudMinima: 4 })
    let campo: HTMLInputElement | HTMLTextAreaElement | null = null
    let valorAntes = ''
    let ultimaTecla = -Infinity

    const alTecla = (ev: KeyboardEvent) => {
      if (ev.ctrlKey || ev.altKey || ev.metaKey) return
      const t = ev.target
      const esCampo = t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement
      if (ev.key.length === 1) {
        // Una ráfaga nueva empieza cuando el buffer está vacío o hubo una pausa larga desde la tecla anterior
        // (el detector hará el mismo reinicio): ahí se guarda el valor que tenía el campo ANTES de esta tecla.
        if (detector.longitudBuffer === 0 || ev.timeStamp - ultimaTecla > umbral) {
          campo = esCampo ? t : null
          valorAntes = esCampo ? t.value : ''
        }
        ultimaTecla = ev.timeStamp
      }
      const codigo = detector.procesar(ev.key, ev.timeStamp)
      if (codigo !== null) {
        ev.preventDefault()
        ev.stopPropagation()
        if (campo) fijarValorInput(campo, valorAntes)
        cb.current(codigo)
      }
    }
    window.addEventListener('keydown', alTecla, true)
    return () => window.removeEventListener('keydown', alTecla, true)
  }, [umbral, activo])
}

/** Bloqueo por inactividad: sin actividad durante `minutos`, descarta la sesión (vuelve a la pantalla de PIN). */
export function useInactividad(minutos: number, activo: boolean) {
  const cerrar = useSesion((s) => s.cerrar)
  useEffect(() => {
    if (!activo || minutos <= 0) return
    let temporizador = window.setTimeout(bloquear, minutos * 60_000)
    function bloquear() {
      cerrar('Sesión bloqueada por inactividad. Ingrese su PIN para continuar.')
    }
    const reiniciar = () => {
      window.clearTimeout(temporizador)
      temporizador = window.setTimeout(bloquear, minutos * 60_000)
    }
    const eventos = ['keydown', 'pointerdown', 'pointermove', 'wheel'] as const
    for (const e of eventos) window.addEventListener(e, reiniciar, { passive: true })
    return () => {
      window.clearTimeout(temporizador)
      for (const e of eventos) window.removeEventListener(e, reiniciar)
    }
  }, [minutos, activo, cerrar])
}

/** Atajos de teclado (F2, F4…). `permitirEnCampos`: teclas que funcionan aunque el foco esté en un input. */
export function useAtajos(mapa: Record<string, (e: KeyboardEvent) => void>, activo = true) {
  const ref = useRef(mapa)
  ref.current = mapa
  useEffect(() => {
    if (!activo) return
    const alTecla = (e: KeyboardEvent) => {
      const f = ref.current[e.key]
      if (f) {
        e.preventDefault()
        f(e)
      }
    }
    window.addEventListener('keydown', alTecla)
    return () => window.removeEventListener('keydown', alTecla)
  }, [activo])
}

/** Estado del servidor (conexión, BD, worker fiscal) cada 10 s. */
export function useSalud() {
  const configurado = useConfig((s) => !!s.servidorUrl)
  return useQuery({
    queryKey: ['salud'],
    queryFn: health,
    enabled: configurado,
    refetchInterval: 10_000,
    retry: false,
    staleTime: 5_000,
  })
}
