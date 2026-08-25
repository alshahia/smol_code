import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell, waitForErrorScreen, waitForLoadingScreen } from './_helpers'

test('app shell renders header + 3 panes with a healthy /api/config', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.brand')).toHaveText('smolcode')
  await expect(page.locator('.pane.plan')).toBeVisible()
  await expect(page.locator('.pane.stream')).toBeVisible()
  await expect(page.locator('#inspector-pane')).toBeVisible()
})

test('error screen renders when /api/config returns 500', async ({ page }) => {
  await mockBackend(page, { fail_config: true })
  await page.goto('/')
  await waitForErrorScreen(page)
  await expect(page.locator('.error-screen h1')).toContainText(/Cannot reach/i)
})

test('loading screen renders when /api/config hangs', async ({ page }) => {
  await mockBackend(page, { hang_config: true })
  await page.goto('/')
  await waitForLoadingScreen(page)
  await expect(page.locator('.loading')).toContainText(/Loading/i)
})

test('header shows dashboard toggle + tier badge + workspace path', async ({ page }) => {
  await mockBackend(page, { config: { workspace: '/tmp/example-ws' } })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.dashboard-open')).toBeVisible()
  // Header tier badge (active tier). Inspector renders more tier badges for the
  // policy cards; scope to .header to be unambiguous.
  await expect(page.locator('.header .tier-badge')).toBeVisible()
  await expect(page.locator('.ws')).toContainText('example-ws')
})
