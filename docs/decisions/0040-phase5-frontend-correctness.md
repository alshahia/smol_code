# ADR 0040 — Frontend correctness: the SPA reflects backend reality

- **Status:** accepted
- **Date:** 2026-09-24
- **Phase:** 5 of `docs/reviews/2026-09-24-full-app-review/REMEDIATION-PLAN.md`
- **Supersedes:** nothing
- **Depends on:** Phase 3 (strict TS + working `pnpm build`), Phase 4 (`cost_usd` on the wire, fixed retry contract)

## Context

Phase 3 made the frontend *build*. Phase 4 fixed the backend endpoints the
SPA talks to. Neither made the SPA *correct*: the review found six
frontend defects that no test and no type error could see, because each
one is a behavioural bug in a component that compiles cleanly against a
type it is itself supplying.

The common shape is **state that is written in one place and read in
another, with nothing tying them together**:

- an effect that should run once depends on a value that changes often;
- an error variable that means "boot failed" is also assigned by a
  background refresh;
- a `useState` that means "this decision's edit" is only reset on two of
  the four buttons that can dismiss the modal;
- a countdown seeded from a server value that is refreshed out from under
  it, with a magic fallback when the server value is absent.

None of these produce a type error, a lint warning, or a failed test.
They produce a UI that lies to the user about what the server is doing.

## Decision

### 1. H10 — separate "boot once" from "refresh on selection"

```
refreshRuns = useCallback(..., [activeRunId])
useEffect(bootstrap, [refreshUploads, refreshRuns])
```

Because `refreshRuns` closes over `activeRunId`, the bootstrap effect —
which also calls `getConfig()` and re-applies `c.provider` / `c.model`
— re-runs on **every run selection**. The user's composer selection is
silently reset to the server default unless `loadLast()` happens to match.

**Decision:** give the bootstrap a `useRef` guard (`bootstrappedRef`) and
make it depend only on stable values (`refreshUploads`). `refreshRuns`
keeps its `activeRunId` dependency — re-resolving the active run on
selection is correct behaviour; re-running boot is not. A ref guard is
chosen over `useState` because the flag must not itself cause a render.

### 2. Error handling — three error channels, not one

A single `error` string is set by `refreshUploads`, the provider fetch,
`onOpenPath`, and the boot sequence. Any of them failing replaces the
entire application with `Cannot reach the smolcode web server`. A failed
thumbnail fetch is not a boot failure, and the screen lies about it.

**Decision:** split into three states with distinct lifetimes:

| State | Set by | Presentation |
|---|---|---|
| `fatalError` | `getConfig()` failing in the boot effect only | full-screen; the app cannot render |
| `transientError` | any non-fatal fetch (`refreshUploads`, providers, `onOpenPath`) | dismissible inline banner **with a Retry button**; app stays mounted |
| `error` (existing, for pane-local use) | unchanged | unchanged |

Every success clears the channel it could have set. The split is
deliberately *not* a generic error-handling library: the codebase has no
such dependency and the failure modes are three, not many.

### 3. ApprovalModal — reset keyed on decision identity

`editedAfter` is reset inside `approve()` and `deny()` but **not** in
`outsideDeny()` / `outsideApproveOnce()` /
`outsideApproveSessionForPath()`, and there is no effect keyed on
`decisionId`. Deny approval A, then approve B: B renders A's edited
diff. The user approves a file write containing content they never
reviewed.

**Decision:**
- reset `editedAfter` in a `useEffect` keyed on `pending?.decisionId`,
  so it resets on every identity change regardless of which button fired;
- give the modal `key={pending.decisionId}` at the call site so React
  remounts it per decision (defence in depth, and it makes the reset
  unconditional);
- add **Escape-to-deny** and a **focus trap**. A destructive confirmation
  dialog that cannot be dismissed with the keyboard traps keyboard and
  screen-reader users in it — an accessibility defect, not a nicety.

### 4. Finished-run history — snapshot, then stream

Selecting a finished run resets `events` to `[]` and opens a new
`EventSource`. The server has nothing left to stream, so the pane shows
"Waiting for events…" forever. The data exists: `RunManager.events_snapshot()`
already parses `events_log` into typed frames, and the export endpoint
uses it.

**Decision:** there was **no HTTP endpoint** for the snapshot, so one is
added: `GET /api/runs/{id}/events/snapshot` → `{"events": [...], "status": ...}`.
Additive; the SSE route is untouched. The SPA:
- fetches the snapshot on run selection and renders it immediately;
- opens an `EventSource` **only** when the run is non-terminal;
- for a terminal run, renders the snapshot and opens no stream at all.

This is the one place Phase 5 touches the backend, and it is unavoidable:
the frontend cannot hydrate from a method that is not reachable over HTTP.

### 5. Countdown and cost — seed from the server, fall back from config

`nowTick` counts up from mount and is never reset when the server's
`remaining_s` changes, so the countdown drifts by however long the run
has been open. When `remaining_s` is absent the fallback is a hardcoded
900 s, which is the *web wall-clock* default, not the tier's
`timeout_s`. And `<Inspector>` never renders `CostBadge` although the
ship report claims it does.

**Decision:**
- reset `nowTick` to 0 whenever `activeRun?.remaining_s` changes, via an
  effect keyed on that value;
- take the fallback from `config.tiers[activeRun.tier].timeout_s`, and
  only use the 900 s constant when the tier is unknown;
- render `CostBadge` using the `cost_usd` Phase 4 put on the wire.
  `CostBadge` already renders `--` for `null`, and the Inspector must
  **pass `cost_usd` straight through** rather than coercing a missing
  value to `0`. A `$0.00` badge reads as "this run was free"; the
  placeholder reads as "no rate is configured", which is the truth.

`CostBadge` already exists and has its own passing test; the defect is
purely that `Inspector` never imports it.

### 6. URL encoding and empty bodies on retry/rerun/export

`api.ts:880,888,900` build URLs by raw string concatenation while every
other helper in the file uses `encodeURIComponent`. A run id containing
`/` or `?` produces a request for a different resource.

`retryRun` also always sends `JSON.stringify(overrides ?? {})`. Phase 4
made the backend tolerate the empty body, so this is now harmless, but
it is still wrong: send **no body at all** when the caller passed no
overrides, so the backend's "inherit from parent" path is unambiguous.

**Decision:** `encodeURIComponent` on all three; omit the body entirely
when there are no overrides.

### 7. Lint warnings — fix or document, not ignore

`pnpm lint` reports 15 warnings; the docs claim 4. Each warning gets
either a real fix or a named suppression in the `oxlint` config **with a
reason string**. A silent suppression is worse than the warning.

Also fixes the one real e2e bug: `page.queryByRole` is a Testing Library
method, not a Playwright `Page` method. It is the only e2e failure.

## Consequences

**Accepted:**
- one new read-only backend endpoint (additive; nothing is removed);
- a `key` remount of `ApprovalModal` per decision, which discards any
  local UI state in it — correct here, because that state is exactly the
  leaked edit;
- a focus trap and Escape handling add code to a presentational
  component. This is the a11y cost of a modal that gates a destructive
  write, and it is not optional.

**Rejected:**
- a global error-management library — three failure modes do not justify
  a dependency;
- removing the 900 s constant — it is still the correct default when the
  tier itself is unknown;
- making the SSE endpoint serve snapshots via a query param — a separate
  route is unambiguous, cacheable, and cannot change SSE behaviour.

**Not in scope (Phase 7+):** `onOpenPath` is only a toast today;
multi-pane error routing, `tier.network_allowlist` surfaces, and the
`loadLast()` / server-default reconciliation policy beyond H10.

## Validation

```
pnpm lint            # 0 warnings (or each remaining one named in oxlint config)
pnpm typecheck       # 0 errors, strict: true
pnpm build           # 0 errors
pnpm test            # vitest, all green including the new Phase 5 specs
pnpm e2e             # Playwright, incl. the new finished-run spec
pytest src/smolcode/tests/test_events_snapshot.py   # the new BE endpoint
```

Each item above is written test-first, and the pre-fix failure is
recorded before the implementation lands. This is the Phase 3 rule
applied to the frontend: a green suite that mocks below the seam
certifies nothing, and Phase 4 showed exactly how that failure looks.
