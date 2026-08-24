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


class SessionEntry(BaseModel):
    id: str
    path: str
    size_bytes: int
    mtime_iso: str


class SessionEvent(BaseModel):
    ts: str
    event: str
    raw: dict[str, Any]


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


class RunStartResponse(BaseModel):
    run_id: str
    status: str


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
    models: list[str]
    cached: bool
    fetched_at: float
    error: str | None = None
