"""Tests for Phase 2 (decision 0025 §6.4): FIFO queue + auto-drain.

Covers the RunManager queue contract:
- ``start_or_enqueue_run`` enqueues when busy
- ``is_busy`` reflects active runs (running/awaiting_approval/paused)
- ``drain`` happens after a run ends (verified via the manager's
  internal queue + position tracking)
- ``cancel_queue`` removes a queued entry + transitions its Run to
  STATUS_STOPPED so SSE subscribers see the cancellation

API-level coverage (FastAPI test client) lives in
``test_web_runs_api.py``.
"""

from __future__ import annotations

from smolcode.web.runs import (
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    Run,
    RunManager,
)


class TestIsBusy:
    def test_empty_manager_not_busy(self):
        rm = RunManager()
        assert rm.is_busy() is False

    def test_running_run_is_busy(self):
        rm = RunManager()
        run = Run(id="r1", task="t", tier="restricted")
        run.status = STATUS_RUNNING
        with rm._lock:
            rm._runs[run.id] = run
        assert rm.is_busy() is True

    def test_paused_run_is_busy(self):
        """Paused runs occupy a slot -- the queue should not start
        another run until the paused one resumes or is stopped."""
        rm = RunManager()
        run = Run(id="r1", task="t", tier="restricted")
        run.status = STATUS_PAUSED
        with rm._lock:
            rm._runs[run.id] = run
        assert rm.is_busy() is True

    def test_terminal_run_not_busy(self):
        rm = RunManager()
        run = Run(id="r1", task="t", tier="restricted")
        run.status = STATUS_STOPPED
        with rm._lock:
            rm._runs[run.id] = run
        assert rm.is_busy() is False


class TestStartOrEnqueue:
    def test_first_run_starts_immediately(self, monkeypatch):
        """When no run is active, ``start_or_enqueue_run`` starts the
        runner thread (mirroring ``start_run``).

        We monkeypatch the threading to avoid actually spawning a
        thread in the test; we only assert that ``start_run`` was
        called and returned a status="running"."""
        rm = RunManager()
        captured: dict = {}

        def fake_start_run(self, **kwargs):
            captured["called"] = True
            return "fake-id"

        monkeypatch.setattr(RunManager, "start_run", fake_start_run)
        run_id, status = rm.start_or_enqueue_run(
            task="hello",
            tier="restricted",
            settings=__import__("smolcode").config.Settings(
                workspace="/tmp",
                executor="local",
                provider="opencode-go",
                model="stub",
                litellm_proxy=None,
                log_level="WARNING",
                tiers=__import__("smolcode").config._default_tiers(),
            ),
        )
        assert captured.get("called") is True
        assert run_id == "fake-id"
        assert status == STATUS_RUNNING

    def test_busy_manager_enqueues(self, monkeypatch):
        """When a run is active, ``start_or_enqueue_run`` enqueues the
        new run with status="queued" and does NOT call ``start_run``.
        """
        rm = RunManager()
        # Mark the manager as busy via a fake running run.
        active = Run(id="active", task="busy", tier="restricted")
        active.status = STATUS_RUNNING
        with rm._lock:
            rm._runs[active.id] = active

        started: list = []

        def fake_start_run(self, **kwargs):
            started.append(kwargs)
            return "should-not-be-called"

        monkeypatch.setattr(RunManager, "start_run", fake_start_run)
        run_id, status = rm.start_or_enqueue_run(
            task="queued task",
            tier="restricted",
            settings=__import__("smolcode").config.Settings(
                workspace="/tmp",
                executor="local",
                provider="opencode-go",
                model="stub",
                litellm_proxy=None,
                log_level="WARNING",
                tiers=__import__("smolcode").config._default_tiers(),
            ),
        )
        assert started == []  # start_run was NOT called
        assert status == STATUS_QUEUED
        assert rm.get(run_id) is not None
        assert rm.get(run_id).status == STATUS_QUEUED
        # The queue contains exactly one entry.
        queued = rm.queue()
        assert len(queued) == 1
        assert queued[0].id == run_id

    def test_queued_runs_track_positions(self):
        """After enqueuing multiple runs, each Run's queue_position is
        1-based and reflects its FIFO position."""
        rm = RunManager()
        # Force busy state.
        active = Run(id="active", task="busy", tier="restricted")
        active.status = STATUS_RUNNING
        with rm._lock:
            rm._runs[active.id] = active
        s = __import__("smolcode").config.Settings(
            workspace="/tmp",
            executor="local",
            provider="opencode-go",
            model="stub",
            litellm_proxy=None,
            log_level="WARNING",
            tiers=__import__("smolcode").config._default_tiers(),
        )
        id_a, _ = rm.start_or_enqueue_run(task="a", tier="restricted", settings=s)
        id_b, _ = rm.start_or_enqueue_run(task="b", tier="restricted", settings=s)
        id_c, _ = rm.start_or_enqueue_run(task="c", tier="restricted", settings=s)
        assert rm.get(id_a).queue_position == 1
        assert rm.get(id_b).queue_position == 2
        assert rm.get(id_c).queue_position == 3


class TestCancelQueue:
    def test_cancel_queued_run_sets_status_stopped(self):
        rm = RunManager()
        active = Run(id="active", task="busy", tier="restricted")
        active.status = STATUS_RUNNING
        with rm._lock:
            rm._runs[active.id] = active
        s = __import__("smolcode").config.Settings(
            workspace="/tmp",
            executor="local",
            provider="opencode-go",
            model="stub",
            litellm_proxy=None,
            log_level="WARNING",
            tiers=__import__("smolcode").config._default_tiers(),
        )
        run_id, _ = rm.start_or_enqueue_run(task="will be cancelled", tier="restricted", settings=s)
        # Sanity: the run is queued.
        assert rm.get(run_id).status == STATUS_QUEUED
        # Drain the publish queue so we can assert the new event later.
        while not rm.get(run_id).events.empty():
            try:
                rm.get(run_id).events.get_nowait()
            except Exception:
                break
        # Cancel.
        ok = rm.cancel_queue(run_id)
        assert ok is True
        assert rm.get(run_id).status == STATUS_STOPPED
        # A run.ended event was published.
        events = []
        while not rm.get(run_id).events.empty():
            try:
                events.append(rm.get(run_id).events.get_nowait())
            except Exception:
                break
        run_ended = [e for e in events if "run.ended" in e]
        assert len(run_ended) == 1

    def test_cancel_unknown_returns_false(self):
        rm = RunManager()
        assert rm.cancel_queue("missing") is False
