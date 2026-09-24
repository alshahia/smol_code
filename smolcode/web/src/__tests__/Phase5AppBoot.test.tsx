// Phase 5 (ADR 0040) items 1 and 2 -- H10 bootstrap effect + error split.
//
// H10 is the highest-value bug in this file: the bootstrap effect depends
// on refreshRuns, which is keyed on [activeRunId], so EVERY run selection
// re-runs getConfig() and re-applies c.provider / c.model over the user's
// composer selection.
//
// These tests stub global fetch rather than mocking the api module. The
// defect lives in the effect graph, so the test has to drive a real <App/>
// -- and stubbing at fetch keeps the real api module in the loop instead
// of replacing it with a hand-written double that can drift from it.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  addEventListener() {}
  removeEventListener() {}
  close() {}
  static reset() {
    FakeEventSource.instances = []
  }
}

const CONFIG = {
  workspace: 'C:/ws',
  executor: 'local',
  provider: 'srv-provider',
  model: 'srv-model',
  litellm_proxy: null,
  log_level: 'WARNING',
  tiers: [
    {
      name: 'restricted',
      uploads: 'none',
      network: 'none',
      max_steps: 12,
      timeout_s: 120,
      docker_image: 'smolcode:restricted',
      commands: [],
      imports: [],
    },
    {
      name: 'elevated',
      uploads: 'ws',
      network: 'none',
      max_steps: 20,
      timeout_s: 180,
      docker_image: 'smolcode:elevated',
      commands: [],
      imports: [],
    },
  ],
  uploads_dir: 'uploads',
  upload_max_bytes: 1048576,
  upload_allowed_mime: [],
}

const PROVIDERS = {
  providers: [
    {
      id: 'srv-provider',
      name: 'Server provider',
      key_state: 'set',
      model_count: 1,
      env_vars: [],
      default_model: 'srv-model',
      host_env_var: null,
    },
    {
      id: 'other-provider',
      name: 'Other provider',
      key_state: 'missing',
      model_count: 1,
      env_vars: [],
      default_model: 'other-model',
      host_env_var: null,
    },
  ],
}

function makeRun(id: string, status: string) {
  return {
    id,
    task: 'task ' + id,
    tier: 'restricted',
    status,
    started_at: 1,
    ended_at: status === 'running' ? null : 2,
    duration_s: null,
    result: null,
    error: null,
    has_pending_approval: false,
    touched_paths: [],
    tokens: { input: 1, output: 1, total: 2, cost_usd: 0.01 },
    step_count: 1,
    remaining_s: 60,
    subagent: null,
    session_id: null,
    project: null,
    effective_cwd: null,
    anchor_to_project_root: false,
    model: 'srv-model',
    provider: 'srv-provider',
    parent_retry_of: null,
    parent_rerun_of: null,
    retry_count: 0,
    context_window: null,
    snapshot_at: null,
    subagent_history: [],
    queue_position: null,
  }
}

const BODY = {
  '/api/config': CONFIG,
  '/api/projects': { projects: [] },
  '/api/providers': PROVIDERS,
  '/api/uploads': { uploads: [] },
  '/api/queue': { active: [], queued: [] },
  '/api/sessions': { sessions: [] },
  '/api/cost-caps': { caps: [], defaults: [] },
  '/api/usage-limits': { limits: {} },
  '/api/allowlist': { allowlist: {} },
  '/api/allowlist/check': { allowed: true },
  '/api/dashboard': {
    runs_today: 0,
    tokens_today: { input: 0, output: 0, total: 0, cost_usd: 0 },
    errors_today: 0,
    by_provider: {},
    sparkline: [],
    cost_estimate_usd_today: 0,
    generated_at: 0,
  },
  '/api/health': { status: 'ok', version: '0', uploads_dir: '', uploads_count: 0 },
  // These two MUST be present with the right shape. AuditPanel does
  // setEntries(r.entries) and then reads entries.length, so a bare {}
  // throws inside render and takes the whole App tree down -- which looks
  // exactly like "the app renders nothing".
  '/api/audit': { entries: [] },
  '/api/workspace/tree': { entries: [] },
}

let runs: unknown[] = [makeRun('r1', 'done')]
let failUploads = false
let failConfig = false
let uploadsCalls = 0

function installFetch() {
  vi.stubGlobal('fetch', (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : String((input as Request).url ?? input)
    const path = url.split('?')[0]
    if (path === '/api/config' && failConfig) {
      return Promise.reject(new Error('config fetch failed'))
    }
    if (path === '/api/uploads') {
      uploadsCalls++
      if (failUploads) return Promise.reject(new Error('uploads backend down'))
      return Promise.resolve(json({ uploads: [] }))
    }
    if (path === '/api/runs') return Promise.resolve(json({ runs }))
    // The snapshot endpoint (decision 0040). It must be handled BEFORE the
    // generic /api/runs/ catch-all below, and it must return a real
    // `events` array: EventStream does setEvents(snap.events) and then
    // iterates it, so a bare {} throws 'events is not iterable' and takes
    // the whole tree down.
    const snap = /^\/api\/runs\/([^/]+)\/events\/snapshot$/.exec(path)
    if (snap) {
      const run = (runs as Array<{ id: string; status: string }>).find((r) => r.id === snap[1])
      return Promise.resolve(json({ events: [], status: run ? run.status : 'done' }))
    }
    if (path in BODY) return Promise.resolve(json(BODY[path as keyof typeof BODY]))
    if (path.startsWith('/api/runs/')) return Promise.resolve(json({}))
    return Promise.resolve(json({}))
  })
}

function json(body: unknown) {
  return {
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(body)),
    json: () => Promise.resolve(body),
  }
}

let App: typeof import('../App').default

beforeEach(async () => {
  FakeEventSource.reset()
  window.localStorage.clear()
  runs = [makeRun('r1', 'done')]
  failUploads = false
  failConfig = false
  uploadsCalls = 0
  vi.stubGlobal('EventSource', FakeEventSource)
  installFetch()
  App = (await import('../App')).default
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function settle(ms = 120) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms))
  })
}

describe('ADR0040-1 H10 bootstrap runs exactly once', () => {
  it('does not reset the composer provider when the active run changes', async () => {
    const user = userEvent.setup()
    runs = [makeRun('r1', 'done'), makeRun('r2', 'done')]
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText(/model provider/i)).toBeTruthy())

    const select = screen.getByLabelText(/model provider/i) as HTMLSelectElement
    expect(select.value).toBe('srv-provider')

    // The user deliberately picks a different provider.
    await user.selectOptions(select, 'other-provider')
    await waitFor(() => expect((screen.getByLabelText(/model provider/i) as HTMLSelectElement).value).toBe('other-provider'))

    // Now the user selects the OTHER run. setActiveRunId fires, and because
    // refreshRuns closes over activeRunId the bootstrap effect re-ran:
    // getConfig() again, setSelectedProviderId(c.provider) again, and the
    // user's choice was stomped back to the server default.
    await user.click(await screen.findByText('task r2'))
    await settle(200)

    expect((screen.getByLabelText(/model provider/i) as HTMLSelectElement).value).toBe('other-provider')
  })
})

describe('ADR0040-2 error channels are separate', () => {
  it('a failing uploads fetch does NOT blank the app', async () => {
    failUploads = true
    render(<App />)
    await waitFor(() => expect(uploadsCalls).toBeGreaterThan(0))
    await settle()

    // The old behaviour: one shared error state replaced the whole app
    // with "Cannot reach the smolcode web server", so a failed background
    // refresh told the user the server was unreachable.
    expect(screen.queryByText(/cannot reach the smolcode web server/i)).toBeNull()
    expect(await screen.findByText('smolcode')).toBeTruthy()
  })

  it('a failing getConfig DOES show the fatal screen', async () => {
    failConfig = true
    render(<App />)
    expect(await screen.findByText(/cannot reach the smolcode web server/i)).toBeTruthy()
  })

  it('a transient error clears when the retry succeeds', async () => {
    const user = userEvent.setup()
    // Fail during boot: the uploads fetch is one of the boot fetches, and
    // there is no periodic uploads poll (only refreshRuns is on the 5s
    // timer), so the failure has to land on a real call.
    failUploads = true
    render(<App />)

    expect(await screen.findByText(/uploads backend down/i)).toBeTruthy()
    // The app is still usable underneath the banner.
    expect(await screen.findByLabelText(/model provider/i)).toBeTruthy()

    // The banner carries a Retry, which is the recovery path the user
    // actually has, and it must clear the banner on success.
    failUploads = false
    await user.click(screen.getByRole('button', { name: /retry/i }))
    await waitFor(() => {
      expect(screen.queryByText(/uploads backend down/i)).toBeNull()
    })
    // And the app is still fully rendered underneath.
    expect(screen.getByLabelText(/model provider/i)).toBeTruthy()
  })

  it('a transient error can be dismissed without retrying', async () => {
    const user = userEvent.setup()
    failUploads = true
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /dismiss error/i }))
    await waitFor(() => {
      expect(screen.queryByText(/uploads backend down/i)).toBeNull()
    })
  })
})
