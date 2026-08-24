"""Agent runner for the web GUI (M9, decision 0010 D2 + D5).

Wraps the existing per-tier CodeAgent factory in a background thread
that publishes step events to the Run's SSE queue and converts the
M4.x destructive-op confirm prompt into a POST-able approval gate.

See module docstring for the full design notes.
"""

from __future__ import annotations

import logging
import os
import time
import traceback

from ..confirm import resolve_destructive_timeout_s
from ..session import DestructiveDecision, DiffDecision, SessionState, set_session
from .diffs import summarize, unified_hunks, unified_text
from .runs import (
    EVT_APPROVAL_DECIDED,
    EVT_APPROVAL_REQUESTED,
    EVT_DIFF_PROPOSED,
    EVT_DIFF_RESOLVED,
    EVT_ERROR,
    EVT_PLAN_STEP,
    EVT_RUN_ENDED,
    EVT_RUN_STARTED,
    EVT_STEP_ACTION,
    EVT_STEP_FINAL_ANSWER,
    STATUS_AWAITING_APPROVAL,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_RUNNING,
    STATUS_STOPPED,
)


_log = logging.getLogger(__name__)


# Decision 0023 (layer B): wall-clock timeout for a single Web UI run.
# If the model hangs inside the Jupyter kernel -- the failure mode
# that bit the user on 2026-08-23 was the model writing
# ``!pip install smolcode`` and never hearing back from the kernel --
# ``agent.run()`` blocks forever and the runner thread never reaches
# its ``finally`` block, so ``agent.cleanup()`` never fires and the
# next run fails with ``Bind for 127.0.0.1:8888 failed: port is
# already allocated``.
#
# We bound ``agent.run()`` with a ``concurrent.futures`` timeout. On
# timeout we call ``agent.cleanup()`` to forcibly stop the container
# (which fails the in-flight Jupyter request and frees the port), then
# reuse the existing ``_StopRequested`` path so the run is published
# as ``stopped`` with a clear error message.
#
# Override at runtime with ``SMOLCODE_WEB_RUN_TIMEOUT_S`` (default 15
# minutes). Tests set this to a small value via monkeypatch.
try:
    _MAX_RUN_WALL_S = int(os.environ.get("SMOLCODE_WEB_RUN_TIMEOUT_S", "900"))
except ValueError:
    _MAX_RUN_WALL_S = 900


# Grace period after a forced cleanup for the inner ``agent.run``
# thread to notice the container is gone and exit on its own. We do
# not block on this in production -- the publish-event happens first
# so the Web UI is unblocked immediately -- but tests want to assert
# the inner thread exited before tearing the fixture down.
_MAX_RUN_DRAIN_S = float(os.environ.get("SMOLCODE_WEB_RUN_DRAIN_S", "30"))


class _StopRequested(BaseException):
    """Internal: raised by the step callback when run.stop_flag is set."""


def _safe_str(value, max_len=4000):
    if value is None:
        return ""
    try:
        s = str(value)
    except Exception:
        s = repr(value)
    if len(s) > max_len:
        return s[: max_len - 1] + "\u2026"
    return s


def _step_kind(step):
    return type(step).__name__


def _time_now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _action_step_payload(step):
    out = {
        "kind": "action",
        "step_number": getattr(step, "step_number", None),
    }
    mom = getattr(step, "model_output_message", None)
    if mom is not None:
        out["thought"] = _safe_str(getattr(mom, "content", "") or getattr(mom, "text", "") or "")
    else:
        mo = getattr(step, "model_output", None)
        if mo is not None:
            out["thought"] = _safe_str(mo)
    code_action = getattr(step, "code_action", None)
    if code_action is not None:
        out["code_action"] = _safe_str(code_action)
    tool_calls = getattr(step, "tool_calls", None)
    if tool_calls:
        out["tool_calls"] = [
            {
                "name": getattr(tc, "name", "") or "",
                "id": getattr(tc, "id", "") or "",
                "args": getattr(tc, "arguments", None) or getattr(tc, "args", None) or {},
            }
            for tc in tool_calls
        ]
    observations = getattr(step, "observations", None)
    if observations is not None:
        out["observations"] = _safe_str(observations)
    err = getattr(step, "error", None)
    if err is not None:
        out["error"] = _safe_str(err)
    if getattr(step, "is_final_answer", False):
        out["is_final_answer"] = True
    timing = getattr(step, "timing", None)
    if timing is not None:
        dur = getattr(timing, "duration", None)
        if dur is not None:
            out["timing_ms"] = float(dur) * 1000.0
    tokens = getattr(step, "token_usage", None)
    if tokens is not None:
        try:
            out["tokens"] = {
                "input": int(getattr(tokens, "input_tokens", 0) or 0),
                "output": int(getattr(tokens, "output_tokens", 0) or 0),
            }
        except Exception:
            pass
    return out


def _planning_step_payload(step):
    out = {"kind": "plan", "step_number": getattr(step, "step_number", None)}
    plan = getattr(step, "plan", None)
    if plan is not None:
        out["plan"] = _safe_str(plan)
    return out


def _final_answer_step_payload(step):
    out = {"kind": "final_answer"}
    out["answer"] = _safe_str(getattr(step, "output", None) or getattr(step, "answer", None) or "")
    return out


def _make_step_callback(run):
    # smolagents >= 1.27 invokes step callbacks as `cb(memory_step, agent=self)`,
    # so the signature must accept any positional/keyword extras without erroring.
    def _cb(step, **_kwargs):
        if run.stop_flag.is_set():
            raise _StopRequested()
        try:
            kind = _step_kind(step)
            if kind == "ActionStep":
                run.publish(EVT_STEP_ACTION, _action_step_payload(step))
            elif kind == "PlanningStep":
                run.publish(EVT_PLAN_STEP, _planning_step_payload(step))
            elif kind == "FinalAnswerStep":
                run.publish(EVT_STEP_FINAL_ANSWER, _final_answer_step_payload(step))
        except _StopRequested:
            raise
        except Exception as e:
            _log.warning("step callback failed for run %s: %s", run.id, e)

    return _cb


def _build_confirm_callback(run, timeout_s):
    def _cb(tool_name, kwargs, summary):
        if run.stop_flag.is_set():
            decision = DestructiveDecision(approved=False, reason="stopped")
        else:
            run.status = STATUS_AWAITING_APPROVAL
            d = run.open_decision(
                tool=tool_name,
                args=dict(kwargs) if isinstance(kwargs, dict) else {},
                summary=str(summary),
                tier=run.tier,
            )
            run.publish(
                EVT_APPROVAL_REQUESTED,
                {
                    "decision_id": d.id,
                    "tool": tool_name,
                    "args": d.args,
                    "summary": str(summary),
                    "tier": run.tier,
                    "ts": _time_now_iso(),
                    "timeout_s": float(timeout_s),
                },
            )
            decided = d.event.wait(timeout=timeout_s)
            if not decided:
                d.resolve(approved=False, edited_args=None, reason="timeout")
                run.publish(
                    EVT_APPROVAL_DECIDED,
                    {
                        "decision_id": d.id,
                        "approved": False,
                        "reason": "timeout",
                        "ts": _time_now_iso(),
                    },
                )
                decision = DestructiveDecision(approved=False, reason="timeout")
            else:
                decision = DestructiveDecision(
                    approved=bool(d.approved),
                    reason=d.reason or "user",
                )
            run.status = STATUS_RUNNING

        if run.audit_sink is not None:
            try:
                run.audit_sink.record(
                    "destructive_decision",
                    tool=tool_name,
                    summary=str(summary),
                    approved=decision.approved,
                    reason=decision.reason,
                    run_id=run.id,
                )
            except Exception:
                pass
        return decision

    return _cb


def _rel_path(run, abs_path):
    """Workspace-relative path for ``abs_path`` (best effort)."""
    if not isinstance(abs_path, str) or not abs_path:
        return ""
    if not run.workspace:
        return ""
    import os

    try:
        common = os.path.commonpath([os.path.normcase(abs_path), os.path.normcase(run.workspace)])
    except ValueError:
        return ""
    if common != os.path.normcase(run.workspace):
        return ""
    return os.path.relpath(abs_path, run.workspace).replace(os.sep, "/")


def _build_diff_callback(run, timeout_s):
    """Return a SessionState.diff_callback that gates write_file/patch_file.

    The callback:

    1. Publishes a ``diff.proposed`` SSE event with the full diff
       (structured hunks + raw unified-diff text) + before/after.
    2. Sets the run status to ``STATUS_AWAITING_APPROVAL`` so the
       SPA can show a "waiting" indicator.
    3. Blocks on the PendingDecision.event.
    4. On approve -> returns ``DiffDecision(approved=True, edited_after=...)``
       (edited_after is the user's edited content if any).
    5. On deny -> returns ``DiffDecision(approved=False)``; the tool
       then raises PermissionError so the agent sees the failure.
    6. On timeout -> deny with reason="timeout".
    """

    def _cb(tool_name, kwargs, path, before, after, summary):
        if run.stop_flag.is_set():
            return DiffDecision(approved=False, reason="stopped")
        run.status = STATUS_AWAITING_APPROVAL
        rel = _rel_path(run, path)
        if rel:
            run.record_touch(rel)
        try:
            hunks = unified_hunks(before, after)
            raw = unified_text(before, after)
            summary_dict = summarize(before, after)
        except Exception as e:
            _log.warning("diff compute failed for run %s: %s", run.id, e)
            hunks = []
            raw = ""
            summary_dict = {"added": 0, "removed": 0, "same": 0, "changed": False}
        d = run.open_decision(
            tool=tool_name,
            args=dict(kwargs) if isinstance(kwargs, dict) else {},
            summary=str(summary),
            tier=run.tier,
            kind="diff",
            path=str(path or ""),
            before=str(before or ""),
            after=str(after or ""),
        )
        run.publish(
            EVT_DIFF_PROPOSED,
            {
                "decision_id": d.id,
                "tool": tool_name,
                "path": str(path or ""),
                "rel_path": rel,
                "args": d.args,
                "summary": str(summary),
                "tier": run.tier,
                "before": str(before or ""),
                "after": str(after or ""),
                "hunks": [h.to_dict() for h in hunks],
                "raw_diff": raw,
                "stats": summary_dict,
                "ts": _time_now_iso(),
                "timeout_s": float(timeout_s),
            },
        )
        decided = d.event.wait(timeout=timeout_s)
        if not decided:
            d.resolve(approved=False, edited_args=None, reason="timeout")
            run.status = STATUS_RUNNING
            run.publish(
                EVT_DIFF_RESOLVED,
                {
                    "decision_id": d.id,
                    "approved": False,
                    "reason": "timeout",
                    "edited": False,
                    "path": str(path or ""),
                    "ts": _time_now_iso(),
                },
            )
            decision = DiffDecision(approved=False, reason="timeout")
        else:
            edited_after = None
            if isinstance(d.edited_args, dict):
                edited_after = d.edited_args.get("__edited_after__")
            decision = DiffDecision(
                approved=bool(d.approved),
                edited_after=edited_after,
                reason=d.reason or "user",
            )
            run.status = STATUS_RUNNING

        if run.audit_sink is not None:
            try:
                run.audit_sink.record(
                    "diff_decision",
                    tool=tool_name,
                    path=str(path or ""),
                    summary=str(summary),
                    approved=decision.approved,
                    reason=decision.reason,
                    edited=decision.edited_after is not None,
                    run_id=run.id,
                )
            except Exception:
                pass
        return decision

    return _cb


def _build_agent_for_run(run, settings):
    from ..agents.elevated import build_elevated_agent
    from ..agents.full_access import build_full_access_agent
    from ..agents.orchestrator import build_orchestrator_agent
    from ..agents.restricted import build_restricted_agent
    from ..models import build_model

    # M11: forward per-run provider / model / key overrides (decision 0014).
    # The api_key_value is consumed exactly here -- never logged, never
    # copied onto the Settings object (which can be re-serialised), never
    # persisted to disk.
    model = build_model(
        settings,
        preset_name=run.provider_override or run.provider,
        model_override=run.model_override or run.model or None,
        api_key_override=run.api_key_value,
    )
    if run.tier == "orchestrator":
        # Phase 0 (decision 0025): pass the outer Run so the orchestrator
        # tools can publish subagent.started / subagent.ended events.
        return build_orchestrator_agent(settings, model, audit_sink=run.audit_sink, outer_run=run)
    if run.tier == "restricted":
        return build_restricted_agent(settings, model)
    if run.tier == "elevated":
        return build_elevated_agent(settings, model)
    if run.tier == "full_access":
        return build_full_access_agent(settings, model)
    raise ValueError("unknown tier: " + str(run.tier))


def run_in_thread(run, settings):
    started = time.monotonic()
    run.status = STATUS_RUNNING
    run.publish(
        EVT_RUN_STARTED,
        {
            "run_id": run.id,
            "task": run.task,
            "tier": run.tier,
            "model": run.model,
            "provider": run.provider,
            "workspace": run.workspace,
            "ts": _time_now_iso(),
        },
    )

    destructive_timeout = resolve_destructive_timeout_s()
    # M10: SMOLCODE_WEB_DIFF_GATE controls the write_file / patch_file
    # diff gate. Default "1" = on. Set to "0" to disable (CLI parity
    # for users who want the web flow to behave like the CLI).
    import os as _os

    diff_gate_on = _os.environ.get("SMOLCODE_WEB_DIFF_GATE", "1") != "0"
    session = SessionState(
        tier=run.tier,
        auto_approve_destructive=False,
        confirm_callback=_build_confirm_callback(run, destructive_timeout),
        audit_sink=run.audit_sink,
        diff_callback=_build_diff_callback(run, destructive_timeout) if diff_gate_on else None,
    )
    set_session(session)

    if run.audit_sink is not None:
        try:
            run.audit_sink.start(
                tier=run.tier,
                task=run.task,
                model=run.model,
                provider=run.provider,
                executor=getattr(settings, "executor", ""),
                workspace=run.workspace,
            )
        except Exception as e:
            _log.warning("audit start failed for run %s: %s", run.id, e)

    exit_code = 0
    final_status = STATUS_DONE
    agent = None
    # Decision 0023 (layer B): we run ``agent.run`` inside a ThreadPoolExecutor
    # so the runner thread can return within a bounded wall-clock window even
    # when the Jupyter kernel itself is hung (e.g. the model wrote
    # ``!pip install smolcode`` and the kernel is stuck downloading).
    import concurrent.futures

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"smolcode-{run.id}")
    run_future = None
    try:
        agent = _build_agent_for_run(run, settings)
        cb = _make_step_callback(run)
        from smolagents.agents import ActionStep, FinalAnswerStep, PlanningStep

        # Decision 0024 (defensive): register all three step kinds in
        # try/except. Earlier code only wrapped PlanningStep /
        # FinalAnswerStep, leaving ActionStep bare -- so any failure
        # in registering the Web UI's step callback (which we observed
        # manifesting as OSError [Errno 22] on Windows when the agent
        # construction left smolagents' internal state in a bad shape)
        # would surface to the broad ``except Exception`` block with
        # no usable context. Now: a registration failure logs and
        # continues -- the agent runs without our step callback, but
        # it still runs. The captured traceback in the broad except
        # already gives us a stack if something else goes wrong.
        for step_cls in (ActionStep, PlanningStep, FinalAnswerStep):
            try:
                agent.step_callbacks.register(step_cls, cb)
            except Exception as e:
                _log.warning(
                    "step callback register failed for run %s (%s): %s",
                    run.id,
                    step_cls.__name__,
                    e,
                )

        try:
            run_future = pool.submit(agent.run, run.task)
        except Exception as e:
            # ThreadPoolExecutor.submit() can raise if the worker
            # thread fails to start (interpreter shutdown, OOM,
            # etc.). Surface it via the same error path the inner
            # ``agent.run`` would have surfaced.
            raise RuntimeError("agent.run submission failed: " + repr(e)) from e
        try:
            answer = run_future.result(timeout=_MAX_RUN_WALL_S)
            run.result = _safe_str(answer, max_len=200000)
        except concurrent.futures.TimeoutError:
            # Decision 0023 (layer B): the model hung inside the
            # Jupyter kernel -- it never returned from the request,
            # so agent.run() is still blocked in the worker thread.
            # Don't try to cancel the thread here (we can't -- it's
            # blocked on a network request). Instead, mark the run as
            # STOPPED with a clear error and let the existing ``finally``
            # block kill the container via agent.cleanup(); once the
            # container is gone, the in-flight Jupyter request fails
            # and the worker thread exits on its own. pool.shutdown
            # below uses wait=False so we do not block on the dying
            # thread.
            _log.warning(
                "run %s exceeded %ds wall-clock timeout; executor will be forcibly stopped in finally",
                run.id,
                _MAX_RUN_WALL_S,
            )
            final_status = STATUS_STOPPED
            run.error = (
                "wall-clock timeout: run exceeded "
                + str(_MAX_RUN_WALL_S)
                + "s without completing; executor was forcibly stopped"
            )
            exit_code = 124  # standard "timed out" exit code
    except _StopRequested:
        final_status = STATUS_STOPPED
        run.error = "stopped by user"
        exit_code = 130
    except KeyboardInterrupt:
        final_status = STATUS_STOPPED
        run.error = "interrupted"
        exit_code = 130
    except Exception as e:
        final_status = STATUS_ERROR
        # Decision 0024: capture the full traceback so the Web UI can
        # surface the actual failing line (the previous behaviour only
        # stored the exception repr, which left OSError [Errno 22]
        # Invalid argument completely un-diagnosable). We cap at 8 KB
        # so a runaway traceback does not blow up the SSE queue.
        tb_text = traceback.format_exc()
        if len(tb_text) > 8192:
            tb_text = tb_text[: 8192 - 1] + "\u2026"
        # Phase 0 (decision 0025, BE-7): include the active sub-agent
        # context when the orchestrator raised mid-delegation. The
        # SPA renders this as a "while running sub-agent X" hint.
        ctx_parts = [type(e).__name__ + ": " + _safe_str(e)]
        if run.subagent_id is not None:
            tier_label = run.subagent_tier or "subagent"
            ctx_parts.append("(while running sub-agent " + tier_label + " id=" + run.subagent_id[:8] + ")")
        ctx_parts.append(tb_text)
        run.error = "\n".join(ctx_parts)
        exit_code = 1
        run.publish(
            EVT_ERROR,
            {
                "run_id": run.id,
                "kind": type(e).__name__,
                "message": _safe_str(e),
                "traceback": tb_text,
                "ts": _time_now_iso(),
            },
        )
        if run.audit_sink is not None:
            try:
                run.audit_sink.error(e)
            except Exception:
                pass
    finally:
        # Decision 0022: ALWAYS tear down the Docker executor.
        # `auto_remove=True` only fires when the container's main
        # process exits cleanly. If the model hung on `!pip install
        # smolcode`, or the Web UI connection dropped, or the run was
        # force-stopped, the container + kernel survive indefinitely
        # and hold the host's 127.0.0.1:8888 port -- the next run then
        # fails with "Bind for 127.0.0.1:8888 failed: port is already
        # allocated". Calling `agent.cleanup()` runs
        # `DockerExecutor.cleanup()` which is
        # `container.stop(); container.remove()` (idempotent).
        if agent is not None:
            try:
                agent.cleanup()
            except Exception as e:
                _log.warning("agent cleanup failed for run %s: %s", run.id, e)
        # Decision 0023 (layer B): release the ThreadPoolExecutor
        # WITHOUT waiting for the inner agent.run thread. If the model
        # hung and we already called ``agent.cleanup()`` above, the
        # Jupyter request inside the inner thread will fail shortly;
        # we do not want to block the runner thread on that.
        try:
            pool.shutdown(wait=False)
        except Exception:
            pass
        run.ended_at = time.monotonic()
        run.status = final_status
        try:
            set_session(None)
        except Exception:
            pass
        if run.audit_sink is not None:
            try:
                run.audit_sink.end(exit_code=exit_code, duration_s=run.ended_at - started)
            except Exception:
                pass
        run.publish(
            EVT_RUN_ENDED,
            {
                "run_id": run.id,
                "status": final_status,
                "exit_code": exit_code,
                "duration_s": run.ended_at - started,
                "result": run.result,
                "error": run.error,
                "ts": _time_now_iso(),
            },
        )


__all__ = ["run_in_thread", "_StopRequested"]
