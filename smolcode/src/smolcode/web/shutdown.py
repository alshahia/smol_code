"""Graceful shutdown helper for the FastAPI lifespan (Phase 8, decision 0043).

The review found the lifespan `finally` block was literally `pass`: on a
normal `SIGTERM` the server exited while a run thread was still working, MCP
subprocesses were left to die with the process, and the audit sink's buffered
tail was never flushed (ops-medium / A7).

`graceful_shutdown(app_state, *, timeout=10.0)` is the one call the lifespan
needs. It is deliberately self-contained and defensive:

* accepts `app.state` OR the app itself (unwraps `.state`);
* tolerates a partial/None state and any manager/driver that is missing or
  raises - shutdown must never turn a clean exit into a traceback;
* cancels queued runs FIRST, so the active run's drain cannot start the next
  queued run in the window between "stop" and "join";
* stops the active run, then joins its runner thread inside ONE shared
  `timeout` budget (join runs in a worker thread, so the event loop is not
  blocked). A run that ignores the stop flag past the deadline is left to the
  process exit: it is a daemon thread, and blocking shutdown forever is worse
  than losing it;
* closes MCP server subprocesses through `tools.close_mcp_servers()`;
* flushes + closes the audit sink (its `close()` is flush-then-close and
  idempotent).

Call site: `web/server.py`'s lifespan `finally`. That file is owned by the
Lead/phases outside this one, so this module is only the mechanism; the ADR
records that shutdown stays cosmetic until the lifespan calls it.
"""

from __future__ import annotations

import asyncio
import logging
import time


_log = logging.getLogger("smolcode.web.shutdown")

# Same set as RunManager.is_busy / health._ACTIVE_RUN_STATUSES.
_ACTIVE_RUN_STATUSES = frozenset({"running", "awaiting_approval", "paused"})

__all__ = ["graceful_shutdown"]


def _state_of(app_state):
    """Return a Starlette state object, given either `app` or `app.state`."""
    if app_state is None:
        return None
    return getattr(app_state, "state", app_state)


def _active_runs(manager):
    try:
        runs = list(manager.list())
    except Exception as e:
        _log.debug("shutdown: cannot list runs: %s", e)
        return []
    return [r for r in runs if getattr(r, "status", None) in _ACTIVE_RUN_STATUSES]


def _cancel_queued(manager) -> int:
    """Drop every queued entry; returns how many were cancelled."""
    try:
        entries = list(manager.queue())
    except Exception as e:
        _log.debug("shutdown: cannot read the run queue: %s", e)
        return 0
    cancelled = 0
    for entry in entries:
        run_id = getattr(entry, "id", None)
        if not run_id:
            continue
        try:
            if manager.cancel_queue(run_id):
                cancelled += 1
        except Exception as e:
            _log.debug("shutdown: cancel_queue(%s) failed: %s", run_id, e)
    return cancelled


def _join_threads(threads, deadline: float) -> list[str]:
    """Join every runner thread within the shared deadline.

    Returns the names of threads that were still alive when the budget ran out.
    """
    alive = []
    for thread in threads:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            thread.join(timeout=remaining)
        except Exception as e:
            _log.debug("shutdown: thread join failed: %s", e)
            continue
        if getattr(thread, "is_alive", lambda: False)():
            alive.append(getattr(thread, "name", "?") or "?")
    return alive


async def graceful_shutdown(app_state, *, timeout: float = 10.0) -> None:
    """Stop work and release process-level resources; never raises.

    Args:
        app_state: the app's `.state` (or the app; it is unwrapped).
        timeout: total wall-clock budget in seconds for run threads to finish
            after the stop flag is set. `<= 0` means "do not wait".
    """
    state = _state_of(app_state)
    if state is None:
        return
    started = time.monotonic()
    try:
        budget = max(0.0, float(timeout))
    except (TypeError, ValueError):
        budget = 10.0
    deadline = started + budget

    manager = getattr(state, "run_manager", None)
    if manager is not None:
        # Order matters: empty the queue before stopping the active run, or
        # its finally-block drain may start the next queued run while we are
        # waiting for it to exit.
        cancelled = _cancel_queued(manager)
        if cancelled:
            _log.info("shutdown: dropped %d queued run(s)", cancelled)

        threads = []
        for run in _active_runs(manager):
            run_id = getattr(run, "id", None)
            try:
                stopped = bool(run_id and manager.stop(run_id))
            except Exception as e:
                _log.warning("shutdown: could not stop run %s: %s", run_id, e)
                stopped = False
            if stopped:
                _log.info("shutdown: stop requested for run %s", run_id)
            # Join even when stop() returned False: False means "this run is
            # not active anymore", and its thread may still be flushing the
            # final audit records. join() is bounded by the shared deadline.
            thread = getattr(run, "thread", None)
            if thread is not None and hasattr(thread, "join"):
                threads.append(thread)
        if threads:
            alive = await asyncio.to_thread(_join_threads, threads, deadline)
            if alive:
                _log.warning(
                    "shutdown: %d run thread(s) still alive after %.1fs: %s",
                    len(alive),
                    time.monotonic() - started,
                    ", ".join(alive),
                )

    # MCP servers are host processes owned by the tool layer (decision 0005).
    try:
        from ..tools import close_mcp_servers

        close_mcp_servers()
    except Exception as e:  # pragma: no cover - import-time failure is not fatal here
        _log.debug("shutdown: could not close MCP servers: %s", e)

    # Flush + close the audit sink last so any run-end records emitted above
    # are already in the file. AuditSink.close() is idempotent.
    sink = getattr(state, "audit_sink", None)
    if sink is not None:
        try:
            sink.close()
        except Exception as e:
            _log.warning("shutdown: audit sink close failed: %s", e)

    _log.info("shutdown: complete in %.2fs", time.monotonic() - started)
