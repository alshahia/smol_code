import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell, defaultMockDashboard } from './_helpers'

test('header Dashboard button toggles the overlay open and closed', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/')
  await waitForAppShell(page)
  // Closed initially.
  await expect(page.locator('#dashboard-overlay')).toHaveCount(0)
  await page.locator('.dashboard-open').click()
  await expect(page.locator('#dashboard-overlay')).toBeVisible()
  await page.locator('.dashboard-open').click()
  await expect(page.locator('#dashboard-overlay')).toHaveCount(0)
})

test('Dashboard renders runs / tokens / errors / cost + sparkline + provider table', async ({ page }) => {
  await mockBackend(page, {
    dashboard: defaultMockDashboard({
      runs_today: 7,
      tokens_today: { input: 1234, output: 567, total: 1801 },
      errors_today: 2,
      cost_estimate_usd_today: 1.23,
      sparkline: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5],
      by_provider: {
        anthropic: { input: 1000, output: 500, total: 1500 },
        openai: { input: 234, output: 67, total: 301 },
      },
    }),
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.locator('.dashboard-open').click()
  await expect(page.locator('#dashboard-overlay')).toBeVisible()
  await expect(page.locator('[data-testid="dashboard-runs-today"] .dashboard-card-value')).toHaveText('7')
  await expect(page.locator('[data-testid="dashboard-tokens-today"] .dashboard-card-value')).toHaveText('1,801')
  await expect(page.locator('[data-testid="dashboard-errors-today"] .dashboard-card-value')).toHaveText('2')
  await expect(page.locator('[data-testid="dashboard-cost-today"] .dashboard-card-value')).toContainText('$1.23')
  await expect(page.locator('[data-testid="dashboard-sparkline"]')).toBeVisible()
  await expect(page.locator('.dashboard-provider-table tbody tr')).toHaveCount(2)
})

test('Dashboard shows "No runs yet today" when by_provider is empty', async ({ page }) => {
  await mockBackend(page, { dashboard: defaultMockDashboard() })
  await page.goto('/')
  await waitForAppShell(page)
  await page.locator('.dashboard-open').click()
  await expect(page.locator('#dashboard-overlay')).toBeVisible()
  await expect(page.locator('.dashboard-empty')).toHaveText(/No runs yet today/i)
})
