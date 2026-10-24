"""Phase 8 (decision 0043): real `GET /api/health` snapshot.

Covers `web/health.build_health_snapshot` (unit, fake Docker client + fake run
manager) and the endpoint itself (TestClient). No Docker daemon is required:
the probe is injected, and the API test starts the app under the local executor
then swaps in docker settings.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from smolcode import images
from smolcode.config import load_settings
from smolcode.web import health
from smolcode.web.health import build_health_snapshot


# ---- fakes -----------------------------------------------------------------


class _FakeImages:
    def __init__(self, labels_by_tag, missing=()):
        self.labels_by_tag = labels_by_tag
        self.missing = set(missing)

    def get(self, tag):
        if tag in self.missing:
            raise RuntimeError("image not found: " + tag)
        return SimpleNamespace(labels=dict(self.labels_by_tag.get(tag, {})))


class _FakeDocker:
    def __init__(self, labels_by_tag=None, missing=()):
        self.images = _FakeImages(labels_by_tag or {}, missing)


class _FakeRun:
    def __init__(self, run_id, status, thread=None):
        self.id = run_id
        self.status = status
        self.thread = thread


class _FakeManager:
    def __init__(self, runs=(), queued=(), drain_error=None):
        self._runs = list(runs)
        self._queue = list(queued)
        self.queue_drain_error = drain_error

    def list(self):
        return list(self._runs)

    def queue(self):
        return list(self._queue)


class _FakeStore:
    def __init__(self, directory, count=0):
        self.dir = directory
        self._count = count

    def list_metadata(self):
        return list(range(self._count))


def _current_labels(settings):
    """Labels that make every tier image look CURRENT to the hash check."""
    return {
        settings.tiers[tier].docker_image: {images.IMAGE_SRC_LABEL: images.source_hash(tier)}
        for tier in images.SANDBOXED_TIERS
    }


@pytest.fixture
def settings():
    return load_settings()


# ---- unit tests ------------------------------------------------------------


class TestSnapshotBody:
    def test_healthy_local_executor(self, settings, monkeypatch):
        monkeypatch.setattr(health, "_spa_stale", lambda: False)
        payload, status_code = build_health_snapshot(
            settings,
            _FakeManager(),
            _FakeStore("uploads-dir", count=2),
            docker_client=_FakeDocker(_current_labels(settings)),
        )
        assert status_code == 200
        assert payload["status"] == "ok"
        assert payload["docker"] == "reachable"
        assert payload["images"] == {tier: "current" for tier in images.SANDBOXED_TIERS}
        assert payload["queue_depth"] == 0
        assert payload["active_run"] is None
        assert payload["queue_drain_error"] is None
        assert payload["spa_stale"] is False
        # Legacy keys must survive unchanged (backward compatibility).
        assert payload["version"]
        assert payload["uploads_dir"] == "uploads-dir"
        assert payload["uploads_count"] == 2

    def test_docker_executor_with_dead_daemon_is_503(self, settings, monkeypatch):
        monkeypatch.setattr(health, "probe_docker", lambda timeout_s=health.DOCKER_PROBE_TIMEOUT_S: (None, "boom"))
        docker_settings = settings.with_executor("docker")
        payload, status_code = build_health_snapshot(docker_settings, _FakeManager(), _FakeStore("u"))
        assert status_code == 503
        assert payload["status"] == "unhealthy"
        assert payload["docker"] == "unreachable"
        # No daemon -> image state is honestly unknown, not a false "current".
        assert payload["images"] == {tier: "unknown" for tier in images.SANDBOXED_TIERS}

    def test_local_executor_with_dead_daemon_stays_200(self, settings, monkeypatch):
        monkeypatch.setattr(
            health, "probe_docker", lambda timeout_s=health.DOCKER_PROBE_TIMEOUT_S: (None, "no daemon")
        )
        payload, status_code = build_health_snapshot(settings, _FakeManager(), _FakeStore("u"))
        assert status_code == 200
        assert payload["status"] == "ok"
        assert payload["docker"] == "unreachable"
        assert payload["images"] == {tier: "unknown" for tier in images.SANDBOXED_TIERS}

    def test_stale_image_degrades_but_stays_200(self, settings, monkeypatch):
        monkeypatch.setattr(health, "_spa_stale", lambda: False)
        labels = _current_labels(settings)
        labels[settings.tiers["elevated"].docker_image] = {images.IMAGE_SRC_LABEL: "0" * 64}
        payload, status_code = build_health_snapshot(
            settings, _FakeManager(), _FakeStore("u"), docker_client=_FakeDocker(labels)
        )
        assert status_code == 200
        assert payload["status"] == "degraded"
        assert payload["images"]["elevated"] == "stale"
        assert payload["images"]["restricted"] == "current"

    def test_missing_image_is_reported(self, settings, monkeypatch):
        monkeypatch.setattr(health, "_spa_stale", lambda: None)
        labels = _current_labels(settings)
        missing = settings.tiers["full_access"].docker_image
        payload, status_code = build_health_snapshot(
            settings, _FakeManager(), _FakeStore("u"), docker_client=_FakeDocker(labels, missing=[missing])
        )
        assert status_code == 200
        assert payload["status"] == "degraded"
        assert payload["images"]["full_access"] == "missing"
        assert payload["spa_stale"] is None

    def test_queue_and_active_run_reported(self, settings, monkeypatch):
        monkeypatch.setattr(health, "_spa_stale", lambda: False)
        manager = _FakeManager(
            runs=[_FakeRun("done-run", "done"), _FakeRun("live-run", "running")],
            queued=["a", "b"],
            drain_error="boom during drain",
        )
        payload, _ = build_health_snapshot(
            settings, manager, _FakeStore("u"), docker_client=_FakeDocker(_current_labels(settings))
        )
        assert payload["queue_depth"] == 2
        assert payload["active_run"] == "live-run"
        assert payload["queue_drain_error"] == "boom during drain"

    def test_partial_state_never_raises(self, settings, monkeypatch):
        monkeypatch.setattr(health, "_spa_stale", lambda: False)

        class _BrokenManager:
            def list(self):
                raise RuntimeError("list exploded")

            def queue(self):
                raise RuntimeError("queue exploded")

        payload, status_code = build_health_snapshot(
            settings, _BrokenManager(), None, docker_client=_FakeDocker(_current_labels(settings))
        )
        assert status_code == 200
        assert payload["queue_depth"] == 0
        assert payload["active_run"] is None
        assert payload["uploads_dir"] == ""
        assert payload["uploads_count"] == 0

    def test_probe_docker_wraps_failure_without_raising(self, monkeypatch):
        import docker

        def _boom(**kwargs):
            raise RuntimeError("pipe missing")

        monkeypatch.setattr(docker, "from_env", _boom)
        client, error = health.probe_docker()
        assert client is None
        assert "RuntimeError" in error

    def test_spa_stale_uses_phase7_helper_when_available(self, monkeypatch):
        # spa.py exists in this tree; patch it to prove the lazy import is used.
        import smolcode.web.spa as spa_module

        monkeypatch.setattr(spa_module, "spa_is_stale", lambda: True)
        assert health._spa_stale() is True


# ---- endpoint tests --------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path / "ws"))
    from smolcode.web import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_endpoint_returns_additive_keys(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    for legacy in ("version", "uploads_dir", "uploads_count"):
        assert legacy in body
    for added in ("docker", "images", "queue_depth", "active_run", "queue_drain_error", "spa_stale"):
        assert added in body, added


def test_endpoint_503_when_docker_executor_and_daemon_down(client, monkeypatch):
    from smolcode.web import health as health_module

    monkeypatch.setattr(health_module, "probe_docker", lambda timeout_s=2.0: (None, "dead"))
    app = client.app
    app.state.settings = app.state.settings.with_executor("docker")
    response = client.get("/api/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["docker"] == "unreachable"
    # Legacy consumers still get their keys on the failure path.
    assert body["version"]
    assert "uploads_dir" in body
