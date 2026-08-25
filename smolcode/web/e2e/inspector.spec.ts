import { test, expect } from '@playwright/test'
import { mockBackend, waitForAppShell, mockTerminalRun, mockSubAgentHistory } from './_helpers'

// The Inspector reads from `activeRun` (set by refreshRuns from /api/runs),
// not directly from `activeRunId`. Clicking a run row in RunHistory only
// updates activeRunId; the next refreshRuns fires 5s later. To avoid
// waiting 5s in tests, these specs use the submit-a-task path: posting
// /api/runs calls refreshRuns() synchronously, which sets activeRun.

async function submitAndWaitForActiveRun(
  page: import('@playwright/test').Page,
  runId: string,
): Promise<void> {
  await page.getByPlaceholder(/Describe the task/i).fill('Activate me')
  await page.getByRole('button', { name: /^Run$/ }).click()
  // Wait for the POST + the subsequent refreshRuns to render Inspector.
  await expect(page.locator('#inspector-pane .inspector-section', { hasText: 'Active run' })).toBeVisible({
    timeout: 8000,
  })
  // The id slice is 12 chars; just check the run is in there.
  await expect(page.locator('#inspector-pane')).toContainText(runId.slice(0, 12))
}

test('Inspector shows the active run summary + token usage for a terminal run', async ({ page }) => {
  await mockBackend(page, {
    runs: [
      mockTerminalRun({
        id: 'r-inspect-1',
        task: 'Compute pi',
        status: 'done',
        tokens: { input: 4242, output: 242, total: 4484 },
        step_count: 7,
      }),
    ],
    start_run_response: { run_id: 'r-inspect-1', status: 'done' },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await submitAndWaitForActiveRun(page, 'r-inspect-1')
  await expect(page.locator('#inspector-pane')).toContainText('done')
  await expect(page.locator('#inspector-pane')).toContainText('restricted')
  // Token usage section
  const tokenSection = page.locator('#inspector-pane .inspector-section', { hasText: 'Token usage' })
  await expect(tokenSection).toContainText('4,242')
  await expect(tokenSection).toContainText('4,484')
})

test('Inspector renders SubAgentList with per-row cost badges + total chip when subagent_history is present', async ({ page }) => {
  await mockBackend(page, {
    runs: [
      mockTerminalRun({
        id: 'r-sub-1',
        task: 'Orchestrated run',
        status: 'done',
        subagent_history: mockSubAgentHistory(),
      }),
    ],
    start_run_response: { run_id: 'r-sub-1', status: 'done' },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await submitAndWaitForActiveRun(page, 'r-sub-1')
  // Sub-agents section + list rows
  await expect(page.locator('#inspector-pane .subagent-list')).toBeVisible()
  await expect(page.locator('#inspector-pane .subagent-list-row')).toHaveCount(2)
  // Specialist + tokens + cost badge for the first row
  const firstRow = page.locator('#inspector-pane .subagent-list-row').first()
  await expect(firstRow.locator('.subagent-specialist')).toHaveText('planner')
  await expect(firstRow.locator('.subagent-tokens')).toContainText('tokens')
  await expect(firstRow.locator('[data-testid="subagent-cost"]')).toBeVisible()
  // Total chip (decision 0028) when sum(cost_usd) > 0
  await expect(page.locator('[data-testid="subagent-list-total"]')).toBeVisible()
  await expect(page.locator('[data-testid="subagent-list-total"]')).toContainText('Sub-agents total')
})

test('Inspector omits the Sub-agents section when subagent_history is empty', async ({ page }) => {
  await mockBackend(page, {
    runs: [
      mockTerminalRun({ id: 'r-no-sub', task: 'No subs', subagent_history: [] }),
    ],
    start_run_response: { run_id: 'r-no-sub', status: 'done' },
  })
  await page.goto('/')
  await waitForAppShell(page)
  await submitAndWaitForActiveRun(page, 'r-no-sub')
  await expect(page.locator('#inspector-pane')).toContainText('Active run')
  await expect(page.locator('#inspector-pane .subagent-list')).toHaveCount(0)
})
