import { defineConfig, devices } from '@playwright/test'

const frontendOrigin = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5200'

/** Milliseconds between Playwright actions; set `E2E_SLOW_MO=0` to disable. */
function slowMoFromEnv(): number | undefined {
  const raw = process.env.E2E_SLOW_MO
  if (raw === undefined || raw === '') return undefined
  const n = Number(raw)
  if (!Number.isFinite(n) || n <= 0) return undefined
  return n
}

const slowMo = slowMoFromEnv()
const launchOptions = slowMo != null ? { slowMo } : {}

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: frontendOrigin,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    locale: 'zh-CN',
    actionTimeout: 15_000,
    navigationTimeout: 45_000,
    launchOptions,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command:
      'pnpm exec vite --host 127.0.0.1 --port 5200 --strictPort',
    url: frontendOrigin,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
