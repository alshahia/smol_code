import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell, mockTerminalRun, mockRunningRun } from './_helpers'

test('filter by task text narrows the run list', async ({ page }) => {
  await mockBackend(page, {
    runs: [
      mockTerminalRun({ id: 'h-1', task: 'Write a haiku' }),
      mockTerminalRun({ id: 'h-2', task: 'Compute pi' }),
      mockTerminalRun({ id: 'h-3', task: 'Haiku about autumn' }),
    ],
  })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.run-history .run-row')).toHaveCount(3)
  await page.locator('.run-history-filter').fill('haiku')
  await expect(page.locator('.run-history .run-row')).toHaveCount(2)
})

test('filter by tier narrows the run list', async ({ page }) => {
  await mockBackend(page, {
    runs: [
      mockTerminalRun({ id: 't-1', task: 'A', tier: 'restricted' }),
      mockTerminalRun({ id: 't-2', task: 'B', tier: 'elevated' }),
      mockTerminalRun({ id: 't-3', task: 'C', tier: 'restricted' }),
    ],
  })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.run-history .run-row')).toHaveCount(3)
  await page.locator('.run-history-tier').selectOption('elevated')
  await expect(page.locator('.run-history .run-row')).toHaveCount(1)
})

test('filter by status narrows the run list + clicking selects a run', async ({ page }) => {
  await mockBackend(page, {
    runs: [
      mockTerminalRun({ id: 's-1', task: 'Done task', status: 'done' }),
      mockRunningRun({ id: 's-2', task: 'Running task' }),
      mockTerminalRun({ id: 's-3', task: 'Errored task', status: 'error' }),
    ],
  })
  await page.goto('/')
  await waitForAppShell(page)
  await page.locator('.run-history-status').selectOption('error')
  await expect(page.locator('.run-history .run-row')).toHaveCount(1)
  // Click to select
  await page.locator('.run-history .run-row').first().click()
  await expect(page.locator('.run-history .run-row-active')).toHaveCount(1)
})
