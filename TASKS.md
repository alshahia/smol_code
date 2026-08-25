# smolcode - cross-session task tracker

**Date:** 2026-08-25 (v1.9.x FE wire-up session)
**Purpose:** Track ongoing + deferred + blocked work across sessions. This
file is the canonical "where am I?" snapshot for the next session.
**Source of truth:** git log + decision docs (`docs/decisions/*.md`) +
this file. The three stay in sync; this file is the readable summary.

---

## 1. Current state (2026-08-25, end of session)

| Item | Status | Reference |
|---|---|---|
| HEAD | `bec3ce9` (v1.9.x FE wire-up) | `git log -1` |
| Branch | `main`, ahead of `origin/main` by 0 (pushed) | `git status -sb` |
| Pytest (BE) | **1044 PASS / 51 FAIL (51 pre-existing baseline)** | unchanged from Phase 3 |
| Vitest (FE) | **55 PASS / 0 FAIL** (33 Phase 3 + 22 v1.9.x) | `pnpm test` from `smolcode/web/` |
| pnpm build | **257.80 KB JS / 77.67 KB gzip** (under 400 KB target) | `pnpm build` |
| Playwright e2e | **2 PASS / 0 FAIL / 1 SKIP** (backend-tolerant) | `pnpm test:e2e` (vite on :5173; no BE assumed) |
| Ruff check | 0 errors | `ruff check src tests` |
| Coverage | 82.33% (>=80% gate PASS) | pytest-cov |
| Working tree | clean (after this update + commit) | `git status` |

**Note on BE failures:** the 51 pre-existing failures remain unchanged.
Stash-revert against `bc39774` confirmed they pre-date v1.8 work; decision
0026 candidate consolidates the MCP-on-Windows + pyproject/uv.lock +
config.py:67 format debt. None of the v1.9.x work touched BE.

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

All eight commits are PUSHED to `https://github.com/alshahia/smol_code`.

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

---

## 4. DEFERRED (tracked across sessions, AFTER v1.9.x FE wire-up)

| Item | Origin | Effort | Priority |
|---|---|---|---|
| Drag-and-drop queue reorder | Phase 2 sec 6.4 / decision 0025 sec 8 | 1d | v1.9.x |
| Per-provider usage caps ("stop at $1") | Phase 3 sec 8 / decision 0025 sec 10.5 | 2-3d | v1.9.x |
| Per-subagent cost aggregation (currently shows tier/duration only) | Phase 3 followup #3 | 0.5d | v1.9.x |
| Full Playwright e2e suite (submit task + wait for done + dashboard + retry + export) | Phase 3 followup #4 | 1d | v1.9.x |
| Prompt library | decision 0025 sec 8 | 2d | v1.9.x |
| Cross-project session search | Phase 1 Known limitations | 1d | low |
| Auto-migrate orphaned sessions on project rename | Phase 1 Known limitations | 0.5d | low |
| Full Monaco editor | decision 0025 sec 4 | 5+d | v2.x (different product) |
| IPv6 iptables enforcement | decision 0021 sec X | 1d | v1.9.x |
| Server-side auto-approve OFF endpoint (FE-6 partial) | v1.9.x FE-6 limitation | 0.5d | low |
| Multi-user real-time collab | decision 0025 sec 4 | n/a | out of scope |
| Voice input | decision 0025 sec 4 | n/a | out of scope |
| Dark mode | decision 0025 sec 4 | 2d | when CSS variables land |
| Plugin/extension API | decision 0025 sec 4 | n/a | wait for 3rd-party interest |
| iptables for restricted tier | decision 0021 sec X | 1d | v1.9.x (defense-in-depth) |

---

## 5. BLOCKED (waiting on external or internal decision)

| Item | Blocker | Notes |
|---|---|---|
| **51 pre-existing BE failures** (MCP-on-Windows + litellm/smolagents version drift + test_web_server + test_checkpoint + config.py:67 format) | Recommendation: create **decision 0026** | Pre-existing per stash-revert against `445fa85`. Never caused by any committed v1.8/v1.9.x work. Likely sync JSON-RPC client pipes close early on Windows (MCP). |
| **pyproject.toml + uv.lock dirty state** | Recommendation: include in decision 0026 | Pre-existing dirty diff: `smolagents[litellm,docker,mcp]` -> `smolagents[all]` + removal of `[tool.uv.sources]` editable path. NOT committed. |
| **Server-side auto-approve OFF endpoint** (FE-6 v1.9.x limitation) | Future followup | The Disable button in the AutoApproveBanner clears the client-side flag; the underlying `sess.auto_approve_destructive=True` continues to auto-approve server-side until the run ends. A new `POST /api/runs/{id}/auto-approve:off` endpoint would close the loop. |
| **No git push to `origin/main`** | RESOLVED 2026-08-24 (user fixed GitHub credential) | All eight recent commits visible on `origin/main` via `git ls-remote`. |

---

## 6. Decision log index (pointers)

| Decision | Status | Title |
|---|---|---|
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
- **Python:** 3.10+. `make test` works on Windows; 51 pre-existing MCP/litellm/smolagents failures are unrelated.
- **GitHub:** remote is `https://github.com/alshahia/smol_code.git`. Git config user is `Ahmad Mahmoud <ahmad2002bc@gmail.com>`. Push from this session works (credential fixed 2026-08-24).
- **Vite binds to `localhost` not `127.0.0.1`** on this host; Playwright config uses `http://localhost:5173` (fixed in v1.9.x commit `bec3ce9`).
- **Harness auto-stash:** every ~5 min the harness creates an empty checkpoint stash (`smolcode-checkpoint-...`). They are EMPTY but persist in `stash list`. Drop them with `git stash drop`. Files that get auto-stashed can be lost across commands - pop + verify before committing.
- **`make test`:** in this repo the wrapper is `Makefile` + `make test`. Pytest addopts include `--cov` for the >=80% coverage gate.
- **ruff:** `ruff check src` is the lightweight gate; `make quality` does check + format-check. `ruff format` is auto-applied.
- **Frontend:** `pnpm --dir smolcode/web` for all package.json scripts. Vite on `localhost:5173`. Vitest + Testing Library + axe-core + Playwright ALL INSTALLED (v1.8 Phase 3 PREWORK + v1.9.x smoke).
- **Chromium already installed** in `$env:LOCALAPPDATA\ms-playwright\chromium-*`. Playwright `pnpm test:e2e` reuses it via `reuseExistingServer: true` (vite must be running).

---

## 8. Next-session entrypoint

If this file is the only thing the next session reads, do this:

1. `git log --oneline -10` - confirm HEAD is `bec3ce9` (or later).
2. `git status -sb` - confirm clean + pushed.
3. **Recommended: create `decision 0026`** to fix the 51 pre-existing BE failures (MCP-on-Windows + pyproject/uv.lock + config.py:67 format). The v1.8 + v1.9.x deliverables are clean.
4. **Or: work on remaining DEFERRED items** in §4. Recommended priority order:
   - Per-subagent cost aggregation (0.5d, small)
   - Server-side auto-approve OFF endpoint (0.5d, small)
   - Full Playwright e2e suite (1d, builds on existing smoke)
   - Drag-and-drop queue reorder (1d)
   - Per-provider usage caps (2-3d)
   - IPv6 iptables enforcement (1d, decision 0021)
5. **Or: open v2.0** scope planning (Monaco editor, multi-project workspaces, etc.) once v1.9.x followups are triaged.

---

## 9. Open questions for the user (if any)

- **None blocking.** All v1.8 + v1.9.x Phase 1 decisions are answered.
- **Optional:** would you like to tackle decision 0026 (MCP-on-Windows + pyproject/uv.lock + config.py:67 format) next? My recommendation: yes, since it cleans up the long-running 51-fail noise from the test baseline.
- **Optional:** which v1.9.x followup should pull-in next? My recommendation: server-side auto-approve OFF endpoint (small, completes FE-6) + per-subagent cost (small, completes the CostBadge followup chain).