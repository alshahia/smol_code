# 0012 — M9 live execution implementation log

**Date:** 2026-08-21
**Status:** active
**Trigger:** M8 SHIPPED (decision 0011). User asked to proceed to M9
(live execution via SSE + tier switcher + stop button + approval modal).
**Related:** decision 0010 (design D2, D5), decision 0011 (M8
implementation log), roadmap.md M9, architecture.md §13 (new),
security.md §3.5 (new), README M9 section.

---

## Question

How do we ship the M9 slice of decision 0010 (live execution via SSE,
tier switcher, stop button, mid-run approval modal) end-to-end while
preserving the M0–M8 invariants (tier policy, audit log, sandbox
isolation, bind allowlist, 80% coverage gate)?

## Findings

### F1. M9 was the deferred v1.2 work in decision 0011

0011 §Followups listed M9 as the next milestone:

> **M9** (live execution): SSE bridge from agent loop to SPA; tier
> switcher with confirmation modal; stop button; mid-run approval
> for gated actions.

Decision 0010 D4 already showed the three-pane layout with the center
stream pane placeholder. The SPA's prior M8 implementation surfaced
the placeholder text "Live agent streaming ships in M9." so the
shape was already established.

### F2. smolagents 1.27.0.dev0 exposes a step_callbacks hook

`CodeAgent` registers per-step-class callbacks through
`agent.step_callbacks.register(ActionStep, callback)`. The callback
receives the step object after the LLM produced it. This is the
cleanest extension point: no monkey-patching, no forking. We register
one callable for `ActionStep`, `PlanningStep`, and `FinalAnswerStep`.

### F3. M4.x destructive-op confirm already runs on the same thread as the agent loop

The CLI's `session.confirm_callback` is invoked synchronously from
the host-side tool's `forward()` method (see cli.py:299 and
decision 0007). The same thread is the agent loop thread. So we can
block in the callback for up to the existing
`SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S` (default 30 s) without
disturbing the loop. The runner's confirm callback publishes the
approval.requested event and blocks on a `PendingDecision.event`.

### F4. The full_access tier requires an interactive y/N prompt

Per decision 0006 + cli.py:201, full_access runs prompt for
`Confirm full-access run? [y/N]` on stdin BEFORE the agent is built.
The web flow has no stdin. We made a v1 decision: **reject
full_access from the web with HTTP 403**. The CLI remains the
authoritative path for full_access. The SPA's tier dropdown omits
full_access entirely. (The user can argue for a confirm-modal pattern
in v1.1; we did not build it because the threat model change is
large and out of scope for M9.)

### F5. StreamingResponse raises KeyError lazily

`RunManager.subscribe()` returns a generator. `StreamingResponse`
does not call `next()` until the response starts streaming, so any
`KeyError` raised inside the generator (for an unknown run_id)
surfaces AFTER the 404 try/except has already returned. Fix: check
`mgr.get(run_id) is None` up front and raise HTTPException(404)
before constructing StreamingResponse.

### F6. PowerShell heredocs + backticks + newlines

The SPA source files were written via PowerShell `@'...'@` heredocs
that did not interpret escape sequences. Three problems:

1. `\n` inside JS strings became raw LFs, breaking the JS literal.
2. Empty-string backslashes (`\\`) inside Python string literals
   showed up as literal `\\\\` because PS does not interpret them.
3. The JSX `title={\`...\`}` pattern requires `{}` wrapping; raw
   backticks inside attributes are invalid JSX.

Fix: post-process written files with a byte-level Python regex that
collapses `'<LF>'` sequences into the literal `'\n'`. Edit-driven
fixes for the JSX backtick issues and the Python backslash-escape
issues where applicable.

### F7. React 19 + TS 6: `JSX.Element` namespace removed

In `@types/react@19` the global `JSX` namespace is no longer
exported. Functions returning JSX need `React.ReactElement` (or
`ReactNode`). Trivial fix in EventStream.tsx.

### F8. Coverage gate pressure

The M9 modules added 7 files (~570 LOC new) and the coverage gate
is enforced at 80% by pyproject's pytest addopts. Initial coverage
was 78.91% — below the gate. Solution: write targeted unit tests
for the agent_runner helpers (`_action_step_payload`,
`_build_confirm_callback`, `_make_step_callback`) — 19 new tests
lifted agent_runner.py from 31.7% to 68.9% and overall to 80.91%.

## Decision

### Scope

M9 ships the four features in decision 0011's Followup as one milestone:

1. **SSE live execution stream** (`GET /api/runs/{id}/events`).
2. **Tier switcher in the header** (changes the next run's tier; the
   SPA hides full_access).
3. **Stop button** (`POST /api/runs/{id}/stop`, cooperative via
   step callback).
4. **Mid-run approval modal** (the destructive-op gate publishes to
   SSE; the SPA shows a modal and POSTs a decision).

### Architecture

- **`smolcode/web/runs.py`** (new, 250 LOC) — `Run`, `RunManager`,
  `PendingDecision`, SSE encoder, status constants. The run manager
  owns the registry, the per-Run event queue, and the lifecycle.
- **`smolcode/web/agent_runner.py`** (new, 280 LOC) — wraps the
  existing tier factories in a worker thread, wires the
  `step_callbacks` hook, and bridges `session.confirm_callback` to
  the approval gate.
- **`smolcode/web/api.py`** (extended, +120 LOC) — 4 new endpoints
  plus shared schemas.
- **`smolcode/web/server.py`** (extended, +5 LOC) — lifespan
  attaches the run manager to `app.state`.
- **`smolcode/web/deps.py`** (extended, +13 LOC) — `get_run_manager`
  FastAPI dependency.
- **`smolcode/web/schemas.py`** (extended, +30 LOC) — Pydantic v2
  models for the new endpoints.
- **`smolcode/web/` SPA source**: 6 new components
  (`EventStream.tsx`, `ApprovalModal.tsx`, `StopButton.tsx`,
  `TierSwitcher.tsx`, `RunComposer.tsx`, `RunHistory.tsx`) + a
  rewritten `App.tsx` (~250 LOC new + ~200 LOC replaced).
- **`smolcode/web/src/index.css`** — appended ~180 lines of M9 CSS.

### M9 API surface

```
POST   /api/runs                       start a new run (returns run_id)
GET    /api/runs                       list runs (newest first)
GET    /api/runs/{id}                  run summary
GET    /api/runs/{id}/events           SSE event stream
POST   /api/runs/{id}/approval         resolve a pending gate
POST   /api/runs/{id}/stop             request stop at next step
```

### Threading

- One worker thread per run. The thread owns the agent loop.
- The SSE handler is a coroutine on the FastAPI event loop; it reads
  from a per-Run `queue.Queue` (unbounded).
- The confirm callback runs on the agent worker thread; it publishes
  an SSE event then blocks on a `PendingDecision.event`.
- The `decide()` HTTP handler runs on the FastAPI event loop; it
  resolves the `PendingDecision.event`, which unblocks the worker.
- The `stop()` HTTP handler sets a `Run.stop_flag` Event; the worker
  checks it from the step callback and raises `_StopRequested` if
  set.

### Tier policy

- The web SPA does not surface full_access in the tier dropdown.
- `POST /api/runs` rejects full_access with HTTP 403 (decision 0012,
  this section).
- The orchestrator tier is exposed because the existing
  `build_orchestrator_agent` does not need full filesystem access
  (it delegates to sub-agents).

### Auth model

- Loopback-only (M8's `ALLOWED_BIND_HOSTS`). No CSRF token, no
  bearer token. Threat model: the only thing on the same machine
  that can hit 127.0.0.1:7860 is the user themselves. (Decision
  0012, this section.)

## Code Impact

| File | Status | Lines |
|---|---|---|
| `smolcode/src/smolcode/web/runs.py` | new | ~250 |
| `smolcode/src/smolcode/web/agent_runner.py` | new | ~280 |
| `smolcode/src/smolcode/web/api.py` | updated | +120 |
| `smolcode/src/smolcode/web/server.py` | updated | +5 |
| `smolcode/src/smolcode/web/deps.py` | updated | +13 |
| `smolcode/src/smolcode/web/schemas.py` | updated | +30 |
| `smolcode/src/smolcode/tests/test_run_manager.py` | new | 20 tests |
| `smolcode/src/smolcode/tests/test_web_runs_api.py` | new | 15 tests |
| `smolcode/src/smolcode/tests/test_agent_runner.py` | new | 19 tests |
| `smolcode/web/src/api.ts` | updated | +90 |
| `smolcode/web/src/components/EventStream.tsx` | new | ~130 |
| `smolcode/web/src/components/ApprovalModal.tsx` | new | ~50 |
| `smolcode/web/src/components/StopButton.tsx` | new | ~25 |
| `smolcode/web/src/components/TierSwitcher.tsx` | new | ~25 |
| `smolcode/web/src/components/RunComposer.tsx` | new | ~45 |
| `smolcode/web/src/components/RunHistory.tsx` | new | ~45 |
| `smolcode/web/src/App.tsx` | updated | rewrite |
| `smolcode/web/src/index.css` | updated | +180 |
| `docs/roadmap.md` | updated | M9 row |
| `docs/architecture.md` | updated | new §13 |
| `docs/security.md` | updated | new §3.5 |
| `smolcode/README.md` | updated | M9 section |

## Validation

| Gate | Result |
|---|---|
| `ruff check src` | All checks passed |
| `ruff format --check src` | 68 files already formatted |
| `pytest` (with coverage gate) | **596 passed** in 84 s |
| `--cov-fail-under=80` | **80.91% reached** (gate at 80%) |
| `pnpm --dir web build` | OK (206 KB JS, 8.6 KB CSS, 27 modules) |
| TestClient e2e smoke | All 4 new endpoints work; SSE stream emits start/end |
| Full_access rejected from web | HTTP 403 + clear message |
| Cooperative stop | Stop flag checked in step callback |

### Test count progression

M8 = 542 → M9 = **596** (+54: 20 run-manager + 15 web-runs-api + 19
agent-runner).

## Followups (v1.1+ / future milestones)

- **M10**: inline diff viewer for `write_file` / `patch_file`; apply /
  reject per step; workspace tree.
- **M11**: specialist editor (forms for `specialists.toml`); MCP
  server manager; CLI `audit ls` / `audit grep`.
- **Replay**: SSE subscriber joining late does not see events that
  arrived before subscription. Add a buffered replay (last N events
  per run) — out of scope for v1.
- **Auth**: add a per-launch CSRF token on mutating endpoints if the
  threat model changes (e.g. shared machine).
- **PyInstaller bundle**: single-file `smolcode.exe` with SPA embedded.

## References

- `docs/decisions/0010-gui-design.md` — design (active)
- `docs/decisions/0011-m8-implementation.md` — M8 implementation log
- `docs/roadmap.md` — M9 SHIPPED section
- `docs/architecture.md` — §13 Web GUI: Live Execution
- `docs/security.md` — §3.5 Web Live Execution
- `smolcode/README.md` — M9 section
- `smolcode/src/smolcode/web/runs.py` — RunManager
- `smolcode/src/smolcode/web/agent_runner.py` — step + confirm bridges
- `smolcode/src/smolcode/web/api.py` — endpoints
- `smolcode/web/src/components/EventStream.tsx` — SSE subscriber
- `smolcode/web/src/components/ApprovalModal.tsx` — destructive gate
- `smolcode/web/src/App.tsx` — three-pane M9 integration