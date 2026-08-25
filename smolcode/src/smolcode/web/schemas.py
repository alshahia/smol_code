"""Pydantic response/request schemas for the smolcode web API (M8 + M9)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    uploads_dir: str
    uploads_count: int


class TierSummary(BaseModel):
    name: str
    uploads: str
    network: str
    max_steps: int
    timeout_s: float
    docker_image: str
    commands: list[str]
    imports: list[str]


class ConfigResponse(BaseModel):
    workspace: str
    executor: str
    provider: str
    model: str
    litellm_proxy: str | None
    log_level: str
    tiers: list[TierSummary]
    uploads_dir: str
    upload_max_bytes: int
    upload_allowed_mime: list[str]
    # Phase 1 (decision 0025 §6.3): list of named project roots. Empty
    # means legacy single-workspace mode.
    projects: list[ProjectOut] = Field(default_factory=list)


# --- Phase 1 (decision 0025 §6.3): project + session types ---------------


class ProjectOut(BaseModel):
    """One project in ``Settings.projects``.

    ``name`` is the unique key (URL-safe, no whitespace, no slashes);
    ``root`` is the absolute filesystem path the SPA's tree panel renders.
    Additive + backwards-compatible: older servers omit this from /api/config.
    """

    name: str
    root: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectOut]


class ProjectCreateRequest(BaseModel):
    """POST /api/projects body. Phase 1, decision 0025 §6.3.

    ``name`` is the unique key (validated by the Project constructor).
    ``root`` is optional: when omitted the project is rooted at
    ``<workspace>/<name>``; when supplied it must be a path that
    already exists.
    """

    name: str = Field(..., description="Unique project name; URL-safe.")
    root: str | None = Field(
        default=None,
        description="Filesystem path; omit to default to <workspace>/<name>.",
    )


class SessionEntry(BaseModel):
    """Metadata for one chat-session file.

    Phase 1 extension: ``name`` (user-provided label stored in sibling
    ``meta.json``), ``run_count`` (number of ``run.started`` events in
    the jsonl), ``project`` (which project the session belongs to;
    ``None`` for sessions created before the project concept landed).
    All additive + optional so older servers can omit them and the SPA
    renders the empty state.
    """

    id: str
    path: str
    size_bytes: int
    mtime_iso: str
    name: str | None = None
    run_count: int = 0
    project: str | None = None


class SessionEvent(BaseModel):
    ts: str
    event: str
    raw: dict[str, Any]


class SessionCreateRequest(BaseModel):
    """POST /api/sessions body. Phase 1, decision 0025 §6.3.

    ``name`` is an optional user-friendly label. Empty/omitted creates
    an unnamed session (the SPA can rename later). ``project``
    associates the session with one of the configured projects; when
    omitted the session is created under the legacy ``workspace/sessions/``
    dir so it shows up in existing GET /api/sessions listings.
    """

    name: str | None = Field(
        default=None,
        description="Optional human-friendly label; stored in sibling meta.json.",
    )
    project: str | None = Field(
        default=None,
        description="Project name to scope this session to; omit for the legacy workspace.",
    )


class SessionCreateResponse(BaseModel):
    id: str
    name: str | None = None
    project: str | None = None


class SessionRenameRequest(BaseModel):
    """PATCH /api/sessions/{id} body. Phase 1, decision 0025 §6.3."""

    name: str = Field(..., description="New human-friendly label.")


class SessionDeleteResponse(BaseModel):
    id: str
    deleted: bool


class AuditEntry(BaseModel):
    ts: str
    event: str
    pid: int | None = None
    raw: dict[str, Any]


class AuditListResponse(BaseModel):
    """Response shape for ``GET /api/audit`` (M14.1, decision 0018).

    ``entries`` are returned as raw dicts (one per JSONL line) rather
    than AuditEntry instances -- the audit sink is free-form and the
    SPA wants the raw shape for direct rendering. Field names match
    ``smolcode.audit_reader.read_audit_entries`` exactly so the
    response is a 1:1 mapping of the reader's payload.

    ``chain`` is populated only when the caller passed ``?verify=1``
    (so the SPA can render the optional chain-health chip). Field is
    additive and ``None`` otherwise.
    """

    entries: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    truncated: bool = False
    note: str | None = None
    chain: dict[str, Any] | None = None


class AllowlistCheckRequest(BaseModel):
    tool: str = Field(..., description="Tool name, e.g. 'shell.run'")
    args: dict[str, Any] = Field(default_factory=dict)
    tier: str = Field(..., description="restricted | elevated | full_access")


class AllowlistCheckResponse(BaseModel):
    allowed: bool
    reason: str


class UploadOut(BaseModel):
    stored_name: str
    original_name: str
    size: int
    mime: str
    sha256: str
    tier: str
    ts: str
    uploaded_by: str


class UploadListResponse(BaseModel):
    uploads: list[UploadOut]


class CleanRequest(BaseModel):
    older_than_days: int | None = None
    confirm: bool = False


class CleanResponse(BaseModel):
    deleted: int
    requested_older_than: int | None


# --- M9: live execution ---------------------------------------------------


class RunStartRequest(BaseModel):
    task: str = Field(..., description="Task description for the agent.")
    tier: str = Field(default="restricted", description="restricted|elevated|full_access|orchestrator")
    upload_names: list[str] = Field(
        default_factory=list,
        description="Optional uploaded filenames to attach to the task as a header.",
    )
    # M11: per-run provider / model / API-key overrides (decision 0014).
    # All optional; the request stays backwards-compatible.
    provider: str | None = Field(
        default=None,
        description="M11: override the LLM provider for this run (e.g. 'opencode-go').",
    )
    model: str | None = Field(
        default=None,
        description="M11: override the model id for this run.",
    )
    keys: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "M11: whitelisted API keys (env-var -> value). Forwarded to the "
            "model factory in-memory; never persisted. Allowed names: "
            "*_API_KEY, *_APIKEY, HF_TOKEN."
        ),
    )
    # Phase 1 (decision 0025 §6.3): attach the run to a chat session + project.
    # Both optional. When omitted the runner still works (legacy mode);
    # when provided, the SPA's SessionsPane filters history by session_id.
    session_id: str | None = Field(
        default=None,
        description="Phase 1: attach this run to an existing chat session id.",
    )
    project: str | None = Field(
        default=None,
        description="Phase 1: scope this run to a named project (must be in Settings.projects).",
    )


class RunStartResponse(BaseModel):
    run_id: str
    # Phase 2 (decision 0025 §6.4): "running" when the run started
    # immediately, "queued" when a run was already active and this
    # one is in the FIFO queue.
    status: str = "running"


class SubAgentSummary(BaseModel):
    """Decision 0028 (per-sub-agent cost aggregation).

    Originally Phase 0 (decision 0025): one sub-agent invocation
    record. Set by the orchestrator do_<tier>_task / do_specialist
    tools around their inner agent.run() call. Reused for both the
    legacy single-entry shape (``subagent`` field on RunSummary) AND
    the new ``subagent_history`` list shape.

    Decision 0028 additions:
    - ``specialist``: name of the specialist agent when the
      sub-agent was invoked via do_specialist(name=...); None for
      do_<tier>_task. The BE dataclass already had this field; the
      Pydantic schema was missing it -- gap fixed by this decision
      so the wire now reflects every field Run.summary_dict emits.
    - ``tokens_in`` / ``tokens_out``: per-sub-agent LLM token
      attribution accumulated by Run.publish while the sub-agent
      was the active one. The outer run's tokens remain the
      TOTAL (own + all sub-agents) so run-level Dashboard cost is
      unchanged.
    - ``cost_usd``: derived at summary_dict() time via cost_for()
      using the outer run's provider/model. Default rates only
      for v1; settings plumbing deferred.
    """

    id: str
    tier: str
    started_at: float
    ended_at: float | None = None
    # Decision 0028: specialist name (was on BE dataclass but missing
    # from this Pydantic schema -- gap fix).
    specialist: str | None = None
    # Decision 0028: per-sub-agent LLM token attribution.
    tokens_in: int = 0
    tokens_out: int = 0
    # Decision 0028: per-sub-agent USD cost, derived at read time.
    cost_usd: float = 0.0


class TokenSummary(BaseModel):
    """Phase 0 (decision 0025): per-run token aggregates.

    total is the sum of input + output across every step.action
    event the runner has observed. input / output are broken out
    separately so the SPA can render two lines.
    """

    input: int = 0
    output: int = 0
    total: int = 0


class RunSummary(BaseModel):
    id: str
    task: str
    tier: str
    status: str
    started_at: float
    ended_at: float | None = None
    duration_s: float | None = None
    result: str | None = None
    error: str | None = None
    has_pending_approval: bool = False
    # M10: workspace-relative paths the run has touched.
    touched_paths: list[str] = Field(default_factory=list)
    # Phase 0 (decision 0025): aggregated tokens + step counter for
    # the Inspector Token usage section.
    tokens: TokenSummary = Field(default_factory=TokenSummary)
    step_count: int = 0
    # Phase 0 (decision 0025): seconds remaining until the agent_runner
    # wall-clock budget (_MAX_RUN_WALL_S) expires. Negative when the
    # run has overrun the budget; None when the budget is disabled.
    remaining_s: float | None = None
    # Phase 0 (decision 0025): latest sub-agent invocation. None when
    # the run has not delegated.
    subagent: SubAgentSummary | None = None
    # Phase 1 (decision 0025 §6.3): chat session id + project name the
    # run is attached to. Both additive; older servers omit them and
    # the SPA renders the empty state.
    session_id: str | None = None
    project: str | None = None
    # Phase 2 (decision 0025 §6.4): seconds since the most recent
    # agent-memory snapshot. None when the run has not been snapshot
    # yet (e.g. a run that was started and immediately stopped).
    snapshot_at: float | None = None
    # Phase 2 (decision 0025 §6.4): full sub-agent invocation history
    # (Phase 0 §14.8 #3 fold-in). Empty for runs that never delegated.
    subagent_history: list[SubAgentSummary] = Field(default_factory=list)
    # Phase 2 (decision 0025 §6.4): 1-based FIFO queue position when
    # the run is in the queue; None for active or terminal runs.
    queue_position: int | None = None


class RunListResponse(BaseModel):
    runs: list[RunSummary]


class ApprovalDecisionRequest(BaseModel):
    decision_id: str = Field(..., description="Decision id from the approval.requested event.")
    approved: bool
    edited_args: dict[str, Any] | None = Field(
        default=None,
        description="Optional edited args (M9: only allowed when the tool supports it; v1 logs but does not re-apply).",
    )
    # M10: for diff gates, the user can edit the proposed content
    # before approving. Sent as the full new file text. The runner
    # uses it in place of the agent's proposed content.
    edited_after: str | None = Field(
        default=None,
        description="M10: optional edited content for diff gates (write_file / patch_file).",
    )
    reason: str = Field(default="user", description="Reason recorded in the audit log.")


class ApprovalDecisionResponse(BaseModel):
    resolved: bool
    decision_id: str


# --- v1.9.x / decision 0027: server-side auto-approve toggle -----------


class AutoApproveSetRequest(BaseModel):
    """POST /api/runs/{id}/auto-approve body.

    ``enabled`` is the desired state of the per-session
    ``auto_approve_destructive`` flag. When ``True``, future
    destructive tool calls for the active ``full_access`` run skip
    the confirm callback (auto-approve destructive). When ``False``,
    the destructive gate re-arms and the next destructive call
    triggers an ``approval.requested`` event (the SPA shows the
    ApprovalModal again).

    The endpoint is intentionally minimal: ``enabled`` is the only
    field. The decision of WHICH side to flip is delegated to the
    caller (the SPA's AutoApproveBanner + ApprovalModal). The
    session module-level singleton holds the actual flag, scoped
    to the run id; the endpoint validates that the caller passed
    the run id that currently owns the singleton.
    """

    enabled: bool = Field(..., description="Target state for the session's auto_approve_destructive flag.")


class AutoApproveSetResponse(BaseModel):
    """Response shape for POST /api/runs/{id}/auto-approve.

    Mirrors the current session flag so the SPA's optimistic UI can
    confirm the flip without re-fetching. ``changed`` is True when
    the flag actually moved (False when the request was idempotent
    -- the flag was already at the target value).
    """

    run_id: str
    auto_approve_destructive: bool
    changed: bool


# --- M10: workspace tree --------------------------------------------------


class TreeEntryOut(BaseModel):
    name: str
    rel_path: str
    is_dir: bool
    size: int
    mtime: float


class WorkspaceTreeResponse(BaseModel):
    workspace: str
    entries: list[TreeEntryOut]
    truncated: bool


class StopResponse(BaseModel):
    stopped: bool


# --- M11: provider / model catalog (decision 0014) -------------------------


class ProviderOut(BaseModel):
    """One row in the provider list returned by GET /api/providers.

    ``key_state`` reflects ONLY in-process env state (``set`` /
    ``missing``). The user's localStorage-backed keys are folded in
    by the SPA client-side; the server never sees them on this GET.
    ``model_count`` is ``None`` until the first fetch.

    M12 (decision 0015) adds ``cached_at``: epoch seconds of the
    most recent model-list fetch (i.e. when the ``model_count`` /
    ``/models`` payload was last refreshed), or ``None`` if the
    per-process cache has never been populated for this provider.
    The SPA renders this as an inline "just now" / "5m ago" /
    "stale (>1h)" badge. Field is additive and backwards-compatible.

    M12.4 adds ``cached_error``: when the most recent ``/models``
    fetch FAILED, this is a short, single-line summary of the error
    (e.g. ``"fetch_failed: 401 Unauthorized"``); ``None`` otherwise.
    When ``cached_error`` is set, ``cached_at`` is the time of the
    FAILED attempt, so the SPA can show "last fetch FAILED 5m ago"
    alongside the badge. Also additive and backwards-compatible.
    """

    id: str
    name: str
    env_vars: list[str]
    default_model: str
    key_state: str
    model_count: int | None = None
    host_env_var: str | None = None
    cached_at: float | None = None
    cached_error: str | None = None


class ProviderListResponse(BaseModel):
    providers: list[ProviderOut]


class ModelListResponse(BaseModel):
    """Per-provider /models response.

    Mirrors ``model_catalog.fetch_models`` shape: ``models``,
    ``cached``, ``fetched_at`` (epoch seconds), and ``error``
    (None on success). An empty ``error`` like ``no_key``,
    ``no_base_url``, or ``fetch_failed: ...`` tells the SPA why
    the list is empty so it can surface a hint.
    """

    provider: str
    models: list[str] = Field(default_factory=list)
    cached: bool = False
    fetched_at: float = 0.0
    error: str | None = None


# ---- Phase 2 (decision 0025 §6.4): pause / resume / queue / file preview ----


class QueueEntryOut(BaseModel):
    """One queued-run record (Phase 2). The SPA's <QueuePane> renders
    one row per entry; the ``queue_position`` is the 1-based FIFO
    position (1 = next to run)."""

    id: str
    task: str
    tier: str
    queued_at: float
    project: str | None = None
    session_id: str | None = None
    queue_position: int = 0


class QueueListResponse(BaseModel):
    """Phase 2: list of active + queued runs.

    ``active`` is a list of full ``RunSummary`` dicts (current run +
    any paused runs). ``queued`` is a list of lightweight
    ``QueueEntryOut`` dicts (the runs that have not started yet).
    """

    active: list[RunSummary] = Field(default_factory=list)
    queued: list[QueueEntryOut] = Field(default_factory=list)


class QueueMoveRequest(BaseModel):
    """Decision 0031: move a queued entry to a new 1-based position.

    ``position=1`` puts the entry at the head of the FIFO list (runs
    next); ``position=N`` puts it at the tail. Values outside
    ``[1, len(queue)]`` are clamped by the BE (no 422 -- the FE
    computes the clamp locally anyway and we want a permissive
    default). The BE rejects ``position`` types other than int
    with 422 (Pydantic-level).
    """

    position: int


class QueueMoveResponse(BaseModel):
    """Decision 0031: response shape for PATCH /api/queue/{id}."""

    run_id: str
    position: int
    queue: list["QueueEntryOut"] = Field(default_factory=list)


class FileReadResponse(BaseModel):
    """Phase 2 (A4 file preview pane): the content of a file under
    the active project root. ``truncated`` is True when the file
    exceeded the request's ``max_bytes`` cap (default 256 KB); the
    SPA renders a notice + reflows the content. ``encoding`` is
    ``utf-8`` for text and ``binary`` for files that could not be
    decoded (rendered with replacement characters)."""

    path: str
    abs_path: str
    size: int
    truncated: bool = False
    encoding: str = "utf-8"
    content: str


class DashboardResponse(BaseModel):
    """Phase 3 (A6 Dashboard tab): aggregate counters + 24h sparkline.

    Counts are bounded to the last 24h. ``by_provider`` is a per-provider
    token breakdown for the same window. ``sparkline`` is 24 integer
    buckets (oldest first; bucket 23 = current hour). ``cost_estimate_usd_today``
    uses ``model_catalog.cost_for()`` with optional override via
    ``Settings.cost_rates`` (decision 0025 Q5)."""

    runs_today: int = 0
    tokens_today: TokenSummary = Field(default_factory=TokenSummary)
    errors_today: int = 0
    by_provider: dict[str, TokenSummary] = Field(default_factory=dict)
    sparkline: list[int] = Field(default_factory=lambda: [0] * 24)
    cost_estimate_usd_today: float = 0.0
    generated_at: float = 0.0
