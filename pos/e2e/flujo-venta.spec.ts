import { expect, test, type Page } from '@playwright/test'
import { mkdirSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const aqui = dirname(fileURLToPath(import.meta.url))
const estado = () => JSON.parse(readFileSync(resolve(aqui, '.estado.json'), 'utf8')) as {
  apiUrl: string
  tokenDispositivo: string
  adminToken: string
}
const CAPTURAS = resolve(aqui, 'capturas')
mkdirSync(CAPTURAS, { recursive: true })
const foto = (page: Page, nombre: string) => page.screenshot({ path: resolve(CAPTURAS, `${nombre}.png`), fullPage: false })

const PIN_CAJERO = '123456' // cajero demo (tope de descuento 5 %)
const PIN_SUPERVISOR = '246810' // propietario demo: puede autorizar descuentos mayores

/** Un teclado humano: pausa larga entre teclas, para que no se confunda con un escáner. */
const humano = (page: Page, texto: string) => page.keyboard.type(texto, { delay: 120 })
/** Un lector HID: ráfaga rápida terminada en Enter. */
const escanear = (page: Page, codigo: string) => page.keyboard.type(codigo + '\n', { delay: 2 })

const numero = (txt: string | null) => Number((txt ?? '').replace(/\D/g, ''))

async function configurar(page: Page) {
  const e = estado()
  await page.goto('/')
  await expect(page).toHaveURL(/#\/config/)
  await page.getByTestId('cfg-url').fill(e.apiUrl)
  await page.getByTestId('cfg-probar').click()
  await expect(page.getByTestId('cfg-resultado')).toContainText('Conectado')
  await page.getByTestId('cfg-token').fill(e.tokenDispositivo)
  await foto(page, '01-configuracion')
  await page.getByTestId('cfg-guardar').click()
  await expect(page).toHaveURL(/#\/pin/)
}

async function entrar(page: Page, pin = PIN_CAJERO) {
  await page.getByTestId('pin-puntos').waitFor()
  await humano(page, pin)
  await page.keyboard.press('Enter')
}

async function abrirTurno(page: Page, base = '50000') {
  await expect(page.getByTestId('turno-base')).toBeVisible()
  await foto(page, '03-apertura-turno')
  await humano(page, base)
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('buscador')).toBeVisible()
}

test.describe.configure({ mode: 'serial' })

// Playwright espera el procesamiento de CADA tecla (30-50 ms en modo desarrollo), a diferencia de un lector real, cuyas
// teclas llegan con marcas de tiempo de hardware (1-5 ms). Para el E2E se sube el umbral (preferencia configurable) a
// 80 ms; el tecleo humano de las pruebas va a 120 ms, así que sigue sin confundirse con un escaneo.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem('mr.config')) localStorage.setItem('mr.config', JSON.stringify({ umbralEscanerMs: 80 }))
  })
})

test('PIN → turno → búsqueda → escáner → descuento con autorización → cobro mixto → FE aceptada → vista previa con CUFE', async ({ page }) => {
  const e = estado()
  await configurar(page)

  // ------------------------------------------------------------------ PIN
  await expect(page.getByTestId('estado-conexion')).toContainText('conectado')
  await foto(page, '02-pin')
  await entrar(page)
  await abrirTurno(page)

  // ------------------------------------------------------------------ búsqueda
  await page.getByTestId('buscador').click()
  await humano(page, 'pastillas spark')
  await expect(page.getByTestId('resultado').first()).toBeVisible()
  const primero = page.getByTestId('resultado').first()
  await expect(primero).toContainText('$') // precio
  await expect(primero).toContainText('disp.') // stock
  await foto(page, '04-venta-busqueda')
  await page.keyboard.press('Enter') // agrega el seleccionado con el teclado
  await expect(page.getByTestId('linea')).toHaveCount(1)

  // ------------------------------------------------------------------ escáner (foco FUERA del buscador)
  const r = await fetch(`${e.apiUrl}/api/v1/catalogo/productos/buscar?q=filtro&limit=50`, {
    headers: { authorization: `Bearer ${e.adminToken}` },
  })
  const lista = (await r.json()).items as { codigo_barras: string | null; nombre: string }[]
  const conEan = lista.find((p) => p.codigo_barras)
  expect(conEan, 'el demo trae productos con EAN-13').toBeTruthy()
  await page.keyboard.press('F3') // foco en el carrito, no en el buscador
  await escanear(page, conEan!.codigo_barras!)
  await expect(page.getByTestId('linea')).toHaveCount(2)
  await expect(page.getByTestId('carrito')).toHaveAttribute('data-ultimo', 'ok')
  // con el foco DENTRO del buscador: el lector también funciona y sus caracteres no quedan escritos en el campo
  await page.keyboard.press('F2')
  await escanear(page, conEan!.codigo_barras!)
  await expect(page.getByTestId('buscador')).toHaveValue('pastillas spark')
  await expect(page.getByTestId('cantidad').nth(1)).toHaveText('2')

  // código inexistente: aviso, sin agregar
  await escanear(page, '9999999999999')
  await expect(page.getByTestId('aviso-error')).toContainText('Código no encontrado')
  await expect(page.getByTestId('linea')).toHaveCount(2)

  // ------------------------------------------------------------------ descuento que exige autorización (tope del cajero: 5 %)
  await page.keyboard.press('F9')
  await page.getByTestId('numero-valor').fill('20')
  await page.getByTestId('numero-aceptar').click()
  await foto(page, '05-venta-carrito')

  // ------------------------------------------------------------------ cobro mixto: tarjeta + efectivo
  await page.keyboard.press('F8')
  await expect(page.getByTestId('cobro')).toBeVisible()
  const total = numero(await page.getByTestId('cobro-total').textContent())
  expect(total).toBeGreaterThan(20000)

  await page.getByTestId('medio-48').click()
  await page.getByTestId('cobro-valor').fill('10000')
  await page.getByTestId('cobro-ref').fill('AP123456')
  await page.getByTestId('cobro-agregar').click()
  await expect(page.getByTestId('cobro-pagos')).toContainText('AP123456')

  await page.getByTestId('medio-10').click()
  const faltante = total - 10000
  const billete = Math.ceil(faltante / 50000) * 50000
  await page.getByTestId('cobro-valor').fill(String(billete))
  await page.getByTestId('cobro-agregar').click()
  await expect(page.getByTestId('cobro-redondeo')).toHaveCount(0) // mixto ⇒ sin redondeo
  expect(numero(await page.getByTestId('cobro-cambio').textContent())).toBe(billete - faltante)
  await foto(page, '06-cobro-mixto')

  await page.getByTestId('cobro-confirmar').click()

  // ------------------------------------------------------------------ autorización por PIN de supervisor
  await expect(page.getByTestId('modal-autorizacion')).toBeVisible()
  await foto(page, '07-autorizacion')
  await page.getByTestId('aut-pin').fill(PIN_SUPERVISOR)
  await page.getByTestId('aut-confirmar').click()

  // ------------------------------------------------------------------ FE aceptada + vista previa con CUFE
  await expect(page.getByTestId('cajon-abierto')).toBeVisible({ timeout: 30_000 }) // hubo efectivo ⇒ cajón (simulado)
  await expect(page.getByTestId('tirilla')).toBeVisible({ timeout: 30_000 })
  const texto = ((await page.getByTestId('tirilla').textContent()) ?? '').replace(/\s+/g, '')
  expect(texto).toContain('FACTURAELECTRÓNICADEVENTA')
  expect(texto).toMatch(/CUFE:[0-9a-zA-Z]{20,}/)
  expect(texto).not.toContain('PROVISIONAL')
  await expect(page.locator('svg[aria-label^="Código de barras"]')).toBeVisible() // Code128 del numero_interno
  await foto(page, '08-vista-previa-fe')
  await page.getByRole('button', { name: /Cerrar/ }).first().click()

  await expect(page.getByTestId('venta-lista')).toBeVisible()
  await expect(page.getByTestId('fiscal-resultado')).toContainText('aceptada')
  await foto(page, '09-venta-registrada')
  await page.getByTestId('nueva-venta').click()
  await expect(page.getByTestId('linea')).toHaveCount(0)
})

test('si la respuesta se pierde, el reintento usa el MISMO id y no duplica la venta', async ({ page }) => {
  const e = estado()
  await configurar(page)
  await entrar(page)
  // el turno del test anterior sigue abierto (misma BD): se entra directo a vender
  await expect(page.getByTestId('buscador')).toBeVisible()

  await page.getByTestId('buscador').click()
  await humano(page, 'bombillo')
  await expect(page.getByTestId('resultado').first()).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('linea')).toHaveCount(1)

  const ids: string[] = []
  let primera = true
  await page.route('**/api/v1/pos/ventas', async (ruta) => {
    if (ruta.request().method() !== 'POST') return ruta.continue()
    ids.push(JSON.parse(ruta.request().postData() ?? '{}').id)
    if (primera) {
      primera = false
      await ruta.fetch() // la petición LLEGA al servidor y se registra…
      return ruta.abort('connectionreset') // …pero el cliente nunca ve la respuesta
    }
    return ruta.continue()
  })

  await page.keyboard.press('F8')
  await page.getByTestId('cobro-valor').fill('100000')
  await page.keyboard.press('Enter')
  await page.getByTestId('cobro-confirmar').click()
  await expect(page.getByTestId('venta-lista')).toBeVisible({ timeout: 45_000 })

  expect(ids.length).toBeGreaterThanOrEqual(2)
  expect(new Set(ids).size).toBe(1) // nunca se creó un id nuevo para la misma venta

  // en el servidor hay UNA sola venta con ese id
  const sesion = await fetch(`${e.apiUrl}/api/v1/pos/auth/pin`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-dispositivo-token': e.tokenDispositivo },
    body: JSON.stringify({ pin: PIN_CAJERO }),
  }).then((x) => x.json())
  const ventas = await fetch(`${e.apiUrl}/api/v1/pos/ventas?turno_actual=true&limit=100`, {
    headers: { authorization: `Bearer ${sesion.token}` },
  }).then((x) => x.json())
  expect((ventas.items as { id: string }[]).filter((v) => v.id === ids[0])).toHaveLength(1)
})
