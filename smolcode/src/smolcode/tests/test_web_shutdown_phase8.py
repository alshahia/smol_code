"""Phase 8 (decision 0043): graceful shutdown helper.

The lifespan call site lives in web/server.py (owned by the Lead); this file
tests the mechanism with fakes only. No Docker, no real runs, no MCP servers.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from smolcode.web import shutdown as shutdown_module
from smolcode.web.shutdown import graceful_shutdown


# ---- fakes -----------------------------------------------------------------


class _FakeThread:
    def __init__(self, alive=False):
        self.alive = alive
        self.joined = []
        self.name = "fake-run-thread"

    def join(self, timeout=None):
        self.joined.append(timeout)

    def is_alive(self):
        return self.alive


class _FakeRun:
    def __init__(self, run_id, status="running", thread=None):
        self.id = run_id
        self.status = status
        self.thread = thread


class _FakeManager:
    def __init__(self, runs=(), queued=(), stop_result=True, list_raises=False):
        self.runs = list(runs)
        self.queued = list(queued)
        self.stop_result = stop_result
        self.list_raises = list_raises
        self.calls = []

    def queue(self):
        self.calls.append("queue")
        return list(self.queued)

    def cancel_queue(self, run_id):
        self.calls.append("cancel:" + run_id)
        return True

    def list(self):
        self.calls.append("list")
        if self.list_raises:
            raise RuntimeError("manager gone")
        return list(self.runs)

    def stop(self, run_id):
        self.calls.append("stop:" + run_id)
        return self.stop_result


class _FakeSink:
    def __init__(self, events, fail=False):
        self.events = events
        self.fail = fail

    def close(self):
        self.events.append("audit-close")
        if self.fail:
            raise OSError("disk full")


@pytest.fixture(autouse=True)
def _no_real_mcp(monkeypatch):
    """Never touch real MCP subprocesses from tests."""
    import smolcode.tools as tools_module

    calls = []
    monkeypatch.setattr(tools_module, "close_mcp_servers", lambda: calls.append("mcp-close"))
    return calls


# ---- behaviour -------------------------------------------------------------


def test_none_state_is_a_noop():
    asyncio.run(graceful_shutdown(None))


def test_empty_state_is_a_noop():
    asyncio.run(graceful_shutdown(SimpleNamespace()))


def test_stops_active_run_and_joins_its_thread():
    events = []
    thread = _FakeThread(alive=False)
    manager = _FakeManager(runs=[_FakeRun("run-1", thread=thread)])
    state = SimpleNamespace(run_manager=manager, audit_sink=_FakeSink(events))

    asyncio.run(graceful_shutdown(state))

    assert "stop:run-1" in manager.calls
    assert thread.joined, "the runner thread must be joined"
    assert thread.joined[0] <= 10.0
    assert events == ["audit-close"]


def test_queued_runs_are_cancelled_before_stopping():
    manager = _FakeManager(
        runs=[_FakeRun("active", thread=_FakeThread())],
        queued=[SimpleNamespace(id="q1"), SimpleNamespace(id="q2")],
    )
    asyncio.run(graceful_shutdown(SimpleNamespace(run_manager=manager)))

    assert manager.calls.count("cancel:q1") == 1
    assert manager.calls.count("cancel:q2") == 1
    assert manager.calls.index("cancel:q1") < manager.calls.index("stop:active")
    assert manager.calls.index("cancel:q2") < manager.calls.index("stop:active")


def test_terminal_runs_are_not_stopped():
    manager = _FakeManager(
        runs=[_FakeRun("done", status="done", thread=_FakeThread()), _FakeRun("err", status="error")]
    )
    asyncio.run(graceful_shutdown(SimpleNamespace(run_manager=manager)))
    assert not any(call.startswith("stop:") for call in manager.calls)


def test_run_without_thread_is_still_stopped():
    manager = _FakeManager(runs=[_FakeRun("no-thread", thread=None)])
    asyncio.run(graceful_shutdown(SimpleNamespace(run_manager=manager)))
    assert manager.calls == ["queue", "list", "stop:no-thread"]


def test_stop_returning_false_still_joins_the_thread():
    # stop() False means "the run is no longer active"; its thread may still
    # be writing its final audit records, so it is joined (within the shared
    # deadline) rather than abandoned.
    thread = _FakeThread()
    manager = _FakeManager(runs=[_FakeRun("already-gone", thread=thread)], stop_result=False)
    asyncio.run(graceful_shutdown(SimpleNamespace(run_manager=manager)))
    assert thread.joined, "a finishing thread must still be joined"


def test_timeout_is_bounded_and_logged(caplog):
    # A real thread that never finishes: join() returns when the budget runs
    # out, and the helper reports the survivor instead of blocking shutdown.
    release = threading.Event()
    thread = threading.Thread(target=release.wait, name="stuck-run", daemon=True)
    thread.start()
    try:
        started = time.monotonic()
        with caplog.at_level("WARNING", logger="smolcode.web.shutdown"):
            asyncio.run(
                graceful_shutdown(
                    SimpleNamespace(run_manager=_FakeManager(runs=[_FakeRun("stuck", thread=thread)])), timeout=0.25
                )
            )
        elapsed = time.monotonic() - started
        assert elapsed < 5.0
        assert "still alive" in caplog.text
    finally:
        release.set()
        thread.join(timeout=5)


def test_zero_timeout_does_not_wait():
    release = threading.Event()
    thread = threading.Thread(target=release.wait, name="zero-budget", daemon=True)
    thread.start()
    try:
        started = time.monotonic()
        asyncio.run(
            graceful_shutdown(
                SimpleNamespace(run_manager=_FakeManager(runs=[_FakeRun("r", thread=thread)])), timeout=0
            )
        )
        assert time.monotonic() - started < 2.0
    finally:
        release.set()
        thread.join(timeout=5)


def test_manager_errors_are_tolerated():
    class _Exploding:
        def queue(self):
            raise RuntimeError("queue gone")

        def list(self):
            raise RuntimeError("list gone")

        def cancel_queue(self, run_id):
            raise RuntimeError("cancel gone")

        def stop(self, run_id):
            raise RuntimeError("stop gone")

    asyncio.run(graceful_shutdown(SimpleNamespace(run_manager=_Exploding())))


def test_audit_close_failure_is_tolerated(caplog):
    events = []
    state = SimpleNamespace(audit_sink=_FakeSink(events, fail=True))
    with caplog.at_level("WARNING", logger="smolcode.web.shutdown"):
        asyncio.run(graceful_shutdown(state))
    assert events == ["audit-close"]
    assert "audit sink close failed" in caplog.text


def test_mcp_servers_are_closed(_no_real_mcp):
    asyncio.run(graceful_shutdown(SimpleNamespace()))
    assert _no_real_mcp == ["mcp-close"]


def test_accepts_the_app_object_as_well_as_app_state():
    manager = _FakeManager(runs=[_FakeRun("app-wrapped")])
    app = SimpleNamespace(state=SimpleNamespace(run_manager=manager))
    asyncio.run(graceful_shutdown(app))
    assert "stop:app-wrapped" in manager.calls


def test_shutdown_module_does_not_import_tools_at_module_import_time():
    # The tool layer imports MCP transport deps; shutdown must stay importable
    # (and cheap) even when the web extras / MCP stack is unhealthy.
    assert not hasattr(shutdown_module, "close_mcp_servers")
