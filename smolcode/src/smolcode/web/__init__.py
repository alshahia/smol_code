"""smolcode.web -- local FastAPI viewer + upload server (M8, decision 0010).

This package exposes:
    create_app(settings=None)  -> FastAPI
    run_server(host, port, ...) -> None  (blocking)

The server binds to 127.0.0.1 ONLY. Any attempt to bind to a public
interface is rejected (security boundary per decision 0010 D1).
"""

from __future__ import annotations

from .server import ALLOWED_BIND_HOSTS, create_app, run_server


__all__ = ["create_app", "run_server", "ALLOWED_BIND_HOSTS"]
