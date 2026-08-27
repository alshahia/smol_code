// e2e test helpers for the smolcode web SPA (decision 0029).
//
// All new spec files use page.route('/api/**', ...) to mock the FastAPI
// backend, so the suite runs without a real smolcode server (the dev env
// has Docker down per TASKS.md §5). The 3-test smoke spec predates this
// helper and tolerates a missing backend via test.skip().
//
// Pattern in a spec file:
//
//   import { test, expect } from '@playwright/test'
//   import { mockBackend, waitForAppShell, mockTerminalRun } from './_helpers'
//
//   test('my feature', async ({ page }) => {
//     await mockBackend(page, {
//       runs: [mockTerminalRun({ id: 'r1', task: 'hello' })],
//     })
//     await page.goto('/')
//     await waitForAppShell(page)
//     await expect(page.getByRole('button', { name: 'r1' })).toBeVisible()
//   })

import type { Page, Route } from '@playwright/test'

// ---------- minimal type re-definitions (mirror api.ts) ---------------------

export interface MockConfig {
  workspace?: string
  provider?: string
  model?: string
  executor?: string
  log_level?: string
  litellm_proxy?: string | null
  tiers?: Array<{
    name: string
    uploads: string
    network: string
    max_steps: number
    timeout_s: number
    docker_image: string
    commands: string[]
    imports: string[]
  }>
}

export interface MockProvider {
  id: string
  name: string
  env_vars?: string[]
  default_model?: string
  key_state?: 'set' | 'missing'
  model_count?: number | null
  host_env_var?: string | null
  cached_at?: number | null
  cached_error?: string | null
}

export interface MockRunSummary {
  id: string
  task: string
  tier: string
  status:
    | 'pending'
    | 'running'
    | 'awaiting_approval'
    | 'paused'
    | 'queued'
    | 'done'
    | 'error'
    | 'stopped'
  started_at?: number
  ended_at?: number | null
  duration_s?: number | null
  result?: string | null
  error?: string | null
  has_pending_approval?: boolean
  touched_paths?: string[]
  tokens?: { input: number; output: number; total: number }
  step_count?: number
  remaining_s?: number | null
  subagent?: unknown | null
  subagent_history?: unknown[]
  snapshot_at?: number | null
  queue_position?: number | null
  session_id?: string | null
  project?: string | null
}

export interface MockQueueEntry {
  id: string
  task: string
  tier: string
  queued_at: number
  project: string | null
  session_id: string | null
  queue_position: number
}

export interface MockSession {
  id: string
  path: string
  size_bytes: number
  mtime_iso: string
  name: string | null
  run_count: number
  project: string | null
}

export interface MockProject {
  name: string
  root: string
}

export interface MockUpload {
  stored_name: string
  original_name: string
  size: number
  mime: string
  sha256: string
  tier: string
  ts: string
  uploaded_by: string
}

export interface MockAuditEntry {
  ts?: string
  event?: string
  tier?: string
  task?: string
  action?: string
  step?: number
  exit_code?: number | null
  duration_s?: number | null
  kind?: string
  message?: string
  decision_id?: string
  [k: string]: unknown
}

export interface MockDashboard {
  runs_today: number
  tokens_today: { input: number; output: number; total: number; cost_usd?: number }
  errors_today: number
  by_provider: Record<string, { input: number; output: number; total: number; cost_usd: number }>
  sparkline: number[]
  cost_estimate_usd_today: number
  generated_at: number
}

// ---------- default factories -----------------------------------------------

export function defaultMockConfig(overrides: MockConfig = {}): Record<string, unknown> {
  return {
    workspace: overrides.workspace ?? '/tmp/smolcode-ws',
    executor: overrides.executor ?? 'docker',
    provider: overrides.provider ?? 'anthropic',
    model: overrides.model ?? 'claude-sonnet-4-5',
    litellm_proxy: overrides.litellm_proxy ?? null,
    log_level: overrides.log_level ?? 'info',
    tiers: overrides.tiers ?? [
      {
        name: 'restricted',
        uploads: 'workspace',
        network: 'blocked',
        max_steps: 20,
        timeout_s: 600,
        docker_image: 'smolcode/restricted:latest',
        commands: ['python', 'pytest', 'git', 'npm'],
        imports: ['json', 'pathlib', 'ast', 're', 'textwrap'],
      },
      {
        name: 'elevated',
        uploads: 'workspace',
        network: 'restricted',
        max_steps: 40,
        timeout_s: 1200,
        docker_image: 'smolcode/elevated:latest',
        commands: ['python', 'pytest', 'git', 'npm', 'curl'],
        imports: ['json', 'pathlib', 'ast', 're', 'textwrap', 'urllib'],
      },
      {
        name: 'orchestrator',
        uploads: 'workspace',
        network: 'restricted',
        max_steps: 60,
        timeout_s: 1800,
        docker_image: 'smolcode/orchestrator:latest',
        commands: ['python', 'pytest', 'git', 'npm', 'curl'],
        imports: ['json', 'pathlib', 'ast', 're', 'textwrap'],
      },
      {
        name: 'full_access',
        uploads: 'workspace',
        network: 'open',
        max_steps: 100,
        timeout_s: 3600,
        docker_image: 'smolcode/full:latest',
        commands: ['python', 'pytest', 'git', 'npm', 'curl', 'ssh'],
        imports: ['json', 'pathlib', 'ast', 're', 'textwrap', 'urllib'],
      },
    ],
    uploads_dir: '/tmp/smolcode-uploads',
    upload_max_bytes: 25 * 1024 * 1024,
    upload_allowed_mime: ['text/plain', 'application/json', 'text/markdown'],
  }
}

export function defaultMockProviders(extra: MockProvider[] = []): MockProvider[] {
  return [
    {
      id: 'anthropic',
      name: 'Anthropic',
      env_vars: ['ANTHROPIC_API_KEY'],
      default_model: 'claude-sonnet-4-5',
      key_state: 'set',
      model_count: 12,
      host_env_var: 'ANTHROPIC_API_KEY',
      cached_at: Math.floor(Date.now() / 1000),
      cached_error: null,
    },
    ...extra,
  ]
}

export function defaultMockDashboard(overrides: Partial<MockDashboard> = {}): MockDashboard {
  return {
    runs_today: 0,
    tokens_today: { input: 0, output: 0, total: 0, cost_usd: 0 },
    errors_today: 0,
    by_provider: {},
    sparkline: Array(24).fill(0),
    cost_estimate_usd_today: 0,
    generated_at: Math.floor(Date.now() / 1000),
    ...overrides,
  }
}

export function mockTerminalRun(overrides: Partial<MockRunSummary> = {}): MockRunSummary {
  const started = Math.floor(Date.now() / 1000) - 30
  return {
    id: overrides.id ?? 'run-terminal-1',
    task: overrides.task ?? 'Write a haiku',
    tier: overrides.tier ?? 'restricted',
    status: overrides.status ?? 'done',
    started_at: overrides.started_at ?? started,
    ended_at: overrides.ended_at ?? started + 25,
    duration_s: overrides.duration_s ?? 25,
    result: overrides.result ?? 'Cherry blossoms fall / silently at dawn / the river runs slow',
    error: overrides.error ?? null,
    has_pending_approval: overrides.has_pending_approval ?? false,
    touched_paths: overrides.touched_paths ?? [],
    tokens: overrides.tokens ?? { input: 1200, output: 80, total: 1280 },
    step_count: overrides.step_count ?? 4,
    remaining_s: overrides.remaining_s ?? null,
    subagent: overrides.subagent ?? null,
    subagent_history: overrides.subagent_history ?? [],
    snapshot_at: overrides.snapshot_at ?? null,
    queue_position: overrides.queue_position ?? null,
    session_id: overrides.session_id ?? null,
    project: overrides.project ?? null,
  }
}

export function mockRunningRun(overrides: Partial<MockRunSummary> = {}): MockRunSummary {
  return {
    id: overrides.id ?? 'run-running-1',
    task: overrides.task ?? 'Computing the answer',
    tier: overrides.tier ?? 'restricted',
    status: overrides.status ?? 'running',
    started_at: overrides.started_at ?? Math.floor(Date.now() / 1000) - 5,
    ended_at: overrides.ended_at ?? null,
    duration_s: overrides.duration_s ?? 5,
    result: overrides.result ?? null,
    error: overrides.error ?? null,
    has_pending_approval: overrides.has_pending_approval ?? false,
    touched_paths: overrides.touched_paths ?? [],
    tokens: overrides.tokens ?? { input: 800, output: 40, total: 840 },
    step_count: overrides.step_count ?? 3,
    remaining_s: overrides.remaining_s ?? 595,
    subagent: overrides.subagent ?? null,
    subagent_history: overrides.subagent_history ?? [],
    snapshot_at: overrides.snapshot_at ?? null,
    queue_position: overrides.queue_position ?? null,
    session_id: overrides.session_id ?? null,
    project: overrides.project ?? null,
  }
}

// Mock a sub-agent invocation history for SubAgentList tests.
// Decision 0028 made cost_usd + specialist + tokens_in/out additive defaults.
export function mockSubAgentHistory(): unknown[] {
  return [
    {
      id: 'sub-1',
      tier: 'restricted',
      specialist: 'planner',
      started_at: Math.floor(Date.now() / 1000) - 30,
      ended_at: Math.floor(Date.now() / 1000) - 22,
      tokens_in: 2400,
      tokens_out: 180,
      cost_usd: 0.0029,
    },
    {
      id: 'sub-2',
      tier: 'restricted',
      specialist: 'researcher',
      started_at: Math.floor(Date.now() / 1000) - 21,
      ended_at: Math.floor(Date.now() / 1000) - 10,
      tokens_in: 1800,
      tokens_out: 220,
      cost_usd: 0.0022,
    },
  ]
}

// ---------- backend mock installer -----------------------------------------

export interface BackendMock {
  config?: MockConfig | Record<string, unknown>
  providers?: MockProvider[]
  runs?: MockRunSummary[]
  queue?: { active: MockRunSummary[]; queued: MockQueueEntry[] }
  sessions?: MockSession[]
  uploads?: MockUpload[]
  audit?: MockAuditEntry[]
  dashboard?: MockDashboard
  workspace_tree?: { entries: unknown[] }
  start_run_response?: { run_id: string; status: string }
  retry_response?: { run_id: string; status: string }
  rerun_response?: { run_id: string; status: string }
  export_response?: unknown
  stop_response?: { stopped: boolean }
  auto_approve_response?: { enabled: boolean }
  cancel_queue_response?: { run_id: string; cancelled: boolean }
  move_queue_response?: { run_id: string; position: number; queue: MockQueueEntry[] }
  /** decision 0032: GET /api/cost-caps mock body. */
  cost_caps_response?: {
    caps: Array<{ provider: string; cap_usd: number }>
    defaults: Array<{ provider: string; cap_usd: number }>
    providers: string[]
    current_spend_usd: Record<string, number>
  }
  /** decision 0032: PUT /api/cost-caps mock body. */
  cost_caps_put_response?: {
    caps: Array<{ provider: string; cap_usd: number }>
    defaults: Array<{ provider: string; cap_usd: number }>
    providers: string[]
    current_spend_usd: Record<string, number>
    updated_at: number
  }
  approval_response?: { decided: boolean }
  upload_response?: MockUpload
  delete_upload_response?: { deleted: string }
  pause_response?: { run_id: string; paused: boolean }
  resume_response?: { run_id: string; resumed: boolean }
  health_response?: { status: string; version: string; uploads_dir: string; uploads_count: number }
  /** When set, GET /api/config returns 500 to drive the error screen. */
  fail_config?: boolean
  /** When set, GET /api/config never resolves to drive the loading screen. */
  hang_config?: boolean
  /** Per-endpoint artificial delay (ms) so busy / in-flight UI states are observable. */
  delays?: {
    start_run?: number
    retry?: number
    rerun?: number
    stop?: number
    auto_approve?: number
    approval?: number
    export?: number
    move_queue?: number
    cost_caps?: number
  }
  /** Phase 4 (decision 0037): projects list mocked for /api/projects. */
  projects?: MockProject[]
  /** Capture all POST/PUT/DELETE bodies for assertion. */
  capturedRequests?: { method: string; url: string; body?: string }[]
}

/**
 * Install page.route handlers that mock the smolcode backend.
 * Must be called BEFORE page.goto() so the SPA's mount-time fetches see
 * the mocks.
 */
export async function mockBackend(page: Page, opts: BackendMock = {}): Promise<void> {
  const captured = opts.capturedRequests ?? []

  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const method = req.method()
    const url = req.url()
    // Helper: per-endpoint artificial delay (ms) so busy UI states are observable.
    const sleep = (ms: number) => (ms > 0 ? new Promise<void>((r) => setTimeout(r, ms)) : Promise.resolve())
    // Skip SSE endpoints: hand off to the next matching route (e.g. mockSSE).
    // Playwright's route.fallback() lets later-registered routes handle the request.
    let earlyPath: string
    try {
      earlyPath = new URL(url, 'http://x').pathname
    } catch {
      earlyPath = url.split('?')[0]
    }
    if (/^\/api\/runs\/[^/]+\/events$/.test(earlyPath)) {
      console.log('[mockBackend] skipping SSE:', earlyPath)
      await route.fallback()
      return
    }
    let body: string | undefined
    try {
      const raw = req.postData()
      if (raw) body = raw
    } catch {
      /* GET has no body */
    }
    captured.push({ method, url, body })

    let pathname: string
    try {
      pathname = new URL(url, 'http://x').pathname
    } catch {
      await route.fulfill({ status: 404, contentType: 'application/json', body: 'unmocked' })
      return
    }

    // ---------- drives the error screen on config failure ----------
    if (pathname === '/api/config' && opts.fail_config) {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'mock failure' }) })
      return
    }
    if (pathname === '/api/config' && opts.hang_config) {
      // never resolves -> SPA shows the Loading screen
      return
    }

    // ---------- GET routes ----------
    if (method === 'GET') {
      if (pathname === '/api/health') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(
            opts.health_response ?? { status: 'ok', version: '1.9.0', uploads_dir: '/tmp', uploads_count: 0 },
          ),
        })
        return
      }
      if (pathname === '/api/config') {
        // Merge any partial config overrides on top of the default factory
        // so callers can override workspace / provider / model without losing
        // the tiers / uploads_dir / upload_max_bytes that the SPA reads.
        const merged = { ...defaultMockConfig(), ...(opts.config as MockConfig ?? {}) }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(merged),
        })
        return
      }
      if (pathname === '/api/providers') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ providers: opts.providers ?? defaultMockProviders() }),
        })
        return
      }
      if (pathname === '/api/runs') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ runs: opts.runs ?? [] }),
        })
        return
      }
      if (pathname === '/api/queue') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.queue ?? { active: [], queued: [] }),
        })
        return
      }
      if (pathname === '/api/uploads' || pathname === '/api/uploads/') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ uploads: opts.uploads ?? [] }),
        })
        return
      }
      if (pathname === '/api/audit') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            entries: opts.audit ?? [],
            total: opts.audit?.length ?? 0,
            truncated: false,
            note: null,
            chain: null,
          }),
        })
        return
      }
      if (pathname === '/api/dashboard') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.dashboard ?? defaultMockDashboard()),
        })
        return
      }
      // decision 0032: GET /api/cost-caps
      if (pathname === '/api/cost-caps') {
        await sleep(opts.delays?.cost_caps ?? 0)
        const resp = opts.cost_caps_response ?? {
          caps: [],
          defaults: [],
          providers: [],
          current_spend_usd: {},
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(resp),
        })
        return
      }
      if (pathname === '/api/workspace/tree') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.workspace_tree ?? { entries: [] }),
        })
        return
      }
      if (pathname === '/api/projects') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ projects: opts.projects ?? [] }),
        })
        return
      }
      // /api/sessions?project=...  (the FE calls /api/sessions with optional
      // ?project= query; not nested under /api/projects/...)
      if (pathname === '/api/sessions') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ sessions: opts.sessions ?? [] }),
        })
        return
      }
      // /api/runs/{id}/export
      if (pathname.match(/^\/api\/runs\/[^/]+\/export$/)) {
        await sleep(opts.delays?.export ?? 0)
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.export_response ?? {
            summary: opts.runs?.[0] ?? mockTerminalRun(),
            events: [],
            subagent_history: [],
            exported_at: Math.floor(Date.now() / 1000),
            schema_version: 1,
          }),
        })
        return
      }
      // /api/runs/{id}
      if (pathname.match(/^\/api\/runs\/[^/]+$/)) {
        const id = pathname.split('/').pop()
        const found = opts.runs?.find((r) => r.id === id)
        await route.fulfill({
          status: found ? 200 : 404,
          contentType: 'application/json',
          body: JSON.stringify(found ?? { detail: 'not found' }),
        })
        return
      }
    }

    // ---------- POST / DELETE routes ----------

    if (method === 'POST') {
      if (pathname === '/api/runs') {
        await sleep(opts.delays?.start_run ?? 0)
        const resp = opts.start_run_response ?? { run_id: 'run-new-1', status: 'running' }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resp) })
        return
      }
      if (pathname.match(/^\/api\/runs\/[^/]+\/retry$/)) {
        await sleep(opts.delays?.retry ?? 0)
        const resp = opts.retry_response ?? { run_id: 'run-retry-1', status: 'running' }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resp) })
        return
      }
      if (pathname.match(/^\/api\/runs\/[^/]+\/rerun$/)) {
        await sleep(opts.delays?.rerun ?? 0)
        const resp = opts.rerun_response ?? { run_id: 'run-rerun-1', status: 'running' }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resp) })
        return
      }
      if (pathname.match(/^\/api\/runs\/[^/]+\/stop$/)) {
        await sleep(opts.delays?.stop ?? 0)
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.stop_response ?? { stopped: true }),
        })
        return
      }
      if (pathname.match(/^\/api\/runs\/[^/]+\/auto-approve$/)) {
        await sleep(opts.delays?.auto_approve ?? 0)
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.auto_approve_response ?? { enabled: true }),
        })
        return
      }
      if (pathname.match(/^\/api\/runs\/[^/]+\/pause$/)) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.pause_response ?? { run_id: 'x', paused: true }),
        })
        return
      }
      if (pathname.match(/^\/api\/runs\/[^/]+\/resume$/)) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.resume_response ?? { run_id: 'x', resumed: true }),
        })
        return
      }
      if (pathname.match(/^\/api\/runs\/[^/]+\/approval$/) && req.method() === 'POST') {
        await sleep(opts.delays?.approval ?? 0)
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.approval_response ?? { resolved: true, decision_id: 'd-1' }),
        })
        return
      }
      if (pathname === '/api/uploads' || pathname === '/api/uploads/') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.upload_response ?? {
            stored_name: 'upload-mock.txt',
            original_name: 'mock.txt',
            size: 12,
            mime: 'text/plain',
            sha256: 'a'.repeat(64),
            tier: 'restricted',
            ts: new Date().toISOString(),
            uploaded_by: 'tester',
          }),
        })
        return
      }
      // Phase 4 F4 (decision 0037): POST /api/projects creates a project.
      if (pathname === '/api/projects') {
        let parsed: { name?: string; root?: string } = {}
        try { parsed = body ? JSON.parse(body) : {} } catch {
          await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'bad json' }) })
          return
        }
        const name = parsed.name ?? ''
        if (!name) {
          await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'project name is required' }) })
          return
        }
        const existing = opts.projects ?? []
        if (existing.some((p) => p.name === name)) {
          await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'project name already exists: ' + name }) })
          return
        }
        const newProj: MockProject = { name, root: parsed.root || '/default/' + name }
        await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(newProj) })
        return
      }
    }
    if (method === 'DELETE') {
      if (pathname.match(/^\/api\/queue\/[^/]+$/)) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.cancel_queue_response ?? { run_id: 'x', cancelled: true }),
        })
        return
      }
      if (pathname.match(/^\/api\/uploads\/[^/]+$/)) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.delete_upload_response ?? { deleted: 'x' }),
        })
        return
      }
      // Phase 4 F4 (decision 0037): DELETE /api/projects/{name} removes.
      if (pathname.match(/^\/api\/projects\/[^/]+$/)) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ deleted: decodeURIComponent(pathname.split('/').pop() ?? '') }),
        })
        return
      }
    }
    if (method === 'PUT') {
      // decision 0032: PUT /api/cost-caps replaces the caps registry
      if (pathname === '/api/cost-caps') {
        await sleep(opts.delays?.cost_caps ?? 0)
        let parsed: { caps?: Record<string, number> } = {}
        try {
          parsed = body ? JSON.parse(body) : {}
        } catch {
          await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'bad json' }) })
          return
        }
        const capEntries = Object.entries(parsed.caps ?? {})
          .filter(([, v]) => typeof v === 'number' && v > 0)
          .map(([provider, v]) => ({ provider, cap_usd: v }))
        const resp = opts.cost_caps_put_response ?? {
          caps: capEntries,
          defaults: capEntries,
          providers: capEntries.map((c) => c.provider),
          current_spend_usd: {},
          updated_at: Math.floor(Date.now() / 1000),
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(resp),
        })
        return
      }
    }
    if (method === 'PATCH') {
      // Decision 0031: PATCH /api/queue/{id} reorders a queued entry.
      // The default response just echoes the run_id and a 1-based
      // position so the FE patches local state; the spec supplies
      // ``move_queue_response`` when it wants to drive the queue
      // back into a specific shape.
      if (pathname.match(/^\/api\/queue\/[^/]+$/)) {
        await sleep(opts.delays?.move_queue ?? 0)
        const id = pathname.split('/').pop() ?? ''
        const fallback = {
          run_id: id,
          position: 1,
          queue: opts.queue?.queued ?? [],
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(opts.move_queue_response ?? fallback),
        })
        return
      }
    }

    // ---------- catch-all: 404 to keep tests deterministic ----------
    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'unmocked: ' + method + ' ' + pathname }) })
  })
}

/**
 * Wait for the SPA to render past the loading screen.
 * Resolves once .app is in the DOM (the 3-pane layout).
 * Throws if the error screen appears.
 */
export async function waitForAppShell(page: Page): Promise<void> {
  await page.locator('.app').waitFor({ state: 'visible', timeout: 15000 })
}

/** Wait for the error screen (drives negative tests). */
export async function waitForErrorScreen(page: Page): Promise<void> {
  await page.locator('.error-screen').waitFor({ state: 'visible', timeout: 15000 })
}

/** Wait for the loading screen. */
export async function waitForLoadingScreen(page: Page): Promise<void> {
  await page.locator('.loading').waitFor({ state: 'visible', timeout: 5000 })
}

// ---------- SSE mock for live event tests ---------------------------------

/**
 * Mock the SSE endpoint /api/runs/{id}/events.
 * Fires the given events exactly once on first connection, then returns
 * keep-alive frames so EventSource doesn't error-out.
 *
 * Mirrors the real BE format (runs.py:_encode_event): each frame sets
 * the `event:` line followed by `data:` JSON. Decision 0030 changed
 * the SPA to dispatch via addEventListener(<type>, ...) so named
 * events now reach the handler.
 *
 * Common usage:
 *
 *   await mockSSE(page, [
 *     { event: 'approval.requested', data: { decision_id: 'd1', tool: 'shell', ... } },
 *   ])
 */
export async function mockSSE(
  page: Page,
  events: Array<{ type: string; data: Record<string, unknown>; id?: string }>,
): Promise<void> {
  let fired = false
  await page.route('**/api/runs/*/events', async (route: Route) => {
    if (fired) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: ': keep-alive\n\n',
      })
      return
    }
    fired = true
    const body = events
      .map((e) => {
        const lines: string[] = []
        if (e.id) lines.push('id: ' + e.id)
        // Set the `event:` line so EventSource dispatches to the typed
        // addEventListener handler registered by EventStream.tsx.
        lines.push('event: ' + e.type)
        lines.push('data: ' + JSON.stringify(e.data))
        lines.push('')
        lines.push('')
        return lines.join('\n')
      })
      .join('')
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    })
  })
}

/** Accept all browser dialogs (window.confirm/alert/prompt). */
export function acceptDialogs(page: Page): void {
  page.on('dialog', (d) => {
    void d.accept().catch(() => {})
  })
}

