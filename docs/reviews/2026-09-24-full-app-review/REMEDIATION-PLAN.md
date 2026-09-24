# smolcode Remediation Plan #2 — Phased (finish the app, make it ready to use)

**Date:** 2026-09-24
**Source:** Full application review #2 of 2026-09-24 (`docs/reviews/2026-09-24-full-app-review/REVIEW-REPORT.md`).
**Finding IDs:** `R1–R12` are new in that report; `C1/C2/H1–H11` refer to `docs/reviews/2026-08-26-full-app-review/00-consolidated-report.md` and are carried forward with updated status.
**Status:** active · **Mode:** plan only — nothing in this document has been implemented.
**Relationship to the 2026-08-26 plan:** Phases 0–2 of that plan shipped. This plan starts at Phase 3 and re-sequences so that verification machinery (build/install/test isolation + CI coverage of the product) lands **before** feature repairs — because the review showed that the previous partial Phase-3 landing passed CI while shipping four runtime-broken endpoints and a non-compiling SPA.

---

## Goal and definition of done

**Goal:** smolcode can be installed from a wheel by a new user, built and tested end-to-end in CI, run as a web app, and produce a real result with a hosted model inside a sandboxed container — with every security control the docs claim actually verified by a test that would fail if the control were removed.

**Definition of done (all must be true on `main`):**

1. `pip install smolcode-*.whl` in a clean venv → `smolcode --print-config` and `python -m smolcode.images source-hash restricted` both work (the wheel carries `docker/`).
2. `pnpm build` (tsc + vite) exits 0 with `strict: true`. `pnpm lint` 0 errors. `pnpm test` and `pnpm test:e2e` green (0 failures).
3. Full Python suite green on a Docker-less machine: `pytest -m "not docker"` → 0 failures, 0 errors.
4. CI runs and blocks on: Python lint/format, Python tests (ubuntu+windows), coverage ≥80, tier-image contract (builds all three images, fails on build error), web lint/build/unit/e2e, Python + npm dependency audit.
5. Every endpoint in R3 returns 2xx against the real `RunManager` in a committed endpoint test; a deliberately removed kwarg turns that test red.
6. A docker-marked integration test proves: restricted container has no egress; elevated firewall allows only the CIDR list; a destructive tool call inside the container prompts (or is denied) per the ADR 0035 contract.
7. `docs/security.md`, `README.md`, `TASKS.md`, `ci.yml` header, and `docs/environment.md` contain no claim contradicted by a test or command in this plan.
8. One recorded live end-to-end run (hosted provider, docker executor, artifact on disk) is attached to the release notes.

**Not in scope for v1.0 (documented as accepted risk in README "Known limitations"):** multi-user auth, CSRF tokens, non-loopback binding, Kubernetes, Monaco editor, mobile/touch queue reorder, real-time collaboration. The loopback-only + no-CSRF threat model (`docs/architecture.md:732-738`) remains the accepted posture; Phase 5 adds Host-header validation to narrow the DNS-rebinding hole without changing that posture.

---

## Guiding principles (inherited from the 2026-08-26 plan, still binding)

1. **Make truth verifiable before making code better.** No phase ships a fix whose absence would not turn a gate red.
2. **No test may mock below the seam it claims to cover.** Real `RunManager`, real `Run` dataclass, real API module, real build. Fakes are allowed only at the network boundary (provider, Docker daemon).
3. **One execution-plane truth.** Pin container-vs-host behavior in a test before unifying it (R8).
4. **Wire controls before adding new ones.** R3/R4 are wiring fixes, not new mechanisms.
5. **No security-control change ships without a test that fails when the control is disabled.**
6. **Repo conventions:** ruff line-length 119; `ruff check` + `ruff format --check` before `pytest`; each shipped phase gets an ADR continuing the numbering (next free = **0038**); update `TASKS.md` as cross-session state; conventional commit subjects tagged `[decision NNNN]`.

**Standard validation commands (run from repo root unless noted):**

```
# Python quality + suite (canonical path; the Makefile wrappers are Windows-only until Phase 7)
uv run ruff check smolcode/src smolcode/scripts
uv run ruff format --check smolcode/src smolcode/scripts
uv run pytest smolcode/src/smolcode/tests -m "not docker" -q
uv run pytest smolcode/src/smolcode/tests -m "not docker" -q --cov=smolcode --cov-report=term-missing --cov-fail-under=80

# Web quality + suite (from smolcode/web)
pnpm install --frozen-lockfile
pnpm lint
pnpm build          # tsc -b && vite build
pnpm test           # vitest run
pnpm test:e2e       # playwright test
```

---

## Phase dependency graph

```
Phase 3 (build/install/test isolation + CI can see the product)   [S-M]
   ├──> Phase 4 (backend feature repair: H7/H8/H9)                 [M]
   │        └──> Phase 5 (frontend correctness + strict TS)       [M]
   ├──> Phase 6 (tool & MCP hardening: H2/H3/H4/H11 + R8)        [L]
   │        └──> Phase 7 (web/session robustness)                 [M]
   └──> Phase 8 (ops & release: host Dockerfile, shutdown, scans)  [M]
            └──> Phase 9 (docs alignment + release evidence)      [M]
```

Phases 4 and 6 are independent and can run in parallel by different people once Phase 3 lands. Phase 5 depends on Phase 4 (it consumes `cost_usd` and the fixed retry contract) and Phase 3 (a working `pnpm build`). Phase 7 depends on Phase 6 (the composition boundary changes what the session model must protect). Phase 8 can start its non-dependent parts (host Dockerfile, scans) after Phase 3.

---

## Phase 3 — Make the product buildable, installable, and testable; make CI able to see it

**Objective:** `pnpm build` is green; a wheel install works; the Python suite runs without Docker; CI fails when any of those regress. **Everything else in this plan is unverifiable until this lands.**

**Findings addressed:** R1, R2, R5, R6 (CI visibility half), R-frontend-medium (e2e test bug, pnpm-workspace).

**Exit criterion (the "broken control ⇒ red" test for this phase):** on a scratch branch, delete one line from `pyproject.toml`'s new `package-data`, or add one unknown property to `StreamEvent` that a component reads — CI goes red.

### 3.1 Frontend build (R2)

1. **RED:** add `pnpm typecheck` script = `tsc -b` to `web/package.json`; wire it as a standalone step so it cannot be skipped by a future `build` change.
2. Fix `web/src/api.ts:236-305` — add to `StreamEvent`: `absolute_target?: string`, `effective_cwd?: string | null`, `allowed_actions?: string[]`, and a typed `ApprovalKind` union for the values the backend actually sends (`agent_runner.py:756-758`; verify the exact set at implementation time, not from this document). Keep them optional so legacy servers that omit them still type-check.
3. Fix `web/src/components/Inspector.tsx:177-179` — render the cache badge only when `tokens.cache_hit != null && tokens.cache_hit > 0`.
4. Enable `"strict": true` in `web/tsconfig.app.json`; fix the resulting errors in a **separate commit** from the 8 known ones so the strictness adoption is reviewable. Budget: expect 10–40 new errors; if a cluster is large, use `// @ts-expect-error` sparingly with a comment, or defer that file to a follow-up — do not weaken compiler options.
5. Add `"noUncheckedIndexedAccess": true` in the same follow-up commit if the error count is manageable; otherwise record it as a Phase 9 follow-up. Do not add both flags in the same commit as the 8 fixes.
6. Fix `web/e2e/project-switcher.spec.ts:55` — `page.queryByRole` is not a Playwright API. Use `expect(page.getByRole('note')).toHaveCount(0)` (or `not.toBeVisible()`).
7. `web/src/components/ProjectSwitcher.tsx:167` — remove the single `as any` (or justify it in a comment).

**Tests:** new `web/src/__tests__/api-types.test-d.ts` (vitest typecheck or a `tsc --noEmit` fixture) asserting `StreamEvent` accepts an `approval.requested` frame with the three fields, so a future removal is a type error in CI.

### 3.2 Python test isolation (R5)

1. `smolcode/src/smolcode/tests/conftest.py:33-48` — in `_isolate_env`, add `monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")` with a comment explaining that `TestClient(app)` boots the lifespan and a docker executor would try to build tier images.
2. Add an opt-in marker/fixture for tests that genuinely need the docker executor (`@pytest.mark.docker` already exists — add a `docker_executor` fixture that sets the env var explicitly for those tests only).
3. Add a **collection-time** guard: a test that calls `create_app()` and enters a `TestClient` context while `SMOLCODE_EXECUTOR=docker` is a configuration error, not an environment failure. Simplest form: a session-scoped autouse check that fails with an actionable message if `SMOLCODE_EXECUTOR` is unset at session start.
4. Re-run the full suite on a Docker-less machine and confirm 0 errors / 0 failures before proceeding.

### 3.3 Packaging (R1)

1. `smolcode/pyproject.toml` — add:
   ```toml
   [tool.setuptools.package-data]
   smolcode = ["docker/*.Dockerfile", "docker/*.sh"]
   ```
   (Verify with `uv build` that `smolcode/docker/*` appears in the wheel; if setuptools still drops it, add a `MANIFEST.in` with `recursive-include src/smolcode/docker *` **and** `include-package-data = true`.)
2. Add `smolcode/tests/test_packaging.py` (docker-less, runs in the `lint` job):
   - `tier_build_context().is_dir()` is True when imported from an installed (non-editable) package — i.e. assert the four Dockerfiles + `iptables-init.sh` are importable-relative;
   - `source_hash(tier)` returns a stable 64-hex string for all three tiers (no Docker needed);
   - skip-with-message (not fail) when running from the editable checkout *only if* a `SMOLCODE_TEST_INSTALLED` env var is absent — better: run this test in a dedicated CI job that installs the built wheel into a throwaway venv (3.4) and assert it there, so the editable case does not mask a packaging regression.
3. Fix `smolcode/src/smolcode/images.py:_main` — wrap the Docker client failure in `ImageBuildError` and return the same clean exit code (6) and message as the CLI boot path, instead of a raw `DockerException` traceback.

### 3.4 CI that can see the product (R6)

Add to `.github/workflows/ci.yml` (next ADR documents the design):

- **`web` job** (ubuntu, `pnpm/action-setup` + `actions/setup-node` with the Node version from `package.json`/`.nvmrc`): `pnpm install --frozen-lockfile` → `pnpm lint` → `pnpm typecheck` → `pnpm build` → `pnpm test` → `pnpm test:e2e` (chromium only on PRs; full 3-browser matrix on `main`).
- **`tier-images` job** (ubuntu, Docker available): `pytest smolcode/src/smolcode/tests/test_tier_images_docker.py smolcode/src/smolcode/tests/test_network_posture.py -m docker -v` with a **build-failure-is-test-failure** policy: today the tests self-skip on build error (`test_tier_images_docker.py:58-64`); change the skip condition to skip only when Docker itself is unreachable, and fail when a build fails. Also fail the job if fewer than 3 images were built/verified.
- **`packaging` job** (ubuntu): `uv build --wheel` → install the wheel into a fresh venv → `python -c "from smolcode.images import source_hash; print(source_hash('restricted'))"` → `smolcode --print-config`. No provider key needed.
- **`audit` job**: `uv run pip-audit` (or `safety`) against the lockfile; `pnpm audit --audit-level=high` in the web job. Add Dependabot for `pip` (pyproject) and `npm` (web). Non-blocking for the first week, then blocking.
- Fix the stale `ci.yml:8-13` header while you are in the file (coverage **is** blocking; `full_access.Dockerfile` **does** build as written) — or defer to Phase 9; do not leave a known-false comment in a file you are editing.

### 3.5 Frontend install reproducibility

1. Create and **commit** `smolcode/web/pnpm-workspace.yaml` with `allowBuilds: { esbuild: true }` (it is currently auto-generated and gitignored, so a fresh clone on pnpm 10+ fails with `ERR_PNPM_IGNORED_BUILDS`). Confirm a clean `pnpm install --frozen-lockfile` in a scratch copy exits 0 with the committed file.
2. Document in `smolcode/web/README` (or README §Run the web GUI) that pnpm ≥10 requires this file; the CI `web` job is the regression guard.

**Size:** S–M (est. 1.5–2.5 person-days). **ADR:** 0038. **Commits:** one per sub-item (type fix / strict / conftest / package-data / CI jobs / pnpm-workspace) so any one can be reverted independently.

---

## Phase 4 — Backend feature repair: retry, rerun, export, queue, cost caps (H7, H8, H9)

**Objective:** the four paths the web UI already exposes work against the real `RunManager`, and the tests that prove it do not mock below the seam.

**Findings addressed:** R3, R4, plus web-medium: project cost-rate wipe, `resume_active_agent` tracker, `QueueEntry.anchor_to_project_root`.

**Working replacements that already exist (use them, do not re-invent):** `Run.summary_dict` (`runs.py:409-431`) for export; the `with_overrides` copy helper pattern (`config.py:249-250,267-268`) for project create/delete.

### 4.1 Retry / rerun / export (H7)

1. `web/runs.py:738-751, 867-880` — add `parent_retry_of: str | None = None` and `parent_rerun_of: str | None = None` parameters to `start_run` and `start_or_enqueue_run`; persist both on `Run` (`runs.py:179-291`); surface them in `summary_dict` and the SSE `run.started` event.
2. `web/api.py:1068-1108` — the calls then match. Keep the existing body-vs-parent tier logic, but make it correct:
3. `web/schemas.py:211` — `tier: str | None = Field(default=None, …)` for `RunStartRequest`; the *endpoint* (not the schema) applies the default `'restricted'` for a fresh `POST /api/runs`. Retry/rerun inherit the parent tier when the body omits it. Add a comment at both sites explaining why the default moved.
4. `web/src/api.ts:861-878` — `retryRun`/`rerunRun` must send **no body** (or `{ tier: parentTier }` gathered from the run summary) when the caller has no overrides; never `JSON.stringify({})`.
5. `web/api.py:1144-1146` — export via `Run.summary_dict()` (or `dataclasses.asdict` on the already-plain structures), not `dict(dataclass)`. Keep Pydantic `model_dump` for the Pydantic parts.
6. `web/src/api.ts:873,881,893` — `encodeURIComponent(id)` on retry/rerun/export URLs, matching every other helper in the file.

### 4.2 Queue drain (H8)

1. Store the manager + settings on `RunManager` at construction (`runs.py:1343-1353` — fold the monkey-patch into the class while you are here, per the carried-forward Phase-5 note) and have `_drain_queue_after_run` (`agent_runner.py:1311-1362`) read `self` / the stored settings. Delete the `_api_module.get_run_manager()` and `_deps.get_settings()` calls entirely.
2. Do **not** swallow the drain failure silently: keep the log line but also set a `queue_drain_error` flag surfaced at `GET /api/health` (Phase 8) so a future regression is visible rather than silent.

### 4.3 Cost caps and dashboard (H9)

1. Add `Run.tokens` as a **property** returning a `TokenSummary`-shaped object built from `tokens_in`/`tokens_out` (`runs.py`), **or** replace every `getattr(r,'tokens',None)` read at `dashboard.py:74,88-90,109-140`, `runs.py:679-736`, and `agent_runner.py:392,402` with explicit `tokens_in`/`tokens_out` reads. Prefer the property: it preserves the existing call sites and gives one definition of "this run's tokens".
2. `web/schemas.py:305-339` — add `cost_usd: float | None = None` to `TokenSummary` so the computed cost survives serialization (`dashboard.py:653-655` already computes it).
3. `web/runs.py:856-863` — pass `cost_cap_tracker` into `run_in_thread` from `start_run` (today only the drain path does). `agent_runner.py:1293` (`resume_active_agent`) — same.
4. `web/api.py:383-395,418-430` — project create/delete must preserve `cost_rates` and `cost_caps` when rebuilding `Settings` (use the `with_overrides` pattern; add a test that creates a project with caps set, deletes it, and asserts the caps survive on the remaining settings).
5. `web/runs.py:965-974` — pass `anchor_to_project_root` into `enqueue()` so `QueueEntry.anchor_to_project_root` reflects reality.
6. Startup: if any provider has a cap configured but no rate in `cost_rates`, log a warning at `create_app` and expose it via `GET /api/cost-caps` (`rate_source`), per decision 0032's design note.

### 4.4 Tests — the part that was missing last time

All under `smolcode/src/smolcode/tests/`, using the **real** `RunManager` from `app.state.run_manager` (the pattern `test_web_runs_api.py` already uses, with only `_build_agent_for_run` stubbed):

- `test_retry_rerun_export.py` — extend to endpoint level:
  - `POST /api/runs/{id}/retry` on a terminal run → 200, new run id, `parent_retry_of` set, `retry_count == parent.retry_count + 1`;
  - empty-body retry of an **elevated** run → child tier is `elevated` (this is the test that would have caught the downgrade);
  - `POST /api/runs/{id}/rerun` → 200, `parent_rerun_of` set;
  - `GET /api/runs/{id}/export` on a run **with subagent history** → 200 and valid JSON (this is the test that would have caught the `dict(dataclass)` 500);
  - unknown run id → 404, not 500.
- `test_queue.py` — replace the `**kwargs` catch-all fake with a fake that has the **real** `start_run` signature (or call the real one with a stubbed agent builder): enqueue 3 runs while one is active → after the active run ends, all 3 execute sequentially in order. This is the test that would have caught H8.
- `test_dashboard.py` / `test_cost_caps.py` — delete the `SimpleNamespace` fakes with a `.tokens` attribute; build **real** `Run` objects (set `tokens_in`/`tokens_out`, `started_at`) and assert:
  - a 200k-in/100k-out run yields non-zero `tokens_today` and a non-zero `cost_estimate_usd_today` for a provider with a rate;
  - spend past the cap → `POST /api/runs` returns 429 with `cost_cap_reached:`;
  - the per-step callback raises `_StopRequested('cost_cap_exceeded')` when a real run crosses the cap mid-run;
  - `GET /api/dashboard` response JSON contains `cost_usd` (regression test for the Pydantic strip).
- `test_web_runs_api.py` — add: concurrent `POST /api/runs` (two simultaneous starts → exactly one gets 409/queued, per the `is_busy` contract) and project create/delete preserving caps.

**Size:** M (est. 2–3 person-days). **ADR:** 0039. **Note:** the fix for H7 alone is ~10 lines; the tests are the bulk of the work, and that is the point.

---

## Phase 5 — Frontend correctness (H10 + medium frontend)

**Objective:** the SPA reflects backend reality and stays that way under TypeScript strict mode.

**Findings addressed:** H10, R-frontend-medium (all rows), the `CostBadge`/`Inspector` drift, the ship-report claim that the Inspector renders per-run cost.

**Depends on:** Phase 3.1 (strict TS), Phase 4.3 (`cost_usd` on the wire).

1. **H10** — `web/src/App.tsx:182-212`: split the bootstrap effect (runs the *once*: `getConfig` + `loadLast`) from the refresh callback. Use a `useRef` guard (`bootstrappedRef`) on the effect that sets `selectedProviderId`/`selectedModelId`, and key `refreshRuns` on stable values (not `activeRunId`). Test: switching the active run does not change the composer selection (`App.test.tsx`).
2. **Error handling** — `App.tsx:453-463`: split the single `error` state into a per-pane transient error (banner with retry) vs. a fatal boot error (only when `/api/config` itself fails and the app cannot render). `refreshUploads`, the provider fetch, and `onOpenPath` must not blank the app. Clear the error on the next success.
3. **ApprovalModal** — `ApprovalModal.tsx:66`: reset `editedAfter` in a `useEffect` keyed on `pending.decisionId` (and on mount), and give the modal a `key={pending.decisionId}` at `App.tsx:653-657`. Add Escape-to-deny and a focus trap. Test: deny A, then approve B → B shows the original diff, not A's edits.
4. **Finished-run history** — `EventStream.tsx:142-147`: on run selection, hydrate from the run's events snapshot (`GET /api/runs/{id}/events` snapshot endpoint — confirm the exact snapshot API at implementation time; `runs.events_snapshot` exists) before opening the `EventSource`. Add a "replay" path: if the run is already terminal, render the snapshot and do not open a stream. Test: selecting a finished run shows its events immediately.
5. **Countdown + cost** — `Inspector.tsx:51,92-97`: reset `nowTick` when the server's `remaining_s` changes; take the fallback from the tier's `timeout_s` (from `/api/config`) instead of the hardcoded 900; render `CostBadge` (per-run cost from `cost_usd`). Test with fake timers.
6. **Lint** — drive `pnpm lint` warnings from 15 to 0 (or document each remaining warning in `oxlint` config with a reason).

**Tests:** vitest additions for each item above; one Playwright spec that selects a finished run and asserts the Inspector shows tokens + cost + status without waiting for SSE.

**Size:** M (est. 2–3 person-days). **ADR:** 0040.

---

## Phase 6 — Tool & MCP hardening + the in-container plane truth (H2, H3, H4, H8/R8, H11)

**Objective:** host-side tools enforce what their names promise even against hostile arguments; the destructive gate has one defined, tested behavior inside the container; MCP is usable-or-absent, never silently leaky.

**Findings addressed:** R8, R9, R10, R11, R12 (and the M-items carried from the 2026-08-26 plan: run cwd/timeout/output bounds, patch_file empty-hunk/newline bugs, git_checkout gating, MCP broken-under-docker, registry collisions, env inheritance).

**Depends on:** Phase 3 (so the docker-marked tests actually run in CI).

### 6.1 R8 first — decide the in-container plane, then pin it with a test

1. **Decide** (ADR required): either (a) the gate logic is inlined into the serialized tool source so it needs no host import, or (b) smolcode is installed into the tier images, or (c) the in-container tool proxies the decision over the host boundary. Option (a) is the smallest and keeps images lean: the serialized source already carries `tier_name`; the destructive classification and the confirm decision can be reduced to a few lines that only need a callback object smolagents can serialize, or the gate can be declared **host-plane-only** and the container denied destructive ops outright unless a host-issued token is present.
2. Write the test first: a `docker`-marked test that runs a real `CodeAgent` tool call inside the `smolcode:restricted` image for `run('git', ['push', …])` and asserts the outcome matches the ADR contract (denied or prompts). This test must fail before the fix.
3. Update `agents/prompting.py:18-19,80-81` and `sandbox_guard.py:63-65,181` to state the chosen truth; delete the contradictory comments in `shell.py:75-77`/`git.py:366-369`.

### 6.2 Git dash-guards (H2 / R10)

1. Reject any argument beginning with `-` in every git tool, and insert `--` where the subcommand supports it: push (`git.py:391-395`), clone (`:449-457`), fetch (`:508-514`), checkout (`:568-577`), add (`:178-184`), diff (`:119-127` — model-controlled `extra_args` is the worst case; allowlist the flags instead), log/status/commit.
2. `git_clone`: scheme-allowlist the URL (`https`, `ssh`); resolve `directory` through `PathPolicy.resolve_under_workspace`; reject a destination that exists and is non-empty unless `overwrite` is set.
3. Validate `remote` against the repo's configured remotes (`git remote -v`) for push/fetch; reject remotes starting with `-`.
4. Export `GIT_CONFIG_GLOBAL=/dev/null` (or an empty temp file on Windows) and `-c core.hooksPath=` for every git invocation so a repo-local `core.hooksPath` or alias cannot execute.
5. Block writes under `.git/` in `tools/fs.py` (all tiers except full_access, which is already audited).
6. Generate the repetitive guards from one template or add an **equivalence test** across all nine git tools so a future tool cannot ship without a guard (the 2026-08-26 review's INFO item — still open).

### 6.3 Composition boundary (H3 / R9)

1. Decide and document the trust model per executor mode. Minimum viable: make the uploads directory read-only **at the mount level** for restricted (a second bind mount `:ro` for `.smolcode/uploads`), and mount `.git` read-only for restricted. Tool-level checks in `forward()` are advisory once `run('python', …)` exists; mount flags are the only enforcement that survives composition.
2. When `SMOLCODE_EXECUTOR=local`, print a prominent one-line warning at boot: *local executor is not a sandbox; model-written code runs on the host with your full permissions.*
3. Bound the `run` tool: clamp `timeout` to the tier's timeout, cap captured output (e.g. 1 MB, truncate with a marker), bind `cwd` to the workspace (not `None`).

### 6.4 Uploads symlink hardening (H4 / R11)

1. `uploads.py` — `os.lstat` + `stat.S_ISLNK` rejection in `read`, `delete`, `list_metadata`, and `save`; on `save`, open with `O_NOFOLLOW|O_CREAT|O_EXCL` (POSIX) / re-check after open (Windows) to close the TOCTOU.
2. Stream with a size cap during save rather than buffering the whole body; align the "50 MB" hint with `config.upload_max_bytes`.

### 6.5 MCP (H11 / R12)

1. **Under the docker executor**, MCP tools cannot run host-side as currently structured. Either ship a host-side proxy (tools stay on the host; only calls cross the boundary) or refuse `mcp_configs` + docker at build time with an actionable error. Do not leave the current silent behavior.
2. Default-deny the server environment: pass only `PATH`, `HOME`, temp dirs, and an explicit per-server passthrough list from `mcp_config.json`; never `dict(os.environ)`.
3. Replace the name-prefix readonly heuristic with an operator-curated per-tool allowlist (keep the prefix regex as an advisory lint); route MCP calls through `is_destructive` for elevated/full_access.
4. Globally unique registry ids (monotonic factory), close superseded servers, resolve configs once per run.
5. Implement the configured `timeout_s` (selector + kill on deadline) and document the single-flight lock.

**Tests:** a docker-marked in-container tool-call suite (6.1); host-side unit tests for every dash-guard with a table of hostile argv; symlink tests using `tmp_path` (no Docker needed); MCP env-passing tests with a fake subprocess.

**Size:** L (est. 4–6 person-days — the largest phase). **ADR:** 0041.

---

## Phase 7 — Web & session-model robustness

**Objective:** no cross-run state leaks, a browser cannot reach the API with a forged Host, and stopping a run always terminates it.

**Findings addressed:** web-medium TOCTOU, Host header, stop/approvals, run eviction, API-key retention, `RunManager.__init__` monkey-patch (folded in Phase 4), child-session auto-approve scope (Low).

**Depends on:** Phase 6 (the composition boundary changes what the session model must protect).

1. **Session model** — replace the process-global `SessionState` read in tool forwards with an explicit execution-context object passed through delegation (the Phase-5 slice of the 2026-08-26 plan, never done). Until that lands, at minimum:
   - move `is_busy()` + `_runs.insert` under one lock (`runs.py:897,963`);
   - `set_session(None)` in `agent_runner.py:1177` only clears the session if the current session's `run_id` matches the finishing run;
   - `set_auto_approve` on the outer `run_id` must not match a child session with `run_id=None` (`session.py:225-230`) — require an exact `run_id` match unless the caller is the CLI's own process.
2. **Host validation** — add `TrustedHostMiddleware` with `allowed_hosts=["127.0.0.1", "localhost", "[::1]"]` in `create_app`. Test: a request with `Host: evil.example` → 400. This narrows the DNS-rebinding hole; the no-CSRF posture stays documented.
3. **stop()** — `runs.py:1090-1095`: resolve any pending approval/diff decision as "denied (run stopped)" so a run awaiting approval cannot hang past its timeout.
4. **Run retention** — evict terminal runs older than a configurable TTL (default e.g. 7 days) from `_runs` (`runs.py:672`); zero `api_key_value` after the run reads it (`runs.py:223`, `agent_runner.py:889-894`).
5. **Graceful drain** — on shutdown, stop accepting new runs, let the active run finish up to a bounded grace period, then stop it and resolve pending decisions (ties into Phase 8's lifespan work).

**Tests:** concurrency test for (1); Host-header test for (2); stop-during-approval test for (3); eviction + key-zeroing test for (4).

**Size:** M (est. 2–3 person-days). **ADR:** 0042.

---

## Phase 8 — Operations & release plumbing

**Objective:** an operator can run smolcode in a container, observe it is healthy, shut it down cleanly, and know its dependencies are not vulnerable.

**Findings addressed:** R6 (scans), ops-medium (host Dockerfile, shutdown/health, digest pins, resource limits, cost defaults, metadata).

**Depends on:** Phase 3 (CI scaffolding); the rest can proceed in parallel with Phases 4–6.

1. **Host Dockerfile** — `smolcode/docker/Dockerfile.host` (or `smolcode/Dockerfile`): non-root user, `smolcode` + `[web]` extra installed from the built wheel (this also exercises R1's fix in production), workspace volume, `HEALTHCHECK` hitting `/api/health`, `STOPSIGNAL SIGTERM`. Document the run-book (mount workspace, set `.env`, loopback publish, LiteLLM compose).
2. **Graceful shutdown** — `web/server.py:113-116`: in the lifespan `finally`, stop the active run, call `agent.cleanup()`, close MCP servers, flush/close the audit sink. Re-enable uvicorn `access_log` (or document why off).
3. **Real health** — `GET /api/health` reports `{status, docker: reachable|unreachable, images: {tier: current|stale|missing}, queue_depth, active_run, queue_drain_error}`; 503 when Docker is unreachable on a docker-executor deployment. The container HEALTHCHECK uses it.
4. **Base image digest pins** — replace `ARG PYTHON_BASE=3.12-bullseye` with `@sha256:…` pins in all three tier Dockerfiles; checksum the gosu download; include the base-image digest in the source-hash label so a base bump triggers a rebuild (closes the Low item).
5. **Resource + cost defaults** — document the defaults; add container `mem_limit`/`cpus`/`pids_limit` in `base.py`; warn at startup when no cost cap is configured; add `max_tokens` to `LiteLLMModel` (a sane per-tier default).
6. **Package metadata** — add `license`, `authors`, `readme`, `urls`, `classifiers` to `pyproject.toml` so a PyPI release is possible. Decide the license with the user (the code has no license file today).
7. **Makefile** — make the targets OS-aware (`.venv/bin` vs `.venv/Scripts`) or document the Windows-only constraint in README; `install.ps1` should not hardcode `py -3.12`; `quality.ps1` should resolve paths from `$PSScriptRoot`.

**Size:** M (est. 2–3 person-days). **ADR:** 0043.

---

## Phase 9 — Documentation alignment & release evidence

**Objective:** no doc claims something a test contradicts; the release is evidenced, not asserted.

**Depends on:** Phases 3–8 (so the claims can cite green gates).

Fix list (from the report's documentation table, each with a verification command):

1. `README.md:41,75,733` + `docs/environment.md:5,32,119,140` — remove the `smol_clone_2` absolute paths; use repo-relative instructions.
2. `README.md:511-513` — correct the coverage-gate location (Makefile + CI job, not pyproject).
3. `README.md:87` and `:25` — iptables/IPv6 are shipped; update the trust-tier table and the status block.
4. `README.md:541` — FastAPI pin is `>=0.115,<0.137` (regression in 0.137+).
5. `README.md:9-26` — rewrite the status block to point at `TASKS.md` §0/§0b rather than asserting per-milestone shipping.
6. `docs/security.md:249-261` — remove the "Forward-looking (M16)" paragraph; `:626` — fix the duplicate `## 9.` heading.
7. `docs/environment.md` — regenerate for the current host/state (date, Python 3.12 canonical path, Docker-optional notes, pnpm workspace note).
8. `TASKS.md:38-40` — correct the "docker-marked tests run in Job B" claim; remove the duplicated "Note on BE failures" block; add §0b (this review's phases).
9. `ci.yml:8-13` header (if not fixed in Phase 3).
10. `docs/reviews/2026-08-27-architecture-vs-claude-md/REPORT.md` §6 — strike the stale "Dockerfiles missing" section or mark it superseded.
11. `smolcode/.env.example` — document every `SMOLCODE_*` var the code reads (~25), grouped; remove the exposed-key reference or mark it rotated.
12. Add a CI grep guard: fail the build if `smol_clone_2`, `NON-BLOCKING`, or `does not build as written` reappear in `README.md`/`ci.yml`/`docs/`.

**Release evidence** — required before tagging v1.0:

- One live end-to-end run recorded: hosted provider, docker executor, restricted tier, a real task producing an artifact on disk, with the audit chain verified (`smolcode audit verify`).
- One elevated-tier run exercising an approval prompt.
- CI green on all jobs (Phases 3–8).
- `docs/reviews/2026-09-24-full-app-review/REVIEW-REPORT.md` updated with a "resolved" column mapping R1–R12 to their fixing commits.

**Size:** M (est. 1.5–2 person-days, mostly mechanical). **ADR:** 0044.

---

## Effort summary

| Phase | Theme | Size | Est. person-days | ADR |
|---|---|---|---|---|
| 3 | Build/install/test isolation + CI visibility | S–M | 1.5–2.5 | 0038 |
| 4 | Backend feature repair (H7/H8/H9) | M | 2–3 | 0039 |
| 5 | Frontend correctness (H10 + medium) | M | 2–3 | 0040 |
| 6 | Tool/MCP hardening + in-container plane (R8–R12) | L | 4–6 | 0041 |
| 7 | Web/session robustness | M | 2–3 | 0042 |
| 8 | Ops & release plumbing | M | 2–3 | 0043 |
| 9 | Docs alignment & release evidence | M | 1.5–2 | 0044 |
| **Total** | | | **15–22.5** | |

These are engineering estimates for a developer familiar with the codebase, excluding review cycles and CI-runner time. Phases 4 and 6 are the critical path for *trust*; Phases 3, 5, 8, 9 are the critical path for *usability and releaseability*.

---

## Release checklist (gate for tagging v1.0)

1. [ ] Wheel installs in a clean venv; `smolcode --print-config` and `images source_hash` work (Phase 3.3).
2. [ ] `pnpm build` green with `strict: true`; `pnpm lint` 0 errors; `pnpm test` and `pnpm test:e2e` green (Phases 3.1, 5).
3. [ ] Full Python suite green on a Docker-less machine; 0 setup errors (Phase 3.2).
4. [ ] CI blocks on: Python lint/format/tests/coverage, tier-image contract, web lint/build/unit/e2e, dependency audit (Phase 3.4, 8.6).
5. [ ] Retry, rerun, export, queue drain, and cost caps proven by endpoint/integration tests against the real manager (Phase 4).
6. [ ] Git tools reject option injection; uploads reject symlinks; MCP env is default-deny; the in-container gate has one tested behavior (Phase 6).
7. [ ] Host validation, session TOCTOU, stop-during-approval, run eviction, key zeroing covered (Phase 7).
8. [ ] Host Dockerfile + run-book; graceful shutdown; real `/api/health`; digest-pinned base images (Phase 8).
9. [ ] Docs list above corrected; CI grep guard in place (Phase 9).
10. [ ] Live end-to-end + elevated-approval runs recorded; audit chain verified; `TASKS.md` updated; branch rebased onto `main`; report marked resolved.

---

## Explicitly deferred (with rationale)

| Item | Why deferred | Revisit when |
|---|---|---|
| Auth / CSRF / non-loopback binding | Threat model accepts loopback-only, no-CSRF for single-user local tool (`architecture.md:732-738`) | A second user or remote bind is requested |
| Process-global `SessionState` full removal | Phase 7 hardens it; full refactor is large | Phase 6's plane decision is made and tested |
| Pin base images by digest | Phase 8 includes it; not a correctness blocker | — |
| `noUncheckedIndexedAccess` | Adopted in Phase 3.1 if error count is manageable | Follow-up |
| Multi-user collab, Monaco, touch DnD, dark mode | Out of product scope for v1.0 | v2 |
