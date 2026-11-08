import { defineConfig } from '@playwright/test'

// E2E en modo navegador contra el backend local con FISCAL_PROVEEDOR=simulado y `datos-demo --catalogo`.
// `scripts/e2e-servidor.mjs` recrea la BD desechable `mundorepuestos_e2e` y levanta API (:8010) + worker fiscal.
export default defineConfig({
  testDir: 'e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  outputDir: 'test-results',
  use: {
    baseURL: 'http://127.0.0.1:1420',
    viewport: { width: 1366, height: 800 },
    locale: 'es-CO',
    timezoneId: 'America/Bogota',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'node scripts/e2e-servidor.mjs',
      url: 'http://127.0.0.1:8010/api/v1/health',
      timeout: 420_000,
      reuseExistingServer: false,
      stdout: 'ignore',
    },
    { command: 'npm run dev', url: 'http://127.0.0.1:1420', reuseExistingServer: true, timeout: 60_000 },
  ],
})
