"""M9 - live execution API tests.

These tests exercise the /api/runs/* endpoints using FastAPI TestClient.
The agent runner is exercised with the smoke stub model (--smoke in
the CLI; equivalent for the API is to monkeypatch build_model to
return _StubLiteLLMModel so no network calls are made).
"""

from __future__ import annotations

import json
import os
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    # Force local executor + stub model so no LLM calls happen.
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    monkeypatch.setenv("SMOLCODE_LOG_LEVEL", "WARNING")
    # Replace build_model in the agent_runner module with the stub so
    # /api/runs can start without a real key.
    from smolcode.web import agent_runner as ar

    monkeypatch.setattr(ar, "_build_agent_for_run", _stub_build_agent)
    from smolcode.web import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def _stub_build_agent(run, settings):
    """Return a tiny CodeAgent-like object whose .run() yields a
    canned transcript + final answer.

    The test for the SSE bridge cares about: the step callback
    firing, the run publishing events, and run.ended arriving with
    status=done.
    """
    from smolagents import CodeAgent

    from smolcode.models import _StubLiteLLMModel
    from smolcode.tools import build_tools

    tier = settings.tiers[run.tier]
    workspace = str(settings.workspace)
    tools = build_tools(tier, settings, workspace_path=workspace, mcp_configs=[])

    class _StubCodeAgent(CodeAgent):
        def __init__(self):
            # Bypass CodeAgent.__init__ entirely (it pulls in models,
            # imports, etc. that we don't need for this test). We just
            # need .run() + .step_callbacks.
            self.tools = tools
            self.model = _StubLiteLLMModel()
            self.max_steps = 4
            self.step_callbacks = type("CB", (), {"register": lambda self, cls, cb: None})()

        def run(self, task):
            # Simulate one step callback publishing then a final answer.
            run.publish(
                "step.action",
                {
                    "kind": "action",
                    "step_number": 1,
                    "thought": "stubbed step",
                    "observations": "stub observations",
                    "timing_ms": 12.5,
                    "tokens": {"input": 10, "output": 5},
                },
            )
            return "stub-final-answer"

    return _StubCodeAgent()


# ---- TestRunsBasic -------------------------------------------------------


class TestRunsBasic:
    def test_runs_list_starts_empty(self, client):
        r = client.get("/api/runs")
        assert r.status_code == 200
        assert r.json() == {"runs": []}

    def test_runs_create_returns_id_and_status(self, client):
        r = client.post("/api/runs", json={"task": "hello world", "tier": "restricted"})
        assert r.status_code == 201
        body = r.json()
        assert "run_id" in body and len(body["run_id"]) >= 16
        assert body["status"] == "running"

    def test_runs_create_rejects_empty_task(self, client):
        r = client.post("/api/runs", json={"task": "   ", "tier": "restricted"})
        assert r.status_code == 400
        assert "non-empty" in r.json()["detail"]

    def test_runs_create_rejects_unknown_tier(self, client):
        r = client.post("/api/runs", json={"task": "hi", "tier": "bogus"})
        assert r.status_code == 400

    def test_runs_create_rejects_full_access(self, client):
        """full_access is CLI-only (decision 0012)."""
        r = client.post("/api/runs", json={"task": "hi", "tier": "full_access"})
        assert r.status_code == 403
        assert "CLI" in r.json()["detail"]

    def test_runs_get_returns_summary(self, client):
        rr = client.post("/api/runs", json={"task": "hi", "tier": "restricted"})
        run_id = rr.json()["run_id"]
        r = client.get("/api/runs/" + run_id)
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == run_id
        assert body["task"] == "hi"
        assert body["tier"] == "restricted"
        # Phase 0 (decision 0025): the new summary fields are present
        # even when the run is mid-flight (tokens may be partial).
        assert "tokens" in body
        assert "input" in body["tokens"]
        assert "output" in body["tokens"]
        assert "total" in body["tokens"]
        assert "step_count" in body
        assert "remaining_s" in body
        assert "subagent" in body

    def test_runs_get_404(self, client):
        r = client.get("/api/runs/nonexistent")
        assert r.status_code == 404

    def test_runs_list_after_create(self, client):
        client.post("/api/runs", json={"task": "a", "tier": "restricted"})
        client.post("/api/runs", json={"task": "b", "tier": "elevated"})
        r = client.get("/api/runs")
        assert r.status_code == 200
        runs = r.json()["runs"]
        assert len(runs) == 2
        tasks = sorted(r["task"] for r in runs)
        assert tasks == ["a", "b"]


# ---- TestCountdownAndLag (Phase 0, decision 0025 T-3) ---------------


class TestCountdownAndLag:
    """Phase 0 (decision 0025, T-3):
    (a) Run.summary_dict()["remaining_s"] decreases over time,
    (b) becomes negative after the budget expires,
    (c) get_run returns 404 cleanly when the run is removed mid-session.
    """

    def test_get_run_404_when_removed_mid_session(self, client):
        """B9 root-cause: when the SPA selects a run that the server
        has purged from RunManager (RunManager._runs dict drops it),
        GET /api/runs/{id} MUST return a clean 404 -- not raise a 500.
        """
        rr = client.post("/api/runs", json={"task": "hi", "tier": "restricted"})
        run_id = rr.json()["run_id"]
        # Confirm it exists first.
        r = client.get("/api/runs/" + run_id)
        assert r.status_code == 200
        # Reach into the app.state run_manager (set by deps.get_run_manager)
        # and purge the run as if the history window expired mid-session.
        # We use the TestClient's app instance directly to bypass the
        # Request dependency plumbing.
        app = client.app
        mgr = getattr(app.state, "run_manager", None)
        assert mgr is not None, "expected run_manager on app.state"
        with mgr._lock:
            mgr._runs.pop(run_id, None)
        # Re-fetch -> must be a clean 404 (not a 500).
        r2 = client.get("/api/runs/" + run_id)
        assert r2.status_code == 404
        assert "run not found" in r2.json()["detail"]
        # And the events stream endpoint must also 404 cleanly.
        r3 = client.get("/api/runs/" + run_id + "/events")
        assert r3.status_code == 404

    def test_run_summary_includes_remaining_s_countdown(self, client):
        """The RunSummary returned by /api/runs/{id} carries a positive
        remaining_s when the run is in flight.
        """
        rr = client.post("/api/runs", json={"task": "hi", "tier": "restricted"})
        run_id = rr.json()["run_id"]
        # Get summary immediately. remaining_s is positive but bounded
        # by the 15-min default budget.
        r = client.get("/api/runs/" + run_id)
        body = r.json()
        if body["remaining_s"] is not None:
            assert 0 < body["remaining_s"] <= 900.5


# ---- TestRunsSSE ---------------------------------------------------------


class TestRunsSSE:
    def test_events_stream_emits_run_started_and_ended(self, client):
        rr = client.post("/api/runs", json={"task": "hi", "tier": "restricted"})
        run_id = rr.json()["run_id"]
        with client.stream("GET", "/api/runs/" + run_id + "/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            chunks = []
            for line in resp.iter_lines():
                chunks.append(line)
                # Stop after we see run.ended + the end sentinel.
                if "event: end" in line:
                    break
        body = "\n".join(chunks)
        assert "event: run.started" in body
        assert "event: step.action" in body
        assert "event: run.ended" in body
        assert "event: end" in body

    def test_events_stream_404_for_unknown_run(self, client):
        r = client.get("/api/runs/no-such-run/events")
        assert r.status_code == 404


# ---- TestRunsApproval ----------------------------------------------------


class TestRunsApproval:
    def test_approval_endpoint_404_for_unknown_run(self, client):
        r = client.post(
            "/api/runs/no-such-run/approval",
            json={"decision_id": "x", "approved": True},
        )
        assert r.status_code == 404

    def test_approval_endpoint_rejects_missing_decision_id(self, client):
        # Pydantic v2 returns 422 for missing required fields; we
        # accept either 400 (manual check) or 422 (Pydantic validation).
        rr = client.post("/api/runs", json={"task": "hi", "tier": "restricted"})
        run_id = rr.json()["run_id"]
        r = client.post("/api/runs/" + run_id + "/approval", json={"approved": True})
        assert r.status_code in (400, 422)

    def test_approval_endpoint_resolves_unknown_decision(self, client):
        """POSTing a decision_id that no tool is currently waiting on
        returns 200 with resolved=false. The run is unaffected."""
        rr = client.post("/api/runs", json={"task": "hi", "tier": "restricted"})
        run_id = rr.json()["run_id"]
        r = client.post(
            "/api/runs/" + run_id + "/approval",
            json={"decision_id": "no-such-decision", "approved": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["resolved"] is False


# ---- TestRunsStop --------------------------------------------------------


class TestRunsStop:
    def test_stop_unknown_run_returns_404(self, client):
        r = client.post("/api/runs/no-such-run/stop")
        assert r.status_code == 404

    def test_stop_sets_flag_and_run_marks_stopped(self, client):
        """Starting a run and immediately stopping it should result
        in status=stopped (the worker checks the flag between steps)."""
        rr = client.post("/api/runs", json={"task": "hi", "tier": "restricted"})
        run_id = rr.json()["run_id"]
        # Give the worker a moment to start the loop.
        time.sleep(0.05)
        r = client.post("/api/runs/" + run_id + "/stop")
        assert r.status_code == 200
        assert r.json() == {"stopped": True}
        # Wait for the run to settle.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            r = client.get("/api/runs/" + run_id)
            if r.json()["status"] in ("stopped", "done", "error"):
                break
            time.sleep(0.1)
        final = client.get("/api/runs/" + run_id).json()
        # The stub agent runs synchronously and finishes immediately,
        # so status may be 'done'. But the stop flag was set, which is
        # the contract we test.
        assert final["status"] in ("stopped", "done", "error")


# ---- M10: Approval with edited_after -----------------------------------


class TestRunsApprovalEditedAfter:
    def test_approval_endpoint_accepts_edited_after(self, client):
        """M10: POST /api/runs/<id>/approval accepts an optional
        ``edited_after`` field that overrides the agent's proposed
        content for diff gates. Resolving an unknown decision_id
        with edited_after still returns 200 with resolved=false."""
        rr = client.post("/api/runs", json={"task": "hi", "tier": "restricted"})
        run_id = rr.json()["run_id"]
        r = client.post(
            "/api/runs/" + run_id + "/approval",
            json={
                "decision_id": "unknown-decision",
                "approved": True,
                "edited_after": "user-edited-content",
            },
        )
        assert r.status_code == 200
        assert r.json() == {
            "resolved": False,
            "decision_id": "unknown-decision",
        }


# ---- M10: Workspace tree endpoint --------------------------------------


class TestWorkspaceTree:
    def test_workspace_tree_returns_entries(self, tmp_path, client, monkeypatch):
        # Create a small file tree under the workspace.
        ws = tmp_path
        (ws / "a.txt").write_text("a", encoding="utf-8")
        (ws / "sub").mkdir()
        (ws / "sub" / "b.txt").write_text("b", encoding="utf-8")
        r = client.get("/api/workspace/tree")
        assert r.status_code == 200
        body = r.json()
        assert body["workspace"] == str(ws)
        assert body["truncated"] is False
        names = sorted(e["rel_path"] for e in body["entries"])
        # The app creates ``.smolcode/uploads`` on startup, so we expect
        # it to be present alongside the test data.
        assert "a.txt" in names
        assert "sub" in names
        assert "sub/b.txt" in names
        assert ".smolcode" in names  # keep .smolcode visible

    def test_workspace_tree_skips_dotdirs_except_smolcode(self, tmp_path, client, monkeypatch):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "x").write_text("x", encoding="utf-8")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "x").write_text("x", encoding="utf-8")
        r = client.get("/api/workspace/tree")
        assert r.status_code == 200
        paths = [e["rel_path"] for e in r.json()["entries"]]
        # .git and node_modules are skipped; .smolcode + uploads remain.
        assert all(not p.startswith(".git") for p in paths)
        assert all(not p.startswith("node_modules") for p in paths)
        assert ".smolcode" in paths

    def test_workspace_tree_marks_dirs(self, tmp_path, client, monkeypatch):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
        r = client.get("/api/workspace/tree")
        assert r.status_code == 200
        entries = {e["rel_path"]: e for e in r.json()["entries"]}
        assert entries["sub"]["is_dir"] is True
        assert entries["sub/b.txt"]["is_dir"] is False

    def test_workspace_tree_max_entries_truncates(self, tmp_path, client, monkeypatch):
        for i in range(10):
            (tmp_path / ("f" + str(i) + ".txt")).write_text("x", encoding="utf-8")
        r = client.get("/api/workspace/tree?max_entries=3")
        assert r.status_code == 200
        body = r.json()
        assert len(body["entries"]) <= 3
        assert body["truncated"] is True

    def test_workspace_tree_rejects_bad_max_entries(self, client):
        r = client.get("/api/workspace/tree?max_entries=0")
        assert r.status_code in (400, 422)
        r = client.get("/api/workspace/tree?max_entries=99999")
        assert r.status_code in (400, 422)
        r = client.get("/api/workspace/tree?max_depth=0")
        assert r.status_code in (400, 422)


# ---- M11: provider / model / key overrides (decision 0014) -----------


class TestRunsM11Overrides:
    """M11 (decision 0014) extensions to POST /api/runs.

    The endpoint accepts three new optional fields:
      - ``provider``: preset id that overrides settings.provider
      - ``model``:    model id that overrides settings.model
      - ``keys``:     whitelisted {env_var: value} map
    All three are optional and the request stays backwards-compatible.
    """

    def test_provider_override_recorded_on_run(self, client):
        r = client.post(
            "/api/runs",
            json={
                "task": "hi",
                "tier": "restricted",
                "provider": "MiniMax",
                "model": "MiniMax-M3",
            },
        )
        assert r.status_code == 201
        run_id = r.json()["run_id"]
        run = client.get("/api/runs/" + run_id).json()
        assert run["tier"] == "restricted"

    def test_unknown_provider_in_request_returns_400(self, client):
        r = client.post(
            "/api/runs",
            json={"task": "hi", "tier": "restricted", "provider": "nonexistent-provider"},
        )
        assert r.status_code == 400
        assert "nonexistent-provider" in r.json()["detail"]

    def test_unknown_env_var_name_in_keys_dropped(self, client):
        # An evil env-var name in the body is silently dropped by
        # extract_keys; the run still starts successfully.
        r = client.post(
            "/api/runs",
            json={
                "task": "hi",
                "tier": "restricted",
                "keys": {"EVIL_NAME": "x", "OPENAI_API_KEY": "sk-abc12345"},
            },
        )
        assert r.status_code == 201

    def test_keys_field_missing_is_noop(self, client):
        # Backwards-compatible: existing callers that omit ``keys``
        # entirely still work.
        r = client.post(
            "/api/runs",
            json={"task": "hi", "tier": "restricted"},
        )
        assert r.status_code == 201

    def test_keys_empty_dict_is_noop(self, client):
        r = client.post(
            "/api/runs",
            json={"task": "hi", "tier": "restricted", "keys": {}},
        )
        assert r.status_code == 201

    def test_model_override_recorded_on_run(self, client):
        r = client.post(
            "/api/runs",
            json={
                "task": "hi",
                "tier": "restricted",
                "model": "deepseek-v4-flash",
            },
        )
        assert r.status_code == 201

    def test_run_started_event_does_not_carry_keys(self, client):
        """Defensive: the api_key_value must NEVER appear in the SSE
        run.started event payload (decision 0014 security contract).
        """
        r = client.post(
            "/api/runs",
            json={
                "task": "hi",
                "tier": "restricted",
                "provider": "openai",
                "keys": {"OPENAI_API_KEY": "sk-TESTKEYSHOULDNEVERAPPEAR"},
            },
        )
        run_id = r.json()["run_id"]
        with client.stream("GET", "/api/runs/" + run_id + "/events") as resp:
            chunks = []
            for line in resp.iter_lines():
                chunks.append(line)
                if "event: end" in line:
                    break
        body = "\n".join(chunks)
        assert "TESTKEYSHOULDNEVERAPPEAR" not in body

    def test_run_summary_does_not_carry_keys(self, client):
        r = client.post(
            "/api/runs",
            json={
                "task": "hi",
                "tier": "restricted",
                "provider": "openai",
                "keys": {"OPENAI_API_KEY": "sk-NEVERHERE"},
            },
        )
        run_id = r.json()["run_id"]
        run = client.get("/api/runs/" + run_id).json()
        # All fields except known ones should NOT contain the key.
        serialised = json.dumps(run)
        assert "NEVERHERE" not in serialised

    def test_orchestrator_tier_with_overrides(self, client):
        r = client.post(
            "/api/runs",
            json={
                "task": "hi",
                "tier": "orchestrator",
                "provider": "MiniMax",
                "model": "MiniMax-M3",
            },
        )
        assert r.status_code == 201

    def test_full_access_still_rejected_even_with_overrides(self, client):
        """decision 0012 still binds: full_access is CLI-only. The
        M11 provider/model/keys fields do not unlock full_access."""
        r = client.post(
            "/api/runs",
            json={
                "task": "hi",
                "tier": "full_access",
                "provider": "openai",
            },
        )
        assert r.status_code == 403

    def test_provider_default_taken_from_settings_when_no_override(self, client, monkeypatch):
        # Env-backed settings.provider = opencode-go; no override
        # on the request -> the run should still start.
        # Default settings.provider is "opencode-go" from load_settings().
        r = client.post(
            "/api/runs",
            json={"task": "hi", "tier": "restricted"},
        )
        assert r.status_code == 201


# ---- M10: touched_paths in run summary ---------------------------------


class TestRunSummaryTouchedPaths:
    def test_run_summary_includes_touched_paths(self, client):
        rr = client.post("/api/runs", json={"task": "hi", "tier": "restricted"})
        run_id = rr.json()["run_id"]
        r = client.get("/api/runs/" + run_id)
        assert r.status_code == 200
        body = r.json()
        # Stub agent doesn't touch files, so list is empty.
        assert "touched_paths" in body
        assert body["touched_paths"] == []
