"""M9 - coverage tests for agent_runner.step_callback / confirm_callback.

These tests exercise the helpers in agent_runner.py without
constructing a full CodeAgent or running a real LLM. They cover:
  - _action_step_payload / _planning_step_payload / _final_answer_step_payload
  - _make_step_callback: emits the right event per step class; raises
    _StopRequested when stop_flag is set
  - _build_confirm_callback: deny on stop; deny on timeout; approve when
    decided; audit-log on every decision
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from smolcode.web.agent_runner import (
    _action_step_payload,
    _build_confirm_callback,
    _build_diff_callback,
    _final_answer_step_payload,
    _make_step_callback,
    _planning_step_payload,
    _rel_path,
    _safe_str,
    _step_kind,
    _StopRequested,
    run_in_thread,
)
from smolcode.web.runs import (
    EVT_DIFF_PROPOSED,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_STOPPED,
    Run,
)


# ---- TestSafeStr ------------------------------------------------------


class TestSafeStr:
    def test_none_returns_empty(self):
        assert _safe_str(None) == ""

    def test_normal_string(self):
        assert _safe_str("hello") == "hello"

    def test_long_string_truncated_with_ellipsis(self):
        s = "x" * 5000
        out = _safe_str(s, max_len=100)
        assert len(out) == 100
        assert out.endswith("\u2026")

    def test_unreprable_value(self):
        # An object whose __str__ raises falls back to repr().
        class Bad:
            def __str__(self):
                raise RuntimeError("nope")

            def __repr__(self):
                return "<Bad>"

        assert _safe_str(Bad()) == "<Bad>"


# ---- TestStepPayloads --------------------------------------------------


class TestStepPayloads:
    def test_action_step_minimal(self):
        class S:
            step_number = 1
            model_output_message = None
            model_output = None
            code_action = None
            tool_calls = None
            observations = None
            error = None
            is_final_answer = False
            timing = None
            token_usage = None

        p = _action_step_payload(S())
        assert p["kind"] == "action"
        assert p["step_number"] == 1

    def test_action_step_with_thought_and_code(self):
        class Msg:
            content = "I should run pytest."
            text = ""

        class S:
            step_number = 2
            model_output_message = Msg()
            model_output = None
            code_action = "print('hello')"
            tool_calls = []
            observations = "hello\n"
            error = None
            is_final_answer = False
            timing = None
            token_usage = None

        p = _action_step_payload(S())
        assert p["thought"] == "I should run pytest."
        assert p["code_action"] == "print('hello')"
        assert p["observations"] == "hello\n"

    def test_action_step_with_tool_calls(self):
        class TC:
            name = "shell.run"
            id = "call_1"
            arguments = {"cmd": "pytest"}

        class S:
            step_number = 3
            model_output_message = None
            model_output = "thought"
            code_action = None
            tool_calls = [TC()]
            observations = None
            error = None
            is_final_answer = True

            class Timing:
                duration = 0.123

            timing = Timing()

            class TU:
                input_tokens = 100
                output_tokens = 50

            token_usage = TU()

        p = _action_step_payload(S())
        assert p["tool_calls"][0]["name"] == "shell.run"
        assert p["tool_calls"][0]["args"] == {"cmd": "pytest"}
        assert p["is_final_answer"] is True
        assert p["timing_ms"] == pytest.approx(123.0)
        assert p["tokens"] == {"input": 100, "output": 50}

    def test_planning_step(self):
        class S:
            step_number = 1
            plan = "1. read x 2. write y"

        p = _planning_step_payload(S())
        assert p["kind"] == "plan"
        assert p["plan"] == "1. read x 2. write y"

    def test_final_answer_step(self):
        class S:
            output = "42"
            answer = None

        p = _final_answer_step_payload(S())
        assert p["kind"] == "final_answer"
        assert p["answer"] == "42"

    def test_step_kind(self):
        class ActionStep:
            pass

        class PlanningStep:
            pass

        assert _step_kind(ActionStep()) == "ActionStep"
        assert _step_kind(PlanningStep()) == "PlanningStep"


# ---- TestStepCallback --------------------------------------------------


class TestStepCallback:
    def test_emits_event_for_action_step(self):
        run = Run(id="r1", task="t", tier="restricted")
        cb = _make_step_callback(run)

        class Msg:
            content = "think"
            text = ""

        class Step:
            step_number = 1
            model_output_message = Msg()
            model_output = None
            code_action = None
            tool_calls = None
            observations = None
            error = None
            is_final_answer = False
            timing = None
            token_usage = None

        # ActionStep class is matched by name == "ActionStep"
        cb(type("ActionStep", (Step,), {})())
        # Drain the queue
        frames = []
        while not run.events.empty():
            frames.append(run.events.get_nowait())
        assert any("step.action" in f for f in frames)

    def test_emits_event_for_final_answer_step(self):
        run = Run(id="r1", task="t", tier="restricted")
        cb = _make_step_callback(run)

        class Step:
            output = "done"
            answer = None

        cb(type("FinalAnswerStep", (Step,), {})())
        frames = []
        while not run.events.empty():
            frames.append(run.events.get_nowait())
        assert any("step.final_answer" in f for f in frames)

    def test_stop_flag_raises_stop_requested(self):
        run = Run(id="r1", task="t", tier="restricted")
        run.stop_flag.set()
        cb = _make_step_callback(run)

        class Step:
            step_number = 1

        with pytest.raises(_StopRequested):
            cb(Step())

    def test_callback_swallows_unknown_step(self):
        """A step class the callback does not know about is silently ignored."""
        run = Run(id="r1", task="t", tier="restricted")
        cb = _make_step_callback(run)

        class MysteryStep:
            step_number = 1

        # Should NOT raise.
        cb(MysteryStep())
        assert run.events.empty()


# ---- TestConfirmCallback ----------------------------------------------


class TestConfirmCallback:
    def test_stop_during_approval_denies_immediately(self):
        run = Run(id="r1", task="t", tier="restricted")
        run.stop_flag.set()
        cb = _build_confirm_callback(run, timeout_s=5.0)
        d = cb("shell.run", {"cmd": "x"}, "summary")
        assert d.approved is False
        assert d.reason == "stopped"

    def test_decide_approve_returns_approved(self):
        run = Run(id="r1", task="t", tier="restricted")
        cb = _build_confirm_callback(run, timeout_s=5.0)

        def _post_decision():
            time.sleep(0.05)
            # Find the decision and resolve it.
            with run.pending_lock:
                if run.pending:
                    run.pending[0].resolve(True, None, "user")

        t = threading.Thread(target=_post_decision)
        t.start()
        d = cb("shell.run", {"cmd": "pytest"}, "run pytest")
        t.join(timeout=2.0)
        assert d.approved is True
        assert d.reason == "user"
        # Run.status should have flipped back to running after approval.
        assert run.status != "awaiting_approval"

    def test_decide_timeout_denies(self):
        run = Run(id="r1", task="t", tier="restricted")
        cb = _build_confirm_callback(run, timeout_s=0.1)
        d = cb("shell.run", {"cmd": "x"}, "summary")
        assert d.approved is False
        assert d.reason == "timeout"

    def test_approval_requested_event_published(self):
        """Verify the SSE event was emitted to the run's queue."""
        run = Run(id="r1", task="t", tier="restricted")
        cb = _build_confirm_callback(run, timeout_s=0.05)
        d = cb("shell.run", {"cmd": "x"}, "summary")
        assert d.approved is False
        # Drain queue and check for approval.requested + approval.decided.
        frames = []
        while not run.events.empty():
            frames.append(run.events.get_nowait())
        body = "".join(frames)
        assert "approval.requested" in body
        assert "approval.decided" in body
        assert '"approved":false' in body
        assert '"reason":"timeout"' in body

    def test_audit_sink_records_decision(self):
        """Verify audit.record is called with destructive_decision event."""
        recorded = []

        class FakeAudit:
            def record(self, event, **fields):
                recorded.append((event, fields))

        run = Run(id="r1", task="t", tier="restricted", audit_sink=FakeAudit())
        cb = _build_confirm_callback(run, timeout_s=0.05)
        cb("shell.run", {"cmd": "x"}, "summary")
        assert any(ev == "destructive_decision" for ev, _ in recorded)


# ---- TestRelPath (M10) --------------------------------------------------


class TestRelPath:
    def test_returns_relative_path_when_inside_workspace(self, tmp_path):
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        target = str(tmp_path / "sub" / "file.txt")
        assert _rel_path(run, target) == "sub/file.txt"

    def test_returns_empty_when_outside_workspace(self, tmp_path):
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        other = str(tmp_path.parent / "elsewhere.txt")
        assert _rel_path(run, other) == ""

    def test_returns_empty_for_empty_path(self, tmp_path):
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        assert _rel_path(run, "") == ""
        assert _rel_path(run, None) == ""  # type: ignore

    def test_returns_empty_for_workspace_root(self, tmp_path):
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        assert _rel_path(run, str(tmp_path)) == "."


# ---- TestDiffCallback (M10) --------------------------------------------


def _drain_run_events(run):
    frames = []
    while not run.events.empty():
        frames.append(run.events.get_nowait())
    return frames


class TestDiffCallback:
    def test_stop_flag_deny(self, tmp_path):
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        run.stop_flag.set()
        cb = _build_diff_callback(run, timeout_s=5.0)
        d = cb("write_file", {"path": "x.txt"}, "x.txt", "", "y", "summary")
        assert d.approved is False
        assert d.reason == "stopped"

    def test_publishes_diff_proposed_with_hunks(self, tmp_path):
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        cb = _build_diff_callback(run, timeout_s=0.05)

        def _resolve():
            time.sleep(0.02)
            with run.pending_lock:
                if run.pending:
                    run.pending[0].resolve(False, None, "user")

        th = threading.Thread(target=_resolve)
        th.start()
        d = cb(
            "write_file",
            {"path": "x.txt", "content": "y"},
            str(tmp_path / "x.txt"),
            "alpha\nbeta\n",
            "alpha\nBETA\n",
            "write_file(x.txt, 1 bytes)",
        )
        th.join(timeout=2.0)
        assert d.approved is False
        assert d.reason == "user"
        frames = _drain_run_events(run)
        body = "".join(frames)
        assert "event: " + EVT_DIFF_PROPOSED in body
        # Before/after propagated.
        assert "alpha" in body
        assert "BETA" in body
        # Raw diff is present.
        assert "@@" in body
        # diff.resolved is published by RunManager.decide in the API
        # layer, NOT by the callback itself. We cover that path in
        # test_workspace_tree_returns_entries / the manager test below.

    def test_timeout_returns_deny(self, tmp_path):
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        cb = _build_diff_callback(run, timeout_s=0.05)
        d = cb("write_file", {}, "x.txt", "a", "b", "summary")
        assert d.approved is False
        assert d.reason == "timeout"
        frames = _drain_run_events(run)
        body = "".join(frames)
        assert '"reason":"timeout"' in body

    def test_records_touched_path(self, tmp_path):
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        cb = _build_diff_callback(run, timeout_s=0.05)
        cb(
            "write_file",
            {},
            str(tmp_path / "sub" / "file.txt"),
            "old",
            "new",
            "summary",
        )
        assert "sub/file.txt" in run.touched_list()

    def test_audit_sink_records_diff_decision(self, tmp_path):
        recorded = []

        class FakeAudit:
            def record(self, event, **fields):
                recorded.append((event, fields))

        run = Run(
            id="r1",
            task="t",
            tier="restricted",
            workspace=str(tmp_path),
            audit_sink=FakeAudit(),
        )
        cb = _build_diff_callback(run, timeout_s=0.05)
        cb("write_file", {}, "x.txt", "a", "b", "summary")
        assert any(ev == "diff_decision" for ev, _ in recorded)

    def test_decide_with_edited_after_returns_edited_after(self, tmp_path):
        from smolcode.web.runs import RunManager

        mgr = RunManager()
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        mgr._runs[run.id] = run
        cb = _build_diff_callback(run, timeout_s=5.0)

        def _resolve():
            time.sleep(0.02)
            with run.pending_lock:
                if run.pending:
                    run.pending[0].resolve(True, {"__edited_after__": "user-edited"}, "user")

        th = threading.Thread(target=_resolve)
        th.start()
        d = cb("write_file", {}, "x.txt", "a", "b", "summary")
        th.join(timeout=2.0)
        assert d.approved is True
        assert d.edited_after == "user-edited"

    def test_handles_diff_compute_failure(self, tmp_path, monkeypatch):
        """If diff computation raises, the callback still publishes
        and resolves; the agent sees a deny (decision is left to the
        user anyway, but the audit path must not crash)."""
        from smolcode.web import agent_runner as ar

        def _bad(*a, **kw):
            raise RuntimeError("diff compute exploded")

        monkeypatch.setattr(ar, "unified_hunks", _bad)
        run = Run(id="r1", task="t", tier="restricted", workspace=str(tmp_path))
        cb = _build_diff_callback(run, timeout_s=0.05)
        # Should not raise.
        d = cb("write_file", {}, "x.txt", "a", "b", "summary")
        assert d.approved is False
        assert d.reason == "timeout"


# ---- TestRunInThreadDockerCleanup (decision 0022) ------------------------
#
# When a run ends -- by success, error, _StopRequested, KeyboardInterrupt,
# or a hung model -- the Docker container that backs the executor MUST be
# removed. Otherwise the next run fails with
# "Bind for 127.0.0.1:8888 failed: port is already allocated".
#
# These tests stub `_build_agent_for_run` to return a mock agent whose
# `.cleanup()` is observable and whose `.run()` either returns cleanly
# or raises. We assert cleanup() is called exactly once in every exit
# path.


def _make_mock_agent(raise_on_run=None, return_value="ok"):
    """Build a MagicMock standing in for a smolagents CodeAgent.

    The mock has:
      - .step_callbacks.register (no-op)
      - .run(task): either returns return_value, or raises raise_on_run
      - .cleanup(): records the call so tests can assert on it
    """
    agent = MagicMock()
    agent.step_callbacks.register = MagicMock()
    if raise_on_run is not None:
        agent.run = MagicMock(side_effect=raise_on_run)
    else:
        agent.run = MagicMock(return_value=return_value)
    agent.cleanup = MagicMock()
    return agent


def _patch_agent_builder(agent):
    """Patch _build_agent_for_run so run_in_thread uses our mock agent."""
    return patch("smolcode.web.agent_runner._build_agent_for_run", return_value=agent)


def _settings_stub(tmp_path):
    """Build a minimal Settings object (local executor, stub provider)."""
    from smolcode.config import Settings, _default_tiers

    return Settings(
        workspace=tmp_path,
        executor="local",
        provider="opencode-go",
        model="stub",
        litellm_proxy=None,
        log_level="WARNING",
        tiers=_default_tiers(),
    )


class TestRunInThreadDockerCleanup:
    """Decision 0022: agent.cleanup() MUST run on every exit path."""

    def test_cleanup_called_on_normal_completion(self, tmp_path):
        """Happy path: agent finishes -> cleanup is called."""
        agent = _make_mock_agent(return_value="done")
        run = Run(id="r-clean-1", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        assert agent.cleanup.call_count == 1, "cleanup() was not called on normal completion"
        assert run.status == STATUS_DONE

    def test_cleanup_called_when_agent_raises(self, tmp_path):
        """The failure mode that bit the user: agent raises -> cleanup still runs."""
        agent = _make_mock_agent(raise_on_run=RuntimeError("model crashed"))
        run = Run(id="r-clean-2", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        assert agent.cleanup.call_count == 1, "cleanup() was not called when agent raised"
        assert run.status == STATUS_ERROR
        assert "RuntimeError" in (run.error or "")

    def test_cleanup_called_when_user_stops(self, tmp_path):
        """User-initiated stop: the step callback raises _StopRequested
        mid-run. The container must still be torn down.
        """

        def _stop_during_run(_task):
            run.stop_flag.set()
            raise _StopRequested()

        agent = _make_mock_agent(raise_on_run=_stop_during_run)
        run = Run(id="r-clean-3", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        assert agent.cleanup.call_count == 1, "cleanup() was not called on _StopRequested"
        assert run.status == STATUS_STOPPED

    def test_cleanup_called_on_keyboard_interrupt(self, tmp_path):
        """Ctrl+C in the CLI surface translates to KeyboardInterrupt. The
        container must still be torn down.
        """
        agent = _make_mock_agent(raise_on_run=KeyboardInterrupt())
        run = Run(id="r-clean-4", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        assert agent.cleanup.call_count == 1, "cleanup() was not called on KeyboardInterrupt"
        assert run.status == STATUS_STOPPED

    def test_cleanup_called_when_model_hangs_then_crashes(self, tmp_path):
        """The exact failure mode the user hit: the model wrote
        `!pip install smolcode`, hung, then crashed. The container must
        still be removed so the next run can bind 127.0.0.1:8888.
        """

        def _hang_then_crash(_task):
            time.sleep(0.01)  # pretend the kernel is busy
            raise RuntimeError("Bind for 127.0.0.1:8888 failed: port is already allocated")

        agent = _make_mock_agent(raise_on_run=_hang_then_crash)
        run = Run(id="r-clean-5", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        assert agent.cleanup.call_count == 1
        assert run.status == STATUS_ERROR
        assert "port is already allocated" in (run.error or "")

    def test_cleanup_failure_does_not_mask_run_status(self, tmp_path):
        """If agent.cleanup() itself raises (e.g. Docker daemon hung),
        the run must still publish its terminal status. We log + swallow.
        """
        agent = _make_mock_agent(return_value="done")
        agent.cleanup = MagicMock(side_effect=RuntimeError("docker daemon hung"))
        run = Run(id="r-clean-6", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        # Status is still DONE -- cleanup failure is logged, not raised.
        assert run.status == STATUS_DONE
        # Cleanup was attempted exactly once.
        assert agent.cleanup.call_count == 1


# ---- TestRunInThreadWallClockTimeout (decision 0023 layer B) -------------
#
# If the model hangs inside the Jupyter kernel -- e.g. ``!pip install
# smolcode`` never returns -- ``agent.run()`` blocks forever and the
# runner thread never reaches its ``finally`` block. Decision 0023
# bounds ``agent.run()`` with a ``concurrent.futures.ThreadPoolExecutor``
# timeout. On timeout we forcibly tear down the Docker executor so
# 127.0.0.1:8888 is freed, then publish the run as ``stopped`` with a
# clear wall-clock-timeout error.
#
# These tests monkeypatch ``_MAX_RUN_WALL_S`` to a small value so the
# timeout fires within the test budget. We assert:
#  1. run_in_thread returns within a bounded wall-clock window.
#  2. agent.cleanup() was called (forcibly killing the container).
#  3. run.status == STATUS_STOPPED with a wall-clock-timeout message.


@pytest.fixture
def short_timeout(monkeypatch):
    """Force _MAX_RUN_WALL_S to 0.3s for the duration of one test."""
    from smolcode.web import agent_runner

    monkeypatch.setattr(agent_runner, "_MAX_RUN_WALL_S", 0.3)
    monkeypatch.setattr(agent_runner, "_MAX_RUN_DRAIN_S", 0.3)
    yield


def _hang_forever(_task):
    """Block forever -- simulates a Jupyter kernel that never replies."""
    time.sleep(60)


class TestRunInThreadWallClockTimeout:
    """Decision 0023 layer B: ``run_in_thread`` MUST return within a
    bounded wall-clock window even when the model hangs."""

    def test_run_returns_when_agent_hangs_forever(self, tmp_path, short_timeout, monkeypatch):
        """The exact scenario from the user report: the model wrote
        ``!pip install smolcode`` and the kernel never returned. The
        runner thread must return within ~MAX_RUN_WALL_S + drain,
        not hang for 60+ seconds."""
        from smolcode.web import agent_runner as ar_mod

        agent = _make_mock_agent(raise_on_run=_hang_forever)
        run = Run(id="r-timeout-1", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            t0 = time.monotonic()
            ar_mod.run_in_thread(run, _settings_stub(tmp_path))
            elapsed = time.monotonic() - t0
        # Must return within 3 * MAX_RUN_WALL_S + drain budget.
        assert elapsed < 3.0, f"run_in_thread took {elapsed:.2f}s, expected < 3s"
        # Cleanup was called -- the container is killed.
        assert agent.cleanup.call_count == 1, "cleanup was not called on wall-clock timeout"
        # Run is published as STOPPED with a clear wall-clock-timeout message.
        assert run.status == STATUS_STOPPED
        assert run.error is not None
        assert "wall-clock timeout" in run.error
        # The inner ``agent.run`` thread is best-effort cancelled; we do
        # not assert it has exited yet because shutdown(wait=False) does
        # not block on it.

    def test_run_status_is_done_when_agent_completes_within_timeout(self, tmp_path, short_timeout):
        """Happy path under the new wrapper: agent returns quickly,
        run is published as DONE, cleanup still runs."""
        agent = _make_mock_agent(return_value="ok")
        run = Run(id="r-timeout-2", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        assert run.status == STATUS_DONE
        assert agent.cleanup.call_count == 1

    def test_pool_is_shut_down_after_timeout(self, tmp_path, short_timeout):
        """After a timeout, the ThreadPoolExecutor must have been
        shut down (wait=False) so it does not hold the agent thread
        alive indefinitely. We can't introspect the pool from here,
        but we can assert run_in_thread returns in bounded time --
        which is only possible if the pool releases the worker."""
        agent = _make_mock_agent(raise_on_run=_hang_forever)
        run = Run(id="r-timeout-3", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            t0 = time.monotonic()
            run_in_thread(run, _settings_stub(tmp_path))
            elapsed = time.monotonic() - t0
        # If pool.shutdown(wait=False) were missing, the with-block
        # (or any equivalent shutdown path) would hang on the
        # 60-second sleep inside _hang_forever. Bounded runtime proves
        # the pool released the worker.
        assert elapsed < 3.0, f"run_in_thread took {elapsed:.2f}s, expected < 3s"
        assert agent.cleanup.call_count == 1


# ---- TestRunInThreadErrorTraceback (decision 0024) -----------------------
#
# Before 0024 the broad ``except Exception`` block in ``run_in_thread``
# stored ONLY ``type(e).__name__ + ": " + str(e)`` on ``run.error``. The
# user (and the tests) saw ``"OSError: [Errno 22] Invalid argument"``
# with no stack, no hint of which line raised it, and no path to a
# diagnosis. 0024 adds ``traceback.format_exc()`` to ``run.error`` (and
# to the EVT_ERROR payload), capped at 8 KB so a runaway traceback does
# not blow up the SSE queue.
#
# These tests pin the new behaviour:
#   1. The traceback is appended (no longer just ``repr(e)``).
#   2. Long tracebacks are capped at 8 KB with a trailing ellipsis.
#   3. ``step_callbacks.register`` failing on all three step kinds does
#      not abort the run -- it logs and continues (a transient smolagents
#      internal-state problem on Windows surfaced as ``OSError [Errno 22]
#      Invalid argument`` when registering ActionStep; the only previous
#      register call NOT wrapped in try/except).
#   4. ``pool.submit`` failure (worker thread can't start) surfaces as
#      a descriptive ``RuntimeError`` on ``run.error``, not a silent kill.


class TestRunInThreadErrorTraceback:
    """Decision 0024: capture the full traceback on any error path."""

    def test_error_includes_traceback(self, tmp_path):
        """When ``agent.run`` raises, ``run.error`` carries the exception
        type + message AND a Python traceback. Before 0024 it carried
        only the type + message -- the exact user-visible bug."""

        def _explode(_task):
            raise ValueError("boom")

        agent = _make_mock_agent(raise_on_run=_explode)
        run = Run(id="r-tb-1", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        assert run.status == STATUS_ERROR
        err = run.error or ""
        # The type + message are still present (back-compat for callers
        # who pattern-match on the leading "ValueError: ..." token).
        assert "ValueError: boom" in err
        # The new traceback follows on the next line.
        assert "Traceback (most recent call last)" in err
        # And it includes the offending frame.
        assert "_explode" in err

    def test_traceback_capped_at_8kb(self, tmp_path, monkeypatch):
        """A pathological error whose traceback exceeds 8 KB must NOT
        blow up the SSE queue: ``run.error`` is capped at 8 KB with a
        trailing ellipsis. We deterministically produce a > 8 KB
        traceback by monkeypatching ``traceback.format_exc`` to return
        a known-long string -- relying on real recursion-depth produces
        a non-deterministic length because Python collapses repeated
        frames with ``[Previous line repeated N more times]``."""
        from smolcode.web import agent_runner as ar_mod

        big = "x" * 10000 + "\\nEND"
        monkeypatch.setattr(ar_mod.traceback, "format_exc", lambda: big)

        def _explode(_task):
            raise ValueError("kaboom")

        agent = _make_mock_agent(raise_on_run=_explode)
        run = Run(id="r-tb-2", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        assert run.status == STATUS_ERROR
        err = run.error or ""
        # The leading "ValueError: kaboom" is preserved.
        assert "ValueError: kaboom" in err
        # The traceback was capped -- the whole error fits in 8 KB +
        # the leading "Type: msg" prefix.
        assert len(err) <= 9000, f"run.error is {len(err)} bytes -- should be <= 9 KB"
        # Trailing ellipsis marks the truncation.
        assert err.endswith("\u2026")

    def test_register_failure_does_not_abort_run(self, tmp_path):
        """If ``step_callbacks.register`` raises for ALL three step kinds
        -- the failure mode that previously surfaced as
        ``OSError: [Errno 22] Invalid argument`` on Windows when
        ActionStep registration hit a transient smolagents-internal
        problem -- the run must NOT abort. Instead the failure is
        logged and the agent still runs.

        We model the failure with a side_effect that raises on the
        first call (ActionStep) and accepts the others, which is the
        most common real-world case. The conservative ``except
        Exception`` in the loop also covers the rarer "all three fail"
        case."""
        from smolagents.agents import ActionStep

        agent = _make_mock_agent(return_value="ok")
        original_register = agent.step_callbacks.register

        def _register_with_first_failure(step_cls, cb):
            if step_cls is ActionStep:
                raise OSError("[Errno 22] Invalid argument")
            return original_register(step_cls, cb)

        agent.step_callbacks.register = MagicMock(side_effect=_register_with_first_failure)
        run = Run(id="r-reg-1", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        # The run completed normally despite the ActionStep failure.
        assert run.status == STATUS_DONE, f"expected DONE, got {run.status}"
        assert agent.cleanup.call_count == 1

    def test_register_failure_for_all_three_steps_does_not_abort_run(self, tmp_path):
        """The harder case: register() raises for ALL three step kinds.
        The run must still complete -- a fully-broken callback layer
        is logged once per step kind but the agent still runs."""
        agent = _make_mock_agent(return_value="ok")
        agent.step_callbacks.register = MagicMock(side_effect=OSError("[Errno 22] Invalid argument"))
        run = Run(id="r-reg-2", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            run_in_thread(run, _settings_stub(tmp_path))
        assert run.status == STATUS_DONE
        assert agent.cleanup.call_count == 1
        # All three register calls were attempted.
        assert agent.step_callbacks.register.call_count == 3

    def test_pool_submit_failure_surfaces_as_error(self, tmp_path):
        """If ``concurrent.futures.ThreadPoolExecutor.submit`` raises
        (interpreter shutdown, OOM, broken pool), ``run_in_thread``
        surfaces it via the broad ``except Exception`` block as a
        descriptive ``RuntimeError`` -- NOT a silent kill."""
        import concurrent.futures

        from smolcode.web import agent_runner as ar_mod

        agent = _make_mock_agent(return_value="ok")

        class _ExplodingPool:
            def submit(self, *a, **kw):
                raise RuntimeError("interpreter shutdown")

            def shutdown(self, wait=True):
                return None

        def _exploding_pool(*a, **kw):
            return _ExplodingPool()

        run = Run(id="r-sub-1", task="t", tier="restricted", workspace=str(tmp_path))
        with _patch_agent_builder(agent):
            with patch.object(concurrent.futures, "ThreadPoolExecutor", _exploding_pool):
                ar_mod.run_in_thread(run, _settings_stub(tmp_path))
        # The submit failure was caught and turned into a normal error.
        assert run.status == STATUS_ERROR
        err = run.error or ""
        assert "submission failed" in err
        assert "interpreter shutdown" in err
        # Cleanup still ran in finally.
        assert agent.cleanup.call_count == 1
