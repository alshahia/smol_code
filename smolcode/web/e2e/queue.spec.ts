import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell, mockRunningRun } from './_helpers'

test('queue pane lists active + queued runs', async ({ page }) => {
  await mockBackend(page, {
    runs: [mockRunningRun({ id: 'q-active', task: 'Computing pi' })],
    queue: {
      active: [mockRunningRun({ id: 'q-active', task: 'Computing pi' })],
      queued: [
        {
          id: 'q-queued-1',
          task: 'Write tests',
          tier: 'restricted',
          queued_at: Math.floor(Date.now() / 1000),
          project: null,
          session_id: null,
          queue_position: 1,
        },
      ],
    },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.queue-pane')).toBeVisible()
  await expect(page.locator('.active-row')).toHaveCount(1)
  await expect(page.locator('.queue-row')).toHaveCount(1)
})

test('Cancel button DELETEs /api/queue/{id}', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, {
    runs: [],
    queue: {
      active: [],
      queued: [
        {
          id: 'q-cancel',
          task: 'Cancel me',
          tier: 'restricted',
          queued_at: Math.floor(Date.now() / 1000),
          project: null,
          session_id: null,
          queue_position: 1,
        },
      ],
    },
    capturedRequests: captured,
  })
  await page.goto('/')
  await waitForAppShell(page)
  // Auto-accept confirm dialog.
  page.on('dialog', (d) => { void d.accept().catch(() => {}) })
  await expect(page.locator('.queue-row')).toHaveCount(1)
  await page.locator('.queue-row button').click()
  await expect
    .poll(() => captured.find((c) => /\/api\/queue\/[^/]+$/.test(c.url) && c.method === 'DELETE'), { timeout: 5000 })
    .toBeTruthy()
})

test('queue pane shows the empty state when no active or queued runs', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.queue-empty')).toBeVisible()
})
