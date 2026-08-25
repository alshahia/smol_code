// Decision 0030: previously skipped because EventStream.tsx used
// es.onmessage + parseFrames() which silently dropped every named
// SSE frame. The SPA now registers an addEventListener per known
// event type, so approval.requested reaches the parent and the
// modal opens. See docs/decisions/0030 for the full writeup.
import { test, expect } from '@playwright/test'
import { mockBackend, mockSSE, waitForAppShell } from './_helpers'

async function triggerApprovalModal(page: import('@playwright/test').Page, runId: string, captured: { method: string; url: string; body?: string }[]): Promise<void> {
  await mockBackend(page, {
    runs: [],
    start_run_response: { run_id: runId, status: 'awaiting_approval' },
    capturedRequests: captured,
  })
  // SSE handler must be installed AFTER mockBackend so it takes precedence.
  await mockSSE(page, [
    {
      type: 'approval.requested',
      data: {
        decision_id: 'd-1',
        tool: 'shell',
        args: { cmd: 'rm -rf /tmp/test' },
        summary: 'Run destructive command',
      },
    },
  ])
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Trigger approval')
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect
    .poll(() => captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/runs')), { timeout: 5000 })
    .toBeTruthy()
  await expect(page.locator('.approval-modal')).toBeVisible({ timeout: 5000 })
}

test('destructive approval: Approve POSTs approved=true', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await triggerApprovalModal(page, 'r-approval', captured)
  await page.getByRole('button', { name: /^Approve$/ }).click()
  await expect
    .poll(() => captured.find((c) => /\/api\/runs\/[^/]+\/approval$/.test(c.url) && c.method === 'POST'), { timeout: 5000 })
    .toBeTruthy()
  const call = captured.find((c) => /\/api\/runs\/[^/]+\/approval$/.test(c.url) && c.method === 'POST')!
  const body = JSON.parse(call.body!)
  expect(body.approved).toBe(true)
  await expect(page.locator('.approval-modal')).toHaveCount(0)
})

test('destructive approval: Deny POSTs approved=false', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await triggerApprovalModal(page, 'r-deny', captured)
  await page.getByRole('button', { name: /^Deny$/ }).click()
  await expect
    .poll(() => captured.find((c) => /\/api\/runs\/[^/]+\/approval$/.test(c.url) && c.method === 'POST'), { timeout: 5000 })
    .toBeTruthy()
  const call = captured.find((c) => /\/api\/runs\/[^/]+\/approval$/.test(c.url) && c.method === 'POST')!
  const body = JSON.parse(call.body!)
  expect(body.approved).toBe(false)
})

test('destructive approval: Approve (no more prompts) also POSTs /auto-approve enabled=true', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await triggerApprovalModal(page, 'r-auto', captured)
  await page.getByRole('button', { name: /no more prompts/i }).click()
  await expect
    .poll(() => captured.find((c) => /\/api\/runs\/[^/]+\/approval$/.test(c.url) && c.method === 'POST'), { timeout: 5000 })
    .toBeTruthy()
  await expect
    .poll(() => captured.find((c) => /\/api\/runs\/[^/]+\/auto-approve$/.test(c.url) && c.method === 'POST'), { timeout: 5000 })
    .toBeTruthy()
  const autoCall = captured.find((c) => /\/api\/runs\/[^/]+\/auto-approve$/.test(c.url) && c.method === 'POST')!
  const autoBody = JSON.parse(autoCall.body!)
  expect(autoBody.enabled).toBe(true)
})
