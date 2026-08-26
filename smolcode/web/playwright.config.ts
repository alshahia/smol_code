import { defineConfig, devices } from '@playwright/test';

// Loopback-only smoke test for Phase 3 PREWORK.
// Requires `pnpm dev` to be running OR Playwright will spawn it via webServer.
//
// Decision 0033: multi-browser matrix (chromium + firefox + webkit).
// Each project uses the same webServer (vite dev on :5173) and the same
// baseURL; per-project overrides are minimal so a test failure is attributable
// to the browser, not config drift.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],
  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60000,
  },
});