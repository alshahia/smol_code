# Decision 0001 — Initial provider, workspace, tier, MCP, orchestrator choices

**Date:** 2026-06-28
**Status:** active
**Trigger:** user provided answers to the 5 open questions in `docs/architecture.md` §10
**Scope:** v1 default behaviour; overridable via env / CLI flags

---

## Context

After the initial planning pass produced `docs/environment.md`, `docs/architecture.md`, `docs/security.md`, and `docs/roadmap.md`, the user resolved the open questions and added two specific configuration requirements:

1. The default LLM provider is **opencode-go**, with env var `OPENCODE_GO_APIKEY` (note: **not** the sibling project's `OPENCODE_API_KEY` — the user explicitly chose this naming).
2. The default model is **`deepseek-v4-flash`** (DeepSeek Flash v4), and "always" use this model across runs.
3. Add **MiniMax support** as well (so two providers are wired, not just one).
4. Docker daemon is **now running** on the host (was stopped during the initial inspection; the user started Docker Desktop).
5. Workspace path: **default** `<repo>/workspace/` — no override requested.
6. First MCP server: **zero** — start with no MCP servers attached.
7. Default tier: `restricted`, with `--tier elevated` and `--tier full_access` available as overrides.
8. Orchestrator: **always present**.

This decision document captures the user's answers and the resulting
default values. It is **append-only**; any future change creates a
`0002-…` doc.

---

## Resolved questions (from `docs/architecture.md` §10)

| # | Question | Resolution |
|---|---|---|
| 1 | Workspace path | Default `<repo>/workspace/` (auto-created on first run); overridable via `SMOLCODE_WORKSPACE`. |
| 2 | First provider | `opencode-go` (default); `MiniMax` (also supported). |
| 3 | First MCP server | Zero. No MCP servers attached in v1; the `mcp_config.json` schema is documented but the project ships with an empty config. |
| 4 | Default tier | `restricted` (CLI default); `--tier elevated` and `--tier full_access` are explicit user overrides. |
| 5 | Orchestrator scope | Always present. `smolcode "task"` routes through the orchestrator; `smolcode --tier <T> "task"` bypasses the orchestrator and runs the named tier directly. |

---

## Default configuration

| Setting | Default | Source |
|---|---|---|
| `SMOLCODE_PROVIDER` | `opencode-go` | user (this decision) |
| `SMOLCODE_MODEL` | `deepseek-v4-flash` | user (this decision) |
| `SMOLCODE_TIER` | `restricted` | user (this decision); `--tier` flag overrides |
| `SMOLCODE_EXECUTOR` | `docker` | Docker daemon is now running (was stopped during initial inspection) |
| `SMOLCODE_WORKSPACE` | `<repo-root>/workspace/` | user (this decision) |
| `MCP_CONFIG` | unset | user (this decision); zero MCP servers in v1 |
| Orchestrator | always present | user (this decision) |

---

## Provider preset specifics

### opencode-go (default)

| Field | Value |
|---|---|
| Provider id | `opencode-go` |
| API key env var | `OPENCODE_GO_APIKEY` (note: `OPENCODE_GO_APIKEY`, **not** the sibling project's `OPENCODE_API_KEY`) |
| API base env var | `OPENCODE_HOST` (default `https://opencode.ai/zen/go/v1`) |
| Default model | `deepseek-v4-flash` |
| `custom_llm_provider` | `openai` |
| Lifted from | `smolagents-hybrid-search/src/smolagents_hybrid/providers.py:121-151` (`OpencodeGoProvider`) |

> **Compatibility note:** the sibling project uses `OPENCODE_API_KEY`
> (`smolagents-hybrid-search/.env.example:5`). The user explicitly chose
> `OPENCODE_GO_APIKEY` for this project; if a user has an existing
> `OPENCODE_API_KEY` in their environment, we will **not** auto-pick
> it up — they must rename or add the new var. This is a deliberate
> choice: silently reading both names would mask config errors.

### MiniMax (secondary, supported)

| Field | Value |
|---|---|
| Provider id | `MiniMax` |
| API key env var | `MINIMAX_API_KEY` |
| API base env var | `MINIMAX_HOST` (default `https://api.minimax.io/v1`) |
| Default model | `MiniMax-M3` |
| `custom_llm_provider` | `openai` |
| Lifted from | `smolagents-hybrid-search/src/smolagents_hybrid/providers.py:85-118` (`MiniMaxProvider`) |

The user explicitly asked for MiniMax support to be added alongside
opencode-go, even though opencode-go is the default.

### Other presets (carry over from the initial design)

`openai`, `anthropic`, and `custom` remain in the preset list
(`docs/architecture.md` §5.2) but are not first-class — the user did
not request them, and they require API keys that have not been
confirmed available. They can be added at any later milestone without
an architectural change.

---

## Impact on other docs

| Doc | Change |
|---|---|
| `docs/environment.md` §2 | Docker daemon status flipped from `NOT RUNNING` to `RUNNING`. |
| `docs/environment.md` §6.1 | Hard blocker #1 (Docker daemon) resolved. |
| `docs/environment.md` §9 | Env var table updated: `OPENCODE_GO_APIKEY` (not `OPENCODE_API_KEY`); `SMOLCODE_PROVIDER` default = `opencode-go`; `SMOLCODE_MODEL` default = `deepseek-v4-flash`. |
| `docs/architecture.md` §5.2 | Provider preset table updated; `opencode-go` is now the default; `MiniMax` is secondary. |
| `docs/architecture.md` §10 | All five questions marked answered; new §11 summarises this decision. |
| `docs/security.md` §2 | "Default executor is Docker" (the `local` opt-in fallback remains for environments without Docker, but on the current host Docker is up). |
| `docs/roadmap.md` §6.6 | Open questions list flipped from "pending" to "resolved"; references this decision. |
| `docs/roadmap.md` §4.4 | Risk R-M1.1 downgraded from "ship with local" to "Docker is up; no fallback needed for M1". |

No code has changed; this is a docs-only update plus the new
`docs/decisions/0001-initial-setup.md` capture.

---

## Code Impact (planned for M1, not yet implemented)

The `models.py` preset list will look like:

```python
PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "opencode-go": ProviderPreset(
        api_key_env="OPENCODE_GO_APIKEY",
        api_base_env="OPENCODE_HOST",
        api_base_default="https://opencode.ai/zen/go/v1",
        default_model="deepseek-v4-flash",
        custom_llm_provider="openai",
        # Lifted from smolagents-hybrid-search/src/smolagents_hybrid/providers.py:121-151
    ),
    "MiniMax": ProviderPreset(
        api_key_env="MINIMAX_API_KEY",
        api_base_env="MINIMAX_HOST",
        api_base_default="https://api.minimax.io/v1",
        default_model="MiniMax-M3",
        custom_llm_provider="openai",
        # Lifted from smolagents-hybrid-search/src/smolagents_hybrid/providers.py:85-118
    ),
    "openai": ProviderPreset(  # secondary; not first-class
        api_key_env="OPENAI_API_KEY",
        api_base_env=None,
        default_model="gpt-4o-mini",
        custom_llm_provider=None,
    ),
    "anthropic": ProviderPreset(  # secondary; not first-class
        api_key_env="ANTHROPIC_API_KEY",
        api_base_env=None,
        default_model="claude-3-5-sonnet-latest",
        custom_llm_provider=None,
    ),
    "custom": ProviderPreset(  # secondary; not first-class
        api_key_env="CUSTOM_API_KEY",
        api_base_env="CUSTOM_BASE_URL",
        default_model="custom-model",
        custom_llm_provider="openai",
    ),
}

DEFAULT_PROVIDER = "opencode-go"
DEFAULT_MODEL = "deepseek-v4-flash"
```

(Concrete implementation lands in M1.3 per `docs/roadmap.md` §4.1.)

---

## References

- `docs/architecture.md` §10 — original open questions.
- `docs/roadmap.md` §6.6 — open questions pending user input.
- `docs/environment.md` §9 — proposed env vars (now updated).
- `smolagents-hybrid-search/src/smolagents_hybrid/providers.py:85-151` — source of the lifted MiniMax / opencode-go provider classes.
- `smolagents-hybrid-search/.env.example:5` — sibling project's `OPENCODE_API_KEY` naming (deliberately **not** adopted; see compatibility note above).
