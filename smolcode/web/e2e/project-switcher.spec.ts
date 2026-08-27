// Phase 4 F4 (decision 0037): Playwright spec for the outside-workspace project selector.

import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell } from './_helpers'

async function setup(page: import('@playwright/test').Page, opts: Parameters<typeof mockBackend>[1], captured?: { method: string; url: string; body?: string }[]) {
  await mockBackend(page, { ...opts, capturedRequests: captured })
  await page.goto('/')
  await waitForAppShell(page)
}

test('in-workspace default: name only sends {name} (no root)', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await setup(page, { projects: [] }, captured)
  await page.getByLabel(/New project name/i).fill('legacy')
  await page.getByLabel(/New project root path/i).press('Enter')
  await expect
    .poll(() => captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/projects')), { timeout: 5000 })
    .toBeTruthy()
  const call = captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/projects'))!
  const body = JSON.parse(call.body!)
  expect(body).toEqual({ name: 'legacy' })
})

test('outside-workspace: name + path sends {name, root}', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await setup(page, { projects: [] }, captured)
  await page.getByLabel(/New project name/i).fill('ext')
  await page.getByLabel(/New project root path/i).fill('C:/outside/proj')
  await page.getByLabel(/New project root path/i).press('Enter')
  await expect
    .poll(() => captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/projects')), { timeout: 5000 })
    .toBeTruthy()
  const call = captured.find((c) => c.method === 'POST' && c.url.endsWith('/api/projects'))!
  const body = JSON.parse(call.body!)
  expect(body).toEqual({ name: 'ext', root: 'C:/outside/proj' })
})

test('outside-workspace notice appears when path is outside live workspace', async ({ page }) => {
  await mockBackend(page, { projects: [], config: { workspace: 'C:/smolcode/ws' } })
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByLabel(/New project root path/i).fill('D:/elsewhere/x')
  const notice = page.getByRole('note')
  await expect(notice).toBeVisible({ timeout: 3000 })
  await expect(notice).toContainText(/outside the default workspace/i)
  await expect(notice).toContainText('C:/smolcode/ws')
})

test('outside-workspace notice does NOT appear for in-workspace path', async ({ page }) => {
  await mockBackend(page, { projects: [], config: { workspace: 'C:/smolcode/ws' } })
  await page.goto('/')
  await waitForAppShell(page)
  await page.getByLabel(/New project root path/i).fill('C:/smolcode/ws/sub/file.py')
  await expect(page.queryByRole('note')).resolves.toBeNull()
})

test('Browse + Path inputs are present (Phase 4 affordance)', async ({ page }) => {
  await mockBackend(page, { projects: [] })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.getByLabel(/New project name/i)).toBeVisible()
  await expect(page.getByLabel(/New project root path/i)).toBeVisible()
  await expect(page.getByRole('button', { name: /Browse for project folder/i })).toBeVisible()
  await expect(page.getByTestId('project-browse-input')).toBeAttached()
})

