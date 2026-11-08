import type { ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { BarraEstado } from '@/components/BarraEstado'
import { CajonSimulado, VistaPreviaModal } from '@/components/VistaTirilla'
import { Ajustes } from '@/features/Ajustes'
import { AperturaTurno } from '@/features/AperturaTurno'
import { Configuracion } from '@/features/Configuracion'
import { Pin } from '@/features/Pin'
import { Venta } from '@/features/Venta'
import { useInactividad } from '@/hooks'
import { estaConfigurado, useConfig } from '@/stores/config'
import { useSesion } from '@/stores/sesion'

type Ruta = 'config' | 'pin' | 'turno' | 'venta' | 'ajustes'

export function App() {
  const configurado = useConfig(estaConfigurado)
  const inactividadMin = useConfig((s) => s.inactividadMin)
  const sesion = useSesion((s) => s.sesion)
  const turno = useSesion((s) => s.turno)

  useInactividad(inactividadMin, !!sesion)

  /** Reglas de acceso: sin configurar → /config; sin sesión → /pin; sin turno → /turno (ajustes sí se permite). */
  const guardia = (ruta: Ruta, el: ReactElement): ReactElement => {
    if (ruta === 'config') return el
    if (!configurado) return <Navigate to="/config" replace />
    if (ruta === 'pin') return sesion ? <Navigate to="/" replace /> : el
    if (!sesion) return <Navigate to="/pin" replace />
    if (ruta === 'turno') return turno ? <Navigate to="/venta" replace /> : el
    if (ruta === 'venta' && !turno) return <Navigate to="/turno" replace />
    return el
  }
  const inicio = !configurado ? '/config' : !sesion ? '/pin' : !turno ? '/turno' : '/venta'

  return (
    <div className="flex h-full flex-col">
      {configurado && <BarraEstado />}
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">
        <Routes>
          <Route path="/" element={<Navigate to={inicio} replace />} />
          <Route path="/config" element={guardia('config', <Configuracion />)} />
          <Route path="/pin" element={guardia('pin', <Pin />)} />
          <Route path="/turno" element={guardia('turno', <AperturaTurno />)} />
          <Route path="/venta" element={guardia('venta', <Venta />)} />
          <Route path="/ajustes" element={guardia('ajustes', <Ajustes />)} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
      <VistaPreviaModal />
      <CajonSimulado />
    </div>
  )
}
