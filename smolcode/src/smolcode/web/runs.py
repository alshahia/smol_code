"""Run manager for live execution via SSE (M9, decision 0010 D2 + D5).

This module owns the runtime side of "the SPA starts a task and watches
the agent step through it". It is intentionally small and process-local.

See the module docstring in the source for the full design notes.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Decision 0028: cost_for() is used in summary_dict() to derive the
# per-sub-agent USD cost from the per-sub-agent token accumulators.
# Imported lazily here to keep the module-level dependency surface
# explicit; the function itself is a pure helper that reads
# DEFAULT_COST_RATES (no Settings needed for v1).
from smolcode.model_catalog import cost_for


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
# Phase 0 (decision 0025): sub-agent lifecycle events emitted by the
# orchestrator's ``do_<tier>_task`` / ``do_specialist`` tools around
# each inner ``agent.run()`` invocation. The SPA renders these as a
# nested <SubAgentBlock> child of the parent's outer step.action row.
EVT_SUBAGENT_STARTED = "subagent.started"
EVT_SUBAGENT_ENDED = "subagent.ended"
# Phase 2 (decision 0025 §6.4): pause/resume lifecycle events. Emitted
# by the API layer around POST /api/runs/{id}/pause + /resume. The SPA
# uses these to flip PauseButton labels and to clear the ``remaining_s``
# countdown (it stops ticking once the run is paused).
EVT_RUN_PAUSED = "run.paused"
EVT_RUN_RESUMED = "run.resumed"


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


def _resolve_run_retention_s(override=None):
    """Phase 7 (decision 0042): resolve the finished-run retention window.

    ``override`` (``RunManager(retention_s=...)``) wins; otherwise
    ``SMOLCODE_RUN_RETENTION_S``; otherwise 24 h. ``<= 0`` disables
    eviction. A malformed env value logs and falls back to the default
    instead of disabling retention silently.
    """
    if override is not None:
        try:
            return float(override)
        except (TypeError, ValueError):
            _log.warning("invalid RunManager retention_s=%r; using default", override)
            return _DEFAULT_RUN_RETENTION_S
    raw = os.environ.get(_RUN_RETENTION_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_RUN_RETENTION_S
    try:
        return float(raw)
    except ValueError:
        _log.warning("invalid %s=%r; using default", _RUN_RETENTION_ENV, raw)
        return _DEFAULT_RUN_RETENTION_S


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


@dataclass
class SubAgentSummary:
    """Phase 0 §14.8 #3 fold-in: a single sub-agent invocation record.

    The orchestrator's ``do_<tier>_task`` / ``do_specialist`` tools
    append one of these on every delegation and mutate ``ended_at`` on
    completion. ``Run.subagent_history`` is a list of these.

    Decision 0028: ``tokens_in`` / ``tokens_out`` accumulate the LLM
    tokens that were attributed to THIS sub-agent invocation by
    ``Run.publish`` while the sub-agent was active. The active
    sub-agent id is tracked on ``Run`` so concurrent ``step.action``
    publishes can route their tokens to the right entry. Cost is
    derived at read time in ``Run.summary_dict`` via
    ``cost_for()`` using the OUTER run's provider/model (sub-agents
    inherit); not stored here to keep the dataclass lean and to
    avoid threading ``Settings`` through every mutation.
    """

    id: str
    tier: str
    started_at: float
    ended_at: float | None = None
    specialist: str | None = None
    # Decision 0028: per-sub-agent LLM token attribution. Updated
    # under ``Run.pending_lock`` whenever a ``step.action`` event is
    # published while this sub-agent is the active one.
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class QueueEntry:
    """Phase 2 (decision 0025 §6.4): one queued-run record.

    Held by ``RunManager._queue`` (a FIFO list protected by
    ``_queue_lock``). When the active run ends, ``RunManager.drain_queue``
    pops the first entry and starts the runner thread.
    """

    id: str
    task: str
    tier: str
    queued_at: float = field(default_factory=time.monotonic)
    project: str | None = None
    session_id: str | None = None
    provider_override: str | None = None
    model_override: str | None = None
    api_key_value: str | None = None
    # Phase 3 F3 (decision 0036): per-run anchor toggle (Q1). The
    # field is forwarded through the queue so the drained run
    # resolves effective_cwd the same way an immediate start_run
    # would. Default False keeps the legacy behaviour.
    anchor_to_project_root: bool = False


STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_STOPPED = "stopped"
# Phase 2 (decision 0025 §6.4): paused is NOT terminal — a paused run is
# resumable via POST /api/runs/{id}/resume. _TERMINAL_STATUSES deliberately
# excludes STATUS_PAUSED so the SSE subscriber's terminal-status check
# does not close the stream when the run pauses mid-flight.
STATUS_PAUSED = "paused"
# Phase 2 (decision 0025 §6.4): a queued run is awaiting a slot in the
# RunManager queue; the runner thread is NOT started until the run is
# dequeued. Status remains "queued" until then; the SPA shows the entry
# in <QueuePane>.
STATUS_QUEUED = "queued"

_TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_ERROR, STATUS_STOPPED})
# Phase 7 (decision 0042): statuses that occupy the single execution slot.
# Mirrors ``RunManager.is_busy`` so the queue drain's slot check and the
# submit-time check agree.
_ACTIVE_STATUSES = frozenset({STATUS_RUNNING, STATUS_AWAITING_APPROVAL, STATUS_PAUSED})

# Phase 7 (decision 0042): private in-band sentinel enqueued by
# ``Run.end_stream()`` after the terminal frame. ``RunManager.subscribe``
# breaks on it (identity check) instead of polling ``run.status``, so a
# subscriber that observes ``status=done`` before the runner published
# ``run.ended`` can no longer drop that terminal frame. A plain unique
# string (identity-checked, never yielded) keeps the queue's contents
# string-safe for helpers that drain ``run.events`` directly.
_STREAM_END = "__smolcode_stream_end__"

# Phase 7 (decision 0042): finished-run retention. The manager sweeps
# terminal runs older than this window on the submit path and zeroes their
# ``api_key_value``. <= 0 disables the sweep. Overridable per-manager
# (``RunManager(retention_s=...)``) or via the environment -- deliberately
# NOT a ``Settings`` field: this is a manager-lifetime knob, and Phase 8
# owns ``config.py`` in this work stream.
_DEFAULT_RUN_RETENTION_S = 86400.0
_RUN_RETENTION_ENV = "SMOLCODE_RUN_RETENTION_S"


@dataclass
class Run:
    id: str
    task: str
    tier: str
    status: str = STATUS_PENDING
    events: queue.Queue = field(default_factory=queue.Queue)
    # Phase 3 (decision 0025 sec 6.5 / B5 export): read-only event log.
    # publish() appends here IN ADDITION to putting on the queue, so a
    # snapshot can read the full event history without consuming the
    # live queue (subscribers would otherwise miss events).
    events_log: list = field(default_factory=list)
    pending: list = field(default_factory=list)
    pending_lock: threading.Lock = field(default_factory=threading.Lock)
    stop_flag: threading.Event = field(default_factory=threading.Event)
    # Phase 7 (decision 0042): set by ``end_stream()`` once the runner has
    # published its terminal frame. ``RunManager.subscribe`` uses it to
    # decide when the event stream is genuinely finished, instead of
    # guessing from ``status`` (which the runner sets before publishing
    # ``run.ended``).
    stream_finished: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    result: str | None = None
    error: str | None = None
    # Phase 3 F1 (decision 0036): ``started_at`` is stamped with the
    # wall clock so the dashboard's last-24h filter (Unix epoch)
    # and the run-start event share the same clock domain. The
    # internal ``started_mono`` below remains monotonic and is the
    # anchor for ``remaining_s()`` + the audit sink's duration so
    # NTP / wall-clock jumps mid-run cannot corrupt the countdown.
    started_at: float = field(default_factory=time.time)
    started_mono: float = field(default_factory=time.monotonic)
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
    # Phase 0 (decision 0025): per-run token + step aggregates. Updated
    # in-place by ``increment_tokens`` under ``pending_lock`` so the
    # Inspector's "Token usage" section is consistent under heavy
    # concurrent step.callback traffic. ``step_count`` is bumped for
    # EVERY ``step.action`` event (regardless of whether it carries
    # tokens) so the FE has a true step counter.
    tokens_in: int = 0
    tokens_out: int = 0
    step_count: int = 0
    # Phase 2 (decision 0025 §6.4): pause flag. The step callback
    # checks this AFTER publishing each step.action and raises
    # ``_PauseRequested`` when set; the runner catches it and flips the
    # status to STATUS_PAUSED + emits ``run.paused``. Resume calls
    # ``clear()`` + emits ``run.resumed`` then resumes the agent thread.
    pause_flag: threading.Event = field(default_factory=threading.Event)
    # Phase 2 (decision 0025 §6.4): snapshot location + timestamp. The
    # agent_runner calls ``run.snapshot(agent)`` AFTER each successful
    # ``step.action`` publish (under pending_lock) so a paused run can
    # be resumed by re-instantiating the agent and replaying the
    # memory. ``snapshot_at`` is the captured wall-clock epoch seconds
    # (``time.time()``) at the moment of the snapshot, or None
    # if no snapshot has been taken yet.
    snapshot_path: Path | None = None
    snapshot_at: float | None = None
    snapshot_lock: threading.Lock = field(default_factory=threading.Lock)
    # Phase 0 §14.8 #3 fold-in (decision 0025 §6.4): track ALL
    # sub-agent invocations, not just the latest one. The orchestrator's
    # ``do_<tier>_task`` / ``do_specialist`` tools call
    # ``append_subagent`` on start and ``close_subagent`` on end. The
    # legacy ``run.subagent`` property still returns the latest entry
    # for backward compatibility with Phase 0 FE consumers.
    subagent_history: list = field(default_factory=list)
    # Decision 0028: id of the currently-active sub-agent (set by
    # ``append_subagent``, cleared by ``close_subagent``). Used by
    # ``publish()`` to attribute ``step.action`` tokens to the
    # right entry. ``None`` when no sub-agent is active (the
    # orchestrator's own steps, or no orchestrator at all).
    active_subagent_id: str | None = None
    # Phase 1 (decision 0025 §6.3): chat-session id + project name the
    # run is attached to. Both None for legacy / standalone runs.
    # Surfaced in RunSummary + run.started event payload; the SPA's
    # SessionsPane filters / highlights by these.
    session_id: str | None = None
    project: str | None = None
    # Phase 2 (decision 0025 §6.4): FIFO queue position (1-based) when
    # the run is waiting in the RunManager queue. None for active or
    # terminal runs. Surfaced in RunSummary.queue_position + the SPA's
    # <QueuePane>.
    queue_position: int | None = None
    # Phase 3 F3 (decision 0036): the resolved working directory for
    # write_file / patch_file. Defaults to None = legacy mode (anchored
    # to settings.workspace via ``workspace``). Set by RunManager.start_run
    # / start_or_enqueue_run to the project root when the user toggled
    # ``anchor_to_project_root=True`` on the composer (per Q1 policy the
    # per-run default is False; the toggle is opt-in). Surfaced in the
    # Inspector "Working root" row so the user can confirm where files
    # actually land + click [Open] to launch the OS file explorer at
    # that path. NEVER updated after Run construction -- effective_cwd
    # is a run-start-time snapshot.
    effective_cwd: Path | None = None
    # Phase 3 F3 (decision 0036): the per-run anchor toggle. Default
    # False per Q1 (anchor mode is opt-in). When True AND project is
    # set AND a matching Project root exists, the runner writes to
    # that root; writes that escape it hit the Q2 outside-root gate
    # (full-path modal + per-session per-path allowlist). When False
    # the runner keeps the legacy behaviour (writes anchored to
    # settings.workspace via Run.workspace).
    anchor_to_project_root: bool = False
    # Phase 4 (decision 0039, review R3/H7): retry / rerun lineage. These were
    # being passed by the API layer to start_or_enqueue_run, which did not
    # accept them -> TypeError -> HTTP 500 on both endpoints. They are real
    # fields now, persisted at construction and surfaced in summary_dict +
    # the run.started event. ``retry_count`` counts how many retries this
    # run has spawned (the ADR increments it on the PARENT).
    parent_retry_of: str | None = None
    parent_rerun_of: str | None = None
    retry_count: int = 0
    # Phase 4 (decision 0039): private, never serialised. ``resume_active_agent``
    # only receives the Run, so this is how it reaches the cost-cap tracker.
    # Before this, resume passed None and pausing a run was a way to bypass
    # per-step cap enforcement for the rest of that run.
    _cost_cap_tracker: Any = None

    @property
    def tokens(self):
        """TokenSummary-shaped view of this run's cumulative usage.

        Phase 4 (decision 0039, review R4): the cost-cap check
        (_check_cost_cap_or_raise), the dashboard, and the per-step cap guard
        all read ``run.tokens``, but ``Run`` only ever had tokens_in /
        tokens_out -- so every one of those reads silently took the
        ``getattr(run, 'tokens', None) is None`` branch and the dashboard
        always reported $0. A property gives one definition of "this run's
        tokens" and keeps every existing call site working.
        """
        from .schemas import TokenSummary

        return TokenSummary(
            input=self.tokens_in,
            output=self.tokens_out,
            total=self.tokens_in + self.tokens_out,
        )

    def record_touch(self, rel_path):
        if not isinstance(rel_path, str) or not rel_path:
            return
        with self.touched_lock:
            self.touched_paths.add(rel_path)

    def touched_list(self):
        with self.touched_lock:
            return sorted(self.touched_paths)

    def publish(self, event_type, data):
        # Phase 0 (decision 0025): auto-aggregate token + step counts on
        # every step.action event BEFORE the frame is enqueued.
        # Idempotent under the existing pending_lock so concurrent
        # publishes from the agent runner thread + step callbacks never
        # lose increments.
        if event_type == EVT_STEP_ACTION and isinstance(data, dict):
            tokens = data.get("tokens")
            with self.pending_lock:
                self.step_count += 1
                if isinstance(tokens, dict):
                    try:
                        inp = int(tokens.get("input", 0) or 0)
                        out = int(tokens.get("output", 0) or 0)
                    except (TypeError, ValueError):
                        inp = 0
                        out = 0
                    # Decision 0028: when a sub-agent is active,
                    # ALSO attribute the tokens to that sub-agent's
                    # accumulator so the per-sub-agent cost view can
                    # be derived in ``summary_dict``. The outer
                    # ``tokens_in``/``tokens_out`` continue to
                    # receive EVERY token (own + sub-agents) so the
                    # run-level Dashboard cost math is unchanged.
                    # Concurrency: ``pending_lock`` covers both
                    # the outer accumulators and the sub-agent entry
                    # mutation, so concurrent ``step.action``
                    # publishes from the orchestrator thread + the
                    # inner sub-agent thread are consistent.
                    if self.active_subagent_id:
                        for s in self.subagent_history:
                            if s.id == self.active_subagent_id:
                                s.tokens_in += inp
                                s.tokens_out += out
                                break
                    self.tokens_in += inp
                    self.tokens_out += out
        frame = _encode_event(event_type, data, event_id=self._next_event_id())
        # Phase 3 (decision 0025 sec 6.5 / B5 export): append to the read-only log.
        with self.pending_lock:
            self.events_log.append(frame)
            if len(self.events_log) > 5000:
                del self.events_log[:1000]
        try:
            self.events.put_nowait(frame)
        except Exception as e:
            _log.warning("run %s: event put failed: %s", self.id, e)

    def end_stream(self):
        """Terminate any live SSE subscriber deterministically.

        Phase 7 (decision 0042): the runner sets ``status`` to a terminal
        value BEFORE publishing ``EVT_RUN_ENDED`` (the audit-sink ``end()``
        write sits between them). ``RunManager.subscribe`` used to break as
        soon as it saw "terminal status + empty queue", which under load
        interleaved exactly in that window and dropped ``run.ended``.
        Enqueuing a private sentinel AFTER the terminal frame removes the
        ordering dependence: the subscriber exits only once it has drained
        everything the runner produced. Idempotent.
        """
        with self.pending_lock:
            if self.stream_finished.is_set():
                return
            self.stream_finished.set()
        try:
            self.events.put_nowait(_STREAM_END)
        except Exception as e:
            _log.warning("run %s: stream-end sentinel put failed: %s", self.id, e)

    def increment_tokens(self, input_delta, output_delta):
        """Add input_delta + output_delta to the running totals.

        Public entry point for callers that already know the delta and
        want to avoid the step.action event round-trip. Idempotent
        under pending_lock.
        """
        try:
            inp = int(input_delta or 0)
            out = int(output_delta or 0)
        except (TypeError, ValueError):
            return
        with self.pending_lock:
            self.tokens_in += inp
            self.tokens_out += out

    def remaining_s(self, max_wall_s):
        """Seconds remaining until max_wall_s elapses since start.

        Returns a float (may be negative when the run has overrun the
        wall-clock budget). Returns None when max_wall_s <= 0
        (timeout disabled) or the run has not started yet. The SPA
        ticks this down once per second from summary_dict().
        """
        try:
            budget = float(max_wall_s)
        except (TypeError, ValueError):
            return None
        if budget <= 0:
            return None
        return budget - (time.monotonic() - self.started_mono)

    def summary_dict(self, max_wall_s=None):
        """Snapshot the fields the FE renders in the Inspector.

        Token / step counts are read under pending_lock so the
        snapshot is consistent even mid-publish. remaining_s is
        computed against the supplied max_wall_s budget (passed
        in by the API layer so this module does not need to import
        the agent_runner timeout constant).

        Phase 2 (decision 0025 §6.4) additions to the snapshot:
        - ``subagent_history``: every sub-agent invocation the
          orchestrator has delegated to (Phase 0 §14.8 #3 fold-in).
        - ``snapshot_at``: epoch seconds of the most recent
          agent-memory snapshot, or None.
        - ``queue_position``: 1-based FIFO position when the run is
          queued, else None.
        """
        with self.pending_lock:
            total = self.tokens_in + self.tokens_out
            # Decision 0028: compute per-sub-agent USD cost at read
            # time. Uses the OUTER run's provider/model (sub-agents
            # inherit the orchestrator's settings; if a future
            # variant overrides per-sub-agent, this is the surface
            # to extend). Default rates only -- settings plumbing
            # to the runner is deferred until the override is
            # surfaced through Settings.cost_rates.
            subagent_history = [
                {
                    "id": s.id,
                    "tier": s.tier,
                    "specialist": getattr(s, "specialist", None),
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "tokens_in": s.tokens_in,
                    "tokens_out": s.tokens_out,
                    "cost_usd": round(
                        cost_for(
                            self.provider or None,
                            self.model or None,
                            s.tokens_in,
                            s.tokens_out,
                        ),
                        6,
                    )
                    if (s.tokens_in or s.tokens_out)
                    else 0.0,
                }
                for s in self.subagent_history
            ]
            snap = {
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "tokens_total": total,
                "step_count": self.step_count,
                "subagent_history": subagent_history,
                "snapshot_at": self.snapshot_at,
                "queue_position": self.queue_position,
            }
            # Legacy Phase 0 single-subagent accessor (kept so older
            # SPA Inspector hints continue to work; new clients read
            # ``subagent_history[-1]`` instead).
            snap["subagent"] = snap["subagent_history"][-1] if snap["subagent_history"] else None
        if max_wall_s is not None:
            snap["remaining_s"] = self.remaining_s(max_wall_s)
        return snap

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

    # Phase 2 (decision 0025 §6.4): sub-agent history accessors
    # (Phase 0 §14.8 #3 fold-in). Append on start, mutate on end.
    def append_subagent(self, sub_id, *, tier, specialist=None, started_at=None):
        """Record a new sub-agent invocation. Idempotent on duplicate ids.

        Called by the orchestrator's ``do_<tier>_task`` /
        ``do_specialist`` tools around their inner ``agent.run()``.
        Thread-safe under pending_lock.
        """
        entry = SubAgentSummary(
            id=str(sub_id),
            tier=str(tier or ""),
            started_at=float(started_at) if started_at is not None else time.time(),
            ended_at=None,
            specialist=str(specialist) if specialist else None,
        )
        with self.pending_lock:
            # Don't append if this sub-id is already tracked (defensive).
            if any(s.id == entry.id for s in self.subagent_history):
                return entry
            self.subagent_history.append(entry)
            # Decision 0028: this sub-agent is now active; subsequent
            # ``step.action`` publishes will attribute their tokens
            # to it. ``close_subagent`` clears the active id.
            self.active_subagent_id = entry.id
        return entry

    def close_subagent(self, sub_id, *, ended_at=None):
        """Mark a sub-agent invocation as closed. Defensive: missing id is a no-op.

        Decision 0028: also clears ``active_subagent_id`` if it
        matches the closing sub-agent so subsequent ``step.action``
        publishes attribute their tokens to the outer run again. A
        nested sub-agent start that happens before close would have
        already overwritten ``active_subagent_id``, so we only
        clear when the id still matches -- this preserves correct
        attribution across nested invocations.
        """
        ended = float(ended_at) if ended_at is not None else time.time()
        with self.pending_lock:
            for s in self.subagent_history:
                if s.id == sub_id:
                    s.ended_at = ended
                    if self.active_subagent_id == sub_id:
                        self.active_subagent_id = None
                    return True
        return False

    @property
    def subagent(self):
        """Legacy Phase 0 accessor: return the most recent sub-agent entry, or None."""
        return self.subagent_history[-1] if self.subagent_history else None

    # Phase 2 (decision 0025 §6.4): snapshot helpers. The runner
    # calls ``snapshot(agent, path)`` after each successful
    # ``step.action`` publish. ``load_snapshot`` returns the parsed
    # dict so ``_resume_agent_from_snapshot`` can rebuild the
    # ``agent.memory.steps`` list.
    def snapshot(self, agent, *, path=None):
        """Capture the agent's memory to ``path`` (defaults to a temp file).

        Returns the Path the snapshot was written to. The Run's
        ``snapshot_path`` + ``snapshot_at`` are updated under
        ``snapshot_lock`` so the Inspector can show the timestamp.
        The agent parameter is duck-typed (``agent.memory`` with
        ``system_prompt`` + ``steps``); no smolagents import here.
        """
        import json as _json

        mem = getattr(agent, "memory", None)
        if mem is None:
            raise ValueError("agent has no .memory attribute")
        system_prompt = getattr(mem, "system_prompt", None)
        steps = getattr(mem, "steps", None) or []

        # Serialize each step via its ``.dict()`` method + a discriminator.
        out_steps = []
        for step in steps:
            kind = type(step).__name__
            if kind == "SystemPromptStep":
                payload = {"system_prompt": getattr(step, "system_prompt", "")}
            else:
                try:
                    payload = step.dict()
                except Exception:
                    # Best-effort: keep the type + any string-coercible fields.
                    payload = {
                        str(k): (getattr(step, k, None) if not callable(getattr(step, k, None)) else None)
                        for k in (
                            "step_number",
                            "model_output",
                            "observations",
                            "code_action",
                            "tool_calls",
                        )
                    }
            out_steps.append({"step_type": kind, **payload})

        data = {
            "system_prompt": getattr(system_prompt, "system_prompt", system_prompt),
            "steps": out_steps,
            "captured_at": time.time(),
            "run_id": self.id,
        }
        if path is None:
            import tempfile as _tempfile

            tmp = _tempfile.NamedTemporaryFile(prefix=f"smolcode-snap-{self.id[:8]}-", suffix=".json", delete=False)
            tmp.close()
            path = Path(tmp.name)
        else:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically: tmp + os.replace. Phase 2: remove the .tmp
        # sidecar on failure so a crashed write does not leak files
        # next to the caller-owned path either.
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp_path.write_text(
                _json.dumps(data, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            os.replace(tmp_path, path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        with self.snapshot_lock:
            self.snapshot_path = path
            self.snapshot_at = time.time()
        return path

    def load_snapshot(self, path):
        """Read a snapshot file and return the parsed dict.

        The returned dict has the shape ``{system_prompt, steps, captured_at, run_id}``
        ready for ``_resume_agent_from_snapshot`` to walk.
        """
        import json as _json

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return _json.loads(path.read_text(encoding="utf-8"))

    def cleanup_temp_snapshot(self):
        """Phase 2: delete the auto-created smolcode-snap-* temp file.

        ``snapshot(path=None)`` materialises agent memory in a
        ``NamedTemporaryFile(delete=False)`` so a PAUSED run can be
        resumed later. Once the run reaches a TERMINAL status that
        file can never be read again -- but nothing deleted it, so
        every web run leaked one temp JSON (with the full transcript)
        into the system temp dir. Called from the runner finally block
        after the terminal event publish. Snapshots written to an
        EXPLICIT caller-supplied path are not ours to delete; only
        the ``smolcode-snap-*`` prefix is removed. Returns True when
        a file was deleted.
        """
        with self.snapshot_lock:
            p = self.snapshot_path
        if p is None:
            return False
        try:
            name = Path(p).name
        except Exception:
            return False
        if not name.startswith("smolcode-snap-"):
            return False
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            return False
        with self.snapshot_lock:
            self.snapshot_path = None
        return True


class RunManager:
    def __init__(self, cost_cap_tracker=None, audit_sink=None, settings=None, retention_s=None):
        # Decision 0032: optional cap tracker. When set, ``start_run`` /
        # ``start_or_enqueue_run`` consults ``tracker.check_reached``
        # against today's per-provider USD spend BEFORE spinning up the
        # runner thread. ``None`` is allowed so existing call sites (and
        # legacy tests) keep working -- it just disables enforcement.
        self._cost_cap_tracker = cost_cap_tracker
        # Phase 2 (H5): optional manager-default audit sink. create_app
        # builds ONE AuditSink per server process and hands it here;
        # any run started WITHOUT an explicit ``audit=`` argument
        # (retry, rerun, queue drain, legacy call sites) then inherits
        # it instead of silently skipping the audit trail. An explicit
        # per-call sink always wins.
        self._audit_sink = audit_sink
        # Phase 4 (decision 0039): the manager owns its Settings instance.
        # The queue drain used to reach back through REQUEST-scoped FastAPI
        # dependencies (api.get_run_manager / deps.get_settings) from the
        # runner thread, long after the request had been torn down -- which is
        # why the queue silently never drained (the resulting TypeError was
        # swallowed by a bare except + log.warning). Holding the settings here
        # makes the drain self-contained.
        self._settings = settings
        # Last queue-drain failure, surfaced by GET /api/health (Phase 8 adds
        # it to the response schema). The manager-side capture lands here so
        # the failure is recorded rather than lost.
        self.queue_drain_error: str | None = None
        self._runs = {}
        self._lock = threading.Lock()
        # Phase 7 (decision 0042): one re-entrant "dispatch" lock serialises
        # the busy-check + slot claim (start_run) and the drain claim
        # (queue -> running). Without it, two concurrent submits could both
        # observe "not busy" and start; and a submit that slipped in after a
        # finishing run's status flipped terminal could race the drain and
        # start a second run alongside the queued one. Re-entrant because
        # start_or_enqueue_run calls start_run while holding it.
        self._dispatch_lock = threading.RLock()
        # Phase 2 (decision 0025 §6.4): FIFO queue + its lock. Previously added
        # by a module-level monkey-patch of __init__; folded in here (decision
        # 0039) so the real class is the single definition.
        self._queue = []
        self._queue_lock = threading.Lock()
        # Phase 7 (decision 0042): finished-run retention window (seconds).
        # <= 0 disables the opportunistic sweep.
        self._run_retention_s = _resolve_run_retention_s(retention_s)

    def _effective_audit(self, audit):
        """Phase 2 (H5): per-call sink wins; else the manager default."""
        return audit if audit is not None else getattr(self, "_audit_sink", None)

    def _check_cost_cap_or_raise(self, settings, provider_override):
        """Decision 0032: per-day USD cap enforcement at run-start.

        Computes today's USD spend for the effective provider via
        ``compute_dashboard`` (using a stub audit sink so the call
        does not require a real audit reader), then asks the
        ``CostCapTracker`` whether the per-provider cap has been
        reached. On reached -> raise ``ValueError`` with the
        ``cost_cap_reached:`` prefix; the API layer maps this prefix
        to HTTP 429. When the tracker is missing or the effective
        provider has no cap set, this is a silent no-op.

        We use a fresh dashboard compute (rather than caching today
        totals) so the cap reflects ``up to this instant`` -- a
        concurrent in-flight run may have spent more since the last
        GET /api/dashboard. The compute is cheap (sums today's
        runs in-memory) and runs BEFORE any queueing / thread spin-up.
        """
        tracker = self._cost_cap_tracker
        if tracker is None:
            return
        base_provider = getattr(settings, "provider", "") or ""
        effective_provider = provider_override or base_provider
        if not effective_provider:
            return
        if tracker.get_cap(effective_provider) <= 0:
            return
        # Late import: ``compute_dashboard`` pulls in model_catalog +
        # dataclasses; we want the cheap cap check on the hot path
        # to stay import-light when no cap is set (the get_cap() call
        # above already early-returned in that case).
        from .dashboard import compute_dashboard

        class _StubAudit:
            """Minimal audit stand-in: never counts anything.

            ``compute_dashboard`` only reads ``count_since`` so a stub
            returning 0 is sufficient. We avoid constructing a real
            AuditSink because the run-start check runs on the API
            request thread, before any runner thread is alive.
            """

            def count_since(self, _since_ts, level=None):
                return 0

        try:
            dashboard = compute_dashboard(self, _StubAudit(), settings)
            today_usd = dashboard.by_provider.get(effective_provider)
            today_usd = today_usd.cost_usd if today_usd is not None else 0.0
        except Exception:
            # Dashboard failure (no settings, broken run history, ...)
            # must NOT wedge a run-start. Fall through silently so the
            # caller can still start the run; the per-step check will
            # enforce the cap on the next action.
            return
        reached, reason = tracker.check_reached(effective_provider, today_usd)
        if reached:
            raise ValueError("cost_cap_reached: " + reason)

    def _build_run(
        self,
        *,
        task,
        tier,
        settings,
        audit=None,
        provider_override=None,
        model_override=None,
        api_key_value=None,
        session_id=None,
        project=None,
        anchor_to_project_root=False,
        parent_retry_of=None,
        parent_rerun_of=None,
        status=STATUS_PENDING,
    ):
        """Validate one run request and build its (unregistered) ``Run``.

        Phase 7 (decision 0042): shared by ``start_run`` and the enqueue
        branch of ``start_or_enqueue_run``. Building the record is pure --
        no lock held, no shared state mutated -- so callers can validate
        before taking ``_dispatch_lock`` and the critical section stays
        short. Registration/status/slot claiming is the caller's job.
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

        # Phase 1: validate project against configured list; coerce
        # unknown to None so legacy mode is the safe default.
        effective_project = None
        if project is not None:
            for p in getattr(settings, "projects", ()):
                if p.name == project:
                    effective_project = p.name
                    break

        # Phase 1: validate session_id (safe chars only; no traversal).
        from ..session import safe_id

        effective_session_id = None
        if session_id is not None:
            try:
                effective_session_id = safe_id(session_id)
            except ValueError:
                effective_session_id = None

        # Phase 3 F3 (decision 0036, Q1): resolve effective_cwd from
        # (anchor_to_project_root AND project AND matching_project_root)
        # ? Path(matching_project_root) : Path(settings.workspace).
        # Anchoring without a matching project is a silent no-op (the
        # SPA renders the "files landed in workspace, not project"
        # notice).
        effective_cwd: Path | None = None
        if bool(anchor_to_project_root) and effective_project:
            from ..session import resolve_project_root

            try:
                effective_cwd = resolve_project_root(settings, effective_project)
                ws_root = Path(str(getattr(settings, "workspace", "") or ""))
                if effective_cwd == ws_root:
                    # resolve_project_root returns the workspace
                    # fallback for projects whose root matches it;
                    # treat as legacy mode so the Inspector does
                    # not show a misleading "Working root" row.
                    effective_cwd = None
            except Exception:
                effective_cwd = None
        if effective_cwd is None:
            ws = getattr(settings, "workspace", "") or ""
            effective_cwd = Path(ws) if ws else None

        run = Run(
            id=uuid.uuid4().hex,
            task=task.strip(),
            tier=tier,
            audit_sink=self._effective_audit(audit),
            model=effective_model,
            provider=effective_provider,
            workspace=str(getattr(settings, "workspace", "") or ""),
            provider_override=provider_override,
            model_override=model_override,
            api_key_value=ak,
            session_id=effective_session_id,
            project=effective_project,
            effective_cwd=effective_cwd,
            anchor_to_project_root=bool(anchor_to_project_root),
            parent_retry_of=parent_retry_of,
            parent_rerun_of=parent_rerun_of,
            # Phase 4 (decision 0039): the resume path needs the tracker and
            # resume_active_agent only has the Run to hand. Private (never
            # serialised) so a resumed run keeps per-step cap enforcement
            # instead of silently losing it on resume.
            _cost_cap_tracker=self._cost_cap_tracker,
        )
        run.status = status
        return run

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
        session_id=None,
        project=None,
        anchor_to_project_root=False,
        parent_retry_of=None,
        parent_rerun_of=None,
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

        Phase 1 (decision 0025 §6.3): ``session_id`` + ``project``
        are optional; when supplied they tag the run so the SPA's
        SessionsPane can filter history. ``project`` is resolved
        against ``settings.projects`` -- an unknown name is silently
        coerced to None (legacy mode) so a stale ``?project=foo``
        from a previous config doesn't hard-fail new runs.
        """
        run = self._build_run(
            task=task,
            tier=tier,
            settings=settings,
            audit=audit,
            provider_override=provider_override,
            model_override=model_override,
            api_key_value=api_key_value,
            session_id=session_id,
            project=project,
            anchor_to_project_root=anchor_to_project_root,
            parent_retry_of=parent_retry_of,
            parent_rerun_of=parent_rerun_of,
        )
        with self._dispatch_lock:
            # Phase 7 (decision 0042): sweep finished runs on the submit path.
            # A sweep failure must never block a new run.
            try:
                self.evict_finished_runs()
            except Exception as e:
                _log.warning("run retention sweep failed: %s", e)
            # Claim the slot BEFORE the runner thread exists: registering the
            # run as "running" under the dispatch lock means a concurrent
            # start_or_enqueue_run cannot observe this run as pending and
            # start a second one. ``run_in_thread`` re-asserts the status.
            run.status = STATUS_RUNNING
            # Phase 7 (decision 0042): slot-claim timestamp used by
            # ``_claim_next_queued`` to detect a submit that slipped in
            # between a finishing run's terminal status and its drain.
            run._registered_at = time.time()
            with self._lock:
                self._runs[run.id] = run
            from .agent_runner import run_in_thread

            run.thread = threading.Thread(
                target=run_in_thread,
                args=(run, settings, self),
                name="smolcode-run-" + run.id[:8],
                daemon=True,
                kwargs={"cost_cap_tracker": self._cost_cap_tracker},
            )
            run.thread.start()
        return run.id

    def start_or_enqueue_run(
        self,
        *,
        task,
        tier,
        settings,
        audit=None,
        provider_override=None,
        model_override=None,
        api_key_value=None,
        session_id=None,
        project=None,
        anchor_to_project_root=False,
        parent_retry_of=None,
        parent_rerun_of=None,
    ):
        """Phase 2 (decision 0025 §6.4): same as ``start_run`` but
        auto-enqueues when a run is already active. Returns
        ``(run_id, status)`` where ``status`` is ``"running"`` when
        the thread started immediately or ``"queued"`` when added to
        the FIFO queue.

        Decision 0032: a per-day cap check runs FIRST (before the
        queue-vs-immediate branching). When the effective provider's
        today-spent USD is at or above its cap, raise ``ValueError``
        with the ``cost_cap_reached:`` prefix so the API layer can map
        it to HTTP 429. Empty caps + missing tracker are no-ops.
        """
        # Decision 0032: per-day cap enforcement. Run BEFORE any
        # queue / threading setup so a cap rejection never allocates a
        # Run id or wakes the runner thread.
        self._check_cost_cap_or_raise(settings, provider_override)
        # Phase 7 (decision 0042): the busy test and the slot claim are ONE
        # critical section. Previously the check and the registration ran
        # under separate locks, so two concurrent submits could both see an
        # idle manager and start two runs. ``_dispatch_lock`` is re-entrant,
        # so the immediate path below can call ``start_run`` (which takes the
        # same lock) without deadlocking.
        with self._dispatch_lock:
            if self.is_busy():
                run = self._build_run(
                    task=task,
                    tier=tier,
                    settings=settings,
                    audit=audit,
                    provider_override=provider_override,
                    model_override=model_override,
                    api_key_value=api_key_value,
                    session_id=session_id,
                    project=project,
                    anchor_to_project_root=anchor_to_project_root,
                    parent_retry_of=parent_retry_of,
                    parent_rerun_of=parent_rerun_of,
                    status=STATUS_QUEUED,
                )
                try:
                    self.evict_finished_runs()
                except Exception as e:
                    _log.warning("run retention sweep failed: %s", e)
                run._registered_at = time.time()
                with self._lock:
                    self._runs[run.id] = run
                self.enqueue(
                    run.id,
                    task=run.task,
                    tier=run.tier,
                    project=run.project,
                    session_id=run.session_id,
                    provider_override=run.provider_override,
                    model_override=run.model_override,
                    api_key_value=run.api_key_value,
                    # Phase 4 (decision 0039): the entry mirrors the original call so
                    # the drained run resolves effective_cwd the same way an
                    # immediate start_run would. QueueEntry already has the field;
                    # nothing was ever passing it.
                    anchor_to_project_root=run.anchor_to_project_root,
                )
                return run.id, STATUS_QUEUED
            run_id = self.start_run(
                task=task,
                tier=tier,
                settings=settings,
                audit=audit,
                provider_override=provider_override,
                model_override=model_override,
                api_key_value=api_key_value,
                session_id=session_id,
                project=project,
                anchor_to_project_root=anchor_to_project_root,
                parent_retry_of=parent_retry_of,
                parent_rerun_of=parent_rerun_of,
            )
            return run_id, STATUS_RUNNING

    def get(self, run_id):
        with self._lock:
            return self._runs.get(run_id)

    def list(self):
        with self._lock:
            return list(self._runs.values())

    def list_all_runs(self):
        """Phase 3 (decision 0025 sec 6.5): alias for .list() (dashboard aggregator interface)."""
        with self._lock:
            return list(self._runs.values())

    @staticmethod
    def _stream_is_done(run):
        """True when no further frames can arrive for ``run``.

        Phase 7 (decision 0042): the producer marks the stream finished
        explicitly (``Run.end_stream``). The ``ended_at is None`` fallback
        keeps the legacy contract for tests and direct ``publish`` callers
        that flip ``status`` terminal without a runner (no producer will
        ever enqueue a sentinel for those).
        """
        if run.stream_finished.is_set():
            return True
        return run.status in _TERMINAL_STATUSES and run.ended_at is None

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
                if run.events.empty() and self._stream_is_done(run):
                    break
                continue
            if frame is _STREAM_END:
                break
            yield frame
            if run.events.empty() and self._stream_is_done(run):
                break
        yield _encode_event("end", {"run_id": run.id, "status": run.status}, event_id=None)

    def events_snapshot(self, run_id, *, max_events=2000):
        """Phase 3 (decision 0025 sec 6.5 / B5 export): non-destructive snapshot of the event log."""
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        out = []
        for frame in list(run.events_log)[-max_events:]:
            data_line = None
            event_type = None
            for line in frame.splitlines():
                if line.startswith("event: "):
                    event_type = line[len("event: ") :]
                elif line.startswith("data: "):
                    data_line = line[len("data: ") :]
            if data_line:
                try:
                    payload = json.loads(data_line)
                except (ValueError, TypeError):
                    payload = {"_raw": data_line}
                if event_type:
                    payload.setdefault("type", event_type)
                out.append(payload)
            else:
                out.append({"_raw": frame})
        return out

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
        """Stop a run, resolving any human-approval wait as DENIED.

        Phase 7 (decision 0042): setting ``stop_flag`` alone only stops the
        agent at its next step boundary. A run blocked inside
        ``confirm_callback`` / ``diff_callback`` is parked in
        ``PendingDecision.event.wait(timeout_s)`` and would not notice the
        flag until the human-decision timeout (default 300 s). Resolve every
        pending decision fail-closed (DENIED, reason "stopped") so the agent
        thread wakes immediately and takes its existing ``_StopRequested``
        path. ``PendingDecision.resolve`` is idempotent and ``take_decision``
        claims atomically, so a concurrent ``POST /approval`` cannot both
        resolve and observe the same decision.
        """
        run = self.get(run_id)
        if run is None:
            return False
        run.stop_flag.set()
        with run.pending_lock:
            pending = list(run.pending)
            run.pending.clear()
        for d in pending:
            d.resolve(approved=False, edited_args=None, reason="stopped")
            if d.kind == "diff":
                run.publish(
                    EVT_DIFF_RESOLVED,
                    {
                        "decision_id": d.id,
                        "approved": False,
                        "reason": "stopped",
                        "edited": False,
                        "path": d.path,
                        "ts": _now_iso(),
                    },
                )
            else:
                run.publish(
                    EVT_APPROVAL_DECIDED,
                    {
                        "decision_id": d.id,
                        "approved": False,
                        "reason": "stopped",
                        "ts": _now_iso(),
                    },
                )
        return True

    # v1.9.x / decision 0027: server-side auto-approve OFF endpoint.
    # Returns ``(ok, error)``; ``ok=False`` with a reason means the
    # endpoint should respond 409 (no active session for this run).
    # On success, the session's ``auto_approve_destructive`` flag is
    # flipped; the next destructive gate call (shell.py / git.py
    # forward()) sees the new value through ``current_session()``.
    def set_auto_approve(self, run_id, enabled):
        from ..session import get_auto_approve as _get
        from ..session import set_auto_approve as _set

        # 404 first so a stale run id (run already ended + purged)
        # returns the same status as POST /stop etc.
        run = self.get(run_id)
        if run is None:
            return False, "run not found", None
        # ``_set`` validates run_id against the active session.
        ok, err = _set(run_id, enabled)
        if not ok:
            return False, err, None
        # Read back so the caller (API layer) can return the new state
        # in the response body (helpful for the SPA's optimistic UI).
        return True, None, _get(run_id)

    # Phase 2 (decision 0025 §6.4): pause / resume. ``pause_run`` sets
    # the run's ``pause_flag``; the step callback raises
    # ``_PauseRequested`` on the next step boundary (in
    # ``agent_runner._make_step_callback``). The runner thread catches
    # it, flips ``status`` to ``STATUS_PAUSED``, snapshots, and emits
    # ``run.paused``. The Run remains in the manager; ``resume_run``
    # clears the flag, rebuilds the agent from the snapshot, and
    # submits a continuation.
    def pause_run(self, run_id):
        run = self.get(run_id)
        if run is None:
            return False
        if run.status not in (STATUS_RUNNING, STATUS_AWAITING_APPROVAL):
            return False
        run.pause_flag.set()
        return True

    def resume_run(self, run_id, settings):
        """Resume a paused run.

        Returns ``(ok: bool, error: str | None)``. On success the
        agent is rebuilt + replayed in a new thread (the same
        pool/thread model as ``start_run``).
        """
        run = self.get(run_id)
        if run is None:
            return False, "run not found"
        if run.status != STATUS_PAUSED:
            return False, "run is not paused"
        if run.snapshot_path is None:
            return False, "no snapshot available for resume"
        # Late import to avoid circular dependency on agent_runner.
        from .agent_runner import resume_active_agent

        run.pause_flag.clear()
        # Build the fresh agent (memory restored) on the runner thread
        # itself, so the resume path mirrors the initial start_run.
        import threading as _threading

        def _resume_thread():
            try:
                agent = resume_active_agent(run, settings)
                run.status = STATUS_RUNNING
                run.publish(
                    EVT_RUN_RESUMED,
                    {
                        "run_id": run.id,
                        "snapshot_at": run.snapshot_at,
                        "ts": _now_iso(),
                    },
                )
                # Submit the continuation. The original ``run.task`` is
                # the user-provided task; the snapshot already includes
                # the TaskStep so ``reset=False`` continues from there.
                agent.run(run.task, reset=False)
            except Exception as e:
                _log and _log.warning("resume thread failed: %s", e)

        run.thread = _threading.Thread(
            target=_resume_thread,
            name="smolcode-resume-" + run.id[:8],
            daemon=True,
        )
        run.thread.start()
        return True, None

    # Phase 2 (decision 0025 §6.4): FIFO queue + pause/resume support.
    # A "queued" run is a Run record whose runner thread has NOT been
    # started yet; the SPA's <QueuePane> shows it with status=queued.
    # ``start_run`` consults ``_active_count`` and either starts the
    # thread immediately or pushes a QueueEntry onto ``_queue``.

    def is_busy(self):
        """True when at least one run is occupying a slot.

        Counts running + awaiting_approval + paused runs as busy. A
        paused run occupies a slot because resume is in-flight (the
        user is expected to resume or stop the paused run before
        another queued run should start).
        """
        with self._lock:
            for r in self._runs.values():
                if r.status in (STATUS_RUNNING, STATUS_AWAITING_APPROVAL, STATUS_PAUSED):
                    return True
        return False

    def enqueue(
        self,
        run_id,
        *,
        task,
        tier,
        project=None,
        session_id=None,
        provider_override=None,
        model_override=None,
        api_key_value=None,
        anchor_to_project_root=False,
    ):
        """Append a QueueEntry to the FIFO list. ``run_id`` is the pre-allocated Run.id.

        The corresponding Run is already registered via ``start_run``
        but its runner thread has NOT been started; ``start_run`` calls
        this instead of ``threading.Thread.start()`` when an active
        run exists. The entry's id matches ``Run.id`` so ``drain_queue``
        can look it up.
        """
        from ..session import safe_id

        eff_sid = None
        if session_id is not None:
            try:
                eff_sid = safe_id(session_id)
            except ValueError:
                eff_sid = None
        entry = QueueEntry(
            id=str(run_id),
            task=str(task),
            tier=str(tier),
            project=project,
            session_id=eff_sid,
            provider_override=provider_override,
            model_override=model_override,
            api_key_value=api_key_value if isinstance(api_key_value, str) else None,
            anchor_to_project_root=bool(anchor_to_project_root),
        )
        with self._queue_lock:
            self._queue.append(entry)
        self._refresh_queue_positions()
        return entry

    def evict_finished_runs(self, now=None):
        """Phase 7 (decision 0042): drop finished runs past the retention window.

        Only runs in a TERMINAL status with an ``ended_at`` older than
        ``_run_retention_s`` are eligible: ``running``,
        ``awaiting_approval``, ``paused`` and ``queued`` runs are never
        touched. ``api_key_value`` is zeroed on eviction so a SPA-supplied
        provider key does not outlive the run record in process memory.
        Called opportunistically from the submit path (and safe to call
        directly -- tests pass an explicit ``now``). Returns the evicted
        run ids.

        ``now`` is wall-clock epoch seconds, the same clock as
        ``Run.ended_at``. ``retention_s <= 0`` disables eviction.
        """
        retention = self._run_retention_s
        if retention is None or retention <= 0:
            return []
        current = time.time() if now is None else float(now)
        cutoff = current - float(retention)
        evicted = []
        with self._dispatch_lock:
            with self._lock:
                for run_id, run in list(self._runs.items()):
                    if run.status not in _TERMINAL_STATUSES:
                        continue
                    if run.ended_at is None or run.ended_at >= cutoff:
                        continue
                    run.api_key_value = None
                    del self._runs[run_id]
                    evicted.append(run_id)
        if evicted:
            _log.info("evicted %d finished run(s) older than %ss", len(evicted), retention)
        return evicted

    def _claim_next_queued(self, exclude_run_id=None):
        """Claim the next FIFO entry for a run that is finishing.

        Phase 7 (decision 0042): the drain used to pop the queue entry and
        start its thread under a separate ``_queue_lock`` section. A submit
        that slipped in after the finishing run's status flipped terminal
        (but before its drain ran) could then start a second run, and the
        drain would start the queued run right next to it. Claiming under
        ``_dispatch_lock`` -- the same lock the submit path uses -- makes
        the two paths serialised.

        Returns ``(run, entry, settings, cost_cap_tracker)`` on success, or
        ``None`` when the queue is empty or another active run owns the
        slot. Raises ``RuntimeError`` when an entry exists but the manager
        has no ``Settings`` (``RunManager._drain_queue`` records that in
        ``queue_drain_error`` instead of losing it).
        """
        with self._dispatch_lock:
            finishing_registered_at = None
            if exclude_run_id is not None:
                finisher = self.get(exclude_run_id)
                if finisher is not None:
                    finishing_registered_at = getattr(finisher, "_registered_at", None)
            if finishing_registered_at is not None:
                # Did a submit claim the slot after this run registered?
                # Then the drain must leave the queue to that run's own
                # drain; starting here would run two agents at once.
                with self._lock:
                    for r in self._runs.values():
                        if r.id == exclude_run_id or r.status not in _ACTIVE_STATUSES:
                            continue
                        other_registered = getattr(r, "_registered_at", None)
                        if other_registered is not None and other_registered > finishing_registered_at:
                            return None
            with self._queue_lock:
                if not self._queue:
                    return None
                entry = self._queue.pop(0)
            # Phase 4 (decision 0039): settings come from the manager, which
            # owns the instance create_app handed it -- not from a
            # request-scoped FastAPI dependency.
            settings = getattr(self, "_settings", None)
            if settings is None:
                # Put the entry back: a later drain (after create_app fixes
                # the wiring) must still be able to run it.
                with self._queue_lock:
                    self._queue.insert(0, entry)
                self._refresh_queue_positions()
                raise RuntimeError(
                    "RunManager has no Settings attached; cannot start queued run "
                    + entry.id
                    + ". create_app() must construct the manager with settings=."
                )
            target = self.get(entry.id)
            if target is None:
                self._refresh_queue_positions()
                return None
            target.status = STATUS_RUNNING
            target.queue_position = None
            target._registered_at = time.time()
            # Decision 0032: pull the cost-cap tracker off the run manager so
            # queued runs get the same per-step cap enforcement as the
            # initial start_or_enqueue_run call.
            cost_cap_tracker = getattr(self, "_cost_cap_tracker", None)
        self._refresh_queue_positions()
        return target, entry, settings, cost_cap_tracker

    def _drain_queue(self, run):
        """Phase 4 (decision 0039): drain the queue, RECORDING failures.

        This is the single seam the runner thread calls. Keeping the
        try/except here (rather than inline in ``run_in_thread``) is what
        makes the failure observable: the old inline version logged a
        warning and moved on, so a permanently stalled queue was
        indistinguishable from an idle one. ``queue_drain_error`` now
        holds the reason and is cleared on the next success.
        """
        from .agent_runner import _drain_queue_after_run

        try:
            result = _drain_queue_after_run(run, self)
        except Exception as exc:
            self.queue_drain_error = str(exc)
            return None
        self.queue_drain_error = None
        return result

    def queue(self):
        """Return a snapshot copy of the FIFO queue."""
        with self._queue_lock:
            return list(self._queue)

    def dequeue(self):
        """Pop the first queue entry, or None if empty. Refreshes positions."""
        with self._queue_lock:
            if not self._queue:
                return None
            entry = self._queue.pop(0)
        self._refresh_queue_positions()
        return entry

    def cancel_queue(self, run_id):
        """Remove a queued entry by id. Returns True on success."""
        with self._queue_lock:
            for i, e in enumerate(self._queue):
                if e.id == run_id:
                    del self._queue[i]
                    break
            else:
                return False
        # Mark the Run as cancelled (terminal) so SSE subscribers see it.
        run = self.get(run_id)
        if run is not None and run.status == STATUS_QUEUED:
            run.status = STATUS_STOPPED
            run.ended_at = time.time()
            run.publish(EVT_RUN_ENDED, {"run_id": run.id, "status": STATUS_STOPPED, "ts": _now_iso()})
            # Phase 7 (decision 0042): wake any SSE subscriber on the
            # cancelled run so it drains run.ended + the end frame instead
            # of waiting for the 15 s heartbeat.
            run.end_stream()
        self._refresh_queue_positions()
        return True

    def move_queue(self, run_id, new_position):
        """Decision 0031: move the queued entry at ``run_id`` to the
        1-based ``new_position``. ``new_position=1`` puts it at the
        head of the FIFO list (runs next); ``new_position=len`` puts it
        at the tail. Out-of-range values are clamped to ``[1, len]``.

        Returns the resulting 1-based position on success, ``None`` if
        ``run_id`` is not currently in the queue. The position of
        every other queued run is recomputed via
        ``_refresh_queue_positions`` so the FE's ``queue_position``
        stays in sync with the new ordering.
        """
        if not isinstance(new_position, int) or isinstance(new_position, bool):
            # Reject bool (subclass of int) and non-int inputs cleanly.
            raise ValueError("new_position must be an int")
        with self._queue_lock:
            ids = [e.id for e in self._queue]
            try:
                cur_idx = ids.index(run_id)
            except ValueError:
                return None
            n = len(self._queue)
            # Clamp to [1, n] (1-based). 0 / negative / >= n+1 all clamp.
            target_1based = max(1, min(int(new_position), n))
            target_0based = target_1based - 1
            if target_0based == cur_idx:
                # No-op. Refresh positions outside the lock below
                # (``_refresh_queue_positions`` also takes ``_queue_lock``
                # so we MUST release it first -- otherwise re-entering
                # the same RLock-equivalent via the threading.Lock would
                # deadlock).
                pass
            else:
                entry = self._queue.pop(cur_idx)
                self._queue.insert(target_0based, entry)
        # Always refresh positions after releasing the lock (no-op
        # moves included, so a stale cached value from a concurrent op
        # still gets corrected).
        self._refresh_queue_positions()
        return target_1based

    def _refresh_queue_positions(self):
        """Update each queued Run's ``queue_position`` (1-based) for the FE."""
        with self._queue_lock:
            queued_ids = [e.id for e in self._queue]
        with self._lock:
            for r in self._runs.values():
                if r.status == STATUS_QUEUED:
                    try:
                        r.queue_position = queued_ids.index(r.id) + 1
                    except ValueError:
                        r.queue_position = None
                else:
                    r.queue_position = None


# Phase 2 (decision 0025 §6.4) originally added ``_queue`` +
# ``_queue_lock`` via a module-level monkey-patch of ``RunManager.__init__``.
# Decision 0039 folded that into the real constructor above and removed the
# patch, so the class has exactly one definition of its state.


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
    "EVT_SUBAGENT_STARTED",
    "EVT_SUBAGENT_ENDED",
    "EVT_RUN_PAUSED",
    "EVT_RUN_RESUMED",
    "PendingDecision",
    "QueueEntry",
    "Run",
    "RunManager",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_AWAITING_APPROVAL",
    "STATUS_DONE",
    "STATUS_ERROR",
    "STATUS_STOPPED",
    "STATUS_PAUSED",
    "STATUS_QUEUED",
    "SubAgentSummary",
]
