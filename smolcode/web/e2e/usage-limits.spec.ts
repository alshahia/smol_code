// decision 0032: e2e test for the UsageLimitsPanel.
// Covers (a) the panel mounting under Dashboard, (b) PUT round-trip,
// (c) the over-cap row class when today's spend >= cap, (d) reset
// clearing all caps.

import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell } from './_helpers'

test('Usage limits panel mounts under the Dashboard overlay', async ({ page }) => {
  await mockBackend(page, {
    cost_caps_response: {
      caps: [],
      defaults: [],
      providers: ['openai'],
      current_spend_usd: { openai: 0.0 },
    },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.locator('.dashboard-open').click()
  await expect(page.locator('#dashboard-overlay')).toBeVisible()
  await expect(page.locator('[data-testid="usage-limits-table"]')).toBeVisible()
})

test('Saving a cap fires PUT /api/cost-caps and shows the saved-flash chip', async ({ page }) => {
  await mockBackend(page, {
    cost_caps_response: {
      caps: [],
      defaults: [],
      providers: ['openai'],
      current_spend_usd: { openai: 0.0 },
    },
    cost_caps_put_response: {
      caps: [{ provider: 'openai', cap_usd: 1 }],
      defaults: [],
      providers: ['openai'],
      current_spend_usd: { openai: 0.0 },
      updated_at: 1700000000,
    },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.locator('.dashboard-open').click()
  const capInput = page.locator('[data-testid="usage-limits-input-openai"]')
  await expect(capInput).toBeVisible()
  await capInput.fill('1')
  await page.locator('[data-testid="usage-limits-save"]').click()
  await expect(page.locator('[data-testid="usage-limits-saved-flash"]')).toBeVisible()
})

test('Over-cap row gets the .over class', async ({ page }) => {
  await mockBackend(page, {
    cost_caps_response: {
      caps: [{ provider: 'openai', cap_usd: 0.1 }],
      defaults: [{ provider: 'openai', cap_usd: 0.1 }],
      providers: ['openai'],
      current_spend_usd: { openai: 0.5 },
    },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.locator('.dashboard-open').click()
  const row = page.locator('[data-testid="usage-limits-row-openai"]')
  await expect(row).toBeVisible()
  await expect(row).toHaveClass(/\bover\b/)
})

test('Reset clears the seeded cap via an empty PUT body', async ({ page }) => {
  await mockBackend(page, {
    cost_caps_response: {
      caps: [{ provider: 'openai', cap_usd: 1 }],
      defaults: [{ provider: 'openai', cap_usd: 1 }],
      providers: ['openai'],
      current_spend_usd: { openai: 0.1 },
    },
    cost_caps_put_response: {
      caps: [],
      defaults: [{ provider: 'openai', cap_usd: 1 }],
      providers: ['openai'],
      current_spend_usd: { openai: 0.1 },
      updated_at: 1700000001,
    },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.locator('.dashboard-open').click()
  await page.locator('[data-testid="usage-limits-reset"]').click()
  const capInput = page.locator('[data-testid="usage-limits-input-openai"]')
  await expect(capInput).toHaveValue('')
})