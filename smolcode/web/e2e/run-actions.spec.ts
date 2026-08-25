import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell, mockTerminalRun } from './_helpers'

test('Retry button POSTs /api/runs/{id}/retry and switches the active run', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, {
    runs: [mockTerminalRun({ id: 'r-actions', status: 'done' })],
    start_run_response: { run_id: 'r-actions', status: 'done' },
    retry_response: { run_id: 'r-retry-1', status: 'running' },
    capturedRequests: captured,
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Retry me')
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect
    .poll(() => captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/runs')), { timeout: 5000 })
    .toBeTruthy()
  // RunActions now rendered (terminal run is active)
  await expect(page.locator('[data-testid="run-actions"]')).toBeVisible()
  await page.locator('[data-testid="run-action-retry"]').click()
  await expect
    .poll(() => captured.find((c) => /\/api\/runs\/[^/]+\/retry$/.test(c.url) && c.method === 'POST'), { timeout: 5000 })
    .toBeTruthy()
})

test('Re-run button POSTs /api/runs/{id}/rerun', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, {
    runs: [mockTerminalRun({ id: 'r-rerun', status: 'done' })],
    start_run_response: { run_id: 'r-rerun', status: 'done' },
    capturedRequests: captured,
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Rerun me')
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect(page.locator('[data-testid="run-actions"]')).toBeVisible({ timeout: 5000 })
  await page.locator('[data-testid="run-action-rerun"]').click()
  await expect
    .poll(() => captured.find((c) => /\/api\/runs\/[^/]+\/rerun$/.test(c.url) && c.method === 'POST'), { timeout: 5000 })
    .toBeTruthy()
})

test('Export button downloads a blob named run-{id}.json', async ({ page }) => {
  await mockBackend(page, {
    runs: [mockTerminalRun({ id: 'r-export', status: 'done' })],
    start_run_response: { run_id: 'r-export', status: 'done' },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Export me')
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect(page.locator('[data-testid="run-actions"]')).toBeVisible({ timeout: 5000 })

  const downloadPromise = page.waitForEvent('download', { timeout: 5000 })
  await page.locator('[data-testid="run-action-export"]').click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('run-r-export.json')
})

test('While a button is busy all three are disabled', async ({ page }) => {
  // Add a 1.5s artificial delay to the retry endpoint so the busy state is observable.
  await mockBackend(page, {
    runs: [mockTerminalRun({ id: 'r-busy', status: 'done' })],
    start_run_response: { run_id: 'r-busy', status: 'done' },
    delays: { retry: 1500 },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Busy')
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect(page.locator('[data-testid="run-actions"]')).toBeVisible({ timeout: 5000 })
  await page.locator('[data-testid="run-action-retry"]').click()
  // All three buttons disabled while retry is in-flight. The Retry label flips to "Retrying..."
  // to confirm the busy state.
  await expect(page.locator('[data-testid="run-action-retry"]')).toHaveText('Retrying...')
  await expect(page.locator('[data-testid="run-action-retry"]')).toBeDisabled()
  await expect(page.locator('[data-testid="run-action-rerun"]')).toBeDisabled()
  await expect(page.locator('[data-testid="run-action-export"]')).toBeDisabled()
})
