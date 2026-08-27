"""M14.1 - GET /api/audit endpoint tests (decision 0018).

Covers:
  * ``/api/audit`` reads the JSONL log via ``audit_reader``.
  * ``?limit`` clamps to ``[1, 500]``.
  * ``?grep`` filters case-insensitive substring across the standard
    haystack fields.
  * ``?verify=1`` includes a ``chain`` sub-object produced by
    ``verify_chain``.
  * Redaction is applied on the way out -- a leaked API key in a
    task description is replaced with ``[REDACTED:*]``.
  * Missing log returns a graceful note + empty list.
  * Malformed JSONL lines are skipped, not crashed.
  * When the server was started with ``--no-audit`` (no sink attached)
    the endpoint returns the documented hint.

The default ``client`` fixture overrides ``app.state.audit_sink``
with a fresh ``AuditSink`` pointing at ``tmp_path / "audit.jsonl"``
so each test gets an isolated log.
"""

from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient


def _make_client_with_audit(tmp_path, monkeypatch, *, with_sink: bool = True):
    """Create a TestClient whose /api/audit serves from a tmp log.

    When ``with_sink=False``, the app state has no audit sink
    attached (mimicking ``--no-audit``); the endpoint should then
    return the graceful empty-state note.

    Returns ``(TestClient, log_path, sink_or_None)``. The caller is
    responsible for ``client.__exit__()`` in a try/finally.
    """
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    # Phase 2 (H5): create_app builds its own sink by default; keep
    # that one pointed at tmp too (the injected sink below stays
    # authoritative for these tests).
    monkeypatch.setenv("SMOLCODE_AUDIT_LOG", str(tmp_path / "boot-audit.jsonl"))
    from smolcode.audit import AuditSink
    from smolcode.web import create_app

    app = create_app()
    log_path = tmp_path / "audit.jsonl"
    sink: AuditSink | None = None
    if with_sink:
        sink = AuditSink(log_path)
    # Enter the TestClient (runs lifespan -> sets audit_sink = None
    # by default), then REPLACE app.state.audit_sink with our sink
    # AFTER the lifespan has fired. This is the cleanest way to
    # inject a sink without modifying the create_app signature.
    client = TestClient(app)
    client.__enter__()
    app.state.audit_sink = sink
    return client, log_path, sink


# ---- Helpers -------------------------------------------------------------


def _write_entries(sink, entries):
    for e in entries:
        sink.record(**e)


# ---- Tests ---------------------------------------------------------------


class TestAuditMissingLog:
    def test_missing_log_returns_graceful_note(self, tmp_path, monkeypatch):
        client, _log, _sink = _make_client_with_audit(tmp_path, monkeypatch, with_sink=False)
        try:
            r = client.get("/api/audit")
            assert r.status_code == 200
            body = r.json()
            assert body["entries"] == []
            assert body["total"] == 0
            assert body["truncated"] is False
            assert "no audit sink attached" in body.get("note", "")
        finally:
            client.__exit__(None, None, None)


class TestAuditEmptyLog:
    def test_empty_log_returns_empty_payload(self, tmp_path, monkeypatch):
        client, log, sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            # The sink created the empty file on construction.
            assert log.exists()
            r = client.get("/api/audit")
            assert r.status_code == 200
            body = r.json()
            assert body["entries"] == []
            assert body["total"] == 0
            # Empty log -> "audit log is empty" hint.
            assert body.get("note") == "audit log is empty"
        finally:
            client.__exit__(None, None, None)


class TestAuditBasicListing:
    def test_lists_recent_entries(self, tmp_path, monkeypatch):
        client, _log, sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            _write_entries(
                sink,
                [
                    {"event": "start", "tier": "restricted", "task": "hello world"},
                    {"event": "step", "step": 1, "action": "final_answer"},
                    {"event": "end", "exit_code": 0, "duration_s": 0.42},
                ],
            )
            r = client.get("/api/audit")
            assert r.status_code == 200
            body = r.json()
            assert body["total"] == 3
            assert len(body["entries"]) == 3
            events = [e["event"] for e in body["entries"]]
            assert events == ["start", "step", "end"]
            assert body["entries"][0]["task"] == "hello world"
        finally:
            client.__exit__(None, None, None)


class TestAuditRedaction:
    def test_redacts_secrets_in_task_field(self, tmp_path, monkeypatch):
        client, _log, sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            _write_entries(
                sink,
                [
                    {
                        "event": "start",
                        "tier": "restricted",
                        "task": "use key sk-abcdefghijklmnopqrstuvwxyz0123456789",
                    },
                    {
                        "event": "start",
                        "tier": "restricted",
                        "task": "use key ghp_abcdefghijklmnopqrstuvwxyz0123456789",
                    },
                ],
            )
            r = client.get("/api/audit")
            assert r.status_code == 200
            entries = r.json()["entries"]
            assert "[REDACTED:openai]" in entries[0]["task"]
            assert "[REDACTED:github]" in entries[1]["task"]
            # Ensure the raw key value is NOT echoed back.
            assert "sk-abcdefghijklmnopqrstuvwxyz" not in entries[0]["task"]
            assert "ghp_abcdefghijklmnopqrstuvwxyz" not in entries[1]["task"]
        finally:
            client.__exit__(None, None, None)


class TestAuditGrep:
    def test_grep_filters_by_task_substring(self, tmp_path, monkeypatch):
        client, _log, sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            _write_entries(
                sink,
                [
                    {"event": "start", "tier": "restricted", "task": "deploy to staging"},
                    {"event": "start", "tier": "restricted", "task": "run unit tests"},
                    {"event": "start", "tier": "restricted", "task": "deploy to prod"},
                ],
            )
            r = client.get("/api/audit", params={"grep": "deploy"})
            assert r.status_code == 200
            body = r.json()
            assert body["total"] == 2
            tasks = [e["task"] for e in body["entries"]]
            assert all("deploy" in t for t in tasks)
        finally:
            client.__exit__(None, None, None)

    def test_grep_is_case_insensitive(self, tmp_path, monkeypatch):
        client, _log, sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            _write_entries(
                sink,
                [
                    {"event": "start", "tier": "restricted", "task": "DEPLOY to staging"},
                    {"event": "start", "tier": "restricted", "task": "run unit tests"},
                ],
            )
            r = client.get("/api/audit", params={"grep": "deploy"})
            assert r.status_code == 200
            assert r.json()["total"] == 1
        finally:
            client.__exit__(None, None, None)


class TestAuditLimit:
    def test_limit_clamps_to_max(self, tmp_path, monkeypatch):
        client, _log, sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            # Write 600 entries; the FastAPI layer caps limit at 500
            # via Query(ge=1, le=500). Pydantic rejects limit=9999
            # with 422, so the test goes through 500.
            _write_entries(sink, [{"event": "step", "step": i} for i in range(600)])
            r = client.get("/api/audit", params={"limit": 500})
            assert r.status_code == 200
            body = r.json()
            assert len(body["entries"]) == 500
            # total counts entries BEFORE limit truncation.
            assert body["total"] == 600
            # The 500 returned must be the most-recent tail (steps
            # 100..599), per the reader's contract.
            assert body["entries"][0]["step"] == 100
            assert body["entries"][-1]["step"] == 599
        finally:
            client.__exit__(None, None, None)

    def test_limit_over_max_is_422(self, tmp_path, monkeypatch):
        client, _log, _sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            r = client.get("/api/audit", params={"limit": 9999})
            assert r.status_code == 422
        finally:
            client.__exit__(None, None, None)


class TestAuditVerifyFlag:
    def test_verify_includes_chain_status(self, tmp_path, monkeypatch):
        client, _log, sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            _write_entries(
                sink,
                [
                    {"event": "start", "tier": "restricted", "task": "x"},
                    {"event": "end", "exit_code": 0, "duration_s": 0.1},
                ],
            )
            r = client.get("/api/audit", params={"verify": "1"})
            assert r.status_code == 200
            body = r.json()
            assert "chain" in body
            assert body["chain"]["ok"] is True
            assert body["chain"]["entries"] == 2
            assert body["chain"]["chained_entries"] == 2
            assert body["chain"]["bad_line"] is None
        finally:
            client.__exit__(None, None, None)

    def test_verify_detects_tampering(self, tmp_path, monkeypatch):
        client, log, sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            _write_entries(
                sink,
                [
                    {"event": "start", "tier": "restricted", "task": "x"},
                    {"event": "end", "exit_code": 0, "duration_s": 0.1},
                ],
            )
            # Tamper with the second line: rewrite the task field.
            with open(log, "r", encoding="utf-8") as fp:
                lines = fp.readlines()
            assert len(lines) == 2
            obj = json.loads(lines[1])
            obj["task"] = "TAMPERED"
            lines[1] = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
            log.write_text("".join(lines), encoding="utf-8")

            r = client.get("/api/audit", params={"verify": "1"})
            assert r.status_code == 200
            body = r.json()
            assert body["chain"]["ok"] is False
            assert body["chain"]["bad_line"] == 2
            assert body["chain"]["chained_entries"] == 1
        finally:
            client.__exit__(None, None, None)


class TestAuditMalformedLines:
    def test_malformed_jsonl_is_skipped(self, tmp_path, monkeypatch):
        client, log, sink = _make_client_with_audit(tmp_path, monkeypatch)
        try:
            _write_entries(
                sink,
                [
                    {"event": "start", "tier": "restricted", "task": "good-1"},
                    {"event": "end", "exit_code": 0, "duration_s": 0.1},
                ],
            )
            # Inject a garbage line into the log. Append a malformed
            # JSON object so the reader must skip it gracefully.
            with open(log, "a", encoding="utf-8") as fp:
                fp.write("this is not valid json\n")
            # One more good entry after the garbage line.
            _write_entries(sink, [{"event": "start", "tier": "restricted", "task": "good-2"}])

            r = client.get("/api/audit")
            assert r.status_code == 200
            body = r.json()
            tasks = [e.get("task", "") for e in body["entries"]]
            assert "good-1" in tasks
            assert "good-2" in tasks
            # total should reflect only the parseable entries.
            assert body["total"] == 3
        finally:
            client.__exit__(None, None, None)


class TestAuditNoSinkAttached:
    def test_no_sink_returns_graceful_note(self, tmp_path, monkeypatch):
        client, _log, _sink = _make_client_with_audit(tmp_path, monkeypatch, with_sink=False)
        try:
            r = client.get("/api/audit")
            assert r.status_code == 200
            body = r.json()
            assert body["entries"] == []
            assert body["total"] == 0
            assert "no audit sink attached" in body["note"]
        finally:
            client.__exit__(None, None, None)
