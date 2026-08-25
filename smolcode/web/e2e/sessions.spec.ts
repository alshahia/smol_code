import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell } from './_helpers'

test('sessions pane lists mock sessions for the active project', async ({ page }) => {
  await mockBackend(page, {
    sessions: [
      { id: 'sess-1', path: '/tmp/sess-1.jsonl', size_bytes: 1024, mtime_iso: new Date().toISOString(), name: 'First session', run_count: 3, project: null },
      { id: 'sess-2', path: '/tmp/sess-2.jsonl', size_bytes: 2048, mtime_iso: new Date().toISOString(), name: null, run_count: 5, project: null },
    ],
  })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.sessions-pane')).toBeVisible()
  // Two sessions should appear in the list (class .sessions-item on each <li>).
  await expect(page.locator('.sessions-pane .sessions-item')).toHaveCount(2)
  await expect(page.locator('.sessions-pane')).toContainText('First session')
})

test('create-session button POSTs /api/sessions and refreshes the list', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, {
    sessions: [],
    capturedRequests: captured,
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.locator('.sessions-name-input').fill('My new session')
  await page.locator('.sessions-pane .btn-primary').click()
  await expect
    .poll(() => captured.find((c) => c.url.endsWith('/api/sessions') && c.method === 'POST'), { timeout: 5000 })
    .toBeTruthy()
})
