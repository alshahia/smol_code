"""Decision 0032: per-provider usage caps.

Five test classes totalling 35 tests.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from smolcode.config import ConfigError, _parse_cost_caps, as_dict, load_settings
from smolcode.web.cost_caps import CostCapTracker
from smolcode.web.server import create_app


# ---- TestParseCostCaps -----


class TestParseCostCaps:
    def test_empty(self):
        assert _parse_cost_caps("") == {}

    def test_valid(self):
        out = _parse_cost_caps(json.dumps({"openai": 1.5}))
        assert out == {"openai": 1.5}

    def test_invalid_json(self):
        with pytest.raises(ConfigError):
            _parse_cost_caps("bad json")

    def test_non_object(self):
        with pytest.raises(ConfigError):
            _parse_cost_caps(json.dumps([1, 2]))

    def test_non_numeric(self):
        with pytest.raises(ConfigError):
            _parse_cost_caps(json.dumps({"x": "bad"}))

    def test_negative(self):
        with pytest.raises(ConfigError):
            _parse_cost_caps(json.dumps({"x": -1}))

    def test_bool_rejected(self):
        with pytest.raises(ConfigError):
            _parse_cost_caps(json.dumps({"x": True}))

    def test_string_coercible(self):
        out = _parse_cost_caps(json.dumps({"x": "1.5"}))
        assert out == {"x": 1.5}


# ---- TestSettingsCostCaps -----


class TestSettingsCostCaps:
    def test_default(self, _isolate_env):
        s = load_settings()
        assert s.cost_caps == {}

    def test_with_overrides(self, _isolate_env, monkeypatch, tmp_path):
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path / "ws"))
        monkeypatch.setenv("SMOLCODE_COST_CAPS", json.dumps({"openai": 1.0}))
        s = load_settings()
        assert s.with_overrides(provider="x").cost_caps == {"openai": 1.0}

    def test_with_executor(self, _isolate_env, monkeypatch, tmp_path):
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path / "ws"))
        monkeypatch.setenv("SMOLCODE_COST_CAPS", json.dumps({"openai": 0.5}))
        s = load_settings()
        assert s.with_executor("local").cost_caps == {"openai": 0.5}

    def test_as_dict_includes(self, _isolate_env):
        d = as_dict(load_settings())
        assert "cost_caps" in d and d["cost_caps"] == {}


# ---- TestCostCapTracker -----


class TestCostCapTracker:
    def test_init_drops_invalid(self):
        t = CostCapTracker(defaults={"openai": 1.0, "MiniMax": 0, "anthropic": -1, "bad": None, "b": True, "c": "x"})
        state = t.get_state()
        assert state["defaults"] == {"openai": 1.0}
        assert state["caps"] == {"openai": 1.0}

    def test_init_default(self):
        t = CostCapTracker()
        assert t.get_state() == {"caps": {}, "defaults": {}}
        assert t.get_cap("openai") == 0.0

    def test_state_independent(self):
        t = CostCapTracker(defaults={"openai": 1.0})
        snap = t.get_state()
        snap["caps"]["openai"] = 999.0
        snap["defaults"]["openai"] = 999.0
        assert t.get_state() == {"caps": {"openai": 1.0}, "defaults": {"openai": 1.0}}

    def test_update_replaces(self):
        t = CostCapTracker(defaults={"openai": 1.0})
        returned = t.update({"anthropic": 2.5})
        assert returned == {"anthropic": 2.5}
        assert t.get_state() == {"caps": {"anthropic": 2.5}, "defaults": {"openai": 1.0}}

    def test_update_silently_drops(self):
        t = CostCapTracker()
        returned = t.update({"openai": 1.5, "bad": None, "neg": -3, "zero": 0, "b": True, "ok_str": "2.5"})
        assert returned == {"openai": 1.5, "ok_str": 2.5}

    def test_update_empty_clears(self):
        t = CostCapTracker(defaults={"openai": 1.0})
        t.update({"anthropic": 2.5})
        returned = t.update({})
        assert returned == {}
        assert t.get_state()["defaults"] == {"openai": 1.0}

    def test_reset_restores_defaults(self):
        t = CostCapTracker(defaults={"openai": 1.0, "MiniMax": 2.0})
        t.update({"anthropic": 3.0})
        returned = t.reset()
        assert returned == {"openai": 1.0, "MiniMax": 2.0}
        assert t.get_state()["caps"] == t.get_state()["defaults"]

    def test_check_reached_zero_cap(self):
        t = CostCapTracker(defaults={"openai": 0})
        reached, reason = t.check_reached("openai", 99999.0)
        assert reached is False
        assert reason == ""

    def test_check_reached_above_cap(self):
        t = CostCapTracker(defaults={"openai": 1.0})
        reached, reason = t.check_reached("openai", 1.0)
        assert reached is True
        assert "openai" in reason and "1.0000" in reason
        assert t.check_reached("openai", 0.9999) == (False, "")

    def test_check_reached_percent_format(self):
        # The reason MUST use %-format (NOT f-string).
        import inspect

        src = inspect.getsource(CostCapTracker.check_reached)
        assert "%" in src
        reason_lines = [ln for ln in src.splitlines() if "reason" in ln and "%" in ln]
        assert reason_lines
        for ln in reason_lines:
            stripped = ln.lstrip()
            assert not (stripped.startswith("reason = f") or stripped.startswith("reason = f"))
        # Runtime check too.
        t = CostCapTracker(defaults={"MiniMax": 5.0})
        reached, reason = t.check_reached("MiniMax", 5.0)
        assert reached is True
        assert "MiniMax" in reason
        assert "5.0000" in reason
        assert "cost cap reached for provider" in reason

    def test_check_reached_unknown(self):
        t = CostCapTracker(defaults={"openai": 1.0})
        reached, reason = t.check_reached("nonexistent", 99999.0)
        assert reached is False
        assert reason == ""

    def test_check_reached_thread_safe(self):
        t = CostCapTracker(defaults={"openai": 1.0})
        errors = []

        def _writer():
            try:
                for _ in range(50):
                    t.update({"openai": 1.0})
            except Exception as e:
                errors.append(e)

        def _reader():
            try:
                for _ in range(50):
                    t.check_reached("openai", 0.5)
                    t.get_cap("openai")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_writer) for _ in range(5)]
        threads += [threading.Thread(target=_reader) for _ in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert errors == []
        assert t.get_cap("openai") == 1.0


# ---- TestCostCapsAPI -----


@contextmanager
def _app_with_cap(monkeypatch, caps=None):
    """Build TestClient with app.state.cost_cap_tracker populated."""
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    import tempfile

    workspace = tempfile.mkdtemp(prefix="smolcode-costcaps-")
    monkeypatch.setenv("SMOLCODE_WORKSPACE", workspace)
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    monkeypatch.setenv("SMOLCODE_LOG_LEVEL", "WARNING")
    settings = load_settings()
    app = create_app(settings=settings)
    client = TestClient(app)
    client.__enter__()
    if caps is not None:
        app.state.cost_cap_tracker.update(caps)
    try:
        yield client
    finally:
        client.__exit__(None, None, None)


class TestCostCapsAPI:
    def test_get_empty(self, monkeypatch):
        with _app_with_cap(monkeypatch) as c:
            r = c.get("/api/cost-caps")
            assert r.status_code == 200
            body = r.json()
            assert body["caps"] == []
            assert body["defaults"] == []
            assert isinstance(body["providers"], list)
            assert isinstance(body["current_spend_usd"], dict)

    def test_put_round_trips(self, monkeypatch):
        with _app_with_cap(monkeypatch) as c:
            r = c.put("/api/cost-caps", json={"caps": {"openai": 1.0, "MiniMax": 2.5}})
            assert r.status_code == 200
            body = r.json()
            caps_by = {x["provider"]: x["cap_usd"] for x in body["caps"]}
            assert caps_by["openai"] == 1.0
            assert caps_by["MiniMax"] == 2.5
            assert isinstance(body["updated_at"], float)
            assert body["updated_at"] <= time.time()
            assert body["updated_at"] > time.time() - 60
            g = c.get("/api/cost-caps")
            gcaps_by = {x["provider"]: x["cap_usd"] for x in g.json()["caps"]}
            assert gcaps_by["openai"] == 1.0
            assert gcaps_by["MiniMax"] == 2.5

    def test_put_unknown_400(self, monkeypatch):
        with _app_with_cap(monkeypatch) as c:
            r = c.put("/api/cost-caps", json={"caps": {"not-a-real-provider": 1.0}})
            assert r.status_code == 400
            assert "not-a-real-provider" in r.json()["detail"]

    def test_put_empty_clears(self, monkeypatch):
        with _app_with_cap(monkeypatch) as c:
            c.put("/api/cost-caps", json={"caps": {"openai": 1.0}})
            r = c.put("/api/cost-caps", json={"caps": {}})
            assert r.status_code == 200
            assert r.json()["caps"] == []
            g = c.get("/api/cost-caps")
            assert g.json()["caps"] == []

    def test_put_minimax_alias_400(self, monkeypatch):
        with _app_with_cap(monkeypatch) as c:
            r = c.put("/api/cost-caps", json={"caps": {"minimax": 1.0}})
            assert r.status_code == 400
            assert "minimax" in r.json()["detail"]

    def test_put_canonical_MiniMax(self, monkeypatch):
        with _app_with_cap(monkeypatch) as c:
            r = c.put("/api/cost-caps", json={"caps": {"MiniMax": 1.0}})
            assert r.status_code == 200
            caps_by = {x["provider"]: x["cap_usd"] for x in r.json()["caps"]}
            assert caps_by["MiniMax"] == 1.0

    def test_get_shape(self, monkeypatch):
        with _app_with_cap(monkeypatch) as c:
            r = c.get("/api/cost-caps")
            body = r.json()
            for key in ("caps", "defaults", "providers", "current_spend_usd"):
                assert key in body
            assert isinstance(body["caps"], list)
            assert isinstance(body["defaults"], list)
            assert isinstance(body["providers"], list)
            assert isinstance(body["current_spend_usd"], dict)


# ---- TestRunStartCapEnforcement -----


@contextmanager
def _app_with_running_runs(monkeypatch, runs):
    """Build an app with fake run history so dashboard computes a real cost_usd."""
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    import tempfile

    workspace = tempfile.mkdtemp(prefix="smolcode-costcaps-")
    monkeypatch.setenv("SMOLCODE_WORKSPACE", workspace)
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    monkeypatch.setenv("SMOLCODE_LOG_LEVEL", "WARNING")
    settings = load_settings()
    app = create_app(settings=settings)
    client = TestClient(app)
    client.__enter__()
    mgr = app.state.run_manager
    mgr.list_all_runs = lambda: list(runs)
    try:
        yield client, app, mgr
    finally:
        client.__exit__(None, None, None)


def _fake_run(*, provider, model, started_at, tokens_in, tokens_out):
    from types import SimpleNamespace

    return SimpleNamespace(
        provider=provider,
        model=model,
        started_at=started_at,
        tokens=SimpleNamespace(input=tokens_in, output=tokens_out, cache_hit=0, total=tokens_in + tokens_out),
    )


def _stub_build_agent(run, settings):
    """Tiny CodeAgent stand-in so POST /api/runs returns synchronously."""
    from smolagents import CodeAgent

    from smolcode.models import _StubLiteLLMModel

    class _StubCodeAgent(CodeAgent):
        def __init__(self):
            self.tools = []
            self.model = _StubLiteLLMModel()
            self.max_steps = 4
            self.step_callbacks = type("CB", (), {"register": lambda self, cls, cb: None})()

        def run(self, task):
            return "stub-final-answer"

        def cleanup(self):
            pass

    return _StubCodeAgent()


class TestRunStartCapEnforcement:
    """Decision 0032 sec 2: per-day cap rejection at run-start."""

    def test_reached_cap_rejects_429(self, monkeypatch):
        now = time.time()
        # gpt-4o @ $0.005/$0.015 -- 200k in + 100k out = $2.50 today
        runs = [_fake_run(provider="openai", model="gpt-4o", started_at=now - 60, tokens_in=200000, tokens_out=100000)]
        with _app_with_running_runs(monkeypatch, runs) as (c, app, mgr):
            tracker = app.state.cost_cap_tracker
            tracker.update({"openai": 1.0})
            r = c.post("/api/runs", json={"task": "hi", "tier": "restricted", "provider": "openai"})
            assert r.status_code == 429
            assert "cost_cap_reached:" in r.json()["detail"]

    def test_below_cap_allows(self, monkeypatch):
        now = time.time()
        runs = [_fake_run(provider="openai", model="gpt-4o", started_at=now - 60, tokens_in=100000, tokens_out=0)]
        with _app_with_running_runs(monkeypatch, runs) as (c, app, mgr):
            tracker = app.state.cost_cap_tracker
            tracker.update({"openai": 1.0})
            from smolcode.web import agent_runner as ar

            monkeypatch.setattr(ar, "_build_agent_for_run", _stub_build_agent)
            r = c.post("/api/runs", json={"task": "hi", "tier": "restricted", "provider": "openai"})
            assert r.status_code == 201

    def test_cap_other_provider_doesnt_block(self, monkeypatch):
        now = time.time()
        runs = [_fake_run(provider="openai", model="gpt-4o", started_at=now - 60, tokens_in=200000, tokens_out=200000)]
        with _app_with_running_runs(monkeypatch, runs) as (c, app, mgr):
            tracker = app.state.cost_cap_tracker
            tracker.update({"anthropic": 1.0})
            from smolcode.web import agent_runner as ar

            monkeypatch.setattr(ar, "_build_agent_for_run", _stub_build_agent)
            r = c.post("/api/runs", json={"task": "hi", "tier": "restricted", "provider": "openai"})
            assert r.status_code == 201

    def test_no_caps_allows(self, monkeypatch):
        now = time.time()
        runs = [
            _fake_run(provider="openai", model="gpt-4o", started_at=now - 60, tokens_in=99999999, tokens_out=99999999)
        ]
        with _app_with_running_runs(monkeypatch, runs) as (c, app, mgr):
            from smolcode.web import agent_runner as ar

            monkeypatch.setattr(ar, "_build_agent_for_run", _stub_build_agent)
            r = c.post("/api/runs", json={"task": "hi", "tier": "restricted", "provider": "openai"})
            assert r.status_code == 201

    def test_unknown_provider_no_429(self, monkeypatch):
        now = time.time()
        runs = [_fake_run(provider="unknown", model="x", started_at=now - 60, tokens_in=10000000, tokens_out=10000000)]
        with _app_with_running_runs(monkeypatch, runs) as (c, app, mgr):
            tracker = app.state.cost_cap_tracker
            tracker.update({"openai": 1.0})
            from smolcode.web import agent_runner as ar

            monkeypatch.setattr(ar, "_build_agent_for_run", _stub_build_agent)
            r = c.post("/api/runs", json={"task": "hi", "tier": "restricted", "provider": "bogus-provider"})
            assert r.status_code in (201, 400)
            assert r.status_code != 429
