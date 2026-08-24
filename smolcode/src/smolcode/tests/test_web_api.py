"""M8 - web API endpoint tests (uses TestClient)."""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    from smolcode.web import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "uploads_dir" in body
        assert body["uploads_count"] == 0


class TestConfig:
    def test_config_returns_settings(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200
        body = r.json()
        assert body["workspace"]
        assert body["provider"] == "opencode-go"
        assert len(body["tiers"]) == 3
        tier_names = {t["name"] for t in body["tiers"]}
        assert tier_names == {"restricted", "elevated", "full_access"}


class TestTiers:
    def test_tiers_returns_three(self, client):
        r = client.get("/api/tiers")
        assert r.status_code == 200
        body = r.json()
        assert set(body["tiers"].keys()) == {"restricted", "elevated", "full_access"}


class TestSessions:
    def test_sessions_empty(self, client):
        r = client.get("/api/sessions")
        assert r.status_code == 200
        assert r.json() == {"sessions": []}

    def test_sessions_listing(self, client, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "abc.jsonl").write_text(json.dumps({"ts": "2026-08-20T00:00:00Z", "event": "start"}) + "\n")
        r = client.get("/api/sessions")
        assert r.status_code == 200
        sessions = r.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["id"] == "abc"

    def test_session_detail(self, client, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "abc.jsonl").write_text(
            json.dumps({"ts": "t1", "event": "start"})
            + "\n"
            + json.dumps({"ts": "t2", "event": "end", "exit_code": 0})
            + "\n"
        )
        r = client.get("/api/sessions/abc")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "abc"
        assert len(body["events"]) == 2

    def test_session_detail_404(self, client):
        r = client.get("/api/sessions/missing")
        assert r.status_code == 404

    def test_session_detail_rejects_traversal(self, client):
        r = client.get("/api/sessions/..%2Fetc%2Fpasswd")
        assert r.status_code in (400, 404)


class TestAllowlistCheck:
    def test_shell_run_allowed(self, client):
        r = client.post(
            "/api/allowlist/check",
            json={"tool": "shell.run", "args": {"cmd": "pytest"}, "tier": "restricted"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["allowed"] is True

    def test_shell_run_denied(self, client):
        r = client.post(
            "/api/allowlist/check",
            json={"tool": "shell.run", "args": {"cmd": "rm"}, "tier": "restricted"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["allowed"] is False

    def test_write_to_uploads_blocked(self, client):
        r = client.post(
            "/api/allowlist/check",
            json={
                "tool": "fs.write_file",
                "args": {"path": ".smolcode/uploads/foo.txt"},
                "tier": "restricted",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["allowed"] is False

    def test_write_normal_allowed(self, client):
        r = client.post(
            "/api/allowlist/check",
            json={
                "tool": "fs.write_file",
                "args": {"path": "src/foo.py"},
                "tier": "restricted",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["allowed"] is True

    def test_unknown_tier(self, client):
        r = client.post(
            "/api/allowlist/check",
            json={"tool": "shell.run", "args": {}, "tier": "bogus"},
        )
        assert r.status_code == 400


class TestUploads:
    def test_upload_list_empty(self, client):
        r = client.get("/api/uploads")
        assert r.status_code == 200
        assert r.json() == {"uploads": []}

    def test_upload_then_list_then_delete(self, client):
        files = {"file": ("hello.txt", b"hello world", "text/plain")}
        r = client.post("/api/uploads?tier=restricted", files=files)
        assert r.status_code == 201
        meta = r.json()
        assert meta["stored_name"] == "hello.txt"
        assert meta["mime"] == "text/plain"
        assert meta["size"] == 11

        r = client.get("/api/uploads")
        assert r.status_code == 200
        ulist = r.json()["uploads"]
        assert len(ulist) == 1
        assert ulist[0]["stored_name"] == "hello.txt"

        r = client.get("/api/uploads/hello.txt")
        assert r.status_code == 200
        assert r.content == b"hello world"

        r = client.delete("/api/uploads/hello.txt")
        assert r.status_code == 200
        assert r.json() == {"deleted": "hello.txt"}

        r = client.get("/api/uploads")
        assert r.json() == {"uploads": []}

    def test_upload_blocked_mime(self, client):
        files = {"file": ("evil.exe", b"\xff\xfeMZfake-exe", "application/x-msdownload")}
        r = client.post("/api/uploads?tier=restricted", files=files)
        assert r.status_code == 400
        assert "not in allowlist" in r.json()["detail"]

    def test_download_404(self, client):
        r = client.get("/api/uploads/nonexistent.txt")
        assert r.status_code == 404

    def test_download_rejects_traversal(self, client):
        # Either FastAPI normalises the path (404) or our handler
        # rejects it (400). Both mean the request was not served.
        r = client.get("/api/uploads/..%2Fetc%2Fpasswd")
        assert r.status_code in (400, 404)


class TestUploadsClean:
    def test_clean_without_confirm_is_noop(self, client):
        files = {"file": ("a.txt", b"a", "text/plain")}
        client.post("/api/uploads?tier=restricted", files=files)
        r = client.post("/api/uploads/clean", json={"older_than_days": None, "confirm": False})
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] == 0
        assert body["would_delete_count"] == 1
        # File still exists.
        assert client.get("/api/uploads").json()["uploads"]

    def test_clean_with_confirm(self, client):
        files = {"file": ("a.txt", b"a", "text/plain")}
        client.post("/api/uploads?tier=restricted", files=files)
        r = client.post("/api/uploads/clean", json={"older_than_days": None, "confirm": True})
        assert r.status_code == 200
        assert r.json()["deleted"] == 1
        assert client.get("/api/uploads").json() == {"uploads": []}
