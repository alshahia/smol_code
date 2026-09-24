"""Phase 4 (decision 0039, review R3/H7/H8): retry / rerun / export at the ENDPOINT level.

Against the real RunManager. The 2026-09-24 review proved all three endpoints 500 because
the tests that "covered" them stopped at the dataclass:

* POST /api/runs/{id}/retry and /rerun passed parent_retry_of / parent_rerun_of to
  start_or_enqueue_run, which did not accept them (api.py:1077,1108 vs runs.py:867-880).
* GET /api/runs/{id}/export called dict(s) on a SubagentEntry dataclass (api.py:1144-1146),
  so any run with sub-agent history 500ed.

Only _build_agent_for_run is stubbed, so no LLM is called.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from smolcode.web.runs import RunManager


class _StubAgent:
    """Minimal stand-in for CodeAgent: publishes one step, returns an answer."""

    def __init__(self, run):
        self.run = run
        self.tools = []
        self.model = None
        self.max_steps = 1
        self.memory = type("M", (), {"steps": [], "system_prompt": "x", "reset": lambda self: None})()
        self.step_callbacks = type("CB", (), {"register": lambda self, cls, cb: None})()

    def run(self, task, **kwargs):
        self.run.publish(
            "step.action",
            {
                "kind": "action",
                "step_number": 1,
                "thought": "stub",
                "observations": "stub",
                "timing_ms": 1.0,
                "tokens": {"input": 10, "output": 5},
            },
        )
        return "stub-final-answer"

    def cleanup(self):
        """smolagents CodeAgent calls cleanup() in run_in_thread's finally."""
        return None


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    monkeypatch.setenv("SMOLCODE_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("SMOLCODE_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    from smolcode.web import agent_runner as ar

    monkeypatch.setattr(ar, "_build_agent_for_run", lambda run, settings: _StubAgent(run))
    from smolcode.web import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def _mgr(client) -> RunManager:
    return client.app.state.run_manager


def _terminal_run(client, **kwargs):
    """Insert a terminal Run straight into the real manager (no thread)."""
    from smolcode.web.runs import Run

    mgr = _mgr(client)
    run = Run(
        id="parent01",
        task="original task",
        tier=kwargs.pop("tier", "restricted"),
        # A real provider/model pair: the retry endpoint forwards these to
        # start_or_enqueue_run as overrides, and an empty provider is rejected
        # by get_preset. Mirrors what a finished run actually carries.
        provider=kwargs.pop("provider", "opencode-go"),
        model=kwargs.pop("model", "deepseek-v4-flash"),
        **kwargs,
    )
    run.status = kwargs.pop("status", "done")
    mgr._runs[run.id] = run
    return run


class TestRetryEndpoint:
    def test_retry_terminal_run_returns_200_and_new_id(self, client):
        parent = _terminal_run(client)
        r = client.post("/api/runs/" + parent.id + "/retry", json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["run_id"] != parent.id

    def test_retry_sets_parent_retry_of_on_child(self, client):
        parent = _terminal_run(client)
        r = client.post("/api/runs/" + parent.id + "/retry", json={})
        assert r.status_code == 200, r.text
        child = _mgr(client).get(r.json()["run_id"])
        assert child.parent_retry_of == parent.id

    def test_retry_increments_parent_retry_count(self, client):
        parent = _terminal_run(client)
        before = parent.retry_count
        client.post("/api/runs/" + parent.id + "/retry", json={})
        assert parent.retry_count == before + 1

    def test_empty_body_retry_of_elevated_run_stays_elevated(self, client):
        """The regression the old non-optional tier default made impossible.

        RunStartRequest.tier defaulted to "restricted", so the endpoint could not tell
        "caller asked for restricted" from "caller said nothing", and an empty-body retry
        silently downgraded an elevated run.
        """
        parent = _terminal_run(client, tier="elevated")
        r = client.post("/api/runs/" + parent.id + "/retry")
        assert r.status_code == 200, r.text
        child = _mgr(client).get(r.json()["run_id"])
        assert child.tier == "elevated"

    def test_retry_unknown_run_is_404_not_500(self, client):
        r = client.post("/api/runs/nope/retry", json={})
        assert r.status_code == 404, r.text

    def test_retry_non_terminal_run_is_409(self, client):
        parent = _terminal_run(client, status="running")
        r = client.post("/api/runs/" + parent.id + "/retry", json={})
        assert r.status_code == 409, r.text


class TestRerunEndpoint:
    def test_rerun_done_run_returns_200_and_sets_parent(self, client):
        parent = _terminal_run(client)
        r = client.post("/api/runs/" + parent.id + "/rerun")
        assert r.status_code == 200, r.text
        child = _mgr(client).get(r.json()["run_id"])
        assert child.parent_rerun_of == parent.id
        assert child.task == parent.task

    def test_rerun_unknown_run_is_404_not_500(self, client):
        r = client.post("/api/runs/nope/rerun")
        assert r.status_code == 404, r.text

    def test_rerun_non_done_run_is_409(self, client):
        parent = _terminal_run(client, status="error")
        r = client.post("/api/runs/" + parent.id + "/rerun")
        assert r.status_code == 409, r.text


class TestExportEndpoint:
    def test_export_run_with_subagent_history_returns_200(self, client):
        """dict(s) on a SubAgentSummary dataclass raised TypeError -> HTTP 500."""
        from smolcode.web.runs import SubAgentSummary

        parent = _terminal_run(client)
        parent.append_subagent("sub-1", tier="restricted")
        parent.close_subagent("sub-1")
        assert parent.subagent_history, "sub-agent history should be populated"
        assert isinstance(parent.subagent_history[0], SubAgentSummary)

        r = client.get("/api/runs/" + parent.id + "/export")
        assert r.status_code == 200, r.text
        payload = json.loads(r.content)
        assert payload["schema_version"] == 1
        assert len(payload["subagent_history"]) == 1

    def test_export_unknown_run_is_404(self, client):
        r = client.get("/api/runs/nope/export")
        assert r.status_code == 404, r.text

    def test_export_sets_attachment_filename(self, client):
        parent = _terminal_run(client)
        r = client.get("/api/runs/" + parent.id + "/export")
        assert r.status_code == 200, r.text
        assert "attachment" in r.headers.get("content-disposition", "")


class TestRunStartTierDefault:
    def test_fresh_start_without_tier_defaults_to_restricted(self, client):
        """The default moved from the schema to the endpoint (decision 0039)."""
        r = client.post("/api/runs", json={"task": "hello"})
        assert r.status_code == 201, r.text
        run = _mgr(client).get(r.json()["run_id"])
        assert run.tier == "restricted"

    def test_explicit_tier_is_honoured(self, client):
        r = client.post("/api/runs", json={"task": "hello", "tier": "elevated"})
        assert r.status_code == 201, r.text
        run = _mgr(client).get(r.json()["run_id"])
        assert run.tier == "elevated"
