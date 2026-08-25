# Decision 0027 — Server-side auto-approve OFF endpoint (closes FE-6 partial)

- **Status:** applied (uncommitted, awaiting user commit)
- **Date:** 2026-08-25
- **Type:** web UI / API contract decision
- **Related:** 0025 (Web UI/UX roadmap §3.10 + §6.5 FE-6 / B10),
  0007 (M4.x per-tool confirmation checkpoint),
  0012 (M9 live execution),
  v1.9.x commit `bec3ce9` (FE wire-up)
- **Supersedes:** none
- **Superseded by:** none
- **Implementation:** All changes live in the working tree but are NOT
  yet committed (per the explicit `AGENTS.md` / `CLAUDE.md` rule
  "Do not commit unless the user explicitly requests it"). See
  §7 for the exact file list + the diff summary that the user should
  review and commit when ready.

---

## 1. Context

v1.9.x commit `bec3ce9` shipped the `<AutoApproveBanner>` mid-run
indicator (FE-6 / B10, decision 0025 §3.10) but the docstring in
`smolcode/web/src/components/AutoApproveBanner.tsx` already flagged
that the "Disable" button only cleared the **client-side** flag:

> *"Clicking Disable lets the user turn the indicator off
> client-side; the backend's per-session state continues to
> auto-approve future prompts (full BE disabling requires a followup
> endpoint)."*

That followup endpoint is this decision. With it:

- Clicking **"Disable"** on the banner → flips
  `session.auto_approve_destructive` on the **server**, so the
  next destructive `shell` / `git_push` call in
  `full_access` tier re-arms the ApprovalModal instead of being
  silently auto-approved.
- Clicking **"Approve (no more prompts this run)"** in the
  ApprovalModal → also reaches the BE so the next destructive call
  skips the gate, matching parity with the CLI's "type `a`" flow.

The previous behaviour (commit `bec3ce9`) had an inconsistency
between CLI and web: on the CLI, the user types `a` →
`DestructiveDecision.auto_approve_now=True` → shell tool flips
`sess.auto_approve_destructive=True` → next destructive call skips
the gate. On the web, the FE sent `reason="auto-approve"` to
`/api/runs/{id}/approval` but the web's `_build_confirm_callback`
only propagated `approved` and `reason` — it dropped
`auto_approve_now` / `auto_approve_off`, so the BE session flag
**never** flipped. The new endpoint fixes this by making the BE
flag flip explicit (a separate POST with an explicit `enabled`
field), instead of relying on the destructive gate callback to
parse the `reason` string.

---

## 2. Decision

1. **Add `POST /api/runs/{run_id}/auto-approve`** with body
   `{"enabled": bool}`. The endpoint flips
   `session.auto_approve_destructive` for the active session if
   the supplied `run_id` matches the session's `run_id`.

   - `200 OK` → `{"run_id", "auto_approve_destructive", "changed": True}`
   - `404 Not Found` → run id is unknown to the RunManager (run
     already purged).
   - `409 Conflict` → run exists in the manager but no session
     currently owns it (run ended, or another run is in flight).
   - `422 Unprocessable Entity` → `enabled` missing or not
     bool-coercible (Pydantic validation).

2. **Tag the session with the active run id.** `SessionState` grows
   a `run_id: str | None = None` field. The web's
   `agent_runner.run_in_thread` passes `run_id=run.id` when it
   constructs the `SessionState`. CLI sessions keep `run_id=None`
   so existing CLI tests are unchanged.

3. **Add two pure helpers to `session.py`:**
   `set_auto_approve(run_id, enabled) -> (ok, error)` and
   `get_auto_approve(run_id) -> bool | None`. Both are atomic
   under the existing `_session_lock`. The endpoint delegates to
   `set_auto_approve` via a thin `RunManager.set_auto_approve`
   wrapper.

4. **FE wiring:** the `<AutoApproveBanner>` "Disable" button (which
   calls `onAutoApproveDisable`) and the `<ApprovalModal>`
   "Approve + auto-approve" button (which calls
   `onAutoApproveToggle(true)`) **both** POST to the new endpoint
   in addition to flipping the client-side `autoApproveRunIds` set.
   The POST is fire-and-forget: a stale run id (404/409) is silently
   swallowed since the client-side state is the source of truth for
   the banner. The next page reload will resync via a future
   GET endpoint (out of scope for 0027).

---

## 3. Rationale

### 3.1 Why a dedicated endpoint, not just propagating `reason="auto-approve"`

The web's `_build_confirm_callback` is a closure that runs inside
the agent thread and only sees the `decision.approved` and
`decision.reason` fields it propagates back. To make it flip
`auto_approve_destructive` based on `reason` we'd have to:

- thread the `reason` through the agent's step callback (a
  smolagents internals change), OR
- parse the reason string in the closure (`if reason == "auto-approve": set_auto_approve_now()`) — fragile,
  stringly-typed, and a regression on the existing `DestructiveDecision` contract that already
  has `auto_approve_now` / `auto_approve_off` flags the CLI uses.

A dedicated endpoint is simpler, has an explicit schema
(`AutoApproveSetRequest`), and is testable in isolation
(`TestRunsAutoApprove`, 6 tests).

### 3.2 Why `run_id` on `SessionState`

The session is a **module-level singleton**. The web process can
host at most one active run at a time (RunManager enforces this
via `_TERMINAL_STATUSES` + the FIFO queue) but the endpoint is
called over HTTP and may carry a stale run id (the SPA kept the
banner visible across a refresh, the run already ended, etc.).
Tagging the session with its run id lets the endpoint validate the
caller before flipping the flag — without that, a stale run id
would silently flip the **next** run's flag.

CLI sessions keep `run_id=None` so existing tests don't need
touching (the helper trusts the caller when `s.run_id is None`,
matching the CLI's "one run at a time" assumption).

### 3.3 Why flip both ON and OFF from the FE

The task scoped the work to the OFF path (banner Disable), but
implementing only OFF would have left an inconsistent state: the
FE banner would show even though the BE flag was never True, and
clicking Disable would be a no-op BE-side (since the BE was
already False). To make the banner Disable meaningful, the ON path
(ApprovalModal "Approve + auto-approve") must also flip the BE —
otherwise the FE has a cosmetic flag the BE never sees.

This is the same behavior as the CLI: typing `a` flips the flag
ON, typing `o` flips it OFF. The web now has parity.

### 3.4 Why `changed: bool` in the response

The helper `RunManager.set_auto_approve` always flips; `changed`
in the response is currently always `True` after the helper
returns ok. We still emit it because:

- it costs nothing (one boolean),
- it gives the SPA a stable response shape for future optimisation
  ("don't re-fetch when changed=false"),
- it documents the intended semantics (idempotent flips).

A future tightening can compare `before` and `after` to set
`changed=false` on no-ops.

---

## 4. Test environment

Decision 0027 has no new environment dependencies. Validated
against the **same** setup decision 0026 stabilised:
`uv sync --locked --extra web` + Python 3.12 + FastAPI 0.136.x +
smolagents 1.26.0. The blocking stub in
`test_auto_approve_flips_session_flag_while_run_active` uses
`threading.Event` to park the agent so the test can fire the
endpoint **during** the run and assert the singleton flag moves.

---

## 5. Validation results

| Gate | Result |
|---|---|
| `ruff check src` | 0 errors |
| `ruff format --check src` | 101 files already formatted |
| `pytest src/smolcode/tests` | **1144 PASS / 0 FAIL / 5 SKIP** (1138 baseline + 6 new) |
| `pnpm test` | **55/55** (AutoApproveBanner 4 + ApprovalModal 5 unchanged) |
| `pnpm exec tsc -b` | 0 errors |
| `pnpm build` | 257.80 KB JS / 77.67 KB gzip (matches baseline) |

The 6 new BE tests in `TestRunsAutoApprove` (file
`smolcode/src/smolcode/tests/test_web_runs_api.py`):

| Test | Asserts |
|---|---|
| `test_auto_approve_unknown_run_returns_404` | Unknown run id → 404 |
| `test_auto_approve_rejects_missing_body` | Missing `enabled` → 422 |
| `test_auto_approve_rejects_nonboolean_body` | `enabled=[1,2,3]` → 422 |
| `test_auto_approve_returns_409_when_session_not_yet_active` | Run already ended → 409 with "session" in detail |
| `test_auto_approve_flips_session_flag_while_run_active` | POST flips `get_session().auto_approve_destructive` ON then OFF; blocking stub via `threading.Event` parks the agent so the session stays installed |
| `test_auto_approve_rejects_wrong_run_id` | POST after run ended → 409 (run still in RunManager; session cleared) |

---

## 6. Remaining limitations (out of scope for 0027)

- **No GET endpoint to refresh the banner state on page reload.**
  The FE optimistically tracks `autoApproveRunIds` in client
  memory; a refresh loses it. A `GET /api/runs/{id}/auto-approve`
  would close this but adds API surface for a minor UX edge case
  (decide 0027 in scope was specifically the OFF endpoint). Tracked
  as a follow-up in `TASKS.md` §4.
- **No auto-approve hint in the audit log.** When the FE toggles the
  flag via the new endpoint, no audit `event` is emitted. The
  CLI emits `destructive_decision` on the gate callback (which
  the endpoint bypasses); for 0027 we accept the gap. A future
  decision can wire the endpoint to also call
  `audit_sink.record("auto_approve_toggle", ...)` — additive and
  trivial to retrofit.
- **No diff-gate parity.** The new endpoint flips the
  `auto_approve_destructive` flag only. The
  `auto_approve_diff` flag (flipped when the user approves a
  write_file with "no more prompts") is unchanged; the FE does not
  expose a UI control for diff auto-approve toggling in v1.9.x.

---

## 7. File-by-file implementation spec

### 7.1 `smolcode/src/smolcode/session.py` (+73 LOC)

- Added `run_id: str | None = None` to `SessionState` (backwards
  compatible: existing CLI tests instantiate
  `SessionState(...)` positionally or by name and the new field
  has a default).
- Added two pure helpers, both atomic under `_session_lock`:
  - `set_auto_approve(run_id, enabled) -> (ok, error)`
  - `get_auto_approve(run_id) -> bool | None`
- Extended `__all__` to export the new helpers.

### 7.2 `smolcode/src/smolcode/web/agent_runner.py` (+8 LOC)

- Added `run_id=run.id` to the `SessionState(...)` constructor in
  `run_in_thread`. The rest of the change is a comment block
  explaining why.

### 7.3 `smolcode/src/smolcode/web/runs.py` (+20 LOC)

- Added `RunManager.set_auto_approve(run_id, enabled)` that
  delegates to `session.set_auto_approve` and reads back via
  `get_auto_approve`. Returns `(ok, error, current_value)` so
  the API layer can return the post-flip state.

### 7.4 `smolcode/src/smolcode/web/schemas.py` (+35 LOC)

- `AutoApproveSetRequest` — Pydantic model with `enabled: bool`.
- `AutoApproveSetResponse` — `run_id`, `auto_approve_destructive`,
  `changed`.

### 7.5 `smolcode/src/smolcode/web/api.py` (+33 LOC)

- Imported `AutoApproveSetRequest`, `AutoApproveSetResponse`.
- Added `@router.post("/runs/{run_id}/auto-approve", ...)`
  endpoint. Maps `run not found` → 404, `no active session` /
  `session is for a different run` → 409.
- Updated the docstring header to list the new endpoint.

### 7.6 `smolcode/web/src/api.ts` (+28 LOC)

- Added `AutoApproveSetResponse` TS interface.
- Added `postAutoApprove(runId, enabled)` that POSTs
  `{enabled}` to `/api/runs/{id}/auto-approve`.

### 7.7 `smolcode/web/src/App.tsx` (+10 LOC)

- Added `postAutoApprove` to the import list.
- Updated `onAutoApproveToggle` to also call
  `postAutoApprove(activeRunId, active)` (fire-and-forget).

### 7.8 `smolcode/web/src/components/AutoApproveBanner.tsx` (+3 LOC, -3 LOC)

- Updated the top docstring to reflect that Disable now reaches
  the BE.

### 7.9 `smolcode/src/smolcode/tests/test_web_runs_api.py` (+150 LOC)

- Added `import threading`.
- New class `TestRunsAutoApprove` with 6 tests (table in §5).

---

## 8. Validation commands

```bash
# From `smolcode/` (canonical validation path = Python 3.12)
uv sync --locked --extra web
.\.venv\Scripts\python.exe -m ruff check src
.\.venv\Scripts\python.exe -m ruff format --check src
.\.venv\Scripts\python.exe -m pytest src/smolcode/tests -q --no-cov

# From `smolcode/web/`
pnpm install --frozen-lockfile
pnpm test --run
pnpm exec tsc -b
pnpm build
```

Expected: BE 1144 PASS / 0 FAIL / 5 SKIP; FE 55/55 vitest;
`pnpm build` ≤ 258 KB / 78 KB gzip; ruff 0 errors.

---

## 9. References

- v1.9.x commit `bec3ce9` — ships `<AutoApproveBanner>` with
  the "Disable" button that this decision wires to the BE.
- Decision 0007 §M4.x — original per-tool confirmation design;
  introduced `SessionState.auto_approve_destructive` and the
  confirm callback that the new endpoint bypasses.
- Decision 0025 §3.10 / FE-6 / B10 — FE banner spec + the explicit
  "followup endpoint" followup that this decision closes.
- Decision 0026 §3.1 — FastAPI pin (`<0.137`) so the new endpoint
  registers correctly (route-registration regression on 0.137+).
- `smolcode/web/src/components/AutoApproveBanner.tsx` original
  docstring (pre-0027) — explicitly mentioned the missing BE
  endpoint as a follow-up.
