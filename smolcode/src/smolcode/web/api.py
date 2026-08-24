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

Provider / model catalog endpoints (M11, decision 0014):
    GET  /api/providers                          -> catalog (key_state + defaults)
    GET  /api/providers/{provider_id}/models     -> live /models list (1h TTL)

The /api/runs endpoint now accepts three optional fields:
``provider``, ``model``, ``keys`` (decision 0014). All are optional
so existing callers stay backwards-compatible.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from .. import __version__
from ..audit import AuditSink
from ..audit_reader import audit_chain_status, read_audit_entries
from ..config import Settings, as_dict
from ..model_catalog import fetch_models
from ..model_catalog import get_providers as _catalog_get_providers
from ..uploads import UploadsStore
from .deps import get_audit_sink, get_run_manager, get_settings, get_uploads_store
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
    CleanRequest,
    ConfigResponse,
    HealthResponse,
    ModelListResponse,
    ProviderListResponse,
    ProviderOut,
    RunListResponse,
    RunStartRequest,
    RunStartResponse,
    RunSummary,
    SessionEntry,
    SessionEvent,
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


@router.get("/sessions")
def get_sessions(settings: Settings = Depends(get_settings)) -> dict:
    sessions_dir = Path(settings.workspace) / "sessions"
    entries = []
    if sessions_dir.exists():
        for f in sorted(sessions_dir.glob("*.jsonl"), reverse=True):
            try:
                stat = f.stat()
                entries.append(
                    SessionEntry(
                        id=f.stem,
                        path=str(f),
                        size_bytes=stat.st_size,
                        mtime_iso=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    ).model_dump()
                )
            except OSError:
                continue
    return {"sessions": entries}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, settings: Settings = Depends(get_settings)) -> dict:
    if "/" in session_id or "\\" in session_id or session_id.startswith("."):
        raise HTTPException(status_code=400, detail="invalid session id")
    sessions_dir = Path(settings.workspace) / "sessions"
    target = sessions_dir / (session_id + ".jsonl")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="session not found")
    events = []
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(
            SessionEvent(
                ts=entry.get("ts", ""),
                event=entry.get("event", ""),
                raw=entry,
            ).model_dump()
        )
    return {"id": session_id, "events": events}


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
    duration = None
    if run.ended_at is not None:
        duration = max(0.0, run.ended_at - run.started_at)
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
        run_id = mgr.start_run(
            task=req.task.strip(),
            tier=req.tier,
            settings=settings,
            audit=audit,
            provider_override=req.provider,
            model_override=req.model,
            api_key_value=api_key_value,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RunStartResponse(run_id=run_id, status="running").model_dump()


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
