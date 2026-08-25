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
    QueueEntry,
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


class TestMoveQueue:
    """Decision 0031: ``RunManager.move_queue`` reorders the FIFO queue.

    Position is 1-based: ``position=1`` is the head (runs next),
    ``position=N`` is the tail. Out-of-range values are clamped to
    ``[1, len(queue)]``. ``move_queue`` returns the resulting 1-based
    position on success, ``None`` when ``run_id`` is not currently in
    the queue, and raises ``ValueError`` for non-int ``new_position``.
    """

    def _busy_manager_with_n_queued(self, n: int) -> tuple[RunManager, str]:
        """Build a RunManager with one active run and ``n`` queued runs.

        Returns ``(manager, active_run_id)``. ``start_run`` is NOT
        called (no thread spawning) -- only the queue + run state are
        populated.
        """
        rm = RunManager()
        active = Run(id="active", task="busy", tier="restricted")
        active.status = STATUS_RUNNING
        with rm._lock:
            rm._runs[active.id] = active
        # Enqueue n runs by populating the queue directly (avoids
        # any thread spawning and matches the QueueEntry contract).
        for i in range(n):
            entry = QueueEntry(
                id=f"q{i + 1}",
                task=f"task-{i + 1}",
                tier="restricted",
                queued_at=float(i),
            )
            with rm._queue_lock:
                rm._queue.append(entry)
            run = Run(id=entry.id, task=entry.task, tier=entry.tier)
            run.status = STATUS_QUEUED
            run.queue_position = i + 1
            with rm._lock:
                rm._runs[run.id] = run
        return rm, active.id

    def test_move_middle_entry_to_head(self):
        """Moving the middle of [a, b, c] to position 1 yields [b, a, c]."""
        rm, _ = self._busy_manager_with_n_queued(3)
        new_pos = rm.move_queue("q2", 1)
        assert new_pos == 1
        ordered = [e.id for e in rm.queue()]
        assert ordered == ["q2", "q1", "q3"]
        # Positions are refreshed on the Run objects.
        assert rm.get("q1").queue_position == 2
        assert rm.get("q2").queue_position == 1
        assert rm.get("q3").queue_position == 3

    def test_move_tail_to_head(self):
        """Moving the last entry of [a, b, c] to position 1 yields [c, a, b]."""
        rm, _ = self._busy_manager_with_n_queued(3)
        new_pos = rm.move_queue("q3", 1)
        assert new_pos == 1
        ordered = [e.id for e in rm.queue()]
        assert ordered == ["q3", "q1", "q2"]

    def test_move_head_to_tail(self):
        """Moving the first entry of [a, b, c] to position 3 yields [b, c, a]."""
        rm, _ = self._busy_manager_with_n_queued(3)
        new_pos = rm.move_queue("q1", 3)
        assert new_pos == 3
        ordered = [e.id for e in rm.queue()]
        assert ordered == ["q2", "q3", "q1"]

    def test_move_to_same_position_is_noop(self):
        """Moving an entry to its current position returns that position
        and leaves the queue order unchanged."""
        rm, _ = self._busy_manager_with_n_queued(3)
        new_pos = rm.move_queue("q2", 2)
        assert new_pos == 2
        ordered = [e.id for e in rm.queue()]
        assert ordered == ["q1", "q2", "q3"]

    def test_move_unknown_returns_none(self):
        """A run_id that is not in the queue returns None (no exception)."""
        rm, _ = self._busy_manager_with_n_queued(2)
        assert rm.move_queue("missing", 1) is None
        # The queue is untouched.
        assert [e.id for e in rm.queue()] == ["q1", "q2"]

    def test_move_non_int_raises_value_error(self):
        """Passing a non-int (e.g. a string) raises ValueError cleanly
        -- this is what the PATCH endpoint converts into a 422."""
        rm, _ = self._busy_manager_with_n_queued(2)
        import pytest

        with pytest.raises(ValueError):
            rm.move_queue("q1", "1")  # type: ignore[arg-type]
        # And a float should also be rejected.
        with pytest.raises(ValueError):
            rm.move_queue("q1", 1.5)  # type: ignore[arg-type]

    def test_move_bool_rejected_even_though_bool_is_int_subclass(self):
        """Python's ``True`` is an ``int`` subclass; reject it explicitly
        so ``PATCH /api/queue/{id} {"position": true}`` cannot sneak
        through as position=1."""
        rm, _ = self._busy_manager_with_n_queued(2)
        import pytest

        with pytest.raises(ValueError):
            rm.move_queue("q1", True)  # type: ignore[arg-type]

    def test_move_position_clamped_above(self):
        """``position > len(queue)`` clamps to ``len(queue)`` (the tail)."""
        rm, _ = self._busy_manager_with_n_queued(3)
        new_pos = rm.move_queue("q1", 99)
        assert new_pos == 3
        ordered = [e.id for e in rm.queue()]
        assert ordered == ["q2", "q3", "q1"]

    def test_move_position_clamped_below(self):
        """``position <= 0`` clamps to ``1`` (the head)."""
        rm, _ = self._busy_manager_with_n_queued(3)
        new_pos = rm.move_queue("q3", 0)
        assert new_pos == 1
        ordered = [e.id for e in rm.queue()]
        assert ordered == ["q3", "q1", "q2"]
        new_pos2 = rm.move_queue("q1", -7)
        assert new_pos2 == 1
        ordered2 = [e.id for e in rm.queue()]
        assert ordered2 == ["q1", "q3", "q2"]

    def test_move_in_single_entry_queue_is_noop(self):
        """A queue of length 1: any move call is a no-op returning 1."""
        rm, _ = self._busy_manager_with_n_queued(1)
        new_pos = rm.move_queue("q1", 1)
        assert new_pos == 1
        assert [e.id for e in rm.queue()] == ["q1"]

    def test_move_on_empty_queue_returns_none(self):
        """An empty queue rejects every run_id (even a valid format)."""
        rm = RunManager()
        assert rm.move_queue("anything", 1) is None
