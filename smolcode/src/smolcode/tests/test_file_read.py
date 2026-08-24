"""Tests for Phase 2 (decision 0025 §6.4): ``GET /api/files``.

Verifies the FastAPI endpoint + the path-traversal rejection logic.
The endpoint serves the SPA's <FilePreview> pane; security-critical
because the user can supply arbitrary paths.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Wire a test client with the workspace + a single project."""
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
    monkeypatch.setenv("SMOLCODE_PROJECTS", f"proj={proj_root}")
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    from smolcode.web import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c, proj_root


class TestFileReadBasic:
    def test_read_existing_file(self, client):
        c, root = client
        f = root / "hello.py"
        f.write_text("print('hi')", encoding="utf-8")
        r = c.get("/api/files", params={"path": "hello.py", "project": "proj"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["path"] == "hello.py"
        assert data["content"] == "print('hi')"
        assert data["size"] == len("print('hi')")
        assert data["encoding"] == "utf-8"
        assert data["truncated"] is False

    def test_read_missing_file_404(self, client):
        c, _ = client
        r = c.get("/api/files", params={"path": "missing.py", "project": "proj"})
        assert r.status_code == 404


class TestFileReadPathSafety:
    def test_traversal_rejected(self, client):
        c, root = client
        # File outside the project root (one level up).
        (root.parent / "outside.py").write_text("OUTSIDE", encoding="utf-8")
        r = c.get("/api/files", params={"path": "../outside.py", "project": "proj"})
        # 403 forbidden because the resolved path is outside the root.
        assert r.status_code == 403

    def test_absolute_outside_root_rejected(self, client):
        c, root = client
        # An absolute Windows path outside the project root.
        outside = str(root.parent / "x.py")
        r = c.get("/api/files", params={"path": outside, "project": "proj"})
        assert r.status_code == 403


class TestFileReadTruncation:
    def test_oversized_file_truncated(self, client):
        c, root = client
        f = root / "big.bin"
        # 10 KB of data; ask for max_bytes=1024.
        f.write_bytes(b"A" * 10240)
        r = c.get(
            "/api/files",
            params={"path": "big.bin", "project": "proj", "max_bytes": 1024},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["truncated"] is True
        assert data["size"] == 10240
        assert len(data["content"]) <= 1024

    def test_binary_file_marked_binary(self, client):
        c, root = client
        f = root / "blob.bin"
        f.write_bytes(b"\xff\xfe\x00\x01\x80invalid")
        r = c.get("/api/files", params={"path": "blob.bin", "project": "proj"})
        assert r.status_code == 200
        data = r.json()
        assert data["encoding"] == "binary"


class TestFileReadProjectFallback:
    def test_unknown_project_falls_back_to_workspace(self, client, tmp_path):
        c, root = client
        ws = tmp_path / "ws"
        f = ws / "loose.txt"
        f.write_text("hello", encoding="utf-8")
        # Unknown project -> falls back to the legacy workspace.
        r = c.get("/api/files", params={"path": "loose.txt", "project": "missing"})
        assert r.status_code == 200
        assert r.json()["content"] == "hello"
