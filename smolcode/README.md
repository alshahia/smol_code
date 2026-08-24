# smolcode

Local / Docker multi-agent coding assistant built on
[smolagents](https://github.com/huggingface/smolagents). Designed to be a
self-hosted alternative to Claude Code / OpenCode with three trust tiers
(`restricted` / `elevated` / `full_access`) and multi-provider support
via LiteLLM.

> **Status:** **v1.7.1.3 shipped — Decision 0024 (Web UI: traceback capture + UTF-8 stdio + defensive hardening):** the v1.7.1.2 layer-B fix closed the recursion / `ModuleNotFoundError` failure mode, but the Web UI's `/api/runs` POST still surfaced as `OSError: [Errno 22] Invalid argument` in 4.4s with no usable stack — the broad `except Exception` block in `agent_runner.run_in_thread` only stored `type(e).__name__ + ": " + str(e)`. Capturing the full `traceback.format_exc()` revealed the real bug: pip's progress output (emoji + box-drawing chars) is rendered through smolagents' `StepLogger.log -> Rich console.print -> legacy_windows_render` path, which on Windows captures `self.write = sys.stdout.write` at construction time and then tries to encode through the legacy `cp1252` / `cp1256` codec — **UnicodeEncodeError: 'charmap' codec can't encode characters in position N-M**. 0024 ships three connected fixes: (1) the broad except now appends the full traceback to `run.error` (capped at 8 KB) AND includes it in `EVT_ERROR.traceback` so the SPA can render it — the next failure becomes diagnosable from one log line; (2) `step_callbacks.register(ActionStep, ...)` (previously the only register call NOT in try/except) + `pool.submit(agent.run, run.task)` are both wrapped in defensive try/except so any failure logs + continues instead of aborting the run; (3) a new `setup_unicode_env()` helper in `_unicode_env.py` reconfigures `sys.stdout/stderr/stdin` to UTF-8 with `errors="replace"` and sets `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` in os.environ — called from `smolcode/__init__.py` BEFORE any submodule imports smolagents, so by the time smolagents constructs its Rich Console the file is already UTF-8 and `LegacyWindowsTerm` writes through UTF-8. **Live end-to-end validated:** Web UI run of "create a simple todo app" with `deepseek-v4-flash` now completes in **114.28s** with `status=done` and produces `todo_app/todo.py` (add/list/done/delete + JSON persistence). **11 new tests** (5 in `TestRunInThreadErrorTraceback`, 6 in new `test_unicode_env.py`); combined test count: **979 passed + 3 skipped**. Ruff check + format clean. See `../docs/decisions/0024-web-ui-traceback-and-utf8.md`.
>
> **v1.7.1.2 shipped — Back-to-back bugfix on top of 0023:** the original 0023 Layer A intercepted model-emitted code on `GuardedExecutor.__call__`, but smolagents' `send_tools` flow (which runs *before* the first model step) bypassed `__call__` and called `install_packages` + `run_code_raise_errors` directly on the inner executor, letting `import smolcode` (auto-injected by `Tool.to_dict` from `from smolcode.session import ...`) reach the Jupyter kernel. Layer B intercepts those infrastructure paths: `install_packages` filters host-only packages; `run_code_raise_errors` strips host-only lines from tool-def code; `send_tools` monkey-patches `inner.install_packages` / `inner.run_code_raise_errors` with routing lambdas whose default-arg closure captures the ORIGINAL bound methods (so re-entry via `inner.<name>(...)` cannot happen — the v1.7.1 first cut had an `inner.install_packages = lambda pkgs: self.install_packages(pkgs)` that recursed infinitely). `__getattr__` is plain delegation; never rebind bound methods (breaks `__slots__` against `self.static_tools = {...}`). Backed by 22 new layer-B unit tests; combined v1.7.1.2 test count: **968 passed + 3 skipped**. Ruff check + format clean. See `../docs/decisions/0023-runtime-sandbox-boundary-guard.md` §10 for the followup design.
>
> **v1.7 shipped — Milestone 16 (iptables enforcement for elevated tier)** shipped 2026-08-23. M16 closes the v1.1 followup #1 by enforcing the elevated tier's network allowlist **at the kernel level** inside the container (defense-in-depth — even if the agent bypasses our Python-level `safe_shell` allowlist or `LocalPythonExecutor` imports check, packets are dropped at the network stack unless they target an explicitly allowlisted CIDR). The elevated container's `ENTRYPOINT` is now `docker/iptables-init.sh`, which applies default-deny OUTPUT + ACCEPT per CIDR in `tier.network_allowlist` (CIDR-only; loopback + Docker DNS always open). The init script runs as root for the firewall setup then `gosu 1000:1000 "$@"` drops to the smolagent user — so the agent process itself never sees `CAP_NET_ADMIN`. The image installs `iptables`, `iproute2`, and a static `gosu` (v1.17). New `smolcode/container.py` exports `parse_cidr_allowlist` / `format_cidr_allowlist` / `elevated_container_env` (fail-closed ConfigError on the first malformed CIDR) and `is_iptables_kill_switch_active` for the audit-log side. `agents/base.py:_executor_kwargs_for` adds `cap_add=["NET_ADMIN"]` + `environment={ELEVATED_NET_ALLOWLIST, ELEVATED_DISABLE_IPTABLES}` for the elevated tier only. **Schema change:** `Tier.network_allowlist` now means **CIDR strings**, not hostnames (the v1.0 hostname form had no consumers and was never enforced, so this is a clean rename of semantics, not a breaking API change). Kill switch `ELEVATED_DISABLE_IPTABLES=1` is a documented security-sensitive escape hatch (security.md §9.5). **Known limitations:** IPv4 only in v1.7 (IPv6 dropped; v1.8 candidate, decision 0021); per-process `--uid-owner` filtering is a v1.9 candidate. Backed by 21 new unit tests + 4 `@pytest.mark.docker` contract tests (1 + 2 of which skip on hosts without container internet egress — Docker Desktop networking limitation). See `../docs/decisions/0020-m16-iptables-enforcement.md` for the design.
> v1 ships **zero** MCP servers by default; opt in via `--mcp-config path/to/mcp_config.json` or `SMOLCODE_MCP_CONFIG=path`. See `../docs/decisions/0005-m3-mcp-integration.md` for the design (hand-rolled sync JSON-RPC 2.0 client — no new deps, no async). See `../docs/decisions/0006-m4-elevated-full-access-tiers.md` for the M4 tier + confirmation + audit design. See `../docs/decisions/0007-m4x-per-tool-confirmation-checkpoint.md` for the M4.x destructive gate + git checkpoint design. See `../docs/decisions/0014-m11-provider-model-key-ui.md` for the M11 SPA UI design.

### Next milestones (planned — see `../docs/decisions/0017-m14-m15-m16-roadmap.md`)

| # | Name | Theme | Est. days |
|---|---|---|---|
| **M14** ✅ | Audit log operational hardening (v1.5) | `GET /api/audit` becomes real + SPA "Recent audit" panel + `smolcode audit rotate [--dry-run]` (pre-rotation `verify_chain`) + `audit grep --patterns` honors custom regex | 1.5 |
| **M15** ✅ | CLI extraction + UX polish (v1.6) | `cli.py` 1172 → 449 via new `_cli_subcommands.py`; `redact.redact_string` public helper (default-patterns fallback); `useMediaQuery` hook drives the inspector breakpoint (replaces CSS `@media`) | 1.0 |
| **M16** ✅ | iptables enforcement for elevated tier (v1.7) | kernel-level egress firewall inside the elevated container; CIDR-only `network_allowlist`; `docker/iptables-init.sh` ENTRYPOINT + `cap_add=[NET_ADMIN]` + gosu drop; `container.py` helpers; fail-closed ConfigError on bad CIDR | 2.0 |

**Total: ~5 days cumulative.** Detailed scope for each milestone lives in its own decision doc (`0018` / `0019` / `0020`). M14 + M15 + M16 are the v1.1 followups (closes roadmap item #1 in the v1.1 followup set); future v1.2 candidates include decision 0021 (apply the same iptables init script to the restricted image as defense-in-depth).

## Quick start

```bash
# Windows (from repo root: E:\python projects\smol_clone_2\)
cd smolcode
uv venv --python 3.12 .venv
uv pip install --python .venv\\Scripts\\python.exe -e ".[dev]"

# Print the resolved config (no API key required)
.venv\\Scripts\\python.exe -m smolcode --print-config

# Offline smoke test (no API key, no Docker)
.venv\\Scripts\\python.exe -m smolcode --smoke --tier restricted "echo hi"

# Real run (Docker + opencode-go; needs OPENCODE_GO_APIKEY in ..\\.env)
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
.venv\\Scripts\\python.exe -m smolcode --tier restricted "what is 2+2?"
```

POSIX equivalents use `.venv/bin/python` and `source .venv/bin/activate`.

## Make targets

| Target | Purpose |
|---|---|
| `make install` | Create `.venv` and install `smolcode` + dev deps |
| `make quality` | `ruff check` + `ruff format --check` on `src/` |
| `make style` | Auto-fix lint + format |
| `make test` | Run `pytest` on `src/smolcode/tests/` |
| `make run ARGS=...` | Pass-through to `python -m smolcode` |

If `make` is not installed, the `.cmd` / `.ps1` scripts in `scripts/`
provide the same surface on Windows.

## Environment variables

`smolcode` reads `.env` from the parent directory (`E:\python projects\smol_clone_2\.env`)
automatically. See `.env.example` in this directory for all keys.

The minimum required for M1 is `OPENCODE_GO_APIKEY`. Other providers
(`MINIMAX_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) are wired but
not exercised in M1.

## Trust tiers (M4 status)

| Tier | Status |
|---|---|
| `restricted` | **M4 implemented.** 13 workspace tools (fs + shell + git) + zero MCP servers by default + 12 max steps. Runs in Docker with bind-mounted workspace. `network="none"`. |
| `elevated` | **M4 implemented.** Adds extra imports (os, sys, shutil, hashlib, tempfile, collections, itertools, functools, glob) + extra commands (pip, npm, node, curl, jq, make). `network="restricted"` (data structure; iptables enforcement deferred to v1.1). |
| `full_access` | **M4 implemented.** Widest import + command set (incl. ssh, scp, rsync, docker, kubectl, terraform, ansible, aws, gcloud, az CLIs). `network="open"` with `network_allowlist=("*",)`. **Requires per-run `y/N` confirmation prompt** (30 s hard, configurable via `SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S` or `--confirm-timeout`); denial = exit 4. All runs audited to `<cwd>/logs/audit.jsonl` (append-only JSONL). **M4.x: per-tool destructive-op gate** (every `git_push`, every `run` with destructive cmd/flags gets a `y/N/a/o` prompt). **Git checkpoint** before the run (skip-if-clean/skip-if-not-repo/`--no-checkpoint`). |

> **Sandbox boundary note (decision 0021, v1.7.1):** every sandbox-tier
> CodeAgent now receives a tier-aware **sandbox-boundary instruction**
> via the `instructions=` kwarg (smolagents substitutes it into the
> `{{custom_instructions}}` slot of the default system prompt). The note
> tells the model — explicitly — that `smolcode` is the host-side
> orchestrator and is **not** installed inside the Docker sandbox, so
> it must never write `import smolcode` in a code block. The note also
> lists the tier's allowed imports and commands. The orchestrator tier
> (which runs locally, not in Docker) is exempt. This fixes the
> `ModuleNotFoundError: No module named 'smolcode'` that surfaced when a
> user asked the Web UI to "create a simple todo app". Implementation:
> `agents/prompting.py` (note generator) + `agents/base.py:make_agent`
> (wiring); 19 unit tests in `tests/test_agent_prompting.py`.

> **Docker cleanup on every exit (decision 0022, v1.7.1):** the Web
> UI's `run_in_thread` now calls `agent.cleanup()` in a `finally`
> block, so the sandbox container is removed on **every** exit path
> (success, error, stop, KeyboardInterrupt, hang). Without this, a
> run that hung on a model `!pip install` left a zombie container
> holding `127.0.0.1:8888`, and the next run failed with
> `Bind for 127.0.0.1:8888 failed: port is already allocated`.
> Implementation: `web/agent_runner.py:run_in_thread`; 6 unit tests
> in `tests/test_agent_runner.py::TestRunInThreadDockerCleanup`.

> **Runtime sandbox-boundary guard + hang-aware cleanup (decision 0023,
> v1.7.1):** 0021's prompt-only fix is not enough — the LLM still
> writes `import smolcode` and `!pip install smolcode` despite the
> instruction. 0023 adds **defense-in-depth**:
>
> 1. **`GuardedExecutor` proxy** (`smolcode/sandbox_guard.py`): wraps
>    `agent.python_executor` for every sandbox tier. Pre-scans every
>    code block via `ast.parse` (Python imports) + regex (Jupyter
>    `!pip install …` / `!python -m pip install …` magics) and raises
>    `SandboxBoundaryViolation` (a `RuntimeError` subclass) before
>    the bad code reaches the kernel. smolagents catches the exception
>    and feeds the message back to the model as an observation, so the
>    next step retries without the host-only import.
> 2. **Wall-clock timeout** in `run_in_thread`: runs `agent.run(task)`
>    inside a `ThreadPoolExecutor` with a wall-clock deadline
>    (`SMOLCODE_WEB_RUN_TIMEOUT_S`, default 900 s). On timeout, the
>    existing `finally` block calls `agent.cleanup()` to kill the
>    container, freeing `127.0.0.1:8888` for the next run even when
>    the Jupyter kernel itself is hung (e.g. on `!pip install smolcode`
>    that never resolves).
>
> Together these close both halves of the same failure mode (a model
> that ignores the system prompt AND hangs the kernel). Implementation:
> `sandbox_guard.py` (~250 LOC) + `agents/base.py:make_agent` (1-line
> wrap); 65 unit tests in `tests/test_sandbox_guard.py` + 3 in
> `tests/test_agent_runner.py::TestRunInThreadWallClockTimeout`.

> **Web UI traceback + UTF-8 stdio (decision 0024, v1.7.1.3):** 0023
> closed the recursion / `ModuleNotFoundError` bug but the Web UI
> still surfaced as `OSError: [Errno 22]` in 4.4s with no usable
> stack — the broad `except Exception` block in `agent_runner` only
> stored `type(e).__name__ + ": " + str(e)`. Capturing the full
> `traceback.format_exc()` revealed the real bug was
> `UnicodeEncodeError: 'charmap' codec can't encode...` raised by
> smolagents' `StepLogger.log -> Rich console.print ->
> legacy_windows_render` path when encoding pip's emoji / box-drawing
> output through the Windows `cp1252` / `cp1256` codec. 0024 ships:
>
> 1. **Full traceback capture** in `web/agent_runner.py` — the broad
>    except now appends `traceback.format_exc()` to `run.error`
>    (capped at 8 KB so a runaway traceback doesn't blow up the SSE
>    queue) AND surfaces it in `EVT_ERROR.traceback` so the SPA can
>    render it. Future errors become diagnosable from a single log
>    line.
> 2. **Defensive hardening** of the runner's setup path — the three
>    `step_callbacks.register(...)` calls (ActionStep, PlanningStep,
>    FinalAnswerStep) are now uniformly wrapped in try/except (earlier
>    code only wrapped two of three); `pool.submit(agent.run, ...)` is
>    wrapped in try/except and re-raised as
>    `RuntimeError("agent.run submission failed: ...")`. A worker-thread
>    start failure is now surfaced via the same error path as the inner
>    `agent.run` would have surfaced.
> 3. **UTF-8 stdio via `_unicode_env.py`** — `setup_unicode_env()`
>    reconfigures `sys.stdout / stderr / stdin` to UTF-8 with
>    `errors="replace"` AND sets `PYTHONUTF8=1` +
>    `PYTHONIOENCODING=utf-8` in `os.environ`. Called from
>    `smolcode/__init__.py` at package import time, BEFORE any
>    submodule imports smolagents, so by the time smolagents
>    constructs its Rich Console `sys.stdout.encoding` is already
>    UTF-8 (Rich picks it up via its `encoding` property on the next
>    write call).
>
> Implementation: `web/agent_runner.py` (~30 LOC) + new
> `_unicode_env.py` (75 LOC) + `__init__.py` (3 lines). **11 new
> tests**: `TestRunInThreadErrorTraceback` (5 tests in
> `tests/test_agent_runner.py`) + `TestSetupUnicodeEnv` (6 tests in
> new `tests/test_unicode_env.py`). **Live end-to-end validated** on
> `deepseek-v4-flash`: Web UI run of "create a simple todo app"
> completes in 114.28s with `status=done` and produces
> `todo_app/todo.py` (add/list/done/delete + JSON persistence).

## Workspace tools (M2 + M10)

The `restricted` tier ships 14 tools (M10 added `patch_file`). All
run on the agent host (not inside the Docker code executor); the
Docker executor is only used for model-written code.

| Tool | Args | What it does |
|---|---|---|
| `read_file` | `path` | UTF-8 read of a file under the workspace |
| `write_file` | `path`, `content` | UTF-8 write of a file under the workspace (M10: diff-gated in web view) |
| `patch_file` | `path`, `diff_text` | M10: apply GNU unified-diff to a file under the workspace (atomic write, diff-gated) |
| `list_dir` | `path` | List immediate entries of a directory |
| `run` | `cmd`, `args`, `timeout` | `subprocess.run(shell=False)` of an allowlisted command |
| `git_status` | — | `git status` |
| `git_diff` | `staged`, `extra_args` | `git diff [--staged]` |
| `git_add` | `paths` | `git add <paths>` |
| `git_commit` | `message` | `git commit -m <message>` |
| `git_log` | `max_count` | `git log -n N` (N clamped to 1..1000) |
| `git_push` | `remote`, `branch` | `git push <remote> [<branch>]` |
| `git_clone` | `url`, `directory` | `git clone <url> [<directory>]` |
| `git_fetch` | `remote` | `git fetch <remote>` |
| `git_checkout` | `target`, `create` | `git checkout [-b] <target>` |

Path and command policies are inlined in each tool's `forward()` so
the source is self-contained for smolagents' Docker serialisation.
See `../docs/decisions/0004-m2-workspace-tools.md` for the
serialisation contract. The diff gate (M10) is wired into
`write_file` and `patch_file`; see `../docs/decisions/0013-m10-inline-diff.md`.

## Security notes

See `../docs/security.md` for the full threat model. M1+M2 enforces:

- All model-written code runs in a Docker container (default executor).
- The container runs as a non-root user (`smolagent`, UID 1000).
- The container's `/workspace` is bind-mounted to `<repo>/workspace/`
  on the host so writes via `write_file` are visible outside the
  container and persist across runs.
- `tier.imports` is the only Python stdlib / packages the agent can
  use without a security warning.
- Path policy: every fs tool resolves the target to a real path and
  raises `PermissionError` if it escapes the workspace.
- Command policy: every `run` / git tool checks the basename against
  `tier.commands` and strips Windows `.exe/.bat/.cmd/.com` suffixes.
- The CLI checks for the API key before constructing the agent and
  exits with code 3 + a clear message if the key is missing.

## Architecture

See `../docs/architecture.md`. Project layout follows §4 of that file.

## Implementation notes

`../docs/decisions/0003-m1-implementation.md` captures five decisions
made during M1 (editable smolagents install via `[tool.uv.sources]`,
`--smoke` forcing local executor, stub model reply format, Windows
`--basetemp` workaround, and `PYTHONIOENCODING` requirement for live
Docker runs on Windows).

`../docs/decisions/0004-m2-workspace-tools.md` captures the M2
decision on per-build class-attribute binding (the only way to
carry state across smolagents' Docker serialisation round-trip),
the Windows 8.3 short-path fix, and the choice to raise
`PermissionError` (built-in) from the tool source instead of
importing `PolicyViolation`.

## MCP servers (M3)

v1 ships **zero MCP servers by default** — opt in with either of:

- `--mcp-config <path>` on the CLI, or
- `SMOLCODE_MCP_CONFIG=<path>` in the env.

The config file is JSON with one `servers` array; each entry has a `name`, `transport` (currently only `"stdio"`), a `command` array (executable + args), and a `tools` mode (`"readonly" | "readwrite" | "full"`):

```json
{
  "servers": [
    {
      "name": "docs",
      "transport": "stdio",
      "command": ["<venv>/Scripts/python.exe", "-u", "-m", "smolcode.tools._mcp_demo_server"],
      "tools": "readonly"
    }
  ]
}
```

MCP tools are filtered against the active tier:

- `restricted` accepts only `readonly` servers, and only tools whose name starts with `get_`, `search_`, `read_`, or `list_`.
- `elevated` accepts `readonly` + `readwrite` servers.
- `full_access` accepts all three.

The names `final_answer` and `python_interpreter` are reserved by smolagents; any MCP tool exposing them is rejected at registration. Exposed tool names are prefixed with `<server_name>__` to avoid collisions across servers (e.g. the demo server's `search_docs` becomes `docs__search_docs`).

A bundled demo MCP server is included for offline testing:

```bash
.venv\\Scripts\\python.exe -m smolcode.tools._mcp_demo_server
```

It exposes `search_docs(query)` and `get_doc(key)` over a hard-coded docs corpus. The runtime uses `-u` (unbuffered stdout) so JSON-RPC responses flush immediately into the pipe.

Design rationale + the rejected alternatives (downgrade to `mcp` 1.29 via `fastmcp`, async client + background loop) are in `../docs/decisions/0005-m3-mcp-integration.md`.

## Elevated + Full access tiers (M4)

M4 ships the previously-stubbed `elevated` and `full_access` tiers, with a per-run confirmation prompt + an append-only JSONL audit log for `full_access`.

### Confirmation prompt

Every `--tier full_access` run prints `Confirm full-access run? [y/N]` and waits up to **30 seconds** (configurable) for the user to type `y` or `yes` (case-insensitive). Anything else — empty, `n`, `no`, garbage, EOF, or timeout — cancels the run with exit code 4.

Override the timeout via:

- `--confirm-timeout <seconds>` (CLI flag), or
- `SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S=<seconds>` (env var).

| Value | Behaviour |
|---|---|
| `30` (default) | 30 s hard `y/N` |
| `0` | require `y` even on instant-decline (most paranoid) |
| `300` | 5-minute grace (do not use on shared/automated terminals) |
| unset / non-numeric / negative | clamp to 30 s + safe default |

### Audit log

Every `smolcode` run writes an append-only JSONL entry to one of:

- `--audit-log <path>` (CLI flag), or
- `SMOLCODE_AUDIT_LOG=<path>` (env var), or
- `<cwd>/logs/audit.jsonl` (default; parent dir auto-created).

Each line is a JSON object with at minimum:

```json
{"ts": "2026-08-19T12:34:56Z", "event": "start", "pid": 1234, "tier": "full_access", "task": "...", "model": "deepseek-v4-flash", "provider": "opencode-go", "executor": "docker", "workspace": "..."}
{"ts": "2026-08-19T12:35:01Z", "event": "end",   "pid": 1234, "exit_code": 0, "duration_s": 4.5}
```

Events emitted: `start` (run begin), `step` (each agent reasoning step), `error` (caught exception), `end` (run outcome + duration).

`AuditSink` refuses any mode other than append (`a` / `a+`). Truncating the audit log is impossible by construction; the constructor raises `AuditError` on `mode="w"`.

Skip the audit log with `--no-audit` (not recommended for `full_access`).

### Network allowlist (deferred)

`elevated` and `full_access` ship with a `Tier.network_allowlist` data structure. **iptables enforcement inside the container is deferred to v1.1** (per `docs/roadmap.md` §6). For v1, restricted + elevated containers still run with `network_mode=none`; only `full_access` containers get the default bridge. See `../docs/decisions/0006-m4-elevated-full-access-tiers.md` for the design and the rejected alternatives (always-yes flag, sudo-style password prompt, per-tool confirmation, syslog).

## M4.x: per-tool destructive-op confirmation + git checkpoint

The M4 confirmation prompt gates the *run*; M4.x adds a finer-grained gate inside the run for individual destructive tool calls (so the user doesn't have to babysit a single `y` for an agent that calls `git_push` 20 times). It also snapshots the workspace before any `full_access` run so an accidental `rm -rf` is recoverable.

### What's "destructive" (the heuristic table)

A tool call inside `full_access` is destructive in v1 iff it matches one of:

| Tool | Trigger |
|---|---|
| `git_push` | always |
| `run` with `cmd` ∈ {ssh, scp, rsync, docker, kubectl, terraform, ansible, aws, gcloud, az} | always |
| `run` with `cmd` ∈ {rm, del, rmdir, rd} + recursive/force flag (`-rf`, `-fr`, `-r`, `-f`, `--force`, `--recursive`, `/q`, `/s`, `/f`) OR glob (`*`, `?`) | always |
| `run` with `aws`/`gcloud`/`az` + subcommand ∈ {destroy, delete, rm, drop, terminate} | always |
| `git_reset` / `git_checkout` with `--hard` or `-f` in `extra_args` | always |

NOT destructive (no prompt): `read_file`, `write_file`, `list_dir`, `git_status`/`diff`/`log`/`add`/`commit`/`clone`/`fetch`/`checkout` (without `--hard`), `run` with `python`/`pytest`/`ruff`/`make`/`pip`/`npm`/`node`/`jq`, all MCP tools.

Heuristic philosophy: narrow is safer than wide. False negatives are recoverable (`git stash pop`); false positives are annoying (user types `y` a lot). v1 errs on the side of false positives.

### Per-tool prompt format

```
[DESTRUCTIVE] git_push(remote='origin', branch='main')
Approve? [y/N/a(ll)/o(ff)] (timeout 30s) 
```

| Reply | Effect |
|---|---|
| `y` / `yes` | approve this call, prompt again on next destructive |
| `a` / `all` | approve this call + flip auto-approve ON for the rest of the run |
| `n` / `no` | deny this call, run aborts (exit code 4) |
| `o` / `off` | deny this call + flip auto-approve OFF for the rest of the run |
| empty / EOF / timeout / garbage | deny |

### Auto-approve toggle — three surfaces

The user wanted auto-approve "enable/disable any time". M4.x exposes:

1. **Before the run.** `--auto-approve-destructive` flag or `SMOLCODE_AUTO_APPROVE_DESTRUCTIVE=1` env var.
2. **Mid-run (on).** Type `a` at any prompt.
3. **Mid-run (off).** Type `o` at any prompt (the escape hatch if `a` was typed by accident).

Timeout is 30 s, editable via `--destructive-confirm-timeout <seconds>` or `SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S=<seconds>`. Setting to `0` means "wait forever".

### Git checkpoint before `full_access`

Before any `full_access` run, the CLI captures the working tree:

```
git stash push -u -m "smolcode-checkpoint-<ISO8601>-<pid>"
```

Skip (not an error) when: `--no-checkpoint` flag, workspace path missing, workspace not a git repo, working tree clean. Failed `git stash` returns `status="failed"` with `stderr` captured in the audit log.

The stash ref + file count is printed to stderr so the user can `git stash pop` to roll back, or `git stash drop` to discard.

Decision + rejected alternatives + acceptance gates: `../docs/decisions/0007-m4x-per-tool-confirmation-checkpoint.md`.

## M5: orchestrator + specialists

M5 ships an **opt-in** orchestrator (pass `--orchestrator` to use it). The orchestrator is a `CodeAgent` whose only tools are three delegation tools + one specialist lookup:

| Tool | Delegates to |
|---|---|
| `do_restricted_task(task)` | a fresh `restricted` agent (no network) |
| `do_elevated_task(task)` | a fresh `elevated` agent (limited network) |
| `do_full_task(task)` | a fresh `full_access` agent (confirmation prompt) |
| `do_specialist(name, task)` | a named specialist (bundled or user-installed) |

Default (no flag) keeps the existing `--tier` behaviour — the orchestrator is **never** silently selected.

```bash
# Without --orchestrator: pass-through to --tier restricted / elevated / full_access
smolcode --tier restricted "add a CLI flag to x.py"

# With --orchestrator: orchestrator picks the tier + runs the sub-agent
smolcode --orchestrator "add a CLI flag to x.py"

# Specialists
smolcode --orchestrator "ship the latest change to staging"  # uses bundled deploy_staging
```

Specialists live in `~/.smolcode/specialists.toml` (TOML); each entry declares a tier + the tool names it narrows to. M5 ships one bundled specialist (`deploy_staging`, full_access, tools = `run` + `git_push`) so the orchestrator has a non-trivial specialist out of the box.

Every sub-agent run writes a `subagent` audit event (`status: ok | error`, `tier`, `specialist`, `task`, `answer | error`, `duration_s`). On sub-agent exception, the orchestrator records `status: error` + the exception class name and re-raises; smolagents then swallows the per-step raise so the orchestrator's next model call can emit `final_answer` to terminate cleanly.

When `--orchestrator` is active:

- The per-run `full_access` confirmation prompt is **skipped** (you opted in by passing the flag).
- The pre-run git checkpoint is **skipped** for the same reason.

Decision: `../docs/decisions/0008-m5-orchestrator.md` (opt-in via `--orchestrator`, option B).

## M6: LiteLLM proxy (opt-in)

M6 wires `smolcode` to an optional [LiteLLM proxy](https://docs.litellm.ai/docs/proxy/quick_start) sidecar. The proxy sits between the CLI and the upstream LLM provider, giving you a single place to:

- unify auth (one place to rotate keys),
- cache responses,
- emit per-request spend logs,
- swap providers without editing `smolcode`,
- apply rate limits.

### Start the proxy

```bash
cd smolcode
docker compose -f docker-compose.litellm.yml up -d
# wait ~10 s, then verify:
docker compose -f docker-compose.litellm.yml ps
curl http://127.0.0.1:4000/health/liveliness  # {"status":"healthy"}
```

### Point `smolcode` at it

```bash
set SMOLCODE_LITELLM_PROXY=http://localhost:4000    # Windows
SMOLCODE_LITELLM_PROXY=http://localhost:4000 smolcode --tier restricted "task"   # POSIX

# or inline:
smolcode --litellm-proxy http://localhost:4000 --tier restricted "task"
```

Verify with `smolcode --print-config`: the `litellm_proxy:` field is non-null.

### What's in `litellm_config.yaml`

The starter config declares the **same five provider presets** that `models.py` knows about (`opencode-go`, `MiniMax`, `openai`, `anthropic`, `custom`) — keys are read from env vars via `os.environ/<NAME>`, no secrets in the file. Per-model rate limits (`rpm` / `tpm`) are set under `model_group_settings`; defaults are generous (60 rpm on first-class providers, 20-30 rpm on paid OpenAI/Anthropic). Edit the file to add new providers; restart with `docker compose -f docker-compose.litellm.yml restart litellm`.

### Model catalog (`smolcode.model_catalog`)

A 5-provider catalog (lifted from `smolagents-ui`'s `services/model_catalog.py` with attribution) is now a first-class module. It exposes `fetch_models(provider, keys, refresh=False)` + `get_providers(keys)` + `clear_cache()`. Cache TTL is **1 hour** per provider; auth failures / network errors do not evict good cache entries.

```python
from smolcode.model_catalog import fetch_models, get_providers

# All providers + their key state (no HTTP call).
print(get_providers({"OPENCODE_GO_APIKEY": "..."}))

# Live fetch from opencode-go (1-hour cache).
print(fetch_models("opencode-go", {"OPENCODE_GO_APIKEY": "..."}))
```

The CLI itself does not yet expose a `--list-models` flag; the catalog is consumed by host-side helpers + tests. The `/models` HTTP endpoint is **deferred to v1.1** (no UI in v1).

### Known limitations

- The Compose file binds to `127.0.0.1:4000` only (loopback). Multi-host setups need a reverse proxy + `LITELLM_MASTER_KEY`.
- No TLS termination (plain HTTP). Add Caddy / nginx / Traefik for prod.
- Spend logs default to disabled; flip `disable_spend_logs: false` in `litellm_config.yaml` for cost observability.

Decision + ship notes: `../docs/decisions/0002-litellm-proxy.md`. Usage guide: `docs/litellm-proxy.md`.

## M7: polish + security review

M7 is the final pre-v1 milestone. No new features — just hardening of what M0-M6 shipped.

### Secret redaction in logs

Every `smolcode` run installs a `RedactSecretsFilter` on the logging factory at startup. The filter scrubs `sk-`, `sk-ant-`, `hf_`, and `ghp_` prefixes from every `LogRecord` (message, args, exception text) before the formatter reads it. The redaction marker is `[REDACTED:<class>]` (e.g. `[REDACTED:openai]`, `[REDACTED:anthropic]`) so an operator can confirm a secret was caught without learning the value.

Filter is installed via `smolcode.redact.install_redact_filter()` which wraps the `LogRecord` factory. Idempotent; re-installation is a no-op.

### Audit log retention

`docs/audit-log-retention.md` ships a reference rotation policy:

- 365 days retention for `full_access` (the only tier whose audit log is required by `docs/security.md` §9).
- Daily rotation, gzip compression, date-suffixed filenames (`audit-YYYYMMDD.jsonl.gz`).
- Cross-platform: `logrotate` (Linux), PowerShell scheduled task (Windows), `launchd` (macOS).
- Reference implementation: `scripts/rotate_audit_log.py` (used by the macOS launchd plist; on Linux call this from `/etc/cron.daily/` if you prefer cron over logrotate).

### Coverage gate

`pyproject.toml` enforces `--cov-fail-under=80` in `pytest` `addopts`. The `.coveragerc` excludes `__main__.py` (CLI shim) and `_mcp_demo_server.py` (docs demo) plus `pragma: no cover` / `if TYPE_CHECKING:` blocks. Current total: **80.28%**.

A regression below 80% will fail `pytest` in CI. To add a new module, either ship tests that cover it or add a `pragma: no cover` comment with justification.

### Security test suite

`tests/test_security.py` mirrors `docs/security.md` §12. Each numbered item in that section is covered by at least one test. Where a behaviour is already covered by a module-level test file (`test_audit.py`, `test_redact.py`), the security test re-asserts it so a regression in the module is caught by the security gate.

Run it on its own with: `pytest src/smolcode/tests/test_security.py -v`.

### Security review sign-off (Q9)

The threat model in `../docs/security.md` was **self-reviewed by the user** on 2026-08-19 (option a per `docs/roadmap.md` §7.6.3). No external audit. This is appropriate for personal use and small teams; for production deployment, consider a third-party review (a follow-up `M7.5` milestone can re-do the sign-off as option (b) — trusted peer — or option (c) — formal audit).

Decision + ship notes: `../docs/decisions/0009-m7-polish-security-review.md`.

## M8: GUI viewer + file uploads (v1.2, the first web surface)

M8 ships a local web GUI (decision 0010 + 0011). It binds to
`127.0.0.1` only — never to a public interface — and exposes a
3-pane viewer (Plan / Stream / Inspector) plus a drag-drop upload
zone where the user can drop files that the agent then reads.

### Install the web extras

```bash
# from the repo root (parent of smolcode/)
uv pip install -e "./smolcode[web]"
```

This adds `fastapi` (pinned <0.140 due to a route-registration
regression in 0.141), `uvicorn[standard]`, and `python-multipart`.

### Run the web GUI

```bash
# Terminal 1: FastAPI server (binds to 127.0.0.1:7860)
smolcode web

# Terminal 2 (optional, dev mode): Vite dev server with HMR
cd smolcode/web
pnpm install
pnpm dev   # proxies /api/* to 7860
```

The browser opens automatically (pass `--no-browser` to suppress).
The SPA at `/` shows the 3-pane layout; the API at `/api/*`
is documented by FastAPI at `/docs`.

### CLI: manage uploads

```bash
smolcode uploads path              # print the .smolcode/uploads/ folder
smolcode uploads list              # tab-separated: name/size/mime/tier/ts/original/sha256
smolcode uploads clean             # preview + require --yes (exit 6)
smolcode uploads clean --yes       # actually delete
smolcode uploads clean --older-than 30 --yes   # delete files older than 30 days
```

### How uploads work (M8 D8)

- **Where**: `<workspace>/.smolcode/uploads/` (hidden; agent's normal
  `list_dir` ignores it).
- **What**: any file matching the default MIME allowlist (text,
  docs, images, code). Executables and archives are blocked.
- **Size cap**: 50 MB by default (`SMOLCODE_UPLOAD_MAX_BYTES`).
- **Persistence**: indefinite. The user explicitly required "don't
  lose my files" — there is no TTL, only explicit deletion.
- **Audit**: every add/delete emits an `upload.add` / `upload.delete`
  event in the audit log. The `.uploads.jsonl` sidecar keeps full
  provenance with sha256 per file.

### Tier policy for uploads

| Tier | Read uploads | Modify uploads | Delete uploads |
|---|---|---|---|
| `restricted` | yes | **no** (write_file raises `PermissionError`) | no |
| `elevated` | yes | yes | yes |
| `full_access` | yes | yes | yes |

The restricted-tier block is enforced inside
`smolcode/tools/fs.py::_WriteFileTool.forward()`, not just at the
GUI, so every code path (CLI, web SPA, programmatic) is covered.

### What's NOT in M8 (deferred)

- **M9**: live agent streaming via SSE; tier switcher with
  confirmation modal; stop button.
- **M10**: diff viewer for write_file / patch_file; apply/reject per step.
- **M11**: specialist editor (forms for `specialists.toml`); MCP
  server manager; audit-log reader (CLI `audit ls` / `audit grep`).

The current SPA shows placeholder panes for these so the user can see
where future work will land.

### Security review

The full GUI design (0010) is approved by the user on 2026-08-20
with all four D8 defaults (option a): hidden folder, direct
multimodal content for images, text + docs + images + code MIME
allowlist, persistent cross-session uploads. The server binds to
loopback only — `smolcode web --host 0.0.0.0` is rejected with
exit code 8. No external auth is wired (localhost-only design).

---

## M9: Live Execution via SSE

`smolcode web` (M8) ships a read-only viewer + uploads. M9 turns
the center pane into a **live execution stream** driven by Server-
Sent Events.

### What ships in M9

- `POST /api/runs` — start a new run (returns `run_id`)
- `GET /api/runs/{id}/events` — SSE stream of step events
- `GET /api/runs/{id}` — run summary
- `GET /api/runs` — list recent runs
- `POST /api/runs/{id}/approval` — resolve a pending destructive-op gate
- `POST /api/runs/{id}/stop` — request stop at next step boundary
- SPA components: `EventStream`, `ApprovalModal`, `StopButton`,
  `TierSwitcher`, `RunComposer`, `RunHistory`

### Usage

```bash
# 1. Start the server (binds loopback only).
smolcode web --no-browser
# Open http://127.0.0.1:7860 in your browser.

# 2. In the SPA:
#    - Pick a tier in the header (restricted / elevated / orchestrator).
#    - Type a task in the left pane.
#    - Click "Run". The center pane streams step events in real time.
#    - If a tool call hits the destructive gate, a modal appears.
#      Approve / Deny / Approve-for-rest-of-run.
#    - Click "Stop" any time to halt at the next step boundary.
```

### Tier policy in the web

- The SPA exposes `restricted`, `elevated`, and `orchestrator` in
  the tier switcher.
- `full_access` is **not** available from the web. The CLI remains
  the authoritative path for full_access (it has a real stdin
  prompt). This is decision 0012.

### Threat model

- The server binds to `127.0.0.1:7860` (loopback only). Anything
  else is rejected.
- Approval gates time out at 30 s by default (env:
  `SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S`). Timeout = deny.
- The SPA never holds an API key.
- The audit log records every approval decision and every step.

### CLI surface (unchanged)

`smolcode` still works exactly as before. The web is a new driver
on top of the existing agent + audit + tier policy.

### Followups (M10 / M11 / v1.1)

- M10: inline diff viewer for `write_file` / `patch_file`.
- M11: specialist editor + MCP server manager + `audit ls/grep`.
- v1.1: replay buffer for late SSE subscribers.
- v1.1: PyInstaller single-file bundle with SPA embedded.

See `docs/decisions/0012-m9-live-execution.md` for the full design
and `docs/architecture.md` §13 for the component map.

## M10: Inline Diff Viewer + Workspace Tree (v1.3)

M10 ships the next slice of decision 0010 — every `write_file` and
`patch_file` call now goes through a **diff gate** that publishes
the proposed before/after to the SPA via the `diff.proposed` SSE
event and blocks until the user Approves, Edits + Approves, or
Denies. The SPA also renders a workspace tree in the inspector
pane that highlights files the run has touched.

This introduces **no new execution surface** — the fs tools were
already present, the gate was already plumbed in M9 (decision
0012 §F4). M10 only adds the UX layer + the `patch_file` tool.

### What ships in M10

- **New fs tool: `patch_file(path, diff_text)`.** Applies a GNU
  unified-diff text to a file under the workspace with the same
  path / tier / upload policies as `write_file`. Atomic write
  via `tempfile.mkstemp` + `os.replace`. Custom hunk applier (NOT
  `difflib.restore` — it only accepts `Differ` output, not
  unified-diff text; see `0013` F3 for the gory details).
- **Diff gate on `write_file` and `patch_file`.** Every write
  consults `SessionState.diff_callback`. The callback publishes
  the full payload (`hunks`, `raw_diff`, `stats`, `timeout_s`,
  before/after) to the SPA, blocks on the user decision, and
  returns a `DiffDecision(approved, edited_after=None, reason)`.
  On deny the tool raises `PermissionError`.
- **Per-decision `edited_after`.** The SPA's DiffViewer can be
  flipped into edit mode; the user's rewritten content is sent
  back via `POST /api/runs/{id}/approval` (new optional field)
  and replaces the agent's proposal before the write commits.
  Audit log records `edited=true`.
- **Workspace tree in the inspector.** New `GET /api/workspace/tree`
  endpoint (with `max_entries` 1..20000 and `max_depth` 1..20).
  The SPA polls every 10 s and highlights paths the run has
  touched (yellow background + amber border).
- **Audit event: `diff_decision`.** Records `tool`, `path`,
  `summary`, `approved`, `reason`, `edited`, `run_id` for every
  diff gate decision. Mirrors the M9 `destructive_decision` event
  so the audit viewer (M8) can show both side by side.
- **`SMOLCODE_WEB_DIFF_GATE` env var** (default `1`). Set to `0`
  to disable the gate and get CLI parity (the fs tools write
  directly without consulting the SPA). Matches the M9
  `SMOLCODE_WEB_CONFIRM_GATE` opt-out pattern.

### Usage

The diff gate is automatic once `smolcode web` is running:

```powershell
# Terminal 1: server (binds loopback only).
cd "E:\python projects\smol_clone_2\smolcode"
.\.venv\Scripts\python.exe -m smolcode web
# Open http://127.0.0.1:7860 in your browser.

# Terminal 2 (optional, dev mode with HMR):
pnpm --dir web dev

# In the SPA:
#   - Pick a tier in the header (restricted / elevated).
#   - Type a task that requires file edits (e.g. "add a docstring
#     to src/foo.py").
#   - When the agent invokes write_file / patch_file:
#       - A modal opens with a color-coded unified diff.
#       - Click "Edit proposed content" to rewrite before approving.
#       - Click Approve / Approve-for-rest-of-run / Deny.
#   - The inspector's Workspace section shows the file tree with
#     touched files highlighted.
```

### Threat model (M10)

See `../docs/security.md` §3.6 for the full threat model. Summary:

- The diff gate is the new write-control point. Every write must
  pass through `SessionState.diff_callback` (default ON).
- The user can edit the proposed content (`edited_after`). The
  audit log marks it.
- `auto_approve_now` flips the gate off for the rest of the run;
  it does NOT persist across runs.
- The workspace tree is read-only. No outbound traffic is added.
- Atomic writes mean a partial write never leaves a truncated file
  on disk.
- Tier policy (restricted read-only on uploads) is preserved for
  `patch_file` just like `write_file`.

### CLI parity

The CLI flow (`smolcode run`, `smolcode --tier elevated ...`) is
unchanged. Agents running under the CLI get
`SessionState.diff_callback == None`; the new `patch_file` tool
applies the diff directly without any UI consultation. The
`SMOLCODE_WEB_DIFF_GATE=0` env var gives CLI parity under the web
view (no gate).

### Followups (M11 / v1.1)

- M11: inline preview of MCP tool result payloads.
- M11: specialist editor + MCP server manager + `audit ls/grep`.
- v1.1: side-by-side diff mode.
- v1.1: syntax-highlighted diff (language inferred from file
  extension).
- v1.1: per-file diff policy (e.g. allow `*.md` to skip the gate).
- v1.1: workspace tree cache (re-walk only on mtime change).

See `../docs/decisions/0013-m10-inline-diff.md` for the implementation
log and `../docs/architecture.md` §14 for the component map.

## M11: Provider / model / API-key selector in the SPA (v1.3)

M11 exposes the existing **5-provider catalog** (opencode-go, MiniMax,
openai, anthropic, custom) directly inside the running web GUI. A new
header bar sits above the existing Task / Execution Stream / Inspector
layout with:

- a **provider dropdown** with `🔑 set` / `∅ missing` badges that
  reflect `os.environ` (server-side, never the value);
- a **model input** pre-filled with the provider's `default_model`
  + a manual ↻ refresh button that hits
  `GET /api/providers/{id}/models?refresh=1`;
- an **API-key panel** with three visual states
  (env-set / browser-stored / enter) that persists per-provider keys
  in `localStorage["smolcode.keys.v1"]` (capped at 16 entries × 4 KB).

The run composer passes those three new fields
(`provider`, `model`, `keys`) as **optional** body fields of
`POST /api/runs`. Without them, the run uses `settings.provider` /
`settings.model` exactly as before — fully backwards-compatible.

### Security (decision 0014)

- Keys are sent only in the request body (loopback only; no headers).
- The server stores them only in `Run.api_key_value` for the lifetime
  of one run. Never persisted, never logged, never returned.
- `extract_keys` whitelist: `*_API_KEY` / `*_APIKEY` / `HF_TOKEN`;
  16-entry × 4 KB caps.
- `ProviderOut.key_state` returns only `'set'` / `'missing'`.
- `redact.py` filter scrubs the request body before any log emission.
- `ALLOWED_BIND_HOSTS` unchanged.

### Tests + verification

- +70 tests in 6 new files + 1 extended (`test_web_keys.py`,
  `test_web_providers_api.py`, `test_web_models_api.py`,
  `test_runs_keys.py`, `test_redact_in_runs.py`,
  `TestRunsM11Overrides`). Suite total: **737 passing** in ~102 s.
- `pnpm lint` 0 errors / 4 stylistic warnings.
- `pnpm build` 220 kB JS / 13 kB CSS in 147 ms.
- Live e2e: `POST /api/runs` w/ M11 fields completed a real
  opencode-go run returning the correct answer.

See `../docs/m11-ui.md` for the full user guide and
`../docs/decisions/0014-m11-provider-model-key-ui.md` for the design.

### M13 addendum — audit integrity + redact expansion + audit reader CLI (v1.4)

- **M13.1 — hash-chained audit log.** `AuditSink` adds SHA-256
  `prev_hash` + `entry_hash` fields to every line (default ON;
  `SMOLCODE_AUDIT_HASH_CHAIN=1` to disable). New `verify_chain(path)`
  reader + `VerifyResult` dataclass (`ok`, `bad_line`,
  `first_unverifiable_line`, `malformed_lines`).
- **M13.2 — `smolcode audit` subcommand.** `smolcode audit ls [-n N] [--json]`,
  `smolcode audit grep <pattern> [--no-redact]`, `smolcode audit verify`,
  `smolcode audit help`. `grep` output is routed through
  `RedactSecretsFilter` so secrets read back from the log cannot leak
  to the terminal. Exit codes: 0 = clean / found, 1 = verify-failed
  or grep-no-match, 2 = usage, 3 = log-not-found.
- **M13.3 — `DEFAULT_PATTERNS` 4 → 9 prefixes.** Adds `gho_` (GitHub
  OAuth), `ghu_` (GitHub user), `ghs_` (GitHub server), `AIza*`
  (Google API key), `AKIA*` (AWS access key ID). Existing `sk-` /
  `sk-ant-` / `hf_` / `ghp_` prefixes unchanged. Marker names
  asserted clean by `test_marker_names_do_not_contain_trigger_prefix`
  (regression guard for the original `sk-ant-` "marker doesn't
  re-match `sk-`" bug).

### Tests + verification

- `+32 tests` across 2 new test classes (`TestHashChain`,
  `TestVerifyChain`, `TestComputeEntryHash` in `test_audit.py`;
  `TestHelp`, `TestLs`, `TestGrep`, `TestVerify`,
  `TestFlagAndVerbErrors`, `TestEnvOverride` in `test_cli_audit.py`)
  + 9 new redact tests in `test_redact.py`. Suite total: **792 passing**
  in ~98 s.
- `ruff check src` PASS.
- `ruff format --check src` PASS.
- `pnpm build` and `pnpm lint` unchanged from M12.5 baseline
  (no SPA changes in M13).
- Live e2e: `smolcode audit verify` on a fresh chained log → exit 0
  (`OK: 4 entries verified`); after tampering line 2 → exit 1
  (`FAIL: line 2 ... 1/2 entries verified before the break`).

See `../docs/decisions/0016-m13-audit-integrity-redact-expansion.md`
for the M13 design + risks + v1.1 followup status; `../docs/security.md`
§8 + §9 for the updated secrets policy and audit log contract.
