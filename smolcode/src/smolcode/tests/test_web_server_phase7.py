"""Phase 7 / Step 0.3 web-server hardening (2026-10-24 assessment).

Covers:
- Host-header validation (TrustedHostMiddleware) rejects DNS-rebinding hosts
  while still accepting loopback names.
- SPA bundle freshness detection and the boot warning (Step 0.3).
- Web boot provisions the restricted-tier internal Docker network (A4).

No Docker daemon is required: the docker path is monkeypatched.
"""

from __future__ import annotations

import os
import time

from smolcode.config import Settings, _default_tiers


def _settings(tmp_path, executor="local"):
    return Settings(
        workspace=tmp_path,
        executor=executor,
        provider="opencode-go",
        model="m",
        litellm_proxy=None,
        log_level="INFO",
        tiers=_default_tiers(),
        uploads_dir=tmp_path / "uploads",
        upload_max_bytes=1024,
        upload_allowed_mime=("text/",),
    )


class TestHostHeaderValidation:
    def test_untrusted_host_is_rejected(self, tmp_path):
        from fastapi.testclient import TestClient

        from smolcode.web import create_app

        app = create_app(settings=_settings(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/api/health", headers={"host": "evil.example.com"})
        assert resp.status_code == 400
        assert "Invalid host header" in resp.text

    def test_loopback_and_testserver_hosts_are_allowed(self, tmp_path):
        from fastapi.testclient import TestClient

        from smolcode.web import create_app

        app = create_app(settings=_settings(tmp_path))
        with TestClient(app, base_url="http://127.0.0.1:7860") as client:
            assert client.get("/api/health").status_code == 200
        with TestClient(app, base_url="http://localhost:7860") as client:
            assert client.get("/api/health").status_code == 200


class TestSpaFreshness:
    def _dirs(self, tmp_path):
        dist = tmp_path / "dist"
        src = tmp_path / "web"
        (dist).mkdir()
        (src / "src").mkdir(parents=True)
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        (src / "src" / "factory.ts").write_text("x", encoding="utf-8")
        return dist, src

    def _age(self, path, seconds_ago):
        stamp = time.time() - seconds_ago
        os.utime(path, (stamp, stamp))

    def test_stale_when_sources_are_newer(self, tmp_path):
        from smolcode.web.spa import spa_is_stale

        dist, src = self._dirs(tmp_path)
        self._age(dist / "index.html", 120)
        self._age(src / "src" / "factory.ts", 10)
        assert spa_is_stale(dist, src) is True

    def test_not_stale_when_bundle_is_newer(self, tmp_path):
        from smolcode.web.spa import spa_is_stale

        dist, src = self._dirs(tmp_path)
        self._age(src / "src" / "factory.ts", 120)
        self._age(dist / "index.html", 10)
        assert spa_is_stale(dist, src) is False

    def test_missing_bundle_is_not_stale(self, tmp_path):
        from smolcode.web.spa import spa_is_stale

        assert spa_is_stale(tmp_path / "nope", tmp_path / "web") is False

    def test_boot_warns_when_bundle_is_stale(self, tmp_path, monkeypatch, caplog):
        import logging

        from smolcode.web import create_app

        # Inject a dist/ that exists: CI checkouts have no built SPA, and the
        # warning only fires when create_app mounted a bundle.
        dist, _src = self._dirs(tmp_path)
        monkeypatch.setattr("smolcode.web.server._spa_dist_dir", lambda: dist)
        monkeypatch.setattr("smolcode.web.server.spa_is_stale", lambda *a, **k: True)
        with caplog.at_level(logging.WARNING, logger="smolcode.web"):
            create_app(settings=_settings(tmp_path))
        assert any("older than the frontend sources" in rec.message for rec in caplog.records)


class TestBootProvisionsInternalNetwork:
    def test_docker_boot_provisions_images_and_network(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from smolcode.web import create_app

        calls = []
        monkeypatch.setattr("smolcode.images.ensure_tier_images", lambda *a, **k: calls.append("images") or [])
        monkeypatch.setattr("smolcode.container.ensure_internal_network", lambda *a, **k: calls.append("network"))
        app = create_app(settings=_settings(tmp_path, executor="docker"))
        with TestClient(app):
            pass
        assert calls == ["images", "network"]
