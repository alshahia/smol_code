# LiteLLM proxy (M6)

**Date:** 2026-06-28 (initial) / 2026-08-19 (M6 implementation)
**Status:** active
**Related:** `../docs/decisions/0002-litellm-proxy.md`, `docker-compose.litellm.yml`, `litellm_config.yaml`, `docs/architecture.md` §5.2

---

## 1. What is this?

`smolcode` calls hosted LLMs through `LiteLLMModel` (from
[smolagents](https://github.com/huggingface/smolagents)). By default it
talks **directly** to the upstream provider — e.g. `https://opencode.ai/zen/go/v1`
for `opencode-go`, or `https://api.minimax.io/v1` for `MiniMax`.

M6 adds the option to route those calls through a **LiteLLM proxy**:

```
  smolcode CLI ───▸ LiteLLM proxy (Docker) ───▸ upstream provider
```

The proxy is a sidecar container (`ghcr.io/berriai/litellm:main-latest`)
that:

* unifies auth (one place to rotate keys),
* caches responses,
* emits per-request spend logs,
* lets you swap providers without editing `smolcode`,
* and gives you a single place to apply rate limits.

This is the **same LiteLLM proxy** the upstream project ships; smolcode
just provides a Compose file + starter config so `docker compose up`
is the only setup step.

---

## 2. Quick start

### 2.1 Start the proxy

From `E:\python projects\smol_clone_2\smolcode\`:

```bash
docker compose -f docker-compose.litellm.yml up -d
```

Wait ~10 s for the container's healthcheck to pass:

```bash
docker compose -f docker-compose.litellm.yml ps
# NAME                STATUS
# smolcode-litellm    Up (healthy)
```

The proxy is now listening on **`http://127.0.0.1:4000`** (loopback only).

### 2.2 Point `smolcode` at it

```bash
# Windows
set SMOLCODE_LITELLM_PROXY=http://localhost:4000
smolcode --tier restricted "what is 2+2?"

# POSIX
SMOLCODE_LITELLM_PROXY=http://localhost:4000 smolcode --tier restricted "what is 2+2?"
```

Or pass it inline:

```bash
smolcode --tier restricted --litellm-proxy http://localhost:4000 "what is 2+2?"
```

### 2.3 Verify the proxy is reachable

```bash
curl http://127.0.0.1:4000/health/liveliness
# {"status":"healthy"}
```

### 2.4 List available models (using `model_catalog`)

```python
from smolcode.model_catalog import fetch_models, get_providers

# All five providers + their key state.
print(get_providers({"OPENCODE_GO_APIKEY": "..."}))

# Live fetch from opencode-go (1-hour cache).
print(fetch_models("opencode-go", {"OPENCODE_GO_APIKEY": "..."}))
```

The CLI itself does not yet expose a `--list-models` flag; the catalog
is consumed by host-side helpers (and tests).

---

## 3. What is in `litellm_config.yaml`?

The starter config declares the **five provider presets** that
`smolcode/src/smolcode/models.py` already knows about:

| Provider id | Default model | Key env var | Host env var |
|---|---|---|---|
| `opencode-go` | `deepseek-v4-flash` | `OPENCODE_GO_APIKEY` | `OPENCODE_HOST` |
| `MiniMax` | `MiniMax-M3` | `MINIMAX_API_KEY` | `MINIMAX_HOST` |
| `openai` | `gpt-4o-mini`, `gpt-4o` | `OPENAI_API_KEY` | — |
| `anthropic` | `claude-3-5-sonnet-latest`, `claude-3-5-haiku-latest` | `ANTHROPIC_API_KEY` | — |
| `custom` | `custom-model` | `CUSTOM_API_KEY` (optional) | `CUSTOM_BASE_URL` (required) |

**No secrets are inlined.** Every key is read via `os.environ/<NAME>`
placeholders, which the proxy resolves from its environment at
startup. `docker-compose.litellm.yml` forwards the env vars from the
host shell into the container.

The starter config also sets **per-model rate limits** (`rpm` / `tpm`)
under `model_group_settings`. These are intentionally generous for a
single-user dev setup; tighten them for any shared deployment.

---

## 4. How does `smolcode` know to use the proxy?

`smolcode/src/smolcode/config.py` reads `SMOLCODE_LITELLM_PROXY` (or
the `--litellm-proxy` CLI flag) and stores the URL on
`Settings.litellm_proxy`. `smolcode/src/smolcode/models.py:_api_base_for`
returns that URL when it is set, which makes `LiteLLMModel` route
through the proxy instead of the upstream provider.

The resolution order is:

1. `--litellm-proxy http://...` (CLI override)
2. `SMOLCODE_LITELLM_PROXY` env var
3. provider-specific host env var (`OPENCODE_HOST`, `MINIMAX_HOST`,
   etc.) — only if no proxy is set
4. provider-specific default in `models.py`

The proxy URL **wins** over the provider-specific host env var. This
is by design: if the proxy is up, route everything through it.

---

## 5. Adding a new provider

Edit `litellm_config.yaml` and append a new entry under `model_list`:

```yaml
  - model_name: my-fancy-model
    litellm_params:
      model: openai/my-fancy-model
      api_base: os.environ/MY_FANCY_HOST
      api_key: os.environ/MY_FANCY_API_KEY
```

Then add the env var(s) to the `environment:` block in
`docker-compose.litellm.yml`:

```yaml
    environment:
      - MY_FANCY_API_KEY=${MY_FANCY_API_KEY:-}
      - MY_FANCY_HOST=${MY_FANCY_HOST:-https://api.myfancy.com/v1}
```

Restart the proxy:

```bash
docker compose -f docker-compose.litellm.yml restart litellm
```

If the new provider should also be available via the **direct**
provider path (no proxy), add it to
`smolcode/src/smolcode/models.py:PROVIDER_PRESETS` AND to
`smolcode/src/smolcode/model_catalog.py` — the two stay in sync.

---

## 6. Cost control

The starter config sets three knobs for local dev:

* `litellm_settings.disable_spend_logs: true` — drop the per-request
  spend log entries. Flip to `false` if you want to track cost in
  real time (the proxy writes them to stdout).
* `litellm_settings.stream_timeout: 60` — 60-second timeout on
  streaming responses. Shorter than upstream's 600 s default because
  dev tasks should finish fast.
* `model_group_settings[*].limits.{rpm, tpm}` — per-model request /
  token budgets. The defaults are generous (60 rpm on first-class
  providers, 20–30 rpm on paid OpenAI/Anthropic). Tighten them if a
  single runaway agent is generating too many calls.

The proxy also writes a `spend_logs` table to its database (the
`/tmp/litellm.db` SQLite file inside the container by default). Set
`disable_spend_logs: false` to keep that table populated; query it
with the `litellm-proxy-extras` CLI or expose it via a
`LITELLM_DATABASE_URL` env var pointed at Postgres for production.

---

## 7. Known limitations

* **Loopback only.** The Compose file binds to `127.0.0.1:4000`. If
  you need other hosts to reach the proxy, change the `ports:` line
  to `"0.0.0.0:4000:4000"` AND set `LITELLM_MASTER_KEY` to a random
  32+ byte secret in the `environment:` block. Without a master key
  the `/admin routes are unauthenticated.
* **No HTTPS termination.** The proxy speaks plain HTTP. Add a
  reverse proxy (Caddy / nginx / Traefik) in front of it for TLS.
* **No persistence of spend logs.** The default SQLite DB lives in
  `/tmp/` inside the container — it is destroyed when the container
  is recreated. Mount a volume or set `LITELLM_DATABASE_URL` for
  persistent logs.
* **No MCP bridge.** LiteLLM's MCP integration is upstream-only; if
  you want to expose MCP servers through the proxy, read the
  LiteLLM docs at <https://docs.litellm.ai/docs/mcp>.
* **`/models` HTTP endpoint not exposed.** smolcode ships no UI; the
  catalog lives in `model_catalog.py` as a host-side helper. If a UI
  ships in v1.1, wire `fetch_models()` + `get_providers()` to a
  `/models` route at that time.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl http://127.0.0.1:4000/health/liveliness` returns "connection refused" | Container is not up | `docker compose -f docker-compose.litellm.yml up -d` |
| Proxy is up but `smolcode` fails with `No API key found for provider=...` | The provider key env var is not in the host shell | Export it (`set OPENCODE_GO_APIKEY=...`) before `docker compose up` |
| `smolcode` ignores the proxy and goes direct | `SMOLCODE_LITELLM_PROXY` is unset, OR `--litellm-proxy` was passed as an empty string | Run `smolcode --print-config` and confirm `litellm_proxy:` is non-null |
| Proxy returns 401 for every provider | A key env var was forwarded with the empty default `${NAME:-}` and the host shell had no value | Re-export the key, then `docker compose restart litellm` |
| `model_catalog.fetch_models("anthropic", ...)` returns `["claude-3-5-sonnet-latest", ...]` even with no key | Anthropic has no `/models` endpoint; the catalog returns a hardcoded list | This is expected; pick the model id manually |

---

## 9. References

* `docs/decisions/0002-litellm-proxy.md` — the design decision
  (resolved by user; ship the Compose file).
* `docs/roadmap.md` §5 (M6) — milestone scope + acceptance gates.
* `docs/environment.md` §9 — the `SMOLCODE_LITELLM_PROXY` env var
  documentation.
* `docs/architecture.md` §5.2 — provider preset table (the source
  of truth for `models.py`).
* [LiteLLM proxy docs](https://docs.litellm.ai/docs/proxy/quick_start)
* [LiteLLM Compose image](https://github.com/BerriAI/litellm/pkgs/container/litellm)
