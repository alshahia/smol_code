# M11 — Provider / model / API-key selector in the SPA (v1.3)

**Date:** 2026-08-22 (initial)
**Status:** active (M11 SHIPPED — backend + frontend + polish)
**Related:**
`../docs/decisions/0014-m11-provider-model-key-ui.md`,
`../research_doc/m11-provider-model-key-ui.md`,
`smolcode/src/smolcode/model_catalog.py`,
`smolcode/src/smolcode/web/api.py`,
`smolcode/src/smolcode/web/keys.py`,
`smolcode/web/src/lib/keysStore.ts`,
`smolcode/web/src/components/ProviderSelector.tsx`,
`smolcode/web/src/components/ApiKeyPanel.tsx`.

---

## 1. What is this?

M11 exposes the existing **5-provider catalog** (opencode-go, MiniMax,
openai, anthropic, custom) directly inside the running web GUI. Three
new affordances live in a new header bar above the existing Task /
Execution Stream / Inspector layout:

| Affordance | Source of truth | Persistence |
|---|---|---|
| **Provider dropdown** | `GET /api/providers` → `model_catalog.get_providers()` | session only |
| **Model input** | `GET /api/providers/{id}/models?refresh=` → `model_catalog.fetch_models()` (1h in-memory TTL) | session only |
| **API-key panel** | `localStorage["smolcode.keys.v1"]` (browser-only) | browser-only, never on disk on the server |

Selecting a provider + typing a model + (optionally) entering a key
rides on `POST /api/runs` as three new optional fields:

```jsonc
{
  "task": "what is 7 times 6?",
  "tier": "restricted",
  "provider": "opencode-go",            // optional — falls back to settings.provider
  "model": "deepseek-v4-flash",         // optional — falls back to settings.model
  "keys": {                             // optional — overrides env-set keys for this run only
    "OPENCODE_GO_APIKEY": "sk-…"
  }
}
```

`POST /api/runs` stays **fully backwards-compatible** — all three new
fields are optional. Old clients that send only `task` + `tier` keep
working exactly as before.

---

## 2. Quick start

### 2.1 Open the SPA

```bash
# Either: serve the built bundle from FastAPI
.venv\Scripts\python.exe -m smolcode web --port 7860
# or: Vite dev server with HMR (proxies /api/* to FastAPI)
cd smolcode\web && pnpm dev
```

Open <http://127.0.0.1:7860/> (production build) or
<http://localhost:5173/> (dev mode).

### 2.2 Pick a provider + model

1. Look at the **new header row** under the main header bar.
2. The **provider dropdown** lists all 5 presets with a per-row
   `🔑 set` / `∅ missing` badge that reflects the **server-side env**
   (the SPA never reveals a key value, only its presence).
3. The **model input** is pre-filled with the provider's
   `default_model`. Type any model id the provider supports.
4. Hit the **↻ refresh** button to fetch the provider's live model
   list (1h cache; the button forces a cache miss).

### 2.3 Enter / save an API key (per provider)

The API-key panel sits to the right of the model input. Its three
visual states:

| State | Trigger | UI |
|---|---|---|
| **✓ set on server (env)** | `OPENCODE_GO_APIKEY` (etc.) is already in `os.environ` | green banner: *"✓ OPENCODE_GO_APIKEY is set on the server (env). Nothing to enter."* |
| **🔑 browser-local** | user previously pressed **Save** for this provider | "🔑 Browser has a stored OPENCODE_GO_APIKEY. Click Forget to remove." + a **Forget** button |
| **enter** | default | password input + Show / Hide + **Save** button |

Keys land in `localStorage["smolcode.keys.v1"]` (JSON-serialised,
per-entry 4 KB cap, 16 entries total — see `web/src/lib/keysStore.ts`).

**Security:** the value is only ever sent in the `keys` field of a
single `POST /api/runs` request. The server holds it in `Run.api_key_value`
for the lifetime of that one run and never persists it, never logs it,
never returns it in any event payload. The `redact.py` filter scrubs
the request body before any log emission as a defence-in-depth layer.

### 2.4 Run a task

Hit **Run**. The composer sends:

```
POST /api/runs  { task, tier, provider, model, keys: { <ENV_VAR>: <value> } }
```

If `apiKeyEnv` is empty (the provider has no key in env and none saved
in the browser), `keys` is omitted entirely.

A small `via <provider> / <model>` hint sits under the Run button so
the user sees what they're about to dispatch.

---

## 3. Environment variables (no new ones)

M11 introduces **no new env vars**. The catalog reads the existing
5-provider preset table from `os.environ`:

| Provider | Key env var(s) | Host env var (optional override) |
|---|---|---|
| `opencode-go` | `OPENCODE_GO_APIKEY` | `OPENCODE_HOST` |
| `MiniMax` | `MINIMAX_API_KEY` | `MINIMAX_HOST` |
| `openai` | `OPENAI_API_KEY` | — |
| `anthropic` | `ANTHROPIC_API_KEY` | — |
| `custom` | `CUSTOM_API_KEY` | `CUSTOM_BASE_URL` (required, no default) |

The SPA only ever **reads the names** of these env vars (via
`ProviderSpec.env_vars`). The values themselves are reported only as
`key_state: "set" | "missing"` — never as a string — see
`smolcode/src/smolcode/web/api.py:get_providers` and the
`ProviderOut.key_state` schema.

If a user wants to use a provider that has no key in `.env`, they
enter one in the SPA's API-key panel. It travels only inside the next
`POST /api/runs` body and dies with that run.

---

## 4. API surface (M11 additions)

| Endpoint | Method | Body | Notes |
|---|---|---|---|
| `/api/providers` | GET | — | Returns the 5 presets with `key_state` and the cached `model_count` |
| `/api/providers/{provider_id}/models` | GET | `?refresh=1` (optional) | Returns `{provider, models, cached, fetched_at, error}` |
| `/api/runs` | POST | extends with `provider`, `model`, `keys` (all optional) | Existing callers continue to work without changes |

All routes bind to loopback only (`ALLOWED_BIND_HOSTS` unchanged per
decision 0009 / 0014).

The `keys` body field is validated by `smolcode/src/smolcode/web/keys.py:extract_keys`:

- Only env-var names matching `*_API_KEY`, `*_APIKEY`, or `HF_TOKEN` are
  accepted. Anything else returns **HTTP 422** with the offending field.
- At most 16 entries.
- Each entry is trimmed, CR-stripped, first-line-truncated, and
  hard-capped at **4096 bytes** (4 KB).

---

## 5. Test count

M11 adds **+70 tests** to the suite (no removals):

| Suite | Tests added |
|---|---|
| `test_web_keys.py` (new) | 14 |
| `test_web_providers_api.py` (new) | 12 |
| `test_web_models_api.py` (new) | 13 |
| `test_runs_keys.py` (new) | 14 |
| `test_redact_in_runs.py` (new) | 7 |
| `TestRunsM11Overrides` (added to `test_web_runs_api.py`) | 10 |
| **Total** | **70** |
| **Suite total** (M11 done) | **737 passing** in ~102 s |

Coverage remains ≥ 80 % (was 82.3 % at M11.1; unchanged at M11.3).

---

## 6. Viewport behaviour

Verified at three viewport sizes with Microsoft Edge headless (M11.3):

| Viewport | Layout |
|---|---|
| 4K (3840 × 2160) | Three-column layout (Task / Execution Stream / Inspector) spreads out naturally; M11 header row sits cleanly across the top |
| Laptop (1440 × 900) | Three columns fit comfortably; M11 header row fits in one line |
| Mobile (390 × 844) | M11 header row **wraps** gracefully (flex-wrap on every row); the three-column main layout overflows horizontally — **pre-existing M8 limitation, not introduced by M11** |

The M11 row uses `flex-wrap: wrap` + 220–280 px `min-width`s so the
selector, model input, and key panel stack vertically on narrow screens.
The 3-pane main layout's mobile behaviour is tracked for a future
release (out of M11 scope).

---

## 7. Known limitations (out of M11 scope)

- **opencode-go `/zen/go/v1/v1/models` returns 404** as of 2026-08-22.
  The catalog retry reports `error: "fetch_failed: Client error '404
  Not Found'"` in the SPA. The default model still works because it
  is hard-coded in the catalog. **Pre-existing** — to be fixed by
  updating the base URL in `model_catalog._DEFAULT_BASE_URLS` once
  the upstream opencode-go team republishes the endpoint.
- **3-pane main layout does not collapse for mobile**. Pre-existing
  from M8. Tracked separately.
- **`oxlint` set-state-in-effect warnings (4)** on lines in
  `App.tsx`, `ProviderSelector.tsx`, `ApiKeyPanel.tsx`, plus 1
  pre-existing on `StopButton.tsx`. Stylistic, non-blocking. Build
  exits 0. Same pattern as the pre-existing M9 warning.

---

## 8. See also

- `../docs/decisions/0014-m11-provider-model-key-ui.md` — full design
  + rejected alternatives + security checklist.
- `../research_doc/m11-provider-model-key-ui.md` — full M11 plan with
  F1–F6 findings + per-file LOC budget.
- `smolcode/src/smolcode/model_catalog.py` — the canonical
  5-provider catalog (single source of truth for both CLI + SPA).
- `smolcode/src/smolcode/web/api.py` — the two new endpoints +
  extended `POST /api/runs`.
- `smolcode/web/src/lib/keysStore.ts` — the browser-local key store
  (the only file that touches `localStorage`).
