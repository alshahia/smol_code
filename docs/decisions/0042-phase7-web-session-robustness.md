# ADR 0042 — Web/session-model robustness (Phase 7)

- **Status:** accepted
- **Date:** 2026-10-24
- **Phase:** 7 of `docs/reviews/2026-09-24-full-app-review/REMEDIATION-PLAN.md`
- **Supersedes:** nothing
- **Depends on:** decisions 0010 (runs/SSE), 0025 §6.4 (queue/pause), 0027 (auto-approve endpoint), 0039 (Phase 4 queue fixes), 0041 (Phase 6 trust boundary)

## Context

The 2026-09-24 review and the 2026-10-24 repair assessment left one cluster of
defects in the web execution plane. Each is a race or a lifetime problem, so
each was invisible to the request/response tests that cover the endpoints:

| Item | Defect at HEAD | Evidence |
|---|---|---|
| Concurrency | `start_or_enqueue_run` checks `is_busy()` and then registers/starts the run in a separate critical section. Two concurrent `POST /api/runs` can both observe "not busy" and both start. The same hole exists between a finishing run's queue drain and a submit that slips in after the finishing run's status flips terminal. | `runs.py:960` + `runs.py:914-925`; `agent_runner.py:1346-1384` |
| Session teardown | `run_in_thread`'s finally calls `set_session(None)` unconditionally. A finishing run A can therefore clear the session of a newer run B, disabling B's confirm/diff callbacks and resetting its auto-approve flag. | `agent_runner.py:1181` |
| Auto-approve scope | `session.set_auto_approve(run_id, enabled)` flips an installed session whose `run_id is None` unconditionally ("CLI path"). The web endpoint therefore flips whatever session is currently installed — including the orchestrator's child session, which is constructed with `run_id=None` — and writes process-global state from an HTTP request. | `session.py:225-230`; child session built at `agents/orchestrator.py:233-244` |
| Stop vs approval | `RunManager.stop()` only sets `run.stop_flag`. An agent blocked inside `confirm_callback` / `diff_callback` is inside `PendingDecision.event.wait(timeout_s)` and does not observe the flag until the human-decision timeout (default 300 s) expires — so "stop" does not stop a run that is waiting for approval. | `runs.py:1163-1168`; waits at `agent_runner.py:466,540,763,832` |
| Run retention | `RunManager._runs` grows for the life of the process. Finished runs, including the per-run `api_key_value` the SPA supplied, are never dropped. | `runs.py:718`, `runs.py:223` |
| SSE flake (A7) | `TestRunsSSE::test_events_stream_emits_run_started_and_ended` intermittently misses `event: run.ended` under full-suite load (1 484 passed / 1 failed at `c79705b`; 5/5 isolated). | assessment report A7 |

### The SSE flake is a real server race, not test slowness

The test's timing is a symptom. `run_in_thread`'s finally sets
`run.status = final_status` **before** it publishes `EVT_RUN_ENDED`
(`agent_runner.py:1179` vs `:1189`), and the audit-sink `end()` write sits
between them. `RunManager.subscribe` terminates when it observes a terminal
status **and an empty queue** (`runs.py:1086-1097`). Under load the subscriber
interleaves exactly in that window: it observes `status=done`, an empty queue
(the terminal frame is not published yet), takes the `get_nowait() -> Empty`
branch and breaks — dropping `run.ended` and emitting only the `end`
sentinel. The 15 s heartbeat in the same loop explains the observed 10–21 s
isolated run times when the subscriber instead parks in `get(timeout=15)`.

## Decision

1. **One dispatch critical section for "busy check + registration".**
   `RunManager` gains a re-entrant `_dispatch_lock`. `start_or_enqueue_run`
   performs the `is_busy()` test, the `Run` registration and the queue append
   (or the call into `start_run`) while holding it. `start_run` itself takes
   the same lock, so a direct `start_run` cannot race an enqueuing submit
   either. The run record is registered with `status=running` inside the
   critical section, so the slot is claimed before any thread is scheduled —
   the previous `pending` window was itself a (smaller) double-start hole.
   The runner thread is started after the registration; `run_in_thread`
   re-asserts `status=running` (idempotent).

2. **The queue drain claims its next run under the same lock.**
   `_drain_queue_after_run` no longer pops-and-starts inline. It calls
   `RunManager._claim_next_queued(exclude_run_id=<finishing run>)`, which
   under `_dispatch_lock`: verifies no *other* run is active, pops the FIFO
   entry, marks the target `running`, and returns it. This closes the
   "submit slips in during the drain window" double-start while preserving
   the two documented queue semantics: (a) a paused run still lets the next
   queued run start (the finishing run is excluded from the busy test), and
   (b) if a submit did claim the slot first, the queued run stays queued and
   is drained by the newly active run's finally.

3. **Session teardown is run-scoped.** `session.clear_session_for_run(run_id)`
   clears the installed session only when it is that run's session (exact
   `run_id` match). `run_in_thread` calls it instead of `set_session(None)`.
   A finishing run can no longer clobber a newer run's session, callbacks or
   auto-approve state. The CLI is unaffected: it installs its own session
   with `run_id=None` and clears it itself (`cli.py:496`).

4. **Auto-approve is run-scoped; an unscoped session is refused for a
   run-scoped caller.** `set_auto_approve(run_id, enabled)`:
   - `run_id is None` (CLI's own in-process call) → flip the installed
     session, preserving CLI behaviour;
   - installed session has `run_id is None` but the caller supplied a run id
     → refuse with `"session is not scoped to a run"` (this is the
     orchestrator child-session hole) and do not mutate anything;
   - installed session has a different run id → refuse with
     `"session is for a different run"` (unchanged);
   - exact match → flip.
   `get_auto_approve` applies the same scoping so a read cannot report a
   child/CLI flag as if it belonged to a run. A run's `SessionState` is
   constructed per run (`agent_runner.py:963-971`) with
   `auto_approve_destructive=False`, so a new run cannot inherit a previous
   run's approval.

5. **`stop()` resolves pending decisions as DENIED (fail-closed).** After
   setting `stop_flag`, `RunManager.stop` drains the run's `pending` list
   (under `pending_lock`) and resolves each `PendingDecision` with
   `approved=False, reason="stopped"`, publishing the matching
   `approval.decided` / `diff.resolved` event. The agent thread wakes at
   once; the existing `_StopRequested` path then terminates the run as
   `stopped`. `PendingDecision.resolve` is already idempotent and
   `take_decision` already claims a decision atomically, so a concurrent
   `POST /approval` cannot both resolve and observe it.

6. **Finished runs are evicted on a TTL; API keys are zeroed on eviction.**
   `RunManager` gains `retention_s` (constructor override, default from
   `SMOLCODE_RUN_RETENTION_S`, 24 h; `<= 0` disables) and
   `evict_finished_runs(now=None)`. It only ever removes runs in a terminal
   status with `ended_at` older than the window — `running`,
   `awaiting_approval`, `paused` and `queued` runs are never touched — and
   sets `run.api_key_value = None` as it drops each record. It is called
   opportunistically from `start_or_enqueue_run` / `start_run` (each submit
   sweeps first) and is safe to call directly (tests pass a fake `now`).
   No `Settings` field was added: a `Settings` change would have to thread
   `__slots__`/`with_overrides`/project-rebuild paths for a manager-lifetime
   knob that the manager already owns, and Phase 8 owns `config.py` in this
   work stream.

7. **The SSE stream terminates on a producer sentinel, not on a status poll.**
   `Run` gains `stream_finished` (+ `end_stream()`), which re-queues a
   private `_STREAM_END` sentinel after the terminal frame and sets the flag.
   `subscribe()` breaks on the sentinel (or when the queue is empty *and*
   the producer is known to be finished). For a run whose status was flipped
   terminal without a producer (legacy tests, direct `publish` callers) it
   keeps the old "`ended_at is None` → break" fallback, so the existing
   `test_run_manager.py` contract is preserved. Result: `run.ended` can no
   longer be dropped by an interleaving that observes the status first.

## Consequences

- Two concurrent `POST /api/runs` now yield exactly one active run; the other
  is queued (existing `start_or_enqueue_run` semantics), never a second
  concurrent runner. This is pinned by a barrier-synchronised N-thread test
  against the real `RunManager`.
- Stopping a run that waits for a human approval diff/decision now terminates
  promptly (test bound: < 2 s) with reason `stopped`; previously it waited up
  to the decision timeout.
- A long-lived server no longer retains every finished run (and its API key)
  forever. Default 24 h is a behaviour change from "never"; it is documented
  and configurable, and the sweep runs on the request path so no timer thread
  or shutdown hook is introduced.
- `set_auto_approve` refuses two cases it used to accept (unscoped child
  session, mismatched run). The web endpoint maps both to **409**, matching
  the existing "run exists but is not the active session" contract; the SPA
  already treats 409 as "banner state is stale".
- The whole per-run `SessionState` singleton refactor (explicit
  execution-context object passed through delegation) is **not** done here.
  This ADR hardens the singleton's lifetime; it does not remove it. That is
  the same scoping the plan permits ("Until that lands, at minimum …").
- No public HTTP contract changes: no route, request field or response field
  changes. `stop` responds as before; eviction only affects ids that a client
  would 404 on already.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Wrap only `is_busy()` + insert in `RunManager._lock` and leave `start_run` outside | A concurrent direct `start_run` (tests, future callers) still races; the dispatch lock is the same cost and covers both entry points. |
| Serialise submits with a module-level global lock | The manager already owns the state; a module global would silently fail for a second manager (tests instantiate several). |
| Move `run.status = final_status` after the `run.ended` publish instead of a sentinel | Shrinks the window but does not close it: a subscriber can still observe terminal-on-read semantics around the status assignment, and a client polling `GET /api/runs/{id}` would see `running` for a finished run. The sentinel is ordering-proof. |
| Have `stop()` raise into the waiting thread (e.g. `Thread.interrupt`) | Not portable, unsafe, and the pending-decision queue is already the defined host↔agent handoff; resolving it is the natural fail-closed answer. |
| Evict from a background timer thread | Adds a lifecycle object (start/stop/exception surface) for a sweep that is O(active runs) and needs to run at most once per submit. Tests would need time control over a thread. |
| Zero `api_key_value` immediately in `_build_agent_for_run` | A paused run can be resumed; resume calls `_build_agent_for_run` again and needs the key. Zeroing at eviction (terminal only) keeps resume working. |
| Keep the SSE test as substring matching and just raise its sleep budget | Would hide the server race instead of fixing it; the assessment explicitly asks for a deterministic test. |

## Validation

```
# from E:\python_projects\smol_code
& smolcode\.venv\Scripts\python.exe -m ruff check <changed files>
& smolcode\.venv\Scripts\python.exe -m ruff format --check <changed files>
& smolcode\.venv\Scripts\python.exe -m pytest smolcode/src/smolcode/tests/test_web_hardening_phase7.py -q
& smolcode\.venv\Scripts\python.exe -m pytest smolcode/src/smolcode/tests/test_web_runs_api.py -q
& smolcode\.venv\Scripts\python.exe -m pytest smolcode/src/smolcode/tests/test_queue.py smolcode/src/smolcode/tests/test_queue_cost_phase4.py smolcode/src/smolcode/tests/test_run_manager.py -q
& smolcode\.venv\Scripts\python.exe -m pytest smolcode/src/smolcode/tests/test_web_server.py -q   # no regression
# SSE determinism: the rebuilt test run alone 5 times, timings recorded
```

Observed on 2026-10-24 (Windows 11, Python 3.13.1, pytest 9.1.1), after the
external auto-checkpoint wipe and recovery:

| Check | Result |
|---|---|
| `ruff check` + `ruff format --check` on the five changed files | clean |
| `test_web_hardening_phase7.py` | 23 passed |
| `test_web_runs_api.py` | 48 passed |
| targeted regression set: hardening, web_runs_api, run_manager, queue, queue_cost_phase4, runs_keys, pause_resume, agent_runner, web_server | 218 passed in 43.29 s |
| SSE test alone, 5 consecutive isolated runs | 5/5 passed; 6.36-8.05 s in-test, 7.36-9.79 s wall |

## Exit criteria

1. N simultaneous `start_or_enqueue_run` calls → exactly one `running` run and
   N-1 `queued`; the drain claims under the same lock and never starts a
   second run while one is active.
2. A finishing run whose id does not own the installed session leaves that
   session intact; `clear_session_for_run` is the only web teardown path.
3. `set_auto_approve` flips only the exact run's session; a run id supplied
   while an unscoped (child/CLI) session is installed is refused; the CLI's
   own unscoped toggle still works.
4. `stop()` unblocks a run parked in the destructive *and* diff approval
   callback with `approved=False`, reason `stopped`, in under 2 s.
5. Eviction removes only terminal runs older than the window, zeroes
   `api_key_value`, and never removes `running`/`paused`/`queued` runs.
6. `test_events_stream_emits_run_started_and_ended` parses SSE events with a
   bounded overall deadline and passes 5/5 isolated runs; the
   status-then-publish race is covered by a deterministic unit test that
   would fail on the pre-fix `subscribe()`.

## File-by-file

| File | Change |
|---|---|
| `web/runs.py` | `_dispatch_lock`; `_build_run`/`_register_run` refactor; atomic `start_or_enqueue_run` + `start_run`; `_claim_next_queued`; run-scoped `stop` decision resolution; `retention_s` + `evict_finished_runs`; `Run.stream_finished`/`end_stream`; sentinel-based `subscribe` |
| `web/agent_runner.py` | `clear_session_for_run(run.id)` instead of `set_session(None)`; `run.end_stream()` after `run.ended`; drain delegates to `_claim_next_queued` |
| `session.py` | `clear_session_for_run`; run-scoped `set_auto_approve` / `get_auto_approve` (unscoped session refused for a run-scoped caller; CLI `run_id=None` path preserved) |
| `tests/test_web_runs_api.py` | SSE test rewritten as an event parser with a bounded deadline (plus the key-redaction SSE test uses the same reader) |
| `tests/test_web_hardening_phase7.py` (new) | concurrency, teardown guard, auto-approve scoping, stop-during-approval (destructive + diff), retention/key-zeroing, subscribe race |
| `docs/decisions/0042-phase7-web-session-robustness.md` | this ADR |

## Supersedes / relates

- Decision 0027 — the auto-approve endpoint's validation contract is narrowed
  here (run-scoped only); its HTTP mapping (404 vs 409) is unchanged.
- Decision 0039 — the queue drain seam it introduced is now claimed
  atomically; no signature changes.
- Decision 0041 — the per-call approval limitation for in-container tools is
  unchanged; this ADR only guarantees that a stopped run's host-side waiter
  is resolved.
- Not in scope (Lead owns): `web/server.py` `TrustedHostMiddleware` and the
  web-boot `ensure_internal_network` provisioning (A4).
