# 0033 — Multi-browser Playwright matrix

**Date:** 2026-08-26
**Status:** applied (branch `feat/decision-0033` @ TBD)
**Closes:** TASKS.md §4 v1.9.x followup "Multi-browser Playwright matrix" (0.25d)

## Problem

The Playwright e2e suite (decision 0029) had been shipping on chromium-only. As the suite grew past 40 tests across 15 files (47 passed + 1 skipped after decision 0032), a single browser matrix left Firefox + Safari regressions invisible. Browser-specific bugs only surfaced when users hit them in production.

## Goals

- Add `firefox` and `webkit` projects to `playwright.config.ts` so the same 47 tests run on all 3 engines.
- Keep chromium, firefox, and webkit on the same code path with minimal per-project config so failures are attributable to the engine, not config drift.
- Fix any genuine cross-browser bugs uncovered by the matrix.

## Non-goals

- Mobile browsers (iPhone / Pixel profiles). Defer until the matrix is stable.
- Visual regression baselines (snapshots). Not requested.
- CI matrix changes. Local + future CI both pick up the project array unchanged.
- New tests. Only the existing 47 are run on each project.

## Design

### Config

`playwright.config.ts` now declares a `projects` array:

```ts
projects: [
  { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  { name: 'firefox',  use: { ...devices['Desktop Firefox'] } },
  { name: 'webkit',   use: { ...devices['Desktop Safari'] } },
],
```

Each project uses the same `webServer` (vite dev on :5173) and same `baseURL`. Per-project overrides are minimal — no `ignoreHTTPSErrors`, no viewport tweaks — so a test that passes in chromium and fails in webkit is a real webkit bug, not a config delta.

`pnpm exec playwright test --project=firefox` runs just one browser; `pnpm exec playwright test` runs all three sequentially (workers: 1, fullyParallel: false keeps ordering predictable for log inspection).

### Bug discovered + fixed: Ctrl+. stop race in webkit

**Symptom:** `keyboard.spec.ts: 'Ctrl+. posts /api/runs/{id}/stop when a run is active'` failed once on webkit with `expect(received).toBeTruthy()`. Passed in chromium + firefox.

**Root cause:** In `App.tsx`, the global keyboard router was installed with `useEffect(..., [activeRunId])`. After clicking the Run button:

1. `RunComposer.handle` fires `await startRun(...)` (captured by the test poll).
2. `onSubmitted(runId)` calls `setActiveRunId(runId)` on the parent.
3. The `useEffect` cleanup uninstalls the old listener and the new effect installs one with the new `activeRunId`.
4. The test then presses `Control+.` and the test poll resolves.

In webkit, the test's `Control+.` dispatch can happen between step 2 and step 3 — the old listener was already torn down, but the new one hadn't installed yet. The `postStop` call was never made.

**Pattern:** install the listener once and read live state via a ref. React state + `useEffect` re-installs are a closure-capture trap for global, time-critical handlers.

**Fix in `App.tsx`:** mirror `activeRunId` into a ref updated on every render, change the stop handler to read `activeRunIdRef.current`, and remove `activeRunId` from the `useEffect` deps (no longer needed):

```tsx
const activeRunIdRef = useRef<string | null>(null)
useEffect(() => { activeRunIdRef.current = activeRunId }, [activeRunId])
// ...
useEffect(() => {
  return installKeyboardRouter({
    // ...
    stop: () => {
      const id = activeRunIdRef.current
      if (id) void postStop(id).catch(() => { /* surfaced via the stream */ })
    },
    // ...
  })
}, []) // mounted once; live state via ref
```

This is also a small efficiency win (no listener reinstall on every run start).

### Test changes

None. All 47 existing tests run unchanged on each browser.

## Failure modes

| Failure | Browser | Status |
|---|---|---|
| HTML5 drag-drop in queue-reorder spec | chromium + firefox | passed; webkit | passed |
| `Control+.` stop shortcut timing | webkit | **fixed by ref mirror (App.tsx)** |
| Color contrast noise in vitest axe | jsdom (all browsers) | pre-existing, unrelated |

## Tests

- `pnpm exec playwright test` (all 3 projects): 141 passed, 3 skipped (47 × 3 = 141, plus 1 skip per project = 3 skipped).
- `pnpm exec vitest run`: 93/93 passed (no regressions).
- `pnpm exec tsc -b`: clean.
- `pnpm exec oxlint`: clean.

## Migration

None. Existing chromium-only CI invocations get firefox + webkit for free once the `projects` array is present. To pin a single browser locally: `pnpm exec playwright test --project=firefox`.

## Known limitations

- **Browser binaries**: firefox-1538 (153.0) and webkit-2336 (26.5) downloaded to `%LOCALAPPDATA%\ms-playwright\`. Already present on this machine from this session; new checkouts run `pnpm exec playwright install firefox webkit` (~150 MiB download, ~2 min).
- **Sequential, not parallel**: `workers: 1` + `fullyParallel: false` mean the 3 projects run one-after-another. Total time is ~6 min. Could parallelize across projects (project-level workers) for ~3 min savings but the suite is already CI-friendly and the serial timing aids debugging.
- **No mobile matrix**: iPhone 13 / Pixel 5 profiles deferred.
- **Smoke spec stays skipped on all browsers**: same SSE-bug reason as before (see 0030 followup note).

## Followups

- Consider project-level workers (`workers: { chromium: 1, firefox: 1, webkit: 1 }`) in a future pass for parallel browsers. Not blocking.
- Mobile matrix (0.5d) once the desktop matrix has been stable for 2 weeks.
- Ref pattern should be applied to other state that the global handlers depend on (currently only `activeRunId`; `dashboardOpen` is intentionally trigger-only, not live-state).
