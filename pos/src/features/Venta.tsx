import { useQuery } from '@tanstack/react-query'
import { Car, Minus, PackageSearch, Plus, Search, Trash2, User, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { buscarProductos, productoPorCodigo } from '@/api/pos'
import { Aviso, Button, Cargando, Input, Kbd, Modal } from '@/components/ui'
import { Cobro } from '@/features/Cobro'
import { ClienteDialog, NumeroDialog, VehiculoDialog } from '@/features/Dialogos'
import { useAtajos, useEscaner } from '@/hooks'
import { aNumero, calcularCarrito, calcularLinea, formatoCantidad, formatoCOP } from '@/lib/dinero'
import { mensajeHumano } from '@/lib/errores'
import { sonidoError, sonidoOk } from '@/lib/sonido'
import { cn } from '@/lib/utils'
import { useCarrito, type ItemProducto } from '@/stores/carrito'
import { useConfig } from '@/stores/config'
import { useIntentoVenta } from '@/stores/intentoVenta'
import { useSesion } from '@/stores/sesion'

type Dialogo = null | 'cliente' | 'vehiculo' | 'cobro' | 'cancelar' | 'desc-global' | 'cantidad' | 'desc-linea' | 'precio'

function useDebounce<T>(valor: T, ms: number): T {
  const [v, setV] = useState(valor)
  useEffect(() => {
    const t = window.setTimeout(() => setV(valor), ms)
    return () => window.clearTimeout(t)
  }, [valor, ms])
  return v
}

export function Venta() {
  const carrito = useCarrito()
  const sonido = useConfig((s) => s.sonido)
  const puedeCambiarPrecio = useSesion((s) => s.tiene('pos.cambiar_precio'))
  const pendiente = useIntentoVenta((s) => s.pendiente)

  const [q, setQ] = useState('')
  const qDeb = useDebounce(q.trim(), 250)
  const [sel, setSel] = useState(0)
  const [selLinea, setSelLinea] = useState(0)
  const [dialogo, setDialogo] = useState<Dialogo>(null)
  const [aviso, setAviso] = useState<{ tipo: 'ok' | 'error'; texto: string; n: number } | null>(null)
  const buscador = useRef<HTMLInputElement>(null)
  const listaCarrito = useRef<HTMLUListElement>(null)

  const versionId = carrito.vehiculo?.versionId ?? null
  const resultados = useQuery({
    queryKey: ['buscar', qDeb, versionId],
    queryFn: () => buscarProductos(qDeb, versionId),
    enabled: qDeb.length >= 2 || !!versionId,
    placeholderData: (prev) => prev,
  })
  const items = resultados.data?.items ?? []

  useEffect(() => setSel(0), [qDeb, versionId])
  useEffect(() => {
    if (selLinea > carrito.lineas.length - 1) setSelLinea(Math.max(0, carrito.lineas.length - 1))
  }, [carrito.lineas.length, selLinea])
  useEffect(() => buscador.current?.focus(), [])
  useEffect(() => {
    if (dialogo === null) buscador.current?.focus()
  }, [dialogo])

  const totales = useMemo(() => calcularCarrito(carrito.lineas, carrito.descuentoGlobalPct), [carrito.lineas, carrito.descuentoGlobalPct])
  const lineaSel = carrito.lineas[selLinea]

  function destello(tipo: 'ok' | 'error', texto: string) {
    setAviso((a) => ({ tipo, texto, n: (a?.n ?? 0) + 1 }))
    if (sonido) (tipo === 'ok' ? sonidoOk : sonidoError)()
  }

  function agregar(p: ItemProducto, cantidad = 1) {
    if (pendiente) return destello('error', 'Hay una venta pendiente de confirmar: resuélvala antes de continuar.')
    if (p.precio <= 0) return destello('error', `«${p.nombre}» no tiene precio vigente.`)
    carrito.agregar(p, cantidad)
    setSelLinea(Math.max(0, useCarrito.getState().lineas.length - 1))
    destello('ok', `Agregado: ${p.nombre}`)
  }

  // Escáner HID: ráfaga rápida + Enter, con el foco donde esté (si no hay un diálogo abierto)
  useEscaner(async (codigo) => {
    try {
      const p = await productoPorCodigo(codigo)
      if (!p) return destello('error', `Código no encontrado: ${codigo}`)
      if (!p.activo || !p.vendible_pos) return destello('error', `«${p.nombre}» no está disponible para la venta.`)
      agregar(
        {
          id: p.id,
          sku: p.sku,
          nombre: p.nombre,
          marca: null,
          precio: aNumero(p.precio),
          stock: aNumero(p.stock_disponible),
          ubicacion: p.ubicacion ?? null,
        },
        Math.max(1, aNumero(p.unidades_por_codigo)),
      )
    } catch (e) {
      destello('error', mensajeHumano(e))
    }
  }, dialogo === null)

  const hayLineas = carrito.lineas.length > 0
  function cobrar() {
    if (pendiente || hayLineas) setDialogo('cobro')
    else destello('error', 'Agregue al menos un producto para cobrar.')
  }

  useAtajos(
    {
      F2: () => buscador.current?.focus(),
      F3: () => listaCarrito.current?.focus(),
      F4: () => setDialogo('cliente'),
      F6: () => setDialogo('vehiculo'),
      F8: cobrar,
      F9: () => hayLineas && setDialogo('desc-global'),
      Escape: () => {
        if (q) setQ('')
        else if (hayLineas) setDialogo('cancelar')
      },
    },
    dialogo === null,
  )

  function alTeclaBuscador(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') (e.preventDefault(), setSel((s) => Math.min(items.length - 1, s + 1)))
    else if (e.key === 'ArrowUp') (e.preventDefault(), setSel((s) => Math.max(0, s - 1)))
    else if (e.key === 'Enter') {
      e.preventDefault()
      const p = items[sel]
      if (p)
        agregar({ id: p.id, sku: p.sku, nombre: p.nombre, marca: p.marca, precio: aNumero(p.precio), stock: aNumero(p.stock_disponible), ubicacion: p.ubicacion })
    }
  }

  function alTeclaCarrito(e: React.KeyboardEvent) {
    if (!lineaSel) return
    const id = lineaSel.producto.id
    if (e.key === 'ArrowDown') (e.preventDefault(), setSelLinea((s) => Math.min(carrito.lineas.length - 1, s + 1)))
    else if (e.key === 'ArrowUp') (e.preventDefault(), setSelLinea((s) => Math.max(0, s - 1)))
    else if (e.key === '+' || e.key === '=') (e.preventDefault(), carrito.fijarCantidad(id, lineaSel.cantidad + 1))
    else if (e.key === '-') (e.preventDefault(), lineaSel.cantidad > 1 && carrito.fijarCantidad(id, lineaSel.cantidad - 1))
    else if (e.key === 'Delete' || e.key === 'Backspace') (e.preventDefault(), carrito.quitar(id))
    else if (e.key.toLowerCase() === 'q') (e.preventDefault(), setDialogo('cantidad'))
    else if (e.key.toLowerCase() === 'd') (e.preventDefault(), setDialogo('desc-linea'))
    else if (e.key.toLowerCase() === 'p') (e.preventDefault(), setDialogo('precio'))
    else if (e.key === 'Escape') (e.stopPropagation(), buscador.current?.focus())
  }

  return (
    <main className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
      {/* ------------------------------------------------------------------ búsqueda */}
      <section className="flex min-h-0 flex-col gap-3" aria-label="Búsqueda de productos">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-6 -translate-y-1/2 text-suave" aria-hidden />
            <Input
              ref={buscador}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={alTeclaBuscador}
              placeholder="Buscar por nombre, referencia o código…  (F2)"
              className="h-14 pl-12 text-xl"
              aria-label="Buscar producto"
              role="combobox"
              aria-expanded={items.length > 0}
              aria-controls="resultados"
              data-testid="buscador"
            />
          </div>
          <Button onClick={() => setDialogo('vehiculo')} className={cn('h-14', carrito.vehiculo && 'border-acento')} data-testid="btn-vehiculo">
            <Car className="size-6" aria-hidden /> <span className="hidden xl:inline">Vehículo</span> <Kbd>F6</Kbd>
          </Button>
        </div>

        {carrito.vehiculo && (
          <div className="flex items-center gap-2 rounded-lg border-2 border-acento px-3 py-1.5" data-testid="chip-vehiculo">
            <Car className="size-5 text-acento" aria-hidden />
            <span className="flex-1 font-semibold">{carrito.vehiculo.etiqueta}</span>
            <Button variante="fantasma" tamano="icono" aria-label="Quitar filtro de vehículo" onClick={() => carrito.fijarVehiculo(null)}>
              <X className="size-5" />
            </Button>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-auto rounded-xl border-2 border-borde bg-superficie">
          {resultados.isFetching && items.length === 0 && <div className="p-4"><Cargando texto="Buscando…" /></div>}
          {resultados.isError && <div className="p-4"><Aviso tipo="error">{mensajeHumano(resultados.error)}</Aviso></div>}
          {!resultados.isError && items.length === 0 && !resultados.isFetching && (
            <div className="flex flex-col items-center gap-2 p-10 text-center text-suave">
              <PackageSearch className="size-12" aria-hidden />
              <p className="text-lg">{qDeb.length >= 2 || versionId ? 'Sin resultados.' : 'Escriba al menos 2 letras, o escanee un código de barras.'}</p>
            </div>
          )}
          <ul id="resultados" role="listbox" aria-label="Resultados" data-testid="resultados">
            {items.map((p, i) => {
              const stock = aNumero(p.stock_disponible)
              return (
                <li
                  key={p.id}
                  role="option"
                  aria-selected={i === sel}
                  data-testid="resultado"
                  onMouseEnter={() => setSel(i)}
                  onClick={() =>
                    agregar({ id: p.id, sku: p.sku, nombre: p.nombre, marca: p.marca, precio: aNumero(p.precio), stock, ubicacion: p.ubicacion })
                  }
                  className={cn(
                    'flex min-h-16 cursor-pointer items-center gap-3 border-b border-borde px-4 py-2',
                    i === sel && 'bg-superficie2 outline outline-2 -outline-offset-2 outline-acento',
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-lg font-semibold">{p.nombre}</p>
                    <p className="truncate text-sm text-suave">
                      {p.sku}
                      {p.marca && <> · {p.marca}</>}
                      {p.ubicacion && <> · Ubicación {p.ubicacion}</>}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-2xl font-bold num">{p.precio ? formatoCOP(p.precio) : 'Sin precio'}</p>
                    <p className={cn('text-sm font-semibold', stock <= 0 ? 'text-error' : 'text-ok')}>
                      {stock <= 0 ? 'Sin stock' : `${formatoCantidad(stock)} disp.`}
                    </p>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      </section>

      {/* ------------------------------------------------------------------ carrito */}
      <section
        key={aviso?.n}
        className={cn('flex min-h-0 flex-col gap-3 rounded-xl', aviso && (aviso.tipo === 'ok' ? 'destello-ok' : 'destello-error'))}
        aria-label="Carrito"
        data-testid="carrito"
        data-ultimo={aviso?.tipo}
      >
        {pendiente && (
          <Aviso tipo="aviso">
            <p className="font-semibold">Hay una venta pendiente de confirmar.</p>
            <Button className="mt-2" variante="primario" onClick={() => setDialogo('cobro')}>Resolver ahora</Button>
          </Aviso>
        )}
        <div className="flex gap-2">
          <Button onClick={() => setDialogo('cliente')} className="h-12 min-w-0 flex-1 justify-start" data-testid="btn-cliente">
            <User className="size-5 shrink-0" aria-hidden />
            <span className="truncate" data-testid="cliente-chip">{carrito.cliente ? carrito.cliente.nombre_completo : 'Consumidor final'}</span>
            <Kbd>F4</Kbd>
          </Button>
        </div>

        <div
          className="min-h-0 flex-1 overflow-auto rounded-xl border-2 border-borde bg-superficie"
          aria-live="polite"
        >
          {!hayLineas && <p className="p-8 text-center text-lg text-suave">El carrito está vacío.</p>}
          <ul
            ref={listaCarrito}
            tabIndex={0}
            role="listbox"
            aria-label="Líneas del carrito"
            onKeyDown={alTeclaCarrito}
            className="focus-visible:outline-acento"
            data-testid="lineas"
          >
            {carrito.lineas.map((l, i) => {
              const c = calcularLinea(l, carrito.descuentoGlobalPct)
              return (
                <li
                  key={l.producto.id}
                  role="option"
                  aria-selected={i === selLinea}
                  data-testid="linea"
                  onClick={() => setSelLinea(i)}
                  className={cn('flex flex-col gap-1 border-b border-borde px-3 py-2', i === selLinea && 'bg-superficie2 outline outline-2 -outline-offset-2 outline-acento')}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-semibold leading-tight">{l.producto.nombre}</p>
                    <Button variante="fantasma" tamano="icono" aria-label={`Quitar ${l.producto.nombre}`} onClick={() => carrito.quitar(l.producto.id)}>
                      <Trash2 className="size-5" />
                    </Button>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1">
                      <Button tamano="icono" aria-label="Menos" onClick={() => l.cantidad > 1 && carrito.fijarCantidad(l.producto.id, l.cantidad - 1)}><Minus className="size-5" /></Button>
                      <span className="w-12 text-center text-xl font-bold num" data-testid="cantidad">{formatoCantidad(l.cantidad)}</span>
                      <Button tamano="icono" aria-label="Más" onClick={() => carrito.fijarCantidad(l.producto.id, l.cantidad + 1)}><Plus className="size-5" /></Button>
                      <span className="ml-2 text-sm text-suave num">× {formatoCOP(l.precio)}{l.precioManual != null && ' (manual)'}</span>
                    </div>
                    <div className="text-right">
                      {c.descuento > 0 && <p className="text-sm text-ok num">-{formatoCOP(c.descuento)}{l.descuentoPct > 0 && ` (${l.descuentoPct}%)`}</p>}
                      <p className="text-2xl font-bold num">{formatoCOP(c.total)}</p>
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>

        {hayLineas && (
          <div className="flex flex-wrap gap-2 text-sm">
            <Button onClick={() => setDialogo('cantidad')} disabled={!lineaSel}>Cantidad <Kbd>Q</Kbd></Button>
            <Button onClick={() => setDialogo('desc-linea')} disabled={!lineaSel} data-testid="btn-desc-linea">Descuento línea <Kbd>D</Kbd></Button>
            <Button onClick={() => setDialogo('desc-global')} data-testid="btn-desc-global">Descuento total <Kbd>F9</Kbd></Button>
            <Button onClick={() => setDialogo('precio')} disabled={!lineaSel} title={puedeCambiarPrecio ? undefined : 'Pedirá autorización de un supervisor'}>Precio <Kbd>P</Kbd></Button>
          </div>
        )}

        <div className="rounded-xl border-2 border-borde bg-superficie p-4">
          <div className="flex items-baseline justify-between text-suave">
            <span>Subtotal</span><span className="num">{formatoCOP(totales.bruto)}</span>
          </div>
          {totales.descuento > 0 && (
            <div className="flex items-baseline justify-between text-ok">
              <span>Descuentos{carrito.descuentoGlobalPct > 0 && ` (total ${carrito.descuentoGlobalPct}%)`}</span><span className="num">-{formatoCOP(totales.descuento)}</span>
            </div>
          )}
          <div className="mt-1 flex items-baseline justify-between">
            <span className="text-xl font-semibold">TOTAL</span>
            <span className="text-5xl font-extrabold num" data-testid="total">{formatoCOP(totales.total)}</span>
          </div>
          <p className="mt-1 text-xs text-suave">Estimado: el servidor calcula el total definitivo al cobrar.</p>
        </div>

        <Button variante="ok" tamano="grande" className="h-16 text-2xl" onClick={cobrar} disabled={!hayLineas && !pendiente} data-testid="btn-cobrar">
          Cobrar <Kbd>F8</Kbd>
        </Button>
      </section>

      {/* ------------------------------------------------------------------ atajos */}
      <footer className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-suave lg:col-span-2" aria-label="Atajos de teclado">
        <span><Kbd>F2</Kbd> Buscar</span>
        <span><Kbd>F3</Kbd> Carrito (↑↓ + − Supr)</span>
        <span><Kbd>F4</Kbd> Cliente</span>
        <span><Kbd>F6</Kbd> Vehículo</span>
        <span><Kbd>F8</Kbd> Cobrar</span>
        <span><Kbd>F9</Kbd> Descuento total</span>
        <span><Kbd>Esc</Kbd> Limpiar / cancelar</span>
      </footer>

      {aviso && (
        <div
          key={`aviso-${aviso.n}`}
          role={aviso.tipo === 'error' ? 'alert' : 'status'}
          data-testid={aviso.tipo === 'error' ? 'aviso-error' : 'aviso-ok'}
          className={cn(
            'pointer-events-none fixed bottom-14 left-1/2 z-30 -translate-x-1/2 rounded-xl border-2 bg-superficie px-5 py-3 text-lg font-bold shadow-xl',
            aviso.tipo === 'ok' ? 'border-ok' : 'border-error text-error',
          )}
        >
          {aviso.texto}
        </div>
      )}

      {/* ------------------------------------------------------------------ diálogos */}
      <Cobro abierto={dialogo === 'cobro'} onCerrar={() => setDialogo(null)} />
      <ClienteDialog abierto={dialogo === 'cliente'} onCerrar={() => setDialogo(null)} />
      <VehiculoDialog abierto={dialogo === 'vehiculo'} onCerrar={() => setDialogo(null)} />
      <NumeroDialog
        abierto={dialogo === 'cantidad'}
        titulo="Cantidad"
        etiqueta="Cantidad"
        valorInicial={lineaSel?.cantidad ?? 1}
        decimales
        onCerrar={() => setDialogo(null)}
        onAceptar={(n) => (lineaSel && n > 0 && carrito.fijarCantidad(lineaSel.producto.id, n), setDialogo(null))}
      />
      <NumeroDialog
        abierto={dialogo === 'desc-linea'}
        titulo="Descuento de la línea"
        etiqueta="Porcentaje de descuento"
        sufijo="%"
        maximo={100}
        decimales
        valorInicial={lineaSel?.descuentoPct ?? 0}
        onCerrar={() => setDialogo(null)}
        onAceptar={(n) => (lineaSel && carrito.fijarDescuentoLinea(lineaSel.producto.id, n), setDialogo(null))}
      />
      <NumeroDialog
        abierto={dialogo === 'desc-global'}
        titulo="Descuento sobre el total"
        etiqueta="Porcentaje de descuento"
        sufijo="%"
        maximo={100}
        decimales
        valorInicial={carrito.descuentoGlobalPct}
        onCerrar={() => setDialogo(null)}
        onAceptar={(n) => (carrito.fijarDescuentoGlobal(n), setDialogo(null))}
      />
      <NumeroDialog
        abierto={dialogo === 'precio'}
        titulo="Cambiar precio"
        etiqueta="Precio unitario (IVA incluido)"
        valorInicial={lineaSel?.precio ?? 0}
        onCerrar={() => setDialogo(null)}
        onAceptar={(n) => (lineaSel && n > 0 && carrito.fijarPrecioManual(lineaSel.producto.id, n === lineaSel.producto.precio ? null : n), setDialogo(null))}
      />
      <Modal abierto={dialogo === 'cancelar'} onCerrar={() => setDialogo(null)} titulo="¿Cancelar la venta?" descripcion="Se vaciará el carrito." ancho="sm">
        <div className="flex justify-end gap-3">
          <Button onClick={() => setDialogo(null)}>Seguir vendiendo</Button>
          <Button
            variante="peligro"
            autoFocus
            onClick={() => {
              carrito.vaciar()
              useIntentoVenta.getState().reiniciar()
              setDialogo(null)
            }}
            data-testid="cancelar-venta"
          >
            Cancelar venta <Kbd>Enter</Kbd>
          </Button>
        </div>
      </Modal>
    </main>
  )
}
