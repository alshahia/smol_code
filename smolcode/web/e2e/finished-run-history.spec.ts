// decision 0040 section 4: selecting a FINISHED run must show its
// recorded history, the run's tokens, its cost and its terminal status
// without waiting for an SSE stream that the server has already finished
// sending. Before the fix this pane sat on "Waiting for events..."
// indefinitely.
//
// The SSE endpoint is deliberately NOT mocked in this spec. That is the
// point: if the SPA tries to open a live stream for a terminal run, it
// hits the real dev-server route, never receives a terminal frame, and
// these assertions time out.

import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell, mockTerminalRun } from './_helpers'

const FINISHED_ID = 'fin-1'

// Shapes must match what EventStream.renderBody actually reads:
// plan.step renders `plan`, step.action renders `tool_calls[].name/args`,
// step.final_answer renders `answer`.
const FINISHED_EVENTS = [
  { type: 'run.started', run_id: FINISHED_ID, task: 'Summarise the changelog', ts: 1700000000 },
  { type: 'plan.step', run_id: FINISHED_ID, plan: 'Read CHANGELOG.md' },
  {
    type: 'step.action',
    run_id: FINISHED_ID,
    thought: 'I need the changelog first.',
    tool_calls: [{ name: 'read_file', args: { path: 'CHANGELOG.md' } }],
  },
  { type: 'step.final_answer', run_id: FINISHED_ID, answer: 'The changelog has 3 entries.' },
  { type: 'run.ended', run_id: FINISHED_ID, status: 'done', result: 'The changelog has 3 entries.' },
]

test.beforeEach(async ({ page }) => {
  await mockBackend(page, {
    runs: [
      mockTerminalRun({
        id: FINISHED_ID,
        task: 'Summarise the changelog',
        status: 'done',
        tokens: { input: 1200, output: 340, total: 1540, cost_usd: 0.0042 },
      }),
    ],
    events_snapshot: {
      [FINISHED_ID]: { events: FINISHED_EVENTS, status: 'done' },
    },
  })
  await page.goto('/')
  await waitForAppShell(page)
})

test('a finished run renders its recorded history without waiting for SSE', async ({ page }) => {
  await page.locator('.run-history .run-row').first().click()

  // The recorded log is on screen. This is the assertion that used to
  // hang: the pane used to show "Waiting for events..." and stay there.
  await expect(page.locator('.event-stream')).toBeVisible()
  await expect(page.locator('.event-stream .stream-row')).toHaveCount(FINISHED_EVENTS.length)

  // Spot-check real frame bodies rather than just a count.
  await expect(page.locator('.event-stream')).toContainText('I need the changelog first.')
  await expect(page.locator('.event-stream')).toContainText('read_file')
  await expect(page.locator('.event-stream')).toContainText('CHANGELOG.md')
  await expect(page.locator('.event-stream')).toContainText('The changelog has 3 entries.')

  // And the placeholder is gone.
  await expect(page.locator('.event-stream')).not.toContainText('Waiting for events...')
})

test('a finished run reports its terminal status rather than a connection state', async ({ page }) => {
  await page.locator('.run-history .run-row').first().click()
  await expect(page.locator('.event-stream .stream-status')).toHaveText('SSE: done')
})

test('a finished run still shows tokens, cost and status in the Inspector', async ({ page }) => {
  await page.locator('.run-history .run-row').first().click()

  const inspector = page.locator('#inspector-pane')
  await expect(inspector).toBeVisible()

  // Phase 5 items 5 (countdown re-seed) and 1 (CostBadge) both land here.
  // These are the fields a user actually opened the run to read.
  await expect(inspector).toContainText('cost:')
  await expect(inspector).toContainText('status:')
  await expect(inspector.locator('.cost-badge, [class*="cost"]').first()).toBeVisible()
})

test('no EventSource is opened for a terminal run', async ({ page }) => {
  // Count live-stream connections. The SPA opens one per EventSource; a
  // terminal run must open none, or the request hangs against the real
  // dev-server route and the pane never settles.
  let sseOpens = 0
  page.on('request', (req) => {
    if (/\/api\/runs\/[^/]+\/events(\?|$)/.test(req.url())) sseOpens++
  })

  await page.locator('.run-history .run-row').first().click()
  await expect(page.locator('.event-stream .stream-row')).toHaveCount(FINISHED_EVENTS.length)
  await expect(page.locator('.event-stream .stream-status')).toHaveText('SSE: done')

  // Give any stray connection a chance to appear before asserting.
  await page.waitForTimeout(400)
  expect(sseOpens).toBe(0)
})
