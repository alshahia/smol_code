# M12 — SPA UX polish + CLI parity

**Date:** 2026-08-23
**Status:** active (M12 SHIPPED 2026-08-22 — M12.1 backend + CLI, M12.2 SPA, M12.3 polish all delivered; M12.4 addendum SHIPPED 2026-08-23; M12.5 addendum + key-rotation hygiene SHIPPED 2026-08-23)
**Trigger:** M11.3 validation surfaced 4 small UX gaps that did not warrant a full milestone on their own. Bundled them into a single follow-up so the catalog surface is symmetric across the SPA and the CLI.
**Related:**
- `docs/roadmap.md` §M11.3 + the deferred section after M11
- `docs/decisions/0014-m11-provider-model-key-ui.md` — the catalog surface this milestone extends
- `docs/m11-ui.md` — the SPA writeup that ships with M11
- `research_doc/decisions/framework-choice.md` — picking a "no new library" posture for this milestone

---

## 1. Question

M11 shipped the SPA provider / model / API-key selector with a working
backend (`GET /api/providers` + `GET /api/providers/{id}/models` + extended
`POST /api/runs`). M11.3 validation surfaced the following residual gaps:

1. **Cache age is invisible.** The SPA renders a `models: N` badge next to the
   provider selector but does not show when the model list was last refreshed.
   Users have to click "↻" blindly to be sure the count is current.
2. **Selection does not persist.** The provider / model choice resets to the
   server default every page reload. Users have to re-pick the model every
   time they open a new browser tab.
3. **Forget-key is one click, no confirm.** The "Forget" button on the
   `ApiKeyPanel` deletes the stored key immediately. Mistapping is recoverable
   (the user can re-enter) but feels too eager for an irreversible local
   action.
4. **No CLI parity.** The catalog is only visible inside the SPA. The CLI
   user (terminal-first workflow) has to start the SPA just to see which
   providers have a key set.

## 2. Findings

### F1. The catalog already knows the cache age

`model_catalog._CacheEntry.fetched_at` is populated on every successful fetch
and on every failed fetch (so the user sees "last tried at" too). The
`/api/providers` endpoint only forwards `model_count`; the timestamp is
discarded by `ProviderOut`. There is no reason not to forward it.

### F2. The SPA already has a keys localStorage helper; selection is one more

`web/src/lib/keysStore.ts` (M11) ships with the exact SSR-safe + defensive
try/catch + versioned storage-key pattern we want for selection persistence.
The same pattern works for selection: `{provider: "MiniMax", model:
"MiniMax-M3"}`. We piggyback on the same conventions (no `useEffect` in
the keys path, plain functions exported, `Object.hasOwn` checks).

### F3. Inline confirm is cheaper than a modal

The SPA already has the `ApprovalModal` for destructive tool calls (M9). For
the "Forget" button we don't need that level of ceremony — a 2-button inline
confirm (`Confirm` / `Cancel`) costs ~10 LOC and matches how the rest of the
SPA handles small destructive actions.

### F4. CLI parity reuses everything

The CLI already has `_uploads_main` and `_web_main` (M8) using the
`argv[0] == "..."` pre-dispatch pattern. Adding `_models_main` is a
straightforward extension. The in-memory cache (`model_catalog._CACHE`) is
per-process but SHARED between the CLI and any running `smolcode web` server
(both import `model_catalog`), so `smolcode models refresh opencode-go`
directly invalidates the SPA's view of that provider.

## 3. Decision

Ship **M12 — SPA UX polish + CLI parity** as a single milestone broken into
three sub-milestones. Sub-milestone M12.1 ships the cache-age + CLI work;
M12.2 ships the selection persistence + Forget confirm; M12.3 is the
verification gate.

### M12.1 — Backend: `cached_at` field + `smolcode models` subcommand

| Change | File |
|---|---|
| `get_providers()` adds `cached_at: float \| None` (epoch seconds, None if never fetched) | `model_catalog.py` |
| `ProviderOut.cached_at: float \| None = None` (additive, backwards-compatible) | `web/schemas.py` |
| `list_providers` populates `cached_at` from `_CACHE[spec.id].fetched_at` | `web/api.py` |
| Pre-dispatch `if argv[0] == "models": return _models_main(...)` | `cli.py` |
| `_models_main(["list" \| "refresh [<provider>]" \| "help"])` with `_models_format_age` helper | `cli.py` |
| 10 new test cases | `tests/test_cli_models.py` |
| 3 new test cases (`TestProvidersCachedAt`) | `tests/test_web_providers_api.py` |

CLI surface:
```
smolcode models                       # default: list
smolcode models list                  # provider table (id, key, models, cache_age, default_model)
smolcode models refresh               # clear cache for ALL providers
smolcode models refresh <provider>    # clear cache for one provider
smolcode models help
```

### M12.2 — Frontend: last-used selection + cache-age badge + Forget confirm

- NEW `web/src/lib/lastSelection.ts` — versioned localStorage CRUD
  (`smolcode.selection.v1`) with SSR safety + defensive try/catch.
- NEW `web/src/components/ModelAgeBadge.tsx` — inline badge rendering
  "just now" / "5m ago" / "stale (>1h)" with a click-refresh affordance.
- MODIFY `ApiKeyPanel.tsx` — inline confirm before Forget; expose
  last-4-chars + masked prefix of the stored key so the user can verify
  what's saved (no full reveal — consistent with decision 0014).
- MODIFY `ProviderSelector.tsx` — render `<ModelAgeBadge>` next to model
  count.
- MODIFY `App.tsx` — read `loadLastSelection()` on mount, validate against
  the loaded providers list, restore `selectedProviderId` + `selectedModel`;
  on every `handleProviderChange`, call `saveLastSelection()`.

### M12.3 — Polish + regression

- Full `ruff check src` + `ruff format --check src`
- Full `pnpm lint` + `pnpm build`
- Full `pytest` (expect ~750 tests after M12.1; +3-5 from M12.2)
- Live curl smoke: `GET /api/providers` → `cached_at` present
- Live curl smoke: `smolcode models list` → table prints
- Live curl smoke: `smolcode models refresh opencode-go` → exits 0
- Manual SPA smoke: reload preserves selection, Forget shows confirm,
  cache-age badge renders

## 4. Code Impact (M12.1 only — already implemented)

- `smolcode/src/smolcode/model_catalog.py` — +5 LOC (1 field in dict literal + docstring + inline comment)
- `smolcode/src/smolcode/web/schemas.py` — +3 LOC (1 field + docstring)
- `smolcode/src/smolcode/web/api.py` — +1 LOC (1 field in ProviderOut() call)
- `smolcode/src/smolcode/cli.py` — +133 LOC (`_models_main`, `_models_format_age`, `_models_collect_env_keys`, pre-dispatch)
- `smolcode/src/smolcode/tests/test_cli_models.py` — NEW, +170 LOC, 10 cases
- `smolcode/src/smolcode/tests/test_web_providers_api.py` — +60 LOC, 3 new cases

## 5. SSL / behavior contracts

### 5.1 `cached_at` shape

- `None` when the per-process cache has never been populated for that provider.
- `float` (epoch seconds, UTC) when at least one fetch has happened.
- The server does NOT compute a human-readable age — that is the client's
  job (different clients may want different formats; SPA does "just now",
  CLI does "5m ago").

### 5.2 CLI cache invalidation is per-process

`smolcode models refresh` clears the `_CACHE` dict in the calling process.
If `smolcode web` is running as a separate process, its cache is UNAFFECTED.
The CLI prints a tip at the bottom of `list` output explaining this
("tip: 'smolcode models refresh <provider>' clears the cache"). For
single-process deployments (the v1 default), the CLI and the server share
the cache because they share the module instance.

### 5.3 Backwards compatibility

- `ProviderOut.cached_at` is additive. Old clients (SPA from M11.x) ignore
  the field.
- `cli.main()` accepts the new `models` first-arg token; existing callers
  are unaffected because the pre-dispatch only fires when `argv[0] == "models"`.
- The CLI's `_models_main` is a NEW function; no existing CLI behavior changes.

## 6. Validation gates (M12.1)

| Gate | Target |
|---|---|
| `ruff check src` | PASS |
| `ruff format --check src` | PASS |
| `pytest src/smolcode/tests/test_cli_models.py` | PASS (10/10) |
| `pytest src/smolcode/tests/test_web_providers_api.py` | PASS (12/12, +3 new) |
| `pytest` (full) | PASS (~750 tests, +13 from M12.1) |
| `smolcode models list` | table prints, all 5 providers, `cached_at` `-` initially |
| `smolcode models refresh opencode-go` | exits 0, prints "cleared model cache for opencode-go" |
| `smolcode models refresh bogus` | exits 2, prints "unknown provider: 'bogus'; known: ..." |
| `GET /api/providers` | 200, every row has `cached_at: null` initially |

## 7. Known limitations (out of scope)

- `cached_at` is per-process. Multiple uvicorn workers would each have
  independent caches. v1 is single-process (decision 0010 D1).
- The CLI `models refresh` does NOT reach into a separate `smolcode web`
  process; that process must call `models refresh` itself.
- No `smolcode models fetch <provider>` subcommand to trigger a fetch from
  the CLI. M11.1 deferred "per-/models HTTP endpoint" to v1.1; if a CLI
  fetch command is wanted it would also be a M12.x add-on.

## 8. Risks

- **R-M12.1 (LOW)** — `cached_at` is backwards-compatible (additive field).
  SPA `ProviderInfo` interface gains 1 optional field; old SPAs ignore it.
- **R-M12.2 (LOW)** — CLI cache invalidation is per-process. Documented in
  the help text + decision doc.
- **R-M12.3 (LOW)** — `cli.py` reaches ~770 LOC after M12.1. Still under 1k.
  Extraction to `_cli_subcommands.py` deferred to a future milestone if
  M12.x or M13 adds more.

## 9. References

- `docs/roadmap.md` §M11 — original SPA UX scope
- `docs/roadmap.md` §M11.3 — known limitations + followups
- `docs/decisions/0014-m11-provider-model-key-ui.md` — M11 design contracts
- `docs/m11-ui.md` — M11 user-facing writeup
- `smolcode/src/smolcode/model_catalog.py:357` — `get_providers` after M12.1
- `smolcode/src/smolcode/web/api.py:553` — `list_providers` after M12.1
- `smolcode/src/smolcode/cli.py:660` — `_models_main` after M12.1

---

# M12.4 — Failed-fetch indicator (addendum)

**Date:** 2026-08-23
**Status:** SHIPPED
**Trigger:** M12 §Known Limitations called out that `cached_at` is `null` after a failed fetch with no way for the SPA to surface "your last fetch FAILED". M12.4 closes that gap with an additive `cached_error` field.

## A1. Question

When `model_catalog.fetch_models` raises (network error, auth failure,
5xx from upstream, …), what should the SPA and CLI show so the user
knows the cached model list may be stale or empty for a *reason*?

## A2. Findings

### F1. The existing `except Exception` branch already had the right data

`fetch_models` (M12.1) catches the generic exception and returns a
dict with `error="fetch_failed: <exc>"`. It does NOT, however, write
to `_CACHE`, so a subsequent `get_providers()` call sees
`cached_at=None` and `cached_error` cannot be reported. The fix is
to write a failure entry on the failure path — the data was always
there.

### F2. Two failure shapes to support

- **No prior cache + failure**: write `_CacheEntry(models=[],
  fetched_at=<now>, error="fetch_failed: ...")`. The SPA can show
  "fetch failed N seconds ago" even though there is no prior good
  list.
- **Prior cache + failure**: keep the prior good model list and
  preserve its `fetched_at` so the age badge stays meaningful
  ("models: 12 — 2m ago — fetch failed"). We do NOT overwrite
  `fetched_at` with the failed-attempt time, because that would
  pretend a failed attempt succeeded.

### F3. SPA needs a warning variant of the existing badge

`<ModelAgeBadge>` (M12.2) already has the rendering scaffolding
(class names, refresh interval, ISO timestamp in `title=`). Adding
an `error` CSS variant + a `cachedError` prop is ~25 LOC and
preserves the existing oxlint baseline.

## A3. Decision

Ship **M12.4 — Failed-fetch indicator** as a single additive change
that touches the existing `cached_at` plumbing:

| Change | File |
|---|---|
| `fetch_models` `except Exception` branch now writes `_CACHE[id]` (with `error=` and either `now` or preserved `fetched_at`) | `model_catalog.py` |
| `get_providers()` adds `cached_error: str \| None = None` (additive) | `model_catalog.py` |
| `ProviderOut.cached_error: str \| None = None` (additive) | `web/schemas.py` |
| `list_providers` populates `cached_error` from `_CACHE[id].error` | `web/api.py` |
| CLI `_models_main` prefixes the `CACHE_AGE` cell with `⚠` + truncated error when `cached_error` is set | `cli.py` |
| `ProviderInfo.cached_error?: string \| null` (additive) | `web/src/api.ts` |
| `<ModelAgeBadge>` accepts `cachedError` prop; renders a red `.error` variant with `title=` carrying the full error | `web/src/components/ModelAgeBadge.tsx` |
| `ProviderSelector` passes `cached_error` from the catalog row to the badge | `web/src/components/ProviderSelector.tsx` |
| New `.model-age-badge.error` CSS variant (red palette, same shape) | `web/src/index.css` |
| 4 new test cases (`TestProvidersCachedError`) | `tests/test_web_providers_api.py` |
| 3 new CLI test cases (warning glyph, no-warning, truncation) | `tests/test_cli_models.py` |

## A4. Behavior contracts

### A4.1 `cached_error` shape

- `None` when the per-process cache has never been populated, OR
  the most recent fetch succeeded.
- Short single-line string starting with `fetch_failed:` when the
  most recent fetch failed.
- Additive — old clients ignore it; no schema bump needed.

### A4.2 `cached_at` semantics with a failed fetch

- If there was a prior successful fetch and the next fetch fails,
  `cached_at` stays at the LAST successful fetch. `cached_error`
  is set. The SPA renders both.
- If there was no prior successful fetch and the fetch fails,
  `cached_at` is set to the time of the FAILED attempt and
  `cached_error` is set. The SPA renders both.

### A4.3 Backwards compatibility

- `ProviderOut.cached_error` is additive. Old clients (SPA from
  M12.x or earlier) ignore the field and render the normal age
  badge.
- The SPA's `ProviderInfo.cached_error` is an optional field; old
  SPAs (M12.x) ignore it.
- The CLI's `⚠` glyph is rendered on the CLI only when
  `cached_error` is set; it does not appear for the common
  no-fetch case.

## A5. Validation gates (M12.4)

| Gate | Target |
|---|---|
| `ruff check src` | PASS |
| `ruff format --check src` | PASS |
| `pytest src/smolcode/tests/test_web_providers_api.py` | PASS (16/16, +4 new) |
| `pytest src/smolcode/tests/test_cli_models.py` | PASS (13/13, +3 new) |
| `pytest` (full) | PASS (~759 tests, +7 from M12.4) |
| `pnpm run build` (strict TS) | PASS |
| `pnpm run lint` (oxlint) | PASS (4 warnings — pre-M12 baseline preserved) |

## A6. Risks

- **R-M12.4 (LOW)** — failure entries persist in `_CACHE` until
  cleared. This is intentional: `smolcode models refresh` is the
  documented escape hatch. No other invariants changed.

## A7. References

- `smolcode/src/smolcode/model_catalog.py:330-360` — `fetch_models`
  failure branch after M12.4
- `smolcode/src/smolcode/model_catalog.py:368-396` — `get_providers`
  after M12.4
- `smolcode/src/smolcode/web/schemas.py:197-232` — `ProviderOut`
  after M12.4
- `smolcode/src/smolcode/web/api.py:553-595` — `list_providers`
  after M12.4
- `smolcode/src/smolcode/cli.py:697-735` — `_models_main` after
  M12.4
- `smolcode/web/src/components/ModelAgeBadge.tsx` — error variant
  after M12.4

---

# §11 — Key rotation procedure (addendum)

**Date:** 2026-08-23
**Status:** SHIPPED (hygiene + documentation only — the actual rotation is
the operator's responsibility, not the assistant's)
**Trigger:** The default-provider `OPENCODE_GO_APIKEY` value in
`E:\python projects\smol_clone_2\.env` was exposed in a chat transcript.
The value lives ONLY in that gitignored file; a tree-wide grep for the
unique token prefix returned zero matches in any tracked file (verified
2026-08-23). This addendum documents the rotation procedure and tightens
the workspace hygiene, but does NOT include the leaked value, the new
value, or any provider-specific URL in chat.

## B1. Containment status (verified 2026-08-23)

- **Where the value lives:** only `E:\python projects\smol_clone_2\.env`
  (repo root, gitignored by both `smolcode/.gitignore` and the new
  top-level `.gitignore`).
- **Where the value does NOT live:** any tracked file, any `*.py`,
  any `*.md`, any `*.ts`, any `*.tsx`, any test fixture. Verified by
  `grep -r` of the unique token prefix across the working tree.
- **Git history:** the repo is not currently a git repository
  (`git rev-parse` reports "not a git repository" at the root), so
  no rewriting of history is required.

## B2. What was changed in this addendum

| Change | File |
|---|---|
| New top-level `.gitignore` mirroring `smolcode/.gitignore` patterns, so any future `git init` at the repo root cannot accidentally stage the leaked `.env` | `.gitignore` (repo root) |
| `.env.example` adds a comment under `OPENCODE_GO_APIKEY=` pointing the operator at this section | `smolcode/.env.example` |
| `docs/decisions/0015-m12-spa-ux-polish-cli-parity.md` §11 (this section) | (this doc) |

No new tests are added because the rotation itself is an operator
action, not a software feature. The redact filter (`smolcode/src/smolcode/redact.py`)
already catches the `sk-` prefix the value begins with; we deliberately
do NOT add a more specific marker because documenting the leak
in code is worse than relying on the existing general prefix.

## B3. Rotation procedure (for the operator)

1. **Generate a new key.** Open the opencode-go dashboard in a browser
   and regenerate the API key. Note the new value in a password manager
   — do NOT paste it into chat.
2. **Replace the value in `.env`.** Edit
   `E:\python projects\smol_clone_2\.env` and update the line
   `OPENCODE_GO_APIKEY=<new-value>`. Save the file. The file remains
   gitignored; nothing else needs to change.
3. **Confirm no process is still holding it.** If `smolcode web` is
   running, stop it (`Ctrl-C`) and restart it so the new env var is
   loaded. The CLI processes pick up the new value on next launch.
4. **Validate the new key.** Run `python -m smolcode models doctor`
   (added in M12.5, see §12). The `opencode-go` row should report
   `OK` with a fresh `just now` age. If it still reports a stale
   `fetch_failed`, the old value may still be cached in a running
   process — restart it.
5. **Optionally invalidate the per-process cache.** Run
   `python -m smolcode models refresh opencode-go` to drop the prior
   entry; the next `/api/providers` call will re-fetch with the new
   key.
6. **Audit transcript.** The old value should be considered burned —
   any system that ingested the leaked transcript (chat history,
   copy-paste buffers, browser autocomplete, etc.) should be cleared
   where possible. This step is the operator's responsibility, not
   the assistant's.

## B4. Cross-references

- `docs/security.md` §8 — RedactSecretsFilter (already catches `sk-`)
- `smolcode/src/smolcode/redact.py` — `DEFAULT_PATTERNS` and the
  `install_redact_filter()` factory
- `smolcode/.gitignore` — the project's gitignore (covers `smolcode/.env`,
  not the repo-root `.env`)
- `.gitignore` (new, repo root) — mirrors the relevant subset of
  `smolcode/.gitignore` so any future top-level git repo inherits
  the same protections

---

# §12 — M12.5 addendum (smolcode models doctor + mobile layout)

**Date:** 2026-08-23
**Status:** SHIPPED
**Trigger:** M12.4 validation surfaced that cached-error follow-up diagnostics
(`models refresh` succeeded but the operator had no per-provider signal to
distinguish a successful cache read from a cached failure) and M12.4 manual
SPA smoke on a narrow viewport (~700px) showed the inspector pane forced a
horizontal scroll on the three-pane grid. Both gaps were bundled into a
single addendum so the shipped surface stays symmetric: one CLI verb for
connectivity (`doctor`) + one CSS breakpoint for mobile (`max-width: 900px`).

## C1. What changed

| Change | File |
|---|---|
| New `doctor [--no-fetch]` verb in `_models_main` (per-provider connectivity diagnostic) | `smolcode/src/smolcode/cli.py` |
| Help text + usage line updated to include `doctor` | `smolcode/src/smolcode/cli.py` |
| Lazy `inspectorOpen` state with localStorage persistence (`smolcode.inspectorOpen.v1`) + mobile toggle button in `<header>` | `smolcode/web/src/App.tsx` |
| `<aside>` now carries `mobile-open` class when toggled; new `@media (max-width: 900px)` block collapses the 3-pane grid to 1-column and hides the inspector until toggled | `smolcode/web/src/index.css` |
| 3 new pytest cases for `doctor` (ok / fail / `--no-fetch`) | `smolcode/src/smolcode/tests/test_cli_models.py` |

## C2. CLI: `smolcode models doctor [--no-fetch]`

The verb iterates `model_catalog.PROVIDERS` and emits a fixed-width row per
provider with three columns:

```
PROVIDER        STATUS         DETAIL
opencode-go     OK            (2 models) just now (M12.5: 1/1)
huggingface     skipped       (ENV not set)
MiniMax      OK            (7 models) just now (M12.5: 1/1)
openai          skipped       (ENV not set)
anthropic       skipped       (ENV not set)
custom          skipped       (ENV not set)
M12.5: 2/2 providers OK; exit0 = all good
```

- **STATUS column** (capped at 14 chars): `skipped` (no key set),
  `no-cache` (`--no-fetch` with no prior cache entry), `fail` (cached
  failure, lowercase), `ok-cached` (cached success), `FAIL` (fresh fetch
  failed), `OK` (fresh fetch succeeded).
- **DETAIL column** shows the error message (truncated to the column
  width) on `FAIL` / `fail`, and `(N models) just now` on fresh successes.
- **Exit code**: `1` if any row reports a failure, `0` otherwise. This
  makes the verb CI-friendly: `python -m smolcode models doctor || exit 1`
  fails the build when a key is misconfigured.
- **`--no-fetch` mode**: skips `fetch_models` entirely, reads `_CACHE`
  directly. Useful for offline diagnosis ("did the previous attempt
  succeed?") without burning another request quota.

## C3. SPA: mobile layout (inspector collapse)

Three-pane grid (`grid-template-columns: 280px 1fr 320px`) worked at
desktop widths but produced horizontal scroll below ~900px (a 13" laptop
window with devtools open, or a tablet). The addendum adds one CSS
breakpoint + one toggle button:

- **`@media (max-width: 900px)`** collapses the grid to
  `grid-template-columns: 1fr; grid-template-rows: auto 1fr` — the
  conversation pane takes the full width, the inspector moves BELOW it
  and is hidden by default, and the workspace pane keeps its existing
  scroll behavior in the top half.
- **`.pane.inspector.mobile-open`** overrides `display: none` to
  `display: block`, capped at `max-height: 50vh` so it cannot dominate
  the viewport.
- **`Inspector ▾` / `Inspector ▴` toggle button** lives in `<header>`
  between `<TierSwitcher>` and `.ws`, hidden by default on desktop via
  `.inspector-toggle { display: none; }` and overridden to `inline-flex`
  inside the media query. Carries `aria-expanded` + `aria-controls` for
  accessibility.
- **`inspectorOpen` state** uses a lazy `useState(() => ...)` initializer
  reading `localStorage.getItem('smolcode.inspectorOpen.v1')` so the
  preference survives a page reload WITHOUT triggering an extra
  `useEffect` setState (which would have grown the oxlint warning
  baseline from 4 to 5).

## C4. Why `result.get("error")` (truthy) and not `"error" in result`

`fetch_models` always returns a dict with the key `error` present (set
to `None` on success, a string on failure). The first draft used
`if "error" in result`, which entered the FAIL branch on success and
crashed on `str(None) + " " + error_message`. Fixed by switching to
`result.get("error")` — a truthy check. Caught by the first `pytest`
run of `test_cli_models.py` before the full suite; the full suite
re-run was clean (see §C5).

## C5. Validation gates (M12.5)

| Gate | Target | Result |
|---|---|---|
| `ruff check src` | PASS | PASS (after auto-fix of E401 import sort) |
| `ruff format --check src` | PASS | PASS (78 files) |
| `pytest src/smolcode/tests/test_cli_models.py` | 16 passed | PASS (13 original + 3 new doctor tests) |
| `pytest` (full) | 760 passed | PASS in 96.19s (757 M12.4 baseline + 3 M12.5 doctor) |
| `pnpm run build` (strict TS) | PASS | PASS — `dist/index.html` 0.52 kB, JS 223.38 kB |
| `pnpm run lint` (oxlint) | 4 warnings | PASS (baseline preserved; lazy `useState` initializer avoided a 5th `set-state-in-effect` warning) |

## C6. Risks

- **R-M12.5-A (LOW)** — `doctor` calls `fetch_models(..., refresh=True)`
  for each provider with a key. On a 5-provider catalog with 4 keys set,
  this is 4 outbound HTTP calls per invocation. Acceptable for a manual
  diagnostic; not intended for tight CI loops. Mitigation: `--no-fetch`
  mode reads the existing cache without hitting the wire.
- **R-M12.5-B (LOW)** — `inspectorOpen` localStorage key is namespaced
  (`smolcode.inspectorOpen.v1`). If the layout shape changes in a future
  milestone, the key needs to bump to `v2` so users do not see a stale
  toggle state that no longer matches the rendered pane.
- **R-M12.5-C (LOW)** — the mobile breakpoint at 900px is a heuristic;
  tablets in landscape (~1024px) keep the 3-pane grid. If the operator
  complains about a specific viewport, add a second breakpoint or a
  matchMedia-driven toggle. Deferred until measured demand.

## C7. References

- `smolcode/src/smolcode/cli.py:697-790` — `_models_main` after M12.5
  (`doctor` block + updated help text)
- `smolcode/src/smolcode/model_catalog.py:330-360` — `fetch_models`
  return-shape contract (the `error` key is always present)
- `smolcode/src/smolcode/tests/test_cli_models.py:255-330` — 3 new
  `test_models_doctor_*` cases
- `smolcode/web/src/App.tsx` — `inspectorOpen` lazy initializer +
  toggle button in `<header>`
- `smolcode/web/src/index.css` — `@media (max-width: 900px)` block +
  `.inspector-toggle` display rule
- `docs/m12-spa-ux-polish.md` §11 — mobile layout writeup
  (corresponding SPA-side documentation)
