"""M8 - web server (create_app + run_server) tests."""

from __future__ import annotations

import os
import tempfile

import pytest


class TestBindHosts:
    def test_allowed_hosts_contains_loopback(self):
        from smolcode.web import ALLOWED_BIND_HOSTS

        assert "127.0.0.1" in ALLOWED_BIND_HOSTS
        assert "localhost" in ALLOWED_BIND_HOSTS
        assert "::1" in ALLOWED_BIND_HOSTS

    def test_allowed_hosts_excludes_public(self):
        from smolcode.web import ALLOWED_BIND_HOSTS

        assert "0.0.0.0" not in ALLOWED_BIND_HOSTS
        assert "" not in ALLOWED_BIND_HOSTS
        assert "192.168.0.1" not in ALLOWED_BIND_HOSTS

    def test_run_server_rejects_public_host(self):
        from smolcode.web import run_server

        with pytest.raises(ValueError, match="not in ALLOWED_BIND_HOSTS"):
            run_server(host="0.0.0.0", port=7860)


class TestCreateApp:
    def test_create_app_default_settings(self):
        from smolcode.web import create_app

        for k in list(os.environ):
            if k.startswith("SMOLCODE_"):
                del os.environ[k]
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SMOLCODE_WORKSPACE"] = tmp
            app = create_app()
            assert app.title == "smolcode viewer"
            paths = sorted({r.path for r in app.router.routes if hasattr(r, "path")})
            # Must include the read-only viewer + upload endpoints.
            assert "/api/health" in paths
            assert "/api/config" in paths
            assert "/api/tiers" in paths
            assert "/api/sessions" in paths
            assert "/api/audit" in paths
            assert "/api/uploads" in paths

    def test_create_app_with_settings(self, tmp_path):
        from smolcode.config import Settings, _default_tiers
        from smolcode.web import create_app

        settings = Settings(
            workspace=tmp_path,
            executor="docker",
            provider="opencode-go",
            model="m",
            litellm_proxy=None,
            log_level="INFO",
            tiers=_default_tiers(),
            uploads_dir=tmp_path / ".smolcode" / "uploads",
            upload_max_bytes=1024,
            upload_allowed_mime=("text/",),
        )
        app = create_app(settings=settings)
        # State is set by the lifespan handler; use a TestClient context
        # to actually run lifespan before inspecting state.
        from fastapi.testclient import TestClient

        with TestClient(app) as _client:
            assert app.state.settings is settings
            assert app.state.uploads_store is not None
