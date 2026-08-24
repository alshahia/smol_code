// API client for smolcode web SPA (M8 + M9).
// Calls are same-origin: /api/* via Vite proxy in dev, FastAPI in prod.

export interface TierSummary {
  name: string
  uploads: string
  network: string
  max_steps: number
  timeout_s: number
  docker_image: string
  commands: string[]
  imports: string[]
}

export interface HealthResponse {
  status: 'ok' | string
  version: string
  uploads_dir: string
  uploads_count: number
}

export interface ConfigResponse {
  workspace: string
  executor: string
  provider: string
  model: string
  litellm_proxy: string | null
  log_level: string
  tiers: TierSummary[]
  uploads_dir: string
  upload_max_bytes: number
  upload_allowed_mime: string[]
}

export interface UploadMetadata {
  stored_name: string
  original_name: string
  size: number
  mime: string
  sha256: string
  tier: string
  ts: string
  uploaded_by: string
}

export interface UploadListResponse {
  uploads: UploadMetadata[]
}

export interface AllowlistCheckResponse {
  allowed: boolean
  reason: string
}

// --- M11 types: provider + model catalog ---------------------------------

export interface ProviderInfo {
  id: string
  name: string
  env_vars: string[]
  default_model: string
  /** "set" if any required env var is populated in the server process; else "missing". */
  key_state: 'set' | 'missing'
  model_count: number | null
  host_env_var: string | null
  /**
   * Epoch seconds of the most recent model-list fetch for this provider,
   * or null if no fetch has happened yet (M12, decision 0015). Used by
   * <ModelAgeBadge> to render a "just now" / "Nm ago" chip.
   * Older servers (pre-M12) omit the field; treat undefined as null.
   */
  cached_at?: number | null
  /**
   * Short single-line error from the most recent failed fetch, or null
   * (M12.4). When set, <ModelAgeBadge> renders a warning-style chip so
   * the user knows the cached list may be stale. Older servers (pre-M12.4)
   * omit the field; treat undefined as null.
   */
  cached_error?: string | null
}

export interface ProviderListResponse {
  providers: ProviderInfo[]
}

export interface ModelInfo {
  id: string
  name?: string | null
  [k: string]: unknown
}

export interface ModelListResponse {
  provider: string
  models: ModelInfo[]
  cached: boolean
  fetched_at: number
  error?: string | null
}

export async function listProviders(): Promise<ProviderListResponse> {
  return jsonOrThrow(await fetch('/api/providers'))
}

export async function listProviderModels(
  providerId: string,
  refresh: boolean = false,
): Promise<ModelListResponse> {
  const q = refresh ? '?refresh=1' : ''
  return jsonOrThrow(
    await fetch(
      '/api/providers/' + encodeURIComponent(providerId) + '/models' + q,
    ),
  )
}

export interface StartRunOptions {
  provider?: string | null
  model?: string | null
  /** Map of env-var-name → API-key-value. The backend only accepts whitelisted names. */
  keys?: Record<string, string>
}

// --- M9 types -------------------------------------------------------------

// Phase 0 (decision 0025): per-run token aggregates.
export interface TokenSummary {
  input: number
  output: number
  total: number
}

// Phase 0 (decision 0025): latest sub-agent invocation.
export interface SubAgentSummary {
  id: string
  tier: string
  started_at: number
  ended_at: number | null
}

export interface RunSummary {
  id: string
  task: string
  tier: string
  status:
    | 'pending'
    | 'running'
    | 'awaiting_approval'
    | 'done'
    | 'error'
    | 'stopped'
  started_at: number
  ended_at: number | null
  duration_s: number | null
  result: string | null
  error: string | null
  has_pending_approval: boolean
  // M10: workspace-relative paths the run has touched (write_file +
  // patch_file). The workspace tree highlights these.
  touched_paths?: string[]
  // Phase 0 (decision 0025): aggregated tokens + step counter for
  // the Inspector Token usage section.
  tokens?: TokenSummary
  step_count?: number
  // Seconds remaining until _MAX_RUN_WALL_S expires. Negative when
  // the run has overrun the budget; null when the budget is disabled
  // or the server has not reported it (pre-v1.8 servers).
  remaining_s?: number | null
  // Latest sub-agent invocation. null when the run has not delegated.
  subagent?: SubAgentSummary | null
}

export interface RunListResponse {
  runs: RunSummary[]
}

export interface RunStartResponse {
  run_id: string
  status: string
}

export interface StreamEvent {
  type:
    | 'run.started'
    | 'run.ended'
    | 'plan.step'
    | 'step.action'
    | 'step.final_answer'
    | 'approval.requested'
    | 'approval.decided'
    | 'diff.proposed'
    | 'diff.resolved'
    | 'error'
    | 'subagent.started'
    | 'subagent.ended'
    | 'end'
  run_id?: string
  task?: string
  tier?: string
  model?: string
  provider?: string
  workspace?: string
  status?: string
  exit_code?: number
  duration_s?: number
  result?: string | null
  error?: string | null
  kind?: string
  message?: string
  ts?: string
  step_number?: number | null
  thought?: string
  code_action?: string
  tool_calls?: { name: string; id: string; args: Record<string, unknown> }[]
  observations?: string
  is_final_answer?: boolean
  timing_ms?: number
  tokens?: { input: number; output: number }
  plan?: string
  answer?: string
  decision_id?: string
  tool?: string
  args?: Record<string, unknown>
  summary?: string
  approved?: boolean
  reason?: string
  timeout_s?: number
  // M10: diff proposal fields
  path?: string
  rel_path?: string
  before?: string
  after?: string
  raw_diff?: string
  hunks?: DiffHunk[]
  stats?: DiffStats
  edited?: boolean
  // Phase 0 (decision 0025): sub-agent fields.
  parent_run_id?: string
  subagent_id?: string
  task_preview?: string
  specialist?: string
  error_kind?: string
}

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const text = await r.text().catch(() => r.statusText)
    throw new Error("HTTP " + r.status + ": " + text)
  }
  return r.json() as Promise<T>
}

export async function getHealth(): Promise<HealthResponse> {
  return jsonOrThrow(await fetch('/api/health'))
}

export async function getConfig(): Promise<ConfigResponse> {
  return jsonOrThrow(await fetch('/api/config'))
}

export async function listUploads(): Promise<UploadListResponse> {
  return jsonOrThrow(await fetch('/api/uploads'))
}

export async function uploadFile(file: File, tier: string): Promise<UploadMetadata> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch("/api/uploads?tier=" + encodeURIComponent(tier), {
    method: 'POST',
    body: fd,
  })
  return jsonOrThrow<UploadMetadata>(r)
}

export async function deleteUpload(name: string): Promise<{ deleted: string }> {
  return jsonOrThrow(
    await fetch("/api/uploads/" + encodeURIComponent(name), { method: 'DELETE' }),
  )
}

export async function checkAllowlist(
  tool: string,
  args: Record<string, unknown>,
  tier: string,
): Promise<AllowlistCheckResponse> {
  return jsonOrThrow(
    await fetch('/api/allowlist/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool, args, tier }),
    }),
  )
}

// --- M9 live-execution API (extended in M11) -----------------------------

export async function startRun(
  task: string,
  tier: string,
  opts: StartRunOptions = {},
): Promise<RunStartResponse> {
  const body: Record<string, unknown> = { task, tier }
  if (opts.provider) body.provider = opts.provider
  if (opts.model) body.model = opts.model
  if (opts.keys && Object.keys(opts.keys).length > 0) {
    body.keys = opts.keys
  }
  return jsonOrThrow(
    await fetch('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function listRuns(): Promise<RunListResponse> {
  return jsonOrThrow(await fetch('/api/runs'))
}

export async function getRun(runId: string): Promise<RunSummary> {
  return jsonOrThrow(await fetch("/api/runs/" + encodeURIComponent(runId)))
}

export async function postApproval(
  runId: string,
  decisionId: string,
  approved: boolean,
  reason: string = 'user',
  editedAfter: string | null = null,
): Promise<{ resolved: boolean; decision_id: string }> {
  const body: Record<string, unknown> = { decision_id: decisionId, approved, reason }
  if (editedAfter !== null) {
    body.edited_after = editedAfter
  }
  return jsonOrThrow(
    await fetch("/api/runs/" + encodeURIComponent(runId) + "/approval", {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function postStop(runId: string): Promise<{ stopped: boolean }> {
  return jsonOrThrow(
    await fetch("/api/runs/" + encodeURIComponent(runId) + "/stop", { method: 'POST' }),
  )
}

// --- M10: diff proposal + workspace tree ---------------------------------

export interface DiffHunk {
  op: 'equal' | 'replace' | 'insert' | 'delete'
  before: string[]
  after: string[]
}

export interface DiffStats {
  added: number
  removed: number
  same: number
  changed: boolean
}

export interface DiffProposedPayload extends StreamEvent {
  type: 'diff.proposed'
  decision_id: string
  tool: string
  path: string
  rel_path: string
  args: Record<string, unknown>
  summary: string
  tier: string
  before: string
  after: string
  raw_diff: string
  hunks: DiffHunk[]
  stats: DiffStats
  timeout_s: number
}

export interface DiffResolvedPayload extends StreamEvent {
  type: 'diff.resolved'
  decision_id: string
  approved: boolean
  reason: string
  edited: boolean
  path: string
}

export interface TreeEntry {
  name: string
  rel_path: string
  is_dir: boolean
  size: number
  depth: number
}

export interface WorkspaceTreeResponse {
  workspace: string
  entries: TreeEntry[]
  truncated: boolean
  max_entries: number
  max_depth: number
}

export async function getWorkspaceTree(
  maxEntries: number = 5000,
  maxDepth: number = 10,
): Promise<WorkspaceTreeResponse> {
  return jsonOrThrow(
    await fetch(
      '/api/workspace/tree?max_entries=' +
        encodeURIComponent(maxEntries) +
        '&max_depth=' +
        encodeURIComponent(maxDepth),
    ),
  )
}

// --- M14: audit log read-back --------------------------------------------
//
// Audit entries are loosely-typed JSON objects emitted by AuditSink. We
// only know a few fields with certainty (ts, event, tier, task, action,
// kind, message) — everything else (step, exit_code, duration_s,
// decision_id, ...) is allowed to vary by event type. So the interface
// is intentionally permissive; the panel renders defensively.

export interface AuditEntry {
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

export interface AuditListResponse {
  entries: AuditEntry[]
  total: number
  truncated: boolean
  /** Human-friendly hint for empty / missing log / no-sink. null when OK. */
  note: string | null
  /**
   * Present only when the request set ?verify=1. Shape mirrors the
   * verify_chain() result: ok, chained_entries, malformed_lines, etc.
   * Older servers (pre-M14) omit this; treat undefined as null.
   */
  chain?: {
    ok: boolean
    entries: number
    chained_entries: number
    bad_line: number | null
    first_unverifiable_line: number | null
    malformed_lines: number
    reason?: string
  } | null
}

export interface AuditListOptions {
  limit?: number
  /** Case-insensitive substring filter on event/tier/task/action/message/kind. */
  grep?: string
  /** When true, server replays the hash chain and includes status. */
  verify?: boolean
}

export async function listAudit(opts: AuditListOptions = {}): Promise<AuditListResponse> {
  const params = new URLSearchParams()
  if (opts.limit !== undefined) params.set('limit', String(opts.limit))
  if (opts.grep !== undefined && opts.grep.length > 0) params.set('grep', opts.grep)
  if (opts.verify === true) params.set('verify', '1')
  const qs = params.toString()
  return jsonOrThrow(await fetch('/api/audit' + (qs.length > 0 ? '?' + qs : '')))
}