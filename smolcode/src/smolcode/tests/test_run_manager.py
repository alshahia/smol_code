"""Tests for the M9 run manager + SSE generator.

These tests exercise the Run / RunManager / PendingDecision lifecycle
WITHOUT spinning up a real agent (so they do not depend on smolagents
network or Docker). The agent runner is tested separately via the API
endpoints (test_web_runs_api.py) using a stub model.
"""

from __future__ import annotations

import json

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
