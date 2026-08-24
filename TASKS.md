# smolcode - cross-session task tracker

**Date:** 2026-08-24
**Purpose:** Track ongoing + deferred + blocked work across sessions. This
file is the canonical "where am I?" snapshot for the next session.
**Source of truth:** git log + decision docs (`docs/decisions/*.md`) +
this file. The three stay in sync; this file is the readable summary.

---

## 1. Current state (2026-08-24, end of session)

| Item | Status | Reference |
|---|---|---|
| HEAD | `2f90b50` (Phase 2) | `git log -1` |
| Branch | `main`, ahead of `origin/main` by 0 (pushed) | `git status -sb` |
| Pytest | 1026 PASS / 16 FAIL (16 pre-existing baseline) | `make test` |
| Coverage | 82.33% (>=80% gate PASS) | pytest-cov |
| Ruff check | 0 errors | `ruff check src tests` |
| pnpm build | 248 KB JS / 75 KB gzip | `pnpm build` |
| Working tree | clean (after this update + commit) | `git status` |

---

## 2. Recently completed (last 3 sessions)

| Commit | Date | Theme | LOC |
|---|---|---|---|
| `445fa85` | 2026-08-22 | Initial commit: smolcode v1.7.1.3 + 24 decision docs | - |
| `88a20e4` | 2026-08-23 | v1.8 Phase 0: sub-agent events + token dashboard + countdown | +2099 |
| `7b33f1d` | 2026-08-24 | v1.8 Phase 1: sessions + projects | +1853 |
| `2f90b50` | 2026-08-24 | v1.8 Phase 2: pause/queue + file previews + file mentions | +2750 |
| (pending) | 2026-08-24 | Memory + plan updates (this session) + Phase 3 plan doc | +~1000 |

All four code commits are PUSHED to `https://github.com/alshahia/smol_code`.

---

## 3. IN PROGRESS - Phase 3 (Dashboard + a11y + power features)

**Owner:** next session (this session continues).
**Source:** `docs/decisions/0025-web-ui-ux-review-and-roadmap.md` sec 6.5 + sec 15 + `docs/decisions/v1.8-phase3-plan.md`.
**Acceptance gate:** sec 13.4 (8 checkboxes; 7 required to PASS before commit).

### 3.1 PREWORK - Vitest + Testing Library + axe-core + Playwright infra

| # | File | Status | Notes |
|---|---|---|---|
| PW-1 | `smolcode/web/package.json` devDeps | TODO | `vitest ^2`, `@testing-library/react ^16`, `@testing-library/jest-dom ^6`, `@testing-library/user-event ^14`, `jsdom ^25`, `@axe-core/react ^4`, `@playwright/test ^1.48` |
| PW-2 | `smolcode/web/vitest.config.ts` (NEW) | TODO | jsdom env + jest-dom setup + axe-core scan |
| PW-3 | `smolcode/web/src/__tests__/setup.ts` (NEW) | TODO | jest-dom matchers + axe-core dev |
| PW-4 | `smolcode/web/src/main.tsx` | TODO | mount axe-core dev (gated on `import.meta.env.DEV`) |
| PW-5 | `smolcode/web/playwright.config.ts` (NEW) | TODO | smoke config (loopback only) |
| PW-6 | `smolcode/web/e2e/smoke.spec.ts` (NEW) | TODO | open app + submit a task |

### 3.2 Backend (~270 LOC across 7 files)

| # | File | LOC | Status |
|---|---|---|---|
| BE-1 | `smolcode/src/smolcode/web/api.py` (4 new endpoints: /retry, /rerun, /export, /dashboard) | +60 | TODO |
| BE-2 | `smolcode/src/smolcode/web/schemas.py` (dashboard + cost + cache-hit fields) | +40 | TODO |
| BE-3 | `smolcode/src/smolcode/web/runs.py` (Run.retry_count + retry/rerun methods) | +30 | TODO |
| BE-4 | `smolcode/src/smolcode/web/agent_runner.py` (export_event_log + retry logic) | +10 | TODO |
| BE-5 | `smolcode/src/smolcode/model_catalog.py` (per-provider cost rates) | +30 | TODO |
| BE-6 | `smolcode/src/smolcode/config.py` (Settings.cost_rates env loader, Q5) | +20 | TODO |
| BE-7 | `smolcode/src/smolcode/web/dashboard.py` (NEW, compute_dashboard aggregator) | +80 | TODO |

### 3.3 Frontend (~585 LOC across 11 files)

| # | File | LOC | Status |
|---|---|---|---|
| FE-1 | `smolcode/web/src/components/Dashboard.tsx` (NEW) | +200 | TODO |
| FE-2 | `smolcode/web/src/components/CostBadge.tsx` (NEW) | +60 | TODO |
| FE-3 | `smolcode/web/src/components/SubAgentList.tsx` (NEW; renders `subagent_history`) | +50 | TODO |
| FE-4 | `smolcode/web/src/lib/keyboard.ts` (NEW; global shortcut router) | +50 | TODO |
| FE-5 | `smolcode/web/src/components/RunHistory.tsx` (extended search filter) | +25 | TODO |
| FE-6 | `smolcode/web/src/components/ApprovalModal.tsx` (auto-approve banner + revoke) | +40 | TODO |
| FE-7 | `smolcode/web/src/components/EventStream.tsx` (retry/rerun/export buttons) | +15 | TODO |
| FE-8 | `smolcode/web/src/App.tsx` (Dashboard tab + keyboard mount) | +15 | TODO |
| FE-9 | `smolcode/web/src/main.tsx` (keyboard mount + axe-core dev) | +10 | TODO |
| FE-10 | `smolcode/web/src/api.ts` (types + helpers for dashboard/cost/retry/rerun/export) | +80 | TODO |
| FE-11 | `smolcode/web/src/components/Inspector.tsx` (embeds SubAgentList) | +10 | TODO |

### 3.4 Tests (~920 LOC across 4 test files)

| # | File | Tests | Status |
|---|---|---|---|
| T-1 | `smolcode/src/smolcode/tests/test_dashboard.py` (NEW; TestDashboardAggregator + TestCostProjection) | ~+200 LOC | TODO |
| T-2 | `smolcode/src/smolcode/tests/test_cost.py` (NEW; TestCostRates) | ~+120 LOC | TODO |
| T-3 | `smolcode/src/smolcode/tests/test_retry_rerun_export.py` (NEW; TestRetry + TestRerun + TestExport) | ~+200 LOC | TODO |
| T-4 | `smolcode/web/src/__tests__/` (NEW; Vitest: Dashboard, CostBadge, SubAgentList, keyboard router; axe-core scan) | ~+400 LOC | TODO |

### 3.5 Phase 3 validation gates (all must PASS before commit)

- [ ] `ruff check src tests` PASS (0 errors)
- [ ] `ruff format --check src tests` PASS
- [ ] `pytest src/smolcode/tests` PASS (~30 new tests added)
- [ ] Coverage >=80% on the new BE code
- [ ] `pnpm --dir smolcode/web build` PASS (bundle <=400 KB JS / gzip)
- [ ] `pnpm --dir smolcode/web test` (Vitest) PASS; >=70% line coverage on new components
- [ ] `pnpm --dir smolcode/web test:a11y` (axe-core) PASS; zero serious/critical violations
- [ ] `pnpm --dir smolcode/web test:e2e` (Playwright) PASS; smoke flow
- [ ] `git push origin main` succeeds

---

## 4. DEFERRED (tracked across sessions)

| Item | Origin | Effort | Priority |
|---|---|---|---|
| Drag-and-drop queue reorder | Phase 2 sec 6.4 / decision 0025 sec 8 | 1d | v1.9.x |
| Per-provider usage caps ("stop at $1") | Phase 3 sec 8 / decision 0025 sec 10.5 | 2-3d | v1.9.x (after cost projection lands) |
| Prompt library | decision 0025 sec 8 | 2d | v1.9.x |
| Cross-project session search | Phase 1 Known limitations | 1d | low |
| Auto-migrate orphaned sessions on project rename | Phase 1 Known limitations | 0.5d | low |
| Full Monaco editor | decision 0025 sec 4 | 5+d | v2.x (different product) |
| IPv6 iptables enforcement | decision 0021 sec X | 1d | v1.9.x |
| Multi-user real-time collab | decision 0025 sec 4 | n/a | out of scope |
| Voice input | decision 0025 sec 4 | n/a | out of scope |
| Dark mode | decision 0025 sec 4 | 2d | when CSS variables land |
| Plugin/extension API | decision 0025 sec 4 | n/a | wait for 3rd-party interest |
| iptables for restricted tier | decision 0021 sec X | 1d | v1.9.x (defense-in-depth) |

---

## 5. BLOCKED (waiting on external or internal decision)

| Item | Blocker | Notes |
|---|---|---|
| **16 MCP-on-Windows test failures** | Recommendation: create **decision 0026** alongside the pyproject/uv.lock flip | Phase 0 sec 14.8 #1; carried across all phases; never the cause of any committed change. Stash-revert against `445fa85` confirms pre-existing. Likely sync JSON-RPC client pipes get closed prematurely on Windows. |
| **pyproject.toml + uv.lock dirty state** | Recommendation: create **decision 0026** | Pre-existing dirty diff: `smolagents[litellm,docker,mcp]` -> `smolagents[all]` + removal of `[tool.uv.sources]` editable path. NOT committed. Decision 0026 should consolidate both items. |
| **config.py:67 ruff format pre-existing diff** | Recommendation: include in decision 0026 | Pre-existing format debt (predates Phase 0). NOT in any phase commit. |
| **Live e2e browser smoke** (Phases 0/1/2 gates 5-10) | Phase 3 PREWORK installs Playwright | Once Playwright is in, all deferred e2e gates can be exercised. Until then, logic is covered by unit tests. |
| **No git push to `origin/main`** in older sessions | RESOLVED 2026-08-24 (user fixed GitHub credential) | All Phase 0/1/2 commits now visible on `origin/main` via `git ls-remote`. |

---

## 6. Decision log index (pointers)

| Decision | Status | Title |
|---|---|---|
| 0025 | phase-3-in-progress | Web UI/UX review + roadmap to v1.8 |
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
| v1.8-phase3-plan.md | pending | Phase 3 detailed plan (mirrors sec 14.1-sec 14.5) |

---

## 7. Environment quirks (worth remembering)

- **Working dir:** `E:\python_projects\smol_code` on Windows. POSIX commands via `pwsh -Command` (PowerShell Core).
- **Python:** 3.10+. `make test` works on Windows; some MCP tests fail because Windows pipes close early on sync JSON-RPC (pre-existing, baseline).
- **GitHub:** remote is `https://github.com/alshahia/smol_code.git`. Git config user is `Ahmad Mahmoud <ahmad2002bc@gmail.com>`. Push from this session now works (credential fixed 2026-08-24).
- **Harness auto-stash:** every ~5 min the harness creates an empty checkpoint stash (`smolcode-checkpoint-...`). They are EMPTY but persist in `stash list`. Drop them with `git stash drop`. Files that get auto-stashed can be lost across commands - pop + verify before committing.
- **`make test`:** in this repo the wrapper is `Makefile` + `make test`. Pytest addopts include `--cov` for the >=80% coverage gate. Addopts also enforce verbose + show durations.
- **ruff:** `ruff check src` is the lightweight gate; `make quality` does check + format-check. `ruff format` is auto-applied.
- **Frontend:** `pnpm --dir smolcode/web` for all package.json scripts. `pnpm build` (no watch). Vitest + Testing Library NOT YET INSTALLED - Phase 3 PREWORK.

---

## 8. Next-session entrypoint

If this file is the only thing the next session reads, do this:

1. `git log --oneline -10` - confirm HEAD is `2f90b50` (or later).
2. `git status -sb` - confirm clean + pushed.
3. Read `docs/decisions/v1.8-phase3-plan.md` + `docs/decisions/0025-web-ui-ux-review-and-roadmap.md` sec 15 - this is Phase 3.
4. Start with sec 3.1 (PW-1 to PW-6: Vitest + Testing Library + axe-core + Playwright infra). Foundation for all subsequent FE work.
5. Then sec 3.2 BE tasks (BE-1 through BE-7). TDD: write test first, see it fail, implement, see it pass.
6. Then sec 3.3 FE tasks (FE-1 through FE-11). Vitest for each new component.
7. Run sec 3.5 validation gates. Fix until all PASS.
8. Commit + push to `origin/main`.
9. Update this file: mark sec 3 items COMPLETED, move Phase 3 into sec 2 (recently completed), add Phase 4 / v1.9 followups if any.
10. Update `0025` sec 12 history (status flip from `phase-3-in-progress` to `phase-3-shipped`) + `roadmap.md` status + `README.md` banner.

---

## 9. Open questions for the user (if any)

- **None blocking Phase 3.** All Phase 3 decisions (Q1-Q5) are answered.
- **Optional:** would you like `decision 0026` (MCP-on-Windows + pyproject/uv.lock + config.py format) before, during, or after Phase 3? My recommendation: AFTER Phase 3 ships - keeps Phase 3 diff clean.
- **Optional:** are there any of the DEFERRED items (drag-drop reorder, usage caps, prompt library) that should pull-in to v1.9.x? My recommendation: ship Phase 3 first, then re-prioritize.
