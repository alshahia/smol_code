import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell } from './_helpers'

test('upload drop zone is visible in the plan pane', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/')
  await waitForAppShell(page)
  // The dropzone renders an <input type="file"> (hidden) plus a visible drop target.
  await expect(page.locator('.plan-uploads input[type="file"]')).toHaveCount(1)
})

test('upload list renders mock uploads with their original names', async ({ page }) => {
  await mockBackend(page, {
    uploads: [
      { stored_name: 'a1b2.txt', original_name: 'notes.txt', size: 256, mime: 'text/plain', sha256: 'a'.repeat(64), tier: 'restricted', ts: new Date().toISOString(), uploaded_by: 'tester' },
      { stored_name: 'c3d4.md', original_name: 'README.md', size: 512, mime: 'text/markdown', sha256: 'b'.repeat(64), tier: 'restricted', ts: new Date().toISOString(), uploaded_by: 'tester' },
    ],
  })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.plan-uploads')).toContainText('Uploads (2)')
  await expect(page.locator('.plan-uploads')).toContainText('notes.txt')
  await expect(page.locator('.plan-uploads')).toContainText('README.md')
})

test('upload delete button DELETEs /api/uploads/{name}', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  await mockBackend(page, {
    uploads: [
      { stored_name: 'delete-me.txt', original_name: 'delete-me.txt', size: 128, mime: 'text/plain', sha256: 'c'.repeat(64), tier: 'restricted', ts: new Date().toISOString(), uploaded_by: 'tester' },
    ],
    capturedRequests: captured,
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.locator('.upload-delete').first().click()
  await expect
    .poll(() => captured.find((c) => /\/api\/uploads\/[^/]+$/.test(c.url) && c.method === 'DELETE'), { timeout: 5000 })
    .toBeTruthy()
})
