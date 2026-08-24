"""Shared FastAPI dependencies (M8 + M9).

The deps return singletons derived from the Settings object passed to
create_app. They are reset on every app creation (so tests can pass
fresh settings).
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..audit import AuditSink
from ..config import Settings
from ..uploads import UploadsStore
from .runs import RunManager


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="server not initialised")
    return settings


def get_uploads_store(request: Request) -> UploadsStore:
    store = getattr(request.app.state, "uploads_store", None)
    if store is not None:
        return store
    settings = get_settings(request)
    audit = get_audit_sink(request)
    store = UploadsStore(
        settings.uploads_dir,
        max_bytes=settings.upload_max_bytes,
        allowed_mime=settings.upload_allowed_mime,
        audit=audit,
    )
    request.app.state.uploads_store = store
    return store


def get_audit_sink(request: Request) -> AuditSink | None:
    """Return the per-app AuditSink (None if --no-audit was passed)."""
    return getattr(request.app.state, "audit_sink", None)


def get_run_manager(request: Request) -> RunManager:
    """Return the per-app RunManager (M9).

    Lazily created on first access. Stored on app.state so all
    requests share the same instance -- which is the whole point of
    a run registry.
    """
    mgr = getattr(request.app.state, "run_manager", None)
    if mgr is None:
        mgr = RunManager()
        request.app.state.run_manager = mgr
    return mgr
