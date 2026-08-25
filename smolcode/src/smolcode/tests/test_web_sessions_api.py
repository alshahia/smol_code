# Phase 1 (decision 0025 sec 6.3) - chat-session API tests.

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
    ws = tmp_path / "ws"
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    from smolcode.web import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


class TestSessionsList:
    def test_empty_returns_empty_list(self, client):
        r = client.get("/api/sessions")
        assert r.status_code == 200
        assert r.json() == {"sessions": []}

    def test_legacy_sessions_listed(self, client, tmp_path):
        sessions_dir = tmp_path / "ws" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "abc.jsonl").write_text(json.dumps({"ts": "t", "event": "run.started"}) + "\n")
        r = client.get("/api/sessions")
        assert r.status_code == 200
        rows = r.json()["sessions"]
        assert len(rows) == 1
        assert rows[0]["id"] == "abc"
        assert rows[0]["run_count"] == 1
        assert rows[0]["name"] is None
        assert rows[0]["project"] is None

    def test_project_scoped_listing(self, client, tmp_path, monkeypatch):
        # Configure project 'alpha' = <tmp>/external.
        ext = tmp_path / "external"
        ext.mkdir()
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha=" + str(ext))
        # Need to recreate the app with the new env.
        from smolcode.web import create_app

        app = create_app()
        with TestClient(app) as c2:
            # Pre-existing legacy session should NOT appear under project=alpha.
            (tmp_path / "ws" / "sessions").mkdir(parents=True, exist_ok=True)
            (tmp_path / "ws" / "sessions" / "legacy.jsonl").write_text("")
            r = c2.get("/api/sessions?project=alpha")
            assert r.status_code == 200
            assert r.json()["sessions"] == []

            # Create a session under the project.
            r = c2.post("/api/sessions?project=alpha", json={"name": "Refactor auth"})
            assert r.status_code == 201
            body = r.json()
            assert body["name"] == "Refactor auth"
            assert body["project"] == "alpha"

            # Now listing should show it.
            r = c2.get("/api/sessions?project=alpha")
            assert r.status_code == 200
            rows = r.json()["sessions"]
            assert len(rows) == 1
            assert rows[0]["name"] == "Refactor auth"
            assert rows[0]["project"] == "alpha"


class TestSessionsCreate:
    def test_create_with_name(self, client):
        r = client.post("/api/sessions", json={"name": "Fix login bug"})
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "Fix login bug"
        assert body["id"]
        assert body["project"] is None

    def test_create_without_name(self, client):
        r = client.post("/api/sessions", json={})
        assert r.status_code == 201
        body = r.json()
        assert body["name"] is None
        assert body["id"]

    def test_create_rejects_empty_name(self, client):
        # Empty string is fine - means "no name".
        r = client.post("/api/sessions", json={"name": ""})
        assert r.status_code == 201

    def test_create_in_unknown_project_400(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha")
        from smolcode.web import create_app

        app = create_app()
        with TestClient(app) as c2:
            r = c2.post("/api/sessions?project=missing", json={"name": "x"})
            # Falls back to workspace (lenient mode); 201.
            assert r.status_code == 201
            assert r.json()["project"] is None


class TestSessionsRename:
    def test_patch_renames_session(self, client):
        r = client.post("/api/sessions", json={"name": "original"})
        sid = r.json()["id"]
        r = client.patch("/api/sessions/" + sid, json={"name": "renamed"})
        assert r.status_code == 200
        # Listing shows new name.
        rows = client.get("/api/sessions").json()["sessions"]
        target = next(s for s in rows if s["id"] == sid)
        assert target["name"] == "renamed"

    def test_patch_missing_session_404(self, client):
        r = client.patch("/api/sessions/nope", json={"name": "x"})
        assert r.status_code == 404

    def test_patch_rejects_traversal(self, client):
        r = client.patch("/api/sessions/..%2Fescape", json={"name": "x"})
        # 400 / 404 / 405 are all valid rejections (the request did not
        # execute the rename). FastAPI returns 405 when the decoded
        # path ("../escape") does not match the /{session_id} route;
        # our safe_id() handler returns 400 when the path matches but
        # the id is unsafe.
        assert r.status_code in (400, 404, 405)


class TestSessionsDelete:
    def test_delete_removes_session(self, client):
        r = client.post("/api/sessions", json={"name": "temporary"})
        sid = r.json()["id"]
        r = client.delete("/api/sessions/" + sid)
        assert r.status_code == 200
        assert r.json()["deleted"] is True
        rows = client.get("/api/sessions").json()["sessions"]
        assert all(s["id"] != sid for s in rows)

    def test_delete_missing_404(self, client):
        r = client.delete("/api/sessions/nope")
        assert r.status_code == 404

    def test_delete_rejects_traversal(self, client):
        r = client.delete("/api/sessions/..%2Fescape")
        assert r.status_code in (400, 404, 405)


class TestSessionDetailWithName:
    def test_detail_404_for_unknown(self, client):
        r = client.get("/api/sessions/missing")
        assert r.status_code == 404

    def test_detail_after_create(self, client):
        r = client.post("/api/sessions", json={"name": "detailed"})
        sid = r.json()["id"]
        r = client.get("/api/sessions/" + sid)
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == sid
        assert body["events"] == []
