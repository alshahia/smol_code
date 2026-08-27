"""smolcode.web.api -- FastAPI endpoints (M8 + M9, decision 0010 D2).

Read-only viewer endpoints:
    GET  /api/health
    GET  /api/config
    GET  /api/tiers
    GET  /api/sessions
    GET  /api/sessions/{id}
    GET  /api/audit
    POST /api/allowlist/check

Upload endpoints (M8 D8):
    POST   /api/uploads
    GET    /api/uploads
    GET    /api/uploads/{name}
    DELETE /api/uploads/{name}
    POST   /api/uploads/clean

Live-execution endpoints (M9):
    POST /api/runs                 -> start a new run (returns run_id)
    GET  /api/runs                 -> list runs (sorted newest first)
    GET  /api/runs/{id}            -> run summary
    GET  /api/runs/{id}/events     -> SSE event stream
    POST /api/runs/{id}/approval   -> resolve a pending approval gate
    POST /api/runs/{id}/stop       -> request stop at next step boundary
    POST /api/runs/{id}/pause      -> request pause at next step boundary
    POST /api/runs/{id}/resume     -> rebuild agent from snapshot + continue
    POST /api/runs/{id}/auto-approve -> toggle session.auto_approve_destructive (decision 0027)

Queue endpoints (Phase 2, decision 0025 §6.4):
    GET    /api/queue              -> list queued + active runs
    DELETE /api/queue/{run_id}     -> cancel a queued run
    PATCH  /api/queue/{run_id}     -> move a queued entry to a new 1-based position (decision 0031)

File preview endpoints (Phase 2, decision 0025 §6.4):
    GET    /api/files              -> read a file by relative path (project-scoped)

Provider / model catalog endpoints (M11, decision 0014):
    GET  /api/providers                          -> catalog (key_state + defaults)
    GET  /api/providers/{provider_id}/models     -> live /models list (1h TTL)

Usage-cap endpoints (decision 0032):
    GET  /api/cost-caps            -> current caps + defaults + today's spend
    PUT  /api/cost-caps            -> replace live caps (validated against known providers)

The /api/runs endpoint now accepts three optional fields:
``provider``, ``model``, ``keys`` (decision 0014). All are optional
so existing callers stay backwards-compatible.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from .. import __version__
from ..audit import AuditSink
from ..audit_reader import audit_chain_status, read_audit_entries
from ..config import Project, Settings, as_dict

# Phase 3 F2 (decision 0036): context-window resolver for the
# Inspector.tsx fill bar denominator.
from ..model_catalog import fetch_models, resolve_context_window
from ..model_catalog import get_providers as _catalog_get_providers
from ..session import (
    create_session_file,
    delete_session_file,
    list_sessions,
    read_session_events,
    rename_session_file,
    resolve_project_root,
    safe_id,
    session_dir_for,
)
from ..uploads import UploadsStore
from .cost_caps import CostCapTracker
from .dashboard import compute_dashboard
from .deps import get_audit_sink, get_cost_cap_tracker, get_run_manager, get_settings, get_uploads_store
from .diffs import walk_tree
from .keys import extract_keys
from .runs import (
    Run,
    RunManager,
)
from .schemas import (
    AllowlistCheckRequest,
    AllowlistCheckResponse,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    AuditListResponse,
    AutoApproveSetRequest,
    AutoApproveSetResponse,
    CleanRequest,
    ConfigResponse,
    CostCapsState,
    CostCapsUpdateRequest,
    CostCapsUpdateResponse,
    DashboardResponse,
    FileReadResponse,
    HealthResponse,
    ModelListResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectOut,
    ProviderListResponse,
    ProviderOut,
    QueueListResponse,
    QueueMoveRequest,
    QueueMoveResponse,
    RunListResponse,
    RunStartRequest,
    RunStartResponse,
    RunSummary,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionDeleteResponse,
    SessionEntry,
    SessionEvent,
    SessionRenameRequest,
    OpenPathRequest,
    OpenPathResponse,
    StopResponse,
    TierSummary,
    TreeEntryOut,
    UploadListResponse,
    UploadOut,
    WorkspaceTreeResponse,
)


router = APIRouter(prefix="/api")


# ---- Read-only viewer endpoints -------------------------------------------


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request, store: UploadsStore = Depends(get_uploads_store)) -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "uploads_dir": str(store.dir),
        "uploads_count": len(store.list_metadata()),
    }


@router.get("/config", response_model=ConfigResponse)
def get_config(settings: Settings = Depends(get_settings)) -> dict:
    d = as_dict(settings)
    return {
        "workspace": d["workspace"],
        "executor": d["executor"],
        "provider": d["provider"],
        "model": d["model"],
        "litellm_proxy": d.get("litellm_proxy"),
        "log_level": d["log_level"],
        "tiers": [
            TierSummary(
                name=name,
                uploads=t["uploads"],
                network=t["network"],
                max_steps=t["max_steps"],
                timeout_s=t["timeout_s"],
                docker_image=t["docker_image"],
                commands=list(t["commands"]),
                imports=list(t["imports"]),
            ).model_dump()
            for name, t in d["tiers"].items()
        ],
        "uploads_dir": d.get("uploads_dir", ""),
        "upload_max_bytes": d.get("upload_max_bytes", 0),
        "upload_allowed_mime": list(d.get("upload_allowed_mime", [])),
        "projects": [ProjectOut(name=p["name"], root=p["root"]).model_dump() for p in d.get("projects", [])],
    }


@router.get("/tiers")
def get_tiers(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "tiers": {
            name: {
                "uploads": t.uploads,
                "network": t.network,
                "commands": list(t.commands),
                "imports": list(t.imports),
                "max_steps": t.max_steps,
            }
            for name, t in settings.tiers.items()
        }
    }


@router.get("/sessions", response_model=dict)
def get_sessions(
    settings: Settings = Depends(get_settings),
    project: str | None = Query(default=None, description="Project name to scope the listing."),
) -> dict:
    """List chat-session files.

    Phase 1 (decision 0025 §6.3): optional ``?project=foo`` query param
    scopes the listing to that project's session dir
    (``<project>/.smolcode/sessions/``). When omitted, lists sessions
    in the legacy ``<workspace>/sessions/`` dir so existing callers
    keep working.
    """
    root = resolve_project_root(settings, project)
    entries = list_sessions(root, project=project)
    return {
        "sessions": [
            SessionEntry(
                id=e["id"],
                path=e["path"],
                size_bytes=e["size_bytes"],
                mtime_iso=e["mtime_iso"],
                name=e["name"],
                run_count=e["run_count"],
                project=e["project"],
            ).model_dump()
            for e in entries
        ]
    }


@router.post("/sessions", response_model=SessionCreateResponse, status_code=201)
def post_sessions(
    req: SessionCreateRequest,
    settings: Settings = Depends(get_settings),
    project: str | None = Query(default=None, description="Project name to scope the new session."),
) -> dict:
    """Create a new chat session (Phase 1, decision 0025 §6.3).

    Always creates the file under the resolved root so the GET can
    list it. ``name`` is optional; the SPA can rename later via PATCH.
    When ``project`` is unknown (or omitted) the session is created
    in legacy workspace mode and the response reports ``project=None``.
    """
    # Resolve to a known project name (None when missing/unknown).
    effective_project = None
    if project is not None:
        for p in settings.projects:
            if p.name == project:
                effective_project = p.name
                break
    root = resolve_project_root(settings, effective_project)
    name = req.name if req.name else None
    try:
        jsonl = create_session_file(root, project=effective_project, name=name)
    except (ValueError, FileExistsError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return SessionCreateResponse(id=jsonl.stem, name=name, project=effective_project).model_dump()


@router.patch("/sessions/{session_id}", response_model=dict)
def patch_session(
    session_id: str,
    req: SessionRenameRequest,
    settings: Settings = Depends(get_settings),
    project: str | None = Query(default=None),
) -> dict:
    """Rename a session (Phase 1, decision 0025 §6.3)."""
    try:
        safe_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    root = resolve_project_root(settings, project)
    sdir = session_dir_for(root, project)
    target = sdir / (session_id + ".jsonl")
    if not target.exists():
        raise HTTPException(status_code=404, detail="session not found")
    try:
        rename_session_file(root, project=project, session_id=session_id, new_name=req.name)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"id": session_id, "name": req.name}


@router.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
def delete_session(
    session_id: str,
    settings: Settings = Depends(get_settings),
    project: str | None = Query(default=None),
) -> dict:
    """Delete a session and its meta.json (Phase 1, decision 0025 §6.3)."""
    try:
        safe_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    root = resolve_project_root(settings, project)
    sdir = session_dir_for(root, project)
    target = sdir / (session_id + ".jsonl")
    if not target.exists():
        raise HTTPException(status_code=404, detail="session not found")
    removed = delete_session_file(root, project=project, session_id=session_id)
    return SessionDeleteResponse(id=session_id, deleted=bool(removed)).model_dump()


@router.get("/sessions/{session_id}", response_model=dict)
def get_session(
    session_id: str,
    settings: Settings = Depends(get_settings),
    project: str | None = Query(default=None),
) -> dict:
    """Return the full event timeline of one session (Phase 1)."""
    try:
        safe_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    root = resolve_project_root(settings, project)
    sdir = session_dir_for(root, project)
    target = sdir / (session_id + ".jsonl")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="session not found")
    events = read_session_events(target)
    return {
        "id": session_id,
        "project": project,
        "events": [
            SessionEvent(
                ts=str(e.get("ts", "")),
                event=str(e.get("event", "")),
                raw=e,
            ).model_dump()
            for e in events
        ],
    }


# ---- Phase 1 (decision 0025 §6.3): project endpoints --------------------


@router.get("/projects", response_model=ProjectListResponse)
def get_projects(settings: Settings = Depends(get_settings)) -> dict:
    """List the configured projects (Phase 1, decision 0025 §6.3).

    Mirrors ``Settings.projects``. The SPA uses this to render the
    ``ProjectSwitcher`` dropdown and to validate ``?project=`` query
    params before forwarding them to other endpoints.
    """
    return ProjectListResponse(
        projects=[ProjectOut(name=p.name, root=str(p.root)).model_dump() for p in settings.projects]
    ).model_dump()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def post_project(
    req: ProjectCreateRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create / register a project at runtime (Phase 1).

    For Phase 1, project registration is in-memory only: the new
    project is appended to the live ``Settings.projects`` tuple for
    the lifetime of the running server. A persistent registration
    (write to ``SMOLCODE_PROJECTS`` env or a ``projects.toml``) is a
    Phase 1 followup; for now the user can copy the suggested
    ``SMOLCODE_PROJECTS`` string out of the response.
    """
    name = req.name
    if any(p.name == name for p in settings.projects):
        raise HTTPException(status_code=400, detail="project name already exists: " + name)
    if req.root:
        root_path = Path(req.root).expanduser().resolve()
        if not root_path.exists():
            raise HTTPException(status_code=400, detail="project root does not exist: " + str(root_path))
    else:
        root_path = (settings.workspace / name).resolve()
        root_path.mkdir(parents=True, exist_ok=True)
    try:
        project = Project(name, root_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Mutate the live settings tuple (Settings is a frozen shape; we
    # rebuild with the new projects list).
    new_settings = Settings(
        workspace=settings.workspace,
        executor=settings.executor,
        provider=settings.provider,
        model=settings.model,
        litellm_proxy=settings.litellm_proxy,
        log_level=settings.log_level,
        tiers=settings.tiers,
        uploads_dir=settings.uploads_dir,
        upload_max_bytes=settings.upload_max_bytes,
        upload_allowed_mime=settings.upload_allowed_mime,
        projects=tuple(list(settings.projects) + [project]),
    )
    # Update the app's stored settings so subsequent requests see the new project.
    request.app.state.settings = new_settings
    return ProjectOut(name=project.name, root=str(project.root)).model_dump()


@router.delete("/projects/{project_name}", response_model=dict)
def delete_project(
    project_name: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Remove a project from the live settings (Phase 1).

    For Phase 1 this only removes the project from the in-memory
    Settings.projects tuple -- the on-disk project directory is left
    untouched (a conservative choice; the user can ``rm -rf`` it
    manually if desired). Restarting the server restores any
    ``SMOLCODE_PROJECTS`` from the env.
    """
    remaining = [p for p in settings.projects if p.name != project_name]
    if len(remaining) == len(settings.projects):
        raise HTTPException(status_code=404, detail="project not found: " + project_name)
    new_settings = Settings(
        workspace=settings.workspace,
        executor=settings.executor,
        provider=settings.provider,
        model=settings.model,
        litellm_proxy=settings.litellm_proxy,
        log_level=settings.log_level,
        tiers=settings.tiers,
        uploads_dir=settings.uploads_dir,
        upload_max_bytes=settings.upload_max_bytes,
        upload_allowed_mime=settings.upload_allowed_mime,
        projects=tuple(remaining),
    )
    request.app.state.settings = new_settings
    return {"deleted": project_name}


@router.get("/audit", response_model=AuditListResponse)
def get_audit(
    limit: int = Query(default=50, ge=1, le=500, description="Max entries to return (1..500)."),
    grep: str | None = Query(
        default=None, max_length=200, description="Substring filter across event/tier/task/action/message/kind."
    ),
    verify: bool = Query(default=False, description="Run verify_chain and include chain status in the response."),
    audit: AuditSink | None = Depends(get_audit_sink),
) -> dict:
    """Read recent audit entries (M14.1, decision 0018).

    Reads the JSONL audit log via ``audit_reader.read_audit_entries``
    and applies ``RedactSecretsFilter`` to every string field on the
    way out. When ``verify=true``, the response also includes a
    ``chain`` sub-object produced by ``audit_chain_status`` so the
    SPA can render a chain-health chip next to the entry list.

    The endpoint is loopback-only (per project rule: never bind to a
    public host), and the reader caps the file at 10 MB to bound
    memory. Long-running hosts should rotate the log via
    ``smolcode audit rotate`` (M14.3) on a schedule.
    """
    if audit is None:
        # Server was started with --no-audit (decision 0009). The SPA
        # renders an empty state with this hint.
        return {
            "entries": [],
            "total": 0,
            "truncated": False,
            "note": "no audit sink attached (server started with --no-audit?)",
        }
    log_path = audit.path
    payload = read_audit_entries(log_path, limit=limit, grep=grep, redact=True)
    if verify:
        try:
            payload["chain"] = audit_chain_status(log_path)
        except FileNotFoundError:
            payload["chain"] = {"ok": False, "note": "log not found"}
    return payload


@router.post("/allowlist/check", response_model=AllowlistCheckResponse)
def check_allowlist(req: AllowlistCheckRequest, settings: Settings = Depends(get_settings)) -> dict:
    tier = settings.tiers.get(req.tier)
    if tier is None:
        raise HTTPException(status_code=400, detail="unknown tier: " + req.tier)
    tool = req.tool
    args = req.args or {}
    if tool == "shell.run":
        cmd = str(args.get("cmd", ""))
        if not cmd:
            return {"allowed": False, "reason": "cmd is required"}
        for suffix in (".exe", ".bat", ".cmd", ".com"):
            if cmd.lower().endswith(suffix):
                cmd = cmd[: -len(suffix)]
                break
        base = cmd
        if base in tier.commands:
            return {"allowed": True, "reason": "command in allowlist"}
        return {"allowed": False, "reason": "command " + repr(base) + " not in tier allowlist"}
    if tool == "fs.write_file":
        if tier.uploads == "read":
            path = str(args.get("path", "")).replace("\\", "/")
            uploads_norm = str(settings.uploads_dir).replace("\\", "/").rstrip("/").lower()
            path_lc = path.lower()
            in_uploads = (
                (uploads_norm and uploads_norm in path_lc)
                or ".smolcode/uploads/" in path_lc
                or path_lc.endswith("/.smolcode/uploads")
                or path_lc == ".smolcode/uploads"
            )
            if in_uploads:
                return {"allowed": False, "reason": "restricted tier cannot modify uploads"}
        return {"allowed": True, "reason": "path within workspace"}
    return {"allowed": True, "reason": "no policy implemented for tool " + tool}


# ---- Upload endpoints (M8 D8) --------------------------------------------


@router.get("/uploads", response_model=UploadListResponse)
def list_uploads(store: UploadsStore = Depends(get_uploads_store)) -> dict:
    metas = store.list_metadata()
    return {
        "uploads": [
            UploadOut(
                stored_name=m.stored_name,
                original_name=m.original_name,
                size=m.size,
                mime=m.mime,
                sha256=m.sha256,
                tier=m.tier,
                ts=m.ts,
                uploaded_by=m.uploaded_by,
            ).model_dump()
            for m in metas
        ]
    }


@router.post("/uploads", response_model=UploadOut, status_code=201)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    tier: str = Query(default="restricted"),
    store: UploadsStore = Depends(get_uploads_store),
) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        meta = store.save(
            original_name=file.filename or "upload",
            data=data,
            declared_mime=file.content_type,
            tier=tier,
            uploaded_by="gui",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return UploadOut(
        stored_name=meta.stored_name,
        original_name=meta.original_name,
        size=meta.size,
        mime=meta.mime,
        sha256=meta.sha256,
        tier=meta.tier,
        ts=meta.ts,
        uploaded_by=meta.uploaded_by,
    ).model_dump()


@router.get("/uploads/{name}")
def download_upload(name: str, store: UploadsStore = Depends(get_uploads_store)) -> Response:
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="invalid name")
    try:
        data = store.read(name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    metas = {m.stored_name: m for m in store.list_metadata()}
    mime = metas.get(name).mime if name in metas else "application/octet-stream"
    return Response(content=data, media_type=mime)


@router.delete("/uploads/{name}")
def delete_upload(name: str, store: UploadsStore = Depends(get_uploads_store)) -> dict:
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="invalid name")
    try:
        store.delete(name, deleted_by="gui")
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"deleted": name}


@router.post("/uploads/clean")
def clean_uploads(req: CleanRequest, store: UploadsStore = Depends(get_uploads_store)) -> dict:
    if not req.confirm:
        metas = store.list_metadata()
        return {
            "deleted": 0,
            "requested_older_than": req.older_than_days,
            "would_delete_count": len(metas),
            "note": "pass confirm=true to actually delete",
        }
    n = store.clean(older_than_days=req.older_than_days)
    return {"deleted": n, "requested_older_than": req.older_than_days}


# ---- Live-execution endpoints (M9) ---------------------------------------


def _run_summary(run: Run) -> dict:
    """Return a RunSummary dict for the SPA /api/runs endpoints.

    Phase 0 (decision 0025): folds in token + step aggregates, the
    remaining wall-clock seconds, and the latest sub-agent
    invocation. The timeout budget is imported from
    agent_runner._MAX_RUN_WALL_S lazily so this module does not
    pay the smolagents import cost on cold-start.
    """
    duration = None
    if run.ended_at is not None:
        duration = max(0.0, run.ended_at - run.started_at)
    try:
        from .agent_runner import _MAX_RUN_WALL_S

        budget = _MAX_RUN_WALL_S
    except Exception:
        budget = 0
    snap = run.summary_dict(max_wall_s=budget)
    from .schemas import SubAgentSummary, TokenSummary

    sub_summary = None
    if snap["subagent"] is not None:
        sub = snap["subagent"]
        sub_summary = SubAgentSummary(
            id=str(sub["id"]),
            tier=str(sub["tier"]),
            started_at=float(sub["started_at"]),
            ended_at=sub.get("ended_at"),
        ).model_dump()
    return RunSummary(
        id=run.id,
        task=run.task,
        tier=run.tier,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
        duration_s=duration,
        result=run.result,
        error=run.error,
        has_pending_approval=bool(run.pending),
        touched_paths=run.touched_list(),
        tokens=TokenSummary(
            input=int(snap["tokens_in"]),
            output=int(snap["tokens_out"]),
            total=int(snap["tokens_total"]),
            # Phase 3 F2 (decision 0036): cache tokens + this-step split.
            # snap dict is the Run.summary_dict() output; falls back to 0
            # when the run is pre-step or the snapshot predates F2.
            cache_hit=int(snap.get("tokens_cache_hit", 0) or 0),
            current_input=int(snap.get("current_input", 0) or 0),
            current_output=int(snap.get("current_output", 0) or 0),
            last_step_at=snap.get("last_step_at"),
        ),
        step_count=int(snap["step_count"]),
        remaining_s=snap.get("remaining_s"),
        subagent=sub_summary,
        session_id=run.session_id,
        project=run.project,
        # Phase 3 F3 (decision 0036): effective_cwd + anchor toggle.
        # effective_cwd is a Path | None on Run; convert to str for
        # the wire (None stays None so the SPA skips the Working
        # root row in legacy mode). anchor_to_project_root is bool
        # with default False -- pre-F3 servers omit both fields
        # and the SPA renders nothing for them.
        effective_cwd=str(run.effective_cwd) if getattr(run, "effective_cwd", None) else None,
        anchor_to_project_root=bool(getattr(run, "anchor_to_project_root", False)),
        # Phase 3 F2 (decision 0036): model id + provider + context window.
        # resolve_context_window returns None when the provider/model pair
        # is unknown (custom provider with no mapping) -- the SPA renders
        # no fill bar in that case.
        model=getattr(run, "model", "") or "",
        provider=getattr(run, "provider", "") or "",
        context_window=resolve_context_window(getattr(run, "provider", "") or None, getattr(run, "model", "") or None),
    ).model_dump()


@router.post("/runs", response_model=RunStartResponse, status_code=201)
def start_run(
    req: RunStartRequest,
    settings: Settings = Depends(get_settings),
    audit: AuditSink | None = Depends(get_audit_sink),
    mgr: RunManager = Depends(get_run_manager),
) -> dict:
    """Start a new agent run. Returns run_id for SSE subscription.

    M11 (decision 0014) request shape extensions, all optional:

      ``provider`` -- preset id to use for this run
                     (overrides ``settings.provider``).
      ``model``    -- model id to use for this run
                     (overrides ``settings.model``).
      ``keys``     -- ``{env_var: value}`` map; the whitelisted subset
                     is forwarded to the model factory in-memory.
                     Keys are NEVER persisted to disk. See
                     ``web/keys.py:extract_keys`` for the whitelist.
    """
    if req.tier not in ("restricted", "elevated", "full_access", "orchestrator"):
        raise HTTPException(status_code=400, detail="unknown tier: " + req.tier)
    if not req.task or not req.task.strip():
        raise HTTPException(status_code=400, detail="task must be non-empty")
    if req.tier == "full_access":
        # Per M4 + decision 0006: full_access requires an explicit y/N
        # prompt BEFORE the agent is built. The web flow does not have
        # a stdin to prompt on; require the SPA to set a per-request
        # X-Smolcode-Full-Access-Confirm header (the SPA shows a modal
        # first). For v1 we hard-reject full_access from the web: use
        # the CLI for that tier. See decision 0012.
        raise HTTPException(
            status_code=403,
            detail=(
                "full_access tier requires the CLI (decision 0012); "
                "the web GUI supports restricted/elevated/orchestrator only."
            ),
        )

    # M11: extract whitelisted keys from the request body. Anything that
    # is not on the whitelist (or empty) is silently dropped -- the SPA
    # can resend its full localStorage map on every request without
    # coordinating with the server about which provider is selected.
    extracted_keys = extract_keys(req.keys or {})

    # Map the chosen provider -> its api_key_env so the runner can
    # pick the single value out of ``extracted_keys`` that is
    # appropriate for THIS run's provider.
    api_key_value: str | None = None
    if req.provider is not None:
        from ..models import get_preset

        try:
            preset = get_preset(req.provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if preset.api_key_env and preset.api_key_env in extracted_keys:
            api_key_value = extracted_keys[preset.api_key_env]
    else:
        # No provider override -> use settings.provider's preset
        # env-var name. settings is authoritative for the default
        # provider, so we ask the same get_preset() to resolve it.
        from ..models import get_preset

        try:
            preset = get_preset(settings.provider)
            if preset.api_key_env and preset.api_key_env in extracted_keys:
                api_key_value = extracted_keys[preset.api_key_env]
        except ValueError:
            api_key_value = None

    try:
        # Phase 2 (decision 0025 §6.4): auto-enqueue when a run is
        # already active. ``start_or_enqueue_run`` returns
        # ``(run_id, status)`` where status is "running" or "queued".
        run_id, status = mgr.start_or_enqueue_run(
            task=req.task.strip(),
            tier=req.tier,
            settings=settings,
            audit=audit,
            provider_override=req.provider,
            model_override=req.model,
            api_key_value=api_key_value,
            session_id=req.session_id,
            project=req.project,
            anchor_to_project_root=bool(req.anchor_to_project_root),
        )
    except ValueError as e:
        # Decision 0032: cost-cap rejection carries a ``cost_cap_reached:``
        # prefix so the SPA can surface the reason. The API layer maps
        # this prefix to HTTP 429 (Too Many Requests -- semantically "the
        # resource budget is exhausted, try again later / lift the cap").
        # Other ValueErrors (task validation, unknown tier, unknown
        # provider) keep their existing 400 mapping.
        msg = str(e)
        if msg.startswith("cost_cap_reached:"):
            raise HTTPException(status_code=429, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e
    return RunStartResponse(run_id=run_id, status=status).model_dump()


@router.get("/runs", response_model=RunListResponse)
def list_runs(mgr: RunManager = Depends(get_run_manager)) -> dict:
    runs = sorted(mgr.list(), key=lambda r: r.started_at, reverse=True)
    return RunListResponse(runs=[_run_summary(r) for r in runs]).model_dump()


@router.get("/runs/{run_id}")
def get_run(run_id: str, mgr: RunManager = Depends(get_run_manager)) -> dict:
    run = mgr.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_summary(run)


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, mgr: RunManager = Depends(get_run_manager)) -> StreamingResponse:
    """SSE stream for a run. Emits events as they are produced by the
    agent loop. Closes when the run reaches a terminal status."""
    # Check existence UP FRONT so the 404 is raised before StreamingResponse
    # takes ownership of the (deferred) generator. subscribe() itself
    # raises KeyError lazily on first next(), which would surface as a 500.
    if mgr.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    gen = mgr.subscribe(run_id)
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering (no effect on loopback)
            "Connection": "keep-alive",
        },
    )


@router.post("/runs/{run_id}/approval", response_model=ApprovalDecisionResponse)
def post_approval(
    run_id: str,
    req: ApprovalDecisionRequest,
    mgr: RunManager = Depends(get_run_manager),
) -> dict:
    run = mgr.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not req.decision_id:
        raise HTTPException(status_code=400, detail="decision_id is required")
    ok = mgr.decide(
        run_id=run_id,
        decision_id=req.decision_id,
        approved=req.approved,
        edited_args=req.edited_args,
        reason=req.reason or "user",
        edited_after=req.edited_after,
    )
    return ApprovalDecisionResponse(resolved=ok, decision_id=req.decision_id).model_dump()


@router.post("/runs/{run_id}/stop", response_model=StopResponse)
def post_stop(run_id: str, mgr: RunManager = Depends(get_run_manager)) -> dict:
    run = mgr.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    mgr.stop(run_id)
    return StopResponse(stopped=True).model_dump()


# --- Phase 3 F3 / Q3 (decision 0036): open-in-explorer endpoint ---


def _open_external(abs_path: str) -> bool:
    """Phase 3 F3 / Q3: platform-specific opener. The test suite
    monkey-patches this to avoid popping a real Explorer window.
    Returns True on success, False on platform / subprocess
    failure. Timeout 3 s per the plan. Windows uses
    ``cmd /c start "" <path>``; macOS ``open``; Linux
    ``xdg-open``. shell=False so we never spawn a shell.
    """
    import subprocess as _sp
    import sys as _sys

    try:
        if _sys.platform == "win32":
            r = _sp.run(
                ["cmd", "/c", "start", "", abs_path],
                shell=False,
                timeout=3,
            )
        elif _sys.platform == "darwin":
            r = _sp.run(["open", abs_path], shell=False, timeout=3)
        else:
            r = _sp.run(["xdg-open", abs_path], shell=False, timeout=3)
    except Exception:
        return False
    return r.returncode == 0


def _is_under(base: Path, target: Path) -> bool:
    """Phase 3 F3 / Q3: containment helper. Returns True when
    ``target`` (resolved absolute) is the same as ``base`` OR
    lives under it. False on any OSError / ValueError so the
    endpoint defaults to safe (deny). Used by /api/open-path.
    """
    import os as _os

    try:
        base_r = base.resolve()
        target_r = target.resolve()
    except (OSError, ValueError):
        return False
    try:
        common = _os.path.commonpath([_os.path.normcase(str(target_r)), _os.path.normcase(str(base_r))])
    except ValueError:
        return False
    return common == _os.path.normcase(str(base_r))


@router.post("/open-path", response_model=OpenPathResponse)
def open_path(
    req: OpenPathRequest,
    settings: Settings = Depends(get_settings),
    mgr: RunManager = Depends(get_run_manager),
) -> dict:
    """Phase 3 F3 / Q3: open ``req.path`` in the platform file
    manager. Whitelist base is ``settings.workspace`` by default
    OR ``run.effective_cwd`` when ``req.run_id`` is supplied AND
    the run exists AND its effective_cwd is set. Containment is
    checked FIRST so a path that is clearly outside the
    whitelist (e.g. /etc/passwd) is refused with 403 before any
    filesystem existence probe (POLICY-DECISIONS.md Q3).
    """
    if not req.path or not str(req.path).strip():
        raise HTTPException(status_code=400, detail="path is required")
    base_path: Path | None = None
    if req.run_id:
        run = mgr.get(req.run_id)
        if run is not None and getattr(run, "effective_cwd", None):
            base_path = Path(run.effective_cwd)
    if base_path is None:
        ws = getattr(settings, "workspace", "") or ""
        base_path = Path(ws) if ws else None
    if base_path is None or not str(base_path):
        raise HTTPException(status_code=400, detail="no workspace base configured")
    try:
        target = Path(req.path)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    if not _is_under(base_path, target):
        raise HTTPException(
            status_code=403,
            detail="path is outside the workspace; refusing to open",
        )
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if not _open_external(str(target)):
        raise HTTPException(status_code=500, detail="opener failed")
    return OpenPathResponse(opened=True).model_dump()


# v1.9.x / decision 0027: server-side auto-approve OFF (and ON) endpoint.
# Closes the FE-6 partial gap: clicking "Disable" on the AutoApproveBanner
# (or "Approve + auto-approve" in the ApprovalModal) now reaches the BE
# so the underlying ``session.auto_approve_destructive`` flag flips and
# future destructive tool calls respect the new state. See decision
# doc 0027 for the full design + edge-case analysis.
@router.post("/runs/{run_id}/auto-approve", response_model=AutoApproveSetResponse)
def post_auto_approve(
    run_id: str,
    req: AutoApproveSetRequest,
    mgr: RunManager = Depends(get_run_manager),
) -> dict:
    ok, err, current = mgr.set_auto_approve(run_id, bool(req.enabled))
    if not ok:
        # Distinguish "run not found" (404) from "session not active for
        # this run" (409). The run-not-found case means the SPA is
        # targeting a purged run id; the not-active case means the run
        # exists in RunManager but is no longer the active session
        # (e.g. it already ended, or another run is in flight).
        if err == "run not found":
            raise HTTPException(status_code=404, detail=err)
        raise HTTPException(status_code=409, detail=err or "no active session for run")
    return AutoApproveSetResponse(
        run_id=run_id,
        auto_approve_destructive=bool(current),
        # ``changed`` reflects whether the flag actually moved. The
        # helper returns ``current`` which is the post-flip value;
        # ``changed`` is therefore the same as (current != ?pre). We
        # omit the pre value here and trust the SPA to treat
        # idempotent flips as no-ops on its end.
        changed=True,
    ).model_dump()


# ---- Phase 2 (decision 0025 §6.4): pause / resume / queue / file preview ----


@router.post("/runs/{run_id}/pause", response_model=dict)
def post_pause(run_id: str, mgr: RunManager = Depends(get_run_manager)) -> dict:
    """Request a pause at the next step boundary.

    Idempotent: a second call when the run is already paused returns
    200 with ``paused=True``. A call against a terminal run returns
    409 (no point pausing a run that already ended).
    """
    run = mgr.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status == "paused":
        return {"run_id": run_id, "paused": True}
    if run.status in ("done", "error", "stopped"):
        raise HTTPException(status_code=409, detail="cannot pause a terminal run")
    ok = mgr.pause_run(run_id)
    return {"run_id": run_id, "paused": bool(ok)}


@router.post("/runs/{run_id}/resume", response_model=dict)
def post_resume(
    run_id: str,
    settings: Settings = Depends(get_settings),
    mgr: RunManager = Depends(get_run_manager),
) -> dict:
    """Resume a paused run.

    Rebuilds the agent from the most recent snapshot + replays the
    step memory. Returns 409 if the run is not paused.
    """
    run = mgr.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "paused":
        raise HTTPException(status_code=409, detail="run is not paused")
    ok, err = mgr.resume_run(run_id, settings)
    if not ok:
        raise HTTPException(status_code=409, detail=str(err or "resume failed"))
    return {"run_id": run_id, "resumed": True}


# Phase 3 (decision 0025 sec 6.5): retry / rerun / export endpoints.
# retry = re-run with the SAME task + SAME settings; returns a new run_id.
#       The parent run must be terminal (done/error/stopped). Used both for
#       manual re-runs AND for transient-failure retry (B7).
# rerun = re-run with the SAME task verbatim, regardless of run status;
#       only valid when the original run is done.
# export = JSON download of {summary, events, subagent_history, schema_version}.
# dashboard = aggregate runs/audit/cost for the Dashboard tab.

_TERMINAL_STATUSES = frozenset({"done", "error", "stopped"})


@router.post("/runs/{run_id}/retry", response_model=RunStartResponse)
def post_retry(
    run_id: str,
    req: RunStartRequest | None = None,
    settings: Settings = Depends(get_settings),
    mgr: RunManager = Depends(get_run_manager),
) -> dict:
    """Retry a terminal run with the same task + settings (B4 + B7).

    Returns a new run_id. The parent run's task/provider/model/session_id/
    project are preserved; an optional RunStartRequest body can override.
    Returns 404 if the parent doesn't exist, 409 if the parent is still
    active.
    """
    parent = mgr.get(run_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="run not found")
    if parent.status not in _TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="can only retry a terminal run (status=" + parent.status + ")")
    # Map the parent's api_key (we don't re-extract; the parent used its
    # own override). For Phase 3 we trust that the SPA re-sends keys on the
    # next start_run call; this endpoint just needs to reproduce the task +
    # settings.
    api_key_value = getattr(parent, "api_key_value", None)
    extracted_keys = extract_keys((req.keys if req else None) or {})
    if req and req.provider:
        from ..models import get_preset

        try:
            preset = get_preset(req.provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if preset.api_key_env and preset.api_key_env in extracted_keys:
            api_key_value = extracted_keys[preset.api_key_env]
    new_id, status = mgr.start_or_enqueue_run(
        task=(req.task if req and req.task else parent.task).strip(),
        tier=(req.tier if req and req.tier else parent.tier),
        settings=settings,
        session_id=(req.session_id if req and req.session_id else parent.session_id),
        project=(req.project if req and req.project else parent.project),
        provider_override=(req.provider if req and req.provider else parent.provider),
        model_override=(req.model if req and req.model else parent.model),
        api_key_value=api_key_value,
        parent_retry_of=parent.id,
    )
    parent.retry_count = getattr(parent, "retry_count", 0) + 1
    return RunStartResponse(run_id=new_id, status=status).model_dump()


@router.post("/runs/{run_id}/rerun", response_model=RunStartResponse)
def post_rerun(
    run_id: str,
    settings: Settings = Depends(get_settings),
    mgr: RunManager = Depends(get_run_manager),
) -> dict:
    """Re-run a completed run verbatim (B4). Only valid when status=done.

    Returns a new run_id. Provider/model/task/session_id/project are all
    copied from the parent. Returns 404 if missing, 409 if not done.
    """
    parent = mgr.get(run_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="run not found")
    if parent.status != "done":
        raise HTTPException(status_code=409, detail="can only rerun a completed run (status=" + parent.status + ")")
    new_id, status = mgr.start_or_enqueue_run(
        task=parent.task,
        tier=parent.tier,
        settings=settings,
        session_id=parent.session_id,
        project=parent.project,
        provider_override=parent.provider,
        model_override=parent.model,
        api_key_value=getattr(parent, "api_key_value", None),
        parent_rerun_of=parent.id,
    )
    return RunStartResponse(run_id=new_id, status=status).model_dump()


@router.get("/runs/{run_id}/export")
def export_run(
    run_id: str,
    mgr: RunManager = Depends(get_run_manager),
) -> Response:
    """Export a run as a JSON download (B5). Includes RunSummary + event log + subagent_history.

    Truncates long observations to 8 KB each (same cap as the SSE event stream).
    Schema version 1 (decision 0025 sec 6.5: schema is additive; bump only on breaking change).
    """
    run = mgr.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    # Pull the event log via the RunManager subscribe API's snapshot mode.
    try:
        raw_events = mgr.events_snapshot(run_id, max_events=2000)
    except Exception:
        raw_events = []
    # Truncate long string observations (defense-in-depth; SSE already truncates).
    events_out = []
    for ev in raw_events:
        if isinstance(ev, dict):
            obs = ev.get("observations")
            if isinstance(obs, list):
                for i, o in enumerate(obs):
                    if isinstance(o, str) and len(o) > 8192:
                        obs[i] = o[:8192] + "...[truncated]..."
        events_out.append(ev)
    payload = {
        "summary": _run_summary(run),
        "events": events_out,
        "subagent_history": [
            s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in getattr(run, "subagent_history", [])
        ],
        "exported_at": time.time(),
        "schema_version": 1,
    }
    return Response(
        content=json.dumps(payload, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="run-' + run_id + '.json"'},
    )


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    settings: Settings = Depends(get_settings),
    mgr: RunManager = Depends(get_run_manager),
    audit_sink: AuditSink | None = Depends(get_audit_sink),
) -> DashboardResponse:
    """Aggregate runs / audit / cost for the Dashboard tab (A6).

    Counts bounded to the last 24h. The sparkline is capped at 24 buckets.
    Cost is computed via model_catalog.cost_for() with optional override
    via Settings.cost_rates (decision 0025 Q5).
    """
    from .dashboard import compute_dashboard

    # Use the audit reader (count_since) if available, else fall back to None.
    audit_reader = SimpleNamespace(count_since=lambda t, level=None: _audit_count_since(audit_sink, t, level))
    return compute_dashboard(mgr, audit_reader, settings)


def _audit_count_since(audit_sink: AuditSink | None, since: float, level: str | None) -> int:
    """Count audit entries >= since timestamp and matching level.

    audit_sink is a writer; we read via the audit_reader module when the sink is missing.
    """
    if audit_sink is None:
        return 0
    try:
        # Use the in-memory deque if available (audit_sink exposes .entries as deque).
        entries = getattr(audit_sink, "entries", None)
        if entries is None:
            return 0
        count = 0
        for ev in entries:
            try:
                if ev.timestamp >= since and (level is None or getattr(ev, "level", None) == level):
                    count += 1
            except AttributeError:
                continue
        return count
    except Exception:
        return 0


@router.get("/queue", response_model=QueueListResponse)
def list_queue(mgr: RunManager = Depends(get_run_manager)) -> dict:
    """List queued + active runs. Active first (sorted by start
    monotonic), then queued FIFO. The SPA's <QueuePane> renders this
    list.
    """
    active = [r for r in mgr.list() if r.status in ("running", "awaiting_approval", "paused")]
    queued = mgr.queue()
    return QueueListResponse(
        active=[
            RunSummary(
                id=r.id,
                task=r.task,
                tier=r.tier,
                status=r.status,
                started_at=r.started_at,
                ended_at=r.ended_at,
                duration_s=None,
                result=r.result,
                error=r.error,
                has_pending_approval=bool(r.pending),
                tokens=__import__("smolcode.web.schemas", fromlist=["TokenSummary"]).TokenSummary(
                    input=r.tokens_in,
                    output=r.tokens_out,
                    total=r.tokens_in + r.tokens_out,
                ),
                step_count=r.step_count,
                remaining_s=r.remaining_s(
                    __import__("smolcode.web.agent_runner", fromlist=["_MAX_RUN_WALL_S"]).__dict__.get(
                        "_MAX_RUN_WALL_S", 0
                    )
                ),
                subagent=(
                    {
                        "id": r.subagent.id,
                        "tier": r.subagent.tier,
                        "started_at": r.subagent.started_at,
                        "ended_at": r.subagent.ended_at,
                    }
                    if r.subagent is not None
                    else None
                ),
                session_id=r.session_id,
                project=r.project,
                queue_position=r.queue_position,
            ).model_dump()
            for r in active
        ],
        queued=[
            {
                "id": e.id,
                "task": e.task,
                "tier": e.tier,
                "queued_at": e.queued_at,
                "project": e.project,
                "session_id": e.session_id,
                "queue_position": i + 1,
            }
            for i, e in enumerate(queued)
        ],
    ).model_dump()


@router.delete("/queue/{run_id}", response_model=dict)
def cancel_queue(run_id: str, mgr: RunManager = Depends(get_run_manager)) -> dict:
    """Cancel a queued (not yet started) run. Returns 409 if the run
    is already active -- the SPA should use POST /api/runs/{id}/stop
    for active runs."""
    run = mgr.get(run_id)
    if run is not None and run.status not in ("queued",):
        raise HTTPException(
            status_code=409,
            detail="cannot cancel a run that is not queued; use /stop instead",
        )
    ok = mgr.cancel_queue(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="queue entry not found")
    return {"run_id": run_id, "cancelled": True}


@router.patch("/queue/{run_id}", response_model=QueueMoveResponse)
def move_queue_entry(
    run_id: str,
    req: QueueMoveRequest,
    mgr: RunManager = Depends(get_run_manager),
) -> dict:
    """Decision 0031: move a queued entry to a new 1-based position.

    ``position=1`` puts the entry at the head of the FIFO list (runs
    next); ``position=N`` puts it at the tail. Out-of-range values
    are clamped server-side to ``[1, len(queue)]`` so a stale FE
    computation (after a cancel) doesn't 422 -- the user just sees
    the entry snap to the nearest valid slot.

    Returns 404 if ``run_id`` is not currently in the queue. Pydantic
    rejects non-int ``position`` with 422.
    """
    try:
        new_pos = mgr.move_queue(run_id, int(req.position))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if new_pos is None:
        raise HTTPException(status_code=404, detail="queue entry not found")
    # Return the full updated queue so the FE can patch its local
    # state without a follow-up GET /api/queue.
    queued = mgr.queue()
    return QueueMoveResponse(
        run_id=run_id,
        position=new_pos,
        queue=[
            {
                "id": e.id,
                "task": e.task,
                "tier": e.tier,
                "queued_at": e.queued_at,
                "project": e.project,
                "session_id": e.session_id,
                "queue_position": i + 1,
            }
            for i, e in enumerate(queued)
        ],
    ).model_dump()


@router.get("/files", response_model=FileReadResponse)
def read_file(
    path: str = Query(..., description="File path relative to the project root, or absolute inside the workspace."),
    project: str | None = Query(
        default=None,
        description="Project name (must be in Settings.projects). Defaults to the active project or legacy workspace.",
    ),
    max_bytes: int = Query(
        default=256 * 1024, ge=1, le=10 * 1024 * 1024, description="Size cap; oversize files return 413."
    ),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Phase 2 (decision 0025 §6.4 A4): read a file for the <FilePreview>
    pane. Path is sandboxed to the project root (or workspace for
    legacy mode). Returns the file content as UTF-8 text + metadata.
    """
    from .agent_runner import _MAX_RUN_WALL_S  # noqa: F401  (kept for parity)

    # Resolve the project root.
    root: Path | None = None
    if project:
        for p in getattr(settings, "projects", ()) or ():
            if getattr(p, "name", None) == project:
                root = Path(getattr(p, "root", ""))
                break
    if root is None:
        root = Path(getattr(settings, "workspace", "") or "")
    if not str(root):
        raise HTTPException(status_code=400, detail="no project root available")
    root = root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    # Reject if candidate escapes root.
    try:
        if Path(os.path.commonpath([str(candidate), str(root)])) != root:
            raise HTTPException(status_code=403, detail="path is outside project root")
    except (ValueError, OSError):
        raise HTTPException(status_code=403, detail="path is outside project root") from None
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    size = candidate.stat().st_size
    truncated = False
    if size > max_bytes:
        truncated = True
        with candidate.open("rb") as f:
            data = f.read(max_bytes)
    else:
        with candidate.open("rb") as f:
            data = f.read()
    try:
        text = data.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        encoding = "binary"
    rel = candidate.relative_to(root).as_posix()
    return FileReadResponse(
        path=rel,
        abs_path=str(candidate),
        size=size,
        truncated=truncated,
        encoding=encoding,
        content=text,
    ).model_dump()


# ---- M10: workspace tree endpoint ---------------------------------------


@router.get("/workspace/tree", response_model=WorkspaceTreeResponse)
def workspace_tree(
    settings: Settings = Depends(get_settings),
    max_entries: int = Query(default=5000, ge=1, le=20000),
    max_depth: int = Query(default=10, ge=1, le=20),
) -> dict:
    """Return the workspace tree (files + directories, sorted).

    The M10 inspector pane renders this. Hidden dotfile directories
    are skipped EXCEPT ``.smolcode`` (so the user sees the uploads
    folder). Common noise dirs (``.git``, ``__pycache__``,
    ``node_modules``, ``.venv``, ``venv``, ``.tox``) are skipped.
    """
    try:
        entries, truncated = walk_tree(
            settings.workspace,
            max_entries=max_entries,
            max_depth=max_depth,
        )
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return WorkspaceTreeResponse(
        workspace=str(settings.workspace),
        entries=[
            TreeEntryOut(
                name=e.name,
                rel_path=e.rel_path,
                is_dir=e.is_dir,
                size=e.size,
                mtime=e.mtime,
            ).model_dump()
            for e in entries
        ],
        truncated=truncated,
    ).model_dump()


# ---- M11: provider / model catalog (decision 0014) ----------------------


@router.get("/providers", response_model=ProviderListResponse)
def list_providers() -> dict:
    """Return the static provider catalog.

    ``key_state`` reflects ONLY in-process env state. The SPA overlays
    its own locally-stored key state (``keysStore``) on the client
    side. This endpoint is safe to cache: it depends solely on the
    module-level PROVIDERS tuple + the per-process model cache.

    M12 (decision 0015): each row now also carries ``cached_at``
    (epoch seconds of the most recent /models fetch for that provider,
    or ``None`` if the cache is empty). The SPA uses this to render
    the inline ``<ModelAgeBadge>`` ("just now" / "5m ago" / "stale").

    M12.4: also carries ``cached_error`` (a short single-line error
    string when the most recent fetch failed, else ``None``). The SPA
    renders this as a warning-style badge so users see that the cached
    list may be stale. Both fields additive.
    """
    env_keys = _collect_env_keys()
    rows = _catalog_get_providers(env_keys)
    return ProviderListResponse(
        providers=[
            ProviderOut(
                id=r["id"],
                name=r["name"],
                env_vars=list(r["env_vars"]),
                default_model=r["default_model"],
                key_state=r["key_state"],
                model_count=r.get("model_count"),
                host_env_var=r.get("host_env_var"),
                cached_at=r.get("cached_at"),
                cached_error=r.get("cached_error"),
            ).model_dump()
            for r in rows
        ]
    ).model_dump()


@router.get("/providers/{provider_id}/models", response_model=ModelListResponse)
def list_provider_models(
    provider_id: str,
    refresh: bool = Query(default=False, description="Bypass the 1h TTL and re-fetch."),
) -> dict:
    """Return the model list for ``provider_id``.

    This endpoint fetches the provider's ``/models`` endpoint using
    KEY VALUES PRESENT IN PROCESS ENV ONLY. To use keys supplied
    through the SPA, the SPA must include them in the request body of
    ``POST /api/runs`` -- this GET endpoint never accepts user-supplied
    keys (otherwise an XSS or accident could exfiltrate them through
    a passive prefetch).
    """
    env_keys = _collect_env_keys()
    result = fetch_models(provider_id, keys=env_keys, refresh=refresh)
    return ModelListResponse(
        provider=provider_id,
        models=list(result.get("models", [])),
        cached=bool(result.get("cached", False)),
        fetched_at=float(result.get("fetched_at", 0.0) or 0.0),
        error=result.get("error"),
    ).model_dump()


# All env-var names the catalog recognises. Used by both provider /
# model endpoints to fold in-process env state into ``key_state`` /
# fetch-auth WITHOUT ever reading user-supplied keys.
_PROVIDER_ENV_VARS = (
    "OPENCODE_GO_APIKEY",
    "OPENCODE_HOST",
    "MINIMAX_API_KEY",
    "MINIMAX_HOST",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CUSTOM_API_KEY",
    "CUSTOM_BASE_URL",
    "HF_TOKEN",
)


def _collect_env_keys() -> dict[str, str]:
    """Return a dict of provider env-vars that are set in THIS process.

    Empty / unset entries are dropped. The result reflects the state
    of ``os.environ`` at the time of the request -- callers like
    ``get_providers`` and ``fetch_models`` then key-state / auth
    against it.
    """
    import os

    return {env: os.environ.get(env, "") for env in _PROVIDER_ENV_VARS if os.environ.get(env, "")}


# ---- Decision 0032: per-provider usage caps ("stop at $1") ---------------


def _known_providers() -> list[str]:
    """Return the list of provider ids the BE accepts on PUT.

    Built from ``model_catalog.PROVIDERS`` (the canonical catalog) plus
    the BE's default fallback set. ``minimax`` is rejected -- the
    canonical id is ``MiniMax`` (decision 0001) so we map any
    lower-case variant in the validator.
    """
    from ..model_catalog import PROVIDERS

    ids = sorted({p.id for p in PROVIDERS})
    # Ensure the canonical defaults from Settings.provider are included
    # even when model_catalog wasn't initialised yet (test fixtures).
    for fallback in ("opencode-go", "MiniMax", "openai", "anthropic", "custom"):
        if fallback not in ids:
            ids.append(fallback)
    return ids


def _current_spend_per_provider(settings, mgr) -> dict[str, float]:
    """Today's USD spend per provider, computed via the dashboard aggregator.

    Used by GET /api/cost-caps to surface "you have spent $X of your $Y
    cap today" without exposing the raw token buckets. Returns an
    empty dict on dashboard failure (broken settings / empty run list)
    so the SPA still renders a meaningful empty state.
    """
    audit_reader = SimpleNamespace(count_since=lambda t, level=None: _audit_count_since(None, t, level))
    try:
        dashboard = compute_dashboard(mgr, audit_reader, settings)
    except Exception:
        return {}
    return {
        prov: float(summary.cost_usd or 0.0)
        for prov, summary in (dashboard.by_provider or {}).items()
        if float(summary.cost_usd or 0.0) > 0
    }


@router.get("/cost-caps", response_model=CostCapsState)
def get_cost_caps(
    settings: Settings = Depends(get_settings),
    mgr: RunManager = Depends(get_run_manager),
    tracker: CostCapTracker = Depends(get_cost_cap_tracker),
) -> dict:
    """Decision 0032: GET /api/cost-caps.

    Returns the live cap state, the env-seeded defaults, the list of
    provider ids the BE knows about (for the SPA's dropdown), and
    today's per-provider USD spend so the SPA can render the
    "spend / cap" gauge without a follow-up GET /api/dashboard.
    """
    state = tracker.get_state()
    spend = _current_spend_per_provider(settings, mgr)
    return CostCapsState(
        caps=[{"provider": k, "cap_usd": v} for k, v in state["caps"].items()],
        defaults=[{"provider": k, "cap_usd": v} for k, v in state["defaults"].items()],
        providers=_known_providers(),
        current_spend_usd=spend,
    ).model_dump()


@router.put("/cost-caps", response_model=CostCapsUpdateResponse)
def put_cost_caps(
    req: CostCapsUpdateRequest,
    tracker: CostCapTracker = Depends(get_cost_cap_tracker),
) -> dict:
    """Decision 0032: PUT /api/cost-caps.

    Replaces the live cap state with ``req.caps`` (after the tracker's
    internal clean: bools rejected, non-numeric dropped, <= 0 dropped).
    Unknown provider ids are rejected with HTTP 400 BEFORE touching
    the tracker -- a typo in the SPA's provider switcher must not
    silently disable enforcement. The canonical id is ``MiniMax``
    (capital X); the alias ``minimax`` (any case) is rejected with
    400 so the SPA can surface a clear "use MiniMax" hint.
    """
    known = set(_known_providers())
    rejected_aliases = {"minimax", "MINIMAX", "minimax", "MiniMax-Go", "minimax-go"}
    for prov in (req.caps or {}).keys():
        if prov in rejected_aliases and prov != "MiniMax":
            raise HTTPException(status_code=400, detail="unknown provider: " + prov)
        if prov not in known:
            raise HTTPException(status_code=400, detail="unknown provider: " + prov)
    cleaned = tracker.update(req.caps or {})
    state = tracker.get_state()
    return CostCapsUpdateResponse(
        caps=[{"provider": k, "cap_usd": v} for k, v in cleaned.items()],
        defaults=[{"provider": k, "cap_usd": v} for k, v in state["defaults"].items()],
        providers=_known_providers(),
        updated_at=float(time.time()),
    ).model_dump()
