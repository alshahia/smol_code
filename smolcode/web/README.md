# smolcode web SPA

**Status:** active (Phase 9 documentation alignment, 2026-10-24, decision 0044).
**Stack:** React 19 + TypeScript, Vite, Vitest, Playwright, Oxlint.
**Backend:** this bundle is **not** a standalone app. It is the browser client for
the FastAPI server in `smolcode/src/smolcode/web/` (`smolcode web`).

## What it is

A single-page GUI for the agent loop: start a run (tier + task), watch the
event stream over SSE, answer approval and diff-proposal modals, browse run
history, the workspace tree, uploads, the audit log and cost limits. All state
lives on the server; the SPA holds no API key and makes only same-origin
requests to `/api/*` (`src/api.ts` is the typed client).

## Development loop

Two processes, one origin each:

1. **Backend** — from the repo root:
   ```powershell
   & "E:\python_projects\smol_code\smolcode\.venv\Scripts\python.exe" -m smolcode web
   ```
   Serves `http://127.0.0.1:7860` and binds loopback only. It refuses to start
   (exit 3) when the tier images are unavailable, because the web path runs
   real sandboxes; that is a fail-closed default, not a bug.
2. **Frontend** — in `smolcode/web`:
   ```powershell
   pnpm install
   pnpm dev
   ```
   Serves `http://127.0.0.1:5173` with HMR. `vite.config.ts` proxies `/api` to
   `http://127.0.0.1:7860` (`changeOrigin: false`) and sets `strictPort: true`,
   so port 5173 must be free — it never silently moves to 5174.

Then open `http://127.0.0.1:5173`. There are **no** host/port environment
variables: the backend takes `--host`/`--port` CLI flags (defaults
`127.0.0.1:7860`) and only loopback addresses are accepted.

## Scripts (from `package.json`)

| Command | What it does |
|---|---|
| `pnpm dev` | Vite dev server on :5173 with the `/api` proxy |
| `pnpm typecheck` | `tsc -b` (no emit) |
| `pnpm build` | `tsc -b && vite build` → `dist/` |
| `pnpm preview` | serve the built `dist/` locally (no backend proxy) |
| `pnpm lint` | `oxlint` (config in `.oxlintrc.json`) |
| `pnpm test` | `vitest run` (jsdom + Testing Library, `src/__tests__/setup.ts`) |
| `pnpm test:watch` | Vitest in watch mode |
| `pnpm test:a11y` | the accessibility suite |
| `pnpm test:e2e` | `playwright test` (spawns its own `pnpm dev` webServer) |
| `pnpm coverage` | Vitest + v8 coverage; thresholds 70/70/70/60 |

`pnpm test:e2e` needs Playwright browsers downloaded (`pnpm exec playwright
install`); that download is not part of `pnpm install` and is not available in
every environment.

## Production bundle

`pnpm build` writes `dist/` (`outDir: 'dist'`, `emptyOutDir: true`,
`sourcemap: false`). `dist/` is **generated** and gitignored — never commit
it. The FastAPI server mounts `web/dist` at `/` with `html=True` when the
directory exists and warns when the bundle is older than its sources
(`smolcode/src/smolcode/web/spa.py`), so "rebuild the SPA" is actionable. A
fresh clone therefore needs `pnpm build` once before `smolcode web` can serve
the UI; the JSON API itself works without a bundle.

`pnpm-lock.yaml` **is** committed — keep it in sync with `package.json` and use
pnpm, not npm or yarn. `pnpm-workspace.yaml` is committed too: it carries the
pnpm 10+ build-script allowlist (`allowBuilds: esbuild`) without which
`pnpm install --frozen-lockfile` fails with `ERR_PNPM_IGNORED_BUILDS`.

## Layout

- `src/api.ts` — typed fetch client, one function per endpoint; relative URLs only.
- `src/components/` — panels, modals, stream renderer.
- `src/lib/` — pure helpers (formatting, event parsing) with unit tests.
- `src/__tests__/` — Vitest suites (jsdom); `setup.ts` loads for all of them.
- `e2e/` — Playwright smoke tests (loopback only, chromium + firefox + webkit).
- `dist/` — generated bundle, ignored by git.

## Notes

- Keep requests same-origin (`/api/...`). There is no configurable API base
  URL and no CORS layer; the Vite proxy exists only for development.
- Security claims about the server live in `../docs/security.md`; this file
  only describes the bundle and its tooling.
