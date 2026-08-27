"""Phase 2 - audit & evidence integrity tests (REMEDIATION-PLAN Phase 2).

Covers:
  H6: chain continuation across AuditSink instances on one log file;
      tampered tail refuses appends; unchained tail falls back.
  M:  hash computation under the sink lock (concurrency regression).
  M:  `audit ls --json` redacted like table/grep paths.
  H5: create_app() attaches a real AuditSink; RunManager threads a
      default sink into runs whose call site passes audit=None;
      web runs leave start/end records passing verify=true.
  M:  smolcode-snap-* temp snapshots deleted on terminal transition.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from smolcode.audit import AuditError, AuditSink, verify_chain


# ---- H6: chain continuation across sinks ----------------------------------


class TestChainContinuation:
    def test_two_sinks_same_file_chain_verifies(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        s1 = AuditSink(path)
        s1.record("start", tier="restricted", task="first run")
        s1.close()
        s2 = AuditSink(path)
        s2.record("end", exit_code=0, duration_s=1.0)
        s2.close()
        r = verify_chain(path)
        assert r.ok, "legitimate two-sink log must verify"
        assert (r.entries, r.chained_entries) == (2, 2)

    def test_three_runs_three_sinks_chain_verifies(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        for i in range(3):
            s = AuditSink(path)
            s.record("start", tier="restricted", task="run " + str(i))
            s.close()
        r = verify_chain(path)
        assert r.ok and (r.entries, r.chained_entries) == (3, 3)

    def test_tampered_middle_line_still_detected(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        s1 = AuditSink(path)
        s1.record("start", tier="restricted", task="innocent")
        s1.close()
        s2 = AuditSink(path)
        s2.record("end", exit_code=0, duration_s=1.0)
        s2.close()
        lines = path.read_text(encoding="utf-8").splitlines()
        obj = json.loads(lines[0])
        obj["task"] = "tampered"
        lines[0] = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        r = verify_chain(path)
        assert not r.ok and r.bad_line == 1

    def test_append_to_tampered_tail_refused(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        s1 = AuditSink(path)
        s1.record("start", tier="restricted", task="hello")
        s1.close()
        # Corrupt ONLY the recorded entry_hash of the tail line.
        lines = path.read_text(encoding="utf-8").splitlines()
        obj = json.loads(lines[0])
        obj["entry_hash"] = "f" * 64
        lines[0] = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(AuditError):
            AuditSink(path)

    def test_unchained_tail_falls_back_to_genesis(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        legacy = AuditSink(path, hash_chain=False)
        legacy.record("start")
        legacy.close()
        s2 = AuditSink(path)  # must NOT raise; fresh genesis anchor
        s2.record("end")
        s2.close()
        r = verify_chain(path)
        assert r.bad_line is None
        assert r.first_unverifiable_line == 1
        # The verifier BREAKS at the first unchained line, so it only
        # counts lines up to (not including) the seam.
        assert r.entries == 1


# ---- M: hash computation under the lock -----------------------------------


class TestHashRaceUnderLock:
    def test_concurrent_records_produce_verifiable_chain(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        sink = AuditSink(path)
        n_threads, per_thread = 8, 40

        def worker(i):
            for j in range(per_thread):
                sink.record("step", worker=i, seq=j)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        sink.close()
        total = n_threads * per_thread
        r = verify_chain(path)
        msg = "interleaved writes broke chain at line " + str(r.bad_line)
        assert r.entries == total
        assert r.ok, msg


# ---- M: audit ls --json redaction ------------------------------------------


_SECRET = "sk-abcdef1234567890"


def _seed_log_with_secret(tmp_path):
    path = tmp_path / "audit.jsonl"
    s = AuditSink(path)
    s.record("start", tier="restricted", task="deploy using key " + _SECRET)
    s.record("error", kind="RuntimeError", message="bad key " + _SECRET)
    s.close()
    return path


class TestLsJsonRedaction:
    def test_json_output_redacts_secrets(self, tmp_path, capsys):
        from smolcode._cli_subcommands import _audit_main

        path = _seed_log_with_secret(tmp_path)
        rc = _audit_main(["audit", "ls", "--json", "--audit-log", str(path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert _SECRET not in out, "raw secret leaked through audit ls --json"
        assert "[REDACTED:" in out
        parsed = [json.loads(line) for line in out.splitlines() if line.strip()]
        assert any("[REDACTED:" in e.get("task", "") for e in parsed)

    def test_json_no_redact_flag_keeps_raw(self, tmp_path, capsys):
        from smolcode._cli_subcommands import _audit_main

        path = _seed_log_with_secret(tmp_path)
        argv = ["audit", "ls", "--json", "--no-redact", "--audit-log", str(path)]
        rc = _audit_main(argv)
        out = capsys.readouterr().out
        assert rc == 0
        assert _SECRET in out

    def test_table_output_still_redacts(self, tmp_path, capsys):
        from smolcode._cli_subcommands import _audit_main

        path = _seed_log_with_secret(tmp_path)
        rc = _audit_main(["audit", "ls", "--audit-log", str(path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert _SECRET not in out


# ---- H5: create_app audit wiring -------------------------------------------


def _fresh_env(monkeypatch, tmp_path):
    import os

    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SMOLCODE_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    monkeypatch.setenv("SMOLCODE_LOG_LEVEL", "WARNING")


class TestCreateAppAuditSink:
    def test_create_app_attaches_real_sink(self, tmp_path, monkeypatch):
        _fresh_env(monkeypatch, tmp_path)
        from fastapi.testclient import TestClient

        from smolcode.web import create_app

        app = create_app()
        with TestClient(app):
            sink = app.state.audit_sink
            assert isinstance(sink, AuditSink), "web boot must attach a real AuditSink"
            assert str(sink.path) == str((tmp_path / "audit.jsonl").resolve())

    def test_create_app_no_audit_flag_disables_sink(self, tmp_path, monkeypatch):
        _fresh_env(monkeypatch, tmp_path)
        from fastapi.testclient import TestClient

        from smolcode.web import create_app

        app = create_app(no_audit=True)
        with TestClient(app) as client:
            assert app.state.audit_sink is None
            body = client.get("/api/audit").json()
            assert "no audit sink attached" in body.get("note", "")

    def test_start_run_falls_back_to_manager_sink(self, tmp_path, monkeypatch):
        from smolcode.web import agent_runner as ar
        from smolcode.web.runs import RunManager

        sink = AuditSink(tmp_path / "a.jsonl")
        mgr = RunManager(audit_sink=sink)
        captured = {}

        def fake_thread(run, settings, cost_cap_tracker=None):
            captured["run"] = run

        monkeypatch.setattr(ar, "run_in_thread", fake_thread)
        settings = SimpleNamespace(provider="p", model="m", workspace=str(tmp_path), projects=())
        rid = mgr.start_run(task="t", tier="restricted", settings=settings)
        thread = mgr.get(rid).thread
        thread.join(timeout=5)
        assert captured["run"].audit_sink is sink

    def test_explicit_audit_wins_over_manager_default(self, tmp_path, monkeypatch):
        from smolcode.web import agent_runner as ar
        from smolcode.web.runs import RunManager

        default_sink = AuditSink(tmp_path / "default.jsonl")
        explicit_sink = AuditSink(tmp_path / "explicit.jsonl")
        mgr = RunManager(audit_sink=default_sink)
        captured = {}

        def fake_thread(run, settings, cost_cap_tracker=None):
            captured["run"] = run

        monkeypatch.setattr(ar, "run_in_thread", fake_thread)
        settings = SimpleNamespace(provider="p", model="m", workspace=str(tmp_path), projects=())
        rid = mgr.start_run(task="t", tier="restricted", settings=settings, audit=explicit_sink)
        mgr.get(rid).thread.join(timeout=5)
        assert captured["run"].audit_sink is explicit_sink


class TestWebRunLeavesVerifiableAuditTrail:
    def test_web_started_run_records_start_end_and_verifies(self, tmp_path, monkeypatch):
        _fresh_env(monkeypatch, tmp_path)
        from fastapi.testclient import TestClient

        from smolcode.web import agent_runner as ar
        from smolcode.web import create_app

        class _MiniAgent:
            def __init__(self):
                self.step_callbacks = type("CB", (), {"register": lambda self, cls, cb: None})()

            def run(self, task):
                return "ok"

            def cleanup(self):
                pass

        monkeypatch.setattr(ar, "_build_agent_for_run", lambda run, s: _MiniAgent())
        secret_task = "run with key sk-phase2secret123"
        app = create_app()
        with TestClient(app) as client:
            assert isinstance(app.state.audit_sink, AuditSink)
            r = client.post("/api/runs", json={"task": secret_task, "tier": "restricted"})
            assert r.status_code == 201
            run_id = r.json()["run_id"]
            deadline = time.monotonic() + 15
            while True:
                status = client.get("/api/runs/" + run_id).json()["status"]
                if status in ("done", "error", "stopped"):
                    break
                assert time.monotonic() < deadline, "run did not finish"
                time.sleep(0.05)
            body = client.get("/api/audit?verify=true").json()
        events = [e.get("event") for e in body["entries"]]
        assert "start" in events and "end" in events, events
        assert body["chain"]["ok"] is True, body.get("chain")
        dumped = json.dumps(body)
        assert "sk-phase2secret123" not in dumped, "task secret leaked via /api/audit"
        assert "[REDACTED:" in dumped


# ---- M: snapshot temp cleanup ------------------------------------------------


class _FakeMemory:
    system_prompt = "s"
    steps = []


class _FakeAgent:
    memory = _FakeMemory()


class TestSnapshotTempCleanup:
    def test_temp_snapshot_deleted_on_cleanup(self, tmp_path):
        from smolcode.web.runs import Run

        run = Run(id="abcdef1234567890", task="t", tier="restricted")
        p = run.snapshot(_FakeAgent())
        assert p.exists() and p.name.startswith("smolcode-snap-")
        assert run.cleanup_temp_snapshot() is True
        assert not p.exists()
        assert run.snapshot_path is None

    def test_explicit_path_snapshot_preserved(self, tmp_path):
        from smolcode.web.runs import Run

        run = Run(id="abcdef1234567890", task="t", tier="restricted")
        keep = tmp_path / "keep.json"
        p = run.snapshot(_FakeAgent(), path=keep)
        assert p == keep
        assert run.cleanup_temp_snapshot() is False
        assert keep.exists(), "caller-owned snapshot must not be deleted"

    def test_cleanup_without_snapshot_is_noop(self, tmp_path):
        from smolcode.web.runs import Run

        run = Run(id="abcdef1234567890", task="t", tier="restricted")
        assert run.cleanup_temp_snapshot() is False
