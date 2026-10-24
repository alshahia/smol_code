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

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..audit import AuditSink
from ..config import Settings, load_settings
from ..uploads import DEFAULT_ALLOWED_MIME, DEFAULT_MAX_BYTES, UploadsStore
from .api import router as api_router
from .cost_caps import CostCapTracker
from .runs import RunManager
from .spa import spa_is_stale


ALLOWED_BIND_HOSTS = ("127.0.0.1", "localhost", "::1")

# 2026-10-24 repair assessment (Phase 7 / A4 hardening): the Host header is
# validated too, not just the bind address. "testserver" is Starlette's
# TestClient default and cannot be resolved by a browser, so keeping it
# listed is safe and lets the suite exercise the middleware.
WEB_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1", "testserver")

_log = logging.getLogger("smolcode.web")


def create_app(settings: Settings | None = None, *, no_audit: bool = False) -> FastAPI:
    """Build a FastAPI app bound to the given Settings.

    Phase 2 (H5): unless ``no_audit=True`` is passed, ONE AuditSink is
    constructed exactly like cli.py resolves it (SMOLCODE_AUDIT_LOG
    override, else ``<cwd>/logs/audit.jsonl``) and shared by the
    uploads store, the run manager, and GET /api/audit. Web-started
    runs therefore leave the same tamper-evident trail CLI runs do.
    Sink construction failure refuses the boot (fail-closed).
    """
    if settings is None:
        settings = load_settings()

    # M11 (decision 0014): install the secret-redacting LogRecord
    # factory up-front so any logger -- including uvicorn's access /
    # error log and smolcode's own _log -- scrubs known token
    # prefixes before the formatter emits them. The filter is
    # idempotent (see redact.install_redact_filter).
    from ..redact import install_redact_filter

    install_redact_filter()

    # Phase 2 (H5): real per-app audit sink. ``None`` only when the
    # operator explicitly opted out via ``no_audit=True`` (the web
    # equivalent of the CLI --no-audit flag); every consumer then
    # sees the documented no-sink behaviour.
    audit: AuditSink | None = None
    if not no_audit:
        from ..audit import default_audit_path as _default_audit_path

        try:
            audit = AuditSink(_default_audit_path())
        except Exception as e:
            raise RuntimeError("audit sink init failed; refusing to start web server: " + str(e)) from e

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

    # M9: run manager is shared across requests. Phase 2 (H5): the
    # manager also receives the default audit sink so queued runs,
    # retries and reruns started without an explicit audit argument
    # still land in the SAME tamper-evident log.
    #
    # Phase 4 (decision 0039): the manager also receives ``settings`` so the
    # queue drain can start the next queued run without reaching back through
    # request-scoped FastAPI dependencies. ``app.state.settings`` is replaced
    # whenever a project is created/deleted, so sync that here too --
    # otherwise a queued run would start against the boot-time settings.
    run_manager = RunManager(cost_cap_tracker=cost_cap_tracker, audit_sink=audit, settings=settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        # Phase 4 (decision 0039): keep the manager's copy of settings in
        # sync with the live one. create_project / delete_project replace
        # app.state.settings; a queued run drained after that must see the
        # new project list, not the boot-time snapshot.
        run_manager._settings = settings
        app.state.uploads_store = uploads_store
        app.state.audit_sink = audit
        app.state.cost_cap_tracker = cost_cap_tracker
        app.state.run_manager = run_manager
        # Phase 1 (C2): refuse to serve when sandboxed runs are configured
        # but the tier images are missing/stale and cannot be built. Local-
        # executor deployments are unaffected.
        if getattr(settings, "executor", "") == "docker":
            import anyio
            from docker.errors import DockerException

            from ..images import ImageBuildError, ensure_tier_images

            def _ensure():
                from ..container import ensure_internal_network
                from ..images import SANDBOXED_TIERS

                ensure_tier_images(settings, SANDBOXED_TIERS)
                # A4 (2026-10-24 assessment): the CLI provisions the
                # restricted-tier internal bridge; the web server did not,
                # so restricted web runs failed on a fresh Docker host with
                # "network smolcode-internal not found". Fail closed like the
                # image check: a missing/denied network refuses the boot.
                ensure_internal_network()

            try:
                await anyio.to_thread.run_sync(_ensure)
            except (ImageBuildError, DockerException) as e:
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

    # Phase 7 hardening (2026-10-24 assessment): reject unexpected Host
    # headers so a DNS-rebinding page cannot drive this loopback server
    # through a browser. Bind-address validation alone does not cover that.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(WEB_ALLOWED_HOSTS))

    spa_dir = Path(__file__).resolve().parents[3] / "web" / "dist"
    if spa_dir.is_dir():
        # Step 0.3: never serve a stale bundle silently. The bundle is a
        # generated artifact; if src/ is newer than dist/index.html the
        # operator is looking at old UI (an 8h-stale bundle was found at
        # HEAD on 2026-10-24). Warn loudly; GET /api/health also reports it.
        if spa_is_stale(spa_dir):
            _log.warning(
                "SPA bundle at %s is older than the frontend sources; run 'pnpm build' in smolcode/web",
                spa_dir,
            )
        app.mount("/", StaticFiles(directory=str(spa_dir), html=True), name="spa")

    return app


def run_server(
    host: str = "127.0.0.1",
    port: int = 7860,
    log_level: str = "info",
    no_browser: bool = False,
    settings: Settings | None = None,
    no_audit: bool = False,
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

    app = create_app(settings=settings, no_audit=no_audit)
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
