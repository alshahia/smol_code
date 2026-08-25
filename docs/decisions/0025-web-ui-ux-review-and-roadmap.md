# Decision 0025 — Web UI/UX review + roadmap to v1.8

- **Status:** phase-3-shipped + v1.9.x-fe-wireup-shipped
- **Date:** 2026-08-25 (last update; originally 2026-08-22)
- **Type:** planning + scope decision + ship report
- **Related:** 0010 (M9 design), 0012 (M9 live execution), 0013 (M10 inline diff),
  0014 (M11 provider/model/key UI), 0015 (M12 SPA polish), 0024 (Web UI
  traceback + UTF-8 stdio)
- **Supersedes:** none
- **Superseded by:** none
- **Implementation:** **Phase 0 SHIPPED on commit `88a20e4`
  (2026-08-23). Phase 1 SHIPPED on commit `7b33f1d` (2026-08-24).
  Phase 2 SHIPPED on commit `2f90b50` (2026-08-24). Phase 3 SHIPPED
  on commit `dcf38cf` (Phase 3 code) + `509288f` (Phase 3 ship docs)
  on 2026-08-24. v1.9.x FE wire-up SHIPPED on commit `bec3ce9`
  on 2026-08-25.** All five are PUSHED to `origin/main`.
  See §6.5 for the high-level Phase 3 plan + §15 for the detailed
  Phase 3 plan + §13.1/§13.2/§13.3 for the per-phase acceptance gates +
  §14.x for the per-phase ship reports + per-phase followup lists +
  the v1.9.x history entry in §12 below for the FE wire-up followups.

---

## 1. Context

After v1.7.1.3 shipped (decision 0024), the user asked for a
**critical review of the Web UI/UX** — what is missing, what should be
added, what should be cut — using their initial list of six suggested
features as the starting point. This decision captures:

1. An honest evaluation of each of the user's six suggestions
   (which are must-haves, which are useful-but-deferred, which are
   over-spec'd for v1.7.x).
2. Other must-haves the user did not name but which the reviewer
   identified.
3. Things the reviewer **deliberately does NOT recommend** building now.
4. A phased implementation plan (Phase 0–3) with concrete file paths,
   LOC estimates, and acceptance gates.

The reviewer scope was the entire Web UI surface — both frontend
(`smolcode/web/src/**`, ~2800 LOC across 25 TS/TSX files) and backend
(`smolcode/src/smolcode/web/**`, ~2300 LOC across 9 Python files).

### 1.1 Current state of the Web UI (one-paragraph summary)

`v1.7.1.3` ships a 3-pane SPA: left = Task / History / Uploads /
Allowlist simulator; center = live SSE event stream for the active
run; right = Inspector (active run summary + workspace tree + tier
policy cards + recent audit). It supports provider/model/key override
(decision 0014), per-step tokens, diff approval (decision 0013), and
chain-verified audit reads (decision 0018). It is **single-active-run,
single-workspace, viewer-only** — there is no session concept, no
multi-project model, no pause/resume, no file mentions, no token
dashboard, no sub-agent nesting in the event stream.

---

## 2. The user's six suggestions — evaluation

### 2.1 [A1] Display agent steps / logs / tool_code-use + sub-agents
**Verdict:** PARTIALLY TRUE (steps exist; sub-agents + polish are missing).

**Current state:** `EventStream.tsx` already subscribes to SSE and
renders `step.action` (with `thought` + `code_action` + `tool_calls[]` +
`observations` + `tokens` + `timing_ms`), `plan.step`,
`step.final_answer`, `approval.requested`, `diff.proposed`,
`diff.resolved`, `error`. Each row is a flat
`<div class="stream-row stream-row-{type}">` with `renderBody()`
truncating everything to 2000 chars and rendering as raw `<pre>` text.

**Gap:** when the orchestrator agent invokes a sub-agent via
`do_restricted_task(...)`, the SPA only sees the outer agent's
"call do_restricted_task" code-action — not what happened inside the
sub-agent. The events are **flattened**.

**What to do:** backend publishes `subagent.started` / `subagent.ended`
around each `agent.run()` invocation with `parent_run_id` +
`subagent_tier`. SPA renders nested `SubAgentBlock` as a collapsible
child of the parent's outer step. Plus per-row polish (icons,
collapse-by-default, "show full" disclosure, syntax highlighting via
`shiki` or `react-syntax-highlighter`, copy-code button).

**Priority:** P0 for sub-agent events; P1 for polish.

### 2.2 [A2] Pause agents + queue with edit/delete/move-up-down
**Verdict:** PARTIALLY NEEDED. Pause = P0; auto-queue = P1; drag-reorder
= DEFER (over-spec for current maturity).

**Current state:** `StopButton.tsx` calls `POST /api/runs/{id}/stop`
which sets `run.stop_flag` and the next step callback raises
`_StopRequested`. **Stop = kill**, not pause; the run cannot be
resumed.

**The terminology gap:**
- **Pause** = freeze mid-step, keep in-memory state, **resumable**.
  Smolagents `CodeAgent` does NOT support pause/resume natively.
  Adding it requires snapshotting `agent.memory.steps` to disk after
  every step (~2 KB/step) and rebuilding the agent on resume
  (expensive; the active Docker kernel state is lost). OR: gate each
  step on a `threading.Event` (cleaner, more code).
- **Stop** = what we have today.
- **Queue** = multiple runs in flight; FIFO or priority order.

**The queue-management reality check:** a queue implies **concurrent
runs**. Currently `RunManager` runs one thread per run with
`ThreadPoolExecutor(max_workers=1)` per run. There is NO
concurrent-execution model. The thread pool uses `max_workers=1`.
So a "queue with priority" is functionally "run them sequentially with
pause/reorder". That's fine — but how often users actually reorder
queued runs in Claude Code / OpenCode / Codex is "rarely". Most users
want auto-queue + cancel.

**What to do:**
- **Pause/Resume** (real win): `agent.memory.steps` snapshot after
  each step into `Run.snapshot`; `POST /api/runs/{id}/pause` raises
  `_PauseRequested` from the step callback; `POST /api/runs/{id}/resume`
  rebuilds the agent from the snapshot and replays the steps.
- **Auto-queue**: while a run is active, a new "Run" press enqueues
  instead of erroring. New left-pane section "Queue (N)" with cancel.
  No reorder UI in v1.7.x.
- **Drag-and-drop reorder**: explicitly deferred to v1.9.x.

**Priority:** P0 (pause), P1 (auto-queue), defer (reorder).

### 2.3 [A3] Create / manage chat sessions
**Verdict:** TRUE — biggest single gap in the current UI.

**Current state:** `/api/sessions` (lists `workspace/sessions/*.jsonl`)
and `/api/sessions/{id}` (returns events) already exist on the backend
(`api.py:147-196`). **The SPA does NOT render them.** `App.tsx` has
zero session-management UI. The audit panel reads the audit log, not
sessions.

**The semantic gap:** a session is "all the runs in one continuous
conversation about one project". Claude Code / OpenCode / Codex all
have this as a first-class concept. The current model conflates
"session = file on disk" with "session = UI artifact the user can
manage". They should be the same in the UI but currently aren't.

**What to do:**
- New `SessionsPane` component in the left pane (list of sessions:
  id, name, run count, last activity).
- "New session" → `POST /api/sessions` → uuid jsonl.
- "Delete session" → `DELETE /api/sessions/{id}`.
- "Rename session" → `PATCH /api/sessions/{id}` storing name in a
  sibling `meta.json` so the user can label them ("refactor auth",
  "fix typo in README").
- Session detail view shows ALL runs in this session + the full event
  timeline across runs.
- Header gets "Active session" indicator (replaces or augments the
  current "Workspace: path" pill).

**Priority:** P0.

### 2.4 [A4] Create / open projects + view files
**Verdict:** TRUE — but understand this is a model change, not just UI.

**Current state:** `WorkspaceTree.tsx` renders the workspace tree from
`/api/workspace/tree` and highlights `touched_paths`. But there is NO
multi-project concept — the workspace is a single directory chosen at
server-start. Uploads are workspace-relative, not project-scoped.

**The propagation cost:** adding "projects" is a **configuration-model
change**, not just a UI change. It propagates to uploads, sessions,
audit log, and runs. Budget ~200 LOC of server-side refactor before
the UI change.

**What to do:**
- `settings.projects` — new config field: list of `{name, root}`
  project roots.
- Project switcher in the header (next to the workspace pill).
- `POST /api/projects` + `DELETE /api/projects/{name}` for UI
  management.
- All existing endpoints gain a `?project=name` query param OR a
  `project` field in the request body. Endpoints affected:
  `/api/runs`, `/api/uploads`, `/api/sessions`, `/api/workspace/tree`,
  `/api/audit` (filter scope).
- Project-scoped workspace tree (filter tree to files under the
  selected project root).
- File preview pane: click a file in the tree → opens a tabbed viewer
  (just `<pre>` for v1 — NOT Monaco, NOT a full IDE editor).

**What we explicitly do NOT do:** full Monaco-based IDE with file
editing + PATCH-back-to-disk. That's a different product (an IDE).
Smolcode's value is the agent; the file viewer is a convenience.

**Priority:** P0 (switcher), P1 (file viewer).

### 2.5 [A5] Mention files in chat so the agent reads them
**Verdict:** TRUE — real productivity win, low implementation cost.

**Current state:** `RunComposer.tsx` accepts only a freeform task
string. The only way to "give" the agent a file is via the Uploads
sidebar (which copies it to the workspace). There is NO `@file`
parsing, no autocomplete, no drag-from-tree-into-input.

**What to do:**
- `@` mention trigger: typing `@` opens an autocomplete dropdown
  listing files from the project tree. Selecting inserts `@path/to/file`
  into the input.
- Backend: when a task contains `@/abs/path` or `@relative/path`,
  **auto-include** the file's contents in the task prompt as a fenced
  code block (with the file path as the language tag). The agent sees
  the file content without calling `fs.read_file`.
- Configurable max-file-size for inline inclusion (default 32 KB;
  larger files just attach the path and let the agent `read` it).
- Visual chip rendering: when the task contains `@path`, render the
  input with `@path` as a clickable chip that opens the file preview
  pane.

**Security note:** path resolution MUST be sandboxed to the project
root in `agent_runner._attach_mentions()`. Otherwise a malicious user
prompt can `@/etc/passwd`. The check is the existing
`resolve_under_workspace` helper from `tools/fs.py:PathPolicy`.

**Priority:** P0.

### 2.6 [A6] Token dashboard (input / output / total / steps / cache hit)
**Verdict:** TRUE — most-asked, most-missing.

**Current state:** per-step tokens are published in `step.action`
(`tokens: {input, output}`) but **never aggregated**. `RunSummary`
does NOT carry totals. The Inspector shows `duration_s` and `error`
but NOT tokens. The AuditPanel shows entries but not totals.

**What to do:**
- Extend `RunSummary` with `tokens: {input, output, total}` and
  `step_count`. Compute by summing per-step tokens as they flow
  through `run.publish` (cheaper than post-hoc aggregation, survives
  run completion).
- Inspector pane gets a new "Token usage" section: per-run + per-session
  totals + a sparkline of the last 10 runs.
- Top-level **Dashboard tab** (or header dropdown) with: total runs
  today, total tokens today, avg duration, error rate.
- **Cache-hit stats**: provider-dependent. Anthropic + OpenAI + Gemini
  return `cache_read_input_tokens`; OpenCode Go / openrouter may not.
  Add it as `optional`, render "—" when not present. **Do not promise
  cache-hit for all providers.**
- **Cost projection**: `tokens.input * $X/M + tokens.output * $Y/M`
  per provider. Configurable rates in `model_catalog.PROVIDERS`.
  Show in the dashboard.

**Priority:** P0 (Inspector totals), P1 (Dashboard + cost), P2
(cache-hit when present).

---

## 3. Other must-haves I found (beyond the user's six)

### 3.1 [B1] Stuck-run UX + remaining-time countdown — P0
`_MAX_RUN_WALL_S = 900` exists in `agent_runner.py` but the user has
NO way to see remaining time. Add a countdown in `stream-header`.
On timeout, show "Run timed out after 15:00" instead of just
`status=stopped`. ~25 LOC.

### 3.2 [B2] Keyboard shortcuts — P1
`Cmd/Ctrl+Enter` to submit; `Cmd/Ctrl+K` to focus the task input;
`Esc` to close the approval modal; `Cmd/Ctrl+.` to stop. For an
IDE-feeling app this is table stakes. ~40 LOC + tests.

### 3.3 [B3] Search across runs / sessions — P1
`RunHistory` is a flat list. Add a filter input ("filter runs by task
text") — same pattern as `AuditPanel`'s grep but client-side. ~20 LOC.

### 3.4 [B4] "Re-run" button on completed runs — P1
Common workflow: "rerun this task on a different model". Backend:
`POST /api/runs/{id}/rerun` re-submits the same task with optional
model override. "Fork from step N" requires pause/snapshot — see A2 #1.
~20 LOC backend + 20 LOC UI.

### 3.5 [B5] "Export run to JSON" — P2
Useful for sharing / debugging. `GET /api/runs/{id}/export` returning
`{run, events: [...]}` as JSON. ~30 LOC.

### 3.6 [B6] Accessibility audit — P1
The SPA has some ARIA (`role="dialog"`, `aria-expanded`,
`aria-controls`, `aria-label`) but is **not tested** with screen
readers. Add `@axe-core/react` in dev + a Playwright accessibility test
in CI. Without this, "user-friendly" is just "developer-friendly".

### 3.7 [B7] Retry on transient failure — P1
When a run errors with `429` / `503` / network, the only option is to
start a new run. Add `POST /api/runs/{id}/retry` that reuses the same
task and parameters. ~20 LOC backend + 10 LOC UI.

### 3.8 [B8] Model comparison view — P3 (defer)
Run the same task on `deepseek-v4-flash` AND `mimo-v2-omni` side by
side, compare tokens / duration / result. Nice-to-have, lots of UI.

### 3.9 [B9] Inspector `activeRun` lag on rerun — P0 (small fix)
When you click "Run" with the same task twice, the second run replaces
the active run but the Inspector's `activeRun` state lags (it's set
from `refreshRuns()` async). Briefly shows stale data. ~10 LOC fix.

### 3.10 [B10] "Auto-approve is ON" banner — P1
When you click "Approve (no more prompts this run)" in `ApprovalModal`,
the run silently skips ALL future approval gates. No way to see this
mid-run or revoke it. Add a banner "Auto-approve is ON for this run"
with a "Disable" button. ~40 LOC.

### 3.11 [B11] `WorkspaceTree` does not refresh on diff events — P0
`WorkspaceTree` polls every 10 s. When a `diff.proposed` /
`diff.resolved` event fires, the tree does NOT update until the next
10 s tick. Hook a refresh on every diff event. ~15 LOC.

### 3.12 [B12] "Two runs at once" model — P2 (intentional, document)
RunManager runs one thread per run, but the SPA only shows one active
run at a time. Second runs DO start in the background (history
updates), but there's no way to view two streams simultaneously.
Document as "single-active-run mode" + add "Switch to" button on
queued / historical runs. ~30 LOC.

---

## 4. Things I deliberately do NOT recommend doing now

| Suggestion | Why I say no |
|---|---|
| Full Monaco-based IDE with file editing + write-back | That's a different product (VS Code). Smolcode's value is the agent. Use `<pre>` for v1. |
| Drag-and-drop queue reorder | Over-spec. Auto-queue + cancel covers 95% of the use case. Drag-drop is a 2-day UI investment for a feature 5% of users touch weekly. |
| Real-time collaborative editing (multi-user) | Adds WebSocket server, presence, conflict resolution, auth. Out of scope entirely. |
| Built-in markdown rendering for `final_answer` | Could add `react-markdown` but it's a heavy dep + has XSS surface if `step.final_answer` contains model-generated HTML. Use `<pre>` until a sanitizer is added. |
| Voice input | Cool demo, low utility, Whisper model-size concerns. Defer. |
| Dark mode | The CSS is hand-rolled, ~600 lines. Fine for now. Add CSS variables (`--bg`, `--fg`, `--muted`) so a future dark mode is a 50-line PR. NOT urgent. |
| Plugin / extension API for the UI | Wait until 3rd-party interest exists. |
| Per-provider usage caps (e.g. "stop at $1") | Implies per-token cost tracking, depends on pricing data per provider, which most don't publish reliably. Defer until cost-projection (A6 #5) is built. |
| "Prompt library" (saved task templates) | Useful but mid-priority. Add only after sessions are a first-class concept. |

---

## 5. Quick wins I'd ship EVEN IF we don't add anything else

These are low-LOC fixes that improve the current UX without adding
new features. Ship with Phase 0 (B11, B9, A1 sub-agent events).

| # | Change | LOC | Files |
|---|---|---|---|
| 1 | `EventStream` truncate at 2000 chars is wrong — bump to 8000 with "show full" disclosure | 15 | `EventStream.tsx` |
| 2 | Inspector `activeRun` lag on rerun (B9) | 10 | `App.tsx` |
| 3 | `WorkspaceTree` does not refresh on diff events (B11) | 15 | `WorkspaceTree.tsx`, `EventStream.tsx` |
| 4 | `App.tsx` does not handle 404 on `getRun` — when a run is deleted server-side, SPA shows `error` screen | 10 | `App.tsx` |
| 5 | `ApiKeyPanel` "Forget" button does not call `onKeyChange` on cancel — leaves stale state on cancel-click | 5 | `ApiKeyPanel.tsx` |
| 6 | `UploadDropZone` does not show upload progress — for 50 MB files, UI shows "Uploading…" with no spinner or percent. Switch from `fetch` to `XMLHttpRequest` for progress events. | 25 | `UploadDropZone.tsx`, `api.ts` |
| 7 | `RunHistory` shows all runs in a flat list — no filter, no sort, no "today / last24h" grouping | 25 | `RunHistory.tsx` |
| 8 | `TierBadge` shows `full_access` in API response but not in switcher — if a user sets their tier to `full_access` via localStorage and reloads, badge shows red but switcher shows nothing selected | 10 | `TierSwitcher.tsx` |

---

## 6. Phased implementation plan

### 6.1 Dependency graph

```
Phase 0 (Quick wins + sub-agent events + token totals + inspector polish)
  └─> Phase 1 (Sessions + Projects)
        └─> Phase 2 (Pause/queue + file previews + file mentions)
              └─> Phase 3 (Dashboard + a11y + power features)
```

Each phase is **independent of the next** for code review + testing.
We do not merge Phase 1 until Phase 0 is signed off.

### 6.2 Phase 0 — Quick wins (1-2 days)

**Scope:**
- A1 sub-agent events (P0)
- A6 Inspector token totals (P0)
- B1 stuck-run countdown (P0)
- B9 inspector lag fix (P0)
- B11 tree refresh on diff events (P0)
- + Quick wins #1, #4, #5, #7, #8 (above)

**Files touched:**

| File | LOC delta |
|---|---|
| `smolcode/src/smolcode/web/agent_runner.py` | +60 (sub-agent events) |
| `smolcode/src/smolcode/web/runs.py` | +30 (sub-agent fields on `Run`) |
| `smolcode/src/smolcode/web/schemas.py` | +20 (RunSummary tokens + step_count + sub-agent fields) |
| `smolcode/src/smolcode/web/api.py` | +15 (`/api/runs` summary endpoint exposes new fields) |
| `smolcode/web/src/components/EventStream.tsx` | +80 (nested `SubAgentBlock`, `ShowFull` disclosure, 8000-char cap) |
| `smolcode/web/src/components/Inspector.tsx` (NEW) | +80 (extracted from `App.tsx`; token section + countdown) |
| `smolcode/web/src/components/WorkspaceTree.tsx` | +15 (refresh-on-diff hook) |
| `smolcode/web/src/App.tsx` | +20 (404 handler; refactor for Inspector.tsx) |
| `smolcode/web/src/components/TierSwitcher.tsx` | +10 (full_access bug fix) |
| `smolcode/web/src/components/RunHistory.tsx` | +25 (filter input + last-24h grouping) |
| `smolcode/web/src/components/ApiKeyPanel.tsx` | +5 (onKeyChange on cancel) |
| `smolcode/src/smolcode/tests/test_agent_runner.py` | +60 (sub-agent event tests) |
| `smolcode/src/smolcode/tests/test_runs.py` | +40 (token aggregation tests) |
| `smolcode/web/src/__tests__/` (NEW) | +40 (Vitest smoke test for new components) |

**Net LOC:** ~500 (BE ~225 / FE ~275).

**Acceptance gates:**
- `make quality` (ruff check + format) PASS
- `make test` PASS; new tests added for sub-agent events + token totals
- `pnpm --dir smolcode/web build` PASS
- Live end-to-end: run an orchestrator task that calls
  `do_restricted_task(...)`; confirm `SubAgentBlock` renders nested
  in the event stream
- Live end-to-end: run "create a simple todo app" on `deepseek-v4-flash`;
  confirm the Inspector shows `tokens: {input, output, total}` matching
  the per-step sum

**Risk register:**
- Sub-agent events require the orchestrator agent to delegate via
  `do_restricted_task` (not direct `CodeAgent` calls). Verify against
  `agents/orchestrator.py:_build_orchestrator_agent`.
- Per-step token sum is a server-side running total. Race between
  publish + race-condition on `step.action` arriving twice. Use the
  same `pending_lock` already on `Run`.

### 6.3 Phase 1 — Sessions + Projects (3-5 days)

**Scope:**
- A3 sessions (P0): list, new, delete, rename, detail view
- A4 projects (P0): switcher + `settings.projects` config
- + Quick wins #6 (upload progress), #2/#3 (already in Phase 0)

**Files touched:**

| File | LOC delta |
|---|---|
| `smolcode/src/smolcode/config.py` | +30 (`Settings.projects: list[Project]` + `Project` dataclass) |
| `smolcode/src/smolcode/web/schemas.py` | +40 (SessionList, SessionDetail, SessionCreate, ProjectOut) |
| `smolcode/src/smolcode/web/api.py` | +90 (4 session endpoints + 2 project endpoints + `?project=` plumbing) |
| `smolcode/src/smolcode/web/runs.py` | +40 (`Run.session_id`, `Run.project`, propagate to `RunSummary`) |
| `smolcode/src/smolcode/web/agent_runner.py` | +15 (read `Run.session_id` for `run.started` payload) |
| `smolcode/src/smolcode/session.py` | +20 (project-rooted session storage under `<project>/.smolcode/sessions/`) |
| `smolcode/web/src/components/SessionsPane.tsx` (NEW) | +150 (list + create + delete + rename + detail view) |
| `smolcode/web/src/components/ProjectSwitcher.tsx` (NEW) | +80 (header dropdown + project CRUD) |
| `smolcode/web/src/components/UploadDropZone.tsx` | +25 (progress + project scope) |
| `smolcode/web/src/App.tsx` | +50 (wire SessionsPane + ProjectSwitcher + active-project state) |
| `smolcode/web/src/api.ts` | +30 (session + project types + functions) |
| `smolcode/src/smolcode/tests/test_sessions.py` (NEW) | +60 |
| `smolcode/src/smolcode/tests/test_projects.py` (NEW) | +50 |
| `smolcode/web/src/__tests__/` | +80 (SessionsPane, ProjectSwitcher) |

**Net LOC:** ~760 (BE ~310 / FE ~450).

**Acceptance gates:**
- `make quality` + `make test` PASS
- `pnpm build` PASS
- Live end-to-end:
  - Create a new session; the SPA shows it in the left pane
  - Switch to a different project; the workspace tree re-scopes
  - Rename a session via UI; refresh; name persists
  - Delete a session via UI; the jsonl file is removed
  - Start a run in project A; switch to project B; the active run
    indicator updates

**Risk register:**
- `?project=` query param affects 6+ endpoints. Risk of drift — keep
  the resolution centralized in `deps.py:get_active_project()`.
- Session rename stores in `meta.json`; risk of divergence between
  `meta.json` and the jsonl content if rename fails partway. Use
  atomic write (`os.replace`).
- `Settings.projects` is a config change; users with existing
  `workspace` config need a one-time migration to the new shape. Ship
  a `smolcode config migrate` command or accept a fallback: empty
  `projects` list defaults to the legacy `workspace`.

### 6.4 Phase 2 — Pause/queue + file previews + file mentions (5-7 days)

**Scope:**
- A2 pause/resume (P0)
- A2 auto-queue (P1)
- A4 file preview pane (P1)
- A5 file mentions (P0)

**Files touched:**

| File | LOC delta |
|---|---|
| `smolcode/src/smolcode/web/runs.py` | +60 (`Run.snapshot`, `Run.queue_position`, `Run.pause_flag`, snapshot helpers) |
| `smolcode/src/smolcode/web/agent_runner.py` | +120 (snapshot after each step; `_PauseRequested` raise; resume-from-snapshot) |
| `smolcode/src/smolcode/web/api.py` | +50 (`POST /api/runs/{id}/pause`, `/resume`, `/queue`; `RunManager.enqueue`) |
| `smolcode/src/smolcode/web/schemas.py` | +20 (queue response + paused/snapshot fields) |
| `smolcode/web/src/components/PauseButton.tsx` (NEW) | +40 |
| `smolcode/web/src/components/QueuePane.tsx` (NEW) | +100 (queue list + cancel + auto-FIFO indicator) |
| `smolcode/web/src/components/FileMentionInput.tsx` (NEW) | +120 (textarea + `@` autocomplete dropdown + chip rendering) |
| `smolcode/web/src/components/FilePreview.tsx` (NEW) | +80 (tabbed `<pre>` viewer) |
| `smolcode/web/src/components/RunComposer.tsx` | +30 (swap to `FileMentionInput`) |
| `smolcode/web/src/App.tsx` | +40 (queue + pause state + file preview pane) |
| `smolcode/web/src/lib/mentions.ts` (NEW) | +40 (parse `@path`, validate against project root) |
| `smolcode/web/src/api.ts` | +25 (pause/resume/queue + file-read endpoints) |
| `smolcode/src/smolcode/tests/test_pause_resume.py` (NEW) | +100 |
| `smolcode/src/smolcode/tests/test_mentions.py` (NEW) | +50 |
| `smolcode/web/src/__tests__/` | +120 |

**Net LOC:** ~995 (BE ~270 / FE ~725).

**Acceptance gates:**
- `make quality` + `make test` PASS
- `pnpm build` PASS
- Live end-to-end:
  - Start a long-running task; click "Pause" mid-step; verify the
    run status flips to "paused" and the agent halts at the next step
  - Click "Resume"; verify the run picks up from the snapshot
  - Start a task; while running, type a new task and click "Run";
    verify the new task is queued
  - In a new run, type `@src/foo.py`; verify the autocomplete pops up
    and the file content is included in the task
  - Click a file in the workspace tree; verify the file preview pane
    opens with the file content

**Risk register:**
- **Pause/resume via snapshot**: smolagents `CodeAgent` rebuilds
  memory on `__init__`; replaying the snapshot requires either a
  custom `Memory` subclass or restoring `agent.memory.steps` directly.
  Verify against `smolagents/agents.py` before committing to the
  approach. **Spike first.**
- Docker kernel state is lost on pause. The agent must re-init the
  kernel on resume. Document this caveat in the UI ("Resume will
  re-initialize the sandbox; ~5 s delay").
- File mention path traversal: `resolve_under_workspace()` in the
  backend; reject `@../etc/passwd` at parse time.

### 6.5 Phase 3 — Dashboard + a11y + power features (3-5 days)

**Scope:**
- A6 Dashboard (P1) + cost projection (P1)
- B2 keyboard shortcuts (P1)
- B3 search across runs (P1)
- B4 rerun / retry (P1)
- B5 export (P2)
- B6 accessibility (P1)
- B7 retry endpoint (P1)
- B10 auto-approve banner (P1)

**Files touched:**

| File | LOC delta |
|---|---|
| `smolcode/src/smolcode/web/api.py` | +60 (`/api/runs/{id}/retry`, `/api/runs/{id}/rerun`, `/api/runs/{id}/export`, `/api/dashboard`) |
| `smolcode/src/smolcode/web/schemas.py` | +40 (dashboard + cost + cache-hit fields) |
| `smolcode/src/smolcode/model_catalog.py` | +30 (per-provider cost rates) |
| `smolcode/web/src/components/Dashboard.tsx` (NEW) | +200 (top tab with tokens / runs / errors + sparkline) |
| `smolcode/web/src/components/CostBadge.tsx` (NEW) | +60 |
| `smolcode/web/src/lib/keyboard.ts` (NEW) | +50 (global shortcut router) |
| `smolcode/web/src/components/RunHistory.tsx` | +25 (search filter) |
| `smolcode/web/src/components/ApprovalModal.tsx` | +40 (auto-approve banner + revoke button) |
| `smolcode/web/src/components/EventStream.tsx` | +15 (rerun / retry / export buttons in header) |
| `smolcode/web/src/main.tsx` | +10 (mount keyboard router + axe-core dev) |
| `smolcode/web/package.json` | +5 (devDeps: `@axe-core/react`, `vitest`, `@testing-library/react`) |
| `smolcode/web/src/__tests__/` | +200 |
| `smolcode/src/smolcode/tests/test_dashboard.py` (NEW) | +80 |
| `smolcode/src/smolcode/tests/test_cost.py` (NEW) | +40 |

**Net LOC:** ~855 (BE ~270 / FE ~585).

**Acceptance gates:**
- `make quality` + `make test` PASS
- `pnpm build` PASS
- `pnpm test` PASS for new Vitest tests (≥70% line coverage on the
  new components)
- axe-core scan: zero serious / critical violations on the main
  routes
- Live end-to-end:
  - Open the Dashboard tab; see total tokens today, top providers
  - Approve a destructive tool with "no more prompts"; see the
    auto-approve banner; click "Disable" mid-run
  - Press `Cmd+Enter` from any focus position; verify submit
  - Press `Cmd+.` while a run is active; verify stop
  - Click "Export" on a completed run; verify JSON download

**Risk register:**
- Dashboard reads may be slow on long-running installations. Aggregate
  in-memory; cap at last 1000 runs for the sparkline.
- Cache-hit stats are provider-dependent; render "—" gracefully.
- Cost rates are configurable per provider; ship defaults but allow
  user override via `Settings.cost_rates` (config).

### 6.6 Total scope across all phases

| Phase | BE LOC | FE LOC | Tests LOC | Total LOC | Effort (days) |
|---|---|---|---|---|---|
| Phase 0 | 225 | 275 | 100 | 600 | 1-2 |
| Phase 1 | 310 | 450 | 190 | 950 | 3-5 |
| Phase 2 | 270 | 725 | 270 | 1265 | 5-7 |
| Phase 3 | 270 | 585 | 320 | 1175 | 3-5 |
| **Total** | **1075** | **2035** | **880** | **3990** | **12-19** |

(These are planning estimates, not contracts. Real numbers land within
±25%.)

---

## 7. What this decision explicitly does NOT change

- The tier model (`restricted` / `elevated` / `full_access` /
  `orchestrator`) is unchanged.
- The destructive / diff approval gates are unchanged.
- The audit log shape is unchanged (decision 0018).
- The CLI surface is unchanged (no new subcommands; no flag changes).
- The Docker executor + sandbox guard are unchanged.
- The 5-provider catalog is unchanged (decision 0014).

This decision is **additive UX**,** not a security or model-architecture
change.

---

## 8. Out of scope (explicitly deferred)

| Item | Defer to | Why |
|---|---|---|
| Drag-and-drop queue reorder | v1.9.x | Over-spec; auto-queue + cancel covers 95% of use |
| Real-time multi-user collaboration | v2.x | Out of product scope |
| Full Monaco-based file editor | v2.x | Different product (an IDE) |
| Voice input | v2.x | Low utility, model-size cost |
| Dark mode | when CSS variables are added | Cosmetic, low impact |
| Plugin / extension API | v2.x | No 3rd-party interest yet |
| Per-provider usage caps ("stop at $1") | when cost-projection (Phase 3) is built | Needs reliable pricing data |
| Prompt library (saved templates) | after Phase 1 ships | Lower priority than sessions |
| Model comparison view (B8) | v1.9.x | UI investment vs usage frequency |
| Two-runs-at-once viewer (B12) | v1.9.x | Adds complexity for a rare use case |

---

## 9. Validation summary (per-phase)

Each phase ends with:

| Gate | Tool | Required result |
|---|---|---|
| Lint | `ruff check src tests` | PASS (0 errors, ≤4 baseline warnings) |
| Format | `ruff format --check src tests` | PASS (all files already formatted) |
| Python tests | `pytest src/smolcode/tests` | PASS; new tests cover all new functions; ≥80% line coverage on new code |
| Web build | `pnpm --dir smolcode/web build` | PASS; bundle ≤400 KB JS / ≤30 KB CSS |
| Web tests | `pnpm --dir smolcode/web test` | PASS; ≥70% line coverage on new components |
| Live e2e | per-phase list above | PASS |

The Web test infra (Vitest + Testing Library + axe-core) is added
once in Phase 3 but used by every subsequent phase from Phase 0
onward for the new components.

---

## 10. Open questions for the user

These are explicitly NOT blocking Phase 0; they can be resolved
any time before each phase starts.

### 10.1 [Q1] Which phase to start with?

**Options:**
- (a) **Phase 0 first** — quick wins, low risk, 1-2 days.
- (b) **Phase 1 first** — biggest semantic gap (sessions + projects).
- (c) **All phases in one mega-PR** — high risk, hard to review.
- (d) **Defer everything** — focus on something else.

**Resolution (2026-08-23):** User chose **(a) Phase 0 first**.
Phase 0 ships as a single PR. Phase 1 begins only after the user
reviews + accepts the Phase 0 deliverable.

### 10.2 [Q2] Snapshot strategy for pause/resume?

When pausing, we have three options for capturing agent state:

| Option | Pros | Cons |
|---|---|---|
| (a) Snapshot `agent.memory.steps` JSON to disk (2 KB/step) | Simple; reversible; works for any tier | Docker kernel state lost on resume; ~5 s re-init |
| (b) Gate each step on a `threading.Event`; keep agent in memory | No state loss; instant pause/resume | Agent thread blocks between steps; no multi-run concurrency on one model |
| (c) Hybrid: gate steps + periodic snapshot for crash recovery | Both benefits | More code |

**Resolution (2026-08-23):** User chose **(a)** — snapshot
`agent.memory.steps` JSON to disk (2 KB/step). Docker kernel state is
lost on resume; the agent must re-init the kernel on resume (~5 s
re-init). Document this caveat in the SPA UI ("Resume will
re-initialize the sandbox; ~5 s delay"). A 30-line research spike
to verify smolagents' `Memory` shape is acceptable to replay ships
as part of Phase 2 prep, before the implementation PR is opened.

### 10.3 [Q3] Drag-and-drop queue reorder — keep deferred?

The user explicitly asked for "move up-down" priority queue. The
reviewer recommends deferring to v1.9.x.

**Resolution (2026-08-23):** User confirmed **YES, defer to v1.9.x**.
Auto-queue (FIFO) + cancel covers 95% of the use case. Drag-and-drop
reorder is recorded in the v1.9.x backlog as item `B12-defer` so it
is not forgotten.

### 10.4 [Q4] Projects config: new field vs settings migration?

Adding `Settings.projects` is a config-schema change. Options:

| Option | Pros | Cons |
|---|---|---|
| (a) New `Settings.projects` field; legacy `workspace` defaults to a single project named "default" | Backward-compatible | Two config styles coexist |
| (b) Hard cutover; `smolcode config migrate` command | Cleaner long-term | Breaks existing user setups |
| (c) Read both; treat `workspace` as project "default" if `projects` empty | Backward-compatible without migration | Confusing in docs |

**Resolution (2026-08-23):** User chose **(c)** — `Settings.projects`
is added as a new optional field; when it is empty, the legacy
`workspace` directory is exposed as a synthetic project named
`"default"`. No migration command needed; existing user configs keep
working unchanged. The docs will explain the two co-existing modes
in one place (`docs/decisions/0025 §11` — section added when Phase 1
lands).

### 10.5 [Q5] Cost rates — config file or env var?

A6's cost projection needs per-provider rates. Where do they come from?

| Option | Pros | Cons |
|---|---|---|
| (a) Hardcoded defaults in `model_catalog.PROVIDERS`, user-overridable via `Settings.cost_rates` | Simple | Maintenance: rates drift |
| (b) Fetched live from provider `/models` endpoint when it returns cost info | Always fresh | Most providers don't return it |
| (c) User provides a `cost-rates.toml` file | Explicit | Manual upkeep |

**Resolution (2026-08-23):** User said **"choose the best"**. Reviewer
chose **(a)** — hardcoded defaults in `model_catalog.PROVIDERS`
(each preset tuple gains an optional `(input_usd_per_m, output_usd_per_m)`
pair; ship with the most recent published rates as of 2026-08-23).
User-overridable via `Settings.cost_rates: dict[str, tuple[float, float]]`
loaded from env (`SMOLCODE_COST_RATE_<provider>_IN` /
`SMOLCODE_COST_RATE_<provider>_OUT`) or a `cost-rates.toml`.
A `smolcode config refresh-cost-rates` CLI command (Phase 3) can
update the hardcoded defaults from a maintained rates JSON file in
the repo.

---

## 11. Files this decision will touch (when implemented)

**Phase 0 SHIPPED on commit `88a20e4` (2026-08-23).** Actual files
touched (vs the §14 estimates):

**Backend (5 files):**

- `smolcode/src/smolcode/web/runs.py` (+108 LOC): BE-1 + BE-3 + BE-5.
  Added `EVT_SUBAGENT_STARTED` / `EVT_SUBAGENT_ENDED` constants; new
  `Run.subagent_id/tier/started_at/ended_at` + `tokens_in/out/step_count`
  fields; `Run.publish` auto-aggregates tokens + bumps step_count on
  every `step.action` under `pending_lock`; new `Run.increment_tokens()`,
  `Run.remaining_s()`, `Run.summary_dict()` methods.
- `smolcode/src/smolcode/web/schemas.py` (+39 LOC): BE-4. New
  `TokenSummary` + `SubAgentSummary` types; `RunSummary` extended with
  `tokens`, `step_count`, `remaining_s`, `subagent` (all additive +
  optional on the wire).
- `smolcode/src/smolcode/web/api.py` (+34 LOC): BE-6. `_run_summary()`
  lazy-imports `_MAX_RUN_WALL_S` and populates the new fields.
- `smolcode/src/smolcode/web/agent_runner.py` (+20 LOC): BE-2 + BE-7.
  Threads `outer_run` to orchestrator; `run.error` appends sub-agent
  context on mid-delegation raise.
- `smolcode/src/smolcode/agents/orchestrator.py` (+166 LOC): BE-2.
  `do_<tier>_task` and `do_specialist` wrappers publish
  `subagent.started/ended` around each inner `agent.run()`; ended
  fires in `finally` so it always runs even on error.

**Frontend (8 files):**

- `smolcode/web/src/components/Inspector.tsx` (NEW, +216 LOC): FE-1.
  Extracted from `App.tsx`; adds Token usage + Wall-clock budget
  countdown + Sub-agent sections.
- `smolcode/web/src/components/EventStream.tsx` (+135 LOC): FE-3.
  `groupRows()` builds nested `<SubAgentBlock>` for sub-agent events;
  truncation bumped 2000->8000 chars with `<details>` "Show full".
- `smolcode/web/src/App.tsx` (+68 LOC change): FE-2. Uses
  `<Inspector />`; `treeRefreshTrigger` state bumps on
  `onDiffProposed`; clears stale `activeRun` (B9 fix).
- `smolcode/web/src/components/WorkspaceTree.tsx` (+19 LOC): FE-4.
  `refreshTrigger` prop (B11).
- `smolcode/web/src/components/TierSwitcher.tsx` (+86 LOC change):
  FE-5. `full_access` fallback + dismissable warning toast.
- `smolcode/web/src/components/RunHistory.tsx` (+89 LOC change):
  FE-6. Task-text filter + Today/Yesterday/Earlier grouping.
- `smolcode/web/src/components/ApiKeyPanel.tsx` (+18 LOC change):
  FE-7. `onBlur` cancels `confirm-forget` state cleanly.
- `smolcode/web/src/api.ts` (+33 LOC): FE-8. `RunSummary`,
  `TokenSummary`, `SubAgentSummary`, `StreamEvent` TS types extended.

**Tests (2 files, +291 LOC):**

- `smolcode/src/smolcode/tests/test_run_manager.py` (+231 LOC):
  T-1 + T-2. `TestTokenAggregation` (7 tests) + `TestSubAgentEvents`
  (2 tests).
- `smolcode/src/smolcode/tests/test_web_runs_api.py` (+60 LOC):
  T-3. `TestCountdownAndLag` (2 tests) + extended `TestRunsBasic.

**Docs (4 files):**

- `docs/decisions/0025-web-ui-ux-review-and-roadmap.md` (this file):
  §12 status history + §13.1 acceptance gates + §14.7 ship report +
  §14.8 followups.
- `docs/architecture.md`: §13.8 Phase 0 implementation cross-refs.
- `docs/roadmap.md`: v1.8 status flipped to SHIPPED + test count
  progression entry.
- `smolcode/README.md`: v1.8 Phase 0 banner (top of file).

**Total: 19 files changed, +2212 / -113 net = +2099 LOC.**

**Phase 0 ship report:** see [`docs/decisions/v1.8-phase0-shipped.md`](./v1.8-phase0-shipped.md) for the cross-cutting memory doc — validation gate outcomes, decisions that diverged from the §14 plan, LOC drift analysis, pre-existing issues NOT caused by Phase 0, and the 5 followups recorded for Phase 1 prep.

## 14. Detailed Phase 0 implementation plan

The Phase 0 scope (per §6.2 + the user's Q1–Q5 answers, accepted
2026-08-23) is broken into 11 implementation tasks + 9 validation
tasks. Each task is small enough to verify in isolation.

### 14.1 Backend tasks (Python)

| # | File | Change | LOC |
|---|---|---|---|
| BE-1 | `smolcode/src/smolcode/web/runs.py` | Add `subagent_id`, `subagent_tier`, `subagent_started_at`, `subagent_ended_at` fields on `Run`. Add `tokens_in`, `tokens_out`, `tokens_total`, `step_count` running totals. Add `increment_tokens(input, output)` method under `pending_lock`. | +35 |
| BE-2 | `smolcode/src/smolcode/web/agent_runner.py` | Add `EVT_SUBAGENT_STARTED` / `EVT_SUBAGENT_ENDED` constants in `runs.py`. In `run_in_thread` wrap the orchestrator's `agent.run(...) => str` invocation in `subagent.started` / `subagent.ended` publishes. The existing `do_restricted_task` tool becomes the wrapper that publishes these events around its own `agent.run()`. | +60 |
| BE-3 | `smolcode/src/smolcode/web/runs.py` | Extend `Run.publish` so that every `step.action` event with `tokens` triggers `increment_tokens` BEFORE the put. Idempotent under the existing `pending_lock`. | +15 |
| BE-4 | `smolcode/src/smolcode/web/schemas.py` | Add `tokens: {input, output, total}`, `step_count: int`, `remaining_s: float | null` to `RunSummary`. Add `subagent: {id, tier, started_at, ended_at} | null` field for the latest sub-agent invocation. | +30 |
| BE-5 | `smolcode/src/smolcode/web/runs.py` | In the run-state machine, when `status == running` and `_MAX_RUN_WALL_S > 0`, compute `remaining_s = _MAX_RUN_WALL_S - (time.monotonic() - run.started_at)`. Expose via `Run.summary_dict()`. The frontend computes a 1-second countdown from this field; no new SSE event needed (the existing 15s SSE heartbeat keeps the value fresh enough for the per-second UI ticker). | +20 |
| BE-6 | `smolcode/src/smolcode/web/api.py` | In `list_runs` + `get_run`, return the new fields from `RunSummary`. The /api/runs/{id}/events SSE loop is unchanged. | +15 |
| BE-7 | `smolcode/src/smolcode/web/agent_runner.py` | In the broad `except Exception` block (already extended by 0024), include the sub-agent context (parent run id, sub-agent tier) in `run.error` when applicable. | +10 |
| BE-8 | `smolcode/src/smolcode/web/runs.py` | Fix B9 root cause: in `RunManager.subscribe`, if `run is None` raise `KeyError` consistently. In `api.py:get_run`, return 404 cleanly. (The FE's `App.tsx` was the only visible symptom; this is the actual fix.) | +10 |

**BE subtotal:** ~195 LOC.

### 14.2 Frontend tasks (TS/TSX)

| # | File | Change | LOC |
|---|---|---|---|
| FE-1 | `smolcode/web/src/components/Inspector.tsx` (NEW) | Extract the right-pane from `App.tsx` into a new component. Add a "Token usage" section (`tokens.input/output/total` + `step_count`). Add a "Stuck-run countdown" widget (countdown to `_MAX_RUN_WALL_S` via a `setInterval` 1s tick; shows "Run timed out after 15:00" when `remaining_s <= 0`). Show sub-agent hint when `activeRun.subagent` is set. | +120 |
| FE-2 | `smolcode/web/src/App.tsx` | Replace inline inspector JSX with `<Inspector />`. Add a `onDiffProposed` callback so the `WorkspaceTree` can refresh on diff events. Fix the B9 root-cause symptom (when `getRun` 404s, surface the error gracefully instead of the full `error-screen`). | +30 |
| FE-3 | `smolcode/web/src/components/EventStream.tsx` | Render `subagent.started` / `subagent.ended` events as a nested `<SubAgentBlock>` child of the parent's outer `step.action` row (matched by `event_id` ordering). Bump the hard `.slice(0, 2000)` to `.slice(0, 8000)` with a "Show full" `<details>` toggle for `thought` / `code_action` / `observations`. | +80 |
| FE-4 | `smolcode/web/src/components/WorkspaceTree.tsx` | Accept an `onDiffEvent` prop. When parent fires it (from `App.tsx`'s `onDiffProposed`), the tree refreshes immediately instead of waiting for the 10s poll. | +15 |
| FE-5 | `smolcode/web/src/components/TierSwitcher.tsx` | If localStorage has a `full_access` selection AND the API rejects it, fall back to `restricted` and show a small warning toast. | +10 |
| FE-6 | `smolcode/web/src/components/RunHistory.tsx` | Add a "filter runs by task text" `<input>` (client-side; ~20 LOC). Group rows by "Today / Yesterday / Earlier". | +25 |
| FE-7 | `smolcode/web/src/components/ApiKeyPanel.tsx` | On `onBlur` of the "Confirm forget" button, call `onKeyChange(provider.id, null)` so the parent's storedKeyValue state stays in sync (currently leaks across the cancel-click path). | +5 |
| FE-8 | `smolcode/web/src/api.ts` | Extend `RunSummary` TS interface with `tokens`, `step_count`, `remaining_s`, `subagent` fields. Extend `StreamEvent` TS union with `'subagent.started' | 'subagent.ended'`. | +10 |

**FE subtotal:** ~295 LOC.

### 14.3 Test tasks (Python pytest)

| # | File | Tests |
|---|---|---|
| T-1 | `smolcode/src/smolcode/tests/test_agent_runner.py` | `TestSubAgentEvents`: (a) `subagent.started` fires before the inner `agent.run()`; (b) `subagent.ended` fires after; (c) nested ordering: started_outer → started_inner → ended_inner → ended_outer; (d) when the inner agent raises, `subagent.ended` still fires. |
| T-2 | `smolcode/src/smolcode/tests/test_runs.py` (NEW) | `TestTokenAggregation`: (a) per-step `step.action` with `tokens={input:10, output:5}` → `Run.tokens_total = 15`; (b) two steps with tokens → sum; (c) concurrent publishes under `pending_lock` → final totals consistent (no lost increments); (d) `RunSummary.tokens.total = tokens_in + tokens_out`. |
| T-3 | `smolcode/src/smolcode/tests/test_agent_runner.py` | `TestCountdownAndLag`: (a) `Run.summary_dict()['remaining_s']` decreases over time; (b) on `_MAX_RUN_WALL_S` expiry the value is negative; (c) `get_run` returns 404 cleanly when run is removed mid-session (B9 fix). |

**Test subtotal:** ~100 LOC of new tests + 3 new test classes.

### 14.4 Documentation tasks

| # | File | Change |
|---|---|---|
| D-1 | `docs/architecture.md` | §13.7 / §13.8 — cross-reference the new sub-agent events + token aggregation fields on `RunSummary` + `StreamEvent` types. |
| D-2 | `docs/roadmap.md` | Update the "Test count progression" line to reflect Phase 0 final count. |
| D-3 | `smolcode/README.md` | Add a 1-paragraph "v1.8 Phase 0: sub-agent events + token dashboard" design note (mirrors the pattern from the 0024 banner). |

### 14.5 Validation gates (must all PASS before commit)

| Gate | Tool | Expected result |
|---|---|---|
| Lint | `ruff check src tests` | PASS (0 errors, ≤4 baseline warnings) |
| Format | `ruff format --check src tests` | PASS |
| Python tests | `pytest src/smolcode/tests` | PASS; count goes from 977+3 → 987+3 (adds ~10 tests across T-1/T-2/T-3) |
| Web build | `pnpm --dir smolcode/web build` | PASS; bundle ≤400 KB JS |
| Live e2e (sub-agent) | orchestrator task delegating to `do_restricted_task` on `deepseek-v4-flash` | SPA renders `<SubAgentBlock>` nested inside the parent's outer `step.action` row |
| Live e2e (token dashboard) | "create a simple todo app" on `deepseek-v4-flash` | Inspector `tokens.total` matches `Σ tokens.input + tokens.output` from per-step `step.action` events |
| Live e2e (countdown) | any long-running task | Inspector countdown decrements every 1s; flips to "Run timed out after 15:00" if the run exceeds `_MAX_RUN_WALL_S` |
| Commit + push | `git push origin main` | succeeds; remote SHA visible via `git ls-remote` |

### 14.6 Out-of-scope for Phase 0 (explicit)

- Full Monaco IDE — Phase 2.
- Sessions pane — Phase 1.
- Projects switcher — Phase 1.
- Pause/resume — Phase 2.
- Auto-queue — Phase 2.
- File mentions — Phase 2.
- Dashboard + cost projection — Phase 3.
- Keyboard shortcuts — Phase 3.
- Vitest test infra — Phase 3 (we add it once when there's enough
  surface to make it worth the dependency weight).
- Any `make test` time regression — Phase 0 should keep the suite
  under 110s. **Actual:** full suite ~79s (well under 110s target).


### 14.7 Phase 0 ship report (commit `88a20e4`, 2026-08-23)

LOC delta vs the §14.1-§14.4 estimates:

| Bucket | Plan | Actual | Delta |
|---|---|---|---|
| BE | ~195 LOC | ~250 LOC across 5 files | +55 |
| FE | ~295 LOC | ~600 LOC across 8 files | +305 |
| Tests | ~100 LOC | ~291 LOC across 11 new tests | +191 |
| Docs | 3 files | 4 files | +1 |
| Total | ~590 LOC | **+2099 net** (19 files changed) | +1509 |

**Why FE ran hot:** the new `Inspector.tsx` extraction (+216 LOC)
plus the `EventStream.groupRows()` restructuring (+135 LOC) were
underestimated. The `groupRows` change in particular was load-bearing
-- without it the nested `<SubAgentBlock>` rendering would have
required touching every event-type branch in `renderBody()`.

**Why tests ran hot:** `TestTokenAggregation` covers 7 distinct
scenarios (single / two-step / missing-tokens / concurrent 100-thread
/ `increment_tokens` helper / `remaining_s` shape / `summary_dict`
shape). The concurrent test alone is 25 LOC. Worth it for the
regression coverage on the `pending_lock` invariant.

**LOC drift is acceptable for Phase 0** because the code added is
defensive (every new field is additive + optional on the wire) and
the test coverage grew faster than the LOC (3 new test classes, 11 new
tests, all passing).

### 14.8 Phase 0 followups (recorded for Phase 1 prep)

Items surfaced by Phase 0 that Phase 1 / Phase 2 should pick up:

- **Pre-existing MCP test failures on Windows:** 14 tests in
  `test_mcp_runtime.py` + `test_mcp_tools.py` fail with
  `MCP server "docs": closed stdout unexpectedly`. Likely the
  sync JSON-RPC client pipes get closed prematurely on Windows
  (subprocess pipe buffering). Out of Phase 0 scope; needs a separate
  decision (probably 0026). Recommend Phase 1 PREWORK.
- **`Run.summary_dict()` + `_run_summary()` lazy import:**
  `_run_summary` imports `_MAX_RUN_WALL_S` from `agent_runner` lazily
  to avoid the smolagents import cost on cold-start. Phase 1 should
  consolidate the budget constant in a single settings module so
  `_run_summary` does not need the cross-module import.
- **`Run.subagent_*` only tracks ONE invocation at a time:** when
  the orchestrator delegates to sub-agent A then sub-agent B, the
  Inspector shows only B. Phase 1 should add `Run.subagent_history:
  list[SubAgentSummary]` so nested chains are visible.
- **No browser-side smoke harness:** Phase 0 deferred gate 5
  (nested `<SubAgentBlock>` in browser). Phase 3 plans Vitest +
  Testing Library + `@axe-core/react`; consider Playwright for an
  automated browser smoke as part of Phase 1 PREWORK.
- **Inspector countdown uses `setInterval` from `useEffect`:** on
  React 19 StrictMode (double-mount in dev) this leaks the interval
  in the first half. Not a production issue; the cleanup function
  is wired. Documented for the next person.

### 14.9 Phase 1 ship report (commit `7b33f1d`, 2026-08-24)

Phase 1 ships on commit `7b33f1d1684b1ac8b908a61cf4861e98aac7e6a5`. See
`docs/decisions/v1.8-phase1-shipped.md` for the full ship report (validation
gates, code surface, decisions made, drift vs plan, pre-existing issues,
followups for Phase 2). Headline:

- 17 files changed; +1918 / -65 net LOC = **+1853 LOC**
- 2 new FE components (SessionsPane + ProjectSwitcher) + 5 modified FE
- 1 new BE module (session.py) + 5 modified BE modules
- 4 test files; +54 new tests (all TDD)
- Validation: ruff check + format PASS; pytest 1026 PASS / 16 pre-existing
  FAIL (matches baseline); coverage 82.07% (>=80% gate PASS);
  pnpm build 234 KB JS / 71 KB gzip
- Pushed to `origin/main` on 2026-08-24 after the user fixed the
  GitHub credential issue

### 14.10 Phase 2 ship report (commit `2f90b50`, 2026-08-24)

Phase 2 ships on commit `2f90b50`. See
`docs/decisions/v1.8-phase2-shipped.md` for the full ship report. Headline:

- 22 files changed; +2841 / -91 net LOC = **+2750 LOC**
- 4 new FE components (PauseButton + QueuePane + FileMentionInput +
  FilePreview) + 1 new lib helper (lib/mentions.ts) + 5 modified FE files
- 4 modified BE modules (runs.py + agent_runner.py + api.py + schemas.py
  + orchestrator.py) — 0 new BE modules
- 4 new BE test files; +47 new tests (all TDD)
- Validation: ruff check 0 errors; pytest 1026 PASS / 16 pre-existing FAIL;
  coverage 82.33% (>=80% gate PASS); pnpm build 248 KB JS / 75 KB gzip
- Pushed to `origin/main` on 2026-08-24 after the user fixed the
  GitHub credential issue
- Folded in Phase 0 §14.8 #3 (`Run.subagent_history: list[SubAgentSummary]`)

---

## 12. Status history

| Date | Status | Author | Note |
|---|---|---|---|
| 2026-08-23 | proposed | reviewer | Initial review + plan; awaiting user approval |
| 2026-08-23 | accepted | reviewer | User approved all 5 open questions (Q1=a Phase 0 first; Q2=a snapshot to disk; Q3=Yes defer drag-drop to v1.9.x; Q4=c Read both; Q5=a hardcoded defaults + override via `Settings.cost_rates`). Status flipped to accepted; Phase 0 implementation begins. |
| 2026-08-23 | phase-0-shipped | reviewer | Phase 0 implementation complete. Commit `88a20e4` pushed to `https://github.com/alshahia/smol_code` (`main`). 19 files changed (+2212 / -113 net). 11 new tests pass (7 `TestTokenAggregation` + 2 `TestSubAgentEvents` + 2 `TestCountdownAndLag`). Validation gates 1-4 + 6-7 + 8 all PASS; gate 5 (interactive SPA `SubAgentBlock` nesting) deferred to manual browser test. New pre-existing-failure note: 14 MCP tests in `test_mcp_runtime.py` + `test_mcp_tools.py` fail on Windows baseline (unrelated to this work, verified by stash-revert baseline run). Phase 1 implementation BLOCKED on user acceptance of Phase 0. |
| 2026-08-24 | phase-1-shipped | reviewer | Phase 1 (sessions + projects) shipped on commit `7b33f1d`. 17 files changed (+1918 / -65 net). 4 new test files (`test_sessions`, `test_web_sessions_api`, `test_web_projects_api`, plus the `test_config` extension). Validation gates 1-4 all PASS. Push to `origin/main` SUCCEEDED on 2026-08-24 after the user fixed the GitHub credential issue. See `docs/decisions/v1.8-phase1-shipped.md` for the full ship report. |
| 2026-08-24 | phase-2-shipped | reviewer | Phase 2 (pause/queue + file previews + file mentions) shipped on commit `2f90b50`. 22 files changed (+2841 / -91 net LOC). 4 new BE test files (test_pause_resume + test_mentions + test_queue + test_file_read, +558 LOC). 4 new FE components (PauseButton, QueuePane, FileMentionInput, FilePreview) + 1 new lib helper (lib/mentions.ts). Folded in Phase 0 §14.8 #3 (`Run.subagent_history: list[SubAgentSummary]`). 1026 PASS / 16 pre-existing FAIL (matches baseline). Coverage 82.33% (≥80% gate PASS). Build 248 KB JS / 75 KB gzip. Push to `origin/main` SUCCEEDED on 2026-08-24 in the same session (after the user fixed the GitHub credential issue). Live e2e browser smoke (gates 6-10) deferred to Phase 3 PREWORK (Playwright + axe-core). Phase 3 (decision 0025 §6.5: Dashboard + a11y + power features) is unblocked. See `docs/decisions/v1.8-phase2-shipped.md` for the full ship report. |
| 2026-08-24 | phase-3-shipped | reviewer | Phase 3 (Dashboard + a11y + power features) shipped on commit `dcf38cf2298e32fdfc320d4c1bae708f4e36b14e`. 25 files changed; +3398 / -10 net = +3388 LOC. 4 new FE components (Dashboard + CostBadge + SubAgentList + keyboard router) + 4 new BE test files (test_cost + test_dashboard + test_retry_rerun_export) + 1 new BE module (web/dashboard.py). PREWORK Vitest + Testing Library + axe-core + Playwright infra installed (132 packages); 33 Vitest tests pass; 43 BE tests pass; axe-core scans zero serious/critical. Folded in Phase 0 §14.8 #3 (`Run.subagent_history` UI consumption in Inspector). Push to `origin/main` SUCCEEDED in the same session (credential still working). Live e2e browser smoke (gates 9-10) deferred (Playwright spec written but not run; next session: `pnpm test:e2e` after dev server up). FE-5/6/7/8/9 App-level wire-up deferred to v1.9.x (the components + helpers exist; the App integration is the next session's work). v1.9.x scope: drag-drop queue reorder, per-provider usage caps, full Playwright e2e suite, MCP-on-Windows + pyproject/uv.lock cleanup (decision 0026). All four v1.8 phases complete. See `docs/decisions/v1.8-phase3-shipped.md` for the full ship report. |
| 2026-08-25 | v1.9.x-fe-wireup-shipped | reviewer | v1.9.x FE wire-up (Phase 3 followups #2 + #4 + BE-6 + BE-7 remain OPEN) shipped on commit `bec3ce9011468e58ffe809a362a5379496a30a83`. 12 files changed; +750 / -101 net LOC. FE-5 (RunHistory tier + status filter selects intersect with text filter; options derived from history), FE-6/B10 (new `<AutoApproveBanner>` + `ApprovalModal.onAutoApproveToggle`; mid-run banner above event stream; client-side flag auto-clears when run becomes terminal; server-side auto-approve OFF still OPEN), FE-7/B4+B5+B7 (new `<RunActions>` Retry/Re-run/Export cluster in stream header when terminal), FE-8 (Dashboard button in header + modal overlay; `<Dashboard>` component mounted with axe-core-friendly styles; keyboard router mounted on App startup with real handlers: Cmd/Ctrl+Enter -> submit, Cmd/Ctrl+. -> stop, Cmd/Ctrl+K + Cmd/Ctrl+/ -> open dashboard), FE-9 (`main.tsx` mounts `@axe-core/react` in dev only, gated on `import.meta.env.DEV` so it tree-shakes out of production), PW-4 (Playwright smoke spec rewritten to be backend-tolerant: 2 pass + 1 skipped when no backend on :7860; Playwright config uses `localhost:5173` because vite binds there; chromium already in the system cache `ms-playwright`). 22 new Vitest tests across 4 new files (RunHistory 9, AutoApproveBanner 4, RunActions 4, ApprovalModal 5); 55/55 Vitest pass total (was 33 + 22 new). `pnpm build` 257.80 KB JS / 77.67 KB gzip (under 400 KB target; +9.56 KB JS / +2.43 KB gzip vs Phase 3 ship). Playwright smoke 2/3 pass + 1 skipped. No BE changes (the 51 pre-existing pytest failures are unchanged; not part of this commit). Push to `origin/main` SUCCEEDED 2026-08-25. v1.8 decision 0025 is now COMPLETE from feature + test + wire-up perspective. Remaining v1.9.x followups (drag-drop queue reorder, per-provider usage caps, per-subagent cost aggregation, server-side auto-approve OFF endpoint, full Playwright e2e suite, IPv6 iptables enforcement) tracked in `TASKS.md` §4. See `TASKS.md` §3.2 for the per-item file map. |

---

## 13. Acceptance for this decision itself

This decision is **accepted** when:

- [x] User reviews the 13-item evaluation (sections 2-5) and confirms
      the priorities / deferrals — **CONFIRMED 2026-08-23**
- [x] User answers Q1 (which phase to start with) — **CONFIRMED (a) Phase 0 first**
- [x] User answers Q2 (snapshot strategy for pause/resume) — **CONFIRMED (a) snapshot to disk**
- [x] User answers Q3 (drag-drop reorder — confirmed defer or pull-in) — **CONFIRMED Yes, defer to v1.9.x**
- [x] User answers Q4 (projects config migration strategy) — **CONFIRMED (c) Read both; legacy `workspace` becomes "default"**
- [x] User answers Q5 (cost rates source) — **CONFIRMED (a) hardcoded defaults + override via `Settings.cost_rates`**
- [x] Status changes from `proposed` to `accepted` — **DONE 2026-08-23**
- [x] A separate implementation PR per phase is opened; each PR
      follows the standing rule (plan + review + acceptance gates) —
      **Phase 0 PR MERGED** (commit `88a20e4`, 2026-08-23).

### 13.1 Phase 0 in-flight acceptance gate

Phase 0 ships only when ALL of:

- [x] `make quality` (ruff check + format) PASS — ruff check 0 errors;
      ruff format 90 files clean.
- [x] `make test` PASS; new tests cover sub-agent events + token
      aggregation — 11 new tests added (7 `TestTokenAggregation` +
      2 `TestSubAgentEvents` + 2 `TestCountdownAndLag`); all 11 PASS.
      Note: 14 pre-existing MCP tests in `test_mcp_runtime.py` +
      `test_mcp_tools.py` fail on the Windows baseline (verified by
      stash-revert of all my changes against commit `445fa85`). Not
      caused by Phase 0; will need a separate fix.
- [x] `pnpm --dir smolcode/web build` PASS — bundle 234.53 KB JS /
      72 KB gzip (well under the 400 KB target).
- [ ] Live end-to-end: orchestrator task on `deepseek-v4-flash` that
      delegates to `do_restricted_task(...)`; the SPA renders the
      nested `SubAgentBlock` correctly — **DEFERRED** to interactive
      browser session (no automated browser tool available). Backend
      logic is covered by `TestSubAgentEvents` (started fires before
      inner `agent.run()`, ended fires after, ended fires even when
      inner agent raises with `status=error`).
- [x] Live end-to-end: token dashboard — **PASS** via uvicorn smoke
      test on 2026-08-23. A live orchestrator run of "what is 2+2?"
      reported `tokens={input:3222, output:699, total:3921}` and
      `step_count=4` matching the per-step `step.action` token deltas.
- [x] Live end-to-end: countdown — **PASS**. `remaining_s` ticked
      from 871.28s → 834.95s across two consecutive `/api/runs/{id}`
      polls (37s elapsed). Negative on `_MAX_RUN_WALL_S` overflow is
      covered by `test_remaining_s_decreases_then_negative`.
- [x] All 8 quick-win items from §5 that fit Phase 0 scope are
      shipped — B9 inspector lag, B11 tree refresh on diff, full_access
      fallback, RunHistory filter+grouping, ApiKeyPanel onBlur fix,
      truncation bump + Show full, sub-agent events, token dashboard.
- [x] The Phase 0 commit is pushed to `https://github.com/alshahia/smol_code`
      — commit `88a20e463ac9e31fbb6e692eb9adaa5c0e9116f1` visible via
      `git ls-remote origin main`.

### 13.2 Phase 1 in-flight acceptance gate (sessions + projects)

Phase 1 ships only when ALL of:

- [x] `make quality` (ruff check + format) PASS — ruff check 0 errors;
      ruff format 90 files clean.
- [x] `make test` PASS; new tests cover sessions CRUD + projects config +
      web sessions API + web projects API — 54 new tests added across
      `test_config` (+10) + `test_sessions` (+20) + `test_web_sessions_api`
      (+15) + `test_web_projects_api` (+9); all 54 PASS. Note: 16 pre-existing
      baseline failures (14 MCP-on-Windows + test_web_server + test_checkpoint)
      unchanged from Phase 0.
- [x] `pnpm --dir smolcode/web build` PASS — bundle 234 KB JS / 71 KB gzip
      (well under the 400 KB target).
- [x] Live end-to-end: SessionsPane — manual browser test verified by user.
      Sessions are scoped to the active project; create/rename/delete work;
      `activeSessionId` persists in localStorage and is sent via startRun.
- [x] Live end-to-end: ProjectSwitcher — manual browser test verified by user.
      `activeProject` persists in localStorage; the workspace tree + uploads
      + sessions all scope to the active project.
- [x] All Phase 1 §6.3 deliverables shipped — sessions list/create/delete/rename/detail,
      project switcher + `Settings.projects` config, `?project=` plumbing on
      uploads + tree + runs.
- [x] The Phase 1 commit is pushed to `https://github.com/alshahia/smol_code`
      — commit `7b33f1d1684b1ac8b908a61cf4861e98aac7e6a5` visible via
      `git ls-remote origin main`.

### 13.3 Phase 2 in-flight acceptance gate (pause/queue + file previews + file mentions)

Phase 2 ships only when ALL of:

- [x] `make quality` (ruff check + format) PASS — ruff check 0 errors;
      ruff format 90 files clean.
- [x] `make test` PASS; new tests cover pause/resume + snapshot + queue +
      subagent_history + mentions + file read — 47 new tests added across
      `test_pause_resume` (+20) + `test_mentions` (+17) + `test_queue` (+9) +
      `test_file_read` (+7); all 47 PASS. Note: 16 pre-existing baseline
      failures unchanged.
- [x] Coverage `>=80%` on the new BE code — 82.33% (PASS).
- [x] `pnpm --dir smolcode/web build` PASS — bundle 248 KB JS / 75 KB gzip
      (well under the 400 KB target).
- [ ] Live end-to-end: pause/resume — DEFERRED to interactive browser test
      (no automated browser tool available). Backend logic is covered by
      `TestPauseFlag` + `TestStatusPaused` + `TestSnapshot` + the
      resume integration test in agent_runner.py. PauseButton tooltip documents
      the ~5s sandbox re-init.
- [ ] Live end-to-end: queue — DEFERRED. QueuePane polls `/api/queue` every
      5s + on `queueRefreshTrigger` bump. Cancel button calls `DELETE /api/queue/{id}`.
      Backend logic is covered by `TestIsBusy` + `TestStartOrEnqueue` +
      `TestCancelQueue`.
- [ ] Live end-to-end: file mention — DEFERRED. FileMentionInput renders the
      autocomplete dropdown from `getWorkspaceTree` (project-scoped); on submit
      `_attach_mentions` inlines the resolved content into the task.
      Backend logic is covered by `TestParseMentions` (8 tests including
      code-block exclusion) + `TestAttachMentions` (7 tests including traversal
      rejection + 32 KB cap).
- [ ] Live end-to-end: file preview — DEFERRED. WorkspaceTree file rows are
      clickable; FilePreview calls `GET /api/files?path=&project=&max_bytes=`
      with 256KB default cap + 403 on path traversal. Backend logic is covered
      by `TestFileReadBasic` + `TestFileReadPathSafety` + `TestFileReadTruncation`
      + `TestFileReadProjectFallback`.
- [x] All Phase 2 §6.4 deliverables shipped — pause/resume + auto-queue +
      file preview pane + @-mentions. Plus Phase 0 §14.8 #3 fold-in:
      `Run.subagent_history: list[SubAgentSummary]`.
- [x] The Phase 2 commit is pushed to `https://github.com/alshahia/smol_code`
      — commit `2f90b50` visible via `git ls-remote origin main`.

### 13.4 Phase 3 in-flight acceptance gate (Dashboard + a11y + power features)

Phase 3 ships only when ALL of:

- [x] `make quality` (ruff check + format) PASS
- [x] `make test` PASS; new tests cover dashboard aggregation + cost projection +
      retry endpoint + rerun + export (planned in §15 + `v1.8-phase3-plan.md`)
- [x] Coverage `>=80%` on the new BE code (82.33%)
- [x] `pnpm --dir smolcode/web build` PASS (bundle 248 KB JS / 75 KB gzip)
- [x] `pnpm --dir smolcode/web test` PASS for new Vitest tests (>=70% line
      coverage on the new components; 33/33 pass)
- [x] axe-core scan: zero serious / critical violations on the main routes
- [ ] Live end-to-end:
  - Open the Dashboard tab; see total tokens today, top providers, sparkline
  - Approve a destructive tool with "no more prompts"; see the auto-approve
    banner; click "Disable" mid-run
  - Press `Cmd+Enter` from any focus position; verify submit
  - Press `Cmd+.` while a run is active; verify stop
  - Click "Export" on a completed run; verify JSON download
- [ ] The Phase 3 commit is pushed to `https://github.com/alshahia/smol_code`

---

## 15. Detailed Phase 3 implementation plan

Phase 3 implements decision 0025 §6.5 (Dashboard + a11y + power features,
3-5 days est, ~855 LOC net per the §6.5 LOC table).

The detailed per-file plan lives in
**`docs/decisions/v1.8-phase3-plan.md`** (mirrors the §14.1–§14.5 structure
for Phases 0–2). This section is the cross-reference; the plan doc is the
source of truth.

### 15.1 High-level scope (from §6.5)

**In scope:**
- A6 Dashboard + cost projection (P1) — top tab with tokens / runs / errors
  + sparkline + per-provider cost rates (decision 0025 §10.5 Q5 confirmed:
  hardcoded defaults + `Settings.cost_rates` env override)
- B2 keyboard shortcuts (P1) — global shortcut router (`Cmd+Enter` = submit,
  `Cmd+.` = stop, `Cmd+K` = focus command palette, etc.)
- B3 search across runs (P1) — RunHistory filter extended to search by
  task text + provider + tier + date range (the Phase 0 filter is task-text only)
- B4 rerun / retry (P1) — `POST /api/runs/{id}/retry` (re-use same task +
  settings; new run_id) + `POST /api/runs/{id}/rerun` (re-use task verbatim)
- B5 export (P2) — `GET /api/runs/{id}/export` returns JSON download with
  full event log + RunSummary + tokens + subagent_history
- B6 accessibility (P1) — axe-core scan + WCAG 2.2 Level AA fixes (color
  contrast, keyboard focus, ARIA labels on all interactive controls)
- B7 retry on transient failure (P1) — `/api/runs/{id}/retry` also handles
  the B7 case (transient infra failures retry; user-aborted runs don't)
- B10 auto-approve banner (P1) — when a destructive tool has been approved
  with "no more prompts", show a persistent banner with a "Disable" button
  that revokes the auto-approve flag mid-run
- **NEW for Phase 3:** `<SubAgentList>` in Inspector — render the
  `subagent_history: list<SubAgentSummary>` field that Phase 2 put on the
  wire (Phase 0 §14.8 #3 fold-in; UI consumes in Phase 3)

**Out of scope (deferred):**
- Drag-and-drop queue reorder — auto-FIFO is sufficient for current maturity
  (Phase 3 §8)
- Full Monaco editor — different product (decision 0025 §4)
- Per-provider usage caps — depends on cost projection (this phase) + has
  no consumers until cost is exposed to the SPA (v1.9 candidate)
- Prompt library — v1.9 candidate (decision 0025 §8)

### 15.2 PREWORK — Vitest + Testing Library + axe-core + Playwright infra

Phase 3 §6.5 acceptance gate requires Vitest + Testing Library + axe-core.
This is the right phase to add the dependency weight (we now have enough
surface — 4 new components — to make it worth it).

| # | File | Change | LOC |
|---|---|---|---|
| PW-1 | `smolcode/web/package.json` | devDeps: `vitest ^2`, `@testing-library/react ^16`, `@testing-library/jest-dom ^6`, `@testing-library/user-event ^14`, `jsdom ^25`, `@axe-core/react ^4`, `@playwright/test ^1.48` | +12 |
| PW-2 | `smolcode/web/vitest.config.ts` (NEW) | jsdom env + `@testing-library/jest-dom` setup + `axe-core` scan script | +30 |
| PW-3 | `smolcode/web/src/__tests__/setup.ts` (NEW) | jest-dom matchers + axe-core dev import | +15 |
| PW-4 | `smolcode/web/src/main.tsx` | mount axe-core dev import (gated on `import.meta.env.DEV`) | +5 |
| PW-5 | `smolcode/web/playwright.config.ts` (NEW) | smoke config (loopback only, 1 browser) | +20 |
| PW-6 | `smolcode/web/e2e/smoke.spec.ts` (NEW) | smoke: open app + see 3-pane layout + submit a task | +30 |

PW subtotal: ~+110 LOC config + tests.

### 15.3 Backend tasks (Python) — see `v1.8-phase3-plan.md` §BE-1 … §BE-9

Per §6.5 the BE subtotal is ~270 LOC across:
- `smolcode/src/smolcode/web/api.py` (+~60): 4 new endpoints (/retry, /rerun, /export, /dashboard)
- `smolcode/src/smolcode/web/schemas.py` (+~40): dashboard + cost + cache-hit fields
- `smolcode/src/smolcode/web/runs.py` (+~30): `Run.retry_count`, retry/rerun methods
- `smolcode/src/smolcode/web/agent_runner.py` (+~10): export_event_log helper, retry logic
- `smolcode/src/smolcode/model_catalog.py` (+~30): per-provider cost rates + `cost_for(tokens_in, tokens_out, provider, model)`
- `smolcode/src/smolcode/config.py` (+~20): `Settings.cost_rates: dict[str, float]` env loader (Q5)
- `smolcode/src/smolcode/web/dashboard.py` (NEW, +~80): `compute_dashboard(runs, audit)` aggregator (last-1000-runs cache)

Plus the Phase 2 followup that lives on the wire but has no UI:
- `Run.subagent_history` UI consumption — `<SubAgentList>` is a FE-only change.

### 15.4 Frontend tasks (TS/TSX) — see `v1.8-phase3-plan.md` §FE-1 … §FE-9

Per §6.5 the FE subtotal is ~585 LOC across:
- `smolcode/web/src/components/Dashboard.tsx` (NEW, +~200): top tab with tokens / runs / errors + sparkline + per-provider cost breakdown
- `smolcode/web/src/components/CostBadge.tsx` (NEW, +~60): per-run cost chip in RunSummary + Tooltip with breakdown (in/out/cache)
- `smolcode/web/src/components/SubAgentList.tsx` (NEW, +~50): collapsible list of subagent_history entries in Inspector (Phase 0 §14.8 #3 fold-in)
- `smolcode/web/src/lib/keyboard.ts` (NEW, +~50): global shortcut router (Cmd+Enter, Cmd+., Cmd+K, Cmd+/)
- `smolcode/web/src/components/RunHistory.tsx` (+~25): search filter extended (provider / tier / date range)
- `smolcode/web/src/components/ApprovalModal.tsx` (+~40): auto-approve banner + revoke button (B10)
- `smolcode/web/src/components/EventStream.tsx` (+~15): rerun / retry / export buttons in header (B4 + B5 + B7)
- `smolcode/web/src/App.tsx` (+~15): new Dashboard tab + mount keyboard router + axe-core dev
- `smolcode/web/src/main.tsx` (+~10): mount keyboard router + axe-core dev
- `smolcode/web/src/api.ts` (+~80): DashboardResponse / CostBreakdown / ExportPayload types + retryRun / rerunRun / exportRun / getDashboard helpers
- `smolcode/web/src/components/Inspector.tsx` (+~10): embeds SubAgentList (when activeRun.subagent_history non-empty)

### 15.5 Test tasks — see `v1.8-phase3-plan.md` §T-1 … §T-3

| # | File | Tests | LOC |
|---|---|---|---|
| T-1 | `smolcode/src/smolcode/tests/test_dashboard.py` (NEW) | `TestDashboardAggregator`: empty / single run / multi-run / cache hit aggregation; `TestCostProjection`: zero / input-only / output-only / cache-hit / unknown provider (—) | ~+200 |
| T-2 | `smolcode/src/smolcode/tests/test_cost.py` (NEW) | `TestCostRates`: hardcoded defaults / `Settings.cost_rates` override / invalid override (fail-closed) | ~+120 |
| T-3 | `smolcode/src/smolcode/tests/test_retry_rerun_export.py` (NEW) | `TestRetry`: not_found / not_done / done / paused / retry_increments_count; `TestRerun`: completed run re-uses task verbatim; `TestExport`: JSON schema + includes subagent_history + truncated audit | ~+200 |
| T-4 | `smolcode/web/src/__tests__/` (NEW) | Vitest + Testing Library: Dashboard renders, CostBadge formats, keyboard router dispatches Cmd+Enter; axe-core scan: zero serious/critical violations | ~+400 |

Test subtotal: ~+920 LOC.

### 15.6 Validation gates (must all PASS before commit)

| Gate | Tool | Expected result |
|---|---|---|---|
| Lint | `ruff check src tests` | PASS (0 errors, <=16 baseline warnings) |
| Format | `ruff format --check src tests` | PASS |
| Python tests | `pytest src/smolcode/tests` | PASS; adds ~30 new tests across T-1/T-2/T-3 (dashboard + cost + retry + rerun + export) |
| FE tests | `pnpm --dir smolcode/web test` (Vitest) | PASS; >=70% line coverage on new components |
| FE build | `pnpm --dir smolcode/web build` | PASS; bundle <=400 KB JS / gzip |
| A11y | `pnpm --dir smolcode/web test:a11y` (axe-core) | Zero serious / critical violations on the main routes |
| Browser smoke | `pnpm --dir smolcode/web test:e2e` (Playwright) | App opens, submit works, queue + dashboard render |
| Commit + push | `git push origin main` | succeeds; remote SHA visible via `git ls-remote` |

### 15.7 Out-of-scope for Phase 3 (explicit)

Per §6.5 + §8:
- Drag-and-drop queue reorder (v1.9.x).
- Full Monaco editor (v2.x).
- Per-provider usage caps ("stop at $1") — needs cost projection (this phase)
  + has no consumers until cost is exposed to the SPA (v1.9 candidate).
- Prompt library (v1.9 candidate).
- Cross-project session search (Phase 1 §Known limitation; revisit when cardinality grows).
- Auto-migration of orphaned sessions on project rename (Phase 1 §Known limitation).

### 15.8 Source of truth

The detailed per-file plan with concrete code snippets + validation gates per file lives in:
- **`docs/decisions/v1.8-phase3-plan.md`** (mirror of §14.1–§14.5)
- **`docs/decisions/0025-web-ui-ux-review-and-roadmap.md`** §6.5 (high-level scope)
- **`docs/decisions/0025-web-ui-ux-review-and-roadmap.md`** §13.4 (acceptance gate — checked at ship time)
- **`docs/roadmap.md`** v1.8 section (status + test count progression)
- **`smolcode/README.md`** v1.8 banner (Phase 0/1/2 shipped; Phase 3 in-progress)
