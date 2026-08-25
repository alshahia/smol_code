# Roadmap

**Date:** 2026-06-28
**Author:** initial planning pass
**Status:** active
**Related:** `docs/environment.md`, `docs/architecture.md`, `docs/security.md`

---

## 1. North star

Build a **self-hosted, Docker-sandboxed, multi-tier coding agent** that
feels like Claude Code / OpenCode, runs on the user's machine, calls
hosted LLMs via LiteLLM, and integrates with MCP servers. Each
milestone produces a runnable, tested artifact; the user can stop at
any milestone and have something useful.

The plan follows the project's tiered research discipline
(`AGENTS.md` → `## Agent Workflow`): each milestone ends with a
`make quality` + `make test` green build, a written entry in
`docs/decisions/` if any tier-3 decision was made, and a check-in
with the user before starting the next milestone.

---

## 2. Milestone overview

| # | Name | Goal | Deliverable | Days (est.) |
|---|---|---|---|---|
| **M0** | **Repo + docs** | Establish the project skeleton and planning artifacts | This PR (4 docs + skeleton directories + `.gitignore` + `.env.example`) | 0.5 |
| **M1** | **Tracer bullet** | Restricted-tier agent runs end-to-end against MiniMax (or opencode-go) inside Docker | `smolcode --tier restricted "echo hi"` returns a final answer | 2 |
| **M2** | **Workspace tools** | `fs`, `shell`, `git` tools with `PathPolicy` + command allowlist | `smolcode --tier restricted "add a CLI flag to x.py"` writes a file inside the workspace | 2 |
| **M3** | **MCP integration** | Zero-MCP server default + minimal `mcp_config.json` shape; one optional demo MCP server hooked up | `smolcode --tier restricted "search the docs"` returns docs MCP result | 2 |
| **M4** | **Elevated + full_access tiers** | Two more tiers with network allow-list scaffolding, confirmation prompt, audit log | `smolcode --tier elevated "open a PR"` runs end-to-end with audit entry | 3 |
| **M5** | **Orchestrator + specialists** | `agents/orchestrator.py` with sub-agent tools; one sample specialist agent (e.g. `deploy-staging`) | `smolcode "ship the latest change to staging"` picks the right tier and runs | 3 |
| **M6** | **LiteLLM proxy support** | Optional `SMOLCODE_LITELLM_PROXY` mode + 1h model catalog (lifted from `smolagents-ui`) | `SMOLCODE_LITELLM_PROXY=... smolcode "task"` works | 2 |
| **M7** | **Polish + security review** | Security test suite, audit log retention, docs cleanup | All `make test` green with coverage >80%; security review checklist signed off | 2 |
| **M8** | **GUI viewer + file uploads (v1.2)** | Local web app (FastAPI + uvicorn, loopback only); React SPA (Vite + TS); drag-drop upload zone; CLI `smolcode uploads` + `smolcode web` subcommands | `smolcode web` opens browser to 127.0.0.1:7860; drag-drop a file -> chip appears + persists across reload; restricted tier cannot write to uploads; the bind-to-0.0.0.0 flag is rejected; coverage gate preserved | 5 |
| **M9** | **Live execution (v1.2)** | SSE bridge from agent loop to SPA; tier switcher in header; stop button; mid-run approval modal for destructive ops | `POST /api/runs` returns run_id; `GET /api/runs/{id}/events` streams step events in real time; destructive-op gate posts `approval.requested` and blocks until `POST /api/runs/{id}/approval` resolves; stop flag checked between steps; `full_access` rejected from web (CLI-only) | 4 |
| **M10** | **Inline diff viewer + workspace tree (v1.3)** | `patch_file` tool + per-step diff viewer (write_file/patch_file); per-decision `edited_after`; `GET /api/workspace/tree`; touched-paths highlight in inspector | The diff modal shows before/after with red/green hunks + line stats; user can edit the proposed content before approving; workspace tree highlights files the run has touched; `SMOLCODE_WEB_DIFF_GATE=0` opt-out for CLI parity; diff_decision audit event recorded | 5 |
| **M11** | **Provider / model / API-key selector in the SPA (v1.3)** | Web GUI exposes a provider dropdown + dependent model dropdown + an API-key panel (per-provider, in-browser only). Catalog endpoints read `model_catalog.PROVIDERS`; per-run overrides ride on `Settings.with_overrides` + `build_model(api_key_override=...)`; keys never touch disk (browser localStorage + server in-memory only); the existing 667-test suite stays green | `GET /api/providers` returns the 5 known presets with `key_state`; `GET /api/providers/{id}/models` returns the model list (1h TTL); `POST /api/runs` accepts per-run `provider` / `model` / `keys` overrides; the SPA header replaces the static `provider / model` text with a real selector pair; the inspector pane exposes an `API keys 🔒` collapsible card; `pnpm build` green; full pytest + ruff green; live smoke with a key override completes | 2 |
|   | **M11.1** *(backend)* | `keys.py`, extend `schemas.py` + `api.py` (2 new GET endpoints + extend `POST /api/runs`), wire per-run overrides through `runs.py` + `agent_runner.py`; 6 backend test files | backend ~150 LOC + ~180 LOC of tests; `pytest` PASS | 0.5 |
|   | **M11.2** *(frontend)* | `lib/keysStore.ts`, `ProviderSelector.tsx`, `ApiKeyPanel.tsx`, extend `api.ts` + `App.tsx` + `RunComposer.tsx` + `index.css` | frontend ~420 LOC; `pnpm build` PASS | 1 |
|   | **M11.3** *(polish + regression)* | Full `ruff` + `pnpm build` + `pytest` (coverage ≥ 80 %); live curl smoke against `/api/providers` and `/api/runs` with overrides; GUI manual smoke | verification only | 0.5 |
| **M12** | **SPA UX polish + CLI parity (v1.3)** | 4 small M11.3 follow-ups: visible cache age on the provider selector, last-used selection persists across reloads, two-step confirm before Forget, CLI `smolcode models` parity with the SPA catalog | `GET /api/providers` adds `cached_at` (additive); `smolcode models list \| refresh \| help` subcommand; SPA renders cache-age pill, restores last `(provider, model)` from `localStorage`, asks `Confirm forget?` for 3s before deleting a key; 13 backend tests + 21 SPA smoke cases; full pytest + ruff + `pnpm build` + `pnpm lint` green | 1.5 |
|   | **M12.1** *(backend + CLI)* | `cached_at` field on `ProviderOut` + `_CACHE.fetched_at` plumbing; `_models_main` pre-dispatch + `list`/`refresh`/`help`; 10 CLI cases + 3 web-API cases | backend + CLI ~140 LOC + ~230 LOC of tests; `pytest` PASS | 0.5 |
|   | **M12.2** *(frontend)* | `lastSelection.ts` localStorage CRUD; `ModelAgeBadge` pill; `ApiKeyPanel` two-step confirm; `App.tsx` restore-on-mount; `ProviderSelector` re-list after refresh | frontend ~210 LOC; `pnpm build` PASS | 1 |
|   | **M12.3** *(polish + regression)* | Full `ruff` + `pnpm build` + `pnpm lint` + `pytest` (~750 tests); live `GET /api/providers` + `smolcode models list/refresh` smoke; decision doc + roadmap + README status updates | docs only (4 files) + verification | 0.5 |
| **M12.4** *(addendum)* | `cached_error` follow-up diagnostic field; SPA renders warning glyph + truncated error in cache-age cell; CLI `models list` does the same | `/api/providers` adds `cached_error`; SPA badge gains tooltip + warning chip; 7 backend + 0 frontend tests; full `ruff` + `pnpm build` + `pytest` PASS | 0.5 |
| **M12.5** *(addendum)* | `smolcode models doctor [--no-fetch]` connectivity diagnostic + mobile inspector-pane collapse at `max-width: 900px` + top-level `.gitignore` for workspace hygiene | 3 backend + 0 frontend tests; `pytest` PASS; doc 0015 §11/§12 + m12-spa-ux-polish §11 | 0.5 |
| **M13** | **Audit integrity + redact expansion + audit reader CLI (v1.4)** — closes 3 v1.1 followups (hash-chained audit log, audit `{ls,grep,verify}` CLI, additional redact patterns) | `AuditSink` gains SHA-256 chain + `verify_chain` reader + `SMOLCODE_AUDIT_HASH_CHAIN` opt-out; `smolcode audit ls | grep | verify | help`; `DEFAULT_PATTERNS` expands 4→9 prefixes (Google/AWS/GitHub-OAuth/User/Server); security.md §8/§9 updated; decision 0016; ~32 new tests | 1.5 |
|   | **M13.1** *(hash chain)* | SHA-256 prev_hash + entry_hash on every line; `verify_chain(path)` reader; pre-M13 logs reported as "PARTIAL" (backwards compatible); `AuditSink(hash_chain=...)` kwarg + `SMOLCODE_AUDIT_HASH_CHAIN` env opt-out | backend ~180 LOC + 16 tests; `pytest` PASS | 0.5 |
|   | **M13.2** *(audit reader CLI)* | `smolcode audit {ls, grep, verify, help}`; `grep` output routed through `RedactSecretsFilter`; exit codes 0/1/2/3 for clean/found/tamper/usage/log-missing | backend ~120 LOC + 22 tests; CLI smoke PASS | 0.5 |
|   | **M13.3** *(redact + docs)* | `DEFAULT_PATTERNS` adds `gho_`/`ghu_`/`ghs_`/`AIza`/`AKIA` (9 total); security.md §8 + §9 updated; `0016-m13-decision.md` + roadmap + README | backend ~60 LOC + 9 redact tests + docs | 0.5 |
| **M14** ✅ | **Audit log operational hardening** (v1.5) — close the operator-UX loop on the M13 audit surface: real `/api/audit` + SPA "Recent audit" panel; `smolcode audit rotate [--dry-run] [--keep-days N]` with pre-rotation `verify_chain` gate (refuses broken chains, exit 4); `audit grep --patterns` regex mode | `audit.py` adds `RotateResult` + `rotate_audit_log()`; new `audit_reader.py` (sibling of `audit.py`) backs `/api/audit`; new `web/src/components/AuditPanel.tsx`; `cli.py` adds 2 verbs; `audit grep --patterns` flag; docs `audit-log-retention.md` + security §9 update; 23 new tests; decision 0018 | 1.5 |
| **M15** ✅ | **CLI extraction + small UX polish** (v1.6) — `cli.py` 1172 → 449 via new `_cli_subcommands.py` (re-export shim preserves test imports); `redact.redact_string` promoted from `_redact_string` (default-patterns fallback); `useMediaQuery` hook drives the inspector breakpoint (replaces CSS `@media`) | pure refactor + 2 deferred items; 2 new redact tests; ~830 → 832 pytest; 4 oxlint warnings preserved; decision 0019 | 1.0 |
| **M16** ✅ | **iptables enforcement for elevated tier** (v1.7) — kernel-level network egress filter for the elevated container. New `docker/iptables-init.sh` ENTRYPOINT applies default-deny OUTPUT + ACCEPT per CIDR in `tier.network_allowlist` (CIDR-only schema; v1.0 hostname semantics dropped because no consumer existed); loopback + Docker DNS always open; ESTABLISHED/RELATED for return traffic. Image installs `iptables`, `iproute2`, `gosu` (static binary from GitHub release v1.17); ENTRYPOINT runs as root for firewall setup then `gosu 1000:1000 "$@"` drops to smolagent. `agents/base.py:_executor_kwargs_for` adds `cap_add=["NET_ADMIN"]` + `environment={ELEVATED_NET_ALLOWLIST, ELEVATED_DISABLE_IPTABLES}` for the elevated tier only. New `container.py` module: `parse_cidr_allowlist` / `format_cidr_allowlist` / `elevated_container_env` (fail-closed ConfigError on first malformed CIDR); `is_iptables_kill_switch_active` helper. Kill switch `ELEVATED_DISABLE_IPTABLES=1` documented in security.md §9 as a security-sensitive escape hatch. IPv4 only in v1.7; IPv6 dropped (v1.8 candidate, decision 0021). 832 → 853 pytest (+21 passing, +3 skipped); 4 oxlint warnings preserved; ruff clean; decision 0020 | 2.0 |

**Total estimate through M16:** ~26.5 person-days = ~5.3 person-weeks. (Up from ~22 / 4.5 at the end of M13.)

M0 + M1 is the **only** scope the user explicitly approved in this
brief ("Inspect the repository and environment to build the
claude/opencode-like with smolagents. Do not implement features yet.")
— M2 onwards are proposed for later rounds, gated on user sign-off
after each milestone.

---

## 3. Milestone 0 — repo + docs (this PR)

**Goal:** Establish the project skeleton and the four planning docs.
**No executable code is shipped**; only docs, skeleton directories,
`Makefile` placeholders, `.env.example`, and `.gitignore`.

### Deliverables (this PR)

1. `docs/environment.md` — host state, capabilities, limitations.
2. `docs/architecture.md` — components, layout, contracts.
3. `docs/security.md` — threat model, tier policies, layered controls.
4. `docs/roadmap.md` — this file.
5. `docs/decisions/.gitkeep` (placeholder; no decisions yet).
6. Skeleton `Makefile` with the same targets as `smolagents/Makefile`
   (so the user can `make quality` / `make test` once code lands).
7. `.gitignore` covering `.venv`, `.env`, `__pycache__`,
   `*.pyc`, `dist/`, `build/`, `.pytest_cache`, `.ruff_cache`,
   `logs/audit.jsonl`.
8. `.env.example` with placeholders for the five provider presets.

### Validation

- `make quality` runs (even though it has nothing to lint yet, the
  target must exist and exit 0).
- All four docs render as markdown; cross-references resolve.

### Done when

- PR opened with the 4 docs + skeleton.
- User has reviewed `docs/architecture.md` and approved the
  high-level design (component diagram, tier matrix, project layout).
- User has answered the 5 open questions in `docs/architecture.md`
  §10 (workspace path, first provider, first MCP server, default tier,
  orchestrator scope).

---

## 4. Milestone 1 — tracer bullet (restricted + Docker + one provider)

**Goal:** Prove the end-to-end pipeline with the smallest possible
slice: one tier (restricted), one provider (MiniMax or opencode-go,
whichever the user has a key for), Docker executor, no MCP, no
orchestrator. The CLI runs `agent.run("task")` and prints the
final answer; that's it.

This is the **risk-reduction milestone**. Everything after M1 is
additive.

### 4.1 Sub-tasks (in order)

1. **M1.1 — install.** `uv venv --python 3.12 .venv` + `uv pip install
   -e "./smolagents[litellm,docker,mcp,dev]"` + verify `smolagents`
   is importable from the venv. `make install` target.

2. **M1.2 — config skeleton.** `smolcode/config.py` with `Tier` and
   `Settings` dataclasses + `load_settings()` that reads env vars.
   Defaults from `docs/environment.md` §9. Refuses to start if
   `SMOLCODE_WORKSPACE` is unset AND the default `<repo>/workspace/`
   cannot be created. **3 unit tests** (`test_config.py`).

3. **M1.3 — model factory.** `smolcode/models.py` with the five
   presets from `docs/architecture.md` §5.2. Lifted from
   `smolagents-hybrid-search/src/smolagents_hybrid/providers.py` with
   attribution headers. `build_model(settings)` raises
   `MissingAPIKey` (a structured exception) when the key is unset.
   **5 unit tests** (`test_models.py`) — one per preset, plus
   `MissingAPIKey` test.

4. **M1.4 — Docker image.** `smolcode/docker/restricted.Dockerfile`
   per `docs/architecture.md` §7. Smoke-test build: `docker build -t
   smolcode:restricted .`. The image is also rebuilt by the
   executor on first run (smolagents' `DockerExecutor` builds it
   lazily per `remote_executors.py:595-604`).

5. **M1.5 — agent factory.** `smolcode/agents/base.py` with the
   `make_agent(tier, settings, model_override=None)` function from
   `docs/architecture.md` §5.4. **2 unit tests** (constructor shape,
   `executor_kwargs` propagation).

6. **M1.6 — restricted tier module.** `smolcode/agents/restricted.py`,
   5 lines. **0 dedicated tests** (covered transitively by M1.7).

7. **M1.7 — CLI.** `smolcode/cli.py` + `smolcode/__main__.py`.
   `argparse` with `--tier`, `--provider`, `--model`,
   `--print-config`, `--smoke`. `smolcode --print-config` prints
   the resolved `Settings` as YAML; `smolcode --smoke "task"`
   uses the stub model and asserts `agent.run` returned a
   `final_answer`. **3 unit tests** (`test_cli.py`).

8. **M1.8 — Makefile + scripts.** `make install`, `make quality`,
   `make test`, `make run` (passes args through to the venv
   Python). `scripts/quality.cmd` + `scripts/quality.ps1` for
   Windows users without `make`.

9. **M1.9 — smoke end-to-end.** With Docker running + a real API key:
   `smolcode --print-config` shows the right config;
   `smolcode --tier restricted "what is 2+2?"` returns the answer
   after one step. `make test` is green.

### 4.2 Files created in M1

```
smolcode/
├── Makefile                       (M1.8)
├── .gitignore                     (M0)
├── .env.example                   (M0)
├── scripts/
│   ├── quality.cmd                (M1.8)
│   └── quality.ps1                (M1.8)
└── src/smolcode/
    ├── __init__.py
    ├── __main__.py                (M1.7)
    ├── cli.py                     (M1.7)
    ├── config.py                  (M1.2)
    ├── models.py                  (M1.3)
    ├── agents/
    │   ├── __init__.py
    │   ├── base.py                (M1.5)
    │   └── restricted.py          (M1.6)
    └── docker/
        └── restricted.Dockerfile  (M1.4)
```

### 4.3 Validation

- `uv venv --python 3.12 .venv` (or `py -3.12 -m venv .venv` on
  Windows without `uv`) succeeds.
- `uv pip install -e "./smolagents[litellm,docker,mcp,dev]"` (or
  `py -3.12 -m pip install -e "./smolagents[litellm,docker,mcp,dev]"`)
  succeeds.
- `py -3.12 -m pip show smolagents litellm docker mcp ruff pytest`
  shows all 6 packages installed.
- `ruff check src/` returns 0 errors.
- `ruff format --check src/` returns 0 errors.
- `pytest` passes ≥10 tests (3 config + 5 models + 2 base).
- `smolcode --print-config` (or `python -m smolcode --print-config`)
  prints a YAML config with the resolved workspace, provider, model,
  and tier settings.
- `smolcode --smoke --tier restricted "echo hi"` exits 0 and prints
  `[stub] final answer: hi`.
- (If Docker daemon is up + a real API key is set:)
  `smolcode --tier restricted "what is 2+2?"` returns `4` after
  one LLM round-trip.

### 4.4 Risks

- **~~R-M1.1 (Docker daemon still down).~~** **RESOLVED.** The Docker
  daemon is now running on the host (user started Docker Desktop
  during the planning phase; see `docs/environment.md` §2). M1 uses
  `executor_type="docker"` as the default; the `local` opt-in
  remains in code for portability but is not the M1 default. The
  M1.4 Dockerfile build will run via `docker build` and the
  resulting image will be cached by `DockerExecutor`.
- **R-M1.2 (API key missing).** `smolcode --print-config` works
  without a key. `smolcode --smoke` works without a key. Only a
  real `smolcode "task"` requires a key. The user has indicated
  the env var name (`OPENCODE_GO_APIKEY`); they will populate the
  shell before M1's end-to-end smoke. Failure mode is a clear
  `MissingAPIKey` error pointing at `OPENCODE_GO_APIKEY`.
- **R-M1.3 (Windows path with spaces in editable install).** Per
  `docs/environment.md` §8 R-4. The venv and the `smolagents` path
  are both inside the repo which contains a space. The fix is to
  use **relative paths** in the new `pyproject.toml` (e.g. `smolagents
  = { path = "./smolagents" }` rather than absolute); tested at M1.1.
- **R-M1.2 (API key missing).** `smolcode --print-config` works
  without a key. `smolcode --smoke` works without a key. Only a
  real `smolcode "task"` requires a key, and the failure mode is
  a clear `MissingAPIKey` error pointing at the right env var.
- **R-M1.3 (Windows path with spaces in editable install).** Per
  `docs/environment.md` §8 R-4. The venv and the `smolagents` path
  are both inside the repo which contains a space. The fix is to
  use **relative paths** in the new `pyproject.toml` (e.g. `smolagents
  = { path = "./smolagents" }` rather than absolute); tested at M1.1.


### 4.4.1 Implementation notes (2026-08-19 — post-M1)

All 9 sub-tasks shipped. Test count: **18 passing** (4 config + 8 model +
2 agent + 4 cli) plus a live Docker + opencode-go end-to-end run that
returned `Final answer: 4` for `what is 2+2?`.

Decisions captured during implementation (rationale in
`docs/decisions/0003-m1-implementation.md`):

- **`pyproject.toml` editable dep on `../smolagents`** uses uv's
  `[tool.uv.sources]` table form with `path = "../smolagents"` —
  required for Windows paths with spaces (R-M1.3).
- **`uv venv` does not seed pip**; install command uses `uv pip install
  --python .venv/Scripts/python.exe -e ".[dev]"` directly.
- **`--smoke` overrides `executor` to `local`** so the offline smoke test
  does not trigger a Docker image build (would otherwise slow tests by
  ~30 s and break pytest's tmp_path teardown on Windows).
- **`_StubLiteLLMModel` returns `<code>final_answer("[stub] hi")</code>`**
  — the format CodeAgent's parser expects, so the stub terminates the run
  in step 1 instead of looping on parsing errors.
- **`pytest --basetemp=.pytest_tmp`** is baked into `pyproject.toml`
  `addopts` to work around a Windows-Docker tmpdir cleanup race
  (`PermissionError [WinError 5]` on teardown).
- **`PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`** must be set when running
  with real LLM (Docker) on Windows; rich's progress bars use unicode
  that Windows cp1252/cp1256 cannot encode.
- **`load_dotenv_into_environ` is patched to a no-op in `conftest.py`**
  so tests do not leak the real `OPENCODE_GO_APIKEY` from the parent
  `.env` into the test environment.

Validation summary (per §4.3 acceptance gates):

| Gate | Result |
|---|---|
| `uv venv --python 3.12 .venv` succeeds | PASS |
| `uv pip install -e ".[dev]"` succeeds | PASS (38 packages incl. smolagents 1.27.0.dev0) |
| `ruff check src/` returns 0 errors | PASS |
| `ruff format --check src/` returns 0 errors | PASS (13 files formatted) |
| `pytest` passes ≥10 tests | PASS (18 passing) |
| `smolcode --print-config` prints YAML | PASS (workspace, provider, model, tiers) |
| `smolcode --smoke "echo hi"` exits 0 | PASS (`[stub] hi` in 1 step) |
| Docker + real key end-to-end | PASS (`Final answer: 4` for `what is 2+2?`) |

### 4.5 Done when

- `make quality` is green.
- `make test` is green (≥10 tests passing).
- `smolcode --print-config` shows the right config.
- `smolcode --smoke "task"` returns a deterministic stub answer.
- (If Docker + key available:) `smolcode --tier restricted "task"`
  returns a real LLM answer from inside Docker.
- The user signs off on M1 and answers the open question for M2 (see
  §5).

---

## 5. Milestone 2 — Workspace tools (fs / shell / git)

**Goal:** Wire up `read_file`, `write_file`, `list_dir`, `run` and the
git wrappers to the restricted tier so the model can actually
mutate the workspace. Everything still runs inside the existing
Docker image from M1.

### 5.1 Sub-tasks (in order)

1. **M2.1 — `tools/policy.py` (host-side).** `PathPolicy` and
   `CommandPolicy` dataclasses that wrap the allowlist / path
   validation logic. Used by tests and by `tools/__init__.py` to
   decide which tools to attach to which tier. (Pure Python; no
   smolagents coupling.)
2. **M2.2 — `tools/fs.py`.** Three `Tool` subclasses
   (`_ReadFileTool`, `_WriteFileTool`, `_ListDirTool`). Each one
   inlines the path-policy check (`realpath` + `commonpath` +
   `normcase`) and raises `PermissionError` on violation. Each
   `__init__` is no-arg; workspace is a class attribute.
3. **M2.3 — `tools/shell.py`.** One `Tool` subclass (`_RunTool`)
   wrapping `subprocess.run(shell=False, check=False)`. Command
   basename + Windows `.exe/.bat/.cmd/.com` suffix strip is inlined.
   Allowlist is a class attribute (pipe-separated string).
4. **M2.4 — `tools/git.py`.** Nine thin wrappers (`git_status`,
   `git_diff`, `git_add`, `git_commit`, `git_log`, `git_push`,
   `git_clone`, `git_fetch`, `git_checkout`) following the same
   pattern as `shell.run`. Higher-risk operations (`reset --hard`,
   `push --force`, `rebase`) are **not** exposed — the agent has
   to use `run` and accept the allowlist.
5. **M2.5 — `tools/_bind.py`.** `bind_attrs(base_cls, attrs)`
   helper that returns a per-build subclass with the attrs merged
   in plus `__source__` set so `validate_tool_attributes` works.
   This is the *only* way to carry per-build state across the
   Docker serialisation round-trip — see
   `docs/decisions/0004-m2-workspace-tools.md` for the full
   rationale.
6. **M2.6 — `agents/base.py` workspace remap.** For docker
   execution, return `/workspace` as the tool workspace path
   (bind-mounted to `<settings.workspace>` on the host). For local
   execution, return the host path. Per-executor kwargs: only
   docker gets the `container_run_kwargs.volumes` bind mount.
7. **M2.7 — tests.** 10 fs tests + 8 shell tests + 13 git tests +
   5 build tests + 15 policy tests + 3 smoke tests + 10 new
   bind-roundtrip tests = **64 new tests** (94 total counting M1).
   Every test must use the public `build_*_tools` factory (so we
   exercise the same path the agent does).

### 5.2 Files created in M2

| Path | Purpose |
|---|---|
| `smolcode/src/smolcode/tools/_bind.py` | `bind_attrs(base_cls, attrs)` — per-build subclass factory |
| `smolcode/src/smolcode/tools/fs.py` | `read_file`, `write_file`, `list_dir` |
| `smolcode/src/smolcode/tools/shell.py` | `run(cmd, args, timeout)` |
| `smolcode/src/smolcode/tools/git.py` | 9 git wrappers |
| `smolcode/src/smolcode/tools/policy.py` | host-side `PathPolicy` / `CommandPolicy` |
| `smolcode/src/smolcode/tools/__init__.py` | `build_tools` (composes fs + shell + git) |
| `smolcode/src/smolcode/tests/test_tools_fs.py` | 11 tests |
| `smolcode/src/smolcode/tests/test_tools_shell.py` | 8 tests |
| `smolcode/src/smolcode/tests/test_tools_git.py` | 13 tests |
| `smolcode/src/smolcode/tests/test_tools_build.py` | 5 tests |
| `smolcode/src/smolcode/tests/test_tools_policy.py` | 15 tests |
| `smolcode/src/smolcode/tests/test_bind_roundtrip.py` | 10 tests (new) |

### 5.3 Validation

- All `make quality` / `ruff check` / `ruff format --check` pass.
- All `pytest src/smolcode/tests` pass — **94 tests** total.
- **Round-trip probe:** `instance_to_source` → `exec` on a fresh
  namespace → the resulting instance's `workspace` / `allowlist` /
  `cwd` attributes match the bound values. See
  `tests/test_bind_roundtrip.py`.
- **End-to-end probe (Docker + real key):**
  `smolcode --tier restricted --max-steps 4 'Use the write_file
  tool to create hi.txt containing exactly the text hello-world.
  Then use read_file on hi.txt and report the content verbatim.'`
  returns `Final answer: hello-world` and the file
  `<repo>/workspace/hi.txt` exists on the host with the right
  content.

### 5.4 Risks (and how they were handled)

- **R-M2.1 (HIGH — confirmed during impl):** smolagents' Docker
  serialiser drops `__init__` args because the remote side calls
  the class with no args. **Resolution:** bind state as class
  attributes via `bind_attrs` (D1-D7 in
  `docs/decisions/0004-m2-workspace-tools.md`).
- **R-M2.2 (MEDIUM — confirmed during impl):** Windows 8.3 short
  paths break `commonpath` if the workspace string is not
  realpathed. **Resolution:** `realpath` is applied to the
  workspace string in `tools/fs.py` (and was already applied on the
  host-side `PathPolicy` via `Path(...).resolve()`).
- **R-M2.3 (LOW):** `validate_tool_attributes` rejects list/tuple
  class attributes because `ast.walk` on a list literal yields
  `ast.Load` contexts. **Resolution:** encode collections as
  pipe-separated strings; split inside `forward()`.
- **R-M2.4 (LOW):** Module-level helpers in the same file are not
  visible to `MethodChecker.visit_Name` after serialisation.
  **Resolution:** inline the policy logic in every `forward()`. A
  duplicate module-level helper is kept for host-side unit tests.
- **R-M2.5 (LOW):** `inspect.getsource` fails on dynamically
  created classes. **Resolution:** set `__source__` on the new
  class; `get_source` honours it.

### 5.5 Implementation notes (2026-08-19 — post-M2)

All 7 sub-tasks shipped. Test count: **94 passing** (84 existing
M1+M2 tool tests + 10 new bind-roundtrip tests). Live Docker +
opencode-go end-to-end: `Final answer: hello-world` for
"create hi.txt with hello-world then read it back"; the file
`<repo>/workspace/hi.txt` was created on the host via the
bind-mount.

Decisions captured during implementation (rationale in
`docs/decisions/0004-m2-workspace-tools.md`):

- **`bind_attrs(base_cls, attrs)` generates a per-build subclass**
  with the attrs merged into the class dict and `__source__`
  copied from the base. This is the *only* way to carry state
  across smolagents' Docker serialisation round-trip.
- **Tools raise `PermissionError` (built-in), not `PolicyViolation`**
  because the tool source cannot `from smolcode.tools.policy
  import PolicyViolation` (NameError on the remote).
  `PolicyViolation` is retained for host-side use.
- **Allowlist is a pipe-separated string** (`"python|git|pytest"`)
  because `validate_tool_attributes` rejects list/tuple class
  attributes. `forward()` splits on demand.
- **All policy logic is INLINED in `forward()`** — no module-level
  helpers, no sibling-class method calls. A duplicate of each
  helper exists for host-side tests but is never called from
  `forward()`.
- **`workspace_norm` now goes through `os.path.realpath`** in
  `tools/fs.py` to handle Windows 8.3 short paths.
- **No new secrets, no new dependencies, no security weakening.**
  The path policy and command allowlist are enforced by the same
  primitives M1 set up.

**Security disclosure (2026-08-19):** the value of the
`OPENCODE_GO_APIKEY` env var appears in this session's transcript
because an earlier pre-flight `Select-String` matched against the
full file content. The session now only matches against variable
*names* (regex), never values. The user should consider rotating
the key as a precaution. Going forward, no value-bearing
`Select-String` against `.env` will be run.

Validation summary:

| Gate | Result |
|---|---|
| `ruff check src/` | PASS |
| `ruff format --check src/` | PASS (27 files already formatted) |
| `pytest src/smolcode/tests` | PASS (94 tests) |
| `smolcode --print-config` prints YAML | PASS |
| `smolcode --smoke "echo hi"` exits 0 | PASS (`[stub] hi` in 1 step) |
| Docker + real key, write_file + read_file end-to-end | PASS (`Final answer: hello-world`, file visible on host) |
| Bind-mount round-trip (workspace, allowlist, cwd preserved across `instance_to_source` → remote `exec`) | PASS |

### 5.6 Done when

- `make quality` is green.
- `make test` is green (94 tests passing).
- `smolcode --tier restricted "task that needs fs/git"` runs
  end-to-end inside Docker with the model writing real files into
  `<repo>/workspace/`.
- The user signs off on M2 and answers the open question for M3
  (which MCP server(s) to ship in v1).

---

## 6. Milestones 3-7 (sketch — to be expanded after M2 sign-off)

### M3 — MCP integration (2 d)

- `tools/mcp_tools.py` — wrapper around a hand-rolled sync JSON-RPC 2.0
  stdio client (`tools/_mcp_runtime.py`) with the readonly / readwrite /
  full name-prefix check.
- `mcp_config.json` schema documented; v1 ships with **zero servers**
  and an empty config; an example block in `README.md` shows how to
  add one.
- One demo MCP server (`smolcode/tools/_mcp_demo_server.py` — built on
  mcp 2.0.0 `MCPServer`) wired into the docs corpus.
- **End-to-end:** `smolcode --tier restricted --mcp-config
  tmp_mcp_config.json "search the docs for 'docker executor'"` returns
  a result from the demo MCP server.
- **Open question for user:** which MCP server(s) to ship in v1
  beyond the demo? (Default: none, opt-in via config.)

**Status (2026-08-19): M3 SHIPPED.** See
`docs/decisions/0005-m3-mcp-integration.md` for the design choice
(hand-rolled sync stdio client vs the broken `mcpadapt` 0.1.20 vs the
`fastmcp` 3.x downgrade path). Test count: **139 passing** (94 M1+M2
+ 16 MCP runtime + 29 MCP tools). `ruff check` + `ruff format --check`
green; `smolcode --print-config` + `--smoke "say hi"` + `--smoke
"say hi" --mcp-config <file>` all PASS.

### M4 — Elevated + full_access tiers (3 d)

- `agents/elevated.py` + `agents/full_access.py` with the
  per-tier allowlists from `docs/security.md` §3.
- `docker/elevated.Dockerfile` + `docker/full_access.Dockerfile`.
- `TIERS.elevated.network_allowlist` data structure; iptables
  enforcement deferred to v1.1.
- Per-run confirmation prompt for `full_access`.
- `AuditSink` writing to `logs/audit.jsonl` (append-only).
- `tests/test_audit.py` — verifies `AuditSink` rejects `'w'` mode.
- **End-to-end:** `smolcode --tier elevated "open a PR for the bug
  fix in #42"` writes the audit entry + opens the PR.
- **Open question for user:** is the confirmation prompt a hard
  `y/N` or a configurable timeout?

**Status (2026-08-19): M4 SHIPPED.** See
`docs/decisions/0006-m4-elevated-full-access-tiers.md` for the
design (user chose 30 s hard `y/N` with editable timeout via
`SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S` / `--confirm-timeout`).
Test count: **198 passing** (139 M1-M3 + 19 AuditSink + 15
confirmation + 12 tiers + 13 expanded CLI). `ruff check` + `ruff
format --check` green; `--print-config` shows all three tiers with
`network_allowlist`; `--smoke --tier elevated` runs without prompt;
`--smoke --tier full_access` with timeout=1s + no stdin returns
exit 4; with piped `y` returns exit 0; audit log writes valid JSONL
and refuses to truncate. iptables enforcement for elevated
`network_allowlist` is **deferred to v1.1** (per roadmap section 6).

### M4.x — per-tool destructive-op confirmation + git checkpoint (sub-deliverable of M4)

- `smolcode/destructive.py` — `is_destructive(tool_name, kwargs)`
  heuristic table; `destructive_reason` formatter.
- `smolcode/checkpoint.py` — `create_checkpoint(workspace)` wrapper
  around `git stash push -u -m "smolcode-checkpoint-<ISO8601>-<pid>"`.
- `smolcode/session.py` — module-level `SessionState` registry
  (`set_session`/`current_session`) so tools find the confirm
  callback without importing `cli.py`.
- `smolcode/confirm.py` extended with `prompt_destructive`
  (`[y/N/a(ll)/o(ff)]` prompt) + `resolve_destructive_timeout_s`
  (env: `SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S`).
- `smolcode/cli.py` extended with `--auto-approve-destructive`,
  `--no-checkpoint`, `--destructive-confirm-timeout` flags; checkpoint
  block before agent build; session install/clear in `finally`.
- `smolcode/tools/git.py` + `smolcode/tools/shell.py` — inline
  destructive gate in `git_push` and `run` `forward()`s. Imports
  switched to absolute (`from smolcode.session import current_session`)
  so they survive `instance_to_source`'s hoist into the remote Docker
  container.
- **End-to-end:** `smolcode --tier full_access` with a dirty repo
  creates a stash before the agent runs; every destructive tool call
  inside the agent prompts `y/N/a/o`; `a` flips auto-approve ON for
  the rest of the run; `o` flips it OFF; user can `git stash pop` to
  roll back.
- **Open question for user:** none — M4.x plan was approved
  (option A in the M4.x design proposal).

**Status (2026-08-19): M4.x SHIPPED.** See
`docs/decisions/0007-m4x-per-tool-confirmation-checkpoint.md` for the
design (15 decisions + rejected alternatives + acceptance gates).
Test count: **326 passing** (198 M1-M4 + 81 destructive + 20
checkpoint + 27 new confirm). `ruff check` + `ruff format --check`
green; live `--smoke --tier full_access --confirm-timeout 1
--no-checkpoint` with piped `n` returns exit 4; with piped `y`
returns exit 0; live `create_checkpoint` test against a tmp git
repo creates `stash@{0}` with `1 file(s)` and rolls back cleanly.

### M5 — Orchestrator + specialists (3 d)

- `agents/orchestrator.py` — `CodeAgent` with
  `do_restricted_task`, `do_elevated_task`, `do_full_task`
  tools.
- One sample specialist agent: `deploy-staging` (full_access
  only, declared extra paths in config).
- `tests/test_orchestrator.py` — 8+ tests covering tier
  delegation.
- **End-to-end:** `smolcode --orchestrator "ship the latest change
  to staging"` picks `deploy-staging` and runs it with confirmation.
- **Open question for user:** is the orchestrator always present at
  v1, or added in M5?

**Status (2026-08-19): M5 PLANNED, AWAITING USER SIGN-OFF.**
The M5 design is in `docs/decisions/0008-m5-orchestrator.md`
(Status: PENDING USER SIGN-OFF). One open question (Q-M5.1):
should the orchestrator be the v1 default, or only when
`--orchestrator` is passed? The recommendation is B (opt-in via
`--orchestrator` flag). Implementation does not begin until the user
picks A / B / C and the Status changes to `active`.

The standing rule "Do not begin Milestone 5 until Milestone 4 is
implemented, tested, and documented" is satisfied: M4 (decision 0006)
and M4.x (decision 0007) are both shipped. M5 is unblocked once
Q-M5.1 is resolved.

### M6 — LiteLLM proxy support (2 d)

- `SMOLCODE_LITELLM_PROXY` env var → `LiteLLMModel(api_base=...)`.
- Model catalog (lifted from `smolagents-ui/server/app/services/model_catalog.py`,
  with attribution) with 1h in-memory TTL.
- `/models` HTTP endpoint (only if we ever ship a UI — deferred to
  v1.1 if not).
- **End-to-end:** `SMOLCODE_LITELLM_PROXY=http://localhost:4000
  smolcode "task"` works against the proxy.
- **Open question for user:** ship a `docker-compose.yml` for the
  LiteLLM proxy, or assume the user runs it themselves?

**Status (2026-08-19): M6 SHIPPED.** See
`docs/decisions/0002-litellm-proxy.md` (active) for the design choice
(user chose "ship `docker-compose.litellm.yml` + `litellm_config.yaml`
+ `docs/litellm-proxy.md`" over "assume user runs it themselves").

Deliverables in this commit:

- `smolcode/docker-compose.litellm.yml` runs `ghcr.io/berriai/litellm:main-latest`
  on `127.0.0.1:4000` with `litellm_config.yaml` bind-mounted read-only.
  All five provider presets are wired (opencode-go, MiniMax, openai,
  anthropic, custom); every key is read via `os.environ/<NAME>` from
  env vars forwarded from the host shell.
- `smolcode/litellm_config.yaml` — starter config with `model_list`
  + per-model `model_group_settings` rate limits (`rpm` / `tpm`) +
  `litellm_settings` (`disable_spend_logs`, `stream_timeout: 60`).
- `smolcode/src/smolcode/model_catalog.py` — 5-provider catalog
  (sync `httpx.Client`, lifted from `smolagents-ui` with attribution).
  `fetch_models(provider, keys, refresh=False)` returns
  `{models, cached, fetched_at, error}`; 1-hour in-memory TTL;
  `get_providers(keys)` exposes the per-provider `key_state` + cached
  `model_count`; `clear_cache()` for tests. `custom` provider
  short-circuits with `no_base_url` when `CUSTOM_BASE_URL` is empty.
- `smolcode/src/smolcode/tests/test_model_catalog.py` — **27 tests**
  covering PROVIDERS tuple shape, key_state, no_key guard, TTL
  behavior (hit / miss / refresh), network failure handling, auth
  failure, anthropic hardcoded list, unknown provider, custom base
  URL, clear_cache semantics, and the `_is_api_key_env` helper
  (which recognises both `_API_KEY` and `_APIKEY` suffixes per
  decision 0001's `OPENCODE_GO_APIKEY`).
- `smolcode/docs/litellm-proxy.md` — usage notes: start the proxy,
  point the CLI at it, add a provider, cost control, troubleshooting,
  known limitations.

CLI surface unchanged: `SMOLCODE_LITELLM_PROXY` env var + `--litellm-proxy`
flag were already wired in `config.py:Settings.litellm_proxy` (M1)
and consumed by `models.py:_api_base_for()` to set `LiteLLMModel.api_base`.
M6 adds the proxy itself and the model catalog; nothing in the agent
loop changes.

The `/models` HTTP endpoint is **deferred to v1.1** (no UI in v1).
The catalog is consumed by host-side helpers + tests only.

Validation summary:

| Gate | Result |
|---|---|
| `ruff check src` | PASS |
| `ruff format --check src` | PASS (51 files) |
| `pytest src/smolcode/tests/` | PASS (381 tests; +27 from M6) |
| `smolcode --print-config` (default) | PASS (`litellm_proxy: null`) |
| `SMOLCODE_LITELLM_PROXY=http://localhost:4000 smolcode --print-config` | PASS (`litellm_proxy: http://localhost:4000`) |
| `smolcode --smoke "echo hi"` | PASS (unchanged from M5) |
| `docker compose -f smolcode/docker-compose.litellm.yml config` | valid YAML + valid Compose schema (proxy start deferred — no live test against the proxy image, but the schema validates) |

### M7 — Polish + security review (2 d)

- `tests/test_security.py` — full security test suite (per
  `docs/security.md` §12).
- Audit log retention policy (rotated by external tool; we ship a
  sample `logrotate.conf` snippet).
- Coverage gate at 80% (matching `smolagents-ui/AGENTS.md` PB-11.1).
- Final cross-link sweep across all four docs.
- **End-to-end:** `make ci` (quality + test) is green; security
  review checklist signed off.
- **Open question for user:** who signs off the security review?

**Status (2026-08-19): M7 SHIPPED.** See
`docs/decisions/0009-m7-polish-security-review.md` for the design (RedactSecretsFilter,
audit log retention policy + cross-platform rotation helper, coverage gate at 80%,
security test suite mirroring `docs/security.md` §12). Q9 resolved: user chose option
(a) self-review (see decision 0009 D6). Test count: **449 passing** (381 M1-M6 + 31 redact
+ 26 security + 8 specialists/shell/fs coverage-lift + 3 already-passing). `ruff check` +
`ruff format --check` green; `--cov-fail-under=80` green; `smolcode --print-config` +
`--smoke --tier restricted "echo hi"` PASS; end-to-end redaction test
(`sk-...` -> `[REDACTED:openai]`) PASS; `scripts/rotate_audit_log.py` smoke test
(rotate + compress + delete old) PASS.

### M8 — GUI viewer + file uploads (v1.2, the first GUI)

**Goal:** ship a local web GUI for smolcode that exposes a read-only
viewer (sessions, audit, tier policies, allowlist simulator) plus a
file-upload zone where the user can drop files that the agent then
reads. The full design is in `docs/decisions/0010-gui-design.md`
(status `active` after the user approved it on 2026-08-20). D8
(file uploads) was confirmed with all four (a) defaults: hidden
folder, direct multimodal content, text+docs+images+code allowlist,
cross-session persistent with current-session hint.

**Status (2026-08-20): M8 SHIPPED.** See
`docs/decisions/0011-m8-implementation.md` for the implementation
log. Test count: **542 passing** (449 M1-M7 + 68 uploads + 25 web
backend). `ruff check` + `ruff format --check` green;
`--cov-fail-under=80` green (80.34% actual); `pnpm build` green
(~200 KB JS bundle, ~5 KB CSS); FastAPI TestClient verifies all 12
API routes; SPA mount at / returns the built index.html.

**Sub-deliverables (per 0010 D2 + D8):**

1. `smolcode/src/smolcode/uploads.py` — sanitize, MIME sniff (magic
   bytes + UTF-8 fallback, browser claim IGNORED), is_mime_allowed
   (default allowlist + blocklist for executables and archives),
   UploadsStore (append-only JSONL sidecar, sha256 per file,
   collision suffix), UploadMetadata dataclass.
2. `smolcode/src/smolcode/web/` — FastAPI app factory + uvicorn
   launcher; bind allowlist (`ALLOWED_BIND_HOSTS = ("127.0.0.1",
   "localhost", "::1")`); serves SPA from `smolcode/web/dist/` if
   present; 12 API routes (health, config, tiers, sessions, audit,
   allowlist/check, uploads GET/POST/DELETE, uploads/clean).
3. `smolcode/web/` — Vite + React 19 + TS 6 project. 4 components
   (TierBadge, UploadDropZone, UploadList, AllowlistSimulator) +
   App.tsx (3-pane layout per 0010 D4). Proxy `/api/*` to FastAPI in
   dev mode.
4. `smolcode/cli.py` — two new subcommands: `smolcode uploads
   list|clean [--older-than N] [--yes]|path` and `smolcode web
   [--port N] [--host H] [--no-browser]`. Both pre-dispatched before
   argparse so they don't trip the main parser.
5. `smolcode/src/smolcode/config.py` — `Tier.uploads` slot (defaults
   to "read" / "readwrite" / "readwrite" for the three tiers);
   `Settings.uploads_dir`, `upload_max_bytes`,
   `upload_allowed_mime`; `SMOLCODE_UPLOAD_DIR/MAX_BYTES/ALLOWED_MIME`
   env vars.
6. `smolcode/src/smolcode/tools/fs.py` — `_WriteFileTool` blocks
   writes to the uploads dir for the `restricted` tier. Existing
   tests that pass only `workspace_path` to `build_fs_tools` keep
   working (new attrs default to "").
7. `smolcode/pyproject.toml` — `[web]` extra: FastAPI 0.115-0.140
   (pinned below 0.140 due to a route-registration regression),
   uvicorn[standard], python-multipart.

**Security invariants (M8):**

- Server binds to loopback only; `--host 0.0.0.0` is rejected at the
  CLI dispatcher with exit code 8.
- Magic-byte MIME sniffing ignores the browser-claimed MIME; UTF-8
  decode fallback for plain text; `application/octet-stream` is
  rejected.
- Default allowlist: text/, PDF, DOCX, XLSX, PNG/JPG/GIF/WebP. Always
  blocked: `application/x-msdownload`, archives (.zip/.tar/.gz).
- Path traversal blocked at API layer (forward + back slash rejected)
  and at FastAPI URL routing (returns 400 or 404).
- Restricted tier cannot mutate files under `.smolcode/uploads/`
  via `write_file`; enforced in the tool, not just at the GUI.
- Append-only JSONL sidecar + AuditSink events `upload.add` /
  `upload.delete` for full provenance.

**Acceptance gates:**

| Gate | Result |
|---|---|
| `ruff check src` | All checks passed |
| `ruff format --check src` | 63 files already formatted |
| `pytest` (with coverage gate) | 542 passed in 70s |
| Coverage | 80.34% (gate 80% reached) |
| `pnpm build` | OK (200 KB JS, 5 KB CSS) |
| FastAPI TestClient smoke | All 12 routes return expected shapes |
| SPA mount at / | 200 + HTML + CSS/JS bundle |
| `smolcode web --host 0.0.0.0` | rejected (exit 8) |
| Restricted write to uploads | raises PermissionError |
| Reload after upload | file persists (sidecar + on-disk) |

---

## 7. Cross-cutting concerns

### 7.1 Tests

Each milestone ends with `make test` green. The full test suite
grows roughly:

| Milestone | New tests | Total |
|---|---|---|
| M0 | 0 | 0 |
| M1 | 18 | 18 |
| M2 | 76 | 94 |
| M3 | 45 | 139 |
| M4 | 59 | 198 |
| M4.x | 128 | 326 |
| M5 | 28 | 354 |
| M6 | 27 | 381 |
| M7 | 68 | 449 |
| M8 | 93 | 542 |
| M9 | 54 | 596 |
| M10 | 71 | 667 |
| M11 | 70 | 737 |

Actual M2 count is **64 new tests** (84 total at end of M2;
expected ~15 was a low estimate). The table is a planning aid,
not a contract.

Coverage gate (`--cov-fail-under=80`) lands at M7.

### 7.2 Linting

Ruff with the same config as `smolagents/pyproject.toml` is enforced
from M1 onward (every PR). `make style` auto-fixes.

### 7.3 Docs

Every milestone that introduces a tier-3 decision adds an entry to
`docs/decisions/` (append-only, one Markdown file per decision).
Inline comments reference these docs by filename.

### 7.4 Git

Each milestone is one PR (or one merge commit per milestone if the
user prefers squash-less history). Commit messages follow the
sibling project's convention: `feat(scope): summary` / `fix(scope):
summary` / `docs(scope): summary` / `chore(scope): summary`.

### 7.5 Secrets

API keys are **never** committed. `.env` is gitignored from M0. The
`secrets policy` from `docs/security.md` §8 is enforced from M1
(the `MissingAPIKey` error is the M1 surface; the
`RedactSecretsFilter` for logs lands at M4 when the audit log
appears).

### 7.6 Open questions

### 7.6.1 Resolved (2026-06-28 — see `docs/decisions/0001-initial-setup.md`)

1. Workspace path → `<repo>/workspace/` (default).
2. First provider → `opencode-go` (default) + `MiniMax` (secondary).
3. First MCP server → zero in v1.
4. Default tier → `restricted`; `--tier elevated` / `--tier full_access` overrides.
5. Orchestrator scope → always present.
6. Docker daemon → running (user started Docker Desktop).

These unblock M1.

### 7.6.2 Resolved during planning phase

8. **LiteLLM proxy (M6)** — **RESOLVED.** The user has chosen
   **"ship docker-compose.yml, do not assume user runs it"**.
   See `docs/decisions/0002-litellm-proxy.md` for the full decision
   (rationale, trade-offs, files added at M6: `docker-compose.litellm.yml`,
   `litellm_config.yaml`, `docs/litellm-proxy.md`).

### 7.6.3 Still pending — explained (do **not** block M1-M3)

7. ~~**Per-run confirmation for full_access (M4)** — what is this, and
   why does the choice matter?

   - **What it is.** Every time the user runs `smolcode --tier
     full_access "task"`, the CLI emits an interactive prompt
     `Confirm full-access run? [y/N]` before the agent starts. The
     user has to type `y` and press Enter for the run to proceed.
     This is the **only** friction between "passing a flag" and
     "granting a powerful agent the keys to the kingdom" (per
     `docs/security.md` §10 — prompt injection → privilege escalation
     is the one threat we do not engineer against; the confirmation
     prompt is the human-in-the-loop backstop).

   - **The two design options.**

     a. **Hard `y/N`.** Every full_access run requires an explicit
        `y` keystroke. Default timeout behaviour: if the prompt is
        not answered within **30 seconds**, the run is **cancelled**
        (treated as a deny). This is the safest option — it is
        consistent with the "explicit, audited" trust assumption in
        `docs/security.md` §3.3 and matches what Claude Code does
        for destructive operations.

     b. **Configurable timeout.** The user can set
        `SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S=300` (or any value,
        including 0 to require `y` even for a 0-second wait). Default
        is still 30s. This is more flexible but requires the user to
        understand the trade-off: a long timeout means an unattended
        terminal can grant a full_access run without anyone watching.

   - **Why the choice matters.** A long unattended timeout is
     functionally equivalent to "no confirmation at all" if the
     terminal is left open. A 0 timeout (require `y` even on
     instant-decline) is the most paranoid; a 30s timeout is the
     middle ground. The user has not yet chosen between these.

   - **My recommendation.** Default to **30s hard `y/N`** (option a).
     It matches `docs/security.md` §3.3's "explicit, audited" tier
     and the timeout-as-deny behaviour is consistent with how the
     WebSocket permission prompt in `smolagents-ui` works (300s
     timeout = deny per `smolagents-ui/AGENTS.md` PB-3.8). Add a
     config knob later if the user needs it.

   - **What to do now.** Nothing. M4 implementation begins only after
     M1-M3 are signed off, and this question can be answered any time
     before M4 starts. The CLI will ship with a safe default; changing
     the default later is a one-line config change.


   - **Resolution (2026-08-19).** User chose **30 s hard `y/N` with editable timeout** (`SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S` env var or `--confirm-timeout` CLI flag). Timeout-as-deny semantics. Recorded in `docs/decisions/0006-m4-elevated-full-access-tiers.md` D1.

9. **Security review sign-off (M7)** — what is this, and why does the
   choice matter?

   - **What it is.** M7 is the **polish + security review** milestone
     (per `docs/roadmap.md` §2 + §5). It is the final gate before
     "v1 ships". The "security review sign-off" is the **explicit
     approval** that the security model in `docs/security.md` is
     correct, complete, and acceptable for the user's threat model.
     It is not a code review; it is a **threat-model review**:
     someone who is not the implementer reads `docs/security.md`
     and answers "yes, this is what we intended".

   - **The options for "who signs off".**

     a. **The user themselves** (`ahmad`). Fast, single-person
        sign-off. Acceptable for a personal tool / hobby project.
        Risk: the implementer is also the reviewer, which is the
        classic "fox guarding the henhouse" anti-pattern.

     b. **A trusted peer / colleague** (someone the user nominates).
        A second pair of eyes on the threat model. No code review
        required — just `docs/security.md` + a 30-minute walk-through.
        Best for an internal-tool / small-team deployment.

     c. **A formal security audit** (paid third-party review). Out of
        scope for v1; would cost more than the implementation itself.
        Reserved for a future v2 if the tool is shipped to customers.

     d. **No formal sign-off** — the M7 milestone ends with `make
        ci` green and the user "agrees by using it". This is the
        weakest option; it is the **default** in many hobby projects
        but is **not recommended** for anything beyond personal use.

   - **Why the choice matters.** The user has not stated whether this
     tool is for personal use, team use, or external use. The answer
     determines how much review is appropriate. A personal-use tool
     can sign off themselves; a team tool needs at least option (b).

   - **My recommendation.** Default to **option (a) — the user
     themselves**, with a note in `docs/security.md` §11
     ("What we explicitly do not defend against") reminding the
     reader that the threat model is the implementer's threat model.
     If the user later wants to deploy to a team, M7.5 (a follow-up
     milestone) can re-do the sign-off as option (b).

   - **What to do now.** Nothing. M7 happens last; the answer can be
     decided any time before then. If the user has not chosen by
     M7, the CLI ships with option (a) and a clear note in
     `README.md` that the threat model has been self-reviewed.

---

### 7.6.4 Summary of decision state

| # | Question | State | Doc |
|---|---|---|---|
| 1 | Workspace path | **resolved** | 0001 |
| 2 | First provider | **resolved** | 0001 |
| 3 | First MCP server | **resolved** | 0001 |
| 4 | Default tier | **resolved** | 0001 |
| 5 | Orchestrator scope | **resolved** | 0001 |
| 6 | Docker daemon | **resolved** (running) | env §2 / §6.1 |
| 7 | full_access confirmation (M4) | **resolved** | 0006 |
| 8 | LiteLLM proxy (M6) | **resolved** | 0002 |
| 9 | Security review sign-off (M7) | **resolved** (option a: self-review) | 0009 |
| 10 | Per-build tool state (M2) | **resolved** | 0004 |
| 11 | Per-tool destructive-op gate + git checkpoint (M4.x) | **resolved** | 0007 |
| 12 | Orchestrator scope (M5) — default vs opt-in | **resolved** | 0008 |
| 13 | Per-run provider / model / API-key overrides in the web SPA (M11) | **resolved** (additive; reuse `model_catalog.PROVIDERS` + `build_model(api_key_override=...)` + `Settings.with_overrides`; keys stay in browser localStorage + server in-memory only) | 0014 |

All open questions are now resolved. M7 closed Q9 (option a — self-review); see decision 0009 D6. The
CLI ships with the safe default (self-review). M2's per-build-state
decision (#10) is recorded in 0004 and unblocks M3. M5 (#12) is
resolved (option B = opt-in via `--orchestrator`); M6 (#8) is
resolved per 0002. M11 (#13) is approved per 0014 and broken into
M11.1 / M11.2 / M11.3 sub-milestones.

**All M0-M10 milestones are now SHIPPED.** v1.2 is shipped (M8–M10); v1.3 ships M11 + M12 (both shipped 2026-08-22).

v1.1 followups are listed in `docs/decisions/0009-m7-polish-security-review.md`
(iptables for elevated network allowlist, hash-chained audit log, /models
HTTP endpoint, additional redact patterns).

v1.2 — GUI for the CLI shipped across M8–M10; see
`docs/decisions/0010-gui-design.md` for the design and
`docs/decisions/0011-m8-implementation.md` / `0012-m9-live-execution.md` /
`0013-m10-inline-diff.md` for the per-milestone implementation logs.

v1.3 ships **M11 — provider / model / API-key selector in the SPA** +
**M12 — SPA UX polish + CLI parity**. M11 design in
`docs/decisions/0014-m11-provider-model-key-ui.md` (Status: active,
**shipped 2026-08-22**) and `research_doc/m11-provider-model-key-ui.md`
for the implementation plan. User-facing writeup: `docs/m11-ui.md`.
M12 design in `docs/decisions/0015-m12-spa-ux-polish-cli-parity.md`
(Status: active, **shipped 2026-08-22**); user-facing writeup:
`docs/m12-spa-ux-polish.md`.

### v1.7.1 follow-ups (bugfixes against M16 + the Web UI)

The post-M16 bugfix set closed real runtime issues that surfaced after
the v1.7 (M16) iptables work was already merged. Each is a self-contained
change with its own decision doc + tests.

| # | Decision | Version | Theme | Tests | Doc |
|---|---|---|---|---|---|
| 0021 | Sandbox-import error path (prompt-only fix) | v1.7.1 | Inject a tier-aware `instructions=` system-prompt block telling the model that `smolcode` is host-side and cannot be `import`-ed; the runtime layer-B guard (0023) is the actual fix. | — | `docs/decisions/0021-bugfix-sandbox-import-error.md` |
| 0022 | Run cleanup on exit | v1.7.1 | `agent.cleanup()` ALWAYS runs in `run_in_thread`'s `finally` block; `auto_remove=True` alone is not enough (the container survives when the connection drops). Prevents the user's `Bind for 127.0.0.1:8888 failed: port is already allocated` failure. | +6 in `tests/test_agent_runner.py::TestRunInThreadDockerCleanup` | `docs/decisions/0022-bugfix-run-cleanup-on-exit.md` |
| 0023 | Runtime sandbox-boundary guard (Layer A + Layer B) | v1.7.1.2 | Two-layer interception. **Layer A** wraps `agent.python_executor` with `GuardedExecutor` (AST scan + regex for `!pip install smolcode`); raises `SandboxBoundaryViolation` before bad code reaches the kernel. **Layer B** intercepts smolagents' `send_tools` flow (which runs *before* the first model step and bypasses `__call__`): `install_packages` filters host-only packages, `run_code_raise_errors` strips host-only lines, `send_tools` monkey-patches the inner executor with routing lambdas whose default-arg closure captures the ORIGINAL bound methods (so re-entry via `inner.<name>(...)` cannot happen — the v1.7.1 first cut had an `inner.install_packages = lambda pkgs: self.install_packages(pkgs)` that recursed infinitely). Plus a wall-clock timeout (`SMOLCODE_WEB_RUN_TIMEOUT_S`, default 900s) that calls `agent.cleanup()` on timeout to free `127.0.0.1:8888` even when the Jupyter kernel hangs. | +65 in `tests/test_sandbox_guard.py`, +22 layer-B tests in v1.7.1.2, +3 in `tests/test_agent_runner.py::TestRunInThreadWallClockTimeout` | `docs/decisions/0023-runtime-sandbox-boundary-guard.md` |
| **0024** | **Web UI: traceback capture + UTF-8 stdio + defensive hardening** | **v1.7.1.3** | **Three connected fixes. (1) Full traceback capture in `agent_runner.run_in_thread`'s broad except — appends `traceback.format_exc()` to `run.error` (capped at 8 KB) AND includes it in `EVT_ERROR.traceback` so the SPA can render it. (2) Defensive wrappers: `step_callbacks.register(ActionStep, ...)` (the only register call NOT previously in try/except) + `pool.submit(agent.run, ...)` both now log-and-continue on failure. (3) New `_unicode_env.py::setup_unicode_env()` reconfigures `sys.stdout/stderr/stdin` to UTF-8 with `errors="replace"` and exports `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`; called from `smolcode/__init__.py` at package import time, BEFORE any submodule imports smolagents, so by the time smolagents constructs its Rich Console `sys.stdout.encoding` is already UTF-8. Fixes the `UnicodeEncodeError: 'charmap' codec can't encode...` raised by smolagents' `StepLogger.log -> Rich console.print -> legacy_windows_render` path when encoding pip's emoji/box-drawing output through the Windows `cp1252/cp1256` codec.** Live end-to-end validated: Web UI run of "create a simple todo app" with `deepseek-v4-flash` now completes in 114.28s with `status=done`. | **+5 in `tests/test_agent_runner.py::TestRunInThreadErrorTraceback`, +6 in new `tests/test_unicode_env.py`** | **`docs/decisions/0024-web-ui-traceback-and-utf8.md`** |

**Test count progression:** 853 (post-M16) → 968+3 (v1.7.1.2 with layer-B) → 979+3 (v1.7.1.3) → **~990+3 (v1.8 Phase 0)** (sub-agent events + token aggregation + countdown) → **~1026+3 (v1.8 Phase 1)** (+54 new tests across `test_config`/`test_sessions`/`test_web_sessions_api`/`test_web_projects_api`) → **~1026+3 (v1.8 Phase 2)** (+47 new tests across `test_pause_resume`/`test_mentions`/`test_queue`/`test_file_read`) → **~1056+3 (v1.8 Phase 3, BE)** (+30 new BE tests across `test_dashboard`/`test_cost`/`test_retry_rerun_export`) + **55 Vitest** (Dashboard + CostBadge + SubAgentList + keyboard) → **+22 v1.9.x Vitest** (RunHistory filters + AutoApproveBanner + RunActions + ApprovalModal.onAutoApproveToggle) + Playwright e2e smoke (3 tests, 2 pass + 1 skipped) = **TOTAL: 1109 BE tests + 55 Vitest + 3 Playwright**.

### v1.8 — Web UI evolution (decision 0025)

After v1.7.1.3 the user asked for a critical review of the Web UI/UX.
`docs/decisions/0025-web-ui-ux-review-and-roadmap.md` captures:

- Honest evaluation of 6 user suggestions (steps/sub-agents, pause/queue,
  sessions, projects, file mentions, token dashboard).
- 12 additional must-haves the reviewer identified (countdown, shortcuts,
  search, rerun, export, a11y, retry, auto-approve banner, tree-refresh,
  inspector lag, model compare, two-runs viewer).
- 9 things deliberately NOT to build now (full Monaco IDE, drag-drop
  reorder, multi-user collab, voice input, dark mode, plugin API,
  usage caps, prompt library, markdown rendering without sanitizer).
- A 4-phase implementation plan with concrete file paths + LOC estimates.

**Status:** **v1.8 + v1.9.x FE wire-up SHIPPED.** Phase 0 = commit `88a20e4`; Phase 1 = `7b33f1d`; Phase 2 = `2f90b50`; Phase 3 = `dcf38cf` (code) + `509288f` (ship docs); v1.9.x FE wire-up = `bec3ce9`. All five are pushed to `origin/main`. v1.8 (decision 0025) is COMPLETE from feature + test + wire-up perspective. Remaining v1.9.x followups tracked in `TASKS.md` §4 (drag-drop queue reorder, per-provider usage caps, per-subagent cost, server-side auto-approve OFF endpoint, full Playwright e2e suite, IPv6 iptables, iptables for restricted tier) + open items (MCP-on-Windows + pyproject/uv.lock + config.py:67 format debt → decision 0026). User approved all 5 open questions (Q1=a Phase 0 first; Q2=a snapshot to disk; Q3=Yes defer drag-drop to v1.9.x; Q4=c Read both; Q5=a hardcoded defaults + override). See `docs/decisions/0025-web-ui-ux-review-and-roadmap.md` §13.1 + §13.2 + §13.3 + §13.4 for the per-phase acceptance gates + §14.x for the per-phase ship reports + §15 for the Phase 3 detailed plan + §12 status history for the v1.9.x-fe-wireup-shipped entry dated 2026-08-25.

**Phased plan (high-level — full detail in 0025 §6):**

| Phase | Theme | Scope | LOC (BE / FE / tests) | Effort |
|---|---|---|---|---|
| **Phase 0** | Quick wins + sub-agent events + token totals | A1 sub-agent events; A6 token totals in Inspector; B1 countdown; B9 inspector lag; B11 tree refresh on diff; + 5 cosmetic fixes | 225 / 275 / 100 | 1-2 d |
| **Phase 1** | Sessions + Projects | A3 sessions (list/create/delete/rename/detail); A4 project switcher + `settings.projects` config; quick win #6 (upload progress) | 310 / 450 / 190 | 3-5 d |
| **Phase 2** | Pause/queue + file previews + file mentions | A2 pause/resume + auto-queue; A4 file preview pane; A5 @-mentions | 270 / 725 / 270 | 5-7 d |
| **Phase 3** | Dashboard + a11y + power features | A6 Dashboard + cost; B2 shortcuts; B3 search; B4 rerun; B5 export; B6 a11y; B7 retry; B10 auto-approve banner | 270 / 585 / 320 | 3-5 d |
| **Total** | | | **1075 / 2035 / 880** | **12-19 d** |

**Scope decisions documented in 0025 §4–§8:**

- **Sub-agent events** (A1 P0) — backend publishes
  `subagent.started` / `subagent.ended` around each inner `agent.run()`;
  SPA renders nested `SubAgentBlock`.
- **Pause/Resume** (A2 P0) — `Run.snapshot` after each step;
  `POST /api/runs/{id}/pause` + `/resume`.
- **Auto-queue** (A2 P1) — while a run is active, new "Run" presses
  enqueue (FIFO). Drag-and-drop reorder DEFERRED to v1.9.x (over-spec
  for v1.7.x maturity).
- **Sessions** (A3 P0) — backend `/api/sessions` already exists but
  SPA does not render it; new `SessionsPane` + project switcher + the
  model change to add `settings.projects`.
- **File mentions** (A5 P0) — `@path` autocomplete + auto-attach file
  content (sandboxed via `resolve_under_workspace`).
- **Token dashboard** (A6 P0) — per-step tokens aggregated server-side
  into `RunSummary.tokens`; Inspector shows totals; cost projection
  ships in Phase 3.

**Critical deferrals (NOT in v1.8):**

- Drag-and-drop queue reorder — auto-queue + cancel covers 95% of use.
- Full Monaco IDE with file write-back — different product.
- Multi-user real-time collaboration — out of scope.
- Voice input — low utility, model-size cost.
- Dark mode — when CSS variables land.
- Plugin/extension API — wait for 3rd-party interest.
- Per-provider usage caps ("stop at $1") — depends on Phase 3 cost
  projection.

**Acceptance for v1.8 (per-phase):** see 0025 §9. Each phase ends with
`make quality` + `make test` + `pnpm build` green; live e2e against
`deepseek-v4-flash`; ≥80% line coverage on new backend code; ≥70% line
coverage on new FE code (Vitest + Testing Library + axe-core).

**Open questions (must be answered by user):** see 0025 §10 — Q1
(which phase to start with; recommend (a) Phase 0), Q2 (snapshot
strategy for pause/resume), Q3 (drag-drop reorder — confirm defer),
Q4 (projects config migration strategy), Q5 (cost rates source).

**Standing rule applies:** no code lands until the user explicitly
approves the plan AND the per-phase scope.

### M8 — GUI viewer + file uploads (the first M of v1.2)

**Status:** PLANNED, APPROVED ON 2026-08-20. See
`docs/decisions/0010-gui-design.md` (status `active`) for the design.
User confirmed all four D8 defaults with option (a) on each.

**Scope** (combined M8 per 0010 D2 endpoints + D8):

1. `smolcode/web/server.py` — FastAPI app + uvicorn launcher, binds
   to `127.0.0.1` only.
2. `smolcode/web/api.py` — read-only endpoints
   (`/api/health`, `/api/config`, `/api/sessions`, `/api/sessions/{id}`,
   `/api/audit`, `/api/allowlist/check`, `/api/tiers`).
3. `smolcode/web/uploads.py` — sanitize, MIME sniff, sidecar, audit
   events (`upload.add/delete/read`).
4. `smolcode/web/dist/` — React SPA (Vite build output) + `src/`.
5. `smolcode/src/smolcode/uploads/__init__.py` — CLI subcommand
   (`uploads list`, `uploads clean`, `uploads path`).
6. `smolcode/cli.py` — new `web` + `uploads` subcommands.
7. `smolcode/src/smolcode/config.py` — `uploads_dir` +
   `SMOLCODE_UPLOAD_*` env vars.
8. `smolcode/src/smolcode/tiers.py` — `uploads = "read"` for
   `restricted`; `write_file` blocked on uploads for restricted.
9. `smolcode/src/smolcode/audit.py` — `upload.add/delete/read` events.
10. `tests/test_web_server.py` + `tests/test_web_api.py` +
    `tests/test_uploads.py`.
11. `pyproject.toml` — `web` extra (FastAPI + uvicorn); npm devDeps.

**Acceptance gates**:

- `ruff check src` PASS
- `ruff format --check src` PASS
- `pytest` PASS (≥449 + new tests)
- Coverage gate (--cov-fail-under=80) PASS
- `smolcode web` opens a browser to `127.0.0.1:7860`; SPA renders
  3-pane layout with tier badge
- `smolcode uploads list` shows empty (or seeded) sidecar
- Drag-drop a file → chip appears, preview loads, sidecar records it
- Reload page → file persists (uploads folder + sidecar intact)
- Delete file → sidecar records `upload.delete`, file removed
- Restricted tier cannot `write_file` to `.smolcode/uploads/`
- `--bind 0.0.0.0` rejected by server (loopback only)

