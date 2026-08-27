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
    EVT_RUN_PAUSED,
    EVT_RUN_STARTED,
    EVT_STEP_ACTION,
    EVT_STEP_FINAL_ANSWER,
    STATUS_AWAITING_APPROVAL,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PAUSED,
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


# Phase 2 (decision 0025 §6.4): per-mention size cap for the file
# mentions (``@path``) inline-attachment feature. Files larger than
# this are NOT inlined; the agent is expected to call ``read_file``
# itself when it actually needs the content. Default 32 KB; override
# via SMOLCODE_WEB_MENTION_MAX_BYTES.
try:
    _MAX_MENTION_BYTES = int(os.environ.get("SMOLCODE_WEB_MENTION_MAX_BYTES", str(32 * 1024)))
except ValueError:
    _MAX_MENTION_BYTES = 32 * 1024


class _StopRequested(BaseException):
    """Internal: raised by the step callback when run.stop_flag is set."""


class _PauseRequested(BaseException):
    """Phase 2 (decision 0025 §6.4): raised by the step callback when
    ``run.pause_flag`` is set. Distinct from ``_StopRequested`` because
    pause is resumable (the agent is rebuilt from a memory snapshot
    on ``POST /api/runs/{id}/resume``), while stop is terminal.

    ``BaseException`` (not ``Exception``) so the broad ``except
    Exception`` in ``run_in_thread`` does NOT swallow it -- we want
    the same control-flow guarantee ``_StopRequested`` has.
    """


# Phase 2 (decision 0025 §6.4): ``@path`` mention syntax parser.
# Splits a task string into mention tokens. Skips tokens that appear
# inside fenced code blocks (`` ``` ... ``` ``) so example paths in
# the user's text are not mistakenly expanded. Pure function -- no
# I/O, no file resolution; that's ``_attach_mentions``'s job.
_MENTION_RE = __import__("re").compile(r"(?<!\w)@(?P<path>[A-Za-z0-9_./\\-]+)")
_FENCE_RE = __import__("re").compile(r"```[^\n]*\n.*?```", __import__("re").DOTALL)


def _parse_mentions(task: str):
    """Return a list of ``{"raw": "@x.py", "path": "x.py"}`` dicts.

    Mentions inside ```` ``` ```` code fences are stripped before the
    mention scan so the user's literal examples do not trigger
    inline-attachment.
    """
    if not isinstance(task, str) or not task:
        return []
    # Strip fenced code blocks; replace them with placeholder spaces
    # so the offsets of subsequent matches still align with the
    # ORIGINAL task string (we want ``raw`` to match what the user
    # actually wrote).
    masked = _FENCE_RE.sub(lambda m: " " * len(m.group(0)), task)
    out = []
    seen = set()
    for m in _MENTION_RE.finditer(masked):
        raw = m.group(0)
        path = m.group("path")
        if path in seen:
            continue
        seen.add(path)
        out.append({"raw": raw, "path": path, "start": m.start(), "end": m.end()})
    return out


def _attach_mentions(task: str, *, project_root):
    """Inline file contents for every ``@path`` mention in ``task``.

    Behaviour:

    - Each ``@<path>`` token is resolved against ``project_root``.
    - Paths that escape ``project_root`` (``../``, absolute paths
      outside, symlinks pointing out) are listed in an "unresolved"
      section; their content is NEVER inlined.
    - Files larger than ``_MAX_MENTION_BYTES`` are also marked
      unresolved (the agent can read them with ``read_file`` if it
      needs the content).
    - Non-UTF-8 files (binary blobs) are skipped -- the agent sees
      only the path + a "not inlined" note.

    Returns the augmented task string. The original ``task`` text is
    preserved verbatim; inlined content is appended as a fenced block
    section with the explicit header so the agent knows to skip the
    ``read_file`` round-trip.
    """
    from pathlib import Path as _P

    mentions = _parse_mentions(task)
    if not mentions:
        return task
    project_root = _P(project_root).resolve()
    inlined: list = []
    unresolved: list = []
    for m in mentions:
        rel_or_abs = m["path"]
        # Decide resolved candidate.
        candidate = _P(rel_or_abs)
        if not candidate.is_absolute():
            candidate = (project_root / candidate).resolve()
        else:
            try:
                candidate = candidate.resolve()
            except OSError:
                candidate = None
        # Safety: candidate must be inside project_root.
        safe = False
        if candidate is not None:
            try:
                # commonpath raises if drives differ on Windows; we
                # want any mismatch to fall into the "unresolved" bucket.
                safe = _P(os.path.commonpath([str(candidate), str(project_root)])) == project_root
            except (ValueError, OSError):
                safe = False
        if not safe or candidate is None or not candidate.is_file():
            unresolved.append(rel_or_abs)
            continue
        try:
            size = candidate.stat().st_size
        except OSError:
            unresolved.append(rel_or_abs)
            continue
        if size > _MAX_MENTION_BYTES:
            unresolved.append(rel_or_abs + " (too large: " + str(size) + " bytes)")
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            unresolved.append(rel_or_abs + " (binary or unreadable)")
            continue
        rel = candidate.relative_to(project_root).as_posix()
        inlined.append((rel, text))
    if not inlined and not unresolved:
        return task
    parts = [task, "", "--- Attached file mentions ---"]
    if inlined:
        parts.append("")
        parts.append("The following files were inlined by the SPA mention feature.")
        parts.append("Do NOT call read_file on these -- the content is already here.")
        for rel, text in inlined:
            parts.append("")
            parts.append("```" + rel)
            parts.append(text.rstrip("\n"))
            parts.append("```")
    if unresolved:
        parts.append("")
        parts.append("Unresolved mentions (could not be inlined -- read with read_file if needed):")
        for u in unresolved:
            parts.append("- " + u)
    return "\n".join(parts)


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


def _make_step_callback(run, agent_ref=None, cost_cap_tracker=None, settings=None):
    """Build the per-step callback the smolagents runner invokes.

    ``agent_ref`` is an optional list-of-one mutable container. The
    ``run_in_thread`` function writes the built agent into it AFTER the
    step callback is registered (smolagents requires the agent to be
    alive before ``agent.step_callbacks.register``). The callback uses
    the reference to call ``agent.memory`` for snapshotting when
    ``pause_flag`` is set.

    Phase 2 (decision 0025 §6.4) changes:

    1. Stop is checked FIRST (existing behaviour).
    2. After publishing the step, check ``run.pause_flag`` -- when
       set, the callback raises ``_PauseRequested`` so the agent's
       outer ``run()`` call returns early. ``run_in_thread`` catches
       it, snapshots the agent one more time, flips ``status`` to
       ``STATUS_PAUSED``, and emits ``run.paused``.

    Decision 0032 additions:
    - ``cost_cap_tracker`` + ``settings``: when both are provided, the
      callback computes the accumulated run-cost after each step and
      raises ``_StopRequested(cost_cap_exceeded:...)`` once the
      per-run cap is reached. ``settings`` is threaded through so
      ``cost_for`` can apply per-provider overrides.
    """

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
        # Decision 0032: per-step cap check. Only fires when both the
        # tracker AND a settings object are wired (the runner thread
        # does this for fresh starts; the legacy ``resume_active_agent``
        # path leaves them None per the design spec). We compute the
        # accumulated run-cost via ``cost_for`` against the run's
        # effective provider/model and ``run.tokens_in/out``.
        try:
            if cost_cap_tracker is not None and settings is not None and getattr(run, "tokens", None) is not None:
                cap = cost_cap_tracker.get_cap(run.provider or "")
                if cap > 0:
                    from ..model_catalog import cost_for

                    run_cost = cost_for(
                        run.provider or None,
                        run.model or None,
                        int(getattr(run, "tokens_in", 0) or 0),
                        int(getattr(run, "tokens_out", 0) or 0),
                        cache_hit=int(getattr(run.tokens, "cache_hit", 0) or 0),
                        settings=settings,
                    )
                    if run_cost >= cap:
                        # Format both sides with 4 decimal places to
                        # match the cost_cap_reached reason string.
                        reason = (
                            "cost_cap_exceeded:"
                            + str(run.provider or "")
                            + ":"
                            + format(run_cost, ".4f")
                            + ":"
                            + format(cap, ".4f")
                        )
                        raise _StopRequested(reason)
        except _StopRequested:
            raise
        except Exception as e:
            # Cap-check failures must NEVER wedge the runner thread;
            # log + continue so a broken dashboard or settings still
            # lets the agent finish its current step.
            _log.warning("cost cap check failed for run %s: %s", run.id, e)
        # Phase 2: snapshot the agent's memory AFTER each step so a
        # pause can resume without losing state. Then check pause_flag
        # and raise if set -- this terminates agent.run() at the next
        # step boundary.
        try:
            if agent_ref is not None and agent_ref[0] is not None and run.pause_flag.is_set():
                # Final snapshot before pause; covers any unflushed step.
                try:
                    run.snapshot(agent_ref[0])
                except Exception as e:
                    _log.warning("snapshot before pause failed for run %s: %s", run.id, e)
                raise _PauseRequested()
        except _PauseRequested:
            raise

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


def _build_full_access_gate(run, timeout_s):
    """Phase 1 (C1): per-run confirmation for full_access DELEGATIONS.

    Mirrors ``_build_confirm_callback``'s decision-modal flow but for the
    orchestrator's lazy gate: the first do_full_task / full_access-
    specialist delegation opens a PendingDecision (tool=
    "full_access_delegation"), publishes approval.requested, and blocks.
    An approval is memoized for the rest of the run; a denial raises so
    the delegation aborts (the orchestrator may route elsewhere).
    """

    state = {"confirmed": False}

    def _gate():
        if state["confirmed"]:
            return
        if run.stop_flag.is_set():
            raise PermissionError("full_access delegation refused: run stopped")
        run.status = STATUS_AWAITING_APPROVAL
        d = run.open_decision(
            tool="full_access_delegation",
            args={},
            summary="Confirm full-access delegation (orchestrator)?",
            tier="full_access",
        )
        run.publish(
            EVT_APPROVAL_REQUESTED,
            {
                "decision_id": d.id,
                "tool": "full_access_delegation",
                "args": {},
                "summary": "Confirm full-access delegation (orchestrator)?",
                "tier": "full_access",
                "ts": _time_now_iso(),
                "timeout_s": float(timeout_s),
            },
        )
        decided = d.event.wait(timeout=timeout_s)
        run.status = STATUS_RUNNING
        if not decided:
            d.resolve(approved=False, edited_args=None, reason="timeout")
            reason = "timeout"
        else:
            reason = d.reason or "user"
        approved = bool(decided and d.approved)
        run.publish(
            EVT_APPROVAL_DECIDED,
            {
                "decision_id": d.id,
                "approved": approved,
                "reason": reason,
                "ts": _time_now_iso(),
            },
        )
        if run.audit_sink is not None:
            try:
                run.audit_sink.record(
                    "full_access_confirmed" if approved else "full_access_denied",
                    via="orchestrator-delegation",
                    reason=reason,
                    run_id=run.id,
                )
            except Exception:
                pass
        if not approved:
            raise PermissionError("full_access delegation not confirmed (" + reason + ")")
        state["confirmed"] = True

    return _gate


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
        # Phase 1 (C1): arm the per-run full-access delegation gate so
        # do_full_task / full_access specialists hit the approval modal.
        from ..confirm import resolve_destructive_timeout_s as _rdt

        return build_orchestrator_agent(
            settings,
            model,
            audit_sink=run.audit_sink,
            outer_run=run,
            full_access_gate=_build_full_access_gate(run, _rdt()),
        )
    if run.tier == "restricted":
        return build_restricted_agent(settings, model)
    if run.tier == "elevated":
        return build_elevated_agent(settings, model)
    if run.tier == "full_access":
        return build_full_access_agent(settings, model)
    raise ValueError("unknown tier: " + str(run.tier))


def run_in_thread(run, settings, cost_cap_tracker=None):
    # Decision 0032: optional ``cost_cap_tracker`` is consulted on
    # EVERY step callback. ``None`` keeps the legacy behaviour
    # (no per-step cap enforcement) -- the run-start check in
    # ``RunManager.start_or_enqueue_run`` is the only enforcement.
    # Phase 3 F1 (decision 0036): stamp with wall clock so the
    # run-end event's duration_s lives in the same clock domain as
    # ``run.started_at`` (set by ``Run()``) and ``run.ended_at`` below.
    started = time.time()
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
            # Phase 1 (decision 0025 §6.3): tag the run with its
            # session + project so the SPA can group events. Both
            # additive; older clients ignore unknown fields.
            "session_id": run.session_id,
            "project": run.project,
            "ts": _time_now_iso(),
        },
    )

    destructive_timeout = resolve_destructive_timeout_s()
    # M10: SMOLCODE_WEB_DIFF_GATE controls the write_file / patch_file
    # diff gate. Default "1" = on. Set to "0" to disable (CLI parity
    # for users who want the web flow to behave like the CLI).
    import os as _os

    diff_gate_on = _os.environ.get("SMOLCODE_WEB_DIFF_GATE", "1") != "0"
    # v1.9.x / decision 0027: tag the session with the run id so
    # POST /api/runs/{id}/auto-approve can validate that the caller
    # is targeting THIS run's session (vs a stale id from the SPA's
    # in-memory state). RunManager only allows one active run at a
    # time, so the session singleton is unambiguous while a run is
    # in flight.
    session = SessionState(
        tier=run.tier,
        auto_approve_destructive=False,
        confirm_callback=_build_confirm_callback(run, destructive_timeout),
        audit_sink=run.audit_sink,
        diff_callback=_build_diff_callback(run, destructive_timeout) if diff_gate_on else None,
        run_id=run.id,
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
    # Phase 2 (decision 0025 §6.4): ``agent_ref`` is a one-element list
    # so the step callback (a closure) can reach the agent AFTER
    # registration. Snapshotting before pause requires the live agent.
    agent_ref: list = [None]
    # Phase 2: inline-attached @-mentions for file-mention syntax. The
    # ``project`` field on the Run resolves to a project root directory
    # via ``Settings.projects``; if no project is set we fall back to
    # ``settings.workspace`` (legacy mode).
    effective_task = run.task
    try:
        from pathlib import Path as _PathForMentions

        project_root = None
        if run.project:
            for p in getattr(settings, "projects", ()) or ():
                if getattr(p, "name", None) == run.project:
                    project_root = _PathForMentions(getattr(p, "root", None))
                    break
        if project_root is None:
            project_root = _PathForMentions(getattr(settings, "workspace", "") or "")
        if project_root and str(project_root):
            effective_task = _attach_mentions(run.task, project_root=project_root)
    except Exception as _e:
        _log.warning("mention attach failed for run %s: %s", run.id, _e)
        effective_task = run.task
    try:
        agent = _build_agent_for_run(run, settings)
        agent_ref[0] = agent
        # Decision 0032: thread the cost-cap tracker + settings so the
        # step callback can compute the per-run cost on every step and
        # trip the gate as soon as the cap is reached.
        cb = _make_step_callback(
            run,
            agent_ref=agent_ref,
            cost_cap_tracker=cost_cap_tracker,
            settings=settings,
        )
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
            run_future = pool.submit(agent.run, effective_task)
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
    except _PauseRequested:
        # Phase 2 (decision 0025 §6.4): the step callback raised
        # ``_PauseRequested`` because ``run.pause_flag`` was set.
        # The agent has already been snapshot by the callback. Flip
        # status to STATUS_PAUSED (NOT terminal -- resumable) and emit
        # ``run.paused`` so the SPA can swap the PauseButton label.
        final_status = STATUS_PAUSED
        run.error = None
        exit_code = 0
        run.publish(
            EVT_RUN_PAUSED,
            {
                "run_id": run.id,
                "snapshot_at": run.snapshot_at,
                "ts": _time_now_iso(),
            },
        )
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
        if run.subagent is not None:
            tier_label = run.subagent.tier or "subagent"
            ctx_parts.append("(while running sub-agent " + tier_label + " id=" + run.subagent.id[:8] + ")")
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
        run.ended_at = time.time()
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
        # Phase 2 (M-item): delete the auto-created smolcode-snap-*
        # snapshot temp file. A TERMINAL run can never resume, and
        # skipping this leaked one transcript JSON per web run into
        # the system temp directory.
        try:
            run.cleanup_temp_snapshot()
        except Exception as _e:
            _log.warning("snapshot cleanup failed for run %s: %s", run.id, _e)
        # Phase 2 (decision 0025 §6.4): drain the FIFO queue so the
        # next queued run starts. Done after EVT_RUN_ENDED so SSE
        # subscribers see the run ended before the next one starts.
        try:
            _drain_queue_after_run(run)
        except Exception as _e:
            _log.warning("queue drain failed after run %s: %s", run.id, _e)


def resume_active_agent(run, settings):
    """Phase 2 (decision 0025 §6.4): rebuild the agent from the
    snapshot and continue the run.

    Called from ``RunManager.resume_run`` (the API endpoint) AFTER the
    ``pause_flag`` is cleared. Steps:

    1. Load ``run.snapshot_path`` via ``run.load_snapshot``.
    2. Build a fresh agent via ``_build_agent_for_run`` (same factory
       the initial run used).
    3. Restore ``agent.memory.system_prompt`` + ``agent.memory.steps``
       from the snapshot data, instantiating the right step subclass
       for each entry (``step_type`` discriminator).
    4. Re-register the step callback so subsequent steps are
       published.
    5. Submit ``agent.run(snapshot_task, reset=False)`` to the same
       pool, so the existing wall-clock budget applies.

    The caller is responsible for clearing ``pause_flag`` and emitting
    ``run.resumed``. Returns the concurrent.futures.Future.
    """
    from smolagents.memory import (
        ActionStep,
        FinalAnswerStep,
        PlanningStep,
        TaskStep,
    )

    if run.snapshot_path is None:
        raise RuntimeError("cannot resume run " + run.id + ": no snapshot available")
    snap = run.load_snapshot(run.snapshot_path)

    agent = _build_agent_for_run(run, settings)

    # Restore system_prompt (it may be a SystemPromptStep object).
    sys_text = snap.get("system_prompt")
    if isinstance(sys_text, dict):
        sys_text = sys_text.get("system_prompt", "")
    if not isinstance(sys_text, str):
        sys_text = str(sys_text or "")
    # AgentMemory.__init__ creates a SystemPromptStep; replace its
    # ``system_prompt`` attribute directly.
    try:
        agent.memory.system_prompt.system_prompt = sys_text
    except Exception:
        pass

    # Rebuild the steps list.
    new_steps = []
    for s in snap.get("steps", []):
        kind = s.get("step_type")
        # SystemPromptStep lives in agent.memory.system_prompt; skip.
        if kind == "SystemPromptStep":
            continue
        # ActionStep / PlanningStep / TaskStep / FinalAnswerStep.
        cls = {
            "ActionStep": ActionStep,
            "PlanningStep": PlanningStep,
            "TaskStep": TaskStep,
            "FinalAnswerStep": FinalAnswerStep,
        }.get(kind)
        if cls is None:
            continue
        # Drop the discriminator + any non-init fields before passing
        # to the dataclass constructor. ``dict()`` over smolagents
        # returns only field names, but be defensive.
        try:
            import dataclasses as _dc

            field_names = {f.name for f in _dc.fields(cls)}
            payload = {k: v for k, v in s.items() if k in field_names and k != "step_type"}
            step = cls(**payload)
        except Exception:
            continue
        new_steps.append(step)
    agent.memory.steps = new_steps

    # Re-register step callback.
    agent_ref = [agent]
    cb = _make_step_callback(run, agent_ref=agent_ref)
    for step_cls in (ActionStep, PlanningStep, FinalAnswerStep):
        try:
            agent.step_callbacks.register(step_cls, cb)
        except Exception as e:
            _log.warning(
                "resume step callback register failed for run %s (%s): %s",
                run.id,
                step_cls.__name__,
                e,
            )

    # Submit the continuation to the same ThreadPoolExecutor used by
    # ``run_in_thread``. We import ``concurrent.futures`` lazily so the
    # caller still owns the lifecycle.
    return agent


def _drain_queue_after_run(run):
    """Phase 2 (decision 0025 §6.4): pop the next queue entry and
    start its runner thread.

    Called from ``run_in_thread``'s finally block, AFTER the run has
    reached a terminal status (or paused -- paused is NOT terminal but
    we still want to drain the queue so the next queued run can
    proceed). The queue entries are ``QueueEntry`` records that mirror
    the parameters of the original ``start_run`` call.
    """
    from . import api as _api_module  # late import to avoid cycle

    mgr = _api_module.get_run_manager()
    with mgr._queue_lock:
        if not mgr._queue:
            return None
        entry = mgr._queue.pop(0)
    # Update queue positions on remaining entries.
    mgr._refresh_queue_positions()
    # Look up the pre-allocated Run record (already in mgr._runs from
    # the original ``start_run`` call) and start its runner thread.
    target = mgr.get(entry.id)
    if target is None:
        return None
    # Settings + audit: the queue entry only carries overrides; we
    # use the global ``get_settings`` because that's what the SPA
    # was using when the original start_run call happened.
    settings = _api_module.get_settings()
    from . import deps as _deps

    settings = _deps.get_settings()
    # Decision 0032: pull the cost-cap tracker off the run manager so
    # queued runs (dequeued after the active run ends) get the same
    # per-step cap enforcement as the initial start_run call.
    # ``RunManager._cost_cap_tracker`` is set at construction time by
    # ``create_app`` and is the SAME instance the API endpoint mutates
    # via PUT /api/cost-caps -- so a PUT that lowers the cap during
    # the active run takes effect on the next queued run too.
    cost_cap_tracker = getattr(mgr, "_cost_cap_tracker", None)
    # Start the runner thread for the dequeued run.
    import threading as _threading

    target.status = STATUS_RUNNING
    target.thread = _threading.Thread(
        target=run_in_thread,
        args=(target, settings),
        kwargs={"cost_cap_tracker": cost_cap_tracker},
        name="smolcode-run-" + target.id[:8],
        daemon=True,
    )
    target.thread.start()
    return target.id


__all__ = [
    "run_in_thread",
    "resume_active_agent",
    "_StopRequested",
    "_PauseRequested",
    "_attach_mentions",
    "_parse_mentions",
]
