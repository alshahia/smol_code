# smolcode — Full Application Review #2 (Consolidated)

**Date:** 2026-09-24 · **Repo:** `E:\python_projects\smol_code` @ `3cebcde` (branch `fix/review-remediation`, clean tree, 2 commits ahead of `main`)
**Method:** One lead read-only review (environment, architecture, security, correctness, tests, build, packaging, docs) plus three independent parallel read-only reviewer passes (security / web+agent / production-delivery), all cross-checked for agreement with direct runtime probes on this host. **No source files were modified during review** (temporary probe artifacts were created outside the repo and removed).
**Status:** active
**Question:** *Is the app production-ready — can it be used, deliver its result, and achieve its goal?*

Companion documents (same folder): `REMEDIATION-PLAN.md` (phased fix plan).
Prior review lineage: `docs/reviews/2026-08-26-full-app-review/` (Phases 0–2 shipped), `docs/reviews/2026-08-27-web-ui-user-feedback/` (F1–F4 shipped), `docs/reviews/2026-08-27-architecture-vs-claude-md/REPORT.md`.

---

## Verdict

**NOT PRODUCTION READY.** It is a strong, well-architected single-developer local tool whose prior *Critical* security findings (C1, C2, H1) and audit-integrity findings (H5, H6) are genuinely remediated in code. But the remediation plan's Phases 3–7 were never started, and the review found that Phase 3's code was **partially landed in a broken state**: the React SPA does not compile, four web endpoints 500 or silently never fire, the wheel cannot build the tier images, and CI cannot see any of it.

It **can** deliver a result for one developer running from an editable checkout with Docker up — that path is wired correctly and fails closed. That is not the same as production-ready.

**Release-blocking summary (4 critical items, each independently verified):**

1. The wheel excludes `docker/*.Dockerfile` + `iptables-init.sh` → any non-editable install cannot build tier images (verified by installing the built wheel into a clean venv).
2. `pnpm build` fails with 8 TypeScript errors — the product surface does not compile.
3. Retry / rerun / export return HTTP 500 at runtime; the queue never drains; cost caps never fire; the dashboard always reports $0.
4. CI has no frontend job, no tier-image job, and no dependency/security scanning; 98 Python tests error at setup because test isolation defaults to the docker executor.

---

## Validation results (all run on this host, 2026-09-24)

| Check | Command | Result |
|---|---|---|
| Ruff lint | `ruff check src scripts` | **PASS** (0 errors) |
| Ruff format | `ruff format --check src scripts` | **PASS** (118 files) |
| Lockfile | `uv lock --check` | **PASS** (warning: `tool.uv.dev-dependencies` deprecated) |
| Full Python suite + coverage | `pytest src/smolcode/tests -m "not docker" -q --cov=smolcode --cov-fail-under=80` | **FAIL** — 12 failed, 1219 passed, 86 errors, 1 skipped, 12 deselected (exit 1, 742 s) |
| Same suite with `SMOLCODE_EXECUTOR=local` | env var (cleared by autouse conftest fixture) | **FAIL** — identical result (proves fixture, not environment, is the gap) |
| Security subset (reviewer) | gate/images/network/security/tools/uploads/mcp subset | 268 passed, 8 correctly deselected (one transient setup flake, not reproducible in 3 reruns) |
| Web API subset (reviewer) | web-related subset | 158 passed, 20 setup errors (all `test_web_api.py`, all Docker-boot) |
| Frontend lint | `pnpm lint` | **PASS** — 0 errors, 15 warnings (docs claim 4) |
| Frontend unit tests | `pnpm test` | **PASS** — 114/114 (mocks the API, so it masks the build break) |
| Frontend build | `pnpm build` (clean install) | **FAIL** — 8 TypeScript errors (exit 2) |
| Playwright e2e (3 browsers) | `pnpm test:e2e` | **FAIL** — 103 passed, 1 failed, 1 skipped (all against a mocked backend) |
| Wheel build + install | `uv build --wheel`; install into clean venv; `smolcode.images.source_hash('restricted')` | **FAIL** — `ImageBuildError: build input missing: .../site-packages/smolcode/docker/restricted.Dockerfile` |
| CLI `--version` / `--print-config` / `--help` | installed CLI | **PASS** — defaults: executor=docker, provider=opencode-go, model=deepseek-v4-flash, tier=restricted |
| CLI `--smoke --tier restricted "echo hi"` | stub model, local executor | **PASS** exit 0 — prints `[stub] hi`; writes nothing (stub only calls `final_answer`) |
| CLI real task without key | `smolcode --tier restricted "echo hi"` | exit 3 — `missing api key: ... OPENCODE_GO_APIKEY` (correct) |
| CLI real task, Docker daemon down | `smolcode --tier restricted "echo hi"` | exit 3 — `missing api key` (key checked before Docker) |
| `python -m smolcode.images ensure`, Docker down | | exit 1 with raw `DockerException` traceback (CLI boot wraps this to exit 6 — direct module call does not) |
| `smolcode web`, Docker daemon down | | exit 3 — `RuntimeError: sandbox images not available; refusing to start web server` (fail-closed, correct by design) |
| Secret-pattern scan (tracked files) | `sk-`/`ghp_`/`AKIA`/`AIza` | **PASS** — only test/doc fixtures; no real secrets; no `.env` present |
| Tracked-file hygiene | `git ls-files` | **PASS** — no `node_modules`, `__pycache__`, `.coverage`, `.pytest_tmp`, logs |
| Docker tier images / no-egress / in-container tool calls | `pytest -m docker` | **SKIPPED** — Docker daemon unreachable on this host (`dockerDesktopLinuxEngine` pipe missing) |
| Live LLM end-to-end run (hosted provider, Docker executor, artifact on disk) | | **SKIPPED** — no provider key; the only in-repo evidence is `README.md:180-183` (2026-08-24) which predates every remediation commit |
| `make test` / `make quality` | | **SKIPPED** — `make` is not installed on this Windows host; equivalents run directly via `.venv\Scripts\` |
| Frontend `pnpm install --frozen-lockfile` in the repo | | **FAIL** — pre-existing `node_modules` is a partial install (symlinks into a missing `.pnpm` store, no `.modules.yaml`). Reproduced cleanly in an isolated scratch copy, which then needed `pnpm-workspace.yaml` with `allowBuilds: { esbuild: true }` (the auto-generated file is gitignored, so a fresh clone on pnpm 10+ fails) |
| Dependency / security scanning | `pip-audit`, `npm audit`, CodeQL, Dependabot | **SKIPPED** — none exist in CI |

Host: Windows 11 Pro, AMD64, 47.6 GB RAM. Python 3.13.1 venv (uv 0.11.22; CI canonical is 3.12 — `uv python list` shows 3.12.13 downloadable, so 3.12 parity is re-validated in CI). smolagents 1.26.0, FastAPI 0.136.3, uvicorn 0.52.4, litellm 1.97.0, mcp 2.0.0, docker SDK 7.2.0. Node v24.18.0, pnpm 12.3.4. Docker CLI 28.3.2 present, daemon down. `make` absent.

---

## Executive summary

The 2026-08-26 review found that headline security controls existed in code and docs but were not wired into the running system. The 2026-08-26 → 2026-08-27 remediation (Phases 0–2) fixed that for C1, C2, H1, H5, H6, and the web-UI feedback batch (F1–F4) is genuinely shipped. The architecture is sound: fail-closed config, three trust tiers with real container boundaries, hash-labelled tier images, a SHA-256 hash-chained audit log, and honest ADRs.

**The dominant defect pattern has shifted.** It is no longer "controls not wired" but **"features landed with tests that mock below the seam, so green CI certified code that cannot run."** Every critical finding in this review shares that shape:

- `H7` retry/rerun/export 500 — `test_retry_rerun_export.py` only unit-tests events_snapshot/list_all_runs and a tautological `retry_count += 1`; zero tests hit the endpoints.
- `H8` queue never drains — `test_queue.py` monkeypatches `start_run` with `def fake_start_run(self, **kwargs)`, a catch-all that cannot detect the kwarg mismatch.
- `H9` cost caps hollow — `test_dashboard.py` and `test_cost_caps.py` inject `SimpleNamespace` runs with a `.tokens` attribute the real `Run` dataclass does not have.
- Frontend build red — `RunActions.test.tsx` mocks `retryRun`/`rerunRun`; vitest never type-checks against the real API module.
- Tier images unproven — the only test that builds them is `docker`-marked, and CI runs `-m "not docker"` everywhere.

**Verification infrastructure is the root cause, and it is fixable first.** Phase 0 of this plan (build/install/test isolation + CI that can see the product) unblocks everything else and is sized at S–M.

---

## Finding index

IDs prefixed **R** are new in this review. IDs **C1/C2/H1–H11** refer to `docs/reviews/2026-08-26-full-app-review/00-consolidated-report.md` and are carried forward with updated status.

### Critical

- **R1 — The wheel cannot build tier images; any non-editable install is unusable.** `pyproject.toml:54-55` declares only `[tool.setuptools.packages.find] where = ["src"]` — no `package-data`, no `MANIFEST.in`. `images.py:74-76` resolves the build context to `Path(__file__).resolve().parent / "docker"`. Verified: wheel contains 122 entries, zero under `smolcode/docker/`; installed into a clean venv, `source_hash('restricted')` raises `ImageBuildError: build input missing: .../site-packages/smolcode/docker/restricted.Dockerfile`. From the editable checkout the same call returns hash `60a510bd4fe65ecf`. Consequence for a user: `ensure_tier_images` fails → CLI exit 6 / web refuses boot. The README quickstart is editable-only, so the gap is invisible in normal use.
- **R2 — The React SPA does not compile (8 TypeScript errors).** `web/src/components/EventStream.tsx:169-172` reads `absolute_target`, `effective_cwd`, `allowed_actions` off `StreamEvent`; the backend sends all three (`web/agent_runner.py:756-758`) but `web/src/api.ts:236-305` never declares them. Commit `eb892e0` added these fields to `RunSummary` / `StartRunOptions` instead of `StreamEvent` and its message claims a clean `tsc -b`, which does not reproduce on a clean install. `web/src/components/Inspector.tsx:177,179` uses `tokens.cache_hit` (typed `number | undefined` at `api.ts:144`) without a guard. `tsconfig.app.json` has no `"strict"`, so nothing else catches this class of bug. `pnpm test` passes 114/114 because vitest transpiles without type-checking and the tests mock `api.ts`.
- **R3 — Four web endpoints 500 or silently never fire (H7 + H8, carried forward, not fixed).**
  - `H7` retry/rerun: `web/api.py:1068-1078, 1099-1109` call `mgr.start_or_enqueue_run(..., parent_retry_of=…/parent_rerun_of=…)`; `runs.py:738-751, 867-880` accept neither → `TypeError` → 500 for every retry/rerun (runtime-verified).
  - `H7` export: `web/api.py:1144-1146` does `dict(s)` over a dataclass whose `subagent_history` holds `SubAgentSummary` objects → `TypeError` → 500 whenever a run has subagents. A working implementation already exists at `runs.py:409-431` (`Run.summary_dict`) and is not used.
  - `H7` tier downgrade: `web/schemas.py:211` types `tier` as `str = Field(default="restricted")` (not `Optional[None]`), and `api.ts:873` always sends a body. An empty-body retry of an elevated/orchestrator run silently downgrades to restricted.
  - `H8` queue: `_drain_queue_after_run` (`web/agent_runner.py:1311-1362`) calls `_api_module.get_run_manager()` (1323) and `_deps.get_settings()` (1341) from a worker thread; both require a `Request` (`web/deps.py:19,54`). The `TypeError` is swallowed by the `except` at `agent_runner.py:1208-1211` and logged as `"queue drain failed"`. Queued runs are accepted, listed, and never execute.
  - Zero tests hit any of these endpoints; `test_retry_rerun_export.py` is 96 lines of unit tests that never call the API.
- **R4 — Cost caps and the dashboard are uniformly wrong (H9, carried forward, not fixed).** `web/dashboard.py:74,88-90,109-140` and `runs.py:679-736` read `run.tokens`; the real `Run` dataclass (`runs.py:179-291`) has only `tokens_in`/`tokens_out`. Probes: a real `Run` (200 k in / 100 k out, openai/gpt-4o) → `tokens_today=0, cost_estimate_usd_today=0.0`; $2.50 spend against a $1.00 cap → no 429; `agent_runner.py:392`'s per-step guard (`getattr(run, 'tokens', None) is not None`) is always false so the step stop never fires. `schemas.TokenSummary` (`schemas.py:305-339`) has no `cost_usd` field, so computed cost is stripped on the wire. The tracker is also not passed by `start_run` (`runs.py:856-863`) — only by the broken drain path.
- **R5 — The Python suite is not runnable as configured (98 setup/failures).** `conftest.py:33-48` clears all `SMOLCODE_*` vars and sets only `WORKSPACE` and `AUDIT_LOG`; it does not set `SMOLCODE_EXECUTOR`, so `create_app()` defaults to the docker executor and every `TestClient(app)` boot in `create_app`'s lifespan (`web/server.py:98-112`) calls `ensure_tier_images` → `docker.from_env()`. With the daemon down: 12 failures (`test_web_audit_api.py`) + 86 errors (`test_web_api.py`, `test_web_models_api.py`, `test_web_projects_api.py`, `test_web_providers_api.py`, `test_web_sessions_api.py`). Setting `SMOLCODE_EXECUTOR=local` externally changes nothing (the fixture clears it). This will also fail on GitHub's Docker-less `windows-latest` / `ubuntu-latest` runners. One-line fixture default fixes the trigger; the code defects behind it are R3/R4.
- **R6 — CI cannot see the product.** `.github/workflows/ci.yml` has 4 Python-only jobs (`lint`, `tests`, `sandbox-contract`, `coverage`); zero references to `pnpm`/`node`/`vitest`/`playwright`/`web`. The tier-image contract (`test_tier_images_docker.py`, the only test that builds all three images and checks image↔allowlist consistency) is `docker`-marked and excluded by every job that runs the suite; `sandbox-contract` runs only `test_elevated_iptables.py`. No `pip-audit`, `npm audit`, CodeQL, or Dependabot. The last four commits — install git in restricted image (`3cebcde`), pass `dockerfile=` to builds (`93f05fd`), silent-build detection, vendor repos for `full_access` — are **unproven by any automated check**.

### High

- **R7 — The web server never provisions the restricted internal network.** `web/server.py:98-112` calls `ensure_tier_images()` but not `ensure_internal_network()`; the CLI does (`cli.py:224-233`). On a fresh Docker host every restricted web run fails to launch (`network smolcode-internal not found`). Fail-closed, but the default web path is broken.
- **R8 — RESOLVED IN DECISION, NOT YET IN A REAL CONTAINER** (ADR 0041, `34b6b42`/`af33be8`). The contradiction is gone and the mechanism is chosen and tested two ways, but plan 6.1 #2 asked for a docker-marked test running a **real `CodeAgent` tool call inside `smolcode:restricted`**, and that was substituted for a simulation (`builtins.__import__` patched to make `smolcode` unimportable). The container path is therefore argued and unit-tested, **not yet executed by a real container**. The serialized tool source imports `from smolcode.destructive import …` / `from smolcode.session import current_session` (`tools/shell.py:78-79`, `tools/git.py:362,370`) and the comments claim the package "IS importable on PYTHONPATH" — but the tier Dockerfiles never install smolcode, and the project's own `agents/prompting.py:18-19,80-81` and `sandbox_guard.py:63-65,181` say it is NOT in the sandbox. Inside Docker this either raises `ModuleNotFoundError` (tool errors) or sees a default `SessionState` with `confirm_callback=None` (denies). **No bypass** — but ADR 0035's "prompt fires on every plane" guarantee is unsubstantiated and no test exercises an in-container tool call.
- **R9 — PARTIALLY RESOLVED in Phase 6** (`45c93be`, `7681468`, `34b6b42`, `af33be8`). Tool gates are bypassable through the allowlisted `run` tool (H3, carried forward). The `run` tool allowlists a *basename* only (`tools/shell.py:68-70`) and the restricted command set includes `python` (`config.py:324`). The workspace is bind-mounted **rw for every tier** (`agents/base.py:96-99`). `run("python", ["-c", …])` therefore executes arbitrary code that can write under `.smolcode/uploads` (whose read-only policy lives only in `tools/fs.py:107-117`) and drop `.git/hooks`. `SMOLCODE_EXECUTOR=local` is accepted with no runtime warning (the orchestrator always uses `executor_type="local"`, `agents/orchestrator.py:666-677`).
- **R10 — PARTIALLY RESOLVED in Phase 6** (`f090b93`). Re-opened 2026-09-24: the phase was first marked resolved and that was wrong. Option injection is closed (dash-guards in all nine tools, `--` separators, `git_clone` scheme allowlist, `git_diff` arg allowlist, `git_push` validated before the gate), but three sub-items from plan 6.2 are **not done**: No `--` separator or dash-guard anywhere in `tools/git.py` (578 lines). `git_push` passes model-controlled `remote`/`branch` straight into argv (`git.py:391-395`, so `--receive-pack=…` reaches git); `git_clone` takes an unvalidated URL and unvalidated destination directory with no path policy (`git.py:449-457`); `git_fetch` remote (`git.py:508-514`); `git_checkout` target (`git.py:568-577`); `git_add` paths (`git.py:178-184`); `git_diff` `extra_args` fully model-controlled (`git.py:119-127`, e.g. `--output=<path>`). 
  - `remote` is dash-rejected but **not** validated against `git remote -v`, so an arbitrary *named* remote is still accepted (plan 6.2 #3).
  - **No** `GIT_CONFIG_GLOBAL=/dev/null` or `-c core.hooksPath=` on any git invocation (plan 6.2 #4) — a hostile repo can still supply config or hooks.
  - **No** `.git/` write block in `tools/fs.py` (plan 6.2 #5) — verified absent: `fs.py` contains no `git` reference at all.
- ~~**R11 — UploadsStore follows symlinks (H4, carried forward).**~~ **RESOLVED in Phase 6** (`f5e561a`). (The separate plan 6.4 #2 item — streaming `save` with a size cap rather than buffering the whole body — is **not** done; `save()` still takes a full `bytes` object. That is resource exhaustion, not symlink escape, so it does not reopen R11, but it is tracked as R14.) No `lstat`/`is_symlink` anywhere in `uploads.py`. `read()` (`:449-453`), `delete()` (`:455-464`), `list_metadata()` (`:432-434`) all follow links; `save()`'s collision check (`:333-345`, `.exists()`) + `target.write_bytes` (`:374-375`) is a classic TOCTOU write through a planted symlink. A symlink planted via the rw workspace mount turns `GET /api/uploads/<name>` into arbitrary host-file download.
- **R12 — PARTIALLY RESOLVED in Phase 6** (`8181ead`). Re-opened 2026-09-24: the phase was first marked resolved and that was wrong. Every defect named below is genuinely fixed — prefix heuristic replaced with a default-deny operator allowlist, `is_destructive` now gates MCP calls, the full host environment is no longer inherited, registry ids are unique, `timeout_s` is enforced. What remains is plan 6.5 #1 and it is architectural: `_READONLY_PREFIX_RE = ^(get|search|read|list)_` (`tools/mcp_tools.py:74`) is applied only to servers whose mode the operator declared readonly (`mcp_tools.py:139-141,152-167`); `readwrite`/`full` accept any name. No `is_destructive` call anywhere in the MCP path (`mcp_tools.py:197-208`). MCP servers inherit the **full host environment including API keys** (`tools/_mcp_runtime.py:98-99`). `timeout_s=30.0` is hardcoded and `call_tool`/`list_tools` block on `readline` under a lock with no deadline (`:84,172-215`). Registry ids collide across successive builds (`:242-243,258-268`).
- ~~**R14 — `UploadsStore.save()` buffers the whole body.**~~ **RESOLVED in Phase 6** (`f6c7ead`). Sharper than first recorded: `await file.read()` loaded the entire body into memory **before** the cap was consulted, because the cap lived in `UploadsStore.save()` and therefore ran *after* the allocation. The limit was enforced and still permitted the exhaustion. The endpoint now reads in 1 MiB chunks and refuses at the cap before retaining the offending chunk, so resident memory is bounded by the limit rather than by the request. Refusal is 413. The frontend's hardcoded "up to 50 MB" hint — wrong the moment `SMOLCODE_UPLOAD_MAX_BYTES` was set to anything else — now reads the real value from `/api/config` and pre-checks locally.
- ~~**R13 — MCP tools are not sandboxed under the docker executor.**~~ **RESOLVED BY REFUSAL** in Phase 6 close-out (`90d13c3`; ADR 0041 addendum). An MCP tool call executes on the host, in the server process, outside every container. The Phase 6 gate limited *which* MCP tools may act; it never changed *where* they run. **The operator chose option B on 2026-09-24**: a docker-executor run with MCP configured and no explicit opt-in now **refuses to start**; with `--allow-unsandboxed-mcp` it is allowed and prints a `NOTICE: MCP TOOLS ARE NOT SANDBOXED` banner. `local` is unchanged. **This accepts the capability, it does not contain it** — the host-side proxy (option C) remains unbuilt and is still the real fix.

### Medium — web robustness (all unfixed)

| Item | Evidence |
|---|---|
| `SessionState` TOCTOU: `is_busy()` check (`runs.py:897`) and `_runs` insert (`runs.py:963-964`) are not under one lock; `set_session(None)` in `agent_runner.py:1177` unconditionally clears whatever session a concurrent thread installed | `runs.py:897,963`; `agent_runner.py:967,1176-1179`; `session.py:107-152` |
| No `TrustedHostMiddleware` / Host validation → DNS-rebinding exposure on a loopback API that has no CSRF token and no bearer token (documented as accepted in `docs/architecture.md:732-738`, still unmitigated) | grep: no `TrustedHost` in `src/` |
| `stop()` only sets `stop_flag`; pending approval/diff callbacks poll it on their own timeout, so a run awaiting approval can hang | `runs.py:1090-1095`; `agent_runner.py:442-448,800+` |
| Project create/delete rebuild `Settings(...)` without `cost_rates`/`cost_caps` → both silently reset to `{}` on every project add/remove | `api.py:383-395,418-430`; `config.py:229-233` |
| `_runs` dict never evicted; `run.api_key_value` is read at `agent_runner.py:889-894` and never zeroed; every run is listed forever | `runs.py:672,223` |
| Snapshot tempfiles **FIXED** (`runs.py:624-654`, called at `agent_runner.py:1201-1204`); SSE terminal race **FIXED in code, untested** (`runs.py:1013-1024`) | — |
| `Resume_active_agent` passes `cost_cap_tracker=None` (`agent_runner.py:1293`) — resumed runs would have no per-step cap even if H9 worked | — |
| `QueueEntry.anchor_to_project_root` is never set by `enqueue()` (`runs.py:965-974`) — harmless today only because drain uses the pre-built Run | — |
| `RunManager.__init__` is still monkey-patched at module bottom (`runs.py:1337-1353`) instead of folded into the class | — |
| `api.ts:873,881,893` build retry/rerun/export URLs by raw string concat (every other helper encodes with `encodeURIComponent`) | — |

### Medium — frontend (all unfixed)

| Item | Evidence |
|---|---|
| H10 — the bootstrap effect (`App.tsx:193-212`) depends on `refreshRuns`, which is keyed on `[activeRunId]`; every run selection re-applies server defaults `c.provider`/`c.model` unless `loadLast()` happens to match. No ref guard | `App.tsx:182-212` |
| Transient fetch failure blanks the entire app; `refreshUploads`, the provider fetch, and `onOpenPath` share one error state; no retry; never cleared on success | `App.tsx:453-463,173-180,231-236,329-335` |
| `ApprovalModal` leaks edited diff text across approvals: `editedAfter` is reset only inside `approve()`/`deny()` (`:85,89`), never for `outside_root` buttons (`:95-103`), no effect keyed on `decisionId`, no `key` on the modal in `App.tsx:653-657` | `ApprovalModal.tsx:66,85-103` |
| Selecting a finished run resets events to `[]` and opens a new `EventSource`; no hydration from the events snapshot → "Waiting for events…" forever | `EventStream.tsx:142-147` |
| Countdown drifts (`nowTick` never resets when server `remaining_s` changes; hardcoded 900 s fallback instead of the tier's `timeout_s`); `<Inspector>` never renders `CostBadge` although the ship report claims it does | `Inspector.tsx:51,92-97`; `docs/reviews/2026-08-27-web-ui-user-feedback/*` ship report |
| 15 oxlint warnings (docs claim 4); `ProjectSwitcher.tsx:167` has one `as-any` | `pnpm lint` |
| e2e `project-switcher.spec.ts:55` calls `page.queryByRole` (not a Playwright Page API) — 1 real test bug, the only e2e failure | — |

### Medium — operations / cost / packaging

| Item | Evidence |
|---|---|
| No host-app production Dockerfile, no service unit, no pinned host image, no resource limits. Only `docker-compose.litellm.yml` exists and it ships the LiteLLM proxy alone (loopback 127.0.0.1:4000, healthcheck, blank master key with warning) | `git ls-files` |
| Shutdown is cosmetic: lifespan `finally: pass` (`server.py:113-116`); `/api/health` returns static `{"status":"ok"}` without checking Docker, images, queue depth, or provider reachability (`api.py:143-146`); `access_log=False` (`server.py:161`); run threads are daemon threads (`runs.py:858-862`) | — |
| Cost caps are opt-in and off by default (`{}`); no `max_tokens` on `LiteLLMModel` (`models.py:140-146`); only tier `max_steps` 12/20/40, timeouts 120/180/300 s, and a 900 s web wall-clock are enforced; no container CPU/memory/disk caps | `config.py:329-330,367-368,444-445`; `web/agent_runner.py:63` |
| `pyproject.toml` metadata incomplete for a release: version 0.1.0, no license/authors/readme/URLs/classifiers (a PyPI upload would be rejected as-is) | `pyproject.toml:5-9` |
| Makefile is Windows-only despite POSIX comments (`.venv/Scripts/…` in every target, `rm -rf` in `clean`); README advertises `make` targets with no caveat; `make` is not installed on this host | `Makefile:5-42`; `README.md:60-71` |
| `scripts/install.ps1` hardcodes `py -3.12`; `scripts/quality.ps1` requires a pre-existing `.venv` and runs ruff relative to CWD | `scripts/install.ps1:5`; `scripts/quality.ps1:3-12` |
| Tier base images tag-pinned only (`ARG PYTHON_BASE=3.12-bullseye`); source-hash label covers the Dockerfile + iptables script but not base-image drift | `docker/*.Dockerfile:13-17`; `images.py:50-54` |
| Frontend fresh-clone install is broken on pnpm 10+: `pnpm-workspace.yaml` is auto-generated and gitignored; a clean install fails with `ERR_PNPM_IGNORED_BUILDS: esbuild` until `allowBuilds: { esbuild: true }` is set. README says only `pnpm install` | scratch-copy install log; `.gitignore`; `README.md:552` |

### Medium — documentation drift (Phase 7, unstarted)

| Item | Evidence |
|---|---|
| Quick start hardcodes `E:\python projects\smol_clone_2\` (a different, pre-rename path); copy-paste fails. Same stale path in `docs/environment.md:5,32,119,140` | `README.md:41,75,733` |
| Claims `pyproject.toml` enforces `--cov-fail-under=80`; the gate is the Makefile target and CI job (`pyproject.toml:57-61` has no cov flags) | `README.md:511-513` |
| Trust-tier table says elevated `network_allowlist` is "data structure; iptables enforcement deferred to v1.1" — shipped in v1.7 (M16) | `README.md:87`; `README.md:25`; `docker/iptables-init.sh` |
| Says "IPv4 only in v1.7 (IPv6 dropped)" — IPv6 enforcement shipped in decision 0034 | `README.md:25`; `config.py:299-308`; `docker/iptables-init.sh` |
| Says FastAPI is pinned `<0.140` because of a regression in `0.141`; the real pin is `>=0.115,<0.137` for a regression in `0.137+` — an operator following the README would install a broken FastAPI | `README.md:541` vs `pyproject.toml:32-37` |
| Top status block is a changelog asserting milestones "SHIPPED … on origin/main" while HEAD is 2 commits ahead of `main` and Phases 3–7 are open | `README.md:9-26`; `TASKS.md:21-25` |
| `docs/security.md` still says the elevated-tier iptables work is "Forward-looking (planned for M16)… M16 will close this gap"; M16 shipped 2026-08-23. Also a duplicate `## 9.` heading at `:626` after `## 9. Audit log` at `:307` | `docs/security.md:249-261,626` |
| `docs/environment.md` is dated 2026-06-28, self-describes as the pre-build planning phase ("no code written yet"), and claims the workspace is not a git repo | `docs/environment.md:3-6,45` |
| `TASKS.md:38-40` claims docker-marked tests run in CI Job B; only `test_elevated_iptables.py` does | `TASKS.md:38-40` vs `ci.yml:81-84` |
| `ci.yml:8-13` header says the coverage gate is "NON-BLOCKING" and `full_access.Dockerfile` "does not build as written"; both untrue at HEAD (coverage is blocking since `d9a5519`; the Dockerfile was repaired) | `ci.yml:8-13` |
| The 08-27 architecture report's §6 still lists tier Dockerfiles as MISSING while its §0 says decision 0035 closed it | `docs/reviews/2026-08-27-architecture-vs-claude-md/REPORT.md:116,182,192,230-247` vs `:20-35` |
| `.env.example` documents 7 `SMOLCODE_*` vars; `config.py` reads 12 and other modules read ~25 in total (`EXECUTOR`, `PROVIDER`, `MODEL`, `PROJECTS`, `COST_RATES`, `COST_CAPS`, `UPLOAD_DIR/MAX_BYTES/ALLOWED_MIME`, `MCP_CONFIG`, `AUDIT_LOG/AUDIT_HASH_CHAIN`, `WEB_DIFF_GATE/RAW`, `WEB_RUN_TIMEOUT_S/DRAIN_S`, `WEB_MENTION_MAX_BYTES`, `AUTO_APPROVE_DESTRUCTIVE`, `*_CONFIRM_TIMEOUT_S`). It also references a previously exposed `OPENCODE_GO` key — treat as compromised until rotation is confirmed | `smolcode/.env.example`; `config.py` |
| `smolcode images ensure` as a direct module call exits 1 with a raw `DockerException` traceback instead of the documented clean exit 6 (the CLI boot path wraps it; the module CLI does not) | `images.py:_main` |

### Low / Info

| Item | Evidence |
|---|---|
| Image source-hash does not cover base-image tag drift or vendor repo key changes — a stale-but-label-matching image is reused forever (documented in ADR 0035) | `images.py:50-54` |
| Child (delegation) sessions copy the parent's auto-approve flags and carry no `run_id`, so `set_auto_approve` on the outer run matches a child session (`session.py:225-230` "trust the caller") — the web auto-approve endpoint can flip a full_access child's flag. By design per ADR 0035, untested | `agents/orchestrator.py:233-244,407-418`; `session.py:225-230` |
| Child session state can diverge from the outer run's auto-approve banner; sub-agent destructive decisions are audited on the parent's inherited callback | `agents/orchestrator.py:233-244` |
| No privileged containers, no host socket mounts, no extra capabilities beyond `NET_ADMIN` for elevated; provider API keys are **not** passed into containers (models are called from the host). MCP subprocesses do inherit the full host env | grep `privileged`/`docker.sock` = 0 hits; `base.py:106`; `_mcp_runtime.py:98-99` |
| One transient pytest setup flake in `test_gate_context.py::test_run_git_push_is_classified_destructive` (passes 20/20 in isolation; clean in 3 subsequent full runs) — worth a glance | reviewer test log |
| `.env.example:6-8` points at decision 0015 §11 key-rotation procedure for a key that was previously exposed | — |
| `uv lock` warns `tool.uv.dev-dependencies` is deprecated (use `dependency-groups.dev`) | `uv lock --check` |
| `TASKS.md` contains a duplicated "Note on BE failures" block (lines 150-175 and 177-195) | `TASKS.md` |

---

## What is genuinely good (closed and verified)

| Finding | Status | Evidence |
|---|---|---|
| C1 — destructive gate keyed on ambient session tier | **FIXED on BOTH planes** (Phase 6, ADR 0041, `34b6b42`/`af33be8`). The container plane was not merely unverifiable, it was broken: the gate's import raised `ImportError` in the sandbox. Now a two-path gate — host keeps the real classifier and the interactive prompt, container uses an inlined classifier against a host-bound policy and fails closed. C1's "every plane" contract is now genuinely met. |-closed)** | Gate now keys on the tool's own `tier_name` (`shell.py:43,78-100`, `git.py:352-389`), bound per build (`tools/__init__.py:76-77`); child `SessionState` per delegation (`orchestrator.py:230-251,404-456`); CLI false premise removed (`cli.py:246-252,283-309`); web modal + auto-approve flip the read flag (`agent_runner.py:442-540`, `runs.py:1103-1118`); direct web `full_access` hard-rejected (`api.py:709-722`); `run(git push|reset …)` classified (`destructive.py:214-220`). `test_gate_context.py` 20/20. See R8 for the in-container caveat. |
| C2 — tier Dockerfiles never reached the executor | **FIXED and now VERIFIED** (Phase 6, `128ae26`) | All three images were **unbuildable**: `python:3.12-bullseye` pins a `git` version that has been superseded, so `apt-get install git` 404s. This was concealed because docker-marked tests were *skipping* with the daemon down. Moved to bookworm; restricted and elevated now build and run under a live daemon. `full_access` remains blocked by an upstream HashiCorp 404 — skipped, not passing. |(`base.py:116-125`); `dockerfile=` passed explicitly (`images.py:122-128,175-182`); hash-labelled reuse + fail-closed (`images.py:90-101,148-221`); CLI exit 6; web boot refusal; Dockerfiles repaired (restricted installs git/pytest/ruff + non-root user; elevated adds curl/jq/make/node/iptables/gosu; full_access uses Debian packages + signed vendor repos) |
| H1 — network isolation declared but not enforced | **PARTIALLY FIXED (wiring); runtime UNVERIFIABLE** | Restricted attaches only to `internal=true` bridge (`base.py:108-115`, `container.py:46-74`); elevated keeps `NET_ADMIN` + v4/v6 default-deny OUTPUT with DNS/loopback/ESTABLISHED/ICMPv6 allowances (`base.py:100-107`, `iptables-init.sh:90,130,141-143`). Bounded by `test_network_posture.py`. See R7 (web never provisions the bridge) |
| H5 — audit chain restarted at genesis per sink | **FIXED** | Chain continuation from tail; multi-run logs pass `verify_chain`; tampered tail blocks further appends with an actionable error (`test_audit_integrity_phase2.py`) |
| H6 — web audit layer disabled | **FIXED** | `create_app` builds a real `AuditSink` unless `--no-audit` (`server.py:33-66`), fail-closed; all four read paths redact including `audit ls --json` |
| Web UI feedback F1–F4 | **SHIPPED** (`69b616f`, `e1ffd39`, `dcd41d4`, `c923dd1`/`eb892e0`/`73b05bd`, `108b145`, `a8e57c4`) | dashboard clock domain, Inspector model/provider/cache fields + context circle, project-root anchoring + outside-root gate + Open-in-Explorer, outside-workspace selector |
| Security subset | **PASS** | 268 passed, 8 correctly deselected (docker-marked) |
| Repo hygiene | **PASS** | clean tree; no tracked artifacts; no secrets; conventional decision-referenced commits; ADRs 0001–0037 complete; `.gitignore`/`.gitattributes` present; coverage gate is blocking (`d9a5519`) despite the stale header |
| LiteLLM compose + config | **ACCURATE** | loopback-only 4000 bind with healthcheck; master key intentionally blank with warning; every provider key via `os.environ` placeholder; no hardcoded secrets |
| README audit + full-access confirmation sections | **ACCURATE** | match `cli.py:235-252,341-367` and `confirm.py` |

---

## Root-cause analysis — why this happened twice

1. **The dominant failure mode has shifted from "controls not wired" to "tests that mock below the seam."** H7, H8, H9, R2, and R6 all shipped with green tests because the tests replaced the very seam that was broken (`**kwargs` catch-alls, `SimpleNamespace` fakes with attributes the real class lacks, API mocks, `-m "not docker"` everywhere).
2. **No build/type gate runs anywhere.** `pnpm build` is never invoked in CI; `tsc -b` is not a separate script; `vitest` does not type-check. A commit whose message claims "tsc clean" can be red and nobody finds out until a user runs `pnpm dev`.
3. **The suite cannot run without Docker because a fixture forgot one variable.** One missing `monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")` in `conftest.py` means 98 tests report as environment failures on every Docker-less machine, training contributors to ignore red.
4. **The wheel was never built from a clean checkout.** The README's quickstart is `uv pip install -e`, so `package-data` has never been exercised. R1 would have been caught by a single CI step that installs the wheel.
5. **Docs were updated per-phase but never reconciled per-release.** Every stale claim traces to a phase that shipped a change without a sweep of the files the change made wrong (`README.md:87`, `:25`, `:541`, `security.md:249`, `ci.yml:8-13`, `TASKS.md:38-40`).

---


## What was NOT verifiable in this review (and why it matters)

| Unverified | Reason | Risk if wrong |
|---|---|---|
| ~~Tier images actually build~~ **restricted + elevated VERIFIED in Phase 6**; `full_access.Dockerfile` (4 external apt repos + gosu download) | Docker daemon down | R6; a broken Dockerfile ships silently |
| Restricted container has no egress; elevated iptables/ip6tables enforce the allowlist | Docker daemon down | R7; H1 remains a declaration |
| ~~In-container destructive gate behavior~~ | **NOW VERIFIED** — the daemon came up in Phase 6 and `test_container_gate_phase6.py` measures the real `ModuleNotFoundError`, while `test_inlined_gate_phase6.py` drives both gate paths | — | |
| Live LLM end-to-end (hosted provider, Docker executor, artifact on disk) | No provider key | The only in-repo evidence (`README.md:180-183`) predates every remediation commit |
| pnpm install in the repo itself | Pre-existing partial `node_modules` (symlinks into a missing `.pnpm` store, no `.modules.yaml`); reproduced cleanly in a scratch copy instead | Not a repo defect; the `pnpm-workspace.yaml` gap in R-frontend-medium is |
| `make test` / `make quality` | `make` not installed on this Windows host | Equivalents (`ruff`, `pytest`) run directly |
| Dependency CVEs | No scanner exists | Pins are silent-staleness risks |
| 12 docker-marked tests + 1 shellcheck-marked | **Daemon now up in Phase 6**, so these execute rather than skip; `full_access` still skips (upstream HashiCorp apt outage) | Expected on this host; CI is meant to run them |

**Bottom line:** the evidence supports NOT PRODUCTION READY. The remediation plan in this folder sequences the work so the verification machinery lands first, then the four critical runtime fixes, then the security hardening phases, then release.
