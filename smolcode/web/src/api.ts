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
  /** Phase 1 (decision 0025 §6.3): attach this run to a chat session id. */
  session_id?: string | null
  /** Phase 1 (decision 0025 §6.3): scope this run to a named project. */
  project?: string | null
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
    | 'paused'
    | 'queued'
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
  // Phase 2 (decision 0025 §6.4): full sub-agent invocation history
  // (Phase 0 §14.8 #3 fold-in). Empty when the run never delegated.
  subagent_history?: SubAgentSummary[]
  // Phase 2: epoch seconds of the most recent agent-memory snapshot.
  // null when no snapshot has been taken yet.
  snapshot_at?: number | null
  // Phase 2: 1-based FIFO queue position; null for active / terminal.
  queue_position?: number | null
  // Phase 1 (decision 0025 §6.3): chat session id + project name the
  // run is attached to. Both additive; older servers omit them.
  session_id?: string | null
  project?: string | null
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
    // Phase 2 (decision 0025 sec 6.4): pause/resume lifecycle.
    | 'run.paused'
    | 'run.resumed'
    // SSE close-frame emitted by the BE when the run ends.
    | 'end'
  run_id?: string
  task?: string
  tier?: string
  model?: string
  provider?: string
  workspace?: string
  // Phase 1 (decision 0025 §6.3): session_id + project surfaced on
  // the run.started event so the SPA can tag the event stream.
  session_id?: string | null
  project?: string | null
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

export async function listUploads(project?: string | null): Promise<UploadListResponse> {
  const q = project ? '?project=' + encodeURIComponent(project) : ''
  return jsonOrThrow(await fetch('/api/uploads' + q))
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
  if (opts.session_id) body.session_id = opts.session_id
  if (opts.project) body.project = opts.project
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

// v1.9.x / decision 0027: server-side auto-approve toggle.
// Flips the active session's auto_approve_destructive flag so the
// destructive gate (shell.py / git.py forward() in the BE) sees the
// new value. Called from:
// - AutoApproveBanner "Disable" button (enabled=false)
// - ApprovalModal "Approve + auto-approve" button (enabled=true)
// 404 when the run is not in the manager; 409 when the run is
// inactive (no session currently owns the singleton).
export interface AutoApproveSetResponse {
  run_id: string
  auto_approve_destructive: boolean
  changed: boolean
}

export async function postAutoApprove(
  runId: string,
  enabled: boolean,
): Promise<AutoApproveSetResponse> {
  return jsonOrThrow(
    await fetch("/api/runs/" + encodeURIComponent(runId) + "/auto-approve", {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  )
}

// --- Phase 2 (decision 0025 §6.4): pause / resume / queue / file preview ----

export interface QueueEntry {
  id: string
  task: string
  tier: string
  queued_at: number
  project: string | null
  session_id: string | null
  queue_position: number
}

export interface QueueListResponse {
  active: RunSummary[]
  queued: QueueEntry[]
}

export async function pauseRun(
  runId: string,
): Promise<{ run_id: string; paused: boolean }> {
  return jsonOrThrow(
    await fetch("/api/runs/" + encodeURIComponent(runId) + "/pause", { method: 'POST' }),
  )
}

export async function resumeRun(
  runId: string,
): Promise<{ run_id: string; resumed: boolean }> {
  return jsonOrThrow(
    await fetch("/api/runs/" + encodeURIComponent(runId) + "/resume", { method: 'POST' }),
  )
}

export async function listQueue(): Promise<QueueListResponse> {
  return jsonOrThrow(await fetch('/api/queue'))
}

export async function cancelQueueEntry(
  runId: string,
): Promise<{ run_id: string; cancelled: boolean }> {
  return jsonOrThrow(
    await fetch('/api/queue/' + encodeURIComponent(runId), { method: 'DELETE' }),
  )
}

// Decision 0031: drag-and-drop queue reorder.
export interface QueueMoveResponse {
  run_id: string
  position: number
  // The full updated queue (same shape as QueueListResponse.queued)
  // so the FE can patch local state without a follow-up GET.
  queue: QueueEntry[]
}

export async function moveQueueEntry(
  runId: string,
  position: number,
): Promise<QueueMoveResponse> {
  return jsonOrThrow(
    await fetch('/api/queue/' + encodeURIComponent(runId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ position }),
    }),
  )
}

export interface FileReadResponse {
  path: string
  abs_path: string
  size: number
  truncated: boolean
  encoding: 'utf-8' | 'binary'
  content: string
}

export async function readFile(opts: {
  path: string
  project?: string | null
  maxBytes?: number
}): Promise<FileReadResponse> {
  const q = new URLSearchParams()
  q.set('path', opts.path)
  if (opts.project) q.set('project', opts.project)
  if (opts.maxBytes) q.set('max_bytes', String(opts.maxBytes))
  return jsonOrThrow(await fetch('/api/files?' + q.toString()))
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
  project?: string | null,
): Promise<WorkspaceTreeResponse> {
  const params = new URLSearchParams()
  params.set('max_entries', String(maxEntries))
  params.set('max_depth', String(maxDepth))
  if (project) params.set('project', project)
  return jsonOrThrow(
    await fetch('/api/workspace/tree?' + params.toString()),
  )
}

// --- Phase 1 (decision 0025 §6.3): projects + chat sessions --------------

export interface ProjectInfo {
  name: string
  root: string
}

export interface ProjectListResponse {
  projects: ProjectInfo[]
}

export interface SessionInfo {
  id: string
  path: string
  size_bytes: number
  mtime_iso: string
  /** User-provided label (stored in sibling meta.json). null until renamed. */
  name: string | null
  /** Number of run.started events in the jsonl. */
  run_count: number
  /** Project name when scoped; null for legacy workspace sessions. */
  project: string | null
}

export interface SessionListResponse {
  sessions: SessionInfo[]
}

export interface SessionCreateRequest {
  name?: string | null
  project?: string | null
}

export interface SessionCreateResponse {
  id: string
  name: string | null
  project: string | null
}

export interface SessionDetailResponse {
  id: string
  project: string | null
  events: { ts: string; event: string; raw: Record<string, unknown> }[]
}

export interface ProjectCreateRequest {
  name: string
  /** Omit to default to <workspace>/<name>. */
  root?: string | null
}

export async function listProjects(): Promise<ProjectListResponse> {
  return jsonOrThrow(await fetch('/api/projects'))
}

export async function createProject(req: ProjectCreateRequest): Promise<ProjectInfo> {
  return jsonOrThrow(
    await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    }),
  )
}

export async function deleteProject(name: string): Promise<{ deleted: string }> {
  return jsonOrThrow(
    await fetch('/api/projects/' + encodeURIComponent(name), { method: 'DELETE' }),
  )
}

export async function listSessions(
  project?: string | null,
): Promise<SessionListResponse> {
  const q = project ? '?project=' + encodeURIComponent(project) : ''
  return jsonOrThrow(await fetch('/api/sessions' + q))
}

export async function createSession(
  req: SessionCreateRequest,
  project?: string | null,
): Promise<SessionCreateResponse> {
  const q = project ? '?project=' + encodeURIComponent(project) : ''
  return jsonOrThrow(
    await fetch('/api/sessions' + q, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    }),
  )
}

export async function renameSession(
  id: string,
  name: string,
  project?: string | null,
): Promise<{ id: string; name: string }> {
  const q = project ? '?project=' + encodeURIComponent(project) : ''
  return jsonOrThrow(
    await fetch('/api/sessions/' + encodeURIComponent(id) + q, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  )
}

export async function deleteSession(
  id: string,
  project?: string | null,
): Promise<{ id: string; deleted: boolean }> {
  const q = project ? '?project=' + encodeURIComponent(project) : ''
  return jsonOrThrow(
    await fetch('/api/sessions/' + encodeURIComponent(id) + q, {
      method: 'DELETE',
    }),
  )
}

export async function getSession(
  id: string,
  project?: string | null,
): Promise<SessionDetailResponse> {
  const q = project ? '?project=' + encodeURIComponent(project) : ''
  return jsonOrThrow(
    await fetch('/api/sessions/' + encodeURIComponent(id) + q),
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

// ============================================================================
// Phase 3 (decision 0025 sec 6.5): Dashboard + cost + retry / rerun / export.
// ============================================================================

export interface TokenSummary {
  input: number
  output: number
  total: number
}

export interface DashboardResponse {
  runs_today: number
  tokens_today: TokenSummary
  errors_today: number
  by_provider: Record<string, TokenSummary>
  /** 24 integer buckets, oldest first; bucket 23 = current hour. */
  sparkline: number[]
  cost_estimate_usd_today: number
  generated_at: number
}

export interface CostBreakdown {
  input_cost_usd: number
  output_cost_usd: number
  cache_cost_usd: number
  total_usd: number
  rate_source: 'default' | 'override' | 'unknown'
}

export async function getDashboard(): Promise<DashboardResponse> {
  return jsonOrThrow(await fetch('/api/dashboard'))
}

export async function retryRun(
  id: string,
  overrides?: {
    task?: string
    tier?: 'restricted' | 'elevated' | 'orchestrator'
    provider?: string
    model?: string
    session_id?: string
    project?: string
    keys?: Record<string, string>
  },
): Promise<RunStartResponse> {
  return jsonOrThrow(await fetch('/api/runs/' + id + '/retry', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(overrides ?? {}),
  }))
}

export async function rerunRun(id: string): Promise<RunStartResponse> {
  return jsonOrThrow(await fetch('/api/runs/' + id + '/rerun', { method: 'POST' }))
}

export interface ExportPayload {
  summary: RunSummary
  events: unknown[]
  subagent_history: SubAgentSummary[]
  exported_at: number
  schema_version: number
}

export async function exportRun(id: string): Promise<ExportPayload> {
  return jsonOrThrow(await fetch('/api/runs/' + id + '/export'))
}

export function downloadExport(id: string, payload: ExportPayload): void {
  // Triggers a browser download of the run as run-<id>.json.
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'run-' + id + '.json'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}