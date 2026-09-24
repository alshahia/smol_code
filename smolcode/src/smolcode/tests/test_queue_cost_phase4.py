"""Phase 4 (decision 0039) -- H8 queue drain + R4 cost accounting.

These tests exist because the Phase 3 suite went green over BOTH defects
while proving neither:

* the queue-drain tests stopped at the dataclass (RunManager._queue) and
  never ran the drain, so the request-scoped api.get_run_manager() /
  deps.get_settings() calls inside it were never executed;
* the cost-cap tests injected types.SimpleNamespace fakes that carried a
  hand-made ".tokens" attribute. A real Run had no tokens attribute at
  all, so every real run reported 0 dollars and no cap could ever trip.

Every test here uses the REAL Run dataclass and the REAL RunManager from
app.state, exercising the code paths the app actually ships.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from smolcode.config import load_settings
from smolcode.web import agent_runner as ar
from smolcode.web import api as api_mod
from smolcode.web import deps as deps_mod
from smolcode.web.runs import STATUS_QUEUED, Run, RunManager
from smolcode.web.server import create_app


def _clear_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    workspace = tempfile.mkdtemp(prefix="smolcode-p4-")
    monkeypatch.setenv("SMOLCODE_WORKSPACE", workspace)
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    monkeypatch.setenv("SMOLCODE_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    return workspace


@pytest.fixture
def app_client(monkeypatch):
    workspace = _clear_env(monkeypatch)
    app = create_app(settings=load_settings())
    client = TestClient(app)
    client.__enter__()
    try:
        yield client, app
    finally:
        client.__exit__(None, None, None)
        shutil.rmtree(workspace, ignore_errors=True)


def _real_run(run_id, *, provider="openai", model="gpt-4o", tokens_in=0, tokens_out=0, status="done"):
    """A REAL Run, not a SimpleNamespace fake.

    This is the whole point of the file: the old tests used a duck-typed
    stand-in, which is why a missing Run.tokens shipped unnoticed.
    """
    run = Run(
        id=run_id,
        task="t",
        tier="restricted",
        started_at=time.time() - 60,
        provider=provider,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    run.status = status
    return run


class _StubAgent:
    def __init__(self):
        self.tools = []

    def run(self, task, **kwargs):
        return "stub-final-answer"

    def cleanup(self):
        return None


class TestRunTokensProperty:
    """R4: the dashboard reads run.tokens; a real Run had none."""

    def test_run_exposes_tokens_summary(self):
        run = _real_run("r1", tokens_in=120, tokens_out=34)
        assert run.tokens.input == 120
        assert run.tokens.output == 34
        assert run.tokens.total == 154

    def test_tokens_is_derived_not_stored(self):
        """A stored snapshot would go stale the moment a step published
        more tokens, so the property must be derived on every read."""
        run = _real_run("r1", tokens_in=10, tokens_out=5)
        run.tokens_in = 99
        assert run.tokens.input == 99
        assert run.tokens.total == 104


class TestCostWithRealRuns:
    """R4: real Runs must produce a non-zero dashboard cost."""

    def test_dashboard_cost_is_nonzero_for_real_runs(self, app_client):
        client, app = app_client
        # gpt-4o: 200k in + 100k out is well over 1 dollar at list pricing.
        app.state.run_manager._runs["r1"] = _real_run("r1", tokens_in=200000, tokens_out=100000)
        r = client.get("/api/dashboard")
        assert r.status_code == 200, r.text
        cost = r.json()["cost_estimate_usd_today"]
        assert cost > 0, (
            "a real Run with 200k in / 100k out must not report 0 -- this is "
            "the exact regression the SimpleNamespace fakes hid"
        )

    def test_dashboard_by_provider_cost_is_nonzero(self, app_client):
        client, app = app_client
        app.state.run_manager._runs["r1"] = _real_run(
            "r1", provider="openai", model="gpt-4o", tokens_in=200000, tokens_out=100000
        )
        body = client.get("/api/dashboard").json()
        assert body["by_provider"]["openai"]["cost_usd"] > 0

    def test_cost_usd_survives_serialization(self, app_client):
        """The Pydantic TokenSummary had no cost_usd field, so Pydantic
        silently DROPPED the dashboard's value and the SPA rendered 0."""
        client, app = app_client
        app.state.run_manager._runs["r1"] = _real_run("r1", tokens_in=200000, tokens_out=100000)
        body = client.get("/api/dashboard").json()
        assert "cost_usd" in body["tokens_today"]
        assert body["tokens_today"]["cost_usd"] > 0

    def test_run_start_cap_trips_with_real_runs(self, app_client):
        """A 429 must be reachable in production, i.e. with real Runs."""
        client, app = app_client
        app.state.run_manager._runs["r1"] = _real_run(
            "r1", provider="openai", model="gpt-4o", tokens_in=200000, tokens_out=100000
        )
        app.state.cost_cap_tracker.update({"openai": 1.0})
        r = client.post("/api/runs", json={"task": "hi", "tier": "restricted", "provider": "openai"})
        assert r.status_code == 429, r.text
        assert "cost_cap_reached:" in r.json()["detail"]

    def test_no_cap_allows_expensive_real_run(self, app_client, monkeypatch):
        client, app = app_client
        app.state.run_manager._runs["r1"] = _real_run(
            "r1", provider="openai", model="gpt-4o", tokens_in=200000, tokens_out=100000
        )
        monkeypatch.setattr(ar, "_build_agent_for_run", lambda run, settings: _StubAgent())
        r = client.post("/api/runs", json={"task": "hi", "tier": "restricted", "provider": "openai"})
        assert r.status_code == 201, r.text


class TestQueueDrain:
    """H8: the drain must not depend on request-scoped FastAPI deps."""

    def test_manager_owns_settings(self, app_client):
        _, app = app_client
        assert isinstance(app.state.run_manager, RunManager)
        assert app.state.run_manager._settings is not None

    def _queued(self, mgr, run_id="q1"):
        run = _real_run(run_id, status=STATUS_QUEUED)
        mgr._runs[run_id] = run
        mgr.enqueue(
            run_id,
            task="queued work",
            tier="restricted",
            provider_override="openai",
            model_override="gpt-4o",
        )
        return run

    def test_drain_does_not_call_request_scoped_deps(self, app_client, monkeypatch):
        """The regression: _drain_queue_after_run called
        api.get_run_manager() + deps.get_settings() from the runner
        thread, where they are no longer valid. Patch both to raise; a
        correct drain must never touch them."""
        _, app = app_client
        mgr = app.state.run_manager
        self._queued(mgr)

        def boom(*a, **k):
            raise AssertionError("queue drain must not use request-scoped dependencies")

        monkeypatch.setattr(api_mod, "get_run_manager", boom, raising=False)
        monkeypatch.setattr(api_mod, "get_settings", boom, raising=False)
        monkeypatch.setattr(deps_mod, "get_settings", boom, raising=False)

        started = []
        monkeypatch.setattr(ar, "run_in_thread", lambda *a, **k: started.append((a, k)))

        mgr._drain_queue(_real_run("finisher", status="done"))

        assert len(started) == 1, "drain should have started exactly one run"
        args, kwargs = started[0]
        assert args[2] is mgr, "run_in_thread must receive the owning manager"
        assert kwargs["cost_cap_tracker"] is app.state.cost_cap_tracker

    def test_drain_uses_manager_settings(self, app_client, monkeypatch):
        _, app = app_client
        mgr = app.state.run_manager
        self._queued(mgr)
        seen = {}

        def fake_run_in_thread(run, settings, manager=None, cost_cap_tracker=None):
            seen["settings"] = settings
            seen["manager"] = manager

        monkeypatch.setattr(ar, "run_in_thread", fake_run_in_thread)
        mgr._drain_queue(_real_run("finisher", status="done"))
        assert seen["settings"] is mgr._settings
        assert seen["manager"] is mgr

    def test_drain_without_settings_raises_rather_than_silently_no_op(self):
        """A manager with no Settings cannot start a queued run. The old
        code swallowed every drain error, so this is the class of failure
        that shipped as 'the queue just never moves'."""
        mgr = RunManager()
        run = Run(id="q1", task="queued work", tier="restricted", status=STATUS_QUEUED)
        mgr._runs["q1"] = run
        mgr.enqueue("q1", task="queued work", tier="restricted")
        with pytest.raises(RuntimeError, match="Settings"):
            ar._drain_queue_after_run(_real_run("finisher", status="done"), mgr)

    def test_queue_drain_error_is_recorded_not_swallowed(self, app_client, monkeypatch):
        _, app = app_client
        mgr = app.state.run_manager
        self._queued(mgr)
        mgr.queue_drain_error = "stale-sentinel"

        def explode(*a, **k):
            raise RuntimeError("drain exploded")

        monkeypatch.setattr(ar, "_drain_queue_after_run", explode)
        mgr._drain_queue(_real_run("finisher", status="done"))
        assert mgr.queue_drain_error == "drain exploded"

    def test_queue_drain_error_clears_on_success(self, app_client, monkeypatch):
        _, app = app_client
        mgr = app.state.run_manager
        self._queued(mgr)
        mgr.queue_drain_error = "stale-sentinel"
        monkeypatch.setattr(ar, "run_in_thread", lambda *a, **k: None)
        mgr._drain_queue(_real_run("finisher", status="done"))
        assert mgr.queue_drain_error is None

    def test_empty_queue_is_a_noop(self, app_client):
        _, app = app_client
        mgr = app.state.run_manager
        assert mgr._drain_queue(_real_run("finisher", status="done")) is None
        assert mgr.queue_drain_error is None

    def test_drain_starts_in_fifo_order(self, app_client, monkeypatch):
        _, app = app_client
        mgr = app.state.run_manager
        self._queued(mgr, "q1")
        self._queued(mgr, "q2")
        order = []

        def fake(run, settings, manager=None, cost_cap_tracker=None):
            order.append(run.id)

        monkeypatch.setattr(ar, "run_in_thread", fake)
        mgr._drain_queue(_real_run("finisher", status="done"))
        mgr._drain_queue(_real_run("finisher2", status="done"))
        assert order == ["q1", "q2"]


class TestCostCapsSurviveProjectChanges:
    """Phase 4 (decision 0039): project create/delete must not wipe caps.

    Caps are seeded the way an operator actually sets them -- the
    SMOLCODE_COST_CAPS / SMOLCODE_COST_RATES env vars read by
    load_settings() -- rather than by poking the Settings object.
    """

    @pytest.fixture
    def capped_app(self, monkeypatch):
        workspace = _clear_env(monkeypatch)
        monkeypatch.setenv("SMOLCODE_COST_CAPS", '{"openai": 5.0}')
        # {provider: {model: [in_per_1k, out_per_1k, cache_per_1k]}}
        monkeypatch.setenv("SMOLCODE_COST_RATES", '{"openai": {"gpt-4o": [0.005, 0.015, 0.005]}}')
        app = create_app(settings=load_settings())
        client = TestClient(app)
        client.__enter__()
        try:
            assert app.state.settings.cost_caps == {"openai": 5.0}
            assert app.state.settings.cost_rates == {"openai": {"gpt-4o": [0.005, 0.015, 0.005]}}
            yield client, app
        finally:
            client.__exit__(None, None, None)
            shutil.rmtree(workspace, ignore_errors=True)

    def test_with_overrides_accepts_projects(self):
        base = load_settings()
        out = base.with_overrides(projects=())
        assert out.projects == ()

    def test_create_project_preserves_caps(self, capped_app):
        client, app = capped_app
        r = client.post("/api/projects", json={"name": "demo"})
        assert r.status_code == 201, r.text
        assert app.state.settings.cost_caps == {"openai": 5.0}
        assert app.state.settings.cost_rates == {"openai": {"gpt-4o": [0.005, 0.015, 0.005]}}

    def test_delete_project_preserves_caps(self, capped_app):
        client, app = capped_app
        r = client.post("/api/projects", json={"name": "demo"})
        assert r.status_code == 201, r.text
        r = client.request("DELETE", "/api/projects/demo")
        assert r.status_code == 200, r.text
        assert app.state.settings.cost_caps == {"openai": 5.0}
        assert app.state.settings.cost_rates == {"openai": {"gpt-4o": [0.005, 0.015, 0.005]}}

    def test_manager_settings_stay_in_sync_with_projects(self, capped_app):
        """A run drained from the queue after a project change must see
        the NEW project list, not the boot-time snapshot."""
        client, app = capped_app
        mgr = app.state.run_manager
        assert mgr._settings is app.state.settings
        client.post("/api/projects", json={"name": "demo"})
        assert mgr._settings is app.state.settings
        assert [p.name for p in mgr._settings.projects] == ["demo"]
