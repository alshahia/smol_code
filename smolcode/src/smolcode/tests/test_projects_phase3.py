"""Phase 3 characterization tests for F4 (project creation with root).

The BE's POST /api/projects handler already accepts {name, root} and
validates that root.exists(). These tests GUARD that contract so a
future refactor cannot silently break the outside-workspace path the
Phase 4 SPA wires.

They pass today (no RED behaviour); Phase 4 wires the SPA on top.

Live evidence:
    REPORT.md F4 "Root cause - SPA wires half of what the BE supports":
        schemas.py:84-92 ProjectCreateRequest accepts optional root
        api.py:347-393 POST /api/projects handles root
        ProjectSwitcher.tsx:39-58 handleCreate posts only {name}
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Minimal TestClient; conftest already cleared SMOLCODE_* and
    pointed SMOLCODE_WORKSPACE at tmp_path/ws. We only need to give
    create_app a fresh app instance per test."""
    from smolcode.web import create_app

    # create_app builds a real AuditSink; keep the log inside tmp.
    monkeypatch.setenv("SMOLCODE_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestProjectCreateWithRoot:
    """F4 characterization: POST /api/projects keeps the existing
    root-handling behaviour alive so Phase 4's SPA can rely on it."""

    def test_post_projects_with_root_creates_project_at_that_root(self, client, tmp_path):
        target = tmp_path / "ext-root"
        target.mkdir()
        r = client.post("/api/projects", json={"name": "ext", "root": str(target)})
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["name"] == "ext"
        assert Path(out["root"]).resolve() == target.resolve()

    def test_post_projects_omitted_root_defaults_to_workspace_plus_name(self, client, tmp_path):
        r = client.post("/api/projects", json={"name": "default-only"})
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["name"] == "default-only"
        # Default root is <workspace>/<name>.
        ws = Path(tmp_path / "ws").resolve()
        expected = (ws / "default-only").resolve()
        assert Path(out["root"]).resolve() == expected

    def test_post_projects_root_must_exist(self, client, tmp_path):
        r = client.post("/api/projects", json={"name": "missing", "root": str(tmp_path / "does-not-exist")})
        assert r.status_code == 400, r.text
        body = r.text.lower()
        assert "does not exist" in body or "not exist" in body

    def test_post_projects_duplicate_name_rejected(self, client, tmp_path):
        r1 = client.post("/api/projects", json={"name": "dup"})
        assert r1.status_code == 201, r1.text
        r2 = client.post("/api/projects", json={"name": "dup"})
        assert r2.status_code == 400, r2.text
        assert "already exists" in r2.text.lower() or "duplicate" in r2.text.lower()
