"""Phase 3 RED tests for F4 (POST /api/open-path endpoint).

Bug surface:
    There is no POST /api/open-path route today (Phase 0 manual probe).
    The Inspector cannot offer an "Open in Explorer" affordance because
    the BE has no endpoint that takes a path + run id and shells out to
    the platform-specific opener with a workspace whitelist.

The endpoint must:
    - accept {"path": "..."} (and optionally {"run_id": "..."} to scope to
      that run's effective_cwd)
    - resolve the absolute target and check it lives inside
      settings.workspace (or run.effective_cwd when a run_id is given)
    - return 200 {"opened": true} on success
    - return 403 with a clear reason on path-escape
    - shell out via the platform command (Windows: cmd /c start,
      macOS: open, Linux: xdg-open) with timeout 3 s
    - not actually pop a window during tests; the implementation must
      expose an "_open_external(path)" hook that tests can monkeypatch.

These tests FAIL today (RED) because the route is missing - 404 / 405
on every POST. They go GREEN after Phase 4 registers the route plus
the whitelist guard.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from smolcode.web import create_app

    monkeypatch.setenv("SMOLCODE_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestOpenPathScoping:
    """F4 - RED: POST /api/open-path is registered and whitelists paths
    inside settings.workspace (or run.effective_cwd)."""

    def test_route_is_registered_post(self, client):
        """RED today: 404 (no route) or 405 (method not allowed).
        Whichever, the implementation MUST register the route."""
        r = client.post("/api/open-path", json={"path": "."})
        assert r.status_code not in (404, 405), (
            "POST /api/open-path not registered: status=" + repr(r.status_code) + " body=" + r.text
        )

    def test_path_inside_workspace_returns_200(self, client, tmp_path, monkeypatch):
        """RED today: 404 (no route). After Phase 4: 200 {"opened": true}.

        Implementation contract: the implementation MUST expose an
        _open_external(path) helper in smolcode.web.api so tests can
        monkeypatch it and never pop a real Explorer window."""
        # Pre-create a file inside the workspace (conftest: workspace = tmp_path/ws).
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir(parents=True, exist_ok=True)
        target = ws_dir / "index.html"
        target.write_text("<html></html>")

        # Stub the implementation opener hook. raising=False because
        # _open_external may not exist yet (RED); after Phase 4 it must.
        import smolcode.web.api as _api_mod

        monkeypatch.setattr(_api_mod, "_open_external", lambda p: True, raising=False)

        r = client.post("/api/open-path", json={"path": str(target)})
        assert r.status_code == 200, r.text

    def test_path_outside_workspace_returns_403(self, client):
        """RED today: 404 (no route). After Phase 4: 403 with a
        reason mentioning workspace, forbidden, or path-escape."""
        r = client.post("/api/open-path", json={"path": "/etc/passwd"})
        assert r.status_code == 403, (
            "/api/open-path should reject paths outside settings.workspace"
            " with 403; got " + repr(r.status_code) + " body=" + r.text
        )

    def test_missing_path_returns_4xx(self, client):
        """RED today: 404 or 422. After Phase 4: 400 (path required)."""
        r = client.post("/api/open-path", json={})
        assert 400 <= r.status_code < 500, (
            "POST /api/open-path missing required path field should 4xx;"
            " got " + repr(r.status_code) + " body=" + r.text
        )
