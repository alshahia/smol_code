# Area Review — Frontend (React 19 + Vite SPA)

**Date:** 2026-08-26 · **Reviewer:** parallel review agent (all components/lib/config files fully read; backend contracts verified read-only; one empirical venv check) · **Status:** active

## Summary
Three-pane coding-agent console: live SSE event stream, approval/diff gating, queue/session/project management, provider/API-key handling, cost dashboard. Good shape overall — consistently structured components, defensive fetch patterns, zero HTML-injection sinks — but carries one real state-clobbering bug around provider/model selection, a silent wire-contract break disabling cost columns, a drifting wall-clock countdown, and several robustness/a11y gaps.

## Architecture notes
- App.tsx owns global state (config, 5s runs polling, provider/model/key selection, pending approval, auto-approve flags); leaf components mostly stateless or self-polling.
- All API access via src/api.ts (same-origin /api/*; Vite dev proxy to FastAPI on 127.0.0.1:7860; prod serves dist/). Types hand-maintained mirrors of schemas.py.
- SSE via named-event addEventListener per type (decision 0030), closed by backend end frame; no history replay by design.
- API keys plaintext in localStorage["smolcode.keys.v1"] (documented decision 0014); lastSelection/UI prefs non-sensitive.
- Linting oxlint (rules-of-hooks + only-export-components only); Vitest+Testing Library with v8 coverage thresholds; Playwright multi-browser smoke specs.

## Findings

1. **[HIGH] Provider/model selection reset to server defaults after every submit or history click** — App.tsx:174-193 (+163-172): initial-load effect depends on [refreshUploads, refreshRuns]; refreshRuns is useCallback(...,[activeRunId]); server default applied unconditionally; mount-only localStorage restore never re-runs. Any activeRunId change recreates refreshRuns ⇒ effect re-runs ⇒ selection silently reverted; next run executes against default provider/model (surprise billing/model) while lastSelection still holds the user's choice. Fix: bootstrap once (empty deps/ref guard) or restore from loadLast(); decouple initial load from polling callback identity.

2. **[MEDIUM] /api/dashboard drops cost_usd: response schema lacks the field the aggregator emits** — schemas.py:294-304 vs dashboard.py:28-38,115,148-156; consumer Dashboard.tsx:112-127. FastAPI validates via response_model so extra attribute stripped (verified empirically against project venv) ⇒ FE reads undefined ⇒ renders '--'. Cost columns + cap progress never show real data despite decision 0032; FE type TokenSummary.cost_usd is a lie on the wire. Fix: add cost_usd to schemas.TokenSummary.

3. **[MEDIUM] Wall-clock countdown drifts ~2× fast and shows premature "timed out"** — Inspector.tsx:41,61-85,147-160: nowTick accumulates per second while remainingServer refreshes every ~5s, each poll re-subtracting elapsed again. 15-min budget hits zero in ~half. MAX_RUN_WALL_S_FALLBACK=900 hardcoded although TierSummary.timeout_s is available. Fix: tick counter reset on each remaining_s change; render from matched tier timeout_s.

4. **[MEDIUM] Any transient error replaces the whole app with an unrecoverable error screen** — App.tsx:392-402,154-161,189-192: setError called from routine paths (uploads fetch catch, providers fetch, approval failure); no retry/dismiss; unmounts everything mid-run killing the EventStream subscription. Fix: scope errors to producing panels; global screen only for initial getConfig failure; retry affordance.

5. **[MEDIUM] ApprovalModal leaks edited content across consecutive approvals** — ApprovalModal.tsx:53-67 + App.tsx:306-335: editedAfter cleared only in approve()/deny(); new diff.proposed swaps payload without remount (no key={decisionId}) ⇒ effectiveAfter shows previous file's edited text as new "after"; Approve sends B with A's content — wrong file written. Fix: key card by decisionId or reset editedAfter on change. Related: no focus trap/Escape handling despite aria-modal.

6. **[MEDIUM] EventStream captures callbacks/stale status once per run; high-frequency re-render cost grows unbounded** — EventStream.tsx:130-196,203-240: deps [runId] with inert eslint-disable comment (oxlint enforces nothing); handlers captured at mount (safe today only by closure luck); `if (type==='end') setStatus(String(evt.status || status))` reads first-render status; every SSE event does setEvents(prev=>[...prev]) re-keying whole transcript (index keys), no virtualization/memo. Fix: refs for handlers; functional status updates; chunked rendering/virtualization; stable keys.

7. **[MEDIUM] Selecting a finished or past run shows a permanently empty stream** — EventStream.tsx:130-134 vs runs.py:870-892: subscribe() tails a per-connection queue with no replay; terminal run idles 15s then yields only end frame. Clicking any RunHistory entry (primary navigation) renders "Waiting for events…" then "SSE: done" with no transcript — history looks broken. Fix: hydrate from events snapshot endpoint before/alongside live subscription.

8. **[MEDIUM] TypeScript strict mode off** — tsconfig.app.json / tsconfig.node.json lack "strict"/strictNullChecks; many unverified `as Error`/`as PendingApproval['hunks']` casts. Fix: enable strict (+noUncheckedIndexedAccess ideally) and fix fallout deliberately.

9. **[MEDIUM] Keyboard/screen-reader gaps on interactive non-button elements and dialogs** — QueuePane.tsx:346-352 ActiveRow role=button tabIndex=0 but no onKeyDown; RunHistory.tsx:145-150 rows not focusable at all; UploadDropZone.tsx:65-73 div lacks Enter/Space; WorkspaceTree directory toggles span role=button without tab stop/keys (file rows do it correctly); FileMentionInput listbox on buttons without combobox wiring/aria-activedescendant; Dashboard overlay + ApprovalModal don't trap focus or close on Escape; axe runs in dev but nothing gates it. Fix: reuse NodeRow pattern everywhere; Escape/focus-trap both modals; combobox wiring.

10. **[LOW] Provider API keys stored plaintext in localStorage** — keysStore.ts:6,35-42 raw strings indefinitely, silent-failure writes. Real mitigations exist (loopback origin, keys leave only in /api/runs body, masked input, two-click Forget, server-side whitelist) and tradeoff documented (0014) hence LOW. Fix options: sessionStorage/don't-persist mode; clear-on-close default; WebCrypto wrap as speed-bump only.

11. **[LOW] Duplicate TokenSummary interface declarations merge silently with wrong required field** — api.ts:130-134 vs 761-767: declaration merging makes cost_usd required on ALL summaries incl. RunSummary.tokens where BE never sends it; hides finding-2 mismatch. Fix: single declaration; optional field on dashboard variant only.

12. **[LOW] retryRun/rerunRun/exportRun skip URL-encoding of run id** — api.ts:835,843,855 string concat vs encodeURIComponent elsewhere. Fix: encode uniformly.

13. **[LOW] Small dead/broken or misleading bits** — package.json test:a11y targets nonexistent src/__tests__/a11y (script always fails); UploadDropZone hardcoded "up to 50 MB" vs authoritative upload_max_bytes; hardcoded endpoints (vite proxy 7860, error-screen 7860, playwright 5173) consistent for dev loop but not env-overridable; UsageLimitsPanel "Saved." flash never cleared; WorkspaceTree setTimeout(refresh,0) not cleared on unmount (same class in ApiKeyPanel).

14. **[INFO] Contract/type drifts currently harmless** — FE ModelInfo[] vs BE models: list[str] (only .length used); WorkspaceTreeResponse max_entries/max_depth declared but never sent/read.

15. **[INFO] FE/BE mention-parser edge divergence** — mentions.ts/FileMentionInput vs agent_runner.py:107-108: identical fence regexes (good), but BE path charset accepts backslash while FE rejects ⇒ hand-typed @dir\file counted differently in the "N mentions" chip vs BE expansion.

16. **[INFO] SSE contract coupling + reconnect behavior** — KNOWN_EVENT_TYPES must manually mirror backend EVT_* constants (currently in sync incl. end close-frame); unknown future types dropped silently; EventSource auto-reconnect enters fresh tail queue (no duplicates; gap events lost forever — ties to finding 7).

## Strengths
1. No XSS surface: zero dangerouslySetInnerHTML anywhere; all model/tool output rendered as escaped text nodes/pre (verified in every component).
2. Disciplined async hygiene: consistent cancellation-flag pattern across fetchers; proper interval/listener cleanup; StrictMode-safe SSE lifecycle; activeRunIdRef avoiding keyboard-router reinstall.
3. Thoughtful UX states and optimistic consistency: distinct loading/empty/error/note states everywhere; queue reorder optimistic with server-authoritative reconciliation and rollback+refetch; accessible up/down fallbacks with aria-labels.
4. Defensive local-storage modules: shape validation on read, size/entry caps, normalization, fail-silent-but-safe, inline decision references.

## Coverage
Fully read: api.ts, App.tsx, main.tsx; all 31 component files; all 5 lib files; package.json, vite/vitest configs, tsconfigs, playwright.config, .oxlintrc.json, index.html, App.css. Skimmed: index.css (head + targeted greps; 1387 lines). Followed out-of-scope for verification: schemas.py (full), api.py route map + events/dashboard/tree handlers, runs.py EVT constants/_encode_event/subscribe, agent_runner mention parser, diffs.py walk_tree normalization, dashboard.py aggregation; one empirical venv check confirming Pydantic strips cost_usd under from_attributes validation. Not read: unit/e2e specs, dist/, node_modules. No files modified.
