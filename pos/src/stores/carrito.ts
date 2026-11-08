import { create } from 'zustand'
import type { Tercero } from '@/api/pos'
import { calcularCarrito, type LineaCalculable } from '@/lib/dinero'

export interface ItemProducto {
  id: string
  sku: string
  nombre: string
  marca: string | null
  precio: number
  stock: number
  ubicacion?: string | null
}

export interface LineaCarrito extends LineaCalculable {
  producto: ItemProducto
  /** Precio fijado a mano (exige permiso o autorización del supervisor). */
  precioManual: number | null
}

export interface VehiculoElegido {
  versionId: string
  etiqueta: string
}

interface Estado {
  lineas: LineaCarrito[]
  descuentoGlobalPct: number
  cliente: Tercero | null
  vehiculo: VehiculoElegido | null
  agregar: (p: ItemProducto, cantidad?: number) => void
  fijarCantidad: (productoId: string, cantidad: number) => void
  quitar: (productoId: string) => void
  fijarDescuentoLinea: (productoId: string, pct: number) => void
  fijarPrecioManual: (productoId: string, precio: number | null) => void
  fijarDescuentoGlobal: (pct: number) => void
  fijarCliente: (c: Tercero | null) => void
  fijarVehiculo: (v: VehiculoElegido | null) => void
  vaciar: () => void
}

export const useCarrito = create<Estado>((set) => ({
  lineas: [],
  descuentoGlobalPct: 0,
  cliente: null,
  vehiculo: null,

  agregar: (p, cantidad = 1) =>
    set((s) => {
      const i = s.lineas.findIndex((l) => l.producto.id === p.id)
      if (i >= 0) {
        const lineas = s.lineas.slice()
        lineas[i] = { ...lineas[i], cantidad: lineas[i].cantidad + cantidad }
        return { lineas }
      }
      return { lineas: [...s.lineas, { producto: p, cantidad, precio: p.precio, descuentoPct: 0, precioManual: null }] }
    }),

  fijarCantidad: (id, cantidad) =>
    set((s) => ({
      lineas: s.lineas.map((l) => (l.producto.id === id ? { ...l, cantidad: Math.max(0.001, cantidad) } : l)),
    })),

  quitar: (id) => set((s) => ({ lineas: s.lineas.filter((l) => l.producto.id !== id) })),

  fijarDescuentoLinea: (id, pct) =>
    set((s) => ({
      lineas: s.lineas.map((l) =>
        l.producto.id === id ? { ...l, descuentoPct: Math.min(100, Math.max(0, pct)) } : l,
      ),
    })),

  fijarPrecioManual: (id, precio) =>
    set((s) => ({
      lineas: s.lineas.map((l) =>
        l.producto.id === id ? { ...l, precioManual: precio, precio: precio ?? l.producto.precio } : l,
      ),
    })),

  fijarDescuentoGlobal: (pct) => set({ descuentoGlobalPct: Math.min(100, Math.max(0, pct)) }),
  fijarCliente: (cliente) => set({ cliente }),
  fijarVehiculo: (vehiculo) => set({ vehiculo }),
  vaciar: () => set({ lineas: [], descuentoGlobalPct: 0, cliente: null, vehiculo: null }),
}))

export const totalesCarrito = (lineas: LineaCarrito[], descuentoGlobalPct: number) =>
  calcularCarrito(lineas, descuentoGlobalPct)
