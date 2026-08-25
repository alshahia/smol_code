# Decision 0030 — Fix EventStream.tsx SSE dispatch

**Date:** 2026-08-26
**Status:** shipped
**Owner:** applied
**Effort:** 0.25d (down from initial 0.5d estimate; turned out smaller than expected)
**Source task:** TASKS.md §4 — "Fix EventStream.tsx SSE dispatch" (newly added by decision 0029 §6.1 followup; supersedes the prior "approval modal never opens in production" risk listed in 0029).

## 1. Context

While implementing decision 0029 (full Playwright e2e suite), I wrote five approval + auto-approve tests against the production EventStream component path. All five failed. Three different workarounds inside the test files did not help — the tests were driving the real component, and the real component was the bug. The bug blocked those 5 e2e tests **and** silently broke production: the approval modal never opens for real users either, because the SSE frames from the BE never reach the React event loop.

The bug was filed in decision 0029 §6.1 "Known limitations" with this callout: *"this is a real production bug, not a test issue."* This decision fixes it.

## 2. Decision

### 2.1 Root cause

`smolcode/web/src/components/EventStream.tsx` (pre-fix, lines 117–160):

```tsx
const handler = (ev: MessageEvent) => {
  bufRef.current += ev.data + '\n'
  // ... parse SSE frames out of bufRef.current
}
es.onmessage = handler
```

The browser EventSource spec dispatches `onmessage` / `addEventListener('message', ...)` **only for default-type SSE events** (no `event:` line). For named events like `event: approval.requested\ndata: {...}\n\n`, the browser dispatches them to handlers registered via `addEventListener('approval.requested', ...)`. There is no catch-all wildcard.

The BE always emits named events:

```python
# smolcode/src/smolcode/web/runs.py:62-70
def _encode_event(event_type, data, event_id=None):
    payload = json.dumps(data, ...)
    lines = []
    if event_id:
        lines.append("id: " + event_id)
    lines.append("event: " + event_type)        # <-- always set
    for ln in payload.splitlines() or [payload]:
        lines.append("data: " + ln)
    return "\n".join(lines) + "\n\n"
```

So `es.onmessage = handler` **never fires**. The frame buffer never accumulates, `parseFrames` never sees a `curType`, and `dispatch` never reaches the parent callbacks. Approval modal stays closed. Run-end never registers. Step events never render. SubAgentBlock is always empty.

There were three layered bugs in the old code:

1. `onmessage` doesn't fire for named events — **primary**.
2. `bufRef.current += ev.data + '\n'` followed by `indexOf('\n')` (single newline, not `'\n\n'`) is broken frame framing — even if events did arrive they would not complete.
3. `parseFrames` requires `curType && dataBuf` but `curType` is only set when an `event:` line was seen — defense-in-depth that papers over bug #1.

### 2.2 Fix: dispatch via addEventListener per type

I replaced the buffer + `parseFrames` machinery with one `addEventListener` registration per known event type. Each MessageEvent already represents one complete SSE frame — `ev.data` is the JSON payload the BE encoded, so no SSE-frame parsing is needed in JS.

```tsx
const KNOWN_EVENT_TYPES: StreamEvent['type'][] = [
  'run.started', 'run.ended', 'plan.step', 'step.action',
  'step.final_answer', 'approval.requested', 'approval.decided',
  'diff.proposed', 'diff.resolved', 'error',
  'subagent.started', 'subagent.ended',
  'run.paused', 'run.resumed',  // BE emits these (runs.py:54-55) but the
                                // old StreamEvent union didn't include them.
  'end',
]

function parseEventData(type, dataStr) {
  if (!dataStr) return null
  try { return { ...JSON.parse(dataStr), type } as StreamEvent }
  catch { return null }    // malformed JSON; drop silently
}

// inside useEffect:
const dispatch = (type) => (ev) => {
  const evt = parseEventData(type, ev.data)
  if (!evt) return
  setEvents((prev) => [...prev, evt])
  if (type === 'approval.requested' && onApprovalRequest) onApprovalRequest(...)
  if (type === 'diff.proposed' && onDiffProposed) onDiffProposed(...)
  if (type === 'run.ended' && onFinal) { onFinal(evt.result, evt.error); setStatus(...) }
  if (type === 'end') { setStatus(...); es.close() }
}
for (const t of KNOWN_EVENT_TYPES) es.addEventListener(t, dispatch(t))
```

Tradeoffs considered:

| Approach | Pro | Con | Verdict |
|---|---|---|---|
| A. addEventListener per type (chosen) | tiny code change; matches BE 1:1; easy to reason about | future BE event types need a FE bump to be dispatched | chosen |
| B. switch to fetch + ReadableStream + custom SSE parser | one handler catches every event regardless of type; no per-type list to maintain | gives up EventSource auto-reconnect; larger refactor; more surface for bugs | rejected (premature) |
| C. listen on `onmessage` and have the BE send `type` in the data payload | simplest patch | BE format mismatch with M9 spec; breaks other consumers | rejected |

I also added `'run.paused'` and `'run.resumed'` to `StreamEvent['type']` in `api.ts` (additive — they're not new event types, the BE has emitted them since decision 0025, the union just didn't include them).

### 2.3 Test infra changes

`smolcode/web/e2e/_helpers.ts`:

- `mockSSE` now sets the `event:` line (matches real BE format). The old workaround (omit `event:`, embed `type` in the data payload) was a workaround for the EventStream bug; once the bug is gone, the mock should match production.
- `mockBackend` approval regex fixed: was `/api/runs/{id}/approvals$` (plural), is now `/api/runs/{id}/approval$` (singular) to match the actual FE `postApproval` URL in `api.ts:361`. The old plural was leftover from a different version of the endpoint and would have silently dropped the actual POST the SPA issues.

### 2.4 E2E test changes

`smolcode/web/e2e/approval.spec.ts` and `auto-approve.spec.ts`:

- Removed `test.skip` on all 5 previously-skipped tests.
- Fixed payload field names: `decisionId` → `decision_id` (snake_case is what the BE actually emits, see `agent_runner.py:377`).
- Removed the `kind: 'destructive'` field from the data — the SPA hard-codes `'destructive'` when it builds the modal (App.tsx:289); the BE never includes `kind` in the data payload.

## 4. Validation

- `pnpm tsc -b` → 0 errors
- `pnpm vitest run` → 74/74 pass (was 64/64; +10 new EventStream tests)
- `pnpm lint` → 12 warnings / 0 errors (all pre-existing in `src/`, 0 in new code)
- `pnpm build` → 259.81 KB / 78.29 KB gzip (was 259.92 KB / 78.36 KB; net code simplification from removing the buffer + parseFrames machinery)
- `pnpm exec playwright test` → **38 passed, 1 skipped, 0 failed** (was 34 passed, 5 skipped, 0 failed; +4 net pass, +5 SSE tests recovered). The remaining skip is the pre-existing smoke.spec.ts gate that requires a real BE (intentional, kept as-is).

## 5. Test catalog (new + changed)

| Test file | Status before | Status after | What it proves |
|---|---|---|---|
| `src/__tests__/EventStream.test.tsx` | did not exist | **NEW, 10 tests** | One unit test per code path (typed dispatch, named listener registration, malformed JSON drop, unmount, reconnect on runId change, end-of-stream close). |
| `e2e/approval.spec.ts` | 3 skipped | **3 active** | Modal opens on approval.requested, Approve/Deny POST to /api/runs/{id}/approval with correct body, "no more prompts" also POSTs /api/runs/{id}/auto-approve enabled=true. |
| `e2e/auto-approve.spec.ts` | 2 skipped | **2 active** | Banner appears after enabling via modal, Disable POSTs enabled=false and removes the banner. |
| `e2e/_helpers.ts` | workaround-only | matches BE format | mockSSE matches `runs.py:_encode_event` byte-for-byte; mockBackend regex matches FE `postApproval` URL. |
| `e2e/{shell,keyboard,composer,dashboard,inspector,run-actions,run-history,queue,sessions,upload,smoke}.spec.ts` | unchanged | unchanged | No regression. |

## 6. Files

```
smolcode/web/src/components/EventStream.tsx        | -50 / +41  (rewritten SSE dispatch)
smolcode/web/src/api.ts                            | +3 / -1   (add run.paused + run.resumed)
smolcode/web/src/__tests__/EventStream.test.tsx    | +228 / -0 (NEW)
smolcode/web/e2e/_helpers.ts                       | +12 / -28 (mockSSE matches BE; approval regex fix)
smolcode/web/e2e/approval.spec.ts                  | +44 / -34 (un-skip + field rename)
smolcode/web/e2e/auto-approve.spec.ts              | +62 / -10 (un-skip + field rename)
docs/decisions/0030-fix-eventstream-sse-dispatch.md| +NEW
TASKS.md                                            | +TBD / -TBD
```

## 7. Limitations / Followups

- **Unknown BE event types are silently dropped.** Same as pre-fix behavior; we just no longer drop the KNOWN types. Adding a new BE event type requires a FE bump (add it to `KNOWN_EVENT_TYPES` in EventStream.tsx and to `StreamEvent['type']` in api.ts). If this becomes a frequent papercut we could switch to approach B (fetch + ReadableStream). Not worth doing now.
- **RunHistory click does not update activeRun synchronously** (5s polling). Out of scope; not introduced by this decision. Existing inspector tests already use the submit pattern from decision 0029 §2.4.
- **3 vitest warning about "axe-core canvas not implemented"** is pre-existing jsdom noise; not introduced by this change.

## 8. References

- `smolcode/src/smolcode/web/runs.py:62-70` (_encode_event; the BE format)
- `smolcode/src/smolcode/web/runs.py:34-55` (EVT_* constants)
- `smolcode/src/smolcode/web/agent_runner.py:374-385` (approval.requested payload schema)
- `smolcode/web/src/components/EventStream.tsx` (the fixed component)
- `docs/decisions/0029-full-playwright-e2e-suite.md §6.1` (where the bug was first documented)
