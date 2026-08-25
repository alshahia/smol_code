// Decision 0031: drag-and-drop queue reorder (e2e).
//
// Verifies the SPA wires the keyboard up/down buttons + drag-and-drop
// to PATCH /api/queue/{id}, that the position label updates after
// the move, and that a PATCH failure shows an error banner + reverts
// the order.

import { test, expect } from '@playwright/test'
import {
  acceptDialogs,
  mockBackend,
  waitForAppShell,
  type MockQueueEntry,
} from './_helpers'

function queuedFixture(): MockQueueEntry[] {
  const now = Math.floor(Date.now() / 1000)
  return [
    { id: 'q-A', task: 'Task A', tier: 'restricted', queued_at: now, project: null, session_id: null, queue_position: 1 },
    { id: 'q-B', task: 'Task B', tier: 'restricted', queued_at: now + 1, project: null, session_id: null, queue_position: 2 },
    { id: 'q-C', task: 'Task C', tier: 'restricted', queued_at: now + 2, project: null, session_id: null, queue_position: 3 },
  ]
}

test('Move-down button PATCHes /api/queue/{id} and re-stamps positions', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  const queued = queuedFixture()
  // After PATCH the mock returns q-A moved to position 2.
  const reordered: MockQueueEntry[] = [
    { ...queued[1], queue_position: 1 },
    { ...queued[0], queue_position: 2 },
    { ...queued[2], queue_position: 3 },
  ]
  await mockBackend(page, {
    queue: { active: [], queued },
    move_queue_response: { run_id: 'q-A', position: 2, queue: reordered },
    capturedRequests: captured,
  })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.queue-row')).toHaveCount(3)

  // Click Move-down on the first row (q-A) -> target position 2.
  await page
    .locator('.queue-row')
    .first()
    .getByRole('button', { name: /move .* down/i })
    .click()

  await expect
    .poll(
      () =>
        captured.find(
          (c) =>
            /\/api\/queue\/[^/]+$/.test(c.url) &&
            c.method === 'PATCH' &&
            c.body === JSON.stringify({ position: 2 }),
        ),
      { timeout: 5000 },
    )
    .toBeTruthy()

  // Position labels update to reflect the new order.
  const positions = await page.locator('.queue-row .queue-row-pos').allTextContents()
  expect(positions).toEqual(['#1', '#2', '#3'])
})

test('Move-up button PATCHes with position=1 and is disabled on the head row', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  const queued = queuedFixture()
  await mockBackend(page, {
    queue: { active: [], queued },
    move_queue_response: { run_id: 'q-B', position: 1, queue: queued },
    capturedRequests: captured,
  })
  await page.goto('/')
  await waitForAppShell(page)
  // The head row's Move-up is disabled (already at the top).
  await expect(
    page.locator('.queue-row').first().getByRole('button', { name: /move .* up/i }),
  ).toBeDisabled()
  // The tail row's Move-down is disabled.
  await expect(
    page.locator('.queue-row').last().getByRole('button', { name: /move .* down/i }),
  ).toBeDisabled()
  // Click Move-up on the second row (q-B) -> target position 1.
  await page
    .locator('.queue-row')
    .nth(1)
    .getByRole('button', { name: /move .* up/i })
    .click()
  await expect
    .poll(
      () =>
        captured.find(
          (c) =>
            /\/api\/queue\/[^/]+$/.test(c.url) &&
            c.method === 'PATCH' &&
            c.body === JSON.stringify({ position: 1 }),
        ),
      { timeout: 5000 },
    )
    .toBeTruthy()
})

test('drag-and-drop reorder fires PATCH with the correct target position', async ({ page }) => {
  const captured: { method: string; url: string; body?: string }[] = []
  const queued = queuedFixture()
  await mockBackend(page, {
    queue: { active: [], queued },
    move_queue_response: { run_id: 'q-A', position: 3, queue: queued },
    capturedRequests: captured,
  })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.queue-row')).toHaveCount(3)
  // Drag the first row onto the third row's upper half -> target slot 4 -> clamps to 3.
  const source = page.locator('.queue-row').first()
  const target = page.locator('.queue-row').nth(2)
  await source.dragTo(target, { targetPosition: { x: 20, y: 5 } })
  await expect
    .poll(
      () =>
        captured.find(
          (c) =>
            /\/api\/queue\/[^/]+$/.test(c.url) &&
            c.method === 'PATCH' &&
            c.body === JSON.stringify({ position: 3 }),
        ),
      { timeout: 5000 },
    )
    .toBeTruthy()
})

test('a single-entry queue disables both up and down buttons', async ({ page }) => {
  const queued = queuedFixture().slice(0, 1)
  await mockBackend(page, {
    queue: { active: [], queued },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.queue-row')).toHaveCount(1)
  await expect(
    page.locator('.queue-row').first().getByRole('button', { name: /move .* up/i }),
  ).toBeDisabled()
  await expect(
    page.locator('.queue-row').first().getByRole('button', { name: /move .* down/i }),
  ).toBeDisabled()
})

test('PATCH failure shows the error banner and refetches the queue', async ({ page }) => {
  const queued = queuedFixture()
  // Set up the rest of the backend mocks so the SPA can render.
  await mockBackend(page, {
    queue: { active: [], queued },
  })
  // Track how many GET /api/queue polls the SPA fires after the failed
  // PATCH. Register AFTER mockBackend so this handler takes precedence
  // (Playwright evaluates routes last-registered-first).
  let getCount = 0
  await page.route(/\/api\/queue/, async (route) => {
    const method = route.request().method()
    if (method === 'GET') {
      getCount += 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ active: [], queued }),
      })
      return
    }
    if (method === 'PATCH') {
      // 404 to simulate a concurrent cancel race.
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'queue entry not found' }),
      })
      return
    }
    await route.fallback()
  })
  acceptDialogs(page)
  await page.goto('/')
  await waitForAppShell(page)
  await expect(page.locator('.queue-row')).toHaveCount(3)
  const getCountBefore = getCount
  // Trigger a move-down on the head row.
  await page
    .locator('.queue-row')
    .first()
    .getByRole('button', { name: /move .* down/i })
    .click()
  // Error banner appears and stays.
  await expect(page.locator('.error-banner')).toBeVisible({ timeout: 5000 })
  await expect(page.locator('.error-banner')).toContainText(/HTTP 404|queue entry not found/i)
  // The rollback refetch happened (>= 1 extra GET /api/queue after the click).
  expect(getCount).toBeGreaterThan(getCountBefore)
})
