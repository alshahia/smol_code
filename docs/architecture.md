# Architecture

**Date:** 2026-06-28
**Author:** initial planning pass
**Status:** active
**Related:** `docs/environment.md`, `docs/security.md`, `docs/roadmap.md`

---

## 1. Goals and non-goals

### 1.1 Goals

- **Self-hosted coding agent** that runs on the user's machine (or a server they control), comparable in feel to Claude Code / OpenCode.
- **Hosted LLMs only** — no model weights live on the box. All inference goes through LiteLLM (direct provider, or via a LiteLLM proxy).
- **Docker-sandboxed code execution.** Model-written Python runs in a per-tier Docker container; the host never sees the model's code.
- **Three trust tiers** (restricted / elevated / full_access) with strict default-deny policies on filesystem, network, imports, and shell commands.
- **MCP as the tool integration layer.** Custom Python tools are first-class; MCP servers are added by configuration.
- **Extensible**: new agents, tools, MCP servers, and providers can be added without forking the core.

### 1.2 Non-goals (v1)

- Cloud-hosted SaaS — every component runs locally.
- ~~A web/chat UI~~ — M8 ships a local web GUI (see section 12). It is local-only (binds to 127.0.0.1) and reads the same backend as the CLI. (Was a non-goal for v1; M8 changed this.) `smolagents-ui/` is no longer relevant as a sibling UI.)
- Real-time multi-user collaboration.
- Auto-fine-tuning or RLHF.
- Production-scale orchestration (Kubernetes, service mesh). v1 is a single-host, multi-process CLI.

---

## 2. High-level component diagram

```
+-----------------------------------------------------------------+
|                         USER (terminal)                         |
+-----------------------------+-----------------------------------+
                              | CLI:  smolcode --tier <T> "task"
                              v
+-----------------------------------------------------------------+
|                          cli.py                                |
|   - parses args, picks tier, loads .env, prints help            |
+-------------------+---------------------+-----------------------+
                    |                     |
                    v                     v
+--------------------------+   +---------------------------------+
|       models.py          |   |        config.py                |
|  LiteLLMModel factory    |   |  tier definitions, allow-lists  |
|  (5 provider presets)    |   |  timeouts, workspace root       |
+-----------+--------------+   +---------------+-----------------+
            |                                  |
            +----------------+-----------------+
                             |
                             v
+-----------------------------------------------------------------+
|                     agents/orchestrator.py                     |
|   CodeAgent that holds sub-agent tools:                         |
|     do_restricted_task(task)  -> CodeAgent(restricted)          |
|     do_elevated_task(task)    -> CodeAgent(elevated)            |
|     do_full_task(task)        -> CodeAgent(full_access)         |
+----------------------------+-+--+------------------------------+
                             | |  |
            +----------------+ |  +----------------+
            v                  v                   v
+------------------+  +-------------------+  +-------------------+
| agents/          |  | agents/           |  | agents/           |
|  restricted.py   |  |  elevated.py      |  |  full_access.py   |
|  CodeAgent +     |  |  CodeAgent +      |  |  CodeAgent +      |
|  tier allowlist  |  |  tier allowlist   |  |  tier allowlist   |
+--------+--------+  +---------+---------+  +---------+---------+
         |                    |                      |
         v                    v                      v
+-----------------------------------------------------------------+
|                  CodeAgent (smolagents)                         |
|   - additional_authorized_imports = tier.allowlist              |
|   - max_steps = tier.max_steps                                  |
|   - executor_type = config.executor                             |
|   - executor_kwargs = tier.docker_kwargs                        |
+--------+-----------------------------------------+--------------+
         |                                         |
         v                                         v
+---------------------------+    +---------------------------------+
|     tools/* (registered) |    |     DockerExecutor               |
|   fs.read / fs.write      |    |  jupyter kernel gateway         |
|   shell.run (allowlist)   |    |  in a per-tier container         |
|   git.* (delegates shell) |    |  python:3.12-bullseye + tier pkg |
|   mcp.<server>.* (stdio   |    +----------------+----------------+
|     or streamable-http)   |                     |
+--------+------------------+                     v
         |                            +---------------------+
         +--------------------------->|  sandboxed code     |
                                      |  (model output)     |
                                      +---------------------+
```

---

## 3. Trust tiers (summary; details in `docs/security.md`)

| Tier | Default? | Filesystem | Imports | Shell allowlist | Network | MCP tools |
|---|---|---|---|---|---|---|
| `restricted` | **YES** | workspace root only | `json`, `pathlib`, `ast`, `textwrap`, `re`, `math`, `itertools`, `collections`, `datetime`, `typing` | `python`, `pytest`, `ruff`, `git read-only`, `cat`, `head`, `tail`, `wc` | **none** | read-only MCP servers (docs search) |
| `elevated` | opt-in | workspace + explicitly-allowed extras | restricted ∪ `subprocess` (via `shell.run` only), `tomllib`, `csv`, `io`, `urllib.parse` | restricted ∪ `npm`, `pnpm`, `cargo`, `make`, `git` (full), `curl`, `docker client` | allow-listed hosts (config-driven) | read + write MCP servers (ticketing, CI) |
| `full_access` | explicit, audited | workspace + configured extra paths (per-agent) | elevated ∪ `socket`, `asyncio`, `requests` | elevated ∪ `ssh`, `rsync`, `kubectl` (if installed) | broader, per-config | full MCP server set |

Every tier still runs inside Docker. The differences are **inside** the
container (allowed imports + which packages are installed) and the **host-side
policy** that the `fs`, `shell`, and `git` tools enforce.

---

## 4. Project layout (proposed)

```
smolcode/                              (new sibling of smolagents/)
├── AGENTS.md
├── README.md
├── docs/
│   ├── environment.md                 (this PR)
│   ├── architecture.md                (this file)
│   ├── security.md                    (this PR)
│   ├── roadmap.md                     (this PR)
│   └── decisions/                     (tier-3 ADR-style append-only)
├── pyproject.toml                     (editable dep on ../smolagents)
├── Makefile                           (quality / style / test wrappers)
├── scripts/
│   ├── quality.cmd
│   └── quality.ps1
├── .env.example                       (placeholder keys for all providers)
├── .gitignore
├── src/
│   └── smolcode/
│       ├── __init__.py
│       ├── __main__.py                (python -m smolcode ...)
│       ├── cli.py                     (argparse; tier routing)
│       ├── config.py                  (Tier dataclass, Settings, env loader)
│       ├── models.py                  (LiteLLMModel factory + presets)
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── fs.py                  (read_file, write_file, list_dir)
│       │   ├── shell.py               (run with allowlist)
│       │   ├── git.py                 (delegates to shell)
│       │   └── mcp_tools.py           (MCPClient wrappers per tier)
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py                (shared make_agent factory)
│       │   ├── restricted.py
│       │   ├── elevated.py
│       │   ├── full_access.py
│       │   └── orchestrator.py        (CodeAgent with sub-agent tools)
│       ├── docker/
│       │   ├── restricted.Dockerfile
│       │   ├── elevated.Dockerfile
│       │   └── full_access.Dockerfile
│       └── tests/
│           ├── conftest.py
│           ├── test_config.py
│           ├── test_models.py
│           ├── test_tools_fs.py
│           ├── test_tools_shell.py
│           ├── test_agents_restricted.py
│           └── test_smoke.py          (offline; uses _StubLiteLLMModel)
```

D-1 note: the package is **flat** (matches `smolagents-ui/AGENTS.md` D-1).
No `server/` nesting — `smolcode.cli` is the entry point.

---

## 5. Component contracts

### 5.1 `config.py` — `Settings` + `Tier`

```python
@dataclass(frozen=True)
class Tier:
    name: Literal["restricted", "elevated", "full_access"]
    imports: tuple[str, ...]            # additional_authorized_imports
    commands: tuple[str, ...]           # shell allowlist (basename match)
    paths: tuple[Path, ...]             # fs allowlist (resolved at boot)
    network: Literal["none", "restricted", "open"]
    mcp_servers: tuple[str, ...]        # MCP server names from MCP_CONFIG
    max_steps: int
    timeout_s: float
    docker_image: str                   # tag for this tier's image

@dataclass(frozen=True)
class Settings:
    workspace: Path
    executor: Literal["local", "docker"]
    provider: str                       # "MiniMax" | "opencode-go" | ...
    model: str
    litellm_proxy: str | None
    log_level: str
    tiers: dict[str, Tier]
```

Resolution order: `SMOLCODE_*` env var → `.env` (`python-dotenv` with
`override=False`, so shell wins) → dataclass default. The `workspace`
path is created on first run if it does not exist; the agent refuses to
operate if it cannot be resolved to an absolute path inside the
`workspace` root.

### 5.2 `models.py` — provider presets

Each preset is a `(model_id, api_key_env, api_base_env, default_model,
custom_llm_provider)` tuple. The factory returns a `LiteLLMModel`
configured with those values, raising a structured `MissingAPIKey` error
if the env var is unset. The five v1 presets are:

| Preset id | `api_key_env` | `api_base_env` | Default model | `custom_llm_provider` | Tier |
|---|---|---|---|---|---|
| `opencode-go` **(default)** | `OPENCODE_GO_APIKEY` | `OPENCODE_HOST` (`https://opencode.ai/zen/go/v1`) | `deepseek-v4-flash` | `openai` | first-class |
| `MiniMax` | `MINIMAX_API_KEY` | `MINIMAX_HOST` (`https://api.minimax.io/v1`) | `MiniMax-M3` | `openai` | first-class |
| `openai` | `OPENAI_API_KEY` | unset | `gpt-4o-mini` | unset (litellm native) | secondary |
| `anthropic` | `ANTHROPIC_API_KEY` | unset | `claude-3-5-sonnet-latest` | unset (litellm native) | secondary |
| `custom` | `CUSTOM_API_KEY` (`optional`) | `CUSTOM_BASE_URL` | `custom-model` | `openai` | secondary |

**Default provider / model** (resolved by user, see `docs/decisions/0001-initial-setup.md`): `opencode-go` + `deepseek-v4-flash`. The user wrote: `OPENCODE_GO_APIKEY is the api key for opencode go provider (default bu add minimax support) in .env file, always use deepseek flash v4, model id "deepseek-v4-flash"`.

**Env var naming note:** the API key for the opencode-go preset is
`OPENCODE_GO_APIKEY` (this project), not `OPENCODE_API_KEY` (the
sibling project `smolagents-hybrid-search/.env.example:5`). The user
explicitly chose this name; we will not silently fall back to the
sibling project's name (that would mask config errors). See
`docs/decisions/0001-initial-setup.md` for the rationale.

The first two presets (`opencode-go`, `MiniMax`) are lifted verbatim
from `smolagents-hybrid-search/src/smolagents_hybrid/providers.py:121-151`
and `85-118` respectively, with the attribution header convention
(per `smolagents-ui/AGENTS.md`). The default model for `opencode-go`
is overridden from the sibling's `kimi-k2.7-code` to the user's
`deepseek-v4-flash`.

### 5.3 `tools/fs.py`, `tools/shell.py`, `tools/git.py`, `tools/mcp_tools.py`

All four files share one rule: **no tool mutates state without first
proving it is inside the workspace root**. The enforcement is a single
`PathPolicy` helper:

```python
def resolve_under_workspace(path: str | Path, *, must_exist: bool = False) -> Path:
    p = (Path(path).expanduser().resolve())
    if not p.is_relative_to(settings.workspace):
        raise PolicyViolation(f"{p} is outside workspace {settings.workspace}")
    if must_exist and not p.exists():
        raise PolicyViolation(f"{p} does not exist")
    return p
```

`fs.read_file(path)` / `fs.write_file(path, content)` /
`fs.list_dir(path)` all call `resolve_under_workspace` before doing
any I/O.

`shell.run(cmd, args, *, timeout)` tokenises `cmd` into basename +
argv, looks up the basename in the tier's `commands` allowlist, and
then forwards to `subprocess.run(..., shell=False, check=False,
timeout=timeout, capture_output=True)`. **No `shell=True` ever.** The
allowlist is a tuple of basenames (`"python"`, `"git"`, etc.), not
regexes, to keep matching unambiguous.

`git.*` are thin wrappers around `shell.run` that hard-code the
subcommand (`status`, `diff`, `add`, `commit`, `log`, `push`,
`clone`, `fetch`, `checkout`). Higher-level git operations (e.g.
`rebase -i`) are not exposed as tools; the agent must use the shell
tool directly and accept that it is subject to the allowlist.

`mcp_tools.py` is the only file that talks to `MCPClient`. It loads
the `MCP_CONFIG` JSON at boot, builds a `MCPClient` per server
named in the active tier, and exposes the resulting `Tool` objects.
A read-only MCP server is one whose tools all start with `get_`,
`search_`, `read_`, or `list_` — the wrapper rejects servers that
violate this rule for the restricted tier.

### 5.4 `agents/base.py` — `make_agent`

```python
def make_agent(tier: Tier, settings: Settings, *, model_override: Model | None = None) -> CodeAgent:
    model = model_override or build_model(settings)
    tools = build_tools(tier, settings)   # fs + shell + git + mcp
    return CodeAgent(
        tools=tools,
        model=model,
        max_steps=tier.max_steps,
        additional_authorized_imports=list(tier.imports),
        executor_type=settings.executor,
        executor_kwargs={
            "image_name": tier.docker_image,
            "build_new_image": True,
            "dockerfile_content": DOCKERFILE_CONTENT[tier.name],
            "container_run_kwargs": tier.container_run_kwargs,
        },
    )
```

The factory is the **only** place `CodeAgent` is constructed. The
three tier modules are 5-liners that call `make_agent` with the
matching `Tier` instance.

### 5.5 `agents/orchestrator.py`

The orchestrator is a `CodeAgent` whose tools are `do_restricted_task`,
`do_elevated_task`, and `do_full_task`. Each tool takes a single
`task: str` argument, instantiates the matching tier agent via
`make_agent`, and returns the agent's final answer. The orchestrator
runs at the **restricted** tier (it cannot escalate its own privilege)
unless the user explicitly passes `--tier elevated` to the CLI, in
which case the orchestrator is itself elevated.

The default CLI invocation `smolcode "task"` uses the orchestrator;
the bypass `smolcode --tier restricted "task"` skips the orchestrator
and runs the task directly in the named tier. The orchestrator only
ever exists in the `restricted` or `elevated` tiers — running an
orchestrator at `full_access` is logged at WARNING and refused (the
point of `full_access` is **specialist** agents, not a generic
router with the keys to the kingdom).

---

## 6. MCP integration

MCP servers are described in `mcp_config.json` (path via `MCP_CONFIG`):

```jsonc
{
  "servers": [
    {
      "name": "docs",
      "transport": "streamable-http",
      "url": "http://localhost:8765/mcp",
      "tools": "readonly"
    },
    {
      "name": "tickets",
      "transport": "stdio",
      "command": ["python", "-m", "tickets_mcp"],
      "tools": "readwrite"
    }
  ]
}
```

Each server's `tools` field is one of:

- `"readonly"` — server is exposed only to `restricted` and `elevated` tiers.
- `"readwrite"` — server is exposed only to `elevated` and `full_access` tiers.
- `"full"` — server is exposed only to `full_access` tier.

The `mcp_tools` wrapper rejects any tool whose name does not match
the declared mode for the active tier (regex prefix `^(get|search|read|list)_`
for readonly; any name for readwrite / full). Tool names that try to
shadow built-in tool names (`final_answer`, `python_interpreter`)
are rejected at registration time.

The MCP lifecycle is bound to the orchestrator: `MCPClient` instances
are opened in the `orchestrator.run` context and closed on exit
(`mcp_client.py:128-138`). The orchestrator's tools are evaluated
lazily — a server that fails to start is logged and the affected
tool is omitted, not fatal.

---

## 7. Docker executor

```python
DOCKERFILE_CONTENT: dict[str, str] = {
    "restricted": textwrap.dedent("""\
        FROM python:3.12-bullseye
        RUN pip install --no-cache-dir jupyter_kernel_gateway jupyter_client ipykernel pytest ruff
        RUN useradd -m -u 1000 agent
        USER agent
        WORKDIR /workspace
        EXPOSE 8888
        CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888"]
    """),
    "elevated": textwrap.dedent("""\
        FROM python:3.12-bullseye
        RUN apt-get update && apt-get install -y --no-install-recommends git curl && rm -rf /var/lib/apt/lists/*
        RUN pip install --no-cache-dir jupyter_kernel_gateway jupyter_client ipykernel pytest ruff requests tomli
        RUN useradd -m -u 1000 agent
        USER agent
        WORKDIR /workspace
        EXPOSE 8888
        CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888"]
    """),
    "full_access": textwrap.dedent("""\
        FROM python:3.12-bullseye
        RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client rsync curl && rm -rf /var/lib/apt/lists/*
        RUN pip install --no-cache-dir jupyter_kernel_gateway jupyter_client ipykernel pytest ruff requests tomli
        RUN useradd -m -u 1000 agent
        USER agent
        WORKDIR /workspace
        EXPOSE 8888
        CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888"]
    """),
}
```

The image is built **once per session** (smolagents' `DockerExecutor`
caches by `image_name`) and torn down with the container. The host's
`workspace` is **not** bind-mounted — the agent uploads code via the
Jupyter kernel over the loopback port forward (the default
`DockerExecutor` flow). For Tier 2/3 agents that need persistent
filesystem state across runs (e.g. `git clone` followed by edits), we
will revisit in Milestone 4 with explicit bind-mount + read-only flag.

Per-tier `container_run_kwargs` (passed via `executor_kwargs`)
control the host-side boundaries:

| Tier | `network_mode` | `read_only` | `tmpfs` | `cap_drop` | `pids_limit` |
|---|---|---|---|---|---|
| restricted | `none` | `True` | `["/tmp", "/workspace"]` | `["ALL"]` | 256 |
| elevated | `bridge` (allow-listed via iptables — Milestone 4) | `False` | `["/tmp"]` | `["NET_RAW", "SYS_ADMIN"]` | 1024 |
| full_access | `bridge` | `False` | none | none | 4096 |

`cap_drop` lists are **subtractive** from the Docker default; the
elevated tier drops only the truly dangerous caps and keeps the rest.
This is a v1 starting point; the iptables allow-list for elevated and
the bind-mount strategy for full_access are Milestone 4 work.

**M4.x update (2026-08-19):** the iptables allow-list for elevated is
**still deferred to v1.1** (data structure only — `Tier.network_allowlist`).
Full-access tier ships with a **per-tool destructive-op confirmation
gate** (`[y/N/a/o]` prompts, 30s default timeout) and a **git stash
checkpoint** before each run (`git stash push -u -m
"smolcode-checkpoint-<ISO8601>-<pid>"`). See `docs/decisions/0007-m4x-per-tool-confirmation-checkpoint.md`.

---

## 8. CLI surface

```bash
# Default: orchestrator at the restricted tier
smolcode "add a CLI flag parser to src/x.py"

# Pin a tier (skips orchestrator; runs the named tier directly)
smolcode --tier restricted "list the failing tests"
smolcode --tier elevated "open a PR with the fix"
smolcode --tier full_access "deploy the staging container"

# Override provider / model for one run
smolcode --provider opencode-go --model kimi-k2.7-code "task"

# Point at a LiteLLM proxy instead of a direct provider
SMOLCODE_LITELLM_PROXY=http://localhost:4000 smolcode "task"

# Override the workspace root
SMOLCODE_WORKSPACE=/tmp/ws smolcode "task"

# Dry-run: print the resolved config (tier, model, executor, allowlists) and exit
smolcode --print-config --tier elevated

# Offline smoke test (uses _StubLiteLLMModel; no network)
smolcode --smoke "task"
```

`--print-config` and `--smoke` are the two CLI affordances that
make the tier boundaries observable without spending tokens.

---

## 9. Extensibility hooks

| Add a… | How |
|---|---|
| new tool | Decorate a function with `@tool` (`smolagents.tools.Tool`) and add it to `build_tools(tier, settings)`. Path / shell tools must use `PathPolicy`. |
| new MCP server | Add an entry to `mcp_config.json`. No code change unless the new server needs a custom transport. |
| new provider | Add a preset tuple to `models.PROVIDER_PRESETS` and a test in `tests/test_models.py`. |
| new tier | Add a `Tier` entry to `config.TIERS`, a `Dockerfile` to `docker/`, and a 5-line `agents/<name>.py` module. |
| new specialist agent | Add `agents/<specialist>.py` exposing `def build() -> CodeAgent`. Register it as a tool on the orchestrator. |
| new audit log destination | Implement `AuditSink` and register in `app.lifespan` (Milestone 5). |

---

## 10. Resolved open questions (added 2026-06-28)

All five questions from the original planning pass were answered by the
user before M1 implementation. See `docs/decisions/0001-initial-setup.md`
for the full decision capture.

| # | Question | Resolution |
|---|---|---|
| 1 | Workspace path | Default `<repo>/workspace/` (auto-created); `SMOLCODE_WORKSPACE` override. |
| 2 | First provider | `opencode-go` (default) + `MiniMax` (secondary, supported). |
| 3 | First MCP server | Zero MCP servers in v1. |
| 4 | Tier default | `restricted`; `--tier elevated` / `--tier full_access` overrides available. |
| 5 | Orchestrator scope | Always present. |

Additional clarifications from the user:

- Docker daemon is **running** on the host (was stopped during initial
  inspection; user started Docker Desktop). `executor_type="docker"`
  is the M1 default; `local` is opt-in via `SMOLCODE_EXECUTOR=local`
  for portability only.
- The opencode-go API key env var is `OPENCODE_GO_APIKEY` (not the
  sibling project's `OPENCODE_API_KEY`). The default model is
  `deepseek-v4-flash` (DeepSeek Flash v4), used across all runs unless
  overridden by `--model` or `SMOLCODE_MODEL`.

**No blocking questions remain.** M1 implementation can begin.

---

## 11. Summary of resolved configuration

| Setting | Default | Override |
|---|---|---|
| Provider | `opencode-go` | `--provider` / `SMOLCODE_PROVIDER` |
| Model | `deepseek-v4-flash` | `--model` / `SMOLCODE_MODEL` |
| Tier | `restricted` | `--tier elevated` / `--tier full_access` |
| Executor | `docker` | `SMOLCODE_EXECUTOR=local` (opt-in, not a sandbox) |
| Workspace | `<repo>/workspace/` | `SMOLCODE_WORKSPACE` |
| MCP servers | zero | `MCP_CONFIG=path/to/config.json` (Milestone 3) |
| Orchestrator | always present | (no override; bypass via `--tier <T>`) |

## M5 update (decision 0008)

The orchestrator (M5) is shipped as an opt-in `--orchestrator` flag. `smolcode "task"`
(no flag) still routes directly to the restricted tier; `smolcode --orchestrator "task"`
builds a `CodeAgent` whose tools are `do_restricted_task` / `do_elevated_task` /
`do_full_task` (+ `do_specialist(name, task)` when specialists are available).

v1 ships ONE bundled specialist: `deploy_staging` (full-access tier, narrowed
toolset of `run` + `git_push`). User-installed specialists live in
`~/.smolcode/specialists.toml`. Every delegation emits a `subagent` event in
the audit log so the delegation chain is recoverable after the fact.

See `docs/decisions/0008-m5-orchestrator.md` for the full decision + 12
sub-decisions (D1-D12) + acceptance gates.

## M6 update (decision 0002)

M6 wires `smolcode` to an opt-in [LiteLLM proxy](https://docs.litellm.ai/docs/proxy/quick_start)
sidecar. The proxy sits between the CLI and the upstream LLM provider, giving the user a
single place to manage auth, cache responses, emit spend logs, swap providers, and apply
rate limits. The CLI surface is unchanged from M1: `--litellm-proxy <url>` /
`SMOLCODE_LITELLM_PROXY=<url>` were already wired and consumed by
`models.py:_api_base_for()`. M6 adds the proxy + the model catalog; nothing in the
agent loop changes.

### Components added in M6

```
smolcode/
├── docker-compose.litellm.yml    Compose for ghcr.io/berriai/litellm:main-latest on 127.0.0.1:4000
├── litellm_config.yaml           Starter config declaring 5 provider presets + per-model rpm/tpm
├── docs/litellm-proxy.md         Usage guide (start, point CLI, add provider, troubleshoot)
└── src/smolcode/
    ├── model_catalog.py          5-provider catalog (1h TTL, sync httpx.Client)
    └── tests/test_model_catalog.py  27 tests
```

### Model catalog

`smolcode.model_catalog` exposes:

* `PROVIDERS` — the 5-provider registry (opencode-go, MiniMax, openai,
  anthropic, custom).
* `fetch_models(provider, keys, refresh=False)` — returns
  `{models, cached, fetched_at, error}`. 1-hour in-memory TTL
  (`_CACHE_TTL_S = 3600.0`); `refresh=True` bypasses it.
* `get_providers(keys)` — returns per-provider metadata
  (`key_state`, cached `model_count`, `default_model`, `env_vars`,
  `host_env_var`).
* `clear_cache(provider=None)` — for tests.

Lifted from `smolagents-ui/smolagents_ui/services/model_catalog.py`
(PB-5.7..5.13) with attribution, but SYNC (CLI has no event loop),
5 providers (not 9 — keeps in sync with `models.py:PROVIDER_PRESETS`),
and `custom` included (smolcode exposes it as a first-class provider).

### Resolution order

When the CLI builds a `LiteLLMModel`:

1. `--litellm-proxy <url>` (CLI override)
2. `SMOLCODE_LITELLM_PROXY=<url>` (env var)
3. provider-specific `OPENCODE_HOST` / `MINIMAX_HOST` (if set)
4. provider-specific default in `models.py`

The proxy URL **wins** over the provider host env var. The proxy is
loopback-only (`127.0.0.1:4000`); multi-host or production deployments
need a reverse proxy and `LITELLM_MASTER_KEY` per `docker-compose.litellm.yml`.

### Known limitations

* The Compose file binds to `127.0.0.1:4000` only.
* No TLS termination (plain HTTP). Reverse proxy required for prod.
* Spend logs default to disabled; flip `disable_spend_logs: false`.
* `/models` HTTP endpoint deferred to v1.1 (no UI in v1).

See `docs/decisions/0002-litellm-proxy.md` for the decision (option
ship Compose), `docs/litellm-proxy.md` for the usage guide.

---

## 12. Web GUI (M8)

**Date:** 2026-08-20 (M8)
**Related:** decision 0010 (design), decision 0011 (implementation log).

### 12.1 Why

The CLI is fully featured but not very discoverable. A local web GUI
gives the user a visual surface for:
- browsing sessions and the audit log,
- seeing what their tier allows,
- uploading files (images, CSVs, PDFs) into the agent's working set.

### 12.2 Components

| Component | Path | Purpose |
|---|---|---|
| FastAPI app | `smolcode/src/smolcode/web/server.py` | Uvicorn launcher; bind allowlist (loopback only); serves SPA from `smolcode/web/dist/` if present |
| API router | `smolcode/src/smolcode/web/api.py` | 12 routes: health, config, tiers, sessions, audit, allowlist/check, uploads GET/POST/DELETE, uploads/clean |
| Pydantic schemas | `smolcode/src/smolcode/web/schemas.py` | Request/response models |
| Deps | `smolcode/src/smolcode/web/deps.py` | FastAPI dependencies for Settings / UploadsStore / AuditSink |
| CLI subcommand | `smolcode/cli.py::_web_main` | `smolcode web [--port N] [--host H] [--no-browser]` |
| React SPA | `smolcode/web/` | Vite + React 19 + TS 6. Components: TierBadge, UploadDropZone, UploadList, AllowlistSimulator + App.tsx (3-pane layout). |
| Build output | `smolcode/web/dist/` | `pnpm build` output, served by the FastAPI app when present |

### 12.3 Bind allowlist

`ALLOWED_BIND_HOSTS = ("127.0.0.1", "localhost", "::1")`. Any other
host raises `ValueError` from `run_server` and exit 8 from the CLI
subcommand. The CLI dispatcher enforces the same allowlist.

### 12.4 Upload folder

The SPA's drop zone POSTs multipart files to `/api/uploads`. The
endpoint reuses `smolcode.uploads.UploadsStore` (the same code path
as `smolcode uploads list`); the storage location is the same
hidden `<workspace>/.smolcode/uploads/` folder.

### 12.5 Dev mode vs production

- **Dev mode**: `smolcode web` runs FastAPI on 127.0.0.1:7860.
  `pnpm --dir smolcode/web dev` runs Vite on 5173 with a proxy for
  `/api/*` to 7860. Open http://localhost:5173.
- **Production**: `pnpm --dir smolcode/web build` produces
  `smolcode/web/dist/`. `smolcode web` serves both the API and
  the static SPA. Open http://127.0.0.1:7860.

### 12.6 What's not in M8 (deferred to M9-M11)

- **M9**: live execution streaming via SSE; tier-switcher with
  confirmation modal; stop button.
- **M10**: diff viewer for `write_file` / `patch_file`; apply /
  reject per step; workspace tree.
- **M11**: specialist editor (forms for `specialists.toml`); MCP
  server manager; audit-log reader (CLI `audit ls` / `audit grep`).

The current SPA explicitly notes these in placeholder panes so the
user knows where future work will land.

---

## 13. Live Execution via SSE (M9)

**Status:** SHIPPED 2026-08-21 (decision 0012). M9 adds the live
execution bridge between the agent loop and the SPA. The
read-only viewer (M8) becomes a write-capable run controller.

### 13.1 Components

| File | Purpose |
|---|---|
| `smolcode/src/smolcode/web/runs.py` | `Run`, `RunManager`, `PendingDecision`, SSE encoder, status constants |
| `smolcode/src/smolcode/web/agent_runner.py` | worker-thread entry point; bridges `step_callbacks` + `confirm_callback` to the SSE queue |
| `smolcode/src/smolcode/web/api.py` (extended) | 4 new endpoints: `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/events`, `POST /api/runs/{id}/approval`, `POST /api/runs/{id}/stop` |
| `smolcode/web/src/components/EventStream.tsx` | SSE subscriber (EventSource); renders events chronologically |
| `smolcode/web/src/components/ApprovalModal.tsx` | modal overlay for mid-run approval gates |
| `smolcode/web/src/components/StopButton.tsx` | POSTs `/api/runs/{id}/stop` |
| `smolcode/web/src/components/TierSwitcher.tsx` | header dropdown; sets tier for the NEXT run |
| `smolcode/web/src/components/RunComposer.tsx` | task input + Run button (replaces the read-only task panel) |
| `smolcode/web/src/components/RunHistory.tsx` | vertical list of recent runs with status + tier |

### 13.2 Threading model

```
  FastAPI event loop                   Agent worker thread
+----------------------+              +----------------------+
|  HTTP handler        |              |  agent.run(task)     |
|  /api/runs (POST)    |---start----->|                      |
|                      |              |  for each step:      |
|  /api/runs/{id}/     |              |    step_callback --> publish(step.*) --> events: Queue
|    events (GET, SSE) |<---get-------|                      |
|                      |              |  on destructive gate:|
|  /api/runs/{id}/     |              |    confirm_callback  |
|    approval (POST)   |---resolve-->|      --> publish(approval.requested)
|                      |              |      --> wait on Event
|  /api/runs/{id}/     |              |                      |
|    stop (POST)       |---set flag-->|  next step callback  |
|                      |              |    sees stop_flag,   |
|                      |              |    raises _StopReq   |
+----------------------+              +----------------------+
```

One worker thread per run. SSE handler is a coroutine reading from
a per-Run `queue.Queue` (unbounded). Cooperative stop via a
`threading.Event` checked from the step callback. Approval gate
blocks the worker thread for up to
`SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S` (default 30 s) — timeout = deny.

### 13.3 SSE event schema

Every event is encoded as `event: <type>\ndata: <json>\n\n`. The
`data` payload is JSON. Type strings are stable:

| Type | Payload |
|---|---|
| `run.started` | `{run_id, task, tier, model, provider, workspace, ts}` |
| `plan.step` | `{step_number, plan}` |
| `step.action` | `{step_number, thought, code_action?, tool_calls?, observations?, error?, is_final_answer?, timing_ms, tokens}` |
| `step.final_answer` | `{answer}` |
| `approval.requested` | `{decision_id, tool, args, summary, tier, timeout_s}` |
| `approval.decided` | `{decision_id, approved, reason, ts}` |
| `error` | `{kind, message}` |
| `run.ended` | `{run_id, status, exit_code, duration_s, result, error, ts}` |
| `end` (sentinel) | `{run_id, status}` |

### 13.4 Tier policy in the web

- `restricted`, `elevated`, `orchestrator` are exposed in the
  SPA's tier switcher.
- `full_access` is **rejected from the web with HTTP 403**. The
  CLI is the authoritative path for `full_access` (it has a
  real stdin prompt). The SPA's tier switcher omits `full_access`
  entirely.
- The orchestrator is exposed because it does not directly
  execute user code — it delegates to sub-agents.

### 13.5 Auth model

Loopback-only (M8's `ALLOWED_BIND_HOSTS`). No CSRF token, no
bearer token. Threat model: if you can hit 127.0.0.1:7860 you
already own the machine. A CSRF or bearer-token guard is recorded
in `docs/decisions/0012-m9-live-execution.md` as a v1.1
followup if the threat model changes.

### 13.6 What's not in M9 (deferred)

- **M10**: inline diff viewer for `write_file` / `patch_file`;
  apply / reject per step; workspace tree.
- **M11**: specialist editor (forms for `specialists.toml`); MCP
  server manager; CLI `audit ls` / `audit grep`.
- Replay: SSE subscribers joining late do not see events that
  arrived before subscription. v1.1 followup (buffer last N events
  per run).
- Auth: see §13.5.
- PyInstaller bundle with SPA embedded.

### 13.7 Runtime hardening (decisions 0022 / 0023 / 0024)

The runner (`agent_runner.run_in_thread`) received three post-M9
hardening passes that touch the threading + error-handling contract
documented in §13.2:

- **0022 (v1.7.1)**: `agent.cleanup()` now runs in `finally`, not just
  on the happy path. Prevents the user's `Bind for 127.0.0.1:8888
  failed: port is already allocated` failure when a previous run's
  container survived an abrupt drop.
- **0023 (v1.7.1.2)**: `agent.run(task)` runs inside a
  `ThreadPoolExecutor(max_workers=1)` with a wall-clock deadline
  (`SMOLCODE_WEB_RUN_TIMEOUT_S`, default 900 s). On timeout the
  existing `finally` block calls `agent.cleanup()` to kill the
  container, freeing `127.0.0.1:8888` even when the Jupyter kernel is
  hung (e.g. on `!pip install smolcode` that never resolves). Layer B
  of the same decision wraps `agent.python_executor` with
  `GuardedExecutor` so host-only `import smolcode` never reaches the
  Jupyter kernel.
- **0024 (v1.7.1.3)**: the broad `except Exception` block now appends
  `traceback.format_exc()` to `run.error` (capped at 8 KB) AND
  includes it in `EVT_ERROR.traceback` so the SPA can render it.
  All three `step_callbacks.register(...)` calls and
  `pool.submit(agent.run, ...)` are uniformly wrapped in try/except
  so transient smolagents-internal failures don't abort the run.
  Plus `_unicode_env.py::setup_unicode_env()` reconfigures
  `sys.stdout / stderr / stdin` to UTF-8 with `errors="replace"` and
  exports `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`; called from
  `smolcode/__init__.py` at package import time, BEFORE any
  submodule imports smolagents. Fixes the
  `UnicodeEncodeError: 'charmap' codec can't encode...` raised by
  smolagents' `StepLogger.log -> Rich console.print ->
  legacy_windows_render` path when encoding pip's emoji/box-drawing
  output through the Windows `cp1252/cp1256` codec. Live
  end-to-end validated: Web UI run of "create a simple todo app"
  with `deepseek-v4-flash` now completes in 114.28 s with
  `status=done`. See `docs/decisions/0024-web-ui-traceback-and-utf8.md`.

### 13.8 v1.8 evolution: sessions, projects, pause/queue, dashboard (decision 0025)

After v1.7.1.3 the user asked for a critical review of the Web UI/UX.
Decision **0025** (`docs/decisions/0025-web-ui-ux-review-and-roadmap.md`)
captures the findings + a 4-phase implementation plan. Headlines:

- **Phase 0 (P0, 1-2 d)**: sub-agent events (`subagent.started` /
  `subagent.ended`), per-step token totals in `RunSummary`, stuck-run
  countdown in the stream header, Inspector `activeRun` lag fix,
  `WorkspaceTree` refresh-on-diff hook, plus 5 cosmetic fixes.
  Backend: ~225 LOC + ~100 tests; frontend: ~275 LOC.
- **Phase 1 (P0, 3-5 d)**: sessions (list/new/delete/rename/detail view —
  backend `/api/sessions` already exists; the SPA simply doesn't render
  it yet) + project switcher + `Settings.projects` config. Backend:
  ~310 LOC; frontend: ~450 LOC; ~190 tests.
- **Phase 2 (P0, 5-7 d)**: pause/resume via `Run.snapshot` after each
  step, auto-queue (FIFO; drag-and-drop reorder explicitly deferred to
  v1.9.x), file preview pane, `@path` mentions with backend auto-attach.
  Backend: ~270 LOC; frontend: ~725 LOC; ~270 tests.
- **Phase 3 (P1, 3-5 d)**: token dashboard + per-provider cost
  projection, keyboard shortcuts, run search, rerun / retry endpoints,
  export run to JSON, `@axe-core/react` accessibility audit, auto-approve
  banner with mid-run revoke. Backend: ~270 LOC; frontend: ~585 LOC;
  ~320 tests.

**Net new code across all phases:** ~3990 LOC (~1075 BE / ~2035 FE /
~880 tests). See decision 0025 §6.6 for the breakdown table.

**Status (2026-08-23):** ACCEPTED. User approved all 5 open
questions: Q1=(a) Phase 0 first; Q2=(a) snapshot `agent.memory.steps`
to disk; Q3=Yes defer drag-drop reorder to v1.9.x; Q4=(c) Read both
(legacy `workspace` becomes "default" project); Q5=(a) hardcoded
defaults in `model_catalog.PROVIDERS` overridable via
`Settings.cost_rates`. Phase 0 implementation is IN FLIGHT.

**Phase 0 implementation cross-references (v1.8.0):**
- `Run.summary_dict(max_wall_s)` returns a dict containing `tokens_in`,
  `tokens_out`, `tokens_total`, `step_count`, `remaining_s`, and
  `subagent` — the snapshot consumed by `_run_summary()` in `web/api.py`.
  `tokens_in` / `tokens_out` are auto-incremented inside `Run.publish`
  for every `EVT_STEP_ACTION` event under `pending_lock`; `step_count`
  is bumped for every step.action regardless of whether it carries
  tokens.
- `Run.remaining_s(budget)` is a float; negative when the run has
  overrun the budget; None when the budget is disabled.
- `Run.subagent_*` fields are set by the orchestrator delegation tools
  (`_build_delegation_tool.forward()` and `_build_specialist_tool.forward()`
  in `agents/orchestrator.py`) around each inner `agent.run()` call.
  The same tools emit `EVT_SUBAGENT_STARTED` / `EVT_SUBAGENT_ENDED`
  events (new constants in `web/runs.py`) on the outer run, which the
  SPA's `EventStream.groupRows()` collects into a nested
  `<SubAgentBlock>` keyed by `subagent_id`.
- `Run.error` (Phase 0 BE-7) appends a sub-agent context string when the
  orchestrator raised mid-delegation, so the SPA can surface
  "while running sub-agent X" in the Inspector.
- `_run_summary()` and `RunSummary` schema (`web/schemas.py`) carry the
  new fields: `tokens: TokenSummary`, `step_count: int`,
  `remaining_s: float or null`, `subagent: SubAgentSummary or null`.
  All new fields are additive and optional on the wire; older servers
  omit them and the SPA renders an empty / "no token data yet" state.
- See decision 0025 §14 for the exact implementation plan (BE-1..BE-8,
  FE-1..FE-8, T-1..T-3) and validation gates.

**Standing rule:** the per-phase implementation still opens a planning
PR (sub-decision doc) before code lands. Phase 0's sub-decision is
now §14 of decision 0025 (the detailed plan + validation gates).

**Out of scope for v1.8** (explicit deferrals): drag-and-drop queue
reorder, full Monaco IDE, multi-user real-time collaboration, voice
input, dark mode, plugin/extension API, per-provider usage caps, prompt
library, model comparison view. See decision 0025 §8 for the full
list with rationale.

## 14. Inline diff viewer + workspace tree (M10)

M10 is a **pure UX layer on top of M9**: the diff gate plumbing
(`SessionState.diff_callback`, `EVT_DIFF_PROPOSED` /
`EVT_DIFF_RESOLVED`, `PendingDecision.kind = "diff"`) was already
shipped in 0012 §F4. M10 wires the gate into `write_file` +
`patch_file`, adds the `patch_file` fs tool, surfaces structured
hunks + raw diff + stats to the SPA via the SSE event payload, and
mounts a workspace tree in the inspector pane that highlights files
the run has touched.

### 14.1 New and changed components

| File | Role |
|---|---|
| `smolcode/web/diffs.py` (NEW) | Diff construction (`unified_hunks`, `unified_text`), summary (`summarize`), workspace walk (`walk_tree`), text read with size cap (`read_text_for_diff`). |
| `smolcode/tools/fs.py` | Adds `_PatchFileTool` (atomic write via `tempfile.mkstemp` + `os.replace`). Inlines the diff-gate consult in `_WriteFileTool.forward()` and `_PatchFileTool.forward()`. Custom `_apply_unified` hunk applier (NOT `difflib.restore` — see 0013 F3). |
| `smolcode/web/agent_runner.py` | Adds `_rel_path` and `_build_diff_callback` that publishes `diff.proposed` (full payload: hunks + raw_diff + stats + timeout) and blocks on the PendingDecision event. |
| `smolcode/web/api.py` | New `GET /api/workspace/tree` endpoint. Approval endpoint now forwards `edited_after`. Run summary now exposes `touched_paths`. |
| `smolcode/web/schemas.py` | `TreeEntryOut`, `WorkspaceTreeResponse`, `ApprovalDecisionRequest.edited_after`, `RunSummary.touched_paths`. |
| `smolcode/web/runs.py` | `PendingDecision.kind/path/before/after`, `Run.touched_paths` + `record_touch` + `touched_list`, `RunManager.decide(..., edited_after)` stores on `edited_args` and publishes `EVT_DIFF_RESOLVED`. |
| `web/src/components/DiffViewer.tsx` (NEW) | Renders `hunks` (or fallback `raw_diff`) with `+`/`-`/context line tags, stats badge, optional inline editor that sets `edited_after`. |
| `web/src/components/WorkspaceTree.tsx` (NEW) | Polls `/api/workspace/tree` every 10 s; collapsible dirs; highlights paths in `activeRun.touched_paths`. |
| `web/src/components/ApprovalModal.tsx` | When `pending.kind === 'diff'` renders `DiffViewer` with `editable=true`; destructive approvals keep the JSON-args layout. Forwards `editedAfter` to `postApproval`. |
| `web/src/components/EventStream.tsx` | Renderers for `diff.proposed` (collapsible raw diff) and `diff.resolved` (muted one-liner). Forwards diff events to the parent via `onDiffProposed`. |
| `web/src/App.tsx` | `onDiffProposed` sets `pending.kind = 'diff'` and copies the diff payload; `WorkspaceTree` mounted in Inspector pane. |
| `web/src/index.css` | Styles for the diff viewer, wide approval card, workspace tree, diff event rows. |

### 14.2 Diff event payload (SSE)

`diff.proposed` event:

```json
{
  "decision_id": "...",
  "tool": "write_file" | "patch_file",
  "path": "E:\\workspace\\src\\foo.py",
  "rel_path": "src/foo.py",
  "args": { ... },
  "summary": "write_file(src/foo.py, 312 bytes)",
  "tier": "restricted",
  "before": "...",
  "after": "...",
  "hunks": [{ "op": "equal" | "replace" | "insert" | "delete",
              "before": ["..."], "after": ["..."] }, ...],
  "raw_diff": "--- before\n+++ after\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n",
  "stats": { "added": 1, "removed": 1, "same": 2, "changed": true },
  "ts": "2026-08-23T12:34:56Z",
  "timeout_s": 30.0
}
```

`diff.resolved` event:

```json
{
  "decision_id": "...",
  "approved": true | false,
  "reason": "user" | "timeout" | "auto-approve" | "stopped",
  "edited": true | false,
  "path": "...",
  "ts": "..."
}
```

### 14.3 Audit + CLI parity

Every diff gate decision is recorded via `run.audit_sink.record("diff_decision", ...)` with the fields `tool`, `path`, `summary`, `approved`, `reason`, `edited`, `run_id`. This mirrors the M9 `destructive_decision` event so post-hoc reviewers can reconstruct every file change the user approved, denied, or edited.

`SMOLCODE_WEB_DIFF_GATE` (default `1`) controls the gate at the runner level. Setting it to `0` leaves `SessionState.diff_callback = None` and the fs tools write directly (CLI parity under the web view). This is the same escape hatch that M9 documented for the destructive confirmation gate.

### 14.4 What's not in M10 (deferred)

- **M11**: inline preview of MCP tool result payloads (PR description,
  ticket body, etc.) so the user can review structured outputs in
  the stream instead of dumping raw JSON.
- **M11+**: cross-run search across `diff_decision` audit events so
  the user can replay past approvals / edits from the history view.
- **M11+**: WebSocket transport (not needed yet — SSE works fine over
  loopback and EventSource reconnects automatically on disconnect).
