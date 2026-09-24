// Phase 5 (ADR 0040) -- frontend correctness, test-first.
//
// Every test in this file asserts a behaviour the code does NOT have yet.
// The pre-fix failure is the point: Phase 3 made the frontend build and
// Phase 4 fixed the backend, but none of these six defects produce a
// type error, a lint warning, or a failed test, because each is a
// behavioural bug in a component that compiles cleanly against a type it
// supplies itself.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ApprovalModal, type PendingApproval } from '../components/ApprovalModal'
import { Inspector } from '../components/Inspector'
import { retryRun, rerunRun, exportRun } from '../api'

// ---------------------------------------------------------------------
// 3. ApprovalModal -- edited diff leaks across decisions
// ---------------------------------------------------------------------

// DiffViewer renders "Empty diff" unless hunks or rawDiff is present,
// and the textarea only appears after the user clicks "Edit proposed
// content". Both are required for the test to reach the leak.
const HUNKS = [{ op: 'replace' as const, before: ['original A'], after: ['ORIGINAL A'] }]
const STATS = { added: 1, removed: 1, same: 0, changed: true }

const DIFF_A: PendingApproval = {
  decisionId: 'd-A',
  tool: 'write_file',
  args: {},
  summary: 'write file a',
  kind: 'diff',
  relPath: 'a.txt',
  before: 'original A',
  after: 'ORIGINAL A',
  hunks: HUNKS,
  stats: STATS,
}

const DIFF_B: PendingApproval = {
  decisionId: 'd-B',
  tool: 'write_file',
  args: {},
  summary: 'write file b',
  kind: 'diff',
  relPath: 'b.txt',
  before: 'original B',
  after: 'ORIGINAL B',
  hunks: [{ op: 'replace' as const, before: ['original B'], after: ['ORIGINAL B'] }],
  stats: STATS,
}

describe('ADR0040-3 ApprovalModal edit isolation', () => {
  it('resets the edited diff when the decisionId changes', async () => {
    // A: user edits the diff and applies it. B: a different decision
    // arrives WITHOUT any editing. B must show its own original, not
    // A's edit.
    const onDecide = vi.fn()
    const { rerender } = render(<ApprovalModal pending={DIFF_A} onDecide={onDecide} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /edit proposed content/i }))
    const editorA = screen.getByLabelText('Edit proposed file content')
    await user.clear(editorA)
    await user.type(editorA, 'TAMPERED BY USER')
    await user.click(screen.getByRole('button', { name: /apply edit/i }))
    // ApprovalModal renders "Apply + Approve" exactly when editedAfter
    // is non-null. That label is the observable leak: if the state is
    // not reset, B inherits A's edit and the user approves content they
    // never reviewed.
    expect(screen.getByRole('button', { name: /apply . approve/i })).toBeTruthy()

    rerender(<ApprovalModal pending={DIFF_B} onDecide={onDecide} />)

    // B must be back to a clean "Approve" -- no inherited edit.
    expect(screen.queryByRole('button', { name: /apply . approve/i })).toBeNull()
    expect(screen.getByRole('button', { name: /^approve$/i })).toBeTruthy()

    // And approving B must not submit A's edited text.
    await user.click(screen.getByRole('button', { name: /^approve$/i }))
    expect(onDecide).toHaveBeenLastCalledWith(true, 'user-approved', null)
  })

  it('does not carry edits through the outside_root dismiss paths', async () => {
    // outsideDeny / outsideApproveOnce / outsideApproveSessionForPath
    // never called setEditedAfter(null). Verify the approve payload is
    // null (no stale edit) after an outside_root dismissal.
    const outside: PendingApproval = {
      decisionId: 'd-out',
      tool: 'write_file',
      args: {},
      summary: 'outside root',
      kind: 'outside_root',
      absoluteTarget: 'C:/elsewhere/x.txt',
      effectiveCwd: 'C:/ws',
    }
    const onDecide = vi.fn()
    const { rerender } = render(<ApprovalModal pending={outside} onDecide={onDecide} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /^deny$/i }))

    // Same component instance, now a diff decision: the edit must be null.
    rerender(<ApprovalModal pending={DIFF_B} onDecide={onDecide} />)
    await user.click(screen.getByRole('button', { name: /^apply \+ approve$|^approve$/i }))
    expect(onDecide).toHaveBeenLastCalledWith(true, 'user-approved', null)
  })

  it('Escape denies the pending decision', async () => {
    const onDecide = vi.fn()
    render(<ApprovalModal pending={PENDING_DESTRUCTIVE} onDecide={onDecide} />)
    const user = userEvent.setup()
    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(onDecide).toHaveBeenCalledWith(false, 'user-denied', null)
    })
  })

  it('traps focus inside the dialog', async () => {
    render(<ApprovalModal pending={PENDING_DESTRUCTIVE} onDecide={vi.fn()} />)
    await waitFor(() => {
      const dialog = screen.getByRole('dialog')
      expect(dialog.contains(document.activeElement)).toBe(true)
    })
  })
})

const PENDING_DESTRUCTIVE: PendingApproval = {
  decisionId: 'd-1',
  tool: 'shell',
  args: { cmd: 'rm -rf /' },
  summary: 'destructive tool',
  kind: 'destructive',
}

// ---------------------------------------------------------------------
// 5. Inspector -- countdown drift + missing cost
// ---------------------------------------------------------------------

function makeConfig(timeoutS: number) {
  return {
    workspace: 'C:/ws',
    executor: 'local',
    provider: 'opencode-go',
    model: 'm',
    litellm_proxy: null,
    log_level: 'WARNING',
    tiers: [
      {
        name: 'restricted',
        uploads: 'none',
        network: 'none',
        max_steps: 12,
        timeout_s: timeoutS,
        docker_image: 'smolcode:restricted',
        commands: [],
        imports: [],
      },
    ],
    uploads_dir: 'uploads',
    upload_max_bytes: 1024,
    upload_allowed_mime: [],
  } as unknown as Parameters<typeof Inspector>[0]['config']
}

const RUNNING_RUN = {
  id: 'r1',
  task: 't',
  tier: 'restricted',
  status: 'running',
  started_at: 1,
  ended_at: null,
  duration_s: null,
  result: null,
  error: null,
  has_pending_approval: false,
  touched_paths: [],
  tokens: { input: 10, output: 5, total: 15, cache_hit: 0, current_input: 0, current_output: 0, last_step_at: null, cost_usd: 0.42 },
  step_count: 1,
  remaining_s: 100,
  subagent: null,
  session_id: null,
  project: null,
  effective_cwd: null,
  anchor_to_project_root: false,
  model: 'm',
  provider: 'opencode-go',
  parent_retry_of: null,
  parent_rerun_of: null,
  retry_count: 0,
  context_window: null,
  snapshot_at: null,
  subagent_history: [],
  queue_position: null,
} as unknown as NonNullable<Parameters<typeof Inspector>[0]['activeRun']>

describe('ADR0040-5 Inspector countdown + cost', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('resets the countdown when the server remaining_s changes', () => {
    // Server says 100. Tick 10s locally -> the display shows 90 (01:30).
    // The server then refreshes to 95, which is the new authoritative
    // base. nowTick must re-seed to 0 so the display is 95 (01:35).
    //
    // Without the reset it would read 95 - 10 = 85 (01:25), and the error
    // would grow for as long as the run stayed open.
    const { rerender } = render(
      <Inspector activeRun={RUNNING_RUN} config={makeConfig(120)} />,
    )
    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    // 100s - 10 ticks = 90s = 01:30
    expect(screen.getByText('01:30')).toBeTruthy()

    rerender(
      <Inspector
        activeRun={{ ...RUNNING_RUN, remaining_s: 95 } as typeof RUNNING_RUN}
        config={makeConfig(120)}
      />,
    )
    // 95s from a re-seeded counter = 01:35, NOT 01:25.
    expect(screen.getByText('01:35')).toBeTruthy()
  })

  it('falls back to the tier timeout_s, not the hardcoded 900', () => {
    // The run has no remaining_s. The tier says 120. The old code
    // rendered 900 (15:00).
    const run = { ...RUNNING_RUN, remaining_s: null }
    render(<Inspector activeRun={run as typeof RUNNING_RUN} config={makeConfig(120)} />)
    expect(screen.getByText('02:00')).toBeTruthy()
    expect(screen.queryByText('15:00')).toBeNull()
  })

  it('renders the per-run cost from cost_usd', () => {
    render(<Inspector activeRun={RUNNING_RUN} config={makeConfig(120)} />)
    // 0.42 -> the badge must show a dollar figure derived from cost_usd.
    expect(screen.getByText(/\$0\.42/)).toBeTruthy()
  })

  it('shows a placeholder rather than a misleading $0.00 when cost_usd is null', () => {
    // An unpriced provider must not render $0.00, which reads as
    // 'this run was free' rather than 'we do not know what it cost'.
    const run = {
      ...RUNNING_RUN,
      tokens: { ...RUNNING_RUN.tokens, cost_usd: null },
    }
    render(<Inspector activeRun={run as typeof RUNNING_RUN} config={makeConfig(120)} />)
    const badge = screen.getByTestId('cost-badge')
    expect(badge.textContent).toBe('--')
    expect(badge.textContent).not.toBe('$0.00')
  })
})

// ---------------------------------------------------------------------
// 6. api.ts -- URL encoding and empty retry body
// ---------------------------------------------------------------------

describe('ADR0040-6 api URL encoding + empty body', () => {
  const fetchSpy = vi.fn()
  beforeEach(() => {
    fetchSpy.mockReset()
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ run_id: 'x', status: 'running' }),
    })
    vi.stubGlobal('fetch', fetchSpy)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const ODD = 'weird/id?x=1&y=2'

  it('encodes the retry run id', async () => {
    await retryRun(ODD)
    const url = String(fetchSpy.mock.calls[0][0])
    expect(url).toBe('/api/runs/' + encodeURIComponent(ODD) + '/retry')
  })

  it('encodes the rerun run id', async () => {
    await rerunRun(ODD)
    const url = String(fetchSpy.mock.calls[0][0])
    expect(url).toBe('/api/runs/' + encodeURIComponent(ODD) + '/rerun')
  })

  it('encodes the export run id', async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        summary: {},
        events: [],
        subagent_history: [],
        exported_at: 0,
        schema_version: 1,
      }),
    })
    await exportRun(ODD)
    const url = String(fetchSpy.mock.calls[0][0])
    expect(url).toBe('/api/runs/' + encodeURIComponent(ODD) + '/export')
  })

  it('sends NO body when retry has no overrides', async () => {
    // The backend's inherit-from-parent path must be unambiguous.
    await retryRun('r1')
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    expect(init.body).toBeUndefined()
  })

  it('still sends a body when retry HAS overrides', async () => {
    await retryRun('r1', { tier: 'elevated' })
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    expect(init.body).toBe(JSON.stringify({ tier: 'elevated' }))
  })
})
