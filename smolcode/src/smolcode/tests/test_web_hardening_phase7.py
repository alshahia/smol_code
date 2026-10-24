"""Phase 7 (decision 0042): web/session-model robustness.

Covers the six Phase-7 items from the full-app review remediation plan:

1. Atomic "busy check + registration" in RunManager (N concurrent submits
   -> exactly one running run, rest queued) and the matching queue-drain claim.
2. Run-scoped session teardown: a finishing run cannot clobber a newer
   the run SessionState.
3. Run-scoped auto-approve: a web request cannot flip an unscoped
   (orchestrator-child / CLI) session, and run A approval is not
   inherited by run B. The CLI own run_id=None toggle still works.
4. RunManager.stop() resolves a pending destructive/diff approval as
   DENIED (fail-closed) so the runner thread wakes immediately.
5. Finished-run retention: stale terminal runs are evicted and their
   api_key_value zeroed; active/paused/queued runs are never touched.
6. The SSE stream race: a subscriber that observes the terminal status
   before run.ended is published must still receive it.

No Docker daemon and no network are required: the runner is replaced with
a fake/stub where a thread would otherwise be started.
"""

from __future__ import annotations

import threading
import time

import pytest

from smolcode.config import Settings, _default_tiers
from smolcode.session import (
    SessionState,
    clear_session_for_run,
    get_auto_approve,
    get_session,
    set_auto_approve,
    set_session,
)
from smolcode.web import agent_runner as ar
from smolcode.web.runs import (
    EVT_RUN_ENDED,
    EVT_RUN_STARTED,
    STATUS_AWAITING_APPROVAL,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    Run,
    RunManager,
)


def _settings(tmp_path):
    return Settings(
        workspace=tmp_path,
        executor="local",
        provider="opencode-go",
        model="stub",
        litellm_proxy=None,
        log_level="WARNING",
        tiers=_default_tiers(),
    )


@pytest.fixture(autouse=True)
def _clean_session():
    """The session store is a process singleton; never leak it across tests."""
    set_session(None)
    yield
    set_session(None)


def _run(run_id="r1", status=STATUS_RUNNING, **kwargs):
    return Run(id=run_id, task="t", tier="restricted", status=status, **kwargs)


# ---- Item 1: atomic submit / drain claim ---------------------------------


class TestAtomicSubmit:
    def test_simultaneous_submits_start_exactly_one_run(self, tmp_path, monkeypatch):
        mgr = RunManager(settings=_settings(tmp_path))
        release = threading.Event()
        started = []

        def fake_run_in_thread(run, settings, manager=None, cost_cap_tracker=None):
            started.append(run.id)
            release.wait(5.0)

        monkeypatch.setattr(ar, "run_in_thread", fake_run_in_thread)

        n = 8
        barrier = threading.Barrier(n)
        results = []
        errors = []

        def submit(i):
            try:
                barrier.wait(5.0)
                results.append(
                    mgr.start_or_enqueue_run(task="task " + str(i), tier="restricted", settings=mgr._settings)
                )
            except Exception as e:  # noqa: BLE001 - asserted below
                errors.append(e)

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15.0)
        release.set()
        try:
            assert not errors, errors
            statuses = [status for _run_id, status in results]
            assert len(results) == n
            assert statuses.count(STATUS_RUNNING) == 1, statuses
            assert statuses.count(STATUS_QUEUED) == n - 1, statuses
            assert len([r for r in mgr.list() if r.status == STATUS_RUNNING]) == 1
            assert len(mgr.queue()) == n - 1
        finally:
            release.set()


class TestDrainClaim:
    def test_claim_refuses_when_a_submit_slipped_in(self, tmp_path):
        """A run registered after the finishing run claimed the slot first.

        This is the submit-vs-drain race: the finishing run status went
        terminal, a new submit started, and the completing run drain then
        tried to start the queued run too. The drain must leave it queued.
        """
        mgr = RunManager(settings=_settings(tmp_path))
        finisher = _run("finisher", status=STATUS_DONE)
        finisher.ended_at = time.time() - 1.0
        finisher._registered_at = time.time() - 10.0
        mgr._runs[finisher.id] = finisher
        slipped = _run("slipped", status=STATUS_RUNNING)
        slipped._registered_at = time.time()
        mgr._runs[slipped.id] = slipped
        queued = _run("q1", status=STATUS_QUEUED)
        mgr._runs[queued.id] = queued
        mgr.enqueue("q1", task="queued work", tier="restricted")

        assert mgr._claim_next_queued(exclude_run_id="finisher") is None
        assert [e.id for e in mgr.queue()] == ["q1"]
        assert queued.status == STATUS_QUEUED

    def test_claim_marks_next_entry_running(self, tmp_path):
        mgr = RunManager(settings=_settings(tmp_path))
        finisher = _run("finisher", status=STATUS_DONE)
        finisher.ended_at = time.time()
        finisher._registered_at = time.time() - 10.0
        mgr._runs[finisher.id] = finisher
        queued = _run("q1", status=STATUS_QUEUED)
        mgr._runs[queued.id] = queued
        mgr.enqueue("q1", task="queued work", tier="restricted")

        claimed = mgr._claim_next_queued(exclude_run_id="finisher")
        assert claimed is not None
        target, entry, settings, tracker = claimed
        assert target.id == "q1"
        assert entry.id == "q1"
        assert settings is mgr._settings
        assert tracker is None
        assert target.status == STATUS_RUNNING
        assert target.queue_position is None
        assert mgr.queue() == []

    def test_claim_without_settings_restores_the_entry(self):
        mgr = RunManager()
        queued = _run("q1", status=STATUS_QUEUED)
        mgr._runs[queued.id] = queued
        mgr.enqueue("q1", task="queued work", tier="restricted")

        with pytest.raises(RuntimeError, match="Settings"):
            mgr._claim_next_queued(exclude_run_id=None)
        # The entry is not lost: a later drain (once create_app wires the
        # settings) must still be able to start it.
        assert [e.id for e in mgr.queue()] == ["q1"]
        assert queued.status == STATUS_QUEUED


# ---- Item 2: run-scoped session teardown ---------------------------------


class TestSessionTeardown:
    def test_clear_only_matching_run(self):
        set_session(SessionState(tier="restricted", run_id="run-b"))
        assert clear_session_for_run("run-a") is False
        assert get_session().run_id == "run-b"
        assert clear_session_for_run("run-b") is True
        assert get_session() is None

    def test_clear_with_no_session_is_noop(self):
        assert clear_session_for_run("run-a") is False

    def test_finishing_run_does_not_clobber_newer_session(self, tmp_path):
        """Run A finally must not clear the run B session."""
        release = threading.Event()

        class _BlockingAgent:
            def __init__(self):
                self.step_callbacks = type("CB", (), {"register": lambda self, cls, cb: None})()

            def run(self, task, reset=True):
                release.wait(5.0)
                return "done"

            def cleanup(self):
                pass

        orig_build = ar._build_agent_for_run
        ar._build_agent_for_run = lambda run, settings: _BlockingAgent()
        try:
            settings = _settings(tmp_path)
            run_a = _run("run-a", status=STATUS_RUNNING)
            mgr = RunManager(settings=settings)
            thread = threading.Thread(target=ar.run_in_thread, args=(run_a, settings, mgr), daemon=True)
            thread.start()
            deadline = time.monotonic() + 5.0
            while get_session() is None or get_session().run_id != "run-a":
                assert time.monotonic() < deadline, "run A never installed its session"
                time.sleep(0.01)
            # Run B starts / installs its session while A is still in flight.
            set_session(SessionState(tier="restricted", auto_approve_destructive=True, run_id="run-b"))
            release.set()
            thread.join(5.0)
            assert not thread.is_alive(), "run A runner did not finish"
            assert run_a.status == STATUS_DONE
            current = get_session()
            assert current is not None and current.run_id == "run-b"
        finally:
            ar._build_agent_for_run = orig_build


# ---- Item 3: run-scoped auto-approve -------------------------------------


class TestAutoApproveScoping:
    def test_exact_run_flip(self):
        set_session(SessionState(tier="restricted", run_id="run-a"))
        assert set_auto_approve("run-a", True) == (True, None)
        assert get_auto_approve("run-a") is True

    def test_run_a_does_not_leak_to_run_b(self):
        set_session(SessionState(tier="restricted", run_id="run-a"))
        set_auto_approve("run-a", True)
        # Run B installs its own session (run_in_thread constructs it with
        # auto_approve_destructive=False).
        set_session(SessionState(tier="restricted", run_id="run-b"))
        assert get_auto_approve("run-b") is False
        assert get_auto_approve("run-a") is None
        assert set_auto_approve("run-a", True) == (False, "session is for a different run")
        assert get_session().auto_approve_destructive is False

    def test_unscoped_session_refused_for_run_scoped_caller(self):
        """The orchestrator child session (run_id=None) must not be flippable
        by a web request that targets a concrete run id."""
        set_session(SessionState(tier="restricted"))
        ok, err = set_auto_approve("run-a", True)
        assert ok is False
        assert err == "session is not scoped to a run"
        assert get_session().auto_approve_destructive is False
        assert get_auto_approve("run-a") is None

    def test_cli_unscoped_toggle_still_works(self):
        set_session(SessionState(tier="restricted"))
        assert set_auto_approve(None, True) == (True, None)
        assert get_auto_approve(None) is True
        assert set_auto_approve(None, False) == (True, None)
        assert get_auto_approve(None) is False

    def test_manager_endpoint_helper_is_scoped(self):
        mgr = RunManager()
        mgr._runs["run-a"] = _run("run-a", status=STATUS_RUNNING)
        set_session(SessionState(tier="restricted", run_id="run-a"))
        ok, err, current = mgr.set_auto_approve("run-a", True)
        assert (ok, err, current) == (True, None, True)
        # A child/CLI session installed under us: fail closed, mutate nothing.
        set_session(SessionState(tier="restricted"))
        ok, err, current = mgr.set_auto_approve("run-a", True)
        assert ok is False
        assert err == "session is not scoped to a run"
        assert current is None
        assert get_session().auto_approve_destructive is False


# ---- Item 4: stop() resolves pending decisions as DENIED -----------------


def _wait_for_pending(run, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with run.pending_lock:
            if run.pending:
                return run.pending[0]
        time.sleep(0.01)
    raise AssertionError("pending decision never appeared")


def _drain_frames(run):
    frames = []
    while not run.events.empty():
        frames.append(run.events.get_nowait())
    return "".join(frames)


class TestStopResolvesPendingDecisions:
    def test_stop_denies_pending_destructive_approval(self, tmp_path):
        mgr = RunManager()
        run = _run("run-a", status=STATUS_AWAITING_APPROVAL)
        mgr._runs[run.id] = run
        result = {}

        def waiter():
            cb = ar._build_confirm_callback(run, timeout_s=30.0)
            result["decision"] = cb("shell.run", {"cmd": "rm -rf build"}, "destructive op")

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        _wait_for_pending(run)

        started = time.monotonic()
        assert mgr.stop(run.id) is True
        t.join(2.0)
        elapsed = time.monotonic() - started

        assert not t.is_alive(), "stop() did not wake the approval waiter"
        assert elapsed < 2.0, "stop() took " + str(elapsed) + "s to unblock the waiter"
        decision = result["decision"]
        assert decision.approved is False
        assert decision.reason == "stopped"
        assert run.pending == []
        body = _drain_frames(run)
        assert "approval.decided" in body
        assert '"reason":"stopped"' in body

    def test_stop_denies_pending_diff_approval(self, tmp_path):
        mgr = RunManager()
        run = _run("run-a", status=STATUS_AWAITING_APPROVAL, workspace=str(tmp_path))
        mgr._runs[run.id] = run
        result = {}
        target = tmp_path / "x.txt"

        def waiter():
            cb = ar._build_diff_callback(run, timeout_s=30.0)
            result["decision"] = cb("write_file", {"path": str(target)}, "x.txt", "", "new contents", "summary")

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        _wait_for_pending(run)

        started = time.monotonic()
        assert mgr.stop(run.id) is True
        t.join(2.0)
        elapsed = time.monotonic() - started

        assert not t.is_alive(), "stop() did not wake the diff waiter"
        assert elapsed < 2.0
        decision = result["decision"]
        assert decision.approved is False
        assert decision.reason == "stopped"
        body = _drain_frames(run)
        assert "diff.resolved" in body
        assert '"reason":"stopped"' in body

    def test_stop_still_sets_the_flag_and_returns_false_for_unknown(self):
        mgr = RunManager()
        run = _run("run-a", status=STATUS_RUNNING)
        mgr._runs[run.id] = run
        assert mgr.stop("run-a") is True
        assert run.stop_flag.is_set()
        assert mgr.stop("nope") is False


# ---- Item 5: retention / eviction ----------------------------------------


class TestRunRetention:
    def _terminal(self, run_id, *, status=STATUS_DONE, ended_at, key="sk-secret"):
        return Run(
            id=run_id,
            task="t",
            tier="restricted",
            status=status,
            ended_at=ended_at,
            api_key_value=key,
        )

    def test_evicts_only_stale_terminal_runs_and_zeroes_keys(self):
        now = 1_000_000.0
        mgr = RunManager(retention_s=60)
        old = self._terminal("old", ended_at=now - 120)
        old_err = self._terminal("old-err", status=STATUS_ERROR, ended_at=now - 61)
        fresh = self._terminal("fresh", ended_at=now - 10)
        running = self._terminal("running", status=STATUS_RUNNING, ended_at=None)
        paused = self._terminal("paused", status=STATUS_PAUSED, ended_at=now - 500)
        queued = self._terminal("queued", status=STATUS_QUEUED, ended_at=None)
        for r in (old, old_err, fresh, running, paused, queued):
            mgr._runs[r.id] = r

        evicted = mgr.evict_finished_runs(now=now)

        assert set(evicted) == {"old", "old-err"}
        assert mgr.get("old") is None
        assert mgr.get("old-err") is None
        # Key material is zeroed on eviction...
        assert old.api_key_value is None
        assert old_err.api_key_value is None
        # ...and nothing else is touched.
        for r in (fresh, running, paused, queued):
            assert mgr.get(r.id) is r
        assert fresh.api_key_value == "sk-secret"
        assert running.api_key_value == "sk-secret"

    def test_disabled_retention_keeps_everything(self):
        now = 1_000_000.0
        for retention in (0, -1):
            mgr = RunManager(retention_s=retention)
            old = self._terminal("old", ended_at=now - 10_000_000)
            mgr._runs["old"] = old
            assert mgr.evict_finished_runs(now=now) == []
            assert mgr.get("old") is old
            assert old.api_key_value == "sk-secret"

    def test_env_configures_retention(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_RUN_RETENTION_S", "120")
        assert RunManager()._run_retention_s == 120.0

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_RUN_RETENTION_S", "soon")
        assert RunManager()._run_retention_s == 86400.0

    def test_submit_sweeps_finished_runs(self, tmp_path, monkeypatch):
        mgr = RunManager(settings=_settings(tmp_path), retention_s=60)
        monkeypatch.setattr(ar, "run_in_thread", lambda *a, **k: None)
        old = self._terminal("old", ended_at=time.time() - 120)
        mgr._runs["old"] = old

        run_id, status = mgr.start_or_enqueue_run(task="new run", tier="restricted", settings=mgr._settings)

        assert status == STATUS_RUNNING
        assert mgr.get("old") is None
        assert old.api_key_value is None
        assert mgr.get(run_id) is not None


# ---- Item 6: SSE stream terminus -----------------------------------------


class TestSubscribeStreamTerminus:
    def test_run_ended_not_dropped_when_status_flips_first(self):
        """The pre-fix subscriber broke on "terminal status + empty queue",
        which the runner reaches before it publishes run.ended."""
        mgr = RunManager()
        run = _run("r1", status=STATUS_RUNNING)
        mgr._runs["r1"] = run
        run.publish(EVT_RUN_STARTED, {"run_id": "r1"})
        # The runner finally: status/ended_at first...
        run.status = STATUS_DONE
        run.ended_at = time.time()

        def _finish():
            time.sleep(0.2)
            run.publish(EVT_RUN_ENDED, {"run_id": "r1", "status": STATUS_DONE})
            run.end_stream()

        t = threading.Thread(target=_finish, daemon=True)
        t.start()
        frames = list(mgr.subscribe("r1"))
        t.join(2.0)

        assert any("event: run.started" in f for f in frames)
        assert any("event: run.ended" in f for f in frames), frames
        assert frames[-1].startswith("event: end")
        assert len(frames) == 3

    def test_finished_stream_exits_without_heartbeat_stall(self):
        mgr = RunManager()
        run = _run("r1", status=STATUS_DONE, ended_at=time.time())
        mgr._runs["r1"] = run
        run.publish(EVT_RUN_ENDED, {"run_id": "r1", "status": STATUS_DONE})
        run.end_stream()

        started = time.monotonic()
        frames = list(mgr.subscribe("r1"))
        elapsed = time.monotonic() - started

        assert elapsed < 1.0, "subscribe() stalled for " + str(elapsed) + "s"
        # The buffered run.ended is flushed, then the stream terminates
        # without a heartbeat (which would otherwise block for 15 s).
        assert len(frames) == 2
        assert "event: run.ended" in frames[0]
        assert frames[1].startswith("event: end")

    def test_legacy_terminal_run_still_closes(self):
        """A run marked terminal WITHOUT a producer (unit tests, direct
        publish callers) keeps the old exit-on-terminal contract."""
        mgr = RunManager()
        run = _run("r1", status=STATUS_DONE)
        mgr._runs["r1"] = run
        run.publish(EVT_RUN_ENDED, {"run_id": "r1", "status": STATUS_DONE})
        frames = list(mgr.subscribe("r1"))
        assert len(frames) == 2
        assert frames[-1].startswith("event: end")
