// Con el backend ya arriba: registra el dispositivo POS de la «Caja 1» del demo y guarda su token para las pruebas.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const aqui = dirname(fileURLToPath(import.meta.url))

export default async function globalSetup() {
  const est = JSON.parse(readFileSync(resolve(aqui, '.estado-backend.json'), 'utf8'))
  const api = `${est.apiUrl}/api/v1`
  const login = await fetch(`${api}/auth/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ usuario: est.admin.usuario, password: est.admin.clave }),
  })
  if (!login.ok) throw new Error(`Login del admin: ${login.status} ${await login.text()}`)
  const { access_token } = await login.json()
  const disp = await fetch(`${api}/cajas/dispositivos`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${access_token}` },
    body: JSON.stringify({ caja_id: est.cajaId, nombre: 'POS E2E' }),
  })
  if (!disp.ok) throw new Error(`Registrar dispositivo: ${disp.status} ${await disp.text()}`)
  const { token } = await disp.json()
  writeFileSync(resolve(aqui, '.estado.json'), JSON.stringify({ ...est, tokenDispositivo: token, adminToken: access_token }, null, 2))
}
