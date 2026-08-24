# Environment Report

**Date:** 2026-06-28
**Author:** initial inspection pass (planning phase — no code written yet)
**Working directory:** E:\python projects\smol_clone_2
**Status:** active

---

## 1. Purpose

This document records the **detected state** of the host environment that the
proposed claude/opencode-like multi-agent system (smolagents-backed) will run
inside. It is the source of truth for what is available, what is missing, and
what fallbacks we have selected. Anything that changes after this document is
written belongs in an `overrides/` entry, not in this file.

> **Scope reminder:** this document is about the *host* (the developer's
> machine that runs the agent runtime), **not** the *sandbox* (the Docker
> container where model-written code executes). The sandbox is described in
> `docs/architecture.md` and `docs/security.md`.

---

## 2. Detected tools and versions

| Tool | Version | Source | Notes |
|---|---|---|---|
| OS | Windows 11 Pro | `Get-CimInstance Win32_OperatingSystem` | Build via `Caption`. |
| Architecture | AMD64 (x86_64) | `[System.Environment]::Is64BitOperatingSystem` + `Win32_Processor.Architecture = 9` | Linux containers in Docker Desktop will run as `linux/amd64`. |
| RAM | 32 GB total / ~14 GB free | `Win32_OperatingSystem.FreePhysicalMemory` | Comfortable headroom; one Docker executor container should sit comfortably below 4 GB. |
| Disk | C: 54 GB / D: 115 GB / **E: 28 GB free** | `Get-PSDrive FileSystem` | The workspace (E:\python projects\smol_clone_2) sits on the **E:** drive, which is the tightest of the three — keep Docker image caches + workspace artefacts under 25 GB. |
| `python` | not on `PATH` (Microsoft Store stub) | `where python` | The Microsoft Store stub is disabled / aliased — use the `py` launcher. |
| `py` launcher | present | `Get-Command py` | Source: `C:\Users\Ahmad Mahmoud\AppData\Local\Microsoft\WindowsApps\py.exe`. |
| Python 3.10.11 | `py -3.10` | `C:\Users\Ahmad Mahmoud\AppData\Local\Programs\Python\Python310\python.exe` | Used only as a fallback — `smolagents` requires 3.10+, so any of these satisfy the floor. |
| Python 3.11.9 | `py -3.11` | `…\Programs\Python\Python311\python.exe` | OK. |
| **Python 3.12.7** | `py -3.12` | `C:\Python313\python.exe` (the 3.12 install lives in the `Python313` folder — see §3) | **Selected default.** Matches the `python:3.12-bullseye` image the upstream smolagents `DockerExecutor` defaults to (`smolagents/src/smolagents/remote_executors.py:597`), and matches the sibling project's `.venv --python 3.12` workflow (`smolagents-ui/AGENTS.md:58-69`). |
| Python 3.13.7 | `py -3.13` | `…\Local\Programs\Python\Python313\python.exe` | Not used by upstream tests. |
| Python 3.14.0 | `py -3.14` | `…\Local\Python\bin\python3.14.exe` | Too new for several `litellm` extras; reserved for future. |
| Docker CLI | **28.3.0** (build 38b7060) | `docker --version` | Installed under `C:\Program Files\Docker\`. Plugins include buildx, compose v2.38.1, debug, cloud. |
| Docker daemon | **RUNNING** (since user-started during planning phase) | `docker ps` → empty container list (no error); `docker info` reports `Version: 28.3.0` / `Context: desktop-linux` | **Was** stopped during initial inspection; user started Docker Desktop during the planning phase. Resolved before M1 implementation. |
| `pip` (global) | not on `PATH` (same Microsoft-Store issue) | `pip --version` | Use `py -3.12 -m pip …`. |
| `ruff` | not installed | `ruff --version` (assumed absent) | Will be added in the project venv per `smolagents/AGENTS.md` and `smolagents-ui/AGENTS.md`. |
| `make` | not detected | — | `smolagents/Makefile` uses GNU-style targets; on Windows we will use `uv`/`pip` directly or a thin wrapper. |
| `git` | available | sibling submodules have `.git/` | The workspace root is **not** a git repo, but `smolagents/` and `smolagents-hybrid-search/` each are. The new project will likely be added as a sibling submodule. |
| LiteLLM | not installed in any Python | `py -3.12 -m pip show litellm` | Will be installed via `smolagents[litellm]` extra. |
| `docker` (PyPI SDK) | not installed | `py -3.12 -m pip show docker` | Will be installed via `smolagents[docker]` extra. |
| `mcp` (PyPI) | not installed | `py -3.12 -m pip show mcp` | Will be installed via `smolagents[mcp]` extra. |

---

## 3. Anomaly: the "3.13 install" is actually 3.12

`Get-Command python.exe` returned both `C:\Python313\python.exe` (which
reports `Python 3.12.7`) and `C:\Users\…\Programs\Python\Python313\python.exe`
(which reports `Python 3.13.7`). The folder name `Python313` is misleading
for the first path — it is **not** a 3.13 install. To avoid foot-guns, the
project venv will use the unambiguous `py -3.12` launcher syntax (which
targets the 3.12 install regardless of folder name).

---

## 4. Existing project conventions

| Convention | Source | Applies to new project? |
|---|---|---|
| `ruff` with `line-length = 119`, `select = ["E", "F", "I", "W"]`, ignore `F403` + `E501` | `smolagents/pyproject.toml:119-125` | **Yes** — copied to new `pyproject.toml`. |
| `pytest` `addopts = "-sv --durations=0"` | `smolagents/pyproject.toml:115-117` | **Yes** — matches sibling project. |
| `pip install -e ".[dev]"` / `[all]` install pattern | `smolagents/AGENTS.md` + `smolagents-hybrid-search/AGENTS.md` | **Yes**. |
| Venv + `uv` workflow | `smolagents-ui/AGENTS.md:56-69` | **Yes** — adopted as the canonical install path on Windows (multiple Python installs + spaces in paths make `uv` strictly better than `pip`). |
| Lifted-code attribution header (`# Lifted from <path>:<line>`) | `smolagents-ui/AGENTS.md` | **Yes** — applied to anything we copy from `smolagents-hybrid-search/src/smolagents_hybrid/providers.py` (MiniMax, opencode-go, Custom, Ollama patterns). |
| Tier-3 decisions are append-only once written | `research_doc/README.md` | **Yes** — `docs/` decisions go into `docs/decisions/`. |
| Research docs live alongside the repo root | `research_doc/` | **Different name**: user's brief explicitly asked for `docs/`, so this project uses `docs/` instead. `research_doc/` already exists and is owned by the sibling project; we do not touch it. |

---

## 5. Detected capabilities

| Capability | How it was detected | What it means for the project |
|---|---|---|
| Multi-Python via `py` launcher | `py --version` + `Get-Command py` | We can pin Python 3.12 for the project venv regardless of host `python` PATH shenanigans. |
| Docker Desktop 28.3.0 binary present | `docker --version` | Once the daemon is started by the user, `DockerExecutor` (`smolagents/src/smolagents/remote_executors.py:551-720`) will work out of the box. |
| Jupyter kernel gateway image is auto-built by `DockerExecutor` | `remote_executors.py:595-604` | No separate image build is needed for the default sandbox — the executor builds `python:3.12-bullseye + jupyter_kernel_gateway` lazily on first use. We can override `dockerfile_content=` for tier-specific images. |
| MCP transports supported | `smolagents/src/smolagents/mcp_client.py:108-116` | Stdio (subprocess) **and** streamable-http **and** sse all work without extra adapters. |
| `additional_authorized_imports` enforcement | `smolagents/src/smolagents/agents.py` + `local_python_executor.py` | Per-tier import allowlists are a first-class `CodeAgent` kwarg — no custom sandbox needed. |
| `LiteLLMModel` accepts `api_base` + `custom_llm_provider` | `models.py:1224-1253` | Direct + LiteLLM-proxy patterns both work without subclassing. |
| Reusable LLM provider classes | `smolagents-hybrid-search/src/smolagents_hybrid/providers.py:85-220` | `MiniMaxProvider`, `OpencodeGoProvider`, `CustomProvider`, `OllamaProvider` exist as drop-in patterns — the model construction logic (env-var → `LiteLLMModel`) can be lifted directly with attribution. |
| `executor_type` literal in `CodeAgent.__init__` | `agents.py:1535` | `"docker"` is one of the 5 first-class options; no monkey-patching needed. |
| `executor_kwargs` pass-through | `agents.py:1536, 1584, 1617` | Lets us inject per-tier `dockerfile_content`, `container_run_kwargs` (network mode, cap-add, read-only mounts, etc.) without subclassing. |

---

## 6. Detected limitations

### 6.1 Hard blockers (cannot proceed without user action)

1. **~~Docker daemon is stopped.~~** **RESOLVED during planning phase.** The user started Docker Desktop; `docker ps` now returns an empty container list with no error and `docker info` reports `Version: 28.3.0`. The `executor_type="docker"` path is the **default** for M1. (The `local` opt-in fallback remains in code for environments where Docker is genuinely unavailable, but on this host it is not needed.)

2. **~~No LLM API keys.~~** **PARTIALLY RESOLVED during planning phase.** A `.env` file exists at the workspace root (`E:\python projects\smol_clone_2\.env`) and contains a single non-empty entry: `OPENCODE_GO_APIKEY` (length 67). The user's default provider is `opencode-go` with model `deepseek-v4-flash`, so this key is sufficient for M1's end-to-end smoke against the default provider.
   - **Impact:** `LiteLLMModel(model_id="deepseek-v4-flash", api_key=os.environ["OPENCODE_GO_APIKEY"])` will succeed for the first `generate()` call. The other four presets (`MiniMax`, `openai`, `anthropic`, `custom`) will still raise `MissingAPIKey` until the user adds the corresponding env vars; this is expected and the CLI will surface the error clearly.
   - **Note on hygiene:** the value of `OPENCODE_GO_APIKEY` is **never** logged, echoed, or printed by the CLI. The `RedactSecretsFilter` (`docs/security.md` §8) catches any accidental leak in structured logs.
   - **Remaining gap:** MiniMax support is wired (preset in `docs/architecture.md` §5.2) but no `MINIMAX_API_KEY` is set. If the user wants to test the MiniMax preset, they must add the key to `.env`.

3. **No Python packages installed** (litellm, docker-PyPI-SDK, mcp, ruff, pytest). `py -3.12 -m pip show litellm`, `docker`, `mcp` all return "not found".
   - **Impact:** any import of these will fail at runtime.
   - **Fallback:** `uv venv --python 3.12 .venv && uv pip install -e "./smolagents[litellm,docker,mcp,dev]"` is the canonical install path. We will use a venv at the project root, never the global Python (per `smolagents-ui/AGENTS.md:58-69` — global Python site-packages can collide when multiple interpreters exist on PATH).

### 6.2 Soft blockers (work can proceed, but the user must decide)

1. **~~Workspace path is not defined.~~** **RESOLVED by user.** Default is `<repo>/workspace/` (auto-created on first run); overridable via `SMOLCODE_WORKSPACE`. See `docs/decisions/0001-initial-setup.md`.

2. **~~No MCP servers configured.~~** **RESOLVED by user.** Zero MCP servers in v1; the `mcp_config.json` schema is documented but the project ships with an empty config. See `docs/decisions/0001-initial-setup.md`.

3. **No LiteLLM proxy is running.** We will call providers directly via `LiteLLMModel` until/unless the user asks for a unified proxy. Calling providers directly is simpler for v1 (no extra container to run, no extra credential store) and matches what `smolagents-hybrid-search/src/smolagents_hybrid/providers.py` already does. If a proxy is wanted later, the `LiteLLMModel(api_base="http://localhost:4000")` form is already wired.

### 6.3 Cosmetic / informational

- `make` is not in PATH on this host. The sibling `smolagents/Makefile` uses GNU-style targets (`quality`, `style`, `test`); on Windows we will provide the same targets via a `Makefile` *and* a `scripts/quality.cmd` / `scripts/quality.ps1` wrapper so both shells can run them.
- The `E:\python projects\smol_clone_2\smolagents-ui\smolagents` directory mentioned in `smolagents-ui/AGENTS.md:73` is a local path-hack for a sibling path-dep install (pip mangles `file://` URLs that contain spaces). The new project should put `smolagents` as a path-dep at a **space-free** path if possible — `smolagents/` already satisfies that.

---

## 7. Selected fallbacks (summary)

| Risk | Selected fallback |
|---|---|
| Docker daemon unavailable at run time | **Not applicable on this host** — Docker is running. The `local` opt-in remains in code for portability (`SMOLCODE_EXECUTOR=local`), documented as "not a sandbox" in the CLI. |
| No API key for MiniMax / opencode-go / OpenAI / etc. | Fail fast with a structured error pointing at the missing env var. Provide `.env.example` with placeholders for all five providers. Provide an offline smoke-test mode that uses a deterministic fake model (the same `_StubLiteLLMModel` pattern used in `smolagents-hybrid-search/tests/test_agent.py:38-88`). |
| Workspace path undefined | Default to `<repo-root>/workspace/` (auto-created on first run). Document the `SMOLCODE_WORKSPACE` env override. |
| `pip install -e` URL parsing with spaces in path | Put the venv and editable installs on a **space-free** path under the repo, or use `uv` which handles `file://` URLs robustly. |
| `make` missing | Provide both `Makefile` (for Linux/CI) and a thin `scripts/quality.cmd` / `scripts/quality.ps1` wrapper for the Windows dev loop. |

---

## 8. Risks

- **R-1 (security).** `local_python_executor` runs model-written code **on the host**. If `executor_type="docker"` is ever bypassed (e.g., by an env override), every tier's safety claim collapses. See `docs/security.md` §4 for the layered controls.
- **R-2 (cost).** Hosted providers charge per token. Default model + `max_steps` per tier are the knobs that bound cost; we will set safe defaults and surface token usage in the CLI output. **No automatic retry-with-larger-model** — failure is failure.
- **R-3 (Docker Desktop licensing).** Docker Desktop for Windows requires a paid licence for organisations > 250 employees or > $10M revenue (per Docker's EULA). If the user is at a company that needs compliance, they may need to switch to Rancher Desktop or Podman. The `docker` PyPI SDK talks to the Docker-compatible socket, so the migration is one-line in `config.py`.
- **R-4 (path with spaces).** Several sibling projects (`smolagents-ui/AGENTS.md:73`) have been bitten by pip munging spaces in `file://` URLs. The repo path `E:\python projects\smol_clone_2\smolagents` contains a space. We will keep `smolagents` as an editable install with **relative paths only** in the new `pyproject.toml`.
- **R-5 (Windows-native Docker volumes).** Bind mounts across the Windows-to-Linux VM boundary are notoriously slow. The default `DockerExecutor` does not bind-mount the workspace — it uses Jupyter over a port forward — so this risk is moot for v1. Tier 2/3 images that *do* need workspace bind-mounts (for `git push`, `npm publish`, etc.) should accept the I/O cost as a known limitation.

---

## 9. Environment variables this project introduces (proposed)

| Name | Default | Purpose |
|---|---|---|
| `SMOLCODE_WORKSPACE` | `<repo>/workspace/` | Filesystem root the agent is allowed to touch. |
| `SMOLCODE_TIER` | `restricted` | Default tier if `--tier` flag is omitted. One of `restricted`, `elevated`, `full_access`. |
| `SMOLCODE_EXECUTOR` | `docker` | Which `executor_type` to pass to `CodeAgent`. Docker daemon is **running** on this host (was stopped during initial inspection; user started Docker Desktop). The `local` fallback is opt-in via `SMOLCODE_EXECUTOR=local` for environments without Docker, and is labelled "not a sandbox" in the CLI. |
| `SMOLCODE_MAX_STEPS` | `20` (restricted) / `40` (elevated) / `80` (full_access) | Per-tier step cap. |
| `SMOLCODE_TIMEOUT_S` | `60` (restricted) / `300` (elevated) / `900` (full_access) | Wall-clock timeout per `agent.run()` call. |
| `SMOLCODE_PROVIDER` | `opencode-go` | Which provider preset to use by default. **Resolved by user.** |
| `SMOLCODE_MODEL` | `deepseek-v4-flash` | Which model id to use by default. **Resolved by user** ("always use deepseek flash v4"). |
| `SMOLCODE_LITELLM_PROXY` | unset | If set, `LiteLLMModel(api_base=...)` is used instead of direct provider calls. |
| `SMOLCODE_LOG_LEVEL` | `INFO` | Structured-log level. |
| `OPENCODE_GO_APIKEY`, `OPENCODE_HOST` | unset (required) | opencode-go provider creds. Note: `OPENCODE_GO_APIKEY` (deliberately **not** `OPENCODE_API_KEY` from the sibling project — see `docs/decisions/0001-initial-setup.md`). |
| `MINIMAX_API_KEY`, `MINIMAX_HOST` | unset | MiniMax provider creds. Supported as a secondary preset (user explicitly asked for it). |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` | unset | Generic provider creds for `LiteLLMModel` (secondary presets, not first-class). |
| `MCP_CONFIG` | unset | Path to a JSON file describing MCP servers to attach. v1 ships with **zero** MCP servers (user explicitly opted to start with none). |

All of these are **non-secret**. Secrets live in the matching `*_API_KEY` env
vars and are **never** committed (`.env` is gitignored).

---

## 10. Next-step pointer

See `docs/architecture.md` for the component breakdown, `docs/security.md`
for the tier model + threat model, and `docs/roadmap.md` for the Milestone 1
plan that respects the limitations in §6.

---

## 11. Resolved configuration (added 2026-06-28 — see `docs/decisions/0001-initial-setup.md`)

The user provided answers to all five open questions during the planning
phase. The current state:

| Question | Resolution |
|---|---|
| Workspace path | Default `<repo>/workspace/` (auto-created); override via `SMOLCODE_WORKSPACE`. |
| First provider | `opencode-go` (default) + `MiniMax` (secondary). |
| First MCP server | Zero MCP servers in v1. |
| Default tier | `restricted`; `--tier elevated` / `--tier full_access` overrides. |
| Orchestrator scope | Always present. |
| Docker daemon | **Running** (was stopped during initial inspection; user started Docker Desktop). |
| API key env for opencode-go | `OPENCODE_GO_APIKEY` (set in `E:\python projects\smol_clone_2\.env`; deliberately not the sibling project's `OPENCODE_API_KEY`). |
| Default model | `deepseek-v4-flash` (always). |

Hard blocker §6.1 #1 (Docker daemon) is **resolved**. Hard blocker §6.1
#2 (API keys) is **partially resolved** (`OPENCODE_GO_APIKEY` is set in
`E:\python projects\smol_clone_2\.env`; MiniMax and other secondary
providers are not configured but are not needed for M1's default). Hard
blocker §6.1 #3 (Python packages) remains — addressed by M1.1
(`uv pip install`).

### 11.1 How the new project loads `.env`

The new project (`smolcode/`) lives at `E:\python projects\smol_clone_2\smolcode\`,
which is **one level below** the `.env` file at `E:\python projects\smol_clone_2\.env`.
Two load strategies are wired in M1:

1. **Default (recommended):** the CLI looks for `.env` in the cwd, then
   in the **parent directory** of the cwd, then in the user's HOME. This
   is implemented via `python-dotenv` with an explicit `dotenv_path`
   search list — not the default behaviour of dotenv (which only looks
   in cwd), but a deliberate extension. The order matches the resolution
   order in `docs/architecture.md` §5.1 (env var → `.env` → default).

2. **Override:** the user can pass `--env-file <path>` to the CLI to
   point at a specific file. Useful when running tests or in CI.

The key itself (`OPENCODE_GO_APIKEY`) is **never** copied into the new
project's own `.env` — that would duplicate the secret and risk
leakage. The new project reads it from the parent `.env` at runtime.

### 11.2 Remaining hard blockers → M1.1 sub-tasks

The remaining hard blocker (#3 — Python packages) is M1.1. The
`OPENCODE_GO_APIKEY` is already on disk, so M1's first real run does
not require any further user setup beyond `uv pip install`.

