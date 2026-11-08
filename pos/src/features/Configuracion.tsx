import { CheckCircle2, Server } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { probarServidor, type Health } from '@/api/pos'
import { Aviso, Button, Campo, Cargando, Input } from '@/components/ui'
import { mensajeHumano } from '@/lib/errores'
import { enTauri } from '@/storage/almacenamiento'
import { useConfig } from '@/stores/config'

/** Primera ejecución: URL del servidor local (con prueba contra /health) y token del dispositivo. */
export function Configuracion() {
  const navegar = useNavigate()
  const guardado = useConfig()
  const [url, setUrl] = useState(guardado.servidorUrl || 'http://localhost:8000')
  const [token, setToken] = useState('')
  const [probando, setProbando] = useState(false)
  const [salud, setSalud] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  async function probar() {
    setProbando(true)
    setError(null)
    setSalud(null)
    try {
      setSalud(await probarServidor(url))
    } catch (e) {
      setError(mensajeHumano(e))
    } finally {
      setProbando(false)
    }
  }

  async function guardar(ev: FormEvent) {
    ev.preventDefault()
    if (!salud) return void probar()
    if (!token.trim()) return setError('Pegue el token del dispositivo que entregó el administrador.')
    setGuardando(true)
    try {
      await guardado.guardarServidor(url.trim(), token.trim())
      navegar('/', { replace: true })
    } catch (e) {
      setError(mensajeHumano(e))
    } finally {
      setGuardando(false)
    }
  }

  return (
    <main className="mx-auto flex max-w-xl flex-col gap-5 p-6">
      <div className="flex items-center gap-3">
        <Server className="size-9 text-marca" aria-hidden />
        <div>
          <h1 className="text-3xl font-bold">Configurar este equipo</h1>
          <p className="text-suave">Conecte el POS con el servidor de la tienda y registre el dispositivo.</p>
        </div>
      </div>

      <form onSubmit={guardar} className="flex flex-col gap-5 rounded-xl border-2 border-borde bg-superficie p-5">
        <Campo etiqueta="Dirección del servidor local" ayuda="Ejemplo: http://192.168.1.10:8000">
          <div className="flex gap-2">
            <Input
              value={url}
              onChange={(e) => {
                setUrl(e.target.value)
                setSalud(null)
              }}
              inputMode="url"
              autoFocus
              aria-label="Dirección del servidor local"
              data-testid="cfg-url"
            />
            <Button variante="secundario" onClick={probar} disabled={probando || !url.trim()} data-testid="cfg-probar">
              Probar conexión
            </Button>
          </div>
        </Campo>

        {probando && <Cargando texto="Probando conexión…" />}
        {salud && (
          <Aviso tipo={salud.estado === 'ok' ? 'ok' : 'aviso'}>
            <p className="flex items-center gap-2 font-semibold" data-testid="cfg-resultado">
              <CheckCircle2 className="size-4" aria-hidden /> Conectado: {salud.nodo_nombre ?? 'servidor'} ({salud.modo}) · versión{' '}
              {salud.version_app}
            </p>
            {salud.estado !== 'ok' && <p>El servidor responde, pero informa un estado degradado.</p>}
          </Aviso>
        )}

        <Campo
          etiqueta="Token del dispositivo"
          ayuda="Lo entrega el administrador al registrar este equipo (se muestra una sola vez). Se guarda cifrado en el sistema."
        >
          <Input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoComplete="off"
            aria-label="Token del dispositivo"
            data-testid="cfg-token"
          />
        </Campo>

        {error && <Aviso tipo="error">{error}</Aviso>}
        {!enTauri() && (
          <Aviso tipo="aviso">
            Modo navegador: el token se guardará en localStorage. <strong>Solo para desarrollo y demostración.</strong>
          </Aviso>
        )}

        <div className="flex justify-end gap-3">
          {guardado.servidorUrl && (
            <Button variante="fantasma" onClick={() => navegar('/', { replace: true })}>
              Cancelar
            </Button>
          )}
          <Button type="submit" variante="primario" tamano="grande" disabled={guardando || !salud} data-testid="cfg-guardar">
            Guardar y continuar
          </Button>
        </div>
      </form>
    </main>
  )
}
