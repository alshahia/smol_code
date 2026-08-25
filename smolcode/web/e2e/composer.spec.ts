import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell } from './_helpers'

test('typing + clicking submit POSTs /api/runs with the task', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, { capturedRequests: captured })
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByPlaceholder(/Describe the task/i).fill('Write a haiku')
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect
    .poll(() => captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/runs')), { timeout: 5000 })
    .toBeTruthy()
  const submit = captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/runs'))!
  const body = JSON.parse(submit.body!)
  expect(body.task).toBe('Write a haiku')
  expect(body.tier).toBe('restricted')
})

test('empty composer shows "Task cannot be empty" error when submit is clicked', async ({ page }) => {
  // The composer does not disable the button when empty; instead the click
  // handler validates the trimmed task and renders an error message.
  await mockBackend(page)
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByRole('button', { name: /^Run$/ }).click()
  await expect(page.locator('.run-composer .error-banner')).toHaveText(/cannot be empty/i)
})
