"""Tests for the M9 run manager + SSE generator.

These tests exercise the Run / RunManager / PendingDecision lifecycle
WITHOUT spinning up a real agent (so they do not depend on smolagents
network or Docker). The agent runner is tested separately via the API
endpoints (test_web_runs_api.py) using a stub model.
"""

from __future__ import annotations

import json
import threading

import pytest

from smolcode.web.runs import (
    EVT_APPROVAL_REQUESTED,
    EVT_RUN_ENDED,
    EVT_RUN_STARTED,
    EVT_STEP_ACTION,
    STATUS_DONE,
    PendingDecision,
    Run,
    RunManager,
    _encode_event,
)


# ---- TestSSEEncoding -----------------------------------------------------


class TestSSEEncoding:
    def test_encode_event_basic(self):
        frame = _encode_event("step.action", {"step_number": 1, "thought": "hi"})
        # Must contain event type + data JSON + trailing blank line
        assert "event: step.action" in frame
        assert 'data: {"step_number":1,"thought":"hi"}' in frame
        assert frame.endswith("\n\n")

    def test_encode_event_with_id(self):
        frame = _encode_event("run.started", {"run_id": "abc"}, event_id="abc:1")
        assert frame.startswith("id: abc:1\n")
        assert "event: run.started" in frame

    def test_encode_event_unicode_safe(self):
        # Non-ASCII chars in data must round-trip cleanly.
        frame = _encode_event("step.action", {"thought": "R\u00e9sum\u00e9 the diff"})
        assert "R\u00e9sum\u00e9" in frame


# ---- TestRun -------------------------------------------------------------


class TestRun:
    def test_publish_enqueues_sse_frame(self):
        run = Run(id="r1", task="t", tier="restricted")
        run.publish(EVT_RUN_STARTED, {"run_id": "r1", "task": "t"})
        frame = run.events.get_nowait()
        assert "event: run.started" in frame
        # JSON-decodable
        line = next(ln for ln in frame.splitlines() if ln.startswith("data:"))
        payload = json.loads(line[len("data: ") :])
        assert payload["run_id"] == "r1"

    def test_publish_assigns_monotonic_event_id(self):
        run = Run(id="r1", task="t", tier="restricted")
        run.publish(EVT_STEP_ACTION, {"step_number": 1})
        run.publish(EVT_STEP_ACTION, {"step_number": 2})
        run.publish(EVT_STEP_ACTION, {"step_number": 3})
        ids = []
        while not run.events.empty():
            frame = run.events.get_nowait()
            for line in frame.splitlines():
                if line.startswith("id:"):
                    ids.append(line[len("id: ") :])
        # 3 unique, monotonically increasing within this run
        assert len(ids) == 3
        assert ids == sorted(ids)
        assert all(i.startswith("r1:") for i in ids)

    def test_open_decision_appends_to_pending(self):
        run = Run(id="r1", task="t", tier="restricted")
        d = run.open_decision("shell.run", {"cmd": "pytest"}, "run pytest", "restricted")
        assert len(run.pending) == 1
        assert d.id == run.pending[0].id
        assert d.tool == "shell.run"

    def test_take_decision_removes(self):
        run = Run(id="r1", task="t", tier="restricted")
        d1 = run.open_decision("shell.run", {}, "a", "restricted")
        d2 = run.open_decision("git.push", {}, "b", "restricted")
        assert len(run.pending) == 2
        taken = run.take_decision(d1.id)
        assert taken is d1
        assert len(run.pending) == 1
        assert run.pending[0] is d2
        # second take returns None
        assert run.take_decision(d1.id) is None


# ---- TestPendingDecision -------------------------------------------------


class TestPendingDecision:
    def test_resolve_sets_approved_and_event(self):
        d = PendingDecision(id="x", tool="t", args={}, summary="s", tier="restricted")
        assert not d.event.is_set()
        d.resolve(approved=True, edited_args=None, reason="user")
        assert d.event.is_set()
        assert d.approved is True
        assert d.reason == "user"

    def test_resolve_is_idempotent(self):
        d = PendingDecision(id="x", tool="t", args={}, summary="s", tier="restricted")
        d.resolve(approved=True, edited_args=None, reason="first")
        d.resolve(approved=False, edited_args=None, reason="second")
        # Second resolve must not overwrite.
        assert d.approved is True
        assert d.reason == "first"


# ---- TestRunManager ------------------------------------------------------


class TestRunManager:
    def test_start_run_rejects_empty_task(self):
        mgr = RunManager()
        with pytest.raises(ValueError, match="non-empty"):
            mgr.start_run(task="", tier="restricted", settings=None)

    def test_start_run_rejects_unknown_tier(self):
        mgr = RunManager()
        with pytest.raises(ValueError, match="tier"):
            mgr.start_run(task="x", tier="bogus", settings=None)

    def test_decide_resolves_pending_gate(self):
        mgr = RunManager()
        # Inject a Run directly (skip the worker thread for unit test).
        run = Run(id="r1", task="t", tier="restricted")
        mgr._runs[run.id] = run  # type: ignore[attr-defined]
        d = run.open_decision("shell.run", {"cmd": "x"}, "summary", "restricted")
        run.publish(EVT_APPROVAL_REQUESTED, {"decision_id": d.id, "tool": "shell.run"})

        ok = mgr.decide(run.id, d.id, approved=True, reason="user")
        assert ok is True
        assert d.event.is_set()
        assert d.approved is True
        # Approval.decided event should now be in the queue.
        frames = []
        while not run.events.empty():
            frames.append(run.events.get_nowait())
        assert any("approval.decided" in f for f in frames)

    def test_decide_unknown_run_returns_false(self):
        mgr = RunManager()
        assert mgr.decide("nope", "x", approved=True) is False

    def test_decide_unknown_decision_returns_false(self):
        mgr = RunManager()
        run = Run(id="r1", task="t", tier="restricted")
        mgr._runs[run.id] = run  # type: ignore[attr-defined]
        assert mgr.decide(run.id, "no-such-decision", approved=True) is False

    def test_stop_sets_flag(self):
        mgr = RunManager()
        run = Run(id="r1", task="t", tier="restricted")
        mgr._runs[run.id] = run  # type: ignore[attr-defined]
        assert not run.stop_flag.is_set()
        assert mgr.stop(run.id) is True
        assert run.stop_flag.is_set()

    def test_stop_unknown_run_returns_false(self):
        mgr = RunManager()
        assert mgr.stop("nope") is False

    def test_get_and_list(self):
        mgr = RunManager()
        r1 = Run(id="r1", task="t", tier="restricted")
        r2 = Run(id="r2", task="u", tier="elevated")
        mgr._runs[r1.id] = r1  # type: ignore[attr-defined]
        mgr._runs[r2.id] = r2  # type: ignore[attr-defined]
        assert mgr.get("r1") is r1
        assert mgr.get("nope") is None
        ids = sorted(r.id for r in mgr.list())
        assert ids == ["r1", "r2"]

    def test_subscribe_unknown_run_raises_keyerror(self):
        mgr = RunManager()
        with pytest.raises(KeyError):
            next(mgr.subscribe("nope"))

    def test_subscribe_yields_queued_events_then_exits_on_terminal(self):
        mgr = RunManager()
        run = Run(id="r1", task="t", tier="restricted")
        mgr._runs[run.id] = run  # type: ignore[attr-defined]
        # Pre-publish 3 events and mark terminal.
        run.publish(EVT_RUN_STARTED, {"run_id": "r1"})
        run.publish(EVT_STEP_ACTION, {"step_number": 1})
        run.publish(EVT_RUN_ENDED, {"run_id": "r1", "status": "done"})
        run.status = STATUS_DONE
        gen = mgr.subscribe("r1")
        frames = list(gen)
        # 3 queued frames + 1 sentinel end frame
        assert len(frames) == 4
        assert any("run.started" in f for f in frames)
        assert any("step.action" in f for f in frames)
        assert any("run.ended" in f for f in frames)
        assert any("event: end" in f for f in frames)

    def test_subscribe_heartbeat_then_idle(self):
        """subscribe() yields at least one heartbeat (SSE comment) then
        exits with a sentinel when the run is already in a terminal state."""
        mgr = RunManager()
        run = Run(id="r1", task="t", tier="restricted")
        mgr._runs[run.id] = run  # type: ignore[attr-defined]
        run.status = STATUS_DONE
        gen = mgr.subscribe("r1")
        frames = list(gen)
        # One heartbeat comment (from the empty queue branch) + one
        # sentinel end frame.
        assert len(frames) == 2
        assert frames[0].startswith(": heartbeat")
        assert "event: end" in frames[1]


# ---- TestTokenAggregation (Phase 0, decision 0025 BE-3) ----------


class TestTokenAggregation:
    """Verify that Run.publish auto-aggregates token + step counts on
    every step.action event and that increment_tokens + summary_dict
    are consistent under concurrent publishes.
    """

    def test_single_step_action_aggregates_tokens(self):
        run = Run(id="r1", task="t", tier="restricted")
        run.publish(EVT_STEP_ACTION, {"step_number": 1, "tokens": {"input": 10, "output": 5}})
        snap = run.summary_dict()
        assert snap["tokens_in"] == 10
        assert snap["tokens_out"] == 5
        assert snap["tokens_total"] == 15
        assert snap["step_count"] == 1
        assert snap["subagent"] is None

    def test_two_steps_sum(self):
        run = Run(id="r1", task="t", tier="restricted")
        run.publish(EVT_STEP_ACTION, {"step_number": 1, "tokens": {"input": 10, "output": 5}})
        run.publish(EVT_STEP_ACTION, {"step_number": 2, "tokens": {"input": 3, "output": 2}})
        snap = run.summary_dict()
        assert snap["tokens_in"] == 13
        assert snap["tokens_out"] == 7
        assert snap["tokens_total"] == 20
        assert snap["step_count"] == 2

    def test_step_action_without_tokens_still_bumps_count(self):
        run = Run(id="r1", task="t", tier="restricted")
        # Tokens field is missing -> tokens stay 0 but step_count goes up.
        run.publish(EVT_STEP_ACTION, {"step_number": 1})
        snap = run.summary_dict()
        assert snap["tokens_in"] == 0
        assert snap["tokens_out"] == 0
        assert snap["step_count"] == 1

    def test_concurrent_publishes_under_pending_lock(self):
        """100 concurrent step.action publishes with a per-thread delta
        must produce totals == 100 * delta (no lost increments).
        """
        run = Run(id="r1", task="t", tier="restricted")
        n_threads = 100
        delta_in = 7
        delta_out = 3

        def worker():
            for _ in range(5):
                run.publish(EVT_STEP_ACTION, {"tokens": {"input": delta_in, "output": delta_out}})

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = run.summary_dict()
        assert snap["tokens_in"] == n_threads * 5 * delta_in
        assert snap["tokens_out"] == n_threads * 5 * delta_out
        assert snap["step_count"] == n_threads * 5
        assert snap["tokens_total"] == snap["tokens_in"] + snap["tokens_out"]

    def test_increment_tokens_helper(self):
        """Public increment_tokens() entry point used by callers that
        already know the delta (bypasses the step.action round-trip).
        """
        run = Run(id="r1", task="t", tier="restricted")
        run.increment_tokens(10, 5)
        run.increment_tokens(3, 2)
        snap = run.summary_dict()
        assert snap["tokens_in"] == 13
        assert snap["tokens_out"] == 7
        assert snap["tokens_total"] == 20
        # Malformed input is silently ignored.
        run.increment_tokens("not a number", None)  # type: ignore[arg-type]
        snap2 = run.summary_dict()
        assert snap2["tokens_total"] == 20

    def test_remaining_s_decreases_then_negative(self):
        """Phase 0 (decision 0025 BE-5): remaining_s = max_wall_s - elapsed.
        Returns None when budget is disabled, negative when expired.
        """
        import time as _time

        run = Run(id="r1", task="t", tier="restricted")
        # Disable -> None.
        assert run.remaining_s(0) is None
        # Positive budget -> float close to the budget (immediately).
        v = run.remaining_s(900)
        assert v is not None and 895 < v <= 900
        # Tiny budget -> already negative.
        _time.sleep(0.05)
        assert run.remaining_s(0.01) < 0

    def test_summary_dict_includes_subagent_when_set(self):
        """Phase 0 (decision 0025 BE-1): summary_dict surfaces the active
        sub-agent invocation when set on the Run.
        """
        run = Run(id="r1", task="t", tier="restricted")
        run.subagent_id = "sub-abc"
        run.subagent_tier = "restricted"
        run.subagent_started_at = 1.0
        run.subagent_ended_at = 2.5
        snap = run.summary_dict()
        assert snap["subagent"] is not None
        assert snap["subagent"]["id"] == "sub-abc"
        assert snap["subagent"]["tier"] == "restricted"
        assert snap["subagent"]["started_at"] == 1.0
        assert snap["subagent"]["ended_at"] == 2.5


# ---- TestSubAgentEvents (Phase 0, decision 0025 T-1 + T-3) ----------


class TestSubAgentEvents:
    """Verify the sub-agent lifecycle events emitted by the orchestrator
    wrappers (_build_delegation_tool / _build_specialist_tool).

    These tests exercise the helper directly without spinning up a
    real CodeAgent -- the forward() method is the unit under test.
    """

    def test_delegate_emits_started_and_ended(self, tmp_path):
        """BE-2: started fires before inner agent.run; ended fires after."""
        from smolcode.agents.orchestrator import _build_delegation_tool

        # Build a minimal Settings object (only needs .tiers).
        from smolcode.config import Settings, _default_tiers
        from smolcode.web.runs import (
            EVT_SUBAGENT_ENDED,
            EVT_SUBAGENT_STARTED,
        )

        settings = Settings(
            workspace=tmp_path,
            executor="local",
            provider="opencode-go",
            model="stub",
            litellm_proxy=None,
            log_level="WARNING",
            tiers=_default_tiers(),
        )
        # Use a stub outer_run to capture events.
        outer = Run(id="outer", task="orchestrator task", tier="orchestrator")
        events_seen: list = []
        outer_orig_publish = outer.publish

        def capture(event_type, data):
            events_seen.append((event_type, data))
            outer_orig_publish(event_type, data)

        outer.publish = capture  # type: ignore[method-assign]
        # Build the tool with a no-op inner agent.run by patching make_agent.
        from smolcode.agents import orchestrator as _orch

        class _StubAgent:
            def run(self, task):
                return "stubbed sub-agent answer"

        orig_make = _orch.make_agent
        _orch.make_agent = lambda tier, settings, model: _StubAgent()
        try:
            tool = _build_delegation_tool("restricted", settings, model=None, outer_run=outer)
            answer = tool.forward("do the thing")
        finally:
            _orch.make_agent = orig_make
        assert answer == "stubbed sub-agent answer"
        types = [e[0] for e in events_seen]
        assert types[0] == EVT_SUBAGENT_STARTED
        assert types[-1] == EVT_SUBAGENT_ENDED
        # Outer Run state was set + cleared across the call.
        assert outer.subagent_id is not None
        assert outer.subagent_tier == "restricted"
        assert outer.subagent_ended_at is not None
        # Started payload has the expected fields.
        started_payload = events_seen[0][1]
        assert started_payload["parent_run_id"] == "outer"
        assert started_payload["tier"] == "restricted"
        # Ended payload carries status=ok + duration.
        ended_payload = events_seen[-1][1]
        assert ended_payload["status"] == "ok"
        assert "duration_s" in ended_payload

    def test_delegate_ended_fires_on_inner_error(self, tmp_path):
        """BE-2: when the inner agent raises, ended still fires (status=error)."""
        from smolcode.agents.orchestrator import _build_delegation_tool
        from smolcode.config import Settings, _default_tiers
        from smolcode.web.runs import EVT_SUBAGENT_ENDED

        settings = Settings(
            workspace=tmp_path,
            executor="local",
            provider="opencode-go",
            model="stub",
            litellm_proxy=None,
            log_level="WARNING",
            tiers=_default_tiers(),
        )
        outer = Run(id="outer", task="orchestrator task", tier="orchestrator")
        events_seen: list = []
        outer_orig_publish = outer.publish

        def capture(event_type, data):
            events_seen.append((event_type, data))
            outer_orig_publish(event_type, data)

        outer.publish = capture  # type: ignore[method-assign]
        from smolcode.agents import orchestrator as _orch

        class _BoomAgent:
            def run(self, task):
                raise RuntimeError("inner boom")

        orig_make = _orch.make_agent
        _orch.make_agent = lambda tier, settings, model: _BoomAgent()
        try:
            tool = _build_delegation_tool("restricted", settings, model=None, outer_run=outer)
            with pytest.raises(RuntimeError, match="inner boom"):
                tool.forward("task")
        finally:
            _orch.make_agent = orig_make
        ended_events = [e for e in events_seen if e[0] == EVT_SUBAGENT_ENDED]
        assert len(ended_events) == 1
        assert ended_events[0][1]["status"] == "error"
        assert ended_events[0][1]["error_kind"] == "RuntimeError"
        assert "inner boom" in ended_events[0][1]["error"]
        # Outer subagent_ended_at was set even on error.
        assert outer.subagent_ended_at is not None
