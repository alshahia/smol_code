# smolcode — Repair-vs-Rewrite Assessment (2026-10-24)

**Date:** 2026-10-24 · **Repo:** `E:/python_projects/smol_code` @ `c79705b` (branch `fix/review-remediation`, clean tree, 45 commits ahead of `main`, **no upstream configured**)
**Method:** Lead re-verification of the 2026-09-24 review's remediated state on the current host, plus two independent read-only reviewer passes (frontend build/test evidence; Python source coherence + security-claim spot-check). Measurements below were run on this host on 2026-10-24. **No source files were modified during the assessment.**
**Status:** active
**Question:** *Is the project repairable in place, or does it need a fresh start for the same idea?*

Companion documents: `docs/reviews/2026-09-24-full-app-review/REVIEW-REPORT.md` (the review this assessment re-verifies against) and `REMEDIATION-PLAN.md` (Phases 3–9; this assessment adds Step 0 and keeps Phases 7–9 as the remaining work).

---

## Verdict

**REPAIR — not a rewrite.** The project is a working, well-architected single-developer tool whose security-critical controls are real and tested. The remaining defects are localized, already catalogued, and sized at roughly **6–10 person-days** for the planned phases plus **Step 0** below. A rewrite would discard ~15.3k LOC of Python source, ~16.5k LOC of tests (test:source ≈ 1.17), ~8.6k LOC of TypeScript, 41 ADRs, and the previously-fixed C1/C2/H1-class security work — while re-earning none of it.

The failure trend is **converging**: the 2026-09-24 review's root cause ("tests mock below the seam") was addressed in Phases 3–5 (strict TS, a CI build gate, conftest isolation, endpoint integration tests), and the suite grew 1,332 → 1,497 while going green. Today's source audit found only thin residue of that pattern, no stubs, and no abandoned abstractions.

---

## Validation results (measured on this host, 2026-10-24)

| Check | Command | Result |
|---|---|---|
| Python suite | `.venv/Scripts/pytest src/smolcode/tests -q` | **PASS with one flake** — 1484 passed, 17 skipped, 1 failed, 8 m 25 s. Failure: `test_web_runs_api.py::TestRunsSSE::test_events_stream_emits_run_started_and_ended` (missing `event: run.ended` under full-suite load). Isolated reruns: **5/5 pass** (10–21 s each) — a timing-sensitive test, tracked as A7. |
| Python lint/format | `ruff check src scripts` + `ruff format --check src scripts` | **PASS** — 0 errors; 135 files already formatted |
| Wheel build + package data | `uv build --wheel` + zip inspection | **PASS** — 143 entries; `smolcode/docker/{restricted,elevated,full_access}.Dockerfile` + `iptables-init.sh` present. The 2026-09-24 R1 blocker is genuinely fixed. |
| CLI surface | `--version`, `--print-config`, `--smoke` | **PASS** — exit 0; executor=docker, provider=opencode-go, tiers resolve |
| Web fail-closed boot | `python -m smolcode web` with daemon down | **PASS by refusal** — exits rather than degrading to an unsandboxed run |
| Frontend typecheck | `pnpm typecheck` (`tsc -b`, `strict: true`) | **PASS** — 0 diagnostics (injected `TS2322` control failed correctly) |
| Frontend lint/unit/build | `pnpm lint`, `pnpm test`, `pnpm build` | **PASS** — 0 warnings/0 errors; 139/139 vitest; 53 modules, 278.42 kB JS (83.29 kB gzip) |
| Fresh-clone frontend install | `pnpm install --frozen-lockfile` in a clean copy **without** the gitignored workspace file | **FAIL** — `ERR_PNPM_IGNORED_BUILDS: esbuild`, exit 1 (A2) |
| e2e smoke (chromium) | `pnpm test:e2e smoke` | **PASS** — 2 passed, 1 skipped (needs live backend) |
| Docker-marked tests | `pytest -m docker` | **SKIPPED** — Docker Desktop installed but service stopped; daemon unreachable |
| Live LLM end-to-end | — | **SKIPPED** — no provider key in env or `.env` |
| CI | — | **NOT RUN** — branch has no upstream, so no CI has ever executed on these 45 commits |

Host: Windows 11, Python 3.13.1 venv (canonical CI is 3.12), Node 24.18.0, pnpm 11.28.5, Docker CLI 28.3.2 (daemon down), uv 0.11.22.

---

## Findings

Severity is relative to "can a user rely on this project".

### A1 — 45 remediation commits are unpushed (critical, operational)

`fix/review-remediation` is 45 commits ahead of `main` and has **no upstream** (`git rev-parse --abbrev-ref @{u}` → *fatal: no upstream configured*). Every fix in Phases 3–6 exists on one disk only. CI has consequently never seen them, and the "CI green" claims in the tracker are untested.

### A2 — Fresh-clone frontend install is still broken (high, release blocker)

`smolcode/web/pnpm-workspace.yaml` states "It is committed so a fresh clone installs cleanly", but `.gitignore:107` (`**/pnpm-workspace.yaml`) excludes it, so **it is untracked**. Reproduced: copying `web/` without that file → `ERR_PNPM_IGNORED_BUILDS: Ignored build scripts: esbuild@0.21.5`, exit 1. This is exactly the R2c defect Phase 3 recorded as fixed; the fix landed on disk but not in git.

### A3 — Destructive approval is inert under the default Docker executor (high, capability gap)

Tools are built at `cli.py:370`, but the session (and `--auto-approve-destructive`) is installed at `cli.py:471`. `tools/__init__.py:96` therefore binds `destructive_policy="deny"` unconditionally. Under Docker the tool body runs in-container, where the inlined gate can only consult that bound policy (`tools/shell.py:222`, `tools/git.py:512`), so:

- the elevated tier **cannot push / perform destructive actions** in the default executor;
- "approve for rest of run" can never reach the container, even though the web endpoint flips the session flag.

Fail-closed and documented as ADR 0041 limitation #2, but it undercuts the elevated tier's stated purpose. A host-side approval broker is unbuilt.

### A4 — R7 is open and unassigned (high, default web path)

`web/server.py:109-123` calls `ensure_tier_images` but never `ensure_internal_network()`; only the CLI does (`cli.py:287-289`). On a fresh Docker host, restricted web runs fail with `network smolcode-internal not found`. R7 appears in `TASKS.md:176` as "newly surfaced" but is absent from every remediation phase.

### A5 — The core sandbox path is unverified on this host (high, validation gap)

Docker daemon down → tier-image contract tests and container-gate tests are skipped. `full_access` remains unbuildable (upstream HashiCorp apt 404). No provider key → no live end-to-end run. The sandbox guarantees are code- and unit-test-verified, not executed end to end on this machine.

### A6 — Documentation drift (medium; Phase 9, unstarted)

`README.md` status block is dated 2026-08-25 and asserts shipped state; `docs/environment.md` is dated 2026-06-28 and self-describes as the pre-build planning phase; 12 stale `smol_clone_2` path references remain; `TASKS.md` `0b's phase table still says Phase 5 "pending"; `docker/restricted.Dockerfile:10-11` claims the import allowlist is enforced by `LocalPythonExecutor` in-container (it is a local-executor feature — under Docker the image is the boundary).

### A7 — Hygiene / small correctness items (low–medium)

- Server mounts `web/dist` whenever it exists with no freshness gate (`web/server.py:137-139`); the bundle at HEAD was ~8 h stale.
- `tsc -b` can never be up-to-date (`noEmit: true` + `tsBuildInfoFile`), so every run re-checks (~11 s) and incremental caching is defeated.
- The SSE endpoint test is load-sensitive (the flake above).
- No root `README.md` / `LICENSE`; `pyproject.toml` has no license/authors/readme/URLs/classifiers (Phase 8 item 6).
- Three localized import cycles; ~110 duplicated lines between the two delegation tools; `_now_iso` copied 4×; four dead symbols. Maintainability debt, not blockers.
- `web/README.md` is still the stock Vite template.

### A8 — Planned work still open (not defects)

Phases 7 (web/session robustness, 2–3 d), 8 (ops/release, 2–3 d), 9 (docs, 1.5–2 d), plus Phase 6 leftovers: a docker-marked real in-container `CodeAgent` tool-call test; the MCP host-side proxy (option C); `full_access` unblock when upstream returns. All are scoped in the 2026-09-24 plan.

---

## What is genuinely good (verified)

| Area | Evidence |
|---|---|
| Fail-closed boot | CLI exit 6 and web refusal on image/network failure; loopback-only bind |
| Trust tiers | Per-tier images, mounts, network posture, command/import allowlists; restricted uploads mounted read-only in-container |
| Destructive gate | Two-path gate, drift-pinned by `test_inlined_gate_phase6.py`; restricted always denies |
| Audit integrity | SHA-256 hash chain with tail continuation, verification, rotation, secret redaction |
| MCP boundary | Docker executor + MCP configured refuses to start without `--allow-unsandboxed-mcp`; explicit default-deny tool allowlist; no env inheritance |
| Test culture | 1,484 passing Python tests, 139 vitest, 168-playwright suite, 41 ADRs, zero TODO/FIXME/HACK, ruff clean |
| Buildability | Wheel carries tier build context; frontend compiles with `strict`; fresh-clone install works **once A2 is fixed** |

---

## Why repair, not rewrite

1. **Nothing structural is wrong.** The core (`Run`/`RunManager`, tool builders, audit sink, tier config) is cohesive; the core does not import the web layer. The three cycles are local and cheap to break.
2. **The expensive assets are all reusable:** security model + proofs, 1.17 test ratio, 41 ADRs, working SPA.
3. **The remaining work is enumerated and bounded**, and the last review's root cause is already fixed.
4. **A rewrite would repeat known-fixed security bugs** and start from zero on trust and documentation.

---

## Recommended repair sequence (this is the work order)

**Step 0 — protect and de-risk (½ day)**
1. Push `fix/review-remediation` to `origin` (backup; lets CI run).
2. Track `smolcode/web/pnpm-workspace.yaml`; remove the conflicting `.gitignore` rule. Verify `pnpm install --frozen-lockfile` on a clean copy.
3. Add a `web/dist` freshness gate + test (warn/refuse rather than silently serve stale SPA).
4. Correct the highest-value doc claims (README status/paths, `environment.md`, `TASKS.md` phase table, restricted Dockerfile comment).
5. Fix the SSE flake (deterministic wait for `run.ended`).

**Phase 7 — web/session robustness (ADR 0042, 2–3 d):** run_id-guarded `set_session(None)`; `is_busy()` + insertion under one lock; exact-`run_id` auto-approve; `TrustedHostMiddleware`; stop resolves pending approval as denied; run TTL eviction + API-key zeroing. Also A4 (provision the internal network on web boot). (Graceful drain folded into Phase 8's lifespan work.)

**Phase 8 — ops/release (ADR 0043, 2–3 d):** host Dockerfile + run-book; graceful shutdown (stop/cleanup/close MCP/flush audit); real `/api/health` (docker/images/queue/active-run, 503 when docker unreachable); base-image digest pins + gosu checksum in the source hash; container resource limits; startup warning when no cost cap; package metadata (license choice still open); OS-aware Makefile.

**Phase 9 — docs alignment (ADR 0044, 1.5–2 d):** the A6 list, `.env.example` completeness, `ci.yml` header, superseded-report notes, and a CI grep guard against the stale strings.

**Phase 6 leftovers:** docker-marked real in-container tool-call test (written now, runs when a daemon is available); host-side approval broker design for A3; `full_access` retry when the upstream repo returns.

**Release evidence still missing (environment-dependent):** `pytest -m docker` + tier-image contract tests on a live daemon; one live hosted-provider e2e run with audit-chain verification; CI green on the pushed branch.

---

## Resolution log

| Finding | Status | Where |
|---|---|---|
| A1 unpushed commits | **resolved** — upstream set, branch pushed | `7ba1705`..`09646cd` on `origin/fix/review-remediation` |
| A2 pnpm-workspace untracked | **resolved** — tracked; fresh-clone `pnpm install --frozen-lockfile` verified from a `git archive` extract | `7ba1705` |
| A3 approval inert under Docker | open (design) — still fail-closed, documented; host-side broker not built | ADR 0041/0043, Phase 6 leftover |
| A4 R7 internal network | **resolved** — web boot provisions the bridge, fail-closed | `230e811` |
| A5 sandbox unverified | **blocked on environment** — daemon down, no provider key; docker-marked e2e test now exists and skips cleanly | `d7fa62d` |
| A6 documentation drift | **resolved** — current-state docs + docs-guard CI job | `09646cd` |
| A7 hygiene items | **mostly resolved** — SPA freshness gate, SSE flake root-caused/fixed, packaging metadata, OS-aware Makefile; root LICENSE still a decision | `230e811`, `3fc65ba`, `d117b88` |
| A8 planned phases | Phases 7–9 **shipped**; release evidence (live daemon + key, CI green) outstanding | this log |

**Batch validation (2026-10-24, after all commits):** full pytest **1567 passed /
18 skipped / 0 failed** (195 s; includes the SSE test that was flaky at baseline),
ruff check + format clean, frontend tsc 0 / oxlint 0 / 139 vitest / build ok,
wheel 153 entries. Baseline for comparison: 1484 passed / 17 skipped / 1 flaky.

**Remaining release evidence:** `pytest -m docker` + tier-image contract on a
live daemon; one live hosted-provider e2e with audit-chain verification; CI green
on the pushed branch. Note: `ci.yml` triggers only on `push: branches: [main]`
and `pull_request` (no `workflow_dispatch`), so pushing the feature branch did
not schedule a run — CI evidence requires opening a PR (or merging to `main`).
The last runs on `main` (2026-08-27..09-02) all failed, so that workflow also
needs a fresh green run before release.
