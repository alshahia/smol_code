"""Phase 5 (ADR 0040 section 4) -- GET /api/runs/{id}/events/snapshot.

The SPA could not hydrate a finished run history because
RunManager.events_snapshot had no HTTP surface: selecting a completed run
reset the pane to an empty list and opened an EventSource for a stream the
server had already finished sending, so the user waited forever.

This is the one place Phase 5 touches the backend, and it is additive:
the SSE route at /api/runs/{id}/events is untouched.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

from smolcode.config import load_settings
from smolcode.web.runs import Run
from smolcode.web.server import create_app


def _clear_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    workspace = tempfile.mkdtemp(prefix="smolcode-snap-")
    monkeypatch.setenv("SMOLCODE_WORKSPACE", workspace)
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    monkeypatch.setenv("SMOLCODE_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    return workspace


@pytest.fixture
def client(monkeypatch):
    workspace = _clear_env(monkeypatch)
    app = create_app(settings=load_settings())
    c = TestClient(app)
    c.__enter__()
    try:
        yield c, app
    finally:
        c.__exit__(None, None, None)
        shutil.rmtree(workspace, ignore_errors=True)


def _seeded_run(mgr, run_id="snap01", status="done"):
    run = Run(id=run_id, task="t", tier="restricted", provider="openai", model="gpt-4o")
    run.status = status
    run.publish("run.started", {"run_id": run_id, "task": "t"})
    run.publish("step.action", {"tool": "write_file", "path": "a.txt"})
    run.publish("run.ended", {"run_id": run_id, "status": status})
    mgr._runs[run_id] = run
    return run


class TestEventsSnapshotEndpoint:
    def test_returns_200_for_a_known_run(self, client):
        c, app = client
        _seeded_run(app.state.run_manager)
        r = c.get("/api/runs/snap01/events/snapshot")
        assert r.status_code == 200, r.text

    def test_unknown_run_is_404_not_500(self, client):
        c, _ = client
        r = c.get("/api/runs/nope/events/snapshot")
        assert r.status_code == 404

    def test_returns_the_recorded_events_with_types(self, client):
        c, app = client
        _seeded_run(app.state.run_manager)
        body = c.get("/api/runs/snap01/events/snapshot").json()
        assert body["status"] == "done"
        types = [e["type"] for e in body["events"]]
        assert "run.started" in types
        assert "step.action" in types
        assert "run.ended" in types

    def test_event_payloads_keep_their_fields(self, client):
        c, app = client
        _seeded_run(app.state.run_manager)
        body = c.get("/api/runs/snap01/events/snapshot").json()
        ended = [e for e in body["events"] if e.get("type") == "run.ended"]
        assert ended and ended[0]["status"] == "done"

    def test_status_is_reported_so_the_client_knows_not_to_stream(self, client):
        c, app = client
        _seeded_run(app.state.run_manager, status="running")
        body = c.get("/api/runs/snap01/events/snapshot").json()
        assert body["status"] == "running"

    def test_empty_history_is_an_empty_list_not_an_error(self, client):
        c, app = client
        run = Run(id="bare", task="t", tier="restricted")
        run.status = "queued"
        app.state.run_manager._runs["bare"] = run
        body = c.get("/api/runs/bare/events/snapshot").json()
        assert body["events"] == []
        assert body["status"] == "queued"

    def test_does_not_disturb_the_sse_route(self, client):
        # The additive route must not shadow or alter the live stream.
        # Seeded as a terminal status on purpose: the SSE route only emits
        # the end sentinel for a finished run, and without it the stream
        # stays open forever and the test hangs.
        c, app = client
        _seeded_run(app.state.run_manager, status="done")
        with c.stream("GET", "/api/runs/snap01/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            for line in resp.iter_lines():
                if "event: end" in line:
                    break

    def test_snapshot_does_not_consume_the_live_event_log(self, client):
        # events_snapshot reads events_log without draining it, so a
        # connected EventSource still sees subsequent events.
        c, app = client
        mgr = app.state.run_manager
        run = _seeded_run(mgr, status="running")
        before = len(list(run.events_log))
        c.get("/api/runs/snap01/events/snapshot")
        after = len(list(run.events_log))
        assert after == before
