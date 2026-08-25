# smolcode - cross-session task tracker

**Date:** 2026-08-25 (decision 0028 session, post 0027 commit)
**Purpose:** Track ongoing + deferred + blocked work across sessions. This
file is the canonical "where am I?" snapshot for the next session.
**Source of truth:** git log + decision docs (`docs/decisions/*.md`) +
this file. The three stay in sync; this file is the readable summary.

---

## 1. Current state (2026-08-25, end of decision 0028 session)

| Item | Status | Reference |
|---|---|---|
| HEAD | `240b25d` (decision 0028 ship) | `git log -1` |
| Branch | `main`, ahead of `origin/main` by 0 (pushed) | `git status -sb` |
| Pytest (BE, Python 3.12) | **1159 PASS / 0 FAIL / 5 SKIP** (was 1044/51/0 → 1138/0/5 → 1144/0/5 → 1159/0/5) | `uv sync --locked --extra web && pytest src/smolcode/tests` |
| Vitest (FE) | **64 PASS / 0 FAIL** (33 Phase 3 + 22 v1.9.x + 9 decision 0028) | `pnpm test` from `smolcode/web/` |
| pnpm build | **258.01 KB JS / 77.72 KB gzip** (under 400 KB target; +0.21 / +0.05 KB vs decision 0027) | `pnpm build` |
| Playwright e2e | **2 PASS / 0 FAIL / 1 SKIP** (backend-tolerant) | `pnpm test:e2e` (vite on :5173; no BE assumed) |
| Ruff check | 0 errors | `ruff check src tests` |
| Ruff format | clean | `ruff format --check src` (101 files) |
| Coverage | 82.33% (>=80% gate PASS) | pytest-cov |
| uv.lock | `smolagents==1.26.0` from PyPI (was `1.27.0.dev0` from `../smolagents`) | `uv lock --check` |
| FastAPI pin | `>=0.115,<0.137` (regression boundary = 0.137.0) | `pyproject.toml` |
| Working tree | **decision 0028 in progress** (commit `240b25d` + TASKS.md update pending) | `git status` |
| Decision 0028 | applied (committed `240b25d`, TASKS.md update pending) | `docs/decisions/0028-per-subagent-cost-aggregation.md` |
| Decision 0027 | shipped (commits `ba64f2d` + `ee2fd3b`) | `docs/decisions/0027-server-side-auto-approve-off.md` |

**Note on BE failures:** the historical "51 pre-existing failures" baseline
is **resolved by decision 0026**. The 51 broke down as:

- 7 model-catalog failures caused by a real
  `ModelListResponse.models: list[dict]` schema mismatch — fixed in
  `smolcode/src/smolcode/web/schemas.py` (one-line).
- 1 FastAPI route-registration failure in `test_web_server.py` — fixed
  by pinning `fastapi>=0.115,<0.137` (regression introduced in 0.137.0).
- 2 checkpoint test failures caused by Git discovering the parent
  worktree via pytest's default `tmp_path` — fixed by using
  `tempfile.mkdtemp()` for the workspace.
- ~41 ruff-format drift failures cascading through `session.py`,
  `test_config.py`, `test_sessions.py`, `test_web_sessions_api.py`,
  `test_checkpoint.py` — fixed by `ruff format`.

Decision 0027 added **6 new BE tests** in `TestRunsAutoApprove` (1144 = 1138
+ 6). Zero FE test changes.

Decision 0028 adds **15 new BE tests** in `TestSubAgent*` (1159 = 1144
+ 15) and **9 new FE tests** in `SubAgentListCost.test.tsx` (64 = 55 + 9).
Bundle +0.21 KB / +0.05 KB gzip (negligible).

The remaining 5 SKIPs are `pytest.mark.docker` and
`pytest.mark.shellcheck` markers — deselected because Docker daemon +
`shellcheck` are absent in this environment. **This is expected**; the
tests exist for CI environments with the tools available.

**Note on BE failures:** the historical "51 pre-existing failures" baseline
is **resolved by decision 0026**. The 51 broke down as:

- 7 model-catalog failures caused by a real
  `ModelListResponse.models: list[dict]` schema mismatch — fixed in
  `smolcode/src/smolcode/web/schemas.py` (one-line).
- 1 FastAPI route-registration failure in `test_web_server.py` — fixed
  by pinning `fastapi>=0.115,<0.137` (regression introduced in 0.137.0).
- 2 checkpoint test failures caused by Git discovering the parent
  worktree via pytest's default `tmp_path` — fixed by using
  `tempfile.mkdtemp()` for the workspace.
- ~41 ruff-format drift failures cascading through `session.py`,
  `test_config.py`, `test_sessions.py`, `test_web_sessions_api.py`,
  `test_checkpoint.py` — fixed by `ruff format`.

The remaining 5 SKIPs are `pytest.mark.docker` and
`pytest.mark.shellcheck` markers — deselected because Docker daemon +
`shellcheck` are absent in this environment. **This is expected**; the
tests exist for CI environments with the tools available.

---

## 2. Recently completed (last 4 sessions)

| Commit | Date | Theme | LOC |
|---|---|---|---|
| `445fa85` | 2026-08-22 | Initial commit: smolcode v1.7.1.3 + 24 decision docs | - |
| `88a20e4` | 2026-08-23 | v1.8 Phase 0: sub-agent events + token dashboard + countdown | +2099 |
| `7b33f1d` | 2026-08-24 | v1.8 Phase 1: sessions + projects | +1853 |
| `2f90b50` | 2026-08-24 | v1.8 Phase 2: pause/queue + file previews + file mentions | +2750 |
| `bc39774` | 2026-08-24 | Memory + plan updates: Phase 1 ship report + Phase 3 plan doc | +1289 |
| `dcf38cf` | 2026-08-24 | v1.8 Phase 3: Dashboard + a11y + power features | +3388 |
| `509288f` | 2026-08-24 | v1.8 Phase 3 ship report + status flip to phase-3-shipped | +163/-15 |
| `bec3ce9` | 2026-08-25 | **v1.9.x FE wire-up**: RunHistory filters + AutoApproveBanner + RunActions + Dashboard modal + keyboard mount + axe-core dev + Playwright smoke (12 files, +750/-101) | +750 |
| `620e322` | 2026-08-25 | **decision 0026**: pin smolagents=1.26.0 + fastapi<0.137 + fix `ModelListResponse.models: list[str]` (4 files, +1108/-76) | +1108 |
| `9c1024a` | 2026-08-25 | **decision 0026 docs+cleanup**: ruff drift fixes + checkpoint test isolation + TASKS.md update (6 files, +38/-24) | +38 |
| `ba64f2d` | 2026-08-25 | **decision 0027**: server-side auto-approve OFF endpoint (10 files, +714/-7) | +714 |
| `ee2fd3b` | 2026-08-25 | **decision 0027 docs**: TASKS.md update for decision 0027 | - |
| `240b25d` | 2026-08-25 | **decision 0028**: per-sub-agent cost aggregation (8 files, +653/-37) — `<SubAgentList>` finally wired into Inspector + per-sub-agent `<CostBadge>` per row | +653 |

All twelve recent commits are PUSHED to `https://github.com/alshahia/smol_code`.

---

## 3. COMPLETED - v1.8 Phase 3 + v1.9.x FE wire-up

### 3.1 v1.8 Phase 3 (commit `dcf38cf` + ship docs `509288f`)

**Owner:** shipped.
**Status:** ALL DONE per `509288f` ship report + decision 0025 §13.4.
**Source:** `docs/decisions/0025-web-ui-ux-review-and-roadmap.md` §6.5 + §15 + `docs/decisions/v1.8-phase3-plan.md`.

Validation gates (all PASS at ship): 43 BE tests + 33 Vitest tests + axe-core + pnpm build 248 KB + ruff 0 errors + push.

### 3.2 v1.9.x FE wire-up (commit `bec3ce9`)

**Owner:** shipped on commit `bec3ce9` (2026-08-25).
**Source:** the 6 deferred items in `docs/decisions/v1.8-phase3-shipped.md` Followups (#2 + #4).

| Item | File(s) | Status |
|---|---|---|
| **FE-5** RunHistory tier + status filters | `components/RunHistory.tsx` + `__tests__/RunHistory.test.tsx` (9 tests) | DONE |
| **FE-6 / B10** Auto-approve banner + revoke | `components/AutoApproveBanner.tsx` (NEW) + `components/ApprovalModal.tsx` (`onAutoApproveToggle` prop) + `__tests__/AutoApproveBanner.test.tsx` (4 tests) + `__tests__/ApprovalModal.test.tsx` (5 tests) | DONE |
| **FE-7 / B4+B5+B7** RunActions (Retry/Re-run/Export) in stream header when terminal | `components/RunActions.tsx` (NEW) + App.tsx wire-up + `__tests__/RunActions.test.tsx` (4 tests) | DONE |
| **FE-8** Dashboard modal overlay + keyboard router mount in App | `App.tsx` (`installKeyboardRouter(...)` + Dashboard button + Dashboard modal) | DONE |
| **FE-9** axe-core dev mount in main | `main.tsx` (gated on `import.meta.env.DEV`) | DONE |
| **PW-4** Playwright e2e smoke against live Vite | `e2e/smoke.spec.ts` (3 tests, 2 pass + 1 skipped when no BE) + `playwright.config.ts` (localhost + 60s timeout) | DONE |

### 3.3 Validation gates (v1.9.x)

- [x] `pnpm test` PASS (55/55 vitest; 22 new)
- [x] `pnpm build` PASS (257.80 KB JS / 77.67 KB gzip; under 400 KB)
- [x] `pnpm exec playwright test` PASS (2/3 + 1 skipped, backend-tolerant)
- [x] `tsc -b && vite build` PASS (no TS errors)
- [x] `git push origin main` succeeds (commit `bec3ce9`)

### 3.4 Decision 0026 — Local env validation cleanup (commits `620e322` + `9c1024a`)

**Owner:** shipped 2026-08-25.
**Source:** `docs/decisions/0026-local-env-validation-cleanup.md`.
**Purpose:** make the local Python / frontend / Docker validation
environment reproducibly installable + diagnose the 51 pre-existing
backend test failures without weakening any security behavior.

Key fixes:

- `smolagents[litellm,docker,mcp]>=1.26.0,<1.27` from PyPI (was unresolvable
  `../smolagents` editable source).
- `fastapi>=0.115,<0.137` (route-registration regression starting in
  0.137.0).
- `ModelListResponse.models: list[str]` (was `list[dict]` — 7 model-catalog
  tests failing).
- `tempfile.mkdtemp()` for `test_checkpoint.py` workspace (2 checkpoint
  tests failing because pytest's default `tmp_path` was inside the repo
  so Git discovered the parent worktree).
- ruff-format drift on 5 files.

Result: **1138 PASS / 0 FAIL / 5 SKIP** (was 1044/51/0). Both commits
pushed to `origin/main`.

### 3.5 Decision 0027 — Server-side auto-approve OFF endpoint (shipped)

**Owner:** shipped 2026-08-25 (commits `ba64f2d` + `ee2fd3b`).
**Source:** `docs/decisions/0027-server-side-auto-approve-off.md`.
**Purpose:** close the FE-6 partial gap. The `<AutoApproveBanner>`
"Disable" button now reaches the BE via `POST /api/runs/{id}/auto-approve`
so the underlying `session.auto_approve_destructive` flag flips too.
Future destructive tool calls re-arm the ApprovalModal instead of being
silently auto-approved. The ApprovalModal "Approve + auto-approve"
button also reaches the BE so the web has CLI parity for the `a`/`o`
flow.

Key changes:

- `SessionState.run_id: str | None = None` + `set_auto_approve` /
  `get_auto_approve` helpers (atomic under `_session_lock`).
- `agent_runner.run_in_thread` passes `run_id=run.id` when installing
  the session.
- `RunManager.set_auto_approve(run_id, enabled)` delegate.
- `AutoApproveSetRequest` + `AutoApproveSetResponse` Pydantic models.
- `POST /api/runs/{run_id}/auto-approve` endpoint (404/409/422/200).
- `postAutoApprove()` in `web/src/api.ts` + `App.tsx` wires the FE
  toggle (both banner Disable and ApprovalModal auto-approve) to call it.
- 6 new BE tests in `TestRunsAutoApprove` (file:
  `src/smolcode/tests/test_web_runs_api.py`).

Result: **1144 PASS / 0 FAIL / 5 SKIP** (1138 baseline + 6 new). FE
55/55 unchanged. `pnpm build` 257.80 KB / 77.67 KB gzip (unchanged).
ruff 0 errors.

### 3.6 Decision 0028 — Per-sub-agent cost aggregation (committed, TASKS.md update pending)

**Owner:** applied 2026-08-25 (commit `240b25d`).
**Source:** `docs/decisions/0028-per-subagent-cost-aggregation.md`.
**Purpose:** close v1.9.x followup #3 — the `<SubAgentList>` (shipped
in decision 0025 §6.5 but never wired into the Inspector) now shows
per-sub-agent USD cost via `<CostBadge>`, and the full sub-agent
history finally appears in the Inspector.

Key changes:

- `Run.active_subagent_id: str | None = None` (new field) +
  `append_subagent` sets it + `close_subagent` clears it
  conditionally (preserves nested attribution).
- `Run.publish(EVT_STEP_ACTION, ...)` attributes tokens to the
  active sub-agent under the same `pending_lock` that increments
  outer totals. Outer `tokens_in` / `tokens_out` stay TOTAL
  (Dashboard cost math unchanged).
- `Run.summary_dict()` derives `cost_usd` per sub-agent at read
  time via `cost_for(provider, model, tokens_in, tokens_out,
  settings=None)` (default rates only for v1).
- `SubAgentSummary` Pydantic gains `specialist` (gap fix — was on
  the BE dataclass, missing from Pydantic), `tokens_in`,
  `tokens_out`, `cost_usd` (all additive).
- `<SubAgentList>` renders `<CostBadge>` per row + a "Sub-agents
  total" chip when sum > 0 + per-row token count column.
- `<Inspector>` imports `<SubAgentList>` and replaces the legacy
  single-sub-agent hint block (the live nested `<SubAgentBlock>`
  inside `<EventStream>` is unchanged — the `sub` accessor still
  drives it).
- 15 new BE tests in `TestSubAgent*` (attribution, wire shape,
  concurrency stress 8×100 publishes = 800 increments preserved
  exactly, dataclass defaults, EVT_SUBAGENT_*_STARTED/ENDED
  regression).
- 9 new FE tests in `SubAgentListCost.test.tsx` (per-row badge,
  undefined/0 cost fallback, token text, total chip visibility,
  axe-core a11y).
- `.gitignore`: catch `**/.pytest_tmp/`.

Result: **1159 PASS / 0 FAIL / 5 SKIP** (1144 + 15 new). FE 64/64
(was 55, +9 new). `pnpm build` 258.01 KB / 77.72 KB gzip (+0.21 /
+0.05 KB). ruff 0 errors. tsc 0 errors.

**Limitations documented in §6 of the decision doc:** default-rates
only (Settings.cost_rates plumbing deferred); no cache_hit
attribution (no per-event cache_hit counter exists today).

---

## 4. DEFERRED (tracked across sessions, AFTER v1.9.x FE wire-up)

| Item | Origin | Effort | Priority |
|---|---|---|---|
| Drag-and-drop queue reorder | Phase 2 sec 6.4 / decision 0025 sec 8 | 1d | v1.9.x |
| Per-provider usage caps ("stop at $1") | Phase 3 sec 8 / decision 0025 sec 10.5 | 2-3d | v1.9.x |
| ~~Per-subagent cost aggregation (currently shows tier/duration only)~~ DONE (decision 0028) | Phase 3 followup #3 | 0.5d | shipped |
| Full Playwright e2e suite (submit task + wait for done + dashboard + retry + export) | Phase 3 followup #4 | 1d | v1.9.x |
| Prompt library | decision 0025 sec 8 | 2d | v1.9.x |
| Cross-project session search | Phase 1 Known limitations | 1d | low |
| Auto-migrate orphaned sessions on project rename | Phase 1 Known limitations | 0.5d | low |
| Full Monaco editor | decision 0025 sec 4 | 5+d | v2.x (different product) |
| IPv6 iptables enforcement | decision 0021 sec X | 1d | v1.9.x |
| ~~Server-side auto-approve OFF endpoint (FE-6 partial)~~ DONE (decision 0027) | v1.9.x FE-6 limitation | 0.5d | shipped |
| Multi-user real-time collab | decision 0025 sec 4 | n/a | out of scope |
| Voice input | decision 0025 sec 4 | n/a | out of scope |
| Dark mode | decision 0025 sec 4 | 2d | when CSS variables land |
| Plugin/extension API | decision 0025 sec 4 | n/a | wait for 3rd-party interest |
| iptables for restricted tier | decision 0021 sec X | 1d | v1.9.x (defense-in-depth) |

---

## 5. BLOCKED (waiting on external or internal decision)

| Item | Blocker | Notes |
|---|---|---|
| **Docker daemon not reachable** (pipe `dockerDesktopLinuxEngine` missing in this env) | Docker Desktop not running | `pytest -m docker` deselected. Docker syntax + `iptables-init.sh` lint-checked by standalone CI; live execution requires a Docker-equipped runner. **NOT a code blocker** — smolcode's security model assumes a real Docker boundary; substituting a non-Docker executor would weaken it. |
| **`shellcheck` not on PATH** | shellcheck not installed | `pytest -m shellcheck` deselected. Same as above — runs in CI, not here. |
| **Decision 0028 TASKS.md update pending** | Sequential commit | Decision 0028 code+tests+doc landed in commit `240b25d`; this TASKS.md update is the second commit (matches 0026 + 0027 pattern). Validation already passed (1159 PASS / 0 FAIL / 5 SKIP, FE 64/64). |
| **No git push to `origin/main`** | RESOLVED 2026-08-24 (user fixed GitHub credential) | All ten recent commits visible on `origin/main` via `git ls-remote`. |

---

## 6. Decision log index (pointers)

| Decision | Status | Title |
|---|---|---|
| **0027** | **shipped (commits `ba64f2d` + `ee2fd3b`)** | **Server-side auto-approve OFF endpoint (closes FE-6 partial). `POST /api/runs/{id}/auto-approve {enabled: bool}` flips `session.auto_approve_destructive` atomically. FE `<AutoApproveBanner>` Disable + `<ApprovalModal>` auto-approve both reach the BE. 6 new BE tests; 1144 PASS / 0 FAIL / 5 SKIP.** |
| **0028** | **applied (committed `240b25d`, TASKS.md update pending)** | **Per-sub-agent cost aggregation (closes v1.9.x followup #3). `<SubAgentList>` finally wired into Inspector + per-row `<CostBadge>` + token counts + "Sub-agents total" chip. BE: `Run.active_subagent_id` + token attribution in `publish` + `cost_usd` derived in `summary_dict` via `cost_for`. Pydantic `SubAgentSummary` gains `specialist` (gap fix) + `tokens_in/out` + `cost_usd`. 15 new BE tests + 9 new FE tests; 1159 PASS / 0 FAIL / 5 SKIP.** |
| **0026** | **shipped (commits `620e322` + `9c1024a`)** | **Local Python/Frontend/Docker validation cleanup: `smolagents>=1.26.0,<1.27` PyPI pin, `fastapi>=0.115,<0.137` pin, `ModelListResponse.models: list[str]`, ruff drift fixes, `test_checkpoint.py` temp-isolation fix. 51 BE failures → 0 failures + 5 expected skips.** |
| 0025 | phase-3-shipped (FE wire-up complete via v1.9.x commit `bec3ce9`) | Web UI/UX review + roadmap to v1.8 (+ v1.9.x FE followups) |
| 0024 | active | Web UI: traceback capture + UTF-8 stdio |
| 0023 | active | Runtime sandbox-boundary guard (Layer A + Layer B) |
| 0022 | active | Run cleanup on exit |
| 0021 | active | Bugfix: sandbox-import error path |
| 0020 | active | M16: iptables enforcement for elevated tier |
| 0019 | active | M15: CLI extraction + UX polish |
| 0018 | active | M14: audit log operational hardening |
| 0017 | active | M14/M15/M16 roadmap |
| v1.8-phase0-shipped.md | active | Phase 0 ship report (commit `88a20e4`) |
| v1.8-phase1-shipped.md | active | Phase 1 ship report (commit `7b33f1d`) |
| v1.8-phase2-shipped.md | active | Phase 2 ship report (commit `2f90b50`) |
| v1.8-phase3-plan.md | active | Phase 3 detailed plan (mirrors sec 14.1-sec 14.5) |
| v1.8-phase3-shipped.md | active | Phase 3 ship report (commit `509288f`) |

---

## 7. Environment quirks (worth remembering)

- **Working dir:** `E:\python_projects\smol_code` on Windows. POSIX commands via `pwsh -Command` (PowerShell Core).
- **Python:** 3.10+. **Use 3.12** (the canonical validation path; 3.14 lacks compatible `mcp`/`pywin32` wheels on Windows).
- **GitHub:** remote is `https://github.com/alshahia/smol_code.git`. Git config user is `Ahmad Mahmoud <ahmad2002bc@gmail.com>`. Push from this session works (credential fixed 2026-08-24).
- **Vite binds to `localhost` not `127.0.0.1`** on this host; Playwright config uses `http://localhost:5173` (fixed in v1.9.x commit `bec3ce9`).
- **Harness auto-stash:** every ~5 min the harness creates an empty checkpoint stash (`smolcode-checkpoint-...`). They are EMPTY but persist in `stash list`. Drop them with `git stash drop`. Files that get auto-stashed can be lost across commands - pop + verify before committing.
- **`make test`:** in this repo the wrapper is `Makefile` + `make test`. Pytest addopts include `--cov` for the >=80% coverage gate.
- **ruff:** `ruff check src` is the lightweight gate; `make quality` does check + format-check. `ruff format` is auto-applied.
- **Frontend:** `pnpm --dir smolcode/web` for all package.json scripts. Vite on `localhost:5173`. Vitest + Testing Library + axe-core + Playwright ALL INSTALLED (v1.8 Phase 3 PREWORK + v1.9.x smoke).
- **Chromium already installed** in `$env:LOCALAPPDATA\ms-playwright\chromium-*`. Playwright `pnpm test:e2e` reuses it via `reuseExistingServer: true` (vite must be running).
- **Decision 0026 dependency pins (locked):** `smolagents==1.26.0` (PyPI), `fastapi==0.136.3` (last 0.136.x — see `docs/decisions/0026-local-env-validation-cleanup.md` §3.2 for the regression-boundary proof), `litellm==1.97.0`, `docker==7.2.0`, `mcp==2.0.0`, `mcpadapt==0.1.20`. `uv sync --locked --extra web` is reproducible from any clean checkout.
- **Decision 0027 BE additions:** `POST /api/runs/{id}/auto-approve` endpoint + `SessionState.run_id` field + `set_auto_approve` / `get_auto_approve` helpers. See `docs/decisions/0027-server-side-auto-approve-off.md` §3 for the design rationale + §7 for the file-by-file spec.
- **Decision 0028 additions:** `Run.active_subagent_id` (new field), per-sub-agent token attribution in `Run.publish`, `cost_usd` derivation in `Run.summary_dict`, `<SubAgentList>` wired into `<Inspector>`. See `docs/decisions/0028-per-subagent-cost-aggregation.md` §3 + §4 for the design rationale + file-by-file spec.

---

## 8. Next-session entrypoint

If this file is the only thing the next session reads, do this:

1. `git log --oneline -10` - confirm HEAD is `240b25d` (decision 0028 code+tests+doc) or later.
2. `git status -sb` - **expect only TASKS.md modified (decision 0028 docs commit pending)**.
3. **RECOMMENDED FIRST ACTION:** commit this TASKS.md update as `docs: TASKS.md update for decision 0028 - log 0027 ship + 0028 status`. Suggested split (matches 0026 + 0027 pattern): (a) code + tests + decision doc; (b) TASKS.md. Both already done — this is the second commit.
4. **Or: work on remaining DEFERRED items** in §4. Recommended priority order:
   - ~~Per-subagent cost aggregation~~ DONE (decision 0028, commit `240b25d`)
   - Full Playwright e2e suite (1d, builds on existing smoke)
   - Drag-and-drop queue reorder (1d)
   - Per-provider usage caps (2-3d)
   - IPv6 iptables enforcement (1d, decision 0021)
5. **Or: open v2.0** scope planning (Monaco editor, multi-project workspaces, etc.) once v1.9.x followups are triaged.

---

## 9. Open questions for the user (if any)

- **Decision 0028 commit granularity:** I committed as 2 commits (matching 0026 + 0027 pattern). If you'd prefer a single squashed commit, the rewrite is `git reset --soft 9c1024a && git commit --amend` + force-push. Just flag and I'll redo.
- **Next v1.9.x followup after 0028:** full Playwright e2e suite (1d), drag-and-drop queue reorder (1d), or per-provider usage caps (2-3d)? My recommendation: full Playwright next (1d, builds on the existing 3-test smoke).
