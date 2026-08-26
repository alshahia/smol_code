import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell } from './_helpers'

test('Ctrl+Enter from the composer textarea submits a run', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, { capturedRequests: captured })
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Keyboard submit test')
  await page.keyboard.press('Control+Enter')
  await expect
    .poll(() => captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/runs')), { timeout: 5000 })
    .toBeTruthy()
})

test('Ctrl+. posts /api/runs/{id}/stop when a run is active', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, { capturedRequests: captured })
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Stop me')
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect
    .poll(() => captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/runs')), { timeout: 5000 })
    .toBeTruthy()
  // Click on body so focus is on <body> (not the textarea) when the
  // keydown fires. Decision 0033: webkit keeps focus on the textarea
  // after the Run click (chromium / firefox move focus to <body>), so
  // without this the editable-target check in lib/keyboard.ts blocks
  // Ctrl+. from firing postStop.
  await page.locator('body').click()
  await page.keyboard.press('Control+.')
  await expect
    .poll(() => captured.find((c) => /\/api\/runs\/[^/]+\/stop$/.test(c.url) && c.method === 'POST'), { timeout: 5000 })
    .toBeTruthy()
})

test('Ctrl+K opens the Dashboard overlay', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/')
  await waitForAppShell(page)
  await page.keyboard.press('Control+k')
  await expect(page.locator('#dashboard-overlay')).toBeVisible()
  await expect(page.locator('.dashboard [data-testid="dashboard-runs-today"]')).toBeVisible()
})

test('Ctrl+/ opens the Dashboard overlay (help)', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/')
  await waitForAppShell(page)
  await page.keyboard.press('Control+/')
  await expect(page.locator('#dashboard-overlay')).toBeVisible()
  await expect(page.locator('.dashboard [data-testid="dashboard-runs-today"]')).toBeVisible()
})
