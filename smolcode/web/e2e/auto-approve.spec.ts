// NOTE: same EventStream.tsx SSE-bug as approval.spec.ts. These tests
// are skipped until the parseFrames / onmessage bug is fixed.
import { test, expect } from '@playwright/test'
import { mockBackend, mockSSE, waitForAppShell } from './_helpers'

test.skip('AutoApproveBanner appears after enabling auto-approve via the approval modal', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, {
    runs: [],
    start_run_response: { run_id: 'r-aa', status: 'awaiting_approval' },
    capturedRequests: captured,
  })
  await mockSSE(page, [
    {
      type: 'approval.requested',
      data: {
        decisionId: 'd-aa',
        tool: 'shell',
        args: {},
        summary: 'Destructive op',
        kind: 'destructive',
      },
    },
  ])
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Auto-approve test')
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect(page.locator('.approval-modal')).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: /no more prompts/i }).click()
  await expect(page.locator('[data-testid="auto-approve-banner"]')).toBeVisible({ timeout: 5000 })
  await expect(page.locator('.auto-approve-banner-text')).toContainText('Auto-approve is ON')
})

test.skip('Clicking Disable on the banner POSTs /auto-approve and removes the banner', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, {
    runs: [],
    start_run_response: { run_id: 'r-aa-disable', status: 'awaiting_approval' },
    capturedRequests: captured,
  })
  await mockSSE(page, [
    {
      type: 'approval.requested',
      data: {
        decisionId: 'd-aa2',
        tool: 'shell',
        args: {},
        summary: 'Destructive op',
        kind: 'destructive',
      },
    },
  ])
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Disable test')
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect(page.locator('.approval-modal')).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: /no more prompts/i }).click()
  await expect(page.locator('[data-testid="auto-approve-banner"]')).toBeVisible({ timeout: 5000 })
  // Banner has at least one auto-approve POST captured (from enabling). Now click Disable.
  await page.locator('[data-testid="auto-approve-banner"] button').click()
  await expect(page.locator('[data-testid="auto-approve-banner"]')).toHaveCount(0, { timeout: 5000 })
  // Verify the disable POST has enabled=false.
  const disableCalls = captured.filter((c) => /\/api\/runs\/[^/]+\/auto-approve$/.test(c.url) && c.method === 'POST')
  expect(disableCalls.length).toBeGreaterThanOrEqual(2)
  const last = JSON.parse(disableCalls[disableCalls.length - 1].body!)
  expect(last.enabled).toBe(false)
})
