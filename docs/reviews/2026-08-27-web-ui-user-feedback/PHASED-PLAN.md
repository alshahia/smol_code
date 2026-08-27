# Web UI User-Feedback Remediation Plan - Phased

Date: 2026-08-27
Source: Web UI user-feedback review of 2026-08-27 (REPORT.md in this folder).
Finding IDs refer to that report (F1 = Dashboard zeros, F2 = Inspector + context circle, F3 = Files invisible, F4 = Outside-workspace selector).
Prior context: Phases 0/1/2 of docs/reviews/2026-08-26-full-app-review/REMEDIATION-PLAN.md shipped at dc2c094. This plan covers the user-feedback batch (post-launch "Phase 3" work) and locally renumbers its phases to avoid colliding with the original plan.
Status: active; Mode: plan only - nothing in this document has been implemented.

---

## Guiding principles

1. Stop lying before adding new things. F1 is a 1-line bug that makes the entire dashboard silently useless. Fix it before anything else so subsequent phases have honest feedback.
2. Surface what is computed. F2 is five layers of "we have the data but never put it on the wire." Add the fields, the extractors, the summary propagation, the catalog source, and the UI - in that order, with a RED test at each seam.
3. Be honest about where files land. F3 is a behavioural surprise, not a security bug. The fix is partly code, partly UI labelling, and partly a policy decision the user has not yet made. Phase 0 captures the policy before Phase 3 touches write_file resolution.
4. Leverage the Phase 2 audit chain. All four fixes keep emitting chained audit records when they touch write paths, so the existing /api/audit?verify=true chip keeps reading ok=true after each phase.
5. Follow repo conventions (ruff line-length 119; make quality then make test before any commit; each shipped phase gets an ADR under docs/decisions/ continuing the numbering (next free = 0037); update TASKS.md as cross-session state).
6. No behaviour change ships without a test that fails when the change is disabled.

Dependency note: Phases are ordered so each depends only on earlier ones. Phase 0 must finish (policy decisions + RED-test scaffold) before Phase 3; Phase 1 can run in parallel with Phase 2 once Phase 0 lands the RED tests.

---

## Phase 0 - RED tests + policy decisions

Objective: write the failing tests for F1/F2/F3/F4 and capture the three policy decisions needed for Phase 3, so later phases are pure green-against-known-target work.
Findings addressed: F1, F2, F3, F4 (RED only - implementation lands in later phases).

### Tasks
1. F1 RED test - new file smolcode/src/smolcode/tests/test_dashboard_phase3.py::TestClockDomain. Construct a fake Run(started_at=time.time() - 3600, ended_at=time.time() - 3540, tokens=TokenSummary(input=100, output=50, total=150), provider="opencode-go", model="deepseek-v4-flash"), hand it to compute_dashboard with a stub audit reader, assert runs_today == 1, errors_today == 0, tokens_today.input == 100, tokens_today.total == 150, sparkline[23] >= 150. Also assert that a Run(started_at=time.time() - 86400 - 10) (just over a day old) is not counted. RED today: fails because runs_today == 0.
2. F2 RED test - new file smolcode/src/smolcode/tests/test_run_summary_phase3.py::TestRunSummaryNewFields. Build a fake Run(tier="restricted", provider="opencode-go", model="deepseek-v4-flash", tokens_in=100, tokens_out=50), call _run_summary(run), assert the response includes model == "deepseek-v4-flash", provider == "opencode-go", context_window == 128000, tokens.cache_hit == 0, tokens.current_input >= 0, tokens.current_output >= 0.
3. F2 cache extractor RED test - new file smolcode/src/smolcode/tests/test_agent_runner_phase3.py::TestCacheTokenExtraction. Construct an ActionStep mock with token_usage=TokenUsage(input_tokens=1000, output_tokens=50) and model_output_message.raw.usage.prompt_tokens_details.cached_tokens=400. Run _action_step_payload(step) and assert the returned dict has tokens.cache_hit == 400. RED today: extractor ignores the field.
4. F2 context catalog RED test - new test_model_catalog_phase3.py::TestContextWindow. Assert resolve_context_window("opencode-go", "deepseek-v4-flash") == 128000, resolve_context_window("MiniMax", "MiniMax-M3") == 2_000_000, resolve_context_window("openai", "gpt-4o") == 128000, resolve_context_window("anthropic", "claude-3-5-sonnet-latest") == 200000, resolve_context_window("unknown", "unknown") is None. RED today: function does not exist.
5. F3 RED tests - new test_effective_cwd_phase3.py::TestProjectRootAnchor. Two cases: (a) Run(project=None) -> effective_cwd == run.workspace (legacy, no change). (b) Run(project="1", workspace="/ws", projects=[ProjectOut(name="1", root="/ws/1")], anchor_to_project_root=True) -> effective_cwd == "/ws/1". RED today: effective_cwd field does not exist. Companion test on _rel_path: assert rel("/ws/1/todo_app/x.py", run_anchored) == "todo_app/x.py" (not "../todo_app/x.py"). RED today: anchored runs still report ../todo_app/...
6. F3 outside-root policy RED test - when effective_cwd == "/ws/1" and the agent asks to write "../outside.txt", the diff callback must (per chosen policy from the user) either (a) silently allow + audit, (b) raise the same approval modal as a normal write, or (c) raise PermissionError without audit. RED test asserts the user-chosen behaviour.
7. F4 RED test - new test_projects_phase3.py::TestProjectCreateWithRoot. POST /api/projects with {name: "ext", root: "/some/path"} and assert the project is created with that root (BE already supports this; this test guards against regression). Companion SPA test in smolcode/web/src/__tests__/ProjectSwitcherOutside.test.tsx (vitest) asserts the new Path input + file picker are rendered when name is non-empty.
8. F4 "Open in Explorer" endpoint RED test - test_open_path_phase3.py::TestOpenPathScoping. POST /api/open-path with {"path": "/ws/todo_app/index.html"} for a run whose effective_cwd == "/ws" returns 200 with {"opened": true}. POST with {"path": "/etc/passwd"} returns 403. RED today: endpoint does not exist.
9. Policy capture - add a section to docs/reviews/2026-08-27-web-ui-user-feedback/POLICY-DECISIONS.md recording the three decisions the user picks (anchor-mode default, outside-root policy, open-path scope). Block on these for Phase 3.
10. TASKS.md - add a "## Phase 3 (web UI feedback) status (2026-08-27)" block summarising F1-F4 and pointing to this plan, mirroring the Phase 0/1/2 status block added at dc2c094.
11. POLICY-DECISIONS.md - capture the three user decisions (anchor default / outside-root policy / open-path scope). **DONE 2026-08-27** in this same session - see POLICY-DECISIONS.md.

### Validation

- pytest -k phase3 exits with the new tests RED (expected).
- make quality && make test still PASS (RED tests are additive - they fail, but no existing test regresses).
- Policy file exists in the review folder; Phase 3 cannot start until all three decisions are filled in.

### Exit criteria

- All 5 RED test files exist; running each in isolation shows the documented failure mode.
- POLICY-DECISIONS.md has user-signed answers for all three questions.

### Size: M.

---

## Phase 1 - F1: Dashboard always zero (clock domain)

Objective: every Dashboard counter, the sparkline, the by-provider table, and the cost-total faithfully reflect the runs that exist.
Findings addressed: F1 (full).

### Tasks
1. smolcode/src/smolcode/web/runs.py - change Run.started_at, Run.ended_at, Run.snapshot_at, Run.append_subagent(started_at=None) default, Run.cancel_queue's run.ended_at = time.monotonic(), and the RunManager FIFO queue_position timestamp - all from time.monotonic to time.time.
2. smolcode/src/smolcode/web/runs.py - _run_summary line 614: duration = max(0.0, run.ended_at - run.started_at) is already wall-vs-wall (after step 1) - keep as is. Do not change Run.remaining_s() / summary_dict() countdown math.
3. smolcode/src/smolcode/web/sessions.py (or wherever the session file naming happens) - if started_at is part of the filename, no change needed (now wall clock; reboots give different timestamps which is what we want).
4. Audit + run history surfaces - search for any other consumer that assumed monotonic; fix if found.
5. docs/security.md / docs/architecture.md - if any doc references started_at semantics, update to clarify "Unix epoch seconds".

### Validation

- The Phase 0 RED test TestClockDomain turns GREEN.
- A fresh pytest -m "not docker" stays green (no other consumer broke).
- Manual probe against the live server: GET /api/dashboard after one run shows runs_today >= 1, tokens_today.total >= 100.
- Restart the server, wait 5 minutes, run another task, refresh dashboard - both runs counted.

### Exit criteria

- F1 fully closed; Phase 0 test green.
- git log -1 includes commit fix(web): Phase 3 F1 - dashboard clock domain (monotonic -> time).

### Size: S.

---

## Phase 2 - F2: Inspector fields + context-window circle

Objective: Inspector shows model+provider, last-step tokens (input, cached, output), session-total tokens (total input, total cached, total output), and a context-window circle with hover-tooltip and clickable breakdown of system prompts / tools / skills / messages.
Findings addressed: F2 (full).

### Tasks
1. smolcode/src/smolcode/model_catalog.py - extend ProviderSpec with default_context_window: int = 128000 (a safe default for unknown models). Add DEFAULT_CONTEXT_WINDOWS: dict[str, dict[str, int]] with the values listed in the REPORT fix surface. Add resolve_context_window(provider, model) -> int | None (overrides via Settings.cost_rates JSON env var, same pattern as _resolve_rates). Public function so the API layer and FE tests can import it.
2. smolcode/src/smolcode/web/agent_runner.py:_action_step_payload - after the existing tokens dict, attempt to read getattr(step.model_output_message.raw.usage.prompt_tokens_details, "cached_tokens", None) (OpenAI shape), fall back to getattr(step.model_output_message.raw.usage, "cache_read_input_tokens", 0) + getattr(step.model_output_message.raw.usage, "cache_creation_input_tokens", 0) (Anthropic shape). Emit cache_hit in the tokens dict. All in a try/except so missing-attr never breaks the SSE stream.
3. smolcode/src/smolcode/web/runs.py - extend the Run dataclass with last_step_tokens: dict = field(default_factory=dict) and last_step_at: float | None = None (wall clock). publish() updates both on every EVT_STEP_ACTION that carries tokens (same lock window as the existing aggregation). summary_dict() exposes both.
4. smolcode/src/smolcode/web/schemas.py:TokenSummary - add fields (all additive with defaults so old wire callers still parse): cache_hit: int = 0, current_input: int = 0, current_output: int = 0, last_step_at: float | None = None. Add a new Pydantic schema ContextBreakdown with system: int = 0, tools: int = 0, skills: int = 0, messages: int = 0, total: int = 0. Extend RunSummary with model: str = "", provider: str = "", context_window: int | None = None, context_used: int | None = None, context_breakdown: ContextBreakdown | None = None.
5. smolcode/src/smolcode/web/agent_runner.py:run_in_thread - after each step.action publish, compute context_breakdown by walking agent.memory and agent.tools. Cache the most recent value on the Run (recompute only on step boundaries; the agent thread is the writer; readers hold pending_lock for snapshot consistency). Use tiktoken.encoding_for_model(model).encode(text) with a len(text) // 4 heuristic fallback. On any exception, log a warning and emit context_breakdown = None (do not crash the run).
6. smolcode/src/smolcode/web/api.py:_run_summary - propagate the new fields. Also forward run.workspace as the fallback context_breakdown.source so the FE can label it.
7. smolcode/web/src/components/Inspector.tsx - restructure the Active-run and Token-usage sections:
   - Active run: add model: {provider}/{model} line and context: {pct}% of {ctx_window.toLocaleString()} tokens line (right below the model line).
   - Token usage: split into two tables - Last step (input, cached input, output) and Session total (total input, total cached input, total output, step_count). Right-align numbers; monospace code formatting.
   - Add a new section Context window:
     - Circle - inline SVG ring (24px), stroke-dasharray driven by pct; turns red above 85 %.
     - Hover tooltip - <div class="tooltip" role="tooltip">{pct}% consumed ({context_used.toLocaleString()} / {context_window.toLocaleString()})</div> shown on mouseenter/focus.
     - Click - opens a <dialog> (native modal) titled "Context breakdown" with four rows: System prompts (X tokens, Y%), Tools (X tokens, Y%), Skills (X tokens, Y%), Messages (X tokens, Y%). Numbers monospace; percent bar to the right.
     - Keyboard accessible - circle is a <button type="button"> with aria-label, Enter/Space opens the dialog. Escape closes.
8. smolcode/web/src/components/Inspector.css - add styles for the new layout; the circle uses currentColor for the ring stroke and a darker shade for the unfilled portion.
9. vitest unit tests - new InspectorTokens.test.tsx covers (a) per-step + session split rendering, (b) context-circle pct = context_used/context_window*100 with cap at 100, (c) dialog opens on click, (d) cache_hit shown when > 0 and hidden when 0.
10. e2e test - extend smolcode/web/e2e/inspector.spec.ts with a happy-path: open a finished run (the existing one from dc2c094), assert the Inspector shows opencode-go / deepseek-v4-flash, the per-step vs session tables, and that clicking the circle opens the breakdown dialog with four rows.

### Validation

- All Phase 0 F2 RED tests turn GREEN.
- New vitest tests + new e2e spec turn GREEN.
- Manual: load the existing run, verify the numbers match /api/runs.

### Exit criteria

- F2 fully closed.
- pnpm build size delta < +5 KB JS gzip (the breakdown modal is the only nontrivial addition).
- git log -1 includes feat(web): Phase 3 F2 - Inspector breakdown + context circle.

### Size: L.

---

## Phase 3 - F3: Honour the project root for write_file + Open in Explorer

Objective: when the user selects a project and toggles "anchor writes to this project's root" (or it's the default per the policy decision), the agent's write_file/patch_file resolve relative paths against the project root; the Inspector shows the actual working root and offers Open in Explorer.
Findings addressed: F3 (full). Blocked until Phase 0 policy decisions are signed.

### Tasks (each numbered to match the policy decisions)
1. smolcode/src/smolcode/web/runs.py - extend Run with effective_cwd: Path | None = None, anchor_to_project_root: bool = False. Default OFF per the recommended policy (backward-compatible). On start, RunManager.start_run / start_or_enqueue_run resolve effective_cwd from (run.anchor_to_project_root AND run.project AND matching_project_root exists) ? Path(matching_project_root) : Path(settings.workspace).
2. smolcode/src/smolcode/web/schemas.py:RunStartRequest - add optional anchor_to_project_root: bool = False.
3. smolcode/src/smolcode/web/agent_runner.py:_build_agent_for_run - accept and forward effective_cwd. For executor_type="local", set LocalExecutor(cwd=str(effective_cwd)) (smolagents LocalExecutor accepts cwd=). For executor_type="docker", mount effective_cwd as /workspace and pass executor_kwargs={"work_dir": "/workspace"}. Audit the resolution in the run.started event payload.
4. smolcode/src/smolcode/web/agent_runner.py:_rel_path - when run.effective_cwd is set AND run.effective_cwd != Path(run.workspace).resolve(), anchor relative paths against effective_cwd instead of workspace. Update touched_paths semantics accordingly.
5. smolcode/src/smolcode/web/agent_runner.py:_build_diff_callback - when run.anchor_to_project_root is True and the diff path resolves outside run.effective_cwd, apply the Q2 policy (BLOCK + full-path confirmation modal + per-session per-path allowlist per POLICY-DECISIONS.md). The callback:
   - Computes absolute_target = str(Path(path).resolve()).
   - Checks current_session().outside_root_allowlist under run.pending_lock; if present, auto-approves and emits diff_decision audit with outside_root=true, auto_approved=true (no modal).
   - Otherwise opens a NEW PendingDecision with kind="outside_root" and publish EVT_APPROVAL_REQUESTED with payload {decision_id, kind: "outside_root", absolute_target, effective_cwd, allowed_actions: ["deny", "approve_once", "approve_session_for_path"]}.
   - Blocks on PendingDecision.event (same timeout as the standard destructive gate).
   - On resolve: Deny -> DiffDecision(approved=False); Approve once -> DiffDecision(approved=True, reason="user-once"); Approve for session for THIS path -> adds absolute_target to current_session().outside_root_allowlist, then DiffDecision(approved=True, reason="user-session-for-path").
   - Each outcome emits a diff_decision audit record with outside_root=true and an action discriminator (deny / approve_once / approve_session_for_path).
6. smolcode/src/smolcode/web/agent_runner.py - small new endpoint POST /api/open-path (smolcode/src/smolcode/web/api.py) accepting {"path": "..."}. Whitelist: the path must be inside run.effective_cwd (or settings.workspace if no run_id in body). Implementation: shell out to subprocess.run([platform-specific command], shell=False, timeout=3) - Windows ["cmd", "/c", "start", "", abs_path], macOS ["open", abs_path], Linux ["xdg-open", abs_path]. Defensive: return 403 on path-escape, 404 if missing, 500 with redacted detail on subprocess failure.
7. smolcode/web/src/components/RunComposer.tsx - add the "anchor writes to this project's root" checkbox below the project selector. State lives in component-local React state (not persisted across reloads, to match the policy recommendation).
8. smolcode/web/src/components/Inspector.tsx - Active-run section: add Working root: {effective_cwd} [Open] row. The [Open] is a button that POSTs /api/open-path and renders a tiny toast on failure. When run.project is set AND run.effective_cwd != project.root, show a small yellow notice: "this run's files landed in {effective_cwd}, not in project {run.project} ({project.root}). Enable Anchor writes to this project's root in the composer next time."
9. Update _run_summary to propagate effective_cwd, anchor_to_project_root on the wire so the Inspector and RunHistory can render the notice.
10. vitest + e2e - new EffectiveCwd.test.tsx and extension of inspector.spec.ts. E2E: select project + anchor, run a tiny task that writes a file, verify the file lands in the project root and the Inspector shows the new Working root line.
10a. smolcode/src/smolcode/session.py + ApprovalModal.tsx - per the Q2 policy (POLICY-DECISIONS.md):
    - Extend SessionState with outside_root_allowlist: set[str] = field(default_factory=set). Reset on every new SessionState() (every new run).
    - Add a SPA ApprovalModal variant (or branch in the existing modal keyed on pending.kind === "outside_root") that renders: absolute target path (monospace, prominent), effective cwd for context, and three buttons (Deny / Approve once / Approve for this session for THIS path).
    - The "Approve for this session for THIS path" button POSTs the approval with reason="user-session-for-path"; the BE adds absolute_target to the allowlist.
    - A unit test exercises: (a) deny -> PermissionError, (b) approve_once -> allowed once then block again, (c) approve_session_for_path -> allowed twice in a row (second one hits the allowlist), (d) the allowlist is reset on a new run.

### Validation

- All Phase 0 F3 RED tests turn GREEN.
- Manual: with project "1" anchored, run "create test.txt in /", verify ls .web-ws/1/test.txt exists and ls .web-ws/test.txt does not. Then un-anchor, re-run, verify the file lands in .web-ws/.
- audit log reflects the outside_root=true events when applicable.

### Exit criteria

- F3 fully closed; policy decisions honoured.
- git log -1 includes feat(web): Phase 3 F3 - project-root anchoring + open-path.

### Size: M-L (the outside-root modal adds 1-2 days over the original M estimate).

---

## Phase 4 - F4: Outside-workspace project selector

Objective: the user can attach an arbitrary outside-workspace directory as a project, with a file-picker, a path field, and a recent projects list. Backwards compatible with the existing in-workspace default.
Findings addressed: F4 (full).

### Tasks
1. smolcode/web/src/components/ProjectSwitcher.tsx - extend handleCreate to send {name, root} when the user supplies a path. The form layout becomes:
   - Name input (existing).
   - Path input (new) - text input pre-filled with <workspace>/<name>; user can replace.
   - Browse button (new) - opens <input type="file" webkitdirectory directory multiple>. On change, populate the Path field with file.webkitRelativePath.split("/")[0]'s parent (browser reports the picked folder's name; the user knows the absolute path is at the platform-standard home/last-used location - we will grab it via a new lightweight endpoint, see below).
   - Recent dropdown (new) - populated from localStorage.smolcode.recentProjects.v1 (array of {name, root, last_used}); clicking a recent fills the form.
2. smolcode/web/src/api.ts - createProject accepts {name, root?}. Wire handleCreate accordingly. The SPA file-picker cannot return the absolute path in any browser (security), so we offer a "use the workspace path" hint plus a manual paste; the BE validates the path exists when supplied.
3. smolcode/web/src/components/ProjectSwitcher.tsx - outside-workspace notice: when the user picks a root outside settings.workspace, show an inline note: "this project's files will live outside the default workspace ({workspace}); full_access can still reach anywhere."
4. Tests - extend smolcode/web/src/__tests__/ProjectSwitcher.test.tsx (and create a new ProjectSwitcherOutside.test.tsx per the Phase 0 RED test). Cover: in-workspace default keeps working; explicit root is sent in the POST body; recent projects persist to localStorage; the outside-workspace notice renders when applicable.
5. e2e - extend smolcode/web/e2e/sessions.spec.ts (or create project-switcher.spec.ts) to assert: clicking + project and pasting a path creates a project at that path.

### Validation

- Phase 0 F4 RED tests turn GREEN.
- POST /api/projects {name: "ext", root: "E:\\outside"} creates the project; GET /api/projects lists it.
- GET /api/config includes the new project in the projects array.
- Selecting the project and toggling "anchor writes" (from Phase 3) writes to the outside path.

### Exit criteria

- F4 fully closed.
- git log -1 includes feat(web): Phase 4 F4 - outside-workspace project selector.

### Size: M.

---

## Suggested sequencing & effort

| Phase | Theme | Depends on | Size |
|---|---|---|---|
| 0 | RED tests + 3 policy decisions | - | M |
| 1 | F1 dashboard clock domain | 0 | S |
| 2 | F2 inspector fields + context circle | 0 | L |
| 3 | F3 project-root anchoring + open-path | 0 (policy) | M |
| 4 | F4 outside-workspace selector | 0 (1 for sanity) | M |

Phases 1, 2, 3 can run in parallel once Phase 0 merges. Phase 4 depends on Phase 1 only to verify the dashboard counts it after writing to an outside workspace.

## Definition of done (all phases)

- Each finding closed by a commit whose test fails without the fix (red->green evidence in commit message body).
- make quality && make test PASS; CI green including the Phase 3 marker tests.
- Behaviour changes ship an ADR (docs/decisions/0037-phase3-web-ui-fixes.md will be written at the start of Phase 1).
- TASKS.md updated with a "## Phase 3 (web UI feedback) status" block at the end of each phase.
- No secrets introduced; public API changes documented in docs/architecture.md.
- Live server probe (the same pwsh-2 instance the user is running) shows: GET /api/dashboard non-zero after a run; Inspector shows model + cache + context circle; workspace tree highlights land in the project root when anchor is on.

## Outstanding questions - RESOLVED 2026-08-27

User decisions captured in `docs/reviews/2026-08-27-web-ui-user-feedback/POLICY-DECISIONS.md`. Phase 3 unblocked.

| # | Question | User pick | Implementation consequence |
|---|---|---|---|
| 1 | Anchor-mode default | **OFF per-run** | Task 1-2 wire default is False; SPA checkbox defaults unchecked |
| 2 | Outside-root policy | **BLOCK + full-path modal + per-session per-path allowlist** | Task 5 implements the full flow (auto-allow hit / deny / approve once / approve session for this path) plus new SessionState.outside_root_allowlist + new SPA ApprovalModal variant |
| 3 | Open-path scope | **any path under effective_cwd** | Task 6 redirects full_access writes (with audit marker) but otherwise reuses the /api/files whitelist helper |

Phase 0 task 9 (capture policy) is now marked RESOLVED.
