import { ArrowLeft, Printer } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Aviso, Button, Campo, Input, Select } from '@/components/ui'
import { hardware, type ConfigImpresora } from '@/hardware'
import { construirTirillaPrueba } from '@/hardware/tirilla'
import { mensajeHumano } from '@/lib/errores'
import { enTauri } from '@/storage/almacenamiento'
import { useConfig } from '@/stores/config'
import { useSesion } from '@/stores/sesion'

/** Configuración de la impresora y preferencias del equipo. Protegida con el permiso `admin.configuracion`. */
export function Ajustes() {
  const permitido = useSesion((s) => s.tiene('admin.configuracion'))
  const cfg = useConfig()
  const [resultado, setResultado] = useState<{ tipo: 'ok' | 'error'; texto: string } | null>(null)
  const imp = cfg.impresora

  if (!permitido)
    return (
      <main className="mx-auto max-w-xl p-6">
        <Aviso tipo="error">No tiene permiso para configurar el equipo. Pida ayuda a un administrador.</Aviso>
        <Button asChild className="mt-4"><Link to="/">Volver</Link></Button>
      </main>
    )

  const cambiar = (c: Partial<ConfigImpresora>) => cfg.actualizar({ impresora: { ...imp, ...c } })

  async function probar(accion: 'imprimir' | 'cajon') {
    setResultado(null)
    try {
      if (accion === 'imprimir') await hardware.imprimir(construirTirillaPrueba({ ancho: imp.ancho }), imp)
      else await hardware.abrirCajon(imp)
      setResultado({ tipo: 'ok', texto: accion === 'imprimir' ? 'Impresión de prueba enviada.' : 'Pulso de cajón enviado.' })
    } catch (e) {
      setResultado({ tipo: 'error', texto: mensajeHumano(e) })
    }
  }

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-5 p-6">
      <div className="flex items-center gap-3">
        <Button asChild variante="fantasma" tamano="icono" aria-label="Volver"><Link to="/"><ArrowLeft className="size-6" /></Link></Button>
        <h1 className="text-3xl font-bold">Ajustes del equipo</h1>
      </div>

      <section className="flex flex-col gap-4 rounded-xl border-2 border-borde bg-superficie p-5" aria-labelledby="t-impresora">
        <h2 id="t-impresora" className="flex items-center gap-2 text-xl font-bold"><Printer className="size-6" aria-hidden /> Impresora de tirillas</h2>
        {!enTauri() && <Aviso tipo="info">En el navegador la impresión es una vista previa (80 mm / 58 mm) con <code>window.print</code>; el cajón se simula.</Aviso>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Campo etiqueta="Tipo de conexión">
            <Select value={imp.tipo} onChange={(e) => cambiar({ tipo: e.target.value as ConfigImpresora['tipo'] })} aria-label="Tipo de conexión" data-testid="imp-tipo">
              <option value="ninguna">Sin impresora</option>
              <option value="red">Red (TCP, puerto 9100)</option>
              <option value="windows">Impresora de Windows (por nombre)</option>
            </Select>
          </Campo>
          <Campo etiqueta="Ancho del papel">
            <Select value={imp.ancho} onChange={(e) => cambiar({ ancho: Number(e.target.value) as 80 | 58 })} aria-label="Ancho del papel" data-testid="imp-ancho">
              <option value={80}>80 mm</option>
              <option value={58}>58 mm</option>
            </Select>
          </Campo>
        </div>
        {imp.tipo !== 'ninguna' && (
          <Campo
            etiqueta={imp.tipo === 'red' ? 'Dirección IP y puerto' : 'Nombre de la impresora'}
            ayuda={imp.tipo === 'red' ? 'Ejemplo: 192.168.1.50:9100 (si omite el puerto se usa 9100).' : 'Exactamente como aparece en Windows → Impresoras y escáneres.'}
          >
            <Input value={imp.destino} onChange={(e) => cambiar({ destino: e.target.value })} aria-label="Destino de la impresora" data-testid="imp-destino" />
          </Campo>
        )}
        <label className="flex min-h-11 items-center gap-3 text-lg"><input type="checkbox" className="size-6" checked={imp.abrirCajon} onChange={(e) => cambiar({ abrirCajon: e.target.checked })} /> Abrir el cajón monedero al cobrar en efectivo</label>
        <label className="flex min-h-11 items-center gap-3 text-lg"><input type="checkbox" className="size-6" checked={imp.sinTildes} onChange={(e) => cambiar({ sinTildes: e.target.checked })} /> Imprimir sin tildes (si la impresora muestra símbolos raros)</label>
        <div className="flex flex-wrap gap-3">
          <Button variante="primario" onClick={() => void probar('imprimir')} data-testid="imp-prueba">Impresión de prueba</Button>
          <Button onClick={() => void probar('cajon')} data-testid="imp-cajon">Probar cajón</Button>
        </div>
        {resultado && <Aviso tipo={resultado.tipo}>{resultado.texto}</Aviso>}
      </section>

      <section className="flex flex-col gap-4 rounded-xl border-2 border-borde bg-superficie p-5" aria-labelledby="t-pref">
        <h2 id="t-pref" className="text-xl font-bold">Preferencias</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <Campo etiqueta="Bloqueo por inactividad (min)" ayuda="0 = nunca">
            <Input type="number" min={0} max={240} value={cfg.inactividadMin} onChange={(e) => cfg.actualizar({ inactividadMin: Math.max(0, Number(e.target.value) || 0) })} aria-label="Minutos de inactividad" />
          </Campo>
          <Campo etiqueta="Espera de la DIAN (s)" ayuda="Antes de imprimir el comprobante provisional">
            <Input type="number" min={0} max={60} value={cfg.esperaFiscalSeg} onChange={(e) => cfg.actualizar({ esperaFiscalSeg: Math.max(0, Number(e.target.value) || 0) })} aria-label="Segundos de espera fiscal" data-testid="pref-espera" />
          </Campo>
          <Campo etiqueta="Umbral del escáner (ms)" ayuda="Tiempo máximo entre teclas">
            <Input type="number" min={10} max={200} value={cfg.umbralEscanerMs} onChange={(e) => cfg.actualizar({ umbralEscanerMs: Math.max(10, Number(e.target.value) || 30) })} aria-label="Umbral del escáner" />
          </Campo>
        </div>
        <label className="flex min-h-11 items-center gap-3 text-lg"><input type="checkbox" className="size-6" checked={cfg.sonido} onChange={(e) => cfg.actualizar({ sonido: e.target.checked })} /> Sonido al escanear</label>
        <Campo etiqueta="Tema">
          <Select value={cfg.tema} onChange={(e) => cfg.actualizar({ tema: e.target.value as 'sistema' | 'claro' | 'oscuro' })} aria-label="Tema">
            <option value="sistema">Según el sistema</option>
            <option value="claro">Claro</option>
            <option value="oscuro">Oscuro</option>
          </Select>
        </Campo>
      </section>

      <section className="rounded-xl border-2 border-borde bg-superficie p-5">
        <h2 className="mb-1 text-xl font-bold">Servidor y dispositivo</h2>
        <p className="mb-3 text-suave">{cfg.servidorUrl}</p>
        <Button asChild><Link to="/config">Cambiar servidor o token</Link></Button>
      </section>
    </main>
  )
}
