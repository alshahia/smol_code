# Phase 1 (decision 0025 sec 6.3) - project API tests.

from __future__ import annotations

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


class TestProjectsList:
    def test_empty_projects(self, client):
        r = client.get("/api/projects")
        assert r.status_code == 200
        assert r.json() == {"projects": []}

    def test_projects_listed_from_env(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha,beta")
        from smolcode.web import create_app

        app = create_app()
        with TestClient(app) as c2:
            r = c2.get("/api/projects")
            assert r.status_code == 200
            rows = r.json()["projects"]
            names = {p["name"] for p in rows}
            assert names == {"alpha", "beta"}


class TestProjectsCreate:
    def test_create_with_default_root(self, client):
        r = client.post("/api/projects", json={"name": "alpha"})
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "alpha"
        assert body["root"].endswith("alpha")

        # GET /api/projects now lists it.
        rows = client.get("/api/projects").json()["projects"]
        assert any(p["name"] == "alpha" for p in rows)

    def test_create_with_explicit_root(self, client, tmp_path):
        ext = tmp_path / "external"
        ext.mkdir()
        r = client.post("/api/projects", json={"name": "alpha", "root": str(ext)})
        assert r.status_code == 201
        assert r.json()["root"] == str(ext.resolve())

    def test_create_rejects_duplicate(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha")
        from smolcode.web import create_app

        app = create_app()
        with TestClient(app) as c2:
            r = c2.post("/api/projects", json={"name": "alpha"})
            assert r.status_code == 400
            assert "already exists" in r.json()["detail"]

    def test_create_rejects_invalid_name(self, client):
        r = client.post("/api/projects", json={"name": "bad name"})
        assert r.status_code == 400

    def test_create_rejects_missing_root(self, client, tmp_path):
        ghost = tmp_path / "does-not-exist"
        r = client.post("/api/projects", json={"name": "alpha", "root": str(ghost)})
        assert r.status_code == 400
        assert "does not exist" in r.json()["detail"]


class TestProjectsDelete:
    def test_delete_removes_project(self, client):
        r = client.post("/api/projects", json={"name": "alpha"})
        assert r.status_code == 201
        r = client.delete("/api/projects/alpha")
        assert r.status_code == 200
        assert r.json() == {"deleted": "alpha"}
        rows = client.get("/api/projects").json()["projects"]
        assert all(p["name"] != "alpha" for p in rows)

    def test_delete_unknown_404(self, client):
        r = client.delete("/api/projects/missing")
        assert r.status_code == 404
