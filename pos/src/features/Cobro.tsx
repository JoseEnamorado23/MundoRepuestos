import { Banknote, CheckCircle2, CreditCard, Loader2, Printer, QrCode, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { crearVenta, estadoFiscal, ticketDeVenta, ventaPorId, type Ticket, type Venta } from '@/api/pos'
import { Aviso, Button, Campo, Input, Kbd, Modal } from '@/components/ui'
import { AutorizacionModal } from '@/features/AutorizacionModal'
import { abrirCajonSiHayEfectivo, imprimirTicket } from '@/features/imprimir'
import { useAtajos } from '@/hooks'
import { calcularCarrito, formatoCOP, redondearEfectivo, resumenCobro } from '@/lib/dinero'
import {
  ApiError,
  ErrorRed,
  comoAutorizacionRequerida,
  mensajeHumano,
  type AutorizacionRequerida,
} from '@/lib/errores'
import { cn } from '@/lib/utils'
import {
  construirCuerpoVenta,
  enviarVentaIdempotente,
  esperarEstadoFiscal,
  huellaVenta,
  type Autorizaciones,
  type EntradaVenta,
  type PagoCobro,
} from '@/lib/venta'
import { useCarrito } from '@/stores/carrito'
import { useConfig } from '@/stores/config'
import { useIntentoVenta } from '@/stores/intentoVenta'
import { usePendientesFE } from '@/stores/pendientesFE'
import { useSesion } from '@/stores/sesion'

type Medio = PagoCobro['codigo']
const MEDIOS: { codigo: Medio; tecla: string; nombre: string; medio: PagoCobro['medio']; icono: typeof Banknote }[] = [
  { codigo: '10', tecla: 'E', nombre: 'Efectivo', medio: 'efectivo', icono: Banknote },
  { codigo: '48', tecla: 'T', nombre: 'Tarjeta crédito', medio: 'tarjeta', icono: CreditCard },
  { codigo: '49', tecla: 'D', nombre: 'Tarjeta débito', medio: 'tarjeta', icono: CreditCard },
  { codigo: '47', tecla: 'Q', nombre: 'Transferencia / QR', medio: 'transferencia', icono: QrCode },
]
const BILLETES = [20000, 50000, 100000]

type Fase = 'editando' | 'enviando' | 'esperando_dian' | 'imprimiendo' | 'listo' | 'pendiente_red'

interface Resultado {
  venta: Venta
  ticket: Ticket | null
  aceptada: boolean
  errorImpresion: string | null
  errorCajon: string | null
}

const esperar = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
const aEntero = (t: string) => Number(t.replace(/\D/g, '')) || 0

export function Cobro({ abierto, onCerrar }: { abierto: boolean; onCerrar: () => void }) {
  const carrito = useCarrito()
  const sesion = useSesion((s) => s.sesion)
  const cfg = useConfig()
  const intento = useIntentoVenta()
  const marcarFE = usePendientesFE((s) => s.marcar)

  const [pagos, setPagos] = useState<PagoCobro[]>([])
  const [medio, setMedio] = useState<Medio>('10')
  const [valorTxt, setValorTxt] = useState('')
  const [refTxt, setRefTxt] = useState('')
  const [fase, setFase] = useState<Fase>('editando')
  const [error, setError] = useState<string | null>(null)
  const [reintento, setReintento] = useState(0)
  const [segundos, setSegundos] = useState(0)
  const [requerida, setRequerida] = useState<AutorizacionRequerida | null>(null)
  const [resultado, setResultado] = useState<Resultado | null>(null)
  const aut = useRef<Autorizaciones>({})
  const inputValor = useRef<HTMLInputElement>(null)

  const unidad = sesion?.redondeo_efectivo ?? 0
  const bruto = useMemo(
    () => calcularCarrito(carrito.lineas, carrito.descuentoGlobalPct),
    [carrito.lineas, carrito.descuentoGlobalPct],
  )
  const r = resumenCobro(bruto.total, pagos, unidad)
  const medioActual = MEDIOS.find((m) => m.codigo === medio)!

  // Al abrir: si quedó una venta con resultado desconocido (red caída), se retoma ESA, con su mismo cuerpo.
  useEffect(() => {
    if (!abierto) return
    if (intento.pendiente) setFase('pendiente_red')
    else if (fase !== 'listo') setFase('editando')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abierto])

  useEffect(() => {
    if (abierto && fase === 'editando') inputValor.current?.focus()
  }, [abierto, fase, medio])

  // Cuenta de segundos mientras se espera a la DIAN
  useEffect(() => {
    if (fase !== 'esperando_dian') return
    setSegundos(0)
    const t = window.setInterval(() => setSegundos((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [fase])

  /** Lo que falta por cobrar si se agrega un pago de este medio ahora. */
  function sugerido(m: PagoCobro['medio']): number {
    if (pagos.length === 0) return m === 'efectivo' ? redondearEfectivo(bruto.total, unidad).total : bruto.total
    return r.falta
  }

  function agregarPago() {
    const valor = aEntero(valorTxt) || sugerido(medioActual.medio)
    if (valor <= 0) return
    setPagos((p) => [
      ...p,
      {
        medio: medioActual.medio,
        codigo: medio,
        valor,
        referencia: medioActual.medio === 'efectivo' ? undefined : refTxt.trim() || undefined,
        canal: medio === '47' ? 'qr' : medio === '10' ? 'manual' : 'datafono',
      },
    ])
    setValorTxt('')
    setRefTxt('')
  }

  function entrada(id: string): EntradaVenta {
    return {
      id,
      terceroId: carrito.cliente && !carrito.cliente.es_consumidor_final ? carrito.cliente.id : null,
      descuentoGlobalPct: carrito.descuentoGlobalPct,
      lineas: carrito.lineas.map((l) => ({
        productoId: l.producto.id,
        cantidad: l.cantidad,
        descuentoPct: l.descuentoPct,
        precioManual: l.precioManual,
      })),
      pagos,
      autorizaciones: aut.current,
    }
  }

  async function confirmar() {
    setError(null)
    setFase('enviando')
    setReintento(0)
    const base = entrada('')
    const id = intento.idPara(huellaVenta(base)) // mismo contenido ⇒ MISMO id en cada intento
    const cuerpo = intento.pendiente ?? construirCuerpoVenta({ ...base, id })
    try {
      const venta = await enviarVentaIdempotente(cuerpo, {
        crear: crearVenta,
        esperar,
        alReintentar: (n) => setReintento(n),
      })
      await alConfirmarse(venta)
    } catch (e) {
      const req = comoAutorizacionRequerida(e)
      if (req) {
        setRequerida(req)
        setFase('editando')
      } else if (e instanceof ErrorRed || (e instanceof ApiError && e.status >= 500)) {
        intento.marcarPendiente(cuerpo) // se ignora si llegó: se reintenta con este mismo cuerpo
        setFase('pendiente_red')
      } else {
        setError(mensajeHumano(e))
        setFase('editando')
      }
    }
  }

  function autorizada(autorizacionId: string) {
    const a = requerida?.accion
    setRequerida(null)
    if (a === 'descuento_mayor') aut.current = { ...aut.current, descuentoId: autorizacionId }
    else if (a === 'cambiar_precio') aut.current = { ...aut.current, precioId: autorizacionId }
    else {
      setError(`Acción «${a}» sin soporte en esta pantalla.`)
      return
    }
    void confirmar() // se repite la operación con el MISMO id de venta y el autorizacion_id
  }

  async function verificarYDescartar() {
    const id = intento.id
    if (!id) return
    try {
      const existente = await ventaPorId(id)
      if (existente) {
        intento.marcarPendiente(null)
        await alConfirmarse(existente) // sí había llegado
      } else {
        intento.reiniciar() // no llegó: es seguro descartar y volver a editar
        setFase('editando')
        setError('La venta no se había registrado. Puede corregirla o volver a cobrar.')
      }
    } catch (e) {
      setError(mensajeHumano(e))
    }
  }

  /** La venta quedó registrada: cajón, espera de la DIAN (configurable) e impresión según el estado fiscal. */
  async function alConfirmarse(venta: Venta) {
    const hayEfectivo = pagos.some((p) => p.medio === 'efectivo')
    intento.reiniciar()
    carrito.vaciar()
    setPagos([])
    aut.current = {}
    let errorCajon: string | null = null
    let errorImpresion: string | null = null
    try {
      await abrirCajonSiHayEfectivo(hayEfectivo)
    } catch (e) {
      errorCajon = mensajeHumano(e)
    }
    setFase('esperando_dian')
    await esperarEstadoFiscal(venta.id, cfg.esperaFiscalSeg, { consultar: estadoFiscal, esperar, ahora: Date.now })
    setFase('imprimiendo')
    let ticket: Ticket | null = null
    try {
      ticket = await ticketDeVenta(venta.id)
      await imprimirTicket(ticket)
    } catch (e) {
      errorImpresion = mensajeHumano(e)
    }
    const aceptada = ticket?.fiscal.estado === 'aceptado'
    if (!aceptada) marcarFE(venta.id) // comprobante provisional ⇒ reimprimir la FE cuando sea aceptada
    setResultado({ venta, ticket, aceptada, errorImpresion, errorCajon })
    setFase('listo')
  }

  async function reintentarImpresion() {
    if (!resultado?.ticket) return
    try {
      await imprimirTicket(resultado.ticket)
      setResultado({ ...resultado, errorImpresion: null })
    } catch (e) {
      setResultado({ ...resultado, errorImpresion: mensajeHumano(e) })
    }
  }

  function terminar() {
    setResultado(null)
    setFase('editando')
    onCerrar()
  }

  useAtajos(
    {
      F8: () => {
        if (fase === 'editando' && r.suficiente) void confirmar()
      },
    },
    abierto,
  )

  function alTeclaValor(e: React.KeyboardEvent<HTMLInputElement>) {
    const m = MEDIOS.find((x) => x.tecla === e.key.toUpperCase())
    if (m && e.key.length === 1) {
      e.preventDefault()
      setMedio(m.codigo)
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      if (!valorTxt && r.suficiente && pagos.length) void confirmar()
      else agregarPago()
    }
  }

  const bloqueado = fase !== 'editando' && fase !== 'listo'
  return (
    <>
      <Modal
        abierto={abierto}
        onCerrar={() => (fase === 'listo' ? terminar() : onCerrar())}
        titulo={fase === 'listo' ? 'Venta registrada' : 'Cobrar'}
        ancho="lg"
        bloquear={bloqueado}
      >
        {fase === 'editando' && (
          <div className="grid gap-5 md:grid-cols-[1fr_20rem]" data-testid="cobro">
            <div className="flex flex-col gap-4">
              <div role="radiogroup" aria-label="Medio de pago" className="grid grid-cols-2 gap-2">
                {MEDIOS.map((m) => (
                  <Button
                    key={m.codigo}
                    role="radio"
                    aria-checked={medio === m.codigo}
                    variante={medio === m.codigo ? 'primario' : 'secundario'}
                    onClick={() => setMedio(m.codigo)}
                    className="justify-start"
                    data-testid={`medio-${m.codigo}`}
                  >
                    <m.icono className="size-5" aria-hidden /> {m.nombre} <Kbd>{m.tecla}</Kbd>
                  </Button>
                ))}
              </div>

              <Campo etiqueta={medioActual.medio === 'efectivo' ? 'Efectivo recibido' : `Valor a cobrar con ${medioActual.nombre.toLowerCase()}`}>
                <Input
                  ref={inputValor}
                  inputMode="numeric"
                  value={valorTxt ? aEntero(valorTxt).toLocaleString('es-CO') : ''}
                  placeholder={formatoCOP(sugerido(medioActual.medio))}
                  onChange={(e) => setValorTxt(e.target.value)}
                  onKeyDown={alTeclaValor}
                  className="h-16 text-right text-4xl font-bold num"
                  aria-label="Valor del pago"
                  data-testid="cobro-valor"
                />
              </Campo>

              {medioActual.medio === 'efectivo' ? (
                <div className="grid grid-cols-4 gap-2" aria-label="Billetes rápidos">
                  <Button onClick={() => setValorTxt(String(sugerido('efectivo')))} data-testid="billete-exacto">Exacto</Button>
                  {BILLETES.map((b) => (
                    <Button key={b} onClick={() => setValorTxt(String(b))} className="num" data-testid={`billete-${b}`}>
                      {formatoCOP(b)}
                    </Button>
                  ))}
                </div>
              ) : (
                <Campo etiqueta="Referencia / aprobación" ayuda="Número de aprobación del datáfono o del comprobante.">
                  <Input value={refTxt} onChange={(e) => setRefTxt(e.target.value)} maxLength={60} aria-label="Referencia" data-testid="cobro-ref" />
                </Campo>
              )}

              <Button variante="secundario" onClick={agregarPago} data-testid="cobro-agregar">
                Agregar pago <Kbd>Enter</Kbd>
              </Button>

              {pagos.length > 0 && (
                <ul className="flex flex-col gap-2" aria-label="Pagos agregados" data-testid="cobro-pagos">
                  {pagos.map((p, i) => (
                    <li key={i} className="flex items-center justify-between rounded-lg border-2 border-borde p-2 pl-3">
                      <span className="font-semibold">
                        {MEDIOS.find((m) => m.codigo === p.codigo)?.nombre}
                        {p.referencia && <span className="ml-2 font-normal text-suave">ref. {p.referencia}</span>}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="text-xl font-bold num">{formatoCOP(p.valor)}</span>
                        <Button variante="fantasma" tamano="icono" aria-label="Quitar pago" onClick={() => setPagos((x) => x.filter((_, j) => j !== i))}>
                          <Trash2 className="size-5" />
                        </Button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {error && <Aviso tipo="error">{error}</Aviso>}
            </div>

            <aside className="flex flex-col gap-3 rounded-xl border-2 border-borde bg-superficie2 p-4" aria-label="Resumen del cobro">
              <Fila etiqueta="Subtotal" valor={formatoCOP(bruto.bruto)} />
              {bruto.descuento > 0 && <Fila etiqueta="Descuentos" valor={'-' + formatoCOP(bruto.descuento)} />}
              {r.redondeo !== 0 && <Fila etiqueta="Redondeo" valor={formatoCOP(r.redondeo)} data-testid="cobro-redondeo" />}
              <div className="border-t-2 border-borde pt-2">
                <p className="text-sm font-semibold text-suave">TOTAL A PAGAR</p>
                <p className="text-5xl font-extrabold num" data-testid="cobro-total">{formatoCOP(r.total)}</p>
              </div>
              <Fila etiqueta="Pagado" valor={formatoCOP(r.pagado)} />
              <Fila etiqueta="Falta" valor={formatoCOP(r.falta)} fuerte={r.falta > 0} />
              <div className={cn('rounded-lg p-3 text-center', r.cambio > 0 ? 'bg-ok text-white' : 'bg-superficie')}>
                <p className="text-sm font-semibold">CAMBIO</p>
                <p className="text-5xl font-extrabold num" data-testid="cobro-cambio">{formatoCOP(r.cambio)}</p>
              </div>
              <Button variante="ok" tamano="grande" disabled={!r.suficiente || !pagos.length} onClick={() => void confirmar()} data-testid="cobro-confirmar">
                Confirmar venta <Kbd>F8</Kbd>
              </Button>
              <Button variante="fantasma" onClick={onCerrar}>
                Volver al carrito <Kbd>Esc</Kbd>
              </Button>
            </aside>
          </div>
        )}

        {fase === 'enviando' && (
          <Progreso texto={reintento ? `Sin respuesta del servidor. Reintentando (${reintento})…` : 'Registrando la venta…'} />
        )}
        {fase === 'esperando_dian' && (
          <Progreso texto={`Validando la factura con la DIAN… ${segundos}/${cfg.esperaFiscalSeg} s`} />
        )}
        {fase === 'imprimiendo' && <Progreso texto="Imprimiendo…" />}

        {fase === 'pendiente_red' && (
          <div className="flex flex-col gap-4" data-testid="venta-pendiente">
            <Aviso tipo="aviso">
              <p className="font-semibold">No se pudo confirmar si la venta quedó registrada.</p>
              <p>Se conserva el mismo número de venta: reintentar NO crea una venta duplicada.</p>
            </Aviso>
            {error && <Aviso tipo="error">{error}</Aviso>}
            <div className="flex flex-wrap justify-end gap-3">
              <Button variante="fantasma" onClick={onCerrar}>Cerrar (queda pendiente)</Button>
              <Button onClick={() => void verificarYDescartar()}>Verificar si se registró</Button>
              <Button variante="primario" tamano="grande" onClick={() => void confirmar()}>
                Reintentar
              </Button>
            </div>
          </div>
        )}

        {fase === 'listo' && resultado && <Listo r={resultado} onReimprimir={reintentarImpresion} onTerminar={terminar} />}
      </Modal>

      <AutorizacionModal
        requerida={requerida}
        entidadTipo="venta"
        entidadId={intento.id ?? ''}
        detalle={{ total: bruto.total }}
        onAutorizada={autorizada}
        onCancelar={() => setRequerida(null)}
      />
    </>
  )
}

function Fila({ etiqueta, valor, fuerte, ...p }: { etiqueta: string; valor: string; fuerte?: boolean } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className="flex items-baseline justify-between" {...p}>
      <span className="text-suave">{etiqueta}</span>
      <span className={cn('text-xl num', fuerte && 'font-bold text-error')}>{valor}</span>
    </div>
  )
}

function Progreso({ texto }: { texto: string }) {
  return (
    <div className="flex flex-col items-center gap-4 py-10" role="status" aria-live="polite" data-testid="cobro-progreso">
      <Loader2 className="size-14 animate-spin text-acento" aria-hidden />
      <p className="text-2xl font-semibold">{texto}</p>
    </div>
  )
}

function Listo({ r, onReimprimir, onTerminar }: { r: Resultado; onReimprimir: () => void; onTerminar: () => void }) {
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => ref.current?.focus(), [])
  return (
    <div className="flex flex-col gap-4" data-testid="venta-lista">
      <div className="flex items-center gap-4">
        <CheckCircle2 className="size-14 text-ok" aria-hidden />
        <div>
          <p className="text-2xl font-bold num">Total {formatoCOP(r.venta.total)}</p>
          {Number(r.venta.cambio) > 0 && <p className="text-4xl font-extrabold text-ok num">Cambio {formatoCOP(r.venta.cambio)}</p>}
        </div>
      </div>
      {r.aceptada ? (
        <Aviso tipo="ok">
          <span data-testid="fiscal-resultado">Factura electrónica aceptada: <strong>{r.ticket?.fiscal.numero_completo}</strong>. Se imprimió la factura completa.</span>
        </Aviso>
      ) : (
        <Aviso tipo="aviso">
          <span data-testid="fiscal-resultado">
            La factura aún no está aceptada por la DIAN. Se imprimió un <strong>comprobante de venta provisional</strong>; la factura se podrá reimprimir cuando sea aceptada (la barra superior avisará).
          </span>
        </Aviso>
      )}
      {r.errorCajon && <Aviso tipo="aviso">No se pudo abrir el cajón: {r.errorCajon}</Aviso>}
      {r.errorImpresion && (
        <Aviso tipo="error">
          <p>No se pudo imprimir: {r.errorImpresion}</p>
          <Button className="mt-2" onClick={onReimprimir}>
            <Printer className="size-4" aria-hidden /> Reintentar impresión
          </Button>
        </Aviso>
      )}
      <div className="flex justify-end">
        <Button ref={ref} variante="primario" tamano="grande" onClick={onTerminar} data-testid="nueva-venta">
          Nueva venta <Kbd>Enter</Kbd>
        </Button>
      </div>
    </div>
  )
}
