# M12 — SPA UX polish + CLI parity (v1.3)

**Date:** 2026-08-22 (initial); 2026-08-23 (M12.4 addendum); 2026-08-23 (M12.5 addendum — `models doctor` + mobile layout)
**Status:** active (M12 SHIPPED — M12.1 backend + CLI, M12.2 SPA, M12.3 polish, M12.4 failed-fetch indicator, M12.5 `models doctor` + mobile inspector collapse)
**Related:**
`../docs/decisions/0015-m12-spa-ux-polish-cli-parity.md`,
`../docs/m11-ui.md` (the M11 writeup that M12 extends),
`smolcode/src/smolcode/model_catalog.py`,
`smolcode/src/smolcode/web/api.py`,
`smolcode/src/smolcode/cli.py`,
`smolcode/web/src/lib/lastSelection.ts`,
`smolcode/web/src/components/ModelAgeBadge.tsx`,
`smolcode/web/src/components/ProviderSelector.tsx`,
`smolcode/web/src/components/ApiKeyPanel.tsx`,
`smolcode/web/src/App.tsx`.

---

## 1. What is this?

M12 closes four small UX gaps that M11.3 validation surfaced on the
existing provider / model / API-key selector. Nothing here is a new
feature; it's all polish that makes the existing surface feel right:

| Gap | Fix |
|---|---|
| **Cache age is invisible** — the SPA shows `models: N` but no "when" | New `cached_at` field on `GET /api/providers`; SPA renders it as a pill (`just now` / `5m ago` / `2h ago`) that updates every 30s |
| **Selection does not persist across reloads** | New `localStorage["smolcode.last.v1"]` (browser-only, versioned, SSR-safe); SPA restores the last `(provider, model)` on mount |
| **Forget-key is one click, no confirm** | Two-step `Forget → Confirm forget` with a 3-second confirmation window and `onBlur` cancel |
| **No CLI parity for the catalog** | New `smolcode models list \| refresh [<provider>] \| help` subcommand |

The CLI subcommand reuses the **same in-process cache** as any running
`smolcode web` server (both import `model_catalog`), so
`smolcode models refresh opencode-go` from the terminal directly
invalidates the SPA's view of that provider.

---

## 2. Quick start

### 2.1 See the catalog from the CLI

```bash
# All 5 providers, columns: id / key / models / cache_age / default_model
.venv\\Scripts\\python.exe -m smolcode models

# Same table, explicit subcommand
.venv\\Scripts\\python.exe -m smolcode models list

# Force-clear the cache for one provider (in-process)
.venv\\Scripts\\python.exe -m smolcode models refresh opencode-go

# Force-clear the cache for ALL providers
.venv\\Scripts\\python.exe -m smolcode models refresh

# Help text
.venv\\Scripts\\python.exe -m smolcode models help
```

Example output (after a few fetches):

```
PROVIDER         KEY              MODELS  CACHE_AGE   DEFAULT_MODEL
opencode-go      OPENCODE_GO_*    -       -           deepseek-v4-flash
MiniMax       MINIMAX_*         12      2m ago      MiniMax-M3
openai           OPENAI_*         -       -           gpt-4o-mini
anthropic        ANTHROPIC_*      8       5m ago      claude-sonnet
custom           CUSTOM_*         -       -           custom-model

tip: 'smolcode models refresh <provider>' clears the cache for that provider
```

The `cache_age` column uses the same bucket formatter as the SPA:
`just now` (<30s), `Ns ago` (<60s), `Nm ago` (<1h), `Nh ago`
(<1d), `Nd ago` (≥1d), `-` (never fetched).

### 2.2 See the cache age in the SPA

Open `http://127.0.0.1:7860/` (production build) or
`http://localhost:5173/` (dev mode). The provider row now shows a
small **purple pill** to the right of the model count:

```
[opencode-go ▾]  [models: 12]  [2m ago ↻]
```

Hover the pill for the exact timestamp (ISO 8601, UTC). Click the
`↻` refresh button (in the same row) to force a fresh fetch; the
pill updates immediately because `ProviderSelector.refresh()` re-lists
`/api/providers` after a successful refresh.

### 2.3 Selection persists across reloads

1. Pick **opencode-go** in the provider dropdown.
2. Type `deepseek-v4-flash` in the model input.
3. Reload the page (`F5`).

After reload, both the dropdown and the model input come back pre-filled
from `localStorage["smolcode.last.v1"]`. The provider is validated
against the catalog on restore — if it's no longer in the catalog, the
SPA falls back to the server default.

### 2.4 Two-step Forget confirm

1. In the API-key panel for any provider with a stored key, click
   **🔑 Forget** once.
2. The button changes to **Confirm forget** (red, `btn-danger`) and
   starts a 3-second window.
3. Click **Confirm forget** again within those 3 seconds to delete
   the key. If you don't click again, the button reverts to
   **🔑 Forget** (cancel-by-timeout).
4. If the button loses focus (`onBlur`) during the window, the
   pending confirm is cancelled.

A screen-reader announcement (`aria-live="polite"`) is wired so
keyboard-only users hear "Confirm forget to remove the stored key".

---

## 3. Environment variables (no new ones)

M12 introduces **no new env vars**. The new `smolcode models`
subcommand reads the existing 5-provider preset table from
`os.environ`, exactly like `GET /api/providers` does. The
`cached_at` field is computed at response time from
`model_catalog._CacheEntry.fetched_at`.

---

## 4. API surface (M12 + M12.4 additions)

| Endpoint | Method | Change |
|---|---|---|
| `/api/providers` | GET | **M12** additive: `cached_at` (`float \| null`, epoch seconds) per provider row |
| `/api/providers` | GET | **M12.4** additive: `cached_error` (`str \| null`) per provider row — short single-line error from the most recent failed fetch, else `null` |
| `/api/providers/{provider_id}/models` | GET | unchanged |
| `/api/runs` | POST | unchanged |

Both `cached_at` and `cached_error` are **additive** — old SPA
clients (M11.x) ignore them. No client-side breakage.

`ProviderOut.cached_at: float | None = None` and
`ProviderOut.cached_error: str | None = None` (Pydantic v2 schema)
keep both fields optional so JSON deserialisation of old test
fixtures without the fields still works.

---

## 5. CLI surface (M12 + M12.5 additions)

```
smolcode models                          # default: list
smolcode models list                     # provider table (id, key, models, cache_age, default_model)
smolcode models refresh                  # clear cache for ALL providers
smolcode models refresh <provider>       # clear cache for one provider
smolcode models doctor                   # M12.5: per-provider connectivity diagnostic (fresh fetch)
smolcode models doctor --no-fetch        # M12.5: read cache only (offline / no quota burn)
smolcode models help
```

The subcommand is pre-dispatched in `cli.main()` on
`argv[0] == "models"` BEFORE `argparse` runs, so it doesn't
collide with any flag-style invocation.

Exit codes:
- `0` — success (also: all providers OK in `doctor`)
- `2` — usage error (e.g. `smolcode models refresh bogus`)
- `1` — internal error / at least one provider failed in `doctor`

`smolcode models refresh` is **per-process**. If `smolcode web` is
running as a separate process, its cache is unaffected; run `smolcode
models refresh` from a second terminal pointing at the same Python
process to share the cache, or restart `smolcode web` to drop its
in-memory cache.

`smolcode models doctor [--no-fetch]` (M12.5) iterates all 5 providers
and prints one row per provider with three columns: `STATUS`
(`OK` / `FAIL` / `skipped` / `fail` / `no-cache` / `ok-cached`) and a
`DETAIL` column with the truncated error or `(N models) just now`.
Exits 1 if any row reports a failure, 0 otherwise — makes the verb
CI-friendly: `python -m smolcode models doctor || exit 1` fails the
build when a key is misconfigured. `--no-fetch` reads `_CACHE`
directly without burning upstream quota; useful for offline diagnosis
or after a process restart. See decision 0015 §12 for the full
contract.

---

## 6. Test count

M12 + M12.4 add **+20 backend tests** and **21 SPA smoke cases** to
the suite (no removals):

| Suite | Tests added |
|---|---|
| `test_cli_models.py` (M12.1 + M12.4 + M12.5) | 16 |
| `TestProvidersCachedAt` (M12.1, in `test_web_providers_api.py`) | 3 |
| `TestProvidersCachedError` (M12.4, in `test_web_providers_api.py`) | 4 |
| **Total backend** | **+23** |
| lastSelection.ts unit cases (tsx ad-hoc) | 10 |
| formatAge bucket boundaries (tsx ad-hoc) | 11 |
| **Total SPA smoke** | **21** |

| Stage | Total |
|---|---|
| End of M11 | 737 |
| After M12.1 | 750 |
| After M12.3 | 750 |
| After M12.4 | **759** (+7 from M12.4: 4 API + 3 CLI) |
| After M12.5 | **760** (+3 from M12.5: 3 doctor CLI) |

Full `pytest` run on M12.5 final: **760 passed in ~96s**.

Coverage remains ≥ 80 %.

---

## 7. Viewport behaviour

Verified at the same three viewport sizes used for M11.3 (plus M12.5
adds a tablet check):

| Viewport | M12 + M12.5 behaviour |
|---|---|
| 4K (3840 × 2160) | Cache-age pill renders cleanly to the right of `models: N`; selection restore works; full 3-pane grid (workspace + conversation + inspector) |
| Laptop (1440 × 900) | Pill renders inline; two-step Forget window fits; full 3-pane grid |
| Tablet (≈1024 × 768) | Still 3-pane grid (above the 900px breakpoint) |
| Narrow laptop (≈768 × 1024) | **M12.5** — collapses to a single column at `max-width: 900px`; inspector hides by default and reveals via the `Inspector ▾ / ▴` toggle in `<header>`; cap of `50vh` so it cannot dominate the viewport |
| Mobile (390 × 844) | Same as narrow laptop; header pills wrap; the inspector toggle is the only way to open the inspector pane |

---

## 8. Known limitations (out of M12 + M12.5 scope)

- **`cached_error` does NOT trigger an automatic retry** — the
  SPA just shows the warning badge so the user knows to click `↻`.
  Retrying is a deliberate user action.
- **CLI `models refresh` is per-process** — see §5.
- **No `smolcode models fetch <provider>`** subcommand. M11.1
  deferred the `/models` HTTP endpoint to v1.1; if a CLI fetch
  command is wanted it would also be a M12.x add-on.
- **Tablets in landscape (~1024px) still get the 3-pane grid** —
  the M12.5 breakpoint at 900px is a heuristic. Deferred to a
  later milestone if measured demand exists.
- **`oxlint` set-state-in-effect warnings (4)** — pre-existing
  baseline from M11; M12.2, M12.4, and M12.5 added 0 new warnings.

---

## 9. See also

- `../docs/decisions/0015-m12-spa-ux-polish-cli-parity.md` — full
  M12 design + rejected alternatives + per-file LOC budget; §11
  (key rotation), §12 (M12.5 addendum).
- `../docs/m11-ui.md` — M11 writeup (M12 extends this surface).
- `smolcode/src/smolcode/model_catalog.py:357` — `get_providers`
  after M12.1.
- `smolcode/src/smolcode/web/api.py:553` — `list_providers` after
  M12.1.
- `smolcode/src/smolcode/cli.py:697-790` — `_models_main` after
  M12.5 (`list` + `refresh` + `doctor [--no-fetch]`).
- `smolcode/web/src/lib/lastSelection.ts` — versioned localStorage
  store for `(provider, model)`.
- `smolcode/web/src/components/ModelAgeBadge.tsx` — cache-age pill.
- `smolcode/web/src/App.tsx` — `inspectorOpen` state +
  `Inspector ▾ / ▴` toggle (M12.5 mobile layout).
- `smolcode/web/src/index.css` — `@media (max-width: 900px)` block
  + `.inspector-toggle { display: none; }` default (M12.5).

---

## 10. M12.4 addendum — failed-fetch indicator

M12 §Known Limitations called out that `cached_at` after a failed
fetch is `null`, so the user can't tell "never fetched" apart from
"the last fetch FAILED". M12.4 fixes that by adding an additive
`cached_error` field.

### 10.1 What changed

- New `cached_error: str | None` field on each `ProviderOut` row.
  `null` on the happy path; a short single-line error string
  (e.g. `"fetch_failed: 401 Unauthorized"`) when the most recent
  fetch failed.
- CLI `smolcode models list` prefixes the `CACHE_AGE` cell with
  `⚠` + a 32-char truncated error when `cached_error` is set.
- SPA `<ModelAgeBadge>` renders a **red warning chip**
  (`! 2m ago · fetch failed`) when `cached_error` is set. Hover
  the chip to see the full error and the ISO timestamp of the
  failed attempt.

### 10.2 See it in the CLI

Seed a failure entry to simulate a failed upstream call:

```bash
# (run from a Python REPL with the same .venv as smolcode)
python -c "from smolcode import model_catalog; import time; \
  model_catalog._CACHE['opencode-go'] = model_catalog._CacheEntry( \
    models=[], fetched_at=time.time(), \
    error='fetch_failed: 401 Unauthorized')"

# Then list — note the ⚠ in the opencode-go row
.venv\Scripts\python.exe -m smolcode models list
```

Output:

```
PROVIDER         KEY              MODELS  CACHE_AGE       DEFAULT_MODEL
opencode-go      OPENCODE_GO_*    -       ⚠ just now (... MiniMax-M3
MiniMax          MINIMAX_*        12      -               MiniMax-M3
openai           OPENAI_*         -       -               gpt-4o-mini
anthropic        ANTHROPIC_*      8       5m ago          claude-sonnet
custom           CUSTOM_*         -       -               custom-model

tip: 'smolcode models refresh <provider>' clears the cache for that provider
     ⚠ in CACHE_AGE column = most recent fetch failed (M12.4)
```

The full error string is preserved in `_CACHE[provider_id].error`
until you run `smolcode models refresh opencode-go`.

### 10.3 See it in the SPA

1. Force a failure: stop your upstream (or revoke an API key) and
   click `↻` in the provider row.
2. The pill to the right of `models: N` flips from
   `· 2m ago` (purple) to `! 2m ago · fetch failed` (red).
3. Hover the red pill to see the full error message and the
   timestamp of the failed attempt.
4. Click `↻` again after fixing the upstream; the pill flips back
   to the normal purple variant as soon as the next fetch
   succeeds.

### 10.4 Behavior with a prior good cache

If a fetch fails AFTER a prior successful fetch for the same
provider, the prior model list is preserved and `cached_at` keeps
the LAST successful fetch time. `cached_error` is still set. The
SPA renders `! 2m ago · fetch failed` where "2m ago" is the age of
the last GOOD fetch — this is intentional so the user can tell
"the cached list is still 2 minutes fresh, but a more recent fetch
attempt failed".

### 10.5 Known limitations

- The warning chip is purely informational. The SPA does NOT
  auto-retry; clicking `↻` is the user's escape hatch.
- The CLI does NOT auto-retry either; `smolcode models refresh`
  only clears the cache.
- An SPA from M12.x (without the M12.4 frontend changes) will
  ignore `cached_error` and render the normal pill; it will
  still see the correct `cached_at`.

---

## 11. M12.5 addendum — `models doctor` + mobile layout

M12.4 validation surfaced two small remaining gaps that we bundled
into a single addendum to keep the shipped surface symmetric: one
CLI verb for connectivity (`doctor`) + one CSS breakpoint for the
SPA mobile layout (`max-width: 900px`). Both shipped 2026-08-23.

### 11.1 What changed

| Change | File |
|---|---|
| New `doctor [--no-fetch]` verb in `_models_main` (per-provider connectivity diagnostic) | `smolcode/src/smolcode/cli.py` |
| Help text + usage line updated to include `doctor` | `smolcode/src/smolcode/cli.py` |
| Lazy `inspectorOpen` state with localStorage persistence (`smolcode.inspectorOpen.v1`) + mobile toggle button in `<header>` | `smolcode/web/src/App.tsx` |
| `<aside>` now carries `mobile-open` class when toggled; new `@media (max-width: 900px)` block collapses the 3-pane grid to 1-column and hides the inspector until toggled | `smolcode/web/src/index.css` |
| 3 new pytest cases for `doctor` (ok / fail / `--no-fetch`) | `smolcode/src/smolcode/tests/test_cli_models.py` |

### 11.2 See the new `models doctor` verb

```bash
# Fresh fetch for every provider with a key set (4 outbound HTTP calls
# in the typical 4-of-5-keys case):
.venv\Scripts\python.exe -m smolcode models doctor

# Or read the existing cache without burning upstream quota:
.venv\Scripts\python.exe -m smolcode models doctor --no-fetch
```

Sample output (4 keys set, fresh fetch):

```
PROVIDER        STATUS         DETAIL
opencode-go     OK             (2 models) just now (M12.5: 1/1)
huggingface     skipped        (ENV not set)
MiniMax      OK             (7 models) just now (M12.5: 2/2)
openai          OK             (3 models) just now (M12.5: 3/3)
anthropic       OK             (5 models) just now (M12.5: 4/4)
custom          skipped        (ENV not set)
M12.5: 4/4 providers OK; exit 0 = all good
```

Sample output (opencode-go key was just rotated and is now a 401):

```
PROVIDER        STATUS         DETAIL
opencode-go     FAIL           fetch_failed: 401 Unauthorized  (M12.5: 0/1)
huggingface     skipped        (ENV not set)
MiniMax      OK             (7 models) just now (M12.5: 1/2)
openai          OK             (3 models) just now (M12.5: 2/3)
anthropic       OK             (5 models) just now (M12.5: 3/4)
custom          skipped        (ENV not set)
M12.5: 3/4 providers OK; exit 1 = at least one provider failed
```

Sample output (`--no-fetch`, with one cached failure from earlier):

```
PROVIDER        STATUS         DETAIL
opencode-go     fail           fetch_failed: 401 Unauthorized
huggingface     skipped        (ENV not set)
MiniMax      ok-cached      (7 models) 5m ago
openai          ok-cached      (3 models) 30s ago
anthropic       no-cache       (nothing cached yet)
custom          skipped        (ENV not set)
M12.5: --no-fetch (read cache only); exit 1 = at least one cached failure
```

#### Exit codes

- `0` — every provider with a key set reported `OK` (fresh) or
  `ok-cached` (--no-fetch).
- `1` — at least one provider reported a failure (either `FAIL` /
  `fail`). The exit code makes the verb CI-friendly: `python -m
  smolcode models doctor || exit 1` fails the build when a key is
  misconfigured.

#### STATUS column vocabulary

| STATUS | Meaning |
|---|---|
| `OK` (uppercase) | Fresh fetch succeeded; the most recent attempt returned a valid model list |
| `FAIL` (uppercase) | Fresh fetch failed; the error string is in DETAIL |
| `ok-cached` | `--no-fetch` mode; the cache had a successful entry |
| `fail` (lowercase) | `--no-fetch` mode; the cache had a failure entry |
| `no-cache` | `--no-fetch` mode; the cache was empty for this provider |
| `skipped` | No API key set in `os.environ` for this provider's `env_var` |

### 11.3 Try the mobile layout

1. Open Chrome devtools (`F12`).
2. Toggle device toolbar (`Ctrl+Shift+M`) and pick any width
   `≤ 900px` (e.g. `768 × 1024`, `390 × 844`).
3. The 3-pane grid collapses to a single column. The conversation
   pane takes the full width; the inspector pane is hidden by
   default and slides in below the conversation when toggled.
4. Click the new **`Inspector ▾`** button in the header (between
   `<TierSwitcher>` and `.ws`). It flips to **`Inspector ▴`** and
   the inspector pane appears, capped at `50vh` so it never
   dominates the viewport.
5. Reload the page (`F5`). The toggle state persists via
   `localStorage["smolcode.inspectorOpen.v1"]` — it stays open or
   closed the way you left it.
6. Switch back to a desktop width (`> 900px`). The toggle button
   disappears (it's `display: none` on desktop via
   `.inspector-toggle { display: none; }` at root, overridden to
   `inline-flex` inside the media query). The full 3-pane grid
   returns.

The accessibility wiring (`aria-expanded`, `aria-controls`,
visible label that flips between ▾ / ▴) means a screen-reader user
hears whether the pane is currently expanded and can find the
button by either label.

### 11.4 Why a lazy `useState` initializer (not two `useEffect`s)

The most natural pattern — a `useEffect` that reads
`localStorage` on mount and `setState(…)` — would have added a 5th
oxlint `set-state-in-effect` warning on top of the existing 4-warning
baseline. M12.5 instead uses a lazy `useState(() => ...)`
initializer:

```typescript
const [inspectorOpen, setInspectorOpen] = useState<boolean>(() => {
  if (typeof window === 'undefined' ||
      typeof window.localStorage === 'undefined') {
    return false
  }
  try {
    return window.localStorage.getItem('smolcode.inspectorOpen.v1') === 'true'
  } catch {
    return false
  }
})
```

The initializer runs ONCE on first render (so no setState happens
inside an effect), and the write-side `useEffect` only writes the
new value back to localStorage — it never calls `setState`.

Verified at the M12.5 validation gate: `pnpm run lint` reports
exactly 4 warnings (the pre-M12 baseline) — no new
`set-state-in-effect` warnings were added.

### 11.5 Why `result.get("error")` and not `"error" in result`

`fetch_models` always returns a dict with the key `error`
present — set to `None` on success and to a string on failure.
The first draft of `doctor` used `if "error" in result`, which
was True on every call (including successes) and crashed on
`str(None) + " " + error_message`. Switched to
`if result.get("error"):` (truthy check). Caught by the first
isolated `pytest -k doctor` run before the full suite; the full
suite was clean (760 passed).

### 11.6 Known limitations (M12.5)

- **Doctor makes N outbound calls.** With the default 5-provider
  catalog and all 5 keys set, a single `doctor` invocation is 5
  HTTP calls. Acceptable for a manual diagnostic; not intended
  for tight CI loops. Mitigation: `--no-fetch` mode.
- **The 900px breakpoint is a heuristic.** Tablets in landscape
  (~1024px) still get the full 3-pane grid. If a specific
  viewport is reported as bad, add a second breakpoint or a
  matchMedia-driven toggle. Deferred to a later milestone.
- **The `inspectorOpen` localStorage key is namespaced as
  `smolcode.inspectorOpen.v1`.** If the layout shape changes
  significantly in a future milestone, bump to `v2` so they do
  not see a stale toggle state that no longer matches the
  rendered pane.
