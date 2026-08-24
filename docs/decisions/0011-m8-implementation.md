# 0011 — M8 GUI viewer + file uploads implementation log

**Date:** 2026-08-20
**Status:** active
**Trigger:** v1 shipped (M0-M7 SHIPPED). User approved the M8 design
(0010) on 2026-08-20 and asked to proceed with implementation. User
also asked for file-upload support to be added; the four D8 design
defaults were confirmed with option (a) on each.
**Related:** decision 0010 (design), roadmap.md M8 section,
architecture.md §12, security.md §3.4, README M8 section.

---

## Question

How do we ship M8 (the GUI viewer + file uploads) end-to-end with
all 8 acceptance gates from the goal: (1) FastAPI backend on
loopback; (2) `smolcode uploads` CLI; (3) React SPA; (4) upload
backend module; (5) tier policy; (6) CLI subcommands wired; (7)
docs updates; (8) tests with coverage gate at 80% preserved.

## Findings

### F1. FastAPI 0.141 has a route-registration regression

`uv pip install -e ".[web]"` resolved fastapi==0.141.1, which
silently dropped every route registered via
`APIRouter.include_router`. Downgrading to 0.119 fixed it. Decision:
pin fastapi to `>=0.115,<0.140` in pyproject.toml.

### F2. The pre-dispatch CLI pattern

Argparse rejected `smolcode uploads list` because "list" was an
unrecognised positional. Same would be true for `smolcode web`.
Fix: detect the leading subcommand keyword in `main()` BEFORE
`argparse.parse_args` runs, and dispatch to a dedicated handler.

### F3. `.rstrip(".exe")` strips `t` from "pytest"

`str.rstrip(chars)` treats its argument as a CHARACTER SET, not as
a suffix. So `"pytest".rstrip(".exe").rstrip(".bat")` removes the
trailing `t` (because `t` is in the set `{.bat}`). Bug caught by
test_shell_run_allowed. Fix: use `removesuffix()` (Python 3.9+)
which is a real suffix matcher.

### F4. Pydantic v2 `response_model` filters dict fields

`/api/uploads/clean` returned `{"deleted": N, "would_delete_count":
M, ...}` but `response_model=CleanResponse` (which only declared
`deleted` and `requested_older_than`) filtered out the extra
`would_delete_count` field. Fix: drop `response_model` from that
endpoint — Pydantic v2 was silently dropping fields not in the
schema.

### F5. SPA bundling via PyInstaller is deferred

M8 ships the SPA as a static dist/ folder mounted by FastAPI. The
PyInstaller single-file bundle is a nice-to-have but adds 80 MB and
a multi-day CI integration. Recorded as a v1.1 followup.

### F6. Live agent streaming is not in M8

M8 is the read-only viewer + upload zone. The "live execution
stream" pane is a placeholder that says "M9 ships this". The
existing CLI (`smolcode "task"`) already streams agent steps; M9
adds the SSE bridge so the SPA can subscribe to the same events.

## Decision

M8 ships the architecture described in 0010 D1-D8, in three phases:

### Phase A — Upload backend (testable, no web deps)

1. `smolcode/src/smolcode/uploads.py` — `safe_name`, `sniff_mime`
   (magic-byte + UTF-8 fallback, browser claim IGNORED),
   `is_mime_allowed` (default allowlist + executable blocklist),
   `UploadsStore` (append-only JSONL sidecar, sha256 per file,
   collision suffix), `UploadMetadata` dataclass.
2. `smolcode/src/smolcode/config.py` — `Tier.uploads` slot (defaults
   "read" / "readwrite" / "readwrite"); `Settings.uploads_dir`,
   `upload_max_bytes`, `upload_allowed_mime`;
   `SMOLCODE_UPLOAD_DIR/MAX_BYTES/ALLOWED_MIME` env vars.
3. `smolcode/src/smolcode/tools/fs.py` — `_WriteFileTool` blocks
   writes to the uploads dir for the `restricted` tier. Existing
   tests that pass only `workspace_path` to `build_fs_tools` keep
   working (new attrs default to "").
4. `smolcode/cli.py` — `smolcode uploads list|clean [--older-than N]
   [--yes]|path` subcommand with pre-dispatch.

### Phase B — FastAPI server + tests

5. `smolcode/src/smolcode/web/` — new package with:
   - `__init__.py` (public exports)
   - `server.py` — `create_app(settings=None)` + `run_server`
     + `ALLOWED_BIND_HOSTS = ("127.0.0.1", "localhost", "::1")`.
     Static SPA mount at `/` when `smolcode/web/dist/` exists.
   - `api.py` — 12 endpoints (health, config, tiers, sessions,
     sessions/{id}, audit, allowlist/check, uploads GET/POST/DELETE,
     uploads/clean).
   - `deps.py` — FastAPI dependencies for Settings / UploadsStore /
     AuditSink.
   - `schemas.py` — Pydantic v2 request/response models.
6. `smolcode/cli.py` — `smolcode web [--port N] [--host H]
   [--no-browser]` subcommand. Host guard: only loopback allowed,
   else exit 8.
7. `smolcode/pyproject.toml` — `[web]` extra: FastAPI
   `>=0.115,<0.140`, `uvicorn[standard]>=0.32`,
   `python-multipart>=0.0.9`.
8. `tests/test_web_server.py` + `tests/test_web_api.py` — 25 new
   tests covering bind allowlist, all 12 API endpoints, upload
   flow (POST / list / download / delete), clean confirm/ noop,
   traversal rejection.

### Phase C — React SPA + build

9. `smolcode/web/` — Vite + React 19 + TS 6 project.
   - `vite.config.ts` — dev-mode proxy `/api/*` →
     `http://127.0.0.1:7860`; build output to `dist/`.
   - `src/api.ts` — typed fetch client for all 12 endpoints.
   - `src/components/TierBadge.tsx` — colored chip (green / amber
     / red) per tier.
   - `src/components/UploadDropZone.tsx` — drag-drop + click-to-
     browse; calls `uploadFile` on each File; shows error banner
     for rejected uploads.
   - `src/components/UploadList.tsx` — per-file row with name,
     size, MIME, tier, sha256 prefix, delete button.
   - `src/components/AllowlistSimulator.tsx` — pick tool + tier +
     args, POST /api/allowlist/check, show allowed/denied.
   - `src/App.tsx` — 3-pane layout per 0010 D4 (Plan left, Stream
     center placeholder for M9, Inspector right).
   - `src/index.css` — hand-rolled CSS (no Tailwind dep needed
     for v1). Theme: dark header, light panes, gray borders.
10. `pnpm build` — produces `smolcode/web/dist/index.html` (0.52
    KB) + JS bundle (~200 KB, 62 KB gzipped) + CSS (4.7 KB).
11. `FastAPI` mounts the SPA at `/` automatically when `dist/`
    exists. `/api/*` continues to serve JSON.

### Phase D — Docs

12. `docs/roadmap.md` — M8 SHIPPED row in the milestone overview
    table; `### M8 — GUI viewer + file uploads (v1.2)` section with
    sub-deliverables, security invariants, and acceptance gates.
13. `docs/architecture.md` — §1.2 amended (web UI is no longer a
    non-goal); new §12 "Web GUI (M8)" describing components, bind
    allowlist, upload folder reuse, dev vs prod mode, M9-M11
    deferred work.
14. `docs/security.md` — new §3.4 "User uploads" with the tier
    matrix and the write-block rationale.
15. `smolcode/README.md` — M8 section: install, run, manage
    uploads, tier policy, deferred work, security review.

## Code Impact

| File | Status | Lines |
|---|---|---|
| `smolcode/src/smolcode/uploads.py` | new | ~370 |
| `smolcode/src/smolcode/web/__init__.py` | new | 14 |
| `smolcode/src/smolcode/web/server.py` | new | ~110 |
| `smolcode/src/smolcode/web/api.py` | new | ~290 |
| `smolcode/src/smolcode/web/deps.py` | new | ~50 |
| `smolcode/src/smolcode/web/schemas.py` | new | ~65 |
| `smolcode/src/smolcode/tests/test_uploads.py` | new | 68 tests |
| `smolcode/src/smolcode/tests/test_web_server.py` | new | 4 tests |
| `smolcode/src/smolcode/tests/test_web_api.py` | new | 21 tests |
| `smolcode/src/smolcode/cli.py` | updated | +web, +uploads pre-dispatch + handlers |
| `smolcode/src/smolcode/config.py` | updated | Tier.uploads + Settings uploads_dir/upload_max_bytes/upload_allowed_mime + env vars |
| `smolcode/src/smolcode/tools/fs.py` | updated | _WriteFileTool blocks uploads for restricted |
| `smolcode/src/smolcode/tools/__init__.py` | updated | build_fs_tools accepts tier + uploads_dir |
| `smolcode/pyproject.toml` | updated | [web] extra with FastAPI pin |
| `smolcode/web/` | new | Vite + React 19 + TS 6, 4 components |
| `smolcode/web/dist/` | new | built SPA (gitignored) |
| `docs/roadmap.md` | updated | M8 SHIPPED row + section |
| `docs/architecture.md` | updated | §1.2 + new §12 |
| `docs/security.md` | updated | §3.4 user uploads |
| `smolcode/README.md` | updated | M8 section |

## Validation

| Gate | Result |
|---|---|
| `ruff check src` | All checks passed |
| `ruff format --check src` | 63 files already formatted |
| `pytest` (with coverage gate) | 542 passed in 70 s |
| `--cov-fail-under=80` | 80.34% reached |
| `pnpm build` | OK (200 KB JS, 5 KB CSS) |
| `smolcode uploads list/clean/path` | exit 0, expected output |
| `smolcode web --host 0.0.0.0` | rejected (exit 8) |
| `smolcode web --no-browser` | OK (would start server; smoke via TestClient) |
| TestClient POST /api/uploads | 201 + UploadOut |
| TestClient GET /api/uploads | list |
| TestClient DELETE /api/uploads/{name} | 200 + {"deleted": ...} |
| FastAPI mount `/` returns built SPA | 200 + HTML + bundle |
| Restricted tier write to uploads | raises `PermissionError` |
| Reload after upload | file persists (sidecar + on-disk) |
| `pnpm build` output | 200 KB JS bundle, 4.7 KB CSS |

## Followups (v1.1+)

- **M9** (live execution): SSE bridge from agent loop to SPA; tier
  switcher with confirmation modal; stop button; mid-run approval
  for gated actions.
- **M10** (diff + editing): inline diff viewer for write_file /
  patch_file; apply / reject per step; workspace tree.
- **M11** (specialist + audit reader): specialist editor (forms for
  specialists.toml); MCP server manager; CLI audit ls / audit grep.
- **PyInstaller bundle**: single-file `smolcode.exe` with SPA
  embedded. ~80 MB.
- **Auth**: localhost-only today. If we ever add even basic auth
  for the SPA, document the threat model change.

## References

- `docs/decisions/0010-gui-design.md` — design (active, user approved 2026-08-20)
- `docs/roadmap.md` — M8 SHIPPED section
- `docs/architecture.md` — §12 Web GUI
- `docs/security.md` — §3.4 User uploads
- `smolcode/README.md` — M8 section
- `smolcode/src/smolcode/uploads.py` — implementation
- `smolcode/src/smolcode/web/server.py` — FastAPI app
- `smolcode/src/smolcode/web/api.py` — endpoints
- `smolcode/web/src/App.tsx` — SPA entry
