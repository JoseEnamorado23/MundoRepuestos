// Diálogos pequeños de la pantalla de venta: número (cantidad, descuento, precio), cliente y vehículo.
import { useMutation, useQuery } from '@tanstack/react-query'
import { Search, UserPlus } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import {
  aniosDeModelo,
  buscarTerceros,
  crearTercero,
  marcasVehiculo,
  modelosDeMarca,
  versionesDe,
  type Tercero,
} from '@/api/pos'
import { Aviso, Button, Campo, Cargando, Input, Kbd, Modal, Select } from '@/components/ui'
import { mensajeHumano } from '@/lib/errores'
import { useCarrito, type VehiculoElegido } from '@/stores/carrito'

// ------------------------------------------------------------------------------------------------ número
export function NumeroDialog({
  abierto,
  titulo,
  etiqueta,
  valorInicial,
  sufijo,
  maximo,
  decimales,
  onAceptar,
  onCerrar,
}: {
  abierto: boolean
  titulo: string
  etiqueta: string
  valorInicial: number
  sufijo?: string
  maximo?: number
  decimales?: boolean
  onAceptar: (n: number) => void
  onCerrar: () => void
}) {
  const [txt, setTxt] = useState('')
  useEffect(() => {
    if (abierto) setTxt(String(valorInicial))
  }, [abierto, valorInicial])
  function enviar(e: FormEvent) {
    e.preventDefault()
    const n = Number(txt.replace(',', '.'))
    if (!Number.isFinite(n) || n < 0 || (maximo !== undefined && n > maximo)) return
    onAceptar(n)
  }
  return (
    <Modal abierto={abierto} onCerrar={onCerrar} titulo={titulo} ancho="sm">
      <form onSubmit={enviar} className="flex flex-col gap-4">
        <Campo etiqueta={etiqueta + (maximo !== undefined ? ` (máx. ${maximo}${sufijo ?? ''})` : '')}>
          <div className="flex items-center gap-2">
            <Input
              autoFocus
              onFocus={(e) => e.currentTarget.select()}
              inputMode={decimales ? 'decimal' : 'numeric'}
              value={txt}
              onChange={(e) => setTxt(e.target.value.replace(decimales ? /[^\d.,]/g : /\D/g, ''))}
              className="text-right text-3xl font-bold num"
              aria-label={etiqueta}
              data-testid="numero-valor"
            />
            {sufijo && <span className="text-2xl font-bold">{sufijo}</span>}
          </div>
        </Campo>
        <div className="flex justify-end gap-3">
          <Button onClick={onCerrar}>
            Cancelar <Kbd>Esc</Kbd>
          </Button>
          <Button type="submit" variante="primario" data-testid="numero-aceptar">
            Aceptar <Kbd>Enter</Kbd>
          </Button>
        </div>
      </form>
    </Modal>
  )
}

// ------------------------------------------------------------------------------------------------ cliente
const TIPOS_DOC = [
  { codigo: '13', nombre: 'Cédula de ciudadanía' },
  { codigo: '31', nombre: 'NIT' },
  { codigo: '22', nombre: 'Cédula de extranjería' },
  { codigo: '41', nombre: 'Pasaporte' },
]

export function ClienteDialog({ abierto, onCerrar }: { abierto: boolean; onCerrar: () => void }) {
  const { cliente, fijarCliente } = useCarrito()
  const [doc, setDoc] = useState('')
  const [crear, setCrear] = useState(false)
  const [resultados, setResultados] = useState<Tercero[] | null>(null)

  useEffect(() => {
    if (abierto) {
      setDoc('')
      setCrear(false)
      setResultados(null)
    }
  }, [abierto])

  const buscar = useMutation({
    mutationFn: () => buscarTerceros(doc.trim()),
    onSuccess: (r) => setResultados(r),
  })

  function elegir(t: Tercero | null) {
    fijarCliente(t && !t.es_consumidor_final ? t : null)
    onCerrar()
  }

  return (
    <Modal abierto={abierto} onCerrar={onCerrar} titulo="Cliente" descripcion="Por defecto la venta es a consumidor final." ancho="md">
      {crear ? (
        <NuevoCliente documentoInicial={doc} onCreado={elegir} onVolver={() => setCrear(false)} />
      ) : (
        <div className="flex flex-col gap-4" data-testid="dialogo-cliente">
          <div className="rounded-lg border-2 border-borde p-3">
            <p className="text-sm text-suave">Cliente actual</p>
            <p className="text-xl font-bold" data-testid="cliente-actual">{cliente ? `${cliente.nombre_completo} · ${cliente.numero_documento}` : 'Consumidor final'}</p>
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (doc.trim()) buscar.mutate()
            }}
          >
            <Input autoFocus value={doc} onChange={(e) => setDoc(e.target.value)} placeholder="Número de documento" inputMode="numeric" aria-label="Número de documento" data-testid="cliente-doc" />
            <Button type="submit" variante="primario" disabled={!doc.trim() || buscar.isPending} data-testid="cliente-buscar">
              <Search className="size-5" aria-hidden /> Buscar
            </Button>
          </form>
          {buscar.isPending && <Cargando />}
          {buscar.isError && <Aviso tipo="error">{mensajeHumano(buscar.error)}</Aviso>}
          {resultados && resultados.length === 0 && (
            <Aviso tipo="info">No hay un cliente con ese documento. Puede crearlo con los datos mínimos para facturar.</Aviso>
          )}
          {resultados && resultados.length > 0 && (
            <ul className="flex flex-col gap-2">
              {resultados.map((t) => (
                <li key={t.id}>
                  <Button className="w-full justify-between" onClick={() => elegir(t)} data-testid="cliente-resultado">
                    <span>{t.nombre_completo}</span>
                    <span className="text-suave num">{t.numero_documento}</span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap justify-between gap-3">
            <Button variante="secundario" onClick={() => setCrear(true)} data-testid="cliente-nuevo">
              <UserPlus className="size-5" aria-hidden /> Crear cliente
            </Button>
            <Button onClick={() => elegir(null)} data-testid="cliente-consumidor">Consumidor final</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function NuevoCliente({ documentoInicial, onCreado, onVolver }: { documentoInicial: string; onCreado: (t: Tercero) => void; onVolver: () => void }) {
  const [tipo, setTipo] = useState('13')
  const [numero, setNumero] = useState(documentoInicial)
  const [razon, setRazon] = useState('')
  const [nombre1, setNombre1] = useState('')
  const [apellido1, setApellido1] = useState('')
  const [email, setEmail] = useState('')
  const [telefono, setTelefono] = useState('')
  const juridica = tipo === '31'
  const m = useMutation({
    mutationFn: () =>
      crearTercero({
        tipo_documento_codigo: tipo,
        numero_documento: numero.trim(),
        ...(juridica ? { razon_social: razon.trim() } : { primer_nombre: nombre1.trim(), primer_apellido: apellido1.trim() }),
        email_facturacion: email.trim() || null,
        telefono: telefono.trim() || null,
      }),
    onSuccess: onCreado,
  })
  const valido = numero.trim().length >= 3 && (juridica ? razon.trim().length >= 2 : nombre1.trim() && apellido1.trim())
  return (
    <form
      className="flex flex-col gap-3"
      data-testid="cliente-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (valido && !m.isPending) m.mutate()
      }}
    >
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Tipo de documento">
          <Select value={tipo} onChange={(e) => setTipo(e.target.value)} aria-label="Tipo de documento">
            {TIPOS_DOC.map((t) => (
              <option key={t.codigo} value={t.codigo}>{t.nombre}</option>
            ))}
          </Select>
        </Campo>
        <Campo etiqueta="Número">
          <Input autoFocus value={numero} onChange={(e) => setNumero(e.target.value)} inputMode="numeric" aria-label="Número de documento" />
        </Campo>
      </div>
      {juridica ? (
        <Campo etiqueta="Razón social">
          <Input value={razon} onChange={(e) => setRazon(e.target.value)} aria-label="Razón social" />
        </Campo>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <Campo etiqueta="Primer nombre"><Input value={nombre1} onChange={(e) => setNombre1(e.target.value)} aria-label="Primer nombre" /></Campo>
          <Campo etiqueta="Primer apellido"><Input value={apellido1} onChange={(e) => setApellido1(e.target.value)} aria-label="Primer apellido" /></Campo>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Correo (para enviar la factura)"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Correo" /></Campo>
        <Campo etiqueta="Teléfono"><Input value={telefono} onChange={(e) => setTelefono(e.target.value)} inputMode="tel" aria-label="Teléfono" /></Campo>
      </div>
      {m.isError && <Aviso tipo="error">{mensajeHumano(m.error)}</Aviso>}
      <div className="flex justify-end gap-3">
        <Button onClick={onVolver}>Volver</Button>
        <Button type="submit" variante="primario" disabled={!valido || m.isPending} data-testid="cliente-guardar">
          Guardar y usar
        </Button>
      </div>
    </form>
  )
}

// ------------------------------------------------------------------------------------------------ vehículo
export function VehiculoDialog({ abierto, onCerrar }: { abierto: boolean; onCerrar: () => void }) {
  const { vehiculo, fijarVehiculo } = useCarrito()
  const [marca, setMarca] = useState('')
  const [modelo, setModelo] = useState('')
  const [anio, setAnio] = useState('')
  const [version, setVersion] = useState('')

  useEffect(() => {
    if (abierto) setMarca(''), setModelo(''), setAnio(''), setVersion('')
  }, [abierto])

  const marcas = useQuery({ queryKey: ['veh-marcas'], queryFn: marcasVehiculo, enabled: abierto, staleTime: 300_000 })
  const modelos = useQuery({ queryKey: ['veh-modelos', marca], queryFn: () => modelosDeMarca(marca), enabled: !!marca, staleTime: 300_000 })
  const anios = useQuery({ queryKey: ['veh-anios', modelo], queryFn: () => aniosDeModelo(modelo), enabled: !!modelo, staleTime: 300_000 })
  const versiones = useQuery({ queryKey: ['veh-versiones', modelo, anio], queryFn: () => versionesDe(modelo, Number(anio)), enabled: !!modelo && !!anio, staleTime: 300_000 })

  const nombre = (lista: { id: string; nombre: string }[] | undefined, id: string) => lista?.find((x) => x.id === id)?.nombre ?? ''

  function aplicar() {
    if (!version) return
    const v: VehiculoElegido = {
      versionId: version,
      etiqueta: `${nombre(marcas.data?.items, marca)} ${nombre(modelos.data, modelo)} ${anio} ${nombre(versiones.data?.items, version)}`.trim(),
    }
    fijarVehiculo(v)
    onCerrar()
  }

  return (
    <Modal abierto={abierto} onCerrar={onCerrar} titulo="Vehículo" descripcion="Filtra la búsqueda a los repuestos compatibles." ancho="md">
      <form
        className="flex flex-col gap-4"
        data-testid="dialogo-vehiculo"
        onSubmit={(e) => {
          e.preventDefault()
          aplicar()
        }}
      >
        {vehiculo && <Aviso tipo="info">Filtro actual: <strong>{vehiculo.etiqueta}</strong></Aviso>}
        {marcas.isError && <Aviso tipo="error">{mensajeHumano(marcas.error)}</Aviso>}
        <Campo etiqueta="Marca">
          <Select autoFocus value={marca} onChange={(e) => (setMarca(e.target.value), setModelo(''), setAnio(''), setVersion(''))} aria-label="Marca" data-testid="veh-marca">
            <option value="">Seleccione…</option>
            {marcas.data?.items.map((m) => <option key={m.id} value={m.id}>{m.nombre}</option>)}
          </Select>
        </Campo>
        <Campo etiqueta="Modelo">
          <Select value={modelo} disabled={!marca} onChange={(e) => (setModelo(e.target.value), setAnio(''), setVersion(''))} aria-label="Modelo" data-testid="veh-modelo">
            <option value="">Seleccione…</option>
            {modelos.data?.map((m) => <option key={m.id} value={m.id}>{m.nombre}</option>)}
          </Select>
        </Campo>
        <Campo etiqueta="Año">
          <Select value={anio} disabled={!modelo} onChange={(e) => (setAnio(e.target.value), setVersion(''))} aria-label="Año" data-testid="veh-anio">
            <option value="">Seleccione…</option>
            {anios.data?.anios.map((a) => <option key={a} value={a}>{a}</option>)}
          </Select>
        </Campo>
        <Campo etiqueta="Versión">
          <Select value={version} disabled={!anio} onChange={(e) => setVersion(e.target.value)} aria-label="Versión" data-testid="veh-version">
            <option value="">Seleccione…</option>
            {versiones.data?.items.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
          </Select>
        </Campo>
        <div className="flex flex-wrap justify-between gap-3">
          <Button onClick={() => (fijarVehiculo(null), onCerrar())} disabled={!vehiculo} data-testid="veh-quitar">Quitar filtro</Button>
          <Button type="submit" variante="primario" disabled={!version} data-testid="veh-aplicar">Aplicar filtro</Button>
        </div>
      </form>
    </Modal>
  )
}
