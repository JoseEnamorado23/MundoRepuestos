import { useConfig } from '@/stores/config'
import { useSesion } from '@/stores/sesion'
import { configurarContexto } from './cliente'

/** Conecta el cliente de la API con los stores (URL, token del dispositivo, sesión). */
export function conectarApi() {
  configurarContexto({
    urlServidor: () => useConfig.getState().servidorUrl,
    tokenSesion: () => useSesion.getState().sesion?.token ?? null,
    tokenDispositivo: () => useConfig.getState().tokenDispositivo,
    alExpirarSesion: () => useSesion.getState().cerrar('La sesión expiró. Ingrese de nuevo con su PIN.'),
  })
}
