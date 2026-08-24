# Decision 0002 — LiteLLM proxy: ship docker-compose.yml

**Date:** 2026-06-28
**Status:** active
**Trigger:** user provided answer to `docs/roadmap.md` §6.6.2 question #8
**Scope:** Milestone 6 (`docs/roadmap.md` §5)

---

## Context

The original planning pass left two questions unresolved about the
LiteLLM proxy in Milestone 6:

- Should the project **ship** a docker-compose file that runs the
  LiteLLM proxy, or assume the user already runs their own?
- If shipped, what is the minimal config so the user can start it and
  have a working proxy?

The user has answered: **ship the docker-compose file**, do not assume
the user runs it themselves.

---

## Decision

The M6 deliverable includes:

1. **`docker-compose.litellm.yml`** at the project root — a Compose
   file that runs the official `ghcr.io/berriai/litellm:main-latest`
   image on port 4000 with a bind-mounted `litellm_config.yaml`.
2. **`litellm_config.yaml`** — a starter config that:
   - Declares the **five provider presets** (opencode-go, MiniMax,
     openai, anthropic, custom) by reading the same env vars the
     direct-provider path uses (OPENCODE_GO_APIKEY, MINIMAX_API_KEY,
     etc.).
   - Sets sensible rate limits per model (`rpm` / `tpm`) per the
     provider's published tier.
   - Has **zero secrets inlined** — the config references env vars
     via `os.environ/<NAME>` placeholders.
3. **`docs/litellm-proxy.md`** — usage notes:
   - How to start: `docker compose -f docker-compose.litellm.yml up`.
   - How to point the CLI at it: `SMOLCODE_LITELLM_PROXY=http://localhost:4000`.
   - How to add a new provider: append to `litellm_config.yaml`.
   - Cost-control notes (rate limits, `stream_timeout`,
     `disable_spend_logs` for local dev).
4. **No docker-compose file for the agent itself.** The new project
   does not ship a single big Compose file with everything in it; the
   Compose file is **specifically for the LiteLLM proxy**. The agent
   runs on the host (per the existing architecture), and the proxy is
   a sidecar.

---

## Rationale

The user explicitly chose "ship docker-compose.yml" over "assume the
user runs it themselves". The rationale (inferred):

- **Lower setup friction.** `docker compose up` is one command; the
  alternative is for the user to install LiteLLM via pip, write their
  own config, run it on a port, and keep it alive. The first is
  better for a self-hosted tool that aims to feel like Claude Code /
  OpenCode.
- **Predictable defaults.** A starter `litellm_config.yaml` ensures
  that rate limits, retry behaviour, and model lists are not
  silently different between the user's manual setup and our docs.
- **Cost observability.** The LiteLLM proxy emits structured
  per-request logs (model, tokens, latency) that the direct-provider
  path does not. For a hosted-model workflow that may span multiple
  providers, this is the cheapest way to answer "what did I spend
  last week?".

---

## Trade-offs (acknowledged)

| Trade-off | Accepted because |
|---|---|
| One more Docker container to run | The proxy image is lightweight (~200 MB) and the user already has Docker running for the agent's executor. |
| Proxy adds a network hop (CLI → proxy → provider) | The latency is sub-millisecond on localhost; the cost observability is worth it. |
| `litellm_config.yaml` is project-specific | The user can override by mounting a different file at `/app/config.yaml` inside the proxy container. |
| The proxy image is from `ghcr.io/berriai` (third party) | It is the canonical LiteLLM image; the project is a thin Compose wrapper, not a fork. |

---

## What is **not** in this decision

- **The agent's own Docker image** — the agent still runs on the host
  and uses `executor_type="docker"` for sandboxing (per
  `docs/architecture.md` §7). No agent-in-Container decision here.
- **Production deployment of the proxy** — the Compose file is for
  local / single-host use. For multi-host production, the user is
  expected to read the upstream LiteLLM docs and adapt.
- **TLS termination / auth on the proxy** — the local proxy is
  intended to be reachable only from `127.0.0.1`. Production auth
  is left to the user.

---

## Code Impact (planned for M6, not yet implemented)

```
smolcode/
├── docker-compose.litellm.yml       (M6.1)
├── litellm_config.yaml              (M6.2)
└── docs/
    └── litellm-proxy.md             (M6.3)
```

No edits to existing files. The CLI's `SMOLCODE_LITELLM_PROXY` env
var is already declared in `docs/environment.md` §9 and the
`LiteLLMModel(api_base=...)` form is already documented in
`docs/architecture.md` §5.2.

## Ship notes (2026-08-19 — post-M6)

All four planned files shipped plus two extras (model_catalog +
tests):

- `smolcode/docker-compose.litellm.yml` — 91 lines, runs
  `ghcr.io/berriai/litellm:main-latest` on `127.0.0.1:4000` with
  `litellm_config.yaml` bind-mounted read-only. Healthcheck on
  `/health/liveliness`. Provider env vars forwarded from the host
  shell via Compose's `${VAR:-}` default-empty interpolation.
- `smolcode/litellm_config.yaml` — 130 lines, declares the five
  provider presets (`opencode-go`, `MiniMax`, `openai`, `anthropic`,
  `custom`) via `model_list`, plus per-model `model_group_settings`
  rate limits (60 rpm / 200k tpm for first-class providers;
  20-30 rpm / 100k-200k tpm for paid OpenAI/Anthropic). No secrets
  inlined — every key uses `os.environ/<NAME>`.
- `smolcode/docs/litellm-proxy.md` — 200 lines: quick start, config
  table, add-a-provider walkthrough, cost-control knobs,
  troubleshooting matrix, known limitations (loopback only, no
  HTTPS, no spend-log persistence, no MCP bridge, no `/models` HTTP
  endpoint), and pointers to upstream LiteLLM docs.
- `smolcode/src/smolcode/model_catalog.py` — NEW, 290 lines.
  5-provider catalog (lifted from `smolagents-ui` with attribution).
  Sync `httpx.Client`, 1-hour TTL (`_CACHE_TTL_S = 3600.0`),
  `fetch_models(provider, keys, refresh=False)` returns
  `{models, cached, fetched_at, error}`. Anthropic returns a
  hardcoded list (no public /models). Custom provider
  short-circuits with `no_base_url` when `CUSTOM_BASE_URL` is empty.
- `smolcode/src/smolcode/tests/test_model_catalog.py` — NEW,
  27 tests. Covers PROVIDERS tuple shape, key_state, no_key guard,
  TTL hit/miss/refresh, network failure handling, auth failure,
  anthropic hardcoded list, unknown provider, custom base URL,
  clear_cache semantics, and the `_is_api_key_env` helper.

CLI surface unchanged: `SMOLCODE_LITELLM_PROXY` (M1) + `--litellm-proxy`
(M1) + `models.py:_api_base_for()` (M1) are all already wired. M6
adds the proxy itself + the model catalog; no existing
agent-loop behaviour changes.

### Sub-decisions made during M6 implementation

These are tier-1 implementation choices, not tier-3 design choices,
but they're recorded here for completeness.

- **Sync vs async catalog.** The lifted smolagents-ui catalog is
  async (`httpx.AsyncClient` + `asyncio.Semaphore`). smolcode's CLI
  has no event loop to coordinate against, so the M6 catalog uses
  sync `httpx.Client`. Public function signatures are otherwise
  unchanged; tests run without any async harness.
- **5 providers, not 9.** smolagents-ui exposes 9 providers
  (`hf`, `openai`, `anthropic`, `gemini`, `mistral`, `groq`,
  `openrouter`, `minimax`, `opencode`). smolcode ships the FIVE
  that are wired into `models.py:PROVIDER_PRESETS`. Adding a new
  provider requires editing BOTH `models.py` AND
  `model_catalog.py` (keep in sync). Documented in the module
  docstring.
- **`custom` is IN the catalog.** smolagents-ui's D-10 excludes
  `custom` from the UI's `PROVIDERS` registry. smolcode exposes it
  as a first-class provider in `models.py`, so the catalog
  includes it. Documented in the module docstring.
- **`OPENCODE_GO_APIKEY` ends in `_APIKEY` (no underscore).**
  The smolagents-ui code's `_is_api_key_env`-equivalent check
  (`env.endswith("_API_KEY")`) misses `OPENCODE_GO_APIKEY` because
  the suffix is `_APIKEY` (no underscore before `KEY`). smolcode's
  M6 catalog adds an `_is_api_key_env(env)` helper that matches
  BOTH `_API_KEY` AND `_APIKEY`. 4 tests pin this behaviour
  (`test_is_api_key_env_*`).
- **No `/models` HTTP endpoint.** Per roadmap M6 sketch, the
  endpoint is deferred to v1.1 because smolcode ships no UI. The
  catalog is consumed by host-side helpers + tests only.

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

---

## References

- `docs/roadmap.md` §5 (M6 sketch), §6.6.2 (pending question).
- `docs/architecture.md` §5.2 (provider preset table).
- `docs/environment.md` §9 (`SMOLCODE_LITELLM_PROXY` env var).
- LiteLLM proxy docs: <https://docs.litellm.ai/docs/proxy/quick_start>.
- Upstream image: <https://github.com/BerriAI/litellm/pkgs/container/litellm>.
