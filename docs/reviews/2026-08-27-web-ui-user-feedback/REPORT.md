# Web UI User-Feedback Review — Root-Cause Report

**Date:** 2026-08-27
**Author:** review-only pass (no code changes)
**Repo:** `E:\python projects\smol_code` @ `dc2c094` (branch `main`, clean tree post-Phase 2)
**Source feedback:** direct user report after exercising the web UI against the Phase 2 build (commit `dc2c094`).
**Companion documents (this folder):** `PHASED-PLAN.md`.
**Related prior work:** `docs/reviews/2026-08-26-full-app-review/` (the full review that produced the Phases 0 → 7 plan, of which Phases 0–2 are shipped at `dc2c094`).
**Status:** active · **Mode:** review/analysis only — nothing in this document has been implemented.

---

## Validation results

| Check | Result |
|---|---|
| `pytest --collect-only -q` (BE, Python 3.12) | PASS — collection clean, no import errors |
| `ruff check src tests` | 0 errors (post-Phase 2) |
| `ruff format --check src tests` | 0 drift (post-Phase 2) |
| `GET /api/dashboard` against live `pwsh-2` server | returns zero counters despite 1 real run in `/api/runs` |
| `GET /api/runs` against live `pwsh-2` server | 1 run, `status=done`, `started_at=1 216 264.359` (monotonic), `tokens_in=51 696`, `touched_paths=["todo_app/*.md|html|css|js"]`, `project="1"`, `provider="opencode-go"`, `model="deepseek-v4-flash"` |
| `GET /api/audit?verify=true` against live server | 7 chained entries, `chain.ok=true` |
| `GET /api/projects` against live server | 1 project (`name="1"`, `root=".web-ws\1"`) |
| On-disk check of agent-written files | confirmed at `.web-ws\todo_app\{index.html,style.css,app.js,README.md}` — NOT at `.web-ws\1\todo_app\…` despite `project="1"` being selected |

## Executive summary

After Phases 0–2 shipped, the user exercised the web UI end-to-end with a real LLM provider and reported four distinct UX failures. All four are reproducible against the live `pwsh-2` instance and each has a clearly identifiable root cause in the source.

**The dominant pattern is "data is computed but never surfaced to the UI" — three of four issues are presentation-layer omissions over an already-working backend:**

1. **Dashboard always zero** — a clock-domain bug (`time.monotonic` mixed with `time.time`) makes every counter silently empty after the server has been up for more than a few seconds.
2. **Inspector shows token totals but not cache hits, not model, not current-step vs session-total, and no context-window visualisation** — the schema, extractor, summary, and component are all missing fields the user explicitly wants.
3. **Files appear in the UI but cannot be found on disk** — the `project` field on a Run is recorded for telemetry only; the agent's `write_file` always resolves paths against `settings.workspace`, never the project root, and the SPA never surfaces the absolute landing path.
4. **No way to attach an outside-workspace directory** — the SPA's `ProjectSwitcher` only creates `<workspace>/<name>` projects; the BE supports arbitrary `root` but the SPA never exposes it.

**Verdict:** Phase 2 hardened the audit pipeline (H5/H6 closed); the user's new findings are UX/visibility debt that the original review (2026-08-26) did not exercise because the reviewer never logged into the running web UI. They are not regressions — they are pre-existing gaps surfaced now that the UI is actually usable.

---

## Finding index

IDs are reused here only inside this document. Severity ranks the user-visible impact (P0 = blocks primary workflow).

- **F1 — Dashboard aggregates always report zero (P0)**, even when runs exist.
- **F2 — Inspector hides model, cache, current-vs-total tokens, and context-window usage (P1)**, forcing users to fly blind on cost and capacity.
- **F3 — Agent-written files are silently routed to the workspace root regardless of selected project (P0)**, leading users to look in the wrong directory.
- **F4 — No UI path to attach an arbitrary outside-workspace project or open an existing local one (P2)**, forcing server restart to change `SMOLCODE_WORKSPACE`.

---

## F1 — Dashboard shows zero / NaN

### Symptoms
- `Dashboard ▾` overlay shows: runs today `0`, tokens today `0`, errors today `0`, cost today `--`, empty 24-bucket sparkline, empty per-provider table — even immediately after a run completes.
- User reports occasional NaN values (we observed zero only — see "Why no NaN" below).

### Live evidence
```
GET /api/dashboard -> 200
  runs_today: 0, tokens_today: {input:0,output:0,total:0},
  sparkline: [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
  by_provider: {}, cost_estimate_usd_today: 0, generated_at: 1 787 814 830.3

GET /api/runs -> 200
  runs: [{ id: "1454…6e9a", task: "create a simple todo app", tier: "restricted",
           status: "done", started_at: 1 216 264.359, ended_at: 1 216 378.937,
           duration_s: 114.58, tokens: {input:51 696,output:5 690,total:57 386},
           touched_paths: ["todo_app/{README.md,app.js,index.html,style.css}"],
           project: "1", provider: "opencode-go", model: "deepseek-v4-flash" }]
```
The current wall clock is ~1.79 × 10⁹ seconds (epoch); the run's `started_at` is 1.22 × 10⁶ — a gap of ~1.79 × 10⁹ seconds, which is **56.6 years**.

### Root cause — **two incompatible clock domains**

Two time-keeping functions are mixed inside the same comparison:

| Where | Code | Clock |
|---|---|---|
| `smolcode/src/smolcode/web/runs.py:177` (Run dataclass) | `started_at: float = field(default_factory=time.monotonic)` | **monotonic** (seconds since boot) |
| `smolcode/src/smolcode/web/runs.py:178` | `ended_at: float = None` (assigned via `time.monotonic()` too) | monotonic |
| `smolcode/src/smolcode/web/dashboard.py:79` | `now = time.time()` | **wall** (Unix epoch) |
| `smolcode/src/smolcode/web/dashboard.py:80` | `day_start = now - 86400` | wall |
| `smolcode/src/smolcode/web/dashboard.py:88` | `today = [r for r in runs if r.started_at >= day_start]` | compares **monotonic vs wall** — always false |
| `smolcode/src/smolcode/web/dashboard.py:67` | `age_h = (now - r.started_at) / 3600.0` | subtracts wall – monotonic → wildly negative |

Consequences, each independently fatal:
1. `r.started_at >= day_start` is **always False** → `today=[]` → every counter is 0.
2. `age_h < 0` triggers the early-skip in `_sparkline_24h` → every bucket is 0.
3. `by_provider` accumulator loops over `today` which is empty → empty dict.

Why it took until now to surface: a reviewer running the test suite immediately after server boot sees a `time.time()` / `time.monotonic()` gap of seconds, not years — `started_at` values appear "recent" enough to match the filter on the very first run of a freshly-started test process. The bug only manifests after the server has been up for any meaningful wall-clock duration. **A regression test against `time.time() - 3600` immediately exposes it.**

### Why no NaN
The Dashboard component guards every divide (`Math.max(1, ...sparkline)` for the sparkline; `cap > 0 ? pct : 0` for the per-provider progress bar; `cost > 0 ? "$"+cost : "--"` for cost display), so the zero/empty pipeline never promotes to NaN. If the user is seeing NaN it is on a different surface (the `cost_estimate_usd_today` could become NaN via a divide if a future refactor computes average-per-run; today it is `round(cost, 6)` from sums).

### Fix surface
- `runs.py:177–178` — change `time.monotonic` → `time.time` for `started_at` / `ended_at` / `snapshot_at` / `cancel_queue`'s `run.ended_at = time.monotonic()`.
- **`Do NOT touch`** `Run.remaining_s()` / `summary_dict()`'s countdown math — that legitimately uses `time.monotonic()` because it must not jump if the system clock changes.
- Add regression: `compute_dashboard` against a fake `Run(started_at=time.time() - 3600)` must report `runs_today == 1` and `sparkline[23] > 0`.
- Also: the session-file naming in `sessions.py` uses `started_at` as a timestamp prefix — must move to `time.time` to keep the file-naming stable across server reboots.

### Cross-cutting observations (not user-reported)
- `_run_summary` line 614 uses `time.monotonic()` for `duration = ended_at - started_at` — this is **wrong** if both are now `time.time()`; the diff of two wall clocks is fine, so just keep the source of truth consistent.
- `Run.started_at` is also exposed on the wire (`RunSummary.started_at`); the SPA's `EventStream` does not currently render it but a future run-timeline view would expect wall-clock seconds.

---

## F2 — Inspector is missing model, cache, current-vs-total tokens, and context-window usage

### Symptoms
- Active-run block: shows `id`, `status`, `tier`, `duration`, `error`. **No model name; no provider.**
- Token usage block: shows `input`, `output`, `total`, `step_count`. **No cache-hit breakdown; no separation of "this step" vs "session total"; no context-window gauge.**
- The user wants:
  - Per-run (this step / last action): `input`, `cached input`, `output` (three numbers).
  - Session totals: `total input`, `total cached input`, `total output` (three numbers).
  - **A circle** that fills as context is consumed from the model's max context — hover shows %, click opens a breakdown of what context was fed (system prompts / tools / skills / messages).

### Root cause — **four-layer omission**

**Layer 1 — schema does not carry the fields** (`smolcode/src/smolcode/web/schemas.py:225–235`):
```python
class TokenSummary(BaseModel):
    input: int = 0
    output: int = 0
    total: int = 0
```
No `cache_hit`, no `current_input`/`current_output`, no `model`/`provider`, no `context_window`, no `context_breakdown`. The Pydantic schema is the wire format; nothing downstream can carry data the schema does not declare.

**Layer 2 — extractor does not read cache fields** (`smolcode/src/smolcode/web/agent_runner.py:283–289`):
```python
tokens = getattr(step, "token_usage", None)
if tokens is not None:
    out["tokens"] = {
        "input": int(getattr(tokens, "input_tokens", 0) or 0),
        "output": int(getattr(tokens, "output_tokens", 0) or 0),
    }
```
smolagents 1.26.0's `TokenUsage` dataclass (`smolagents/monitoring.py`) declares only `input_tokens` / `output_tokens` / `total_tokens`. The provider responses **do** include cache data — OpenAI returns `response.usage.prompt_tokens_details.cached_tokens`; Anthropic returns `cache_creation_input_tokens` and `cache_read_input_tokens` — but smolagents discards it before our code sees it. **However**: smolagents stores `raw=response` on the `ChatMessage` (see `LiteLLMModel.generate` in `.venv/.../smolagents/models.py`), so the cache data IS reachable via `step.model_output_message.raw.usage.prompt_tokens_details.cached_tokens` without modifying smolagents.

**Layer 3 — `_run_summary` drops `run.model` and `run.provider`** (`smolcode/src/smolcode/web/api.py:603–655`):
```python
tokens=TokenSummary(
    input=int(snap["tokens_in"]),
    output=int(snap["tokens_out"]),
    total=int(snap["tokens_total"]),
),
```
The Run dataclass carries `run.model = "deepseek-v4-flash"` and `run.provider = "opencode-go"` (visible in `/api/runs` JSON today), but `_run_summary` does NOT propagate them into `RunSummary`. The Inspector can't show what it doesn't receive.

**Layer 4 — Inspector never reads the fields, and there is no context-window data anywhere** (`smolcode/web/src/components/Inspector.tsx:71–131`):
- Active-run section does not consult `activeRun.model` / `activeRun.provider`.
- Token-usage section renders only the three scalar fields.
- `model_catalog.PROVIDERS` does not declare a `context_window` field anywhere in `smolcode/src/smolcode/model_catalog.py` (grep for `context_window|context_length|max_context` returns nothing). Without that data the context-circle has nothing to compare against.

### Fix surface — five files
1. `model_catalog.py` — extend `ProviderSpec` with `default_context_window: int`; extend per-model `DEFAULT_COST_RATES` (or new `DEFAULT_CONTEXT_WINDOWS` dict) with `{model: ctx_tokens}`. Hardcode known values: `deepseek-v4-flash=128000`, `MiniMax-M3=2_000_000`, `gpt-4o=128000`, `gpt-4o-mini=128000`, `o1-preview=128000`, `o1-mini=128000`, `claude-3-5-sonnet-latest=200000`, `claude-3-5-haiku-latest=200000`, `claude-3-opus-latest=200000`. Add `_resolve_context_window(provider, model)`.
2. `agent_runner.py:283–289` — extract cache tokens via `step.model_output_message.raw.usage.prompt_tokens_details.cached_tokens` (with try/except for missing attrs); fall back to `cache_read_input_tokens + cache_creation_input_tokens` for Anthropic. Emit `cache_hit` in the `step.action` payload alongside `input`/`output`.
3. `runs.py` — extend `Run.summary_dict` to track `last_step_tokens` (a snapshot of the most recent `step.action` payload's tokens, reset on each publish) in addition to the session totals. Extend `TokenSummary` schema in `schemas.py` with `cache_hit`, `current_input`, `current_output`, `last_step_at`. Extend `RunSummary` with `model: str`, `provider: str`, `context_window: int | None`.
4. `_run_summary` (api.py:603) — populate the new fields from the snapshot.
5. `Inspector.tsx` — add a Model line; split Token usage into "This step" vs "Session total"; render the context circle as an inline SVG ring with hover tooltip + clickable modal showing `{system: N, tools: N, skills: N, messages: N}` with percentages.

### Context-circle breakdown: how to compute without adding a tokenizer dep

Tiktoken is already installed (`tiktoken-0.14.0`); `litellm` exposes `litellm.token_counter(model, messages)` which uses the right model's encoding. The breakdown walks `agent.memory`:
```
system   = tokens(system_prompt.system_prompt)
messages = sum(tokens(step.dict())) for step in memory.steps
           (covers task, model_output, observations, plan)
tools    = sum(tokens(tool.name + tool.description + tool.inputs_schema))
           for tool in agent.tools.values()
skills   = sum(tokens(step.code_action) for step in ActionStep)
           (the agent's executable code it has been writing - the "skills" the user mentioned)
```
Where `tokens(text)` calls `tiktoken.encoding_for_model(model).encode(text)` with a `len(text) // 4` heuristic fallback if encoding init fails. The four sums produce the four breakdown buckets; the percentages are each divided by the sum of all four.

### Why no NaN here either
The Inspector's current display is fully integer (no division); once we add the context-circle we divide by `context_window`, which we must guard with `context_window > 0 ? pct : 0` (mirroring the Dashboard pattern).

---

## F3 — Files visible in UI but not findable on disk

### Symptoms
Run history shows `touched_paths: ["todo_app/README.md", "todo_app/app.js", "todo_app/index.html", "todo_app/style.css"]`. The Workspace tree (Inspector) shows the same files. User looked for them on disk in:
- The repo root - empty.
- The workspace directory - actually they ARE here (`.web-ws\todo_app\…`), but the user expected them at `.web-ws\1\todo_app\…` because they had project `"1"` selected.
- The uploads area - wrong, that's where UPLOADED files go.

### Live evidence
```
audit entry { event: "diff_decision", tool: "write_file",
  path: "E:\\python projects\\smol_code\\smolcode\\.web-ws\\todo_app\\index.html",
  approved: true, edited: false, run_id: "1454..." }
audit entry { ..., path: "E:\\python projects\\smol_code\\smolcode\\.web-ws\\todo_app\\style.css" }
audit entry { ..., path: "E:\\python projects\\smol_code\\smolcode\\.web-ws\\todo_app\\app.js" }
audit entry { ..., path: "E:\\python projects\\smol_code\\smolcode\\.web-ws\\todo_app\\README.md" }

project "1" root: E:\\python projects\\smol_code\\smolcode\\.web-ws\\1

ls .web-ws\todo_app\   -> 4 files (confirmed on disk)
ls .web-ws\1\todo_app\ -> does not exist
```
**Files were written to the workspace root, NOT the project root, despite `project="1"` being set on the run.**

### Root cause - `project` is decorative; it does NOT change the agent's working directory

| Where | What |
|---|---|
| `smolcode/src/smolcode/web/runs.py:180` | `workspace=str(getattr(settings, "workspace", "") or "")` - the workspace root, ignoring `run.project` |
| `smolcode/src/smolcode/web/agent_runner.py:_rel_path` | `_rel_path(run, abs_path)` resolves relative to `run.workspace`, never `run.project`. That's why `touched_paths` shows `todo_app/` (workspace-relative) instead of `../todo_app/` (project-relative). |
| `smolcode/src/smolcode/web/agent_runner.py:_build_agent_for_run` (~lines 711-740) | Constructs `build_<tier>_agent(settings, model)` with **no** `cwd=` / `project_root=` override. The smolagents `write_file` tool sees `path="todo_app/index.html"` and resolves it against `settings.workspace`. |
| `smolcode/src/smolcode/web/agent_runner.py:_PathForMentions` block (~lines 782-798) | DOES compute `project_root` correctly from `run.project` - but only for `@<path>` mention expansion in the task string, NOT for the write_file tool's path resolution. |

### Interpretation chosen - the user picked Option A-light (toggle-off by default) + strict gate (Q2)

The user picked:
- **Q1 (anchor default)**: OFF per-run. Selecting a project does NOT redirect writes by default; the user must tick "anchor writes to this project's root" in the composer.
- **Q2 (outside-root policy)**: BLOCK with a confirmation modal that shows the FULL absolute target path, with a per-session per-path allowlist ("Approve for this session for THIS path"). When the user makes that choice, future writes to that exact absolute path skip the modal for the remainder of THIS run's session. Captured in `POLICY-DECISIONS.md`.
- **Q3 (open-path scope)**: any path under `effective_cwd` (the standard `/api/files` whitelist helper, no per-write approval).

Implication: the original "Option B (just label the surprise)" path was REJECTED in favour of Option A-light. The user wants the STRICTEST behaviour here: writes are blocked at the gate when they escape the project root, with a clear modal showing where the agent wants to write, AND a per-path memory so the user doesn't have to re-approve the same path repeatedly within one session.

### Fix surface (regardless of policy)
1. `runs.py` - record `effective_cwd: Path | None` on Run (the resolved working directory: project root if anchor-toggle ON, else workspace root).
2. `agent_runner.py:_build_agent_for_run` - accept `effective_cwd`; pass to a smolagents wrapper that pins `executor.cwd = effective_cwd` (smolagents `DockerExecutor` / `LocalExecutor` both accept `cwd=`).
3. `agent_runner.py:_rel_path` - when `run.effective_cwd != run.workspace`, use `effective_cwd` as the relative anchor.
4. `Inspector.tsx` - add a "Working root" line under Active-run that shows `effective_cwd` with an "Open in Explorer" link (uses `cmd /c start ""` on Windows / `open` on macOS / `xdg-open` on Linux via a tiny new `POST /api/open-path` endpoint that whitelists paths inside `effective_cwd`).
5. Banner: when `run.project` is set AND `run.effective_cwd != project.root` AND the toggle is OFF, show a small notice: "this run's files landed in the workspace root, not in project X. Enable 'Anchor writes to project root' in the composer next time."

---

## F4 - Workspace selector cannot open existing or outside-workspace paths

### Symptoms
- The header `ProjectSwitcher` dropdown only lists projects already in `Settings.projects` plus a `+ project` textbox that creates `<workspace>/<name>` only.
- To change the active directory the user must restart the server with a different `SMOLCODE_WORKSPACE` env var.
- No "open folder" or "open file" picker anywhere.

### Root cause - SPA wires half of what the BE supports

| Where | Status |
|---|---|
| `smolcode/src/smolcode/web/schemas.py:84-92` (`ProjectCreateRequest`) | Accepts optional `root: str`; docstring already says "omit to default to <workspace>/<name>" |
| `smolcode/src/smolcode/web/api.py:347-393` (`POST /api/projects`) | Handles `root`; validates it exists |
| `smolcode/web/src/components/ProjectSwitcher.tsx:39-58` (`handleCreate`) | **Posts only `{name}` - never sends `root`.** The "create outside-workspace" path is API-complete but UI-incomplete. |

### Fix surface - UI-only extension
1. Extend `handleCreate` to send `{name, root}` when the user supplies a path.
2. Add an `<input type="file" webkitdirectory directory multiple>` next to the name field; on change, populate the path input from `file.webkitRelativePath.split("/")[0]`-derived root (the user picks a folder; we use the path that the browser reports).
3. Add a recent-projects list (last 5 from `localStorage.smolcode.recentProjects.v1`).
4. The "outside-workspace" gate: confirm with the user that writes will go outside the default workspace; this is just informational - the BE allows it already (when `root` is provided and exists).

### Security note
Phase 1 made write_file enforce `path` resolution against `settings.workspace` for restricted/elevated. With F3 fixed (anchor toggle + project root), **`full_access` writes can target any absolute path** - that's the documented design. The toggle + project-root anchoring changes NOTHING for the security model; it only redirects the working directory for `write_file`/`patch_file` relative paths. **No security control is weakened.**

---

## Severity ranking for triage

| Rank | Finding | User impact | Fix complexity | Phase |
|---|---|---|---|---|
| **P0** | F1 - Dashboard always zero | Mislies about every aggregate; users can't see their usage | 1-line + 1 test | Phase 1 |
| **P0** | F3 - Files invisible (project root not honoured) | Silent data-loss illusion; users can't find what they paid tokens for | Medium (chdir + rel-path + UI banner) | Phase 3 (after policy decision) |
| **P1** | F2 - Inspector missing fields + context circle | Loses cost-caching discount + visible "which model is running" + zero context awareness | Large (5 layers: schema -> extractor -> summary -> catalog -> UI) | Phase 2 |
| **P2** | F4 - No outside-workspace selector | Workflow friction; users must restart server with new env | Small (UI + pass-through) | Phase 4 |

---

## Strengths (not user-reported, observed during review)
- The audit chain (`dc2c094`) correctly tracked all 7 entries including the write-file diff decisions.
- The diff gate + user-approval flow worked end-to-end (4 approved writes, chain ok).
- Sub-agent events (none in this run, but the schema is in place).
- Workspace tree highlights `touched_paths` - already shipped (Phase 1 fix).

## Limitations
- Live UI was exercised against a single provider (`opencode-go / deepseek-v4-flash`); cache-hit behaviour is inferred from the litellm response shape, not observed live. The Phase 2 plan arranges for a fixture-driven test that doesn't depend on a live provider.
- Context-window sizes in `model_catalog.py` are best-effort from provider docs as of 2026-08; we will accept user-supplied overrides via `Settings.cost_rates`-style JSON.
- "Skills" interpretation: in the absence of a formal Skills subsystem, we map "skills" to the agent's accumulated `code_action` snippets (its reusable patterns) plus the tool-call invocations. If the user wants a different mapping we will adjust in the same phase.

---

## Decision needed before Phase 3 starts - RESOLVED 2026-08-27

User answers captured in `docs/reviews/2026-08-27-web-ui-user-feedback/POLICY-DECISIONS.md`. Phase 3 unblocked.

Recap:

1. **Anchor mode default** - user picked **OFF per-run**. Selecting a project shows an "anchor writes to this project's root" checkbox; default unchecked. Backward-compatible with legacy runs.
2. **Outside-root policy** - user picked **BLOCK + confirmation modal that shows the FULL absolute target path + per-session per-path allowlist** ("Approve for this session for THIS path"). The flow:
   - diff callback computes `absolute_target = str(Path(path).resolve())`.
   - If `absolute_target in SessionState.outside_root_allowlist` -> auto-approve (no modal).
   - Else -> raise `kind="outside_root"` approval with three buttons: Deny / Approve once / Approve for this session for THIS path.
   - "Approve for this session" adds `absolute_target` to `SessionState.outside_root_allowlist`; future writes to that exact path skip the modal until the run ends.
   - The allowlist is per-run (new run = fresh allowlist); the wording "for this session" is honest because each run gets its own `SessionState`.
3. **Open in Explorer scope** - user picked **any path under `effective_cwd`**. Reuses the existing `/api/files` whitelist helper. `full_access` writes are exempt (with an audit marker for traceability).

These three choices are no longer open questions.

---

---

## Companion document

`PHASED-PLAN.md` (same folder) - the implementation plan for F1-F4, structured into four phases (1-4) plus a tiny Phase 0. Follows the same conventions as the original `docs/reviews/2026-08-26-full-app-review/REMEDIATION-PLAN.md`.