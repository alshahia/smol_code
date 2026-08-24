"""Run manager for live execution via SSE (M9, decision 0010 D2 + D5).

This module owns the runtime side of "the SPA starts a task and watches
the agent step through it". It is intentionally small and process-local.

See the module docstring in the source for the full design notes.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


_log = logging.getLogger(__name__)


EVT_RUN_STARTED = "run.started"
EVT_RUN_ENDED = "run.ended"
EVT_PLAN_STEP = "plan.step"
EVT_STEP_ACTION = "step.action"
EVT_STEP_FINAL_ANSWER = "step.final_answer"
EVT_APPROVAL_REQUESTED = "approval.requested"
EVT_APPROVAL_DECIDED = "approval.decided"
EVT_DIFF_PROPOSED = "diff.proposed"  # M10
EVT_DIFF_RESOLVED = "diff.resolved"  # M10
EVT_ERROR = "error"


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode_event(event_type, data, event_id=None):
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lines = []
    if event_id:
        lines.append("id: " + event_id)
    lines.append("event: " + event_type)
    for ln in payload.splitlines() or [payload]:
        lines.append("data: " + ln)
    return "\n".join(lines) + "\n\n"


@dataclass
class PendingDecision:
    id: str
    tool: str
    args: dict
    summary: str
    tier: str
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool | None = None
    edited_args: dict | None = None
    reason: str = ""
    # M10: "destructive" (M9 confirm flow) or "diff" (M10 write_file
    # gate). Empty string falls back to "destructive" for backward
    # compatibility.
    kind: str = "destructive"
    # M10: for diff gates, the file path + before text. Optional for
    # destructive gates (still passed for symmetry).
    path: str = ""
    before: str = ""
    after: str = ""

    def resolve(self, approved, edited_args, reason):
        if self.event.is_set():
            return
        self.approved = bool(approved)
        self.edited_args = edited_args
        self.reason = reason
        self.event.set()


STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_STOPPED = "stopped"

_TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_ERROR, STATUS_STOPPED})


@dataclass
class Run:
    id: str
    task: str
    tier: str
    status: str = STATUS_PENDING
    events: queue.Queue = field(default_factory=queue.Queue)
    pending: list = field(default_factory=list)
    pending_lock: threading.Lock = field(default_factory=threading.Lock)
    stop_flag: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    result: str | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None
    audit_sink: Any = None
    model: str = ""
    provider: str = ""
    workspace: str = ""
    # M10: workspace-relative paths the run has touched (write_file +
    # patch_file). The SPA's workspace tree highlights these.
    touched_paths: set = field(default_factory=set)
    touched_lock: threading.Lock = field(default_factory=threading.Lock)
    # M11: per-run provider / model / API-key overrides (decision 0014).
    # ``provider_override`` and ``model_override`` are non-None only
    # when the SPA explicitly overrode the Settings defaults.
    # ``api_key_value`` is the single key supplied for the chosen
    # provider's ``api_key_env``; it is NEVER logged or returned in
    # any event payload -- the runner reads it off ``Run`` once, when
    # it calls ``build_model`` in agent_runner.py.
    provider_override: str | None = None
    model_override: str | None = None
    api_key_value: str | None = None

    def record_touch(self, rel_path):
        if not isinstance(rel_path, str) or not rel_path:
            return
        with self.touched_lock:
            self.touched_paths.add(rel_path)

    def touched_list(self):
        with self.touched_lock:
            return sorted(self.touched_paths)

    def publish(self, event_type, data):
        frame = _encode_event(event_type, data, event_id=self._next_event_id())
        try:
            self.events.put_nowait(frame)
        except Exception as e:
            _log.warning("run %s: event put failed: %s", self.id, e)

    def _next_event_id(self):
        n = getattr(self, "_evt_seq", 0) + 1
        self._evt_seq = n
        return self.id + ":" + str(n)

    def open_decision(self, tool, args, summary, tier, *, kind="destructive", path="", before="", after=""):
        d = PendingDecision(
            id=uuid.uuid4().hex,
            tool=tool,
            args=args,
            summary=summary,
            tier=tier,
            kind=str(kind or "destructive"),
            path=str(path or ""),
            before=str(before or ""),
            after=str(after or ""),
        )
        with self.pending_lock:
            self.pending.append(d)
        return d

    def take_decision(self, decision_id):
        with self.pending_lock:
            for i, d in enumerate(self.pending):
                if d.id == decision_id:
                    return self.pending.pop(i)
        return None


class RunManager:
    def __init__(self):
        self._runs = {}
        self._lock = threading.Lock()

    def start_run(
        self,
        *,
        task,
        tier,
        settings,
        audit=None,
        provider_override=None,
        model_override=None,
        api_key_value=None,
    ):
        """Start one agent run.

        M11 (decision 0014) extensions: ``provider_override``,
        ``model_override`` and ``api_key_value`` are forwarded by
        ``POST /api/runs``. ``run.provider`` and ``run.model`` reflect
        the EFFECTIVE values (override wins over ``settings``). The
        ``api_key_value`` is kept on the Run as a private field and
        is consumed exactly once, in ``agent_runner.run_in_thread``,
        when constructing the LiteLLM model. It is NEVER included in
        any event payload or audit record.
        """
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        if tier not in ("restricted", "elevated", "full_access", "orchestrator"):
            raise ValueError("tier must be restricted|elevated|full_access|orchestrator")

        base_provider = getattr(settings, "provider", "") or ""
        base_model = getattr(settings, "model", "") or ""
        effective_provider = provider_override or base_provider
        effective_model = model_override or base_model

        # Reject unknown providers early so the SSE stream starts with a
        # known id (the run.started event surfaces run.provider).
        if provider_override is not None:
            from ..models import get_preset

            try:
                get_preset(provider_override)
            except ValueError as e:
                raise ValueError(str(e)) from e

        # Normalise the optional api_key_value (only set when the SPA
        # supplied it). Reject obviously malformed values early.
        ak = api_key_value if isinstance(api_key_value, str) and api_key_value.strip() else None

        run = Run(
            id=uuid.uuid4().hex,
            task=task.strip(),
            tier=tier,
            audit_sink=audit,
            model=effective_model,
            provider=effective_provider,
            workspace=str(getattr(settings, "workspace", "") or ""),
            provider_override=provider_override,
            model_override=model_override,
            api_key_value=ak,
        )
        with self._lock:
            self._runs[run.id] = run
        from .agent_runner import run_in_thread

        run.thread = threading.Thread(
            target=run_in_thread,
            args=(run, settings),
            name="smolcode-run-" + run.id[:8],
            daemon=True,
        )
        run.thread.start()
        return run.id

    def get(self, run_id):
        with self._lock:
            return self._runs.get(run_id)

    def list(self):
        with self._lock:
            return list(self._runs.values())

    def subscribe(self, run_id):
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        HEARTBEAT_S = 15.0
        while True:
            try:
                frame = run.events.get(timeout=HEARTBEAT_S)
            except queue.Empty:
                yield ": heartbeat\n\n"
                if run.status in _TERMINAL_STATUSES and run.events.empty():
                    break
                continue
            yield frame
            if run.status in _TERMINAL_STATUSES and run.events.empty():
                try:
                    frame = run.events.get_nowait()
                except queue.Empty:
                    break
                else:
                    yield frame
                break
        yield _encode_event("end", {"run_id": run.id, "status": run.status}, event_id=None)

    def decide(self, run_id, decision_id, approved, edited_args=None, reason="user", edited_after=None):
        run = self.get(run_id)
        if run is None:
            return False
        d = run.take_decision(decision_id)
        if d is None:
            return False
        # M10: for diff gates, edited_after replaces the proposed
        # content. Persist it on the decision so the runner picks it up.
        if edited_after is not None:
            d.edited_args = {"__edited_after__": str(edited_after)}
        d.resolve(approved=approved, edited_args=d.edited_args, reason=reason)
        # M10: choose the right "decided" event name.
        if d.kind == "diff":
            run.publish(
                EVT_DIFF_RESOLVED,
                {
                    "decision_id": decision_id,
                    "approved": bool(approved),
                    "reason": reason,
                    "edited": bool(edited_after is not None and edited_after != d.after),
                    "path": d.path,
                    "ts": _now_iso(),
                },
            )
        else:
            run.publish(
                EVT_APPROVAL_DECIDED,
                {
                    "decision_id": decision_id,
                    "approved": bool(approved),
                    "reason": reason,
                    "ts": _now_iso(),
                },
            )
        return True

    def stop(self, run_id):
        run = self.get(run_id)
        if run is None:
            return False
        run.stop_flag.set()
        return True


__all__ = [
    "EVT_RUN_STARTED",
    "EVT_RUN_ENDED",
    "EVT_PLAN_STEP",
    "EVT_STEP_ACTION",
    "EVT_STEP_FINAL_ANSWER",
    "EVT_APPROVAL_REQUESTED",
    "EVT_APPROVAL_DECIDED",
    "EVT_DIFF_PROPOSED",
    "EVT_DIFF_RESOLVED",
    "EVT_ERROR",
    "PendingDecision",
    "Run",
    "RunManager",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_AWAITING_APPROVAL",
    "STATUS_DONE",
    "STATUS_ERROR",
    "STATUS_STOPPED",
]
