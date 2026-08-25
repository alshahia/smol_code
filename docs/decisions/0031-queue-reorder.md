# Decision 0031 — Drag-and-drop queue reorder

**Date:** 2026-08-29
**Status:** shipped
**Owner:** applied
**Effort:** 1d (matches the §4 spec estimate)
**Source task:** TASKS.md §4 — "Drag-and-drop queue reorder" (1d effort, originally from Phase 2 §6.4 / decision 0025 §8; deferred in 0025 §10.3 user confirmed yes defer to v1.9.x).

## 1. Context

Decision 0025 §2.2 / §8 designed the queue as "run them sequentially with pause/reorder" — FIFO plus a UI for manual reordering — but the reorder UI was explicitly deferred (0025 §10.3) because we needed shipping signal first.

v1.8.x shipped the queue + cancel + auto-drain (decision 0025 Phase 2, decisions 0026–0029) and the SSE dispatch fix (0030). The queue works: every run while busy is auto-enqueued, the user can cancel queued entries, and the active run drains the queue FIFO on completion. But the SPA cannot reorder the queue today — the only user agency is cancel-and-retry.

This decision closes that gap. The reorder UI must:

- work for users without a screen reader (mouse / trackpad drag-and-drop)
- work for keyboard / screen-reader users (visible ↑/↓ buttons per row)
- not regress the existing cancel UX
- not introduce a new dependency
- stay consistent with the rest of the QueuePane styling

## 2. Decision

### 2.1 API: `PATCH /api/queue/{run_id}`

A new endpoint accepts a 1-based position and atomically reorders the FIFO list:

```
PATCH /api/queue/{run_id}
Content-Type: application/json

{"position": 2}

→ 200 OK
{
  "run_id": "abc",
  "position": 2,
  "queue": [/* QueueEntryOut dicts, 1-based queue_position re-stamped */]
}
```

Contract:

- `position` is 1-based; `position=1` is the head, `position=len` is the tail.
- Values outside `[1, len(queue)]` are **clamped** server-side, not rejected. This lets the FE compute the clamp locally and still hit a 200 even after a concurrent cancel rearranges the queue under it.
- Returns 404 only when `run_id` is not currently in the queue (genuine stale id, not a position computation error).
- Pydantic rejects `position` types other than int with 422. (`"1"` → coerced to `1`; `1.5` → rejected; `true` is coerced to `1` by Pydantic v2 default. This matches existing Pydantic v2 behavior across the API and is documented in `test_patch_queue_non_int_position_returns_422`.)
- The response carries the **full updated queue** so the FE patches local state without a follow-up GET round-trip.

### 2.2 Implementation: `RunManager.move_queue(run_id, new_position)`

New method on `RunManager` between `cancel_queue` and `_refresh_queue_positions` (runs.py:1073-1106). Atomic pop+insert under `_queue_lock`; `_refresh_queue_positions()` runs after the lock is released to keep each Run's `queue_position` in sync.

```python
def move_queue(self, run_id, new_position):
    if not isinstance(new_position, int) or isinstance(new_position, bool):
        raise ValueError("new_position must be an int")
    with self._queue_lock:
        ids = [e.id for e in self._queue]
        try:
            cur_idx = ids.index(run_id)
        except ValueError:
            return None
        n = len(self._queue)
        target_1based = max(1, min(int(new_position), n))
        target_0based = target_1based - 1
        if target_0based == cur_idx:
            pass  # no-op
        else:
            entry = self._queue.pop(cur_idx)
            self._queue.insert(target_0based, entry)
    self._refresh_queue_positions()
    return target_1based
```

### 2.3 Deadlock found by tests (and fixed)

The first version called `self._refresh_queue_positions()` inside the `_queue_lock` block in the no-op branch:

```python
with self._queue_lock:
    ...
    if target_0based == cur_idx:
        self._refresh_queue_positions()   # <-- re-enters _queue_lock
        return target_1based             # <-- DEADLOCK on every no-op move
```

`_refresh_queue_positions` itself takes `_queue_lock`, and `threading.Lock` is not reentrant. A no-op PATCH would have hung the worker forever in production. The unit test `test_move_to_same_position_is_noop` would have hung too — which is exactly what the test caught (10s timeout). Fix: hoist the `_refresh_queue_positions()` call out of the lock for both branches; the no-op branch just `pass`es inside the lock and refreshes after.

This is the kind of bug that only the BE unit test for the no-op branch catches. Both the BE and FE commit together so this is a clean story.

### 2.4 FE: HTML5 drag-and-drop + keyboard ↑/↓ buttons

`<QueuePane>` (`smolcode/web/src/components/QueuePane.tsx`) now renders each row as `<li draggable={true}>` with:

- ↑ / ↓ buttons (always visible, `aria-label="Move {task} up/down"`); the head row's ↑ and tail row's ↓ are `disabled`.
- HTML5 drag handlers: `onDragStart` records the dragged id in a ref (no React re-render), `onDragOver` computes "above" / "below" by the row's midpoint and toggles a `drag-over-above` / `drag-over-below` CSS class for the drop indicator, `onDrop` converts midpoint to a 1-based target slot, `onDragEnd` clears visual state.
- An optimistic update: locally reorder + re-stamp `queue_position`, then PATCH; on PATCH failure, refetch from BE and persist the error banner.
- The Cancel button text becomes "Working…" while a move is in flight (shared `busyId` flag).

Tradeoffs considered:

| Approach | Pro | Con | Verdict |
|---|---|---|---|
| A. HTML5 native drag-and-drop + keyboard ↑/↓ buttons | no new dependency; modern browser coverage; keyboard a11y included | hand-written drop-target math (above/below midpoint); no touch support | **chosen** |
| B. `@dnd-kit/core` (~12 KB gzip + 1 transitive dep) | touch support out of the box; battle-tested DnD semantics | new dependency for a small SPA surface; CLAUDE.md forbids deps unless necessary | rejected |
| C. Keyboard-only reorder (no DnD) | tiny UI surface; zero drag-and-drop testing burden | drops the most natural UX for the most common case (mouse user with 5+ queued runs) | rejected |

The SPA already had `MoveUp` / `MoveDown` keyboard accessibility available elsewhere (the Move-up/down pattern in run history); the same UX applies here.

### 2.5 CSS additions

`smolcode/web/src/index.css` gained the missing queue-pane CSS (the existing `QueuePane.tsx` referenced `.queue-row`, `.queue-pane`, `.queue-list`, `.active-row` classes but no matching rules existed in the stylesheet — they were rendered with browser defaults). New rules:

- `.queue-row[draggable='true']:hover` → `cursor: grab`
- `.queue-row.dragging` → `opacity: 0.4` + `cursor: grabbing`
- `.queue-row.drag-over-above` → `border-top: 3px solid #3b82f6`
- `.queue-row.drag-over-below` → `border-bottom: 3px solid #3b82f6`
- Container + row backgrounds, position pill styling, button alignment

The new CSS is purely additive — no existing rules were modified.

### 2.6 Refresh-doesn't-clear-err (small UX fix)

`QueuePane.refresh()` previously called `setErr(null)` on every successful GET. The reorder catch path does `setErr(...)` then `refresh()`, so a transient PATCH failure (e.g. race against a concurrent cancel) would flash the error and immediately clear it before the user could read it. I removed the `setErr(null)` from `refresh()`. Errors now persist until the next user-driven action succeeds, matching the existing Cancel error UX.

## 3. Validation

- `make quality` (ruff check + ruff format --check) → 0 new violations (2 pre-existing I001/F401 in `test_web_runs_api.py:382-386` + 3 ruff-format `--check` failures pre-existing from decision 0030; all out of scope for this decision)
- `pytest src/smolcode/tests` (with coverage) → all tests pass; coverage threshold (80%) preserved (no new uncovered modules)
- `pnpm test` → 84/84 pass (was 74/74; +10 new QueuePane tests)
- `pnpm build` → 0 TS errors; bundle 262.49 KB / 79.16 KB gzip (+0.57 KB / +1.00 KB gzip for the new component logic + CSS)
- `pnpm lint` → 12 warnings / 0 errors (all 12 pre-existing; no new warnings in the QueuePane file)
- `pnpm test:e2e` → 44/44 pass (was 38/38; +5 new queue-reorder tests, 1 queue.spec.ts regression fixed by tightening the Cancel-button selector)

## 4. Test catalog (new + changed)

| Test file | Status before | Status after | What it proves |
|---|---|---|---|
| `src/smolcode/tests/test_queue.py` `TestMoveQueue` | did not exist | **NEW, 11 tests** | middle→head, tail→head, head→tail, no-op, unknown id, non-int, bool subclass rejection (bool is int subclass), clamp above, clamp below, single-entry no-op, empty-queue None |
| `src/smolcode/tests/test_web_runs_api.py` `TestRunsQueueMove` | did not exist | **NEW, 7 tests** | happy path with reordered positions, clamp above, clamp below, unknown id 404, float → 422, empty queue 404, same-position no-op |
| `smolcode/web/src/__tests__/QueuePane.test.tsx` | did not exist | **NEW, 10 tests** | render with 3 rows, ↑ / ↓ buttons fire correct PATCH, head/tail button disabled, single-entry buttons disabled, dragstart sets .dragging, drop calls PATCH with clamped target, PATCH 404 → error banner + refetch, dragend clears .dragging, cancel disabled while in-flight |
| `smolcode/web/e2e/_helpers.ts` | no PATCH branch | **PATCH /api/queue/{id} branch + move_queue_response + delays.move_queue** | E2E can drive reorder success / failure paths |
| `smolcode/web/e2e/queue-reorder.spec.ts` | did not exist | **NEW, 5 tests** | ↓ PATCHes with position=2, ↑ PATCHes with position=1 + head/tail disabled, dragTo → PATCH with clamped position, single-entry disabled, PATCH 404 → error banner + refetch |
| `smolcode/web/e2e/queue.spec.ts` | broad `.queue-row button` selector (worked when there was 1 button per row) | **tightened to `getByRole('button', { name: /^Cancel$/ })`** | regression: my new ↑/↓ buttons broke the broad selector |

## 5. Files

```
smolcode/src/smolcode/web/runs.py                | +37 / -0   (move_queue method, +deadlock fix)
smolcode/src/smolcode/web/schemas.py             | +22 / -0   (QueueMoveRequest + QueueMoveResponse)
smolcode/src/smolcode/web/api.py                 | +52 / -0   (move_queue_entry endpoint + import + docstring)
smolcode/src/smolcode/tests/test_queue.py        | +147 / -0  (TestMoveQueue class + QueueEntry import)
smolcode/src/smolcode/tests/test_web_runs_api.py | +121 / -0  (TestRunsQueueMove class)
smolcode/web/src/api.ts                          | +20 / -0   (QueueMoveResponse + moveQueueEntry)
smolcode/web/src/components/QueuePane.tsx       | +177 / -49 (DnD handlers + keyboard buttons + reorder() + QueuedRow)
smolcode/web/src/index.css                       | +99 / -0   (.queue-* CSS + drag states)
smolcode/web/src/__tests__/QueuePane.test.tsx    | +227 / -0  (NEW vitest)
smolcode/web/e2e/_helpers.ts                     | +26 / -0   (PATCH branch + move_queue_response + delays.move_queue)
smolcode/web/e2e/queue-reorder.spec.ts           | +166 / -0  (NEW Playwright)
smolcode/web/e2e/queue.spec.ts                   | +3 / -2    (Cancel selector fix)
docs/decisions/0031-queue-reorder.md             | +NEW
TASKS.md                                         | +TBD / -TBD
```

## 6. Limitations / Followups

- **No touch support.** HTML5 native drag-and-drop doesn't fire on mobile / tablet browsers. If users start reporting mobile usage, switch to `@dnd-kit/core` (rejected today per CLAUDE.md "do not introduce a dependency unless necessary") or a hand-written touch handler.
- **Race condition: a move issued just as the active run drains could move the wrong entry.** The BE clamps to `[1, len(queue)]`, so the entry snaps to the nearest valid slot — never a 422 — but the user might see a different entry than expected. This is the same trade-off as auto-FIFO; the SPA polls every 5s so the visual state corrects within 5s.
- **The SPA's error banner persists across refreshes** (UX fix in 2.6). If a user dismisses the banner manually there's no current path — refresh is the only way to clear it. Consider adding a small × button on the banner in a followup. Out of scope for 0031.
- **2 pre-existing ruff check violations** in `test_web_runs_api.py:382-386` (I001 import order + F401 unused `build_tools`) and **3 pre-existing ruff format issues** in the same file predate this decision. Not addressed here; trivial cleanup for a followup commit.

## 7. References

- `smolcode/src/smolcode/web/runs.py:1073-1106` (`move_queue` implementation + deadlock fix)
- `smolcode/src/smolcode/web/runs.py:1108-1120` (`_refresh_queue_positions`, called outside the lock)
- `smolcode/src/smolcode/web/api.py:1142-1183` (PATCH endpoint)
- `smolcode/src/smolcode/web/schemas.py:521-540` (QueueMoveRequest + QueueMoveResponse)
- `smolcode/web/src/components/QueuePane.tsx` (rewritten with DnD + keyboard + reorder)
- `smolcode/web/src/api.ts:443-470` (moveQueueEntry + QueueMoveResponse)
- `docs/decisions/0025-web-ui-ux-review-and-roadmap.md §8 / §10.3` (original design + deferral)
- `TASKS.md §4` (the "Drag-and-drop queue reorder" spec row)
