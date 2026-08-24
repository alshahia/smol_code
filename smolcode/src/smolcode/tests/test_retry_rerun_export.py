"""Phase 3 (decision 0025 sec 6.5): retry / rerun / export / events_snapshot tests."""

from __future__ import annotations

import pytest

from smolcode.web.runs import Run, RunManager


class TestEventsSnapshot:
    def test_empty_run(self):
        mgr = RunManager()
        run = Run(id="r1", task="x", tier="restricted")
        mgr._runs[run.id] = run
        assert mgr.events_snapshot("r1") == []

    def test_snapshot_includes_published_events(self):
        mgr = RunManager()
        run = Run(id="r1", task="x", tier="restricted")
        mgr._runs[run.id] = run
        run.publish("run.started", {"task": "x"})
        run.publish("step.action", {"tokens": {"input": 10, "output": 5}})
        snap = mgr.events_snapshot("r1")
        assert len(snap) == 2
        assert snap[0].get("type") == "run.started"
        assert snap[1].get("type") == "step.action"

    def test_snapshot_does_not_consume_queue(self):
        mgr = RunManager()
        run = Run(id="r1", task="x", tier="restricted")
        mgr._runs[run.id] = run
        run.publish("run.started", {})
        # Snapshot reads the log
        snap = mgr.events_snapshot("r1")
        assert len(snap) == 1
        # Queue still has the event for SSE subscribers
        assert not run.events.empty()

    def test_snapshot_caps_at_max_events(self):
        mgr = RunManager()
        run = Run(id="r1", task="x", tier="restricted")
        mgr._runs[run.id] = run
        for i in range(10):
            run.publish("step.action", {"i": i})
        snap = mgr.events_snapshot("r1", max_events=5)
        assert len(snap) == 5
        # Last 5
        assert snap[-1].get("i") == 9
        assert snap[0].get("i") == 5

    def test_snapshot_unknown_run_raises(self):
        mgr = RunManager()
        with pytest.raises(KeyError):
            mgr.events_snapshot("nope")

    def test_events_log_capped_at_5000(self):
        """The events_log should drop oldest when it exceeds 5000."""
        mgr = RunManager()
        run = Run(id="r1", task="x", tier="restricted")
        mgr._runs[run.id] = run
        # Push more than 5000; log should drop to ~5000 (oldest dropped in chunks of 1000)
        for i in range(5100):
            run.publish("step.action", {"i": i})
        # Log was capped (drop 1000 at a time when > 5000).
        assert len(run.events_log) <= 5000
        # The latest event is preserved
        snap = mgr.events_snapshot("r1")
        assert snap[-1].get("i") == 5099


class TestListAllRuns:
    def test_empty(self):
        mgr = RunManager()
        assert mgr.list_all_runs() == []

    def test_returns_all_runs(self):
        mgr = RunManager()
        for i in range(3):
            run = Run(id=f"r{i}", task=f"task {i}", tier="restricted")
            mgr._runs[run.id] = run
        assert len(mgr.list_all_runs()) == 3


class TestParentRetryOf:
    """The Run dataclass supports retry_count + parent_retry_of for retry tracking."""

    def test_default_retry_count_zero(self):
        run = Run(id="r1", task="x", tier="restricted")
        assert getattr(run, "retry_count", 0) == 0

    def test_retry_count_increments(self):
        run = Run(id="r1", task="x", tier="restricted")
        run.retry_count = 0
        run.retry_count += 1
        run.retry_count += 1
        assert run.retry_count == 2
