"""FastAPI app factory + uvicorn launcher (M8 + M9, decision 0010 D1, D2).

create_app(settings=None) -> FastAPI
    Build a fresh app with shared state. Used by tests + run_server.

run_server(host, port, log_level, ...) -> None
    Blocking uvicorn launcher. Enforces host in ALLOWED_BIND_HOSTS.

ALLOWED_BIND_HOSTS = ("127.0.0.1", "localhost", "::1")
    Anything else is REJECTED. The server never binds to a public
    interface. This is a hard security boundary per decision 0010.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..audit import AuditSink
from ..config import Settings, load_settings
from ..uploads import DEFAULT_ALLOWED_MIME, DEFAULT_MAX_BYTES, UploadsStore
from .api import router as api_router
from .cost_caps import CostCapTracker
from .runs import RunManager


ALLOWED_BIND_HOSTS = ("127.0.0.1", "localhost", "::1")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app bound to the given Settings."""
    if settings is None:
        settings = load_settings()

    # M11 (decision 0014): install the secret-redacting LogRecord
    # factory up-front so any logger -- including uvicorn's access /
    # error log and smolcode's own _log -- scrubs known token
    # prefixes before the formatter emits them. The filter is
    # idempotent (see redact.install_redact_filter).
    from ..redact import install_redact_filter

    install_redact_filter()

    audit: AuditSink | None = None

    uploads_store = UploadsStore(
        settings.uploads_dir,
        max_bytes=settings.upload_max_bytes or DEFAULT_MAX_BYTES,
        allowed_mime=settings.upload_allowed_mime or DEFAULT_ALLOWED_MIME,
        audit=audit,
    )

    # Decision 0032: per-provider usage caps ("stop at $1"). Seeded
    # from ``Settings.cost_caps`` (the SMOLCODE_COST_CAPS JSON env var)
    # so an operator who configures caps at boot has them live WITHOUT
    # a follow-up PUT. The tracker is shared with ``RunManager`` so the
    # per-day run-start check can consult it without re-reading settings.
    cost_cap_tracker = CostCapTracker(defaults=settings.cost_caps or {})

    # M9: run manager is shared across requests.
    run_manager = RunManager(cost_cap_tracker=cost_cap_tracker)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.uploads_store = uploads_store
        app.state.audit_sink = audit
        app.state.cost_cap_tracker = cost_cap_tracker
        app.state.run_manager = run_manager
        # Phase 1 (C2): refuse to serve when sandboxed runs are configured
        # but the tier images are missing/stale and cannot be built. Local-
        # executor deployments are unaffected.
        if getattr(settings, "executor", "") == "docker":
            import anyio

            from ..images import ImageBuildError, ensure_tier_images

            def _ensure():
                from ..images import SANDBOXED_TIERS

                ensure_tier_images(settings, SANDBOXED_TIERS)

            try:
                await anyio.to_thread.run_sync(_ensure)
            except ImageBuildError as e:
                raise RuntimeError("sandbox images not available; refusing to start web server: " + str(e)) from e
        try:
            yield
        finally:
            pass

    app = FastAPI(
        title="smolcode viewer",
        version="0.1.0",
        description="Local read-only viewer + upload API for smolcode (M8 + M9).",
        lifespan=lifespan,
    )
    app.include_router(api_router)

    spa_dir = Path(__file__).resolve().parents[3] / "web" / "dist"
    if spa_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(spa_dir), html=True), name="spa")

    return app


def run_server(
    host: str = "127.0.0.1",
    port: int = 7860,
    log_level: str = "info",
    no_browser: bool = False,
    settings: Settings | None = None,
) -> None:
    if host not in ALLOWED_BIND_HOSTS:
        raise ValueError(
            "host "
            + repr(host)
            + " is not in ALLOWED_BIND_HOSTS="
            + repr(ALLOWED_BIND_HOSTS)
            + ". The web server binds to loopback only."
        )

    try:
        import uvicorn
    except ImportError as e:
        raise RuntimeError("uvicorn is not installed. Install with: uv pip install -e .[web]") from e

    app = create_app(settings=settings)
    config = uvicorn.Config(
        app=app,
        host=host,
        port=int(port),
        log_level=log_level,
        access_log=False,
    )
    server = uvicorn.Server(config)

    if not no_browser:
        import threading
        import time
        import webbrowser

        def _open_browser():
            for _ in range(50):
                if server.started:
                    break
                time.sleep(0.1)
            if server.started:
                try:
                    webbrowser.open("http://" + host + ":" + str(port) + "/")
                except Exception:
                    pass

        threading.Thread(target=_open_browser, daemon=True).start()

    server.run()
