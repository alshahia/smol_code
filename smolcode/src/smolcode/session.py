"""Per-run session state (M4.x, decision 0007).

The CLI sets a SessionState at the start of main() and clears it
at the end. Host-side tools (git, shell) read auto_approve_destructive
from the session via current_session() and consult the confirm
callback before executing destructive operations.

Why a module-level singleton? The tool's forward() runs on the host
(not in the Docker container) but doesn't have a reference to the
calling cli.py:main() stack frame. A module-level registry gives
host tools a way to find the session without importing cli (which
would create a circular import + make the tool untestable in
isolation).

Threading: SessionState is mutated by the confirm callback (in the
agent loop's thread) and read by tool forward() (also in the agent
loop's thread). Both run on the same thread for smolagents' current
loop architecture; we use a Lock anyway so future async / multi-
agent code is safe.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass
class DestructiveDecision:
    """Result of a destructive-op confirmation prompt."""

    approved: bool
    auto_approve_now: bool = False  # user typed `a` -> flip auto-approve ON for rest of run
    auto_approve_off: bool = False  # user typed `o` -> flip auto-approve OFF for rest of run
    reason: str = ""  # why approved/denied (e.g. "timeout", "user-denied", "user-approved")


# Callback signature: given (tool_name, kwargs, summary) -> DestructiveDecision.
# The session owner (CLI) installs the real one that calls
# confirm.prompt_destructive(); tests install a fake.
DestructiveCallback = Callable[[str, dict, str], DestructiveDecision]


# M10: diff-gate callback. Used by the web GUI to gate every
# ``write_file`` / ``patch_file`` call. The tool's forward() reads
# the file's current content (``before``), computes the proposed
# ``after``, and calls the callback with all of that. The callback
# may approve, deny, or approve with an edited ``after`` text.
@dataclass
class DiffDecision:
    """Result of a write_file / patch_file diff gate."""

    approved: bool
    edited_after: str | None = None  # if approved and edited, replace the proposed content
    auto_approve_now: bool = False  # flip auto_approve_diff ON for rest of run
    reason: str = ""


# Callback signature: given (tool_name, kwargs, path, before, after,
# summary) -> DiffDecision.
DiffCallback = Callable[[str, dict, str, str, str, str], DiffDecision]


@dataclass
class SessionState:
    """Per-run mutable state read by host-side tools."""

    tier: str = "restricted"
    auto_approve_destructive: bool = False
    confirm_callback: DestructiveCallback | None = None
    # Optional audit sink so destructive decisions + checkpoints
    # land in the run's JSONL.
    audit_sink: Any = None  # AuditSink | None
    # M10: diff gate. When set, write_file and patch_file forward()
    # call this before touching disk. Empty default -> tools behave
    # exactly as before (CLI / tests without a web session).
    diff_callback: DiffCallback | None = None
    auto_approve_diff: bool = False  # flipped by auto_approve_now=True in DiffDecision
    # v1.9.x / decision 0027: the run id this session belongs to.
    # ``None`` for CLI sessions (no run id) and for the default
    # SessionState returned by current_session() when no session is
    # installed. The web's POST /api/runs/{id}/auto-approve endpoint
    # uses this to validate that the caller is targeting the run that
    # currently owns the singleton (RunManager only allows one active
    # run, but the endpoint is called over HTTP and may target a
    # stale id).
    run_id: str | None = None


_session: SessionState | None = None
_session_lock = threading.Lock()


def set_session(session):
    """Install the active session. Pass None to clear."""
    global _session
    with _session_lock:
        _session = session


def get_session():
    """Return the active session, or None if none is installed."""
    with _session_lock:
        return _session


def current_session():
    """Return the active session, or a safe default if none installed.

        The default has auto_approve_destructive=False and a None
        confirm_callback. The None callback means "if you reach this,
    you're being called outside a smolcode run; deny for safety".
    """
    s = get_session()
    if s is None:
        return SessionState()
    return s


def _ensure_default_session():
    """Internal: install a default session if none exists. Used by
    host tools that want to be safe even if main() never ran."""
    global _session
    with _session_lock:
        if _session is None:
            _session = SessionState()


def set_auto_approve(run_id, enabled):
    """Flip the active session's ``auto_approve_destructive`` flag.

    Decision 0027: server-side auto-approve OFF endpoint. The web
    SPA's <AutoApproveBanner> calls this when the user clicks
    "Disable" so the underlying session stops auto-approving future
    destructive prompts. Also used by the ON path: when the user
    clicks "Approve + auto-approve" in the ApprovalModal, the FE
    mirrors that flip here so the BE's destructive gate sees it.

    Validation: the caller MUST pass the run id that owns the
    current session. Returns ``(ok, error)``:

    - ``(False, "no active session")`` when ``set_session(None)`` was
      called (run already ended) or no session was ever installed.
    - ``(False, "session is for a different run")`` when the active
      session's ``run_id`` does not match ``run_id`` (the FE called
      against a stale run id).
    - ``(True, None)`` on success.

    The flag flip is atomic under ``_session_lock`` so a concurrent
    tool forward() reading ``current_session().auto_approve_destructive``
    sees a consistent value (Lock held only for the assignment).
    """
    global _session
    with _session_lock:
        s = _session
        if s is None:
            return False, "no active session"
        if s.run_id is not None and s.run_id != run_id:
            return False, "session is for a different run"
        # When the session has no run_id (CLI), trust the caller and
        # flip unconditionally. CLI tests install SessionState() with
        # run_id=None.
        s.auto_approve_destructive = bool(enabled)
    return True, None


def get_auto_approve(run_id):
    """Return the active session's ``auto_approve_destructive`` flag.

    Returns ``None`` when no active session is installed OR when the
    active session's ``run_id`` does not match ``run_id``. Returns
    the boolean flag value on a match (or on a session with no
    run_id, e.g. CLI). Used by the FE to refresh the banner state
    on page reload / cross-run navigation.
    """
    with _session_lock:
        s = _session
        if s is None:
            return None
        if s.run_id is not None and s.run_id != run_id:
            return None
        return bool(s.auto_approve_destructive)


__all__ = [
    "DestructiveCallback",
    "DestructiveDecision",
    "DiffCallback",
    "DiffDecision",
    "SessionState",
    "current_session",
    "get_session",
    "set_session",
    # v1.9.x / decision 0027: server-side auto-approve toggle helpers
    # used by POST /api/runs/{id}/auto-approve.
    "set_auto_approve",
    "get_auto_approve",
    # Phase 1 (decision 0025 §6.3): chat-session storage helpers.
    "resolve_project_root",
    "session_dir_for",
    "session_path_for",
    "create_session_file",
    "delete_session_file",
    "rename_session_file",
    "list_sessions",
    "read_session_events",
    "session_run_count",
    "safe_id",
]


# ============================================================================
# Phase 1 (decision 0025 §6.3): chat-session storage helpers
# ============================================================================
#
# A chat session is a JSONL file that accumulates ``run.started`` /
# ``run.ended`` events across many runs in one continuous conversation.
# Phase 0's /api/sessions + /api/sessions/{id} already read these files
# from ``<workspace>/sessions/``. Phase 1 extends the storage to be
# project-aware: a session can be scoped to one of the configured
# projects (``<project>/.smolcode/sessions/``) instead of the legacy
# ``<workspace>/sessions/``.
#
# Each session has TWO files:
# - ``<id>.jsonl``     the event log (append-only)
# - ``<id>.meta.json`` the user-editable name + metadata; renamed
#                      atomically via ``os.replace`` so the SPA cannot
#                      see a half-written state.
#
# The legacy ``<workspace>/sessions/`` layout is preserved when no
# project name is supplied -- existing SPA clients keep working.


# Allowed characters in a session id. URL-safe + filename-safe. We use
# the same alphabet as smolagents' Run id (lowercase hex) but allow
# hyphens for human-friendly labels.
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")


def safe_id(session_id):
    """Validate a session id. Raises ValueError on traversal / bad chars.

    Returns the id unchanged on success. Mirrors the existing
    ``api.get_session`` guard but lifted out so the helper functions
    below can call it before touching the filesystem.
    """
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("invalid session id: must be a non-empty string")
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError("invalid session id " + repr(session_id) + ": must match [a-zA-Z0-9][a-zA-Z0-9_-]{0,127}")
    return session_id


def _resolve_root(settings, project_name):
    """Return the filesystem root for ``project_name``.

    Resolution order:
    1. ``project_name is None`` -> ``settings.workspace`` (legacy mode)
    2. ``project_name`` matches one of ``settings.projects`` -> that root
    3. otherwise -> ``settings.workspace`` (lenient fallback; matches
       Phase 1's "empty projects list = legacy mode" semantics)
    """
    if project_name is None:
        return Path(settings.workspace)
    for p in settings.projects:
        if p.name == project_name:
            return Path(p.root)
    return Path(settings.workspace)


def resolve_project_root(settings, project_name):
    """Public wrapper around the project root resolver.

    Returns a Path (always; never None). Used by the API layer to
    determine where to read / write session files.
    """
    return _resolve_root(settings, project_name)


def session_dir_for(root, project=None):
    """Return the directory session files live under for the given root.

    Legacy mode (``project is None``): ``<root>/sessions/``.
    Project mode: ``<root>/.smolcode/sessions/`` (hidden + matches the
    uploads folder convention so users see one ``.smolcode`` dir per
    project).
    """
    root = Path(root)
    if project is None:
        return root / "sessions"
    return root / ".smolcode" / "sessions"


def session_path_for(root, project=None, session_id="default"):
    """Return the full path to a session's jsonl file."""
    safe_id(session_id)
    return session_dir_for(root, project) / (session_id + ".jsonl")


def _meta_path_for(jsonl_path):
    """Sibling metadata path: ``<id>.meta.json`` next to the jsonl."""
    return jsonl_path.with_suffix("").with_name(jsonl_path.stem + ".meta.json")


def _atomic_write_json(path, obj):
    """Write ``obj`` to ``path`` atomically (tmp + os.replace).

    Decision 0025 §6.3 risk register: ``meta.json`` rename is the one
    place the SPA could otherwise see a partial state. Use a temp
    file in the same directory + ``os.replace`` so the rename is
    atomic on POSIX and Windows.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        # Best-effort cleanup of the tmp file.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _new_session_id():
    """Generate a new session id (uuid4 hex, lowercase, no dashes)."""
    return uuid.uuid4().hex


def create_session_file(root, project=None, session_id=None, name=None):
    """Create a new session file (jsonl + meta.json). Returns the jsonl path.

    If ``session_id`` is None, a uuid4 hex is generated. ``name`` is
    stored in the sibling ``meta.json``. The jsonl starts empty (zero
    bytes) so the runner can append events as they fire.
    """
    root = Path(root)
    if session_id is None:
        session_id = _new_session_id()
    safe_id(session_id)
    sdir = session_dir_for(root, project)
    sdir.mkdir(parents=True, exist_ok=True)
    jsonl = sdir / (session_id + ".jsonl")
    meta = _meta_path_for(jsonl)
    if jsonl.exists():
        # Idempotent: if both files already exist with our expected
        # shape, return the existing path. Otherwise the caller is
        # asking us to overwrite -- refuse.
        raise FileExistsError("session " + session_id + " already exists at " + str(jsonl))
    jsonl.touch()
    _atomic_write_json(meta, {"name": name, "project": project, "created_at": datetime.now(timezone.utc).isoformat()})
    return jsonl


def delete_session_file(root, project=None, session_id=None):
    """Remove both jsonl + meta.json. Returns True if a file was removed."""
    safe_id(session_id)
    sdir = session_dir_for(root, project)
    jsonl = sdir / (session_id + ".jsonl")
    meta = _meta_path_for(jsonl)
    removed = False
    for p in (jsonl, meta):
        try:
            p.unlink()
            removed = True
        except FileNotFoundError:
            pass
    return removed


def rename_session_file(root, project=None, session_id=None, new_name=""):
    """Update the user-friendly label in meta.json (atomic write)."""
    safe_id(session_id)
    sdir = session_dir_for(root, project)
    jsonl = sdir / (session_id + ".jsonl")
    meta = _meta_path_for(jsonl)
    if not jsonl.exists():
        raise FileNotFoundError("session " + session_id + " not found at " + str(jsonl))
    if meta.exists():
        try:
            existing = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    else:
        existing = {}
    existing["name"] = new_name
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(meta, existing)


def _read_meta(meta_path):
    """Return the meta dict ({} on missing / corrupt)."""
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def session_run_count(jsonl_path):
    """Count the number of ``run.started`` events in the jsonl.

    Cheap O(n) scan; capped at the file size (the SPA only needs a
    hint for the session list).
    """
    n = 0
    try:
        with open(jsonl_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("event") == "run.started":
                    n += 1
    except OSError:
        return 0
    return n


def list_sessions(root, project=None):
    """Return a list of session metadata dicts (newest first).

    Shape mirrors ``SessionEntry``: id, path, size_bytes, mtime_iso,
    name, run_count, project. ``project`` is the explicit project
    name when known (legacy mode = None).
    """
    sdir = session_dir_for(root, project)
    out = []
    if not sdir.is_dir():
        return out
    for f in sorted(sdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = f.stat()
        except OSError:
            continue
        meta = _read_meta(_meta_path_for(f))
        out.append(
            {
                "id": f.stem,
                "path": str(f),
                "size_bytes": stat.st_size,
                "mtime_iso": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "name": meta.get("name"),
                "run_count": session_run_count(f),
                "project": project,
            }
        )
    return out


def read_session_events(jsonl_path):
    """Return a list of raw event dicts read from the jsonl.

    Garbage / blank lines are skipped silently so the SPA renders a
    clean timeline. Returns [] if the file does not exist.
    """
    jsonl_path = Path(jsonl_path)
    if not jsonl_path.is_file():
        return []
    out = []
    try:
        text = jsonl_path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(obj)
    return out
