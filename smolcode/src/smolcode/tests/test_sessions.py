# Phase 1 (decision 0025 sec 6.3) - chat-session storage helpers tests.

from __future__ import annotations

import json

import pytest


class TestResolveProjectRoot:
    def test_returns_workspace_for_none(self, tmp_path):
        from smolcode.session import resolve_project_root

        s = type("S", (), {"workspace": str(tmp_path), "projects": ()})()
        # When project is None, return the workspace (legacy mode).
        from pathlib import Path

        assert resolve_project_root(s, None) == Path(str(tmp_path))

    def test_returns_workspace_for_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path / "ws"))
        from smolcode.config import load_settings
        from smolcode.session import resolve_project_root

        settings = load_settings()
        root = resolve_project_root(settings, "missing")
        assert root == settings.workspace

    def test_returns_project_root_when_found(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha")
        from smolcode.config import load_settings
        from smolcode.session import resolve_project_root

        settings = load_settings()
        root = resolve_project_root(settings, "alpha")
        assert root is not None
        assert root == (ws / "alpha").resolve()


class TestSessionDirs:
    def test_legacy_dir_under_workspace(self, tmp_path):
        from smolcode.session import session_dir_for

        d = session_dir_for(tmp_path, project=None)
        assert d == tmp_path / "sessions"

    def test_project_dir_under_project_root(self, tmp_path):
        from smolcode.session import session_dir_for

        d = session_dir_for(tmp_path, project="alpha")
        assert d == tmp_path / ".smolcode" / "sessions"

    def test_session_path_appends_jsonl(self, tmp_path):
        from smolcode.session import session_path_for

        p = session_path_for(tmp_path, project=None, session_id="abc")
        assert p == tmp_path / "sessions" / "abc.jsonl"


class TestSessionCrud:
    def test_create_session_file_returns_path_and_id(self, tmp_path):
        from smolcode.session import create_session_file

        p = create_session_file(tmp_path, project=None)
        assert p.exists()
        assert p.suffix == ".jsonl"
        assert (p.parent / (p.stem + ".meta.json")).exists()
        meta = json.loads((p.parent / (p.stem + ".meta.json")).read_text())
        assert meta.get("name") in (None, "")

    def test_create_session_file_with_name(self, tmp_path):
        from smolcode.session import create_session_file

        p = create_session_file(tmp_path, project=None, name="refactor auth")
        meta = json.loads((p.parent / (p.stem + ".meta.json")).read_text())
        assert meta["name"] == "refactor auth"

    def test_create_session_file_with_explicit_id(self, tmp_path):
        from smolcode.session import create_session_file

        p = create_session_file(tmp_path, project=None, session_id="my-id-123")
        assert p.name == "my-id-123.jsonl"

    def test_create_session_rejects_traversal(self, tmp_path):
        from smolcode.session import create_session_file

        with pytest.raises(ValueError, match="invalid"):
            create_session_file(tmp_path, project=None, session_id="../escape")

    def test_read_events_returns_empty_for_missing(self, tmp_path):
        from smolcode.session import read_session_events

        events = read_session_events(tmp_path / "nope.jsonl")
        assert events == []

    def test_read_events_skips_garbage_lines(self, tmp_path):
        from smolcode.session import read_session_events

        p = tmp_path / "x.jsonl"
        p.write_text(
            json.dumps({"ts": "t1", "event": "start"}) + "\n"
            + "not json\n"
            + json.dumps({"ts": "t2", "event": "end"}) + "\n"
        )
        events = read_session_events(p)
        assert len(events) == 2
        assert events[0]["event"] == "start"
        assert events[1]["event"] == "end"

    def test_rename_session_writes_meta_atomically(self, tmp_path):
        from smolcode.session import create_session_file, rename_session_file

        p = create_session_file(tmp_path, project=None, session_id="abc")
        rename_session_file(tmp_path, project=None, session_id="abc", new_name="Refactor")
        meta_path = p.parent / "abc.meta.json"
        meta = json.loads(meta_path.read_text())
        assert meta["name"] == "Refactor"

    def test_rename_session_rejects_traversal_id(self, tmp_path):
        from smolcode.session import rename_session_file

        with pytest.raises(ValueError, match="invalid"):
            rename_session_file(tmp_path, project=None, session_id="../x", new_name="x")

    def test_delete_session_removes_both_files(self, tmp_path):
        from smolcode.session import create_session_file, delete_session_file

        p = create_session_file(tmp_path, project=None, session_id="abc")
        assert p.exists()
        assert (p.parent / "abc.meta.json").exists()
        delete_session_file(tmp_path, project=None, session_id="abc")
        assert not p.exists()
        assert not (p.parent / "abc.meta.json").exists()

    def test_delete_session_returns_false_when_missing(self, tmp_path):
        from smolcode.session import delete_session_file

        assert delete_session_file(tmp_path, project=None, session_id="nope") is False


class TestListAndCount:
    def test_list_empty(self, tmp_path):
        from smolcode.session import list_sessions

        entries = list_sessions(tmp_path, project=None)
        assert entries == []

    def test_list_returns_meta_and_count(self, tmp_path):
        from smolcode.session import create_session_file, list_sessions

        p1 = create_session_file(tmp_path, project=None, session_id="a", name="First")
        p1.write_text(
            json.dumps({"ts": "t", "event": "run.started"}) + "\n"
            + json.dumps({"ts": "t", "event": "run.started"}) + "\n"
            + json.dumps({"ts": "t", "event": "step.action"}) + "\n"
        )
        create_session_file(tmp_path, project=None, session_id="b")
        entries = list_sessions(tmp_path, project=None)
        ids = {e["id"] for e in entries}
        assert ids == {"a", "b"}
        a = next(e for e in entries if e["id"] == "a")
        assert a["name"] == "First"
        assert a["run_count"] == 2
        b = next(e for e in entries if e["id"] == "b")
        assert b["name"] is None
        assert b["run_count"] == 0

    def test_run_count_caps_at_size(self, tmp_path):
        from smolcode.session import create_session_file, session_run_count

        p = create_session_file(tmp_path, project=None, session_id="a")
        with open(p, "w", encoding="utf-8") as fh:
            for i in range(100):
                evt = "run.started" if i % 2 == 0 else "step.action"
                fh.write(json.dumps({"ts": str(i), "event": evt}) + "\n")
        n = session_run_count(p)
        assert n == 50

    def test_list_excludes_meta_files(self, tmp_path):
        from smolcode.session import create_session_file, list_sessions

        create_session_file(tmp_path, project=None, session_id="a")
        entries = list_sessions(tmp_path, project=None)
        for e in entries:
            assert e["id"] != "a.meta"
