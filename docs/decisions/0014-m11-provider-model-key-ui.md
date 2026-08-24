# 0014 — M11 web UI for provider / model / API-key selection

**Date:** 2026-08-22
**Status:** active (shipped — backend M11.1, frontend M11.2, polish M11.3)
**Trigger:** M10 SHIPPED (decision 0013). User asked: "allow the user
to select provider and model (like you provide to dropdown list for
provider and models of that provider available/support) and allow the
user to add his api key for provider".
**Related:** decision 0010 (SPA design — header dropdown pattern from
M10), decision 0013 (M10 inline-diff log), `model_catalog.py`
(catalog is the single source of truth for the dropdowns),
`models.py:build_model` (already accepts per-call overrides),
`config.py:Settings.with_overrides` (already chains overrides).

---

## Question

How do we add provider + model + API-key selection to the live web
GUI without restarting the server, and without weakening the
M0–M10 security model (loopback bind, redact filter, audit log,
no secrets on disk, no API keys in responses)?

## Findings

Full findings in `research_doc/m11-provider-model-key-ui.md` (F1–F6).
Summary:

- The catalog and the model factory already do the heavy lifting
  (`model_catalog.PROVIDERS`, `fetch_models`, `build_model(...
  api_key_override=...)`). M11 is mostly glue.
- Two new HTTP endpoints (`GET /api/providers`,
  `GET /api/providers/{id}/models`) + a per-run override on
  `POST /api/runs` cover the wire layer.
- Six new files / five edited files on the SPA side.
- Total ~750 LOC, all additive. No public-API renames.

### Key design choices

- **Keys are passed in the request body**, not headers. Loopback
  only, simpler than inventing a header convention. Server stores
  them only in `Run.api_key_value` for the lifetime of the run.
- **Keys are stored in browser `localStorage`** under
  `smolcode.keys.v1`. Cleared by `localStorage.clear()`. Server
  never persists them.
- **The catalog endpoint reads `os.environ`** to report
  `key_state`. To use a different key, the user enters it in the
  GUI; the server merges it into the keys dict when calling
  `fetch_models` and `build_model`. This way `OPENCODE_GO_APIKEY`
  in `.env` and a user-typed `OPENAI_API_KEY` both work without
  restart.
- **`extract_keys()` validates the env-var name shape**
  (`*_API_KEY` / `*_APIKEY` / `HF_TOKEN`) so the client can't
  stuff arbitrary fields into the dict.
- **`POST /api/runs` stays backwards-compatible** — `provider`,
  `model`, `keys` are all optional. Without them the run uses
  `settings.provider` / `settings.model` exactly as before.

## Decision

Ship M11 as three short sub-milestones, each independently testable
and each leaving the existing 667 tests green.

| # | Name | Scope | LOC (est.) | Done when |
|---|---|---|---|---|
| **M11.1** | Backend | `keys.py`, `schemas.py`, `api.py` (2 new endpoints + `start_run` extension), `runs.py`, `agent_runner.py`; 6 backend test files | ~330 backend + tests | All tests pass; `curl /api/providers` returns the 5 presets; `POST /api/runs` accepts the new fields |
| **M11.2** | Frontend | `lib/keysStore.ts`, `components/ProviderSelector.tsx`, `components/ApiKeyPanel.tsx`, `api.ts`, `App.tsx`, `components/RunComposer.tsx`, `index.css` | ~420 | `pnpm build` PASS; manual GUI smoke passes |
| **M11.3** | Polish + regression | `ruff` + `pnpm build` + full pytest + live e2e smoke | ~0 (verification only) | Full suite green; live run with a key override completes |

Each sub-milestone is sized to fit in one focused work session.
M11.1 must land before M11.2 (SPA needs the endpoints). M11.3 is
verification-only and can run as the last commit before sign-off.

## Rejected alternatives

- **Server-side key vault (sqlite/json file under `.smolcode/`).**
  Rejected: violates the "keys never touch disk" invariant in
  `docs/security.md §8`. Also adds a real auth/ACL surface that v1
  doesn't need.
- **Header-based key transport (`X-Smolcode-Keys: OPENAI_API_KEY=…`).**
  Rejected: CORS preflight on loopback adds noise without a real
  benefit; body field is simpler.
- **MCP-style JSON-RPC for the provider catalog.** Rejected: the
  catalog is a tiny GET, not a stateful session.
- **Ship a separate "Settings" page instead of an inspector pane
  card.** Rejected: the user said "dropdown list for provider and
  models" and "add his api key for provider" — both fit naturally in
  the existing header + inspector layout.
- **Auto-refresh model list on every provider change.** Rejected:
  the catalog already has a 1-hour TTL (`model_catalog._CACHE_TTL_S`).
  A manual refresh button is enough for v1.

## Code Impact

See `research_doc/m11-provider-model-key-ui.md` "Code Impact" section
for the per-file LOC budget. All changes are additive. The public
API surfaces that change:

- `RunStartRequest` adds 3 optional fields (provider, model, keys)
  → no client breakage (FastAPI ignores extra fields on request;
  the SPA is updated to send them).
- Two new endpoints added to `api.py` → SPA is the only consumer.
- New components in `web/src/components/` → no existing component
  renamed.

## Acceptance gates

- `ruff check src` PASS, `ruff format --check src` PASS.
- `pytest src/smolcode/tests` PASS, coverage ≥ 80 %.
- `pnpm build` PASS (no TS / oxlint errors).
- `curl http://127.0.0.1:7860/api/providers` returns the 5 known
  presets with `key_state` matching the env.
- `curl -X POST http://127.0.0.1:7860/api/runs -H 'Content-Type:
  application/json' -d '{"task":"hi","tier":"restricted",
  "provider":"openai","model":"gpt-4o-mini",
  "keys":{"OPENAI_API_KEY":"sk-test"}}'` returns 201 (stub model
  path — the real key is never sent to a real provider from a test).
- Manual: open http://127.0.0.1:7860/, enter an OpenAI key in the
  inspector pane, pick `openai` + `gpt-4o-mini`, run a task, see
  the SSE stream with the chosen provider/model.

## Security checklist

- [ ] Keys never written to disk by the server.
- [ ] Keys never written to disk by the browser outside localStorage.
- [ ] `extract_keys` rejects non-`*_API_KEY` / `*_APIKEY` / `HF_TOKEN`
  names.
- [ ] `ProviderOut.key_state` returns only `'set'` / `'missing'`,
  never the value.
- [ ] `Run.api_key_value` is `str | None`; the runner does not log
  the `Run` object.
- [ ] `redact.py` patterns cover all known prefixes; request bodies
  are not logged.
- [ ] `ALLOWED_BIND_HOSTS` unchanged.

## References

- `research_doc/m11-provider-model-key-ui.md` — full plan with F1–F6
  and per-file LOC budget.
- `smolcode/src/smolcode/model_catalog.py` — `PROVIDERS`,
  `get_providers`, `fetch_models`.
- `smolcode/src/smolcode/models.py:build_model` — `api_key_override`.
- `smolcode/src/smolcode/config.py:Settings.with_overrides` — chain
  overrides onto the base settings for one run.
- `docs/decisions/0010-gui-design.md` — SPA 3-pane layout + header
  dropdown pattern.
- `docs/roadmap.md` — M0–M10 status; M11 entry lands here at
  the end of M11.3.

---

## Ship log

**2026-08-22 — M11 SHIPPED end-to-end.**

- **M11.1** (backend): 6 new + 1 extended test file; 70 new tests
  (737 total); `pnpm build` not yet applicable; `GET /api/providers`
  returns the 5 presets; `POST /api/runs` accepts the new fields.
- **M11.2** (frontend): `web/src/lib/keysStore.ts`,
  `web/src/components/ProviderSelector.tsx`,
  `web/src/components/ApiKeyPanel.tsx`; edits to `web/src/api.ts`,
  `web/src/App.tsx`, `web/src/components/RunComposer.tsx`,
  `web/src/index.css`; `pnpm lint` 0 errors + 4 stylistic warnings;
  `pnpm build` 220.34 kB JS / 13.07 kB CSS in 147 ms.
- **M11.3** (polish + regression): full pytest 737 passed in ~102 s;
  lint + build still green; live e2e `POST /api/runs` w/ M11 fields
  completed `{"result":"108"}`; Vite dev proxy verified end-to-end;
  Microsoft Edge headless screenshots at 4K / laptop / mobile; 20/20
  keysStore unit tests green; no API-key leak in either response body
  or `server.log`.

User-facing writeup: `../docs/m11-ui.md`.
Roadmap entry: `../docs/roadmap.md` (test table row M11 = 70 new / 737 total).
