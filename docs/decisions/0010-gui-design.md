# 0010 — GUI design proposal

**Date:** 2026-08-20
**Status:** active (user approved on 2026-08-20; M8 implementation in progress)
**Trigger:** v1 is shipped (M0-M7 all SHIPPED per `docs/roadmap.md`). User asked "if we want to add a gui, what the suggestions and how its should look like and what its should have and why" at the end of M7. User then asked for file-upload support ("add support to upload files/media by user from the gui chat ... can we keep the user uploaded files and not get it lost"), answered the four D8 design defaults with option (a) on each, and approved M8 on 2026-08-20.
**Related:** `docs/architecture.md`, `docs/security.md`, `docs/roadmap.md`, decisions 0001-0009.

---

## User decisions on D8 (2026-08-20)

| # | Question | Answer |
|---|---|---|
| 1 | Folder visibility | **(a) Hidden `.smolcode/uploads/`** — agent's normal `list_dir('.')` stays clean |
| 2 | Image handling | **(a) Direct multimodal content** — image bytes sent to vision-capable models; text-only models get a path reference placeholder |
| 3 | MIME policy | **(a) Text + docs + images + code** — allowlist `text/*`, PDF, DOCX, XLSX, PNG/JPG/GIF/WebP, code; block `.exe`, `.so`, `.dll`, archives |
| 4 | Cross-session visibility | **(a) Persistent on disk; hint only current session** — files never lost; system-prompt hint mentions current-session uploads; `list_uploads()` shows everything on disk |

D8 is now **locked** to these defaults. Implementation in M8 begins with these as the source of truth.

---

## Question

Should smolcode ship a graphical user interface alongside its CLI? If yes:

1. Which architecture (web / desktop / TUI)?
2. What should it look like (layout)?
3. What features does it need (scope)?
4. Why those features (rationale)?
5. How is it phased (milestones)?

This decision captures the **design** only. Implementation is gated on
the user's explicit approval of this proposal.

---

## Findings

### F1. The CLI is fully featured but lacks visibility

The CLI (`smolcode` / `smolcode.cli.main`) provides:

- Multi-tier agents (restricted / elevated / full_access) with audit trail
- Streaming agent steps to the terminal (via smolagents `stream` callbacks)
- Approval prompts for destructive ops (M4.x)
- Live audit log at `logs/audit.jsonl`
- Provider/model switcher via env + CLI flags
- MCP server loading via `mcp_config.json`
- Specialist registry via `specialists.toml`
- Session history in `sessions/<id>.jsonl`

A power user running `smolcode --tier elevated --orchestrator "ship
the latest change to staging"` gets a wall of text. Hard to scan,
hard to compare past runs, hard to see *why* the agent picked
`deploy_staging` over the default coding specialist, hard to replay a
single step in isolation, and impossible to share a visual artifact
with a teammate.

### F2. Three audience segments, three different needs

| Audience | Need | Implication |
|---|---|---|
| Self-hosting individual | Visual diff + easier replay | Read-only viewer is 80% of value |
| Small team lead | "What did the agent do last Tuesday?" | Audit dashboard + session browser |
| Power user (CLI native) | Keyboard-driven, dense, fast | Stay in CLI; GUI is opt-in |

The lowest-risk entry point addresses the first two: a **read-only
viewer** that consumes existing audit + session logs. Zero new
execution surface, zero new attack surface, re-uses all 449 existing
tests.

### F3. Three architecture candidates

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Local web app** (FastAPI + React SPA served on 127.0.0.1) | Reuses Python backend; SSE/WebSocket easy; themable; rich diff; tabs; copy-paste UI primitives (shadcn); one-command launch (`smolcode web`) | ~80 MB PyInstaller bundle; needs JS toolchain for dev; requires browser | **Recommended** |
| Desktop app (Tauri or Electron) | OS-native chrome; offline icon; auto-update channel | Heavy toolchain (Rust for Tauri); harder for users to build locally; "yet another binary" | Defer |
| Terminal UI (Textual) | Small bundle; SSH-friendly; pure Python | No diff viewer; no images; limited rich text; harder to share session artifacts | Defer |

Local-web wins because:
- **Backend reuse**: the GUI can import `smolcode.audit`, `smolcode.policy`, `smolcode.tiers` directly — no subprocess piping.
- **No IPC**: same process = same types = no serialization layer.
- **No native code**: avoids Tauri/Electron toolchain dependency.
- **Single port**: `smolcode web --port 7860` opens the browser; the URL bar doubles as the share/export handle.

### F4. The design must be security-first, not chat-first

Most AI chat UIs lead with a text input and a transcript. smolcode
leads with **tier context**. The tier is the security boundary, and
the GUI must keep it visible at all times:

- Tier badge in the header (green / amber / red)
- Every tool call shows tier + allowlist check inline
- Destructive ops show a modal (replacing CLI's `[y/N]`)
- Audit log is the source of truth — every step links to its entry
- Redacted secrets are visible as `[REDACTED:<class>]` inline; the
  GUI shows *what class* was filtered, never the value (M7 invariant)

### F5. Phasing matters

The user explicitly asked for design only ("if we want to add gui").
That implies an approval gate before any implementation. The phasing
below is ordered so that **each phase delivers standalone value** and
**regressions are caught early**:

| Phase | Scope | New execution surface? | Days (est.) |
|---|---|---|---|
| **M8** | Read-only viewer (sessions, audit, tier dashboard, allowlist simulator) | **None** | ~5 |
| **M9** | Live execution (SSE bridge, approval modal, stop button, tier switcher) | Adds one | ~10 |
| **M10** | Diff + editing (inline diff viewer, apply/reject, workspace tree) | None | ~5 |
| **M11** | Power user (specialist editor, MCP manager, audit reader CLI) | None | ~5 |

M8 first because it is the only phase with **zero new execution
surface**. M9 only starts once the viewer UX is validated.

### F6. Uploads are a first-class feature for an AI GUI

Most AI chat UIs lead with a text input. smolcode's GUI leads with a
**file upload** area because the user often wants the agent to work
over their own data: a CSV, a screenshot of a bug, a draft doc, a
log file. Without uploads, the workflow is "save the file into the
workspace, then ask the agent to read it" — friction that breaks the
UX promise.

A separate `<workspace>/.smolcode/uploads/` folder is the right home
because:

- It is **outside** the agent's normal discovery (`list_dir('.')` does
  not show dot-prefixed dirs by default in most tools / shells).
- It can carry **per-file metadata** (original name, MIME, size,
  timestamp) without polluting the workspace.
- It can be **wiped** independently of the workspace.
- The existing `PathPolicy` covers it automatically because it lives
  inside the workspace.

Uploads must be **persistent by default** — the user explicitly
asked for this. They survive agent restarts and CLI invocations.
Deletion is explicit (per-file button or `smolcode uploads clean`).

---

## Decision

### D1. Architecture: local web app

`smolcode web` spawns a uvicorn server on `127.0.0.1:<port>` and
opens the user's browser to the SPA. The server runs in the same
process as the CLI, so it can import `smolcode.audit`,
`smolcode.policy`, etc. directly.

Bind to loopback only (`127.0.0.1`). No auth. The local-only design
intentionally removes an entire class of vulnerabilities.

### D2. Backend: FastAPI + uvicorn + SSE

- **FastAPI**: async-native, OpenAPI docs for free, Pydantic models
  match our existing config schemas.
- **uvicorn**: standard ASGI server; small footprint.
- **SSE (Server-Sent Events)** for live step streaming: simpler than
  WebSocket, fits the one-way agent → UI direction, easy to consume
  with `EventSource` in the browser.

Endpoints (M8 sketch):

```
GET  /                          → SPA index.html
GET  /api/health                → {status: "ok"}
GET  /api/config                → current smolcode config (tiers, providers, MCP servers)
GET  /api/sessions              → list session JSONL files
GET  /api/sessions/{id}         → parsed session events
GET  /api/audit?limit=N&since=T → recent audit entries (re-uses M7 `AuditSink`)
POST /api/allowlist/check       → {"tool": "shell.run", "args": {...}, "tier": "restricted"} → {"allowed": bool, "reason": str}
GET  /api/tiers                 → tier policies (allowlists, paths, network rules)
```

M9 adds:

```
POST /api/runs                  → start a new agent run; returns run_id
GET  /api/runs/{id}/events      → SSE stream of agent steps
POST /api/runs/{id}/approve     → approve a gated action
POST /api/runs/{id}/deny        → deny + cancel
POST /api/runs/{id}/stop        → kill the agent
```

D8 (uploads, M8) adds:

```
POST   /api/uploads                      upload one or more files (multipart/form-data)
GET    /api/uploads                      list metadata sidecar entries
GET    /api/uploads/{name}               download/preview a file
DELETE /api/uploads/{name}               delete one file
POST   /api/uploads/clean                bulk delete (with optional ?older_than_days=N)
```

### D3. Frontend: React + Vite + TypeScript + shadcn/ui + Tailwind

- **React + Vite + TS**: fast HMR; large ecosystem; mature.
- **shadcn/ui + Tailwind**: copy-paste components, no vendor lock-in,
  full control over styling, accessible by default.
- **Zustand** for state (no Redux ceremony).
- **TanStack Query** for server state (caching + re-fetch + retries).
- **react-arborist** or **@headless-tree** for the workspace tree.
- **diff2html** for inline diff rendering.
- **xterm.js** for the live shell output pane (so terminal commands
  render with colors).

Build artifact is a static directory `smolcode/web/dist/`. The
`smolcode web` command serves it via FastAPI's
`StaticFiles` mount.

### D4. Layout: three-pane transcript

```
┌──────────────────────────────────────────────────────────────────────────┐
│ smolcode ▸ [● restricted ▼] [opencode-go ▼] [orchestrator ▼]  ⚙ history  │
├──────────────┬─────────────────────────────────────────┬─────────────────┤
│ PLAN         │ EXECUTION STREAM (live, scrollable)     │ INSPECTOR       │
│              │                                         │                 │
│ Task:        │ ✓ Thought: "explore workspace"         │ Step #7         │
│ ┌──────────┐ │ ⏺ list_dir('.') → 12 files             │ ─────────────── │
│ │ Find and │ │ ✓ Thought: "grep for race"             │ Tool: shell.run │
│ │ patch    │ │ ⏺ grep('logic.py', 'race')             │ Tier: restricted│
│ │ race con │ │   → "race at line 42"                  │ Args:           │
│ │ in logi  │ │ ⏸ AWAITING APPROVAL                    │   cmd=pytest    │
│ │ c.py     │ │   shell.run  pytest -q                 │   args=[-q]     │
│ └──────────┘ │   [Approve] [Deny] [Edit cmd]           │ Result: 3 passed│
│              │                                         │                 │
│ Specialists: │ ── audit ───────────────────────────────│ Tier policy:    │
│ • coding     │ 12:34:56 shell.run   tier=restricted    │ [view allowlist]│
│ • test-runner│ 12:34:58 fs.read     logic.py:42       │                 │
│              │ 12:34:59 shell.run   pytest (approved) │ Allowlist hit:  │
│              │                                         │ ✓ pytest allowed│
│              │                                         │ ✗ rm denied     │
└──────────────┴─────────────────────────────────────────┴─────────────────┘
```

Three panes, not chat-style, because:

- **Plan (left)**: persistent task + specialist across the session.
  The user can correct course mid-run ("actually use `deploy_staging`
  instead").
- **Stream (center)**: live agent transcript. Mirrors Claude Code's
  transcript, but with explicit audit timestamps and tier badges on
  every tool call.
- **Inspector (right)**: focused detail for the selected step — diff
  for `write_file`, allowlist for `shell`, MCP schema for tool
  calls, error traceback on failure.

### D5. Security-first UX (must-have, not nice-to-have)

These are unique to smolcode and should be **first-class UI elements**:

1. **Tier badge always visible** in the header — colored chip
   (green/amber/red). Hovering shows the tier policy summary.
2. **Every tool call** shows tier + allowlist check inline
   (`✓ pytest allowed` / `✗ rm denied` / `⏸ awaiting approval`).
3. **Destructive actions** get an explicit modal, not a CLI prompt.
   The modal shows *which tier policy* triggered the gate, and offers
   **Edit** (modify the args before approval) — not just Approve/Deny.
4. **Audit log is the source of truth**. Every step links to its audit
   entry. Audit entries are tamper-evident (M7.5: hash chain; for now:
   append-only + rotation).
5. **Redaction is visible but value-safe** — show
   `[REDACTED:openai]` inline, with a tooltip explaining *what class*
   of secret was filtered. Never the value.
6. **Workspace boundary** — file tree shows only workspace contents.
   Escape attempts flash red in the audit pane.
7. **Provider/model visible** — current provider + model name always
   shown. Helps debug unexpected outputs (different model = different
   behavior).
8. **Uploaded files are visibly user-provided** — every uploaded file
   gets a "user-uploaded" badge in the inspector pane and a distinct
   color in the file tree, so the user can always tell at a glance
   what came from them vs. what the agent created.

### D6. What NOT to build (out of scope)

Explicit non-goals to keep scope honest:

- **No mobile / responsive** — desktop tool, not a chat app.
- **No multi-user / cloud sync** — local-first is the whole point.
- **No real-time collaboration** — single user, single agent at a time.
- **No browser extension** — keeps the surface minimal.
- **Uploads are read-only by default** for the `restricted` tier (the
  agent can `read_file` them but cannot modify or delete them via the
  workspace tools; explicit `Delete` button in the GUI is the only
  way to remove a file). `elevated` and `full_access` can modify.
- **No cloud-hosted mode** — even as an option, in v1.x.
- **No chat history search** (initially) — defer to M11 audit reader.

### D7. Bundle + delivery

- **Dev mode**: `pnpm --dir smolcode/web dev` (Vite HMR on
  `localhost:5173`, FastAPI on `localhost:7860`, Vite proxies
  `/api/*` to FastAPI).
- **Built mode**: `pnpm --dir smolcode/web build` produces
  `smolcode/web/dist/`. `smolcode web` serves it.
- **PyInstaller bundle** (optional, M11): single-file `smolcode.exe`
  with the SPA embedded via `StaticFiles(html=True)`. ~80 MB.
- **No CDN, no remote analytics, no telemetry**.

### D8. File upload support

The GUI's chat input has a **drag-drop area + file picker** for
uploading files into the agent's working set. Uploads are first-class
data the user brings into the session.

**Storage location**: `<workspace>/.smolcode/uploads/` (a hidden
dot-folder so the agent's normal `list_dir('.')` does not pick it up
unless explicitly asked).

**Metadata sidecar**: `<workspace>/.smolcode/uploads/.uploads.jsonl`
— append-only JSONL of `{ts, original_name, stored_name, size,
mime, sha256, tier_at_upload, uploaded_by}`.

**Persistence**: uploads **persist indefinitely** by default. There is
no TTL. Deletion is **explicit only**:

- Per-file: `DELETE /api/uploads/{name}` or the GUI's delete button.
- Bulk: `smolcode uploads clean` (CLI subcommand) or
  `POST /api/uploads/clean`.

Optional `SMOLCODE_UPLOAD_TTL_DAYS` env var can be set to enable a
soft TTL (files older than N days are flagged in the GUI; deletion is
still explicit).

**Filename sanitization**: `safe_name(filename)` strips path
separators, resolves `..`, rejects Windows-reserved names
(`CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9`), and
caps length at 200 chars. Collisions append `-<sha256[:6]>` before
the extension.

**File size cap**: `SMOLCODE_UPLOAD_MAX_BYTES` (default `52428800` =
50 MB). Reject with HTTP 413 before reading the body into memory.

**MIME handling**: server sniffs actual MIME via
`mimetypes.guess_type` + the first 8 KB magic-byte check
(`filetype`-style). The **sniffed** MIME is what gets recorded, not
the browser-claimed one.

**Allowed types** (default allowlist; configurable via
`SMOLCODE_UPLOAD_ALLOWED_MIME`):

- Text: `text/*`, `application/json`, `application/xml`,
  `application/yaml`, `application/csv`
- Documents: `application/pdf`, `application/msword`,
  `application/vnd.openxmlformats-officedocument.*`,
  `application/vnd.ms-excel`
- Images: `image/png`, `image/jpeg`, `image/gif`, `image/webp`
- Code: `text/x-python`, `text/javascript`, `text/x-shellscript`,
  etc. (anything with a textual MIME)

**Explicitly blocked** (regardless of MIME): executables
(`application/x-msdownload`, `application/x-executable`,
`application/x-shellscript` is allowed as text but not executed),
archives with executable entries (we extract nothing in v1).

**Agent integration** (three layers, all enabled by default):

1. **System prompt hint** at run start:
   `"The user uploaded these files: <list>. They live in
   <workspace>/.smolcode/uploads/. Call list_uploads() for the full
   list with metadata."` — gives the agent immediate context.
2. **`list_uploads()` tool**: returns the metadata sidecar (filename,
   size, MIME, sha256, timestamp). The agent calls this to discover
   files it was not told about.
3. **`read_upload(name)` tool**: convenience wrapper that calls
   `read_file` on `<workspace>/.smolcode/uploads/<safe_name>`. The
   agent could call `read_file` directly, but `read_upload` is shorter
   and survives a future rename of the uploads folder.

For **images**, the GUI's chat-input preview already shows the image
inline. When the agent runs, the model receives the image as
**multimodal content** (not just a path reference) for any vision-
capable model. Text-only models get a `<image: filename.png
(12 KB)>` placeholder.

**Tier policy** (extends `docs/security.md` §3):

| Tier | Read uploads | Modify uploads | Delete uploads |
|---|---|---|---|
| `restricted` | ✓ | ✗ (read-only) | ✗ (explicit GUI button only) |
| `elevated` | ✓ | ✓ | ✓ |
| `full_access` | ✓ | ✓ | ✓ |

The `restricted` tier's read-only stance is enforced by a new entry
in `TIERS.restricted.uploads = "read"` (parallel to existing
`commands` and `imports` allowlists). Modifying a file under
`.smolcode/uploads/` via `write_file` raises `PermissionError` for
`restricted`. The GUI's per-file delete button bypasses the tier
policy (the user is acting, not the agent).

**Audit events** (added to `AuditSink` event vocabulary):

- `upload.add` — `{name, size, mime, sha256, tier}`
- `upload.delete` — `{name, deleted_by: "gui"|"cli"|"agent", tier}`
- `upload.read` — emitted by `read_upload()` tool when called by the
  agent (separate from the regular `fs.read` audit entry, so the
  audit log distinguishes "user-provided data" from "codebase")

**API endpoints** (added to M8):

```
POST   /api/uploads                      upload one or more files (multipart/form-data)
GET    /api/uploads                      list metadata sidecar entries
GET    /api/uploads/{name}               download/preview a file (for the GUI's preview pane)
DELETE /api/uploads/{name}               delete one file
POST   /api/uploads/clean                bulk delete (with optional `?older_than_days=N`)
```

**CLI surface** (added to M8):

```
smolcode uploads list                   # show metadata sidecar
smolcode uploads clean [--older-than N] # delete files (with confirm prompt)
smolcode uploads path                   # print the uploads folder path
```

**Why this design**:

- **Hidden dot-folder**: keeps `list_dir('.')` clean for the agent;
  uploads are explicit intent, not ambient noise.
- **Persistent by default**: matches the user's explicit "don't lose
  them" requirement; deletion is opt-in.
- **Three-layer agent awareness**: hint at run start + tool for later
  discovery + convenience tool; covers both the common case
  (upload-then-ask) and the iterative case (agent discovers uploads
  mid-run).
- **Read-only for `restricted`**: the agent can't accidentally rewrite
  or delete user data; only an explicit human action removes a file.
- **MIME sniffing, not browser claim**: prevents `evil.png.exe`
  attacks where the browser says PNG but the file is a Windows
  executable.
- **Metadata sidecar**: every file's provenance is recorded; the
  `sha256` lets us dedup and verify integrity.
- **Audit events are distinct from `fs.*`**: the audit log can answer
  "what user-provided data did this run touch?" separately from "what
  code files did this run modify?".

**Failure modes (must surface clearly in the GUI)**:

- Upload rejected (size > cap, MIME blocked, name rejected) → red
  banner with the specific reason. No silent failures.
- Upload overwrites existing file → confirm modal ("Replace
  existing file?"). Never overwrite silently.
- Delete while agent is reading it → block until the run ends, then
  delete (or cancel the delete and warn).

---

## Layout sketch — approval modal (M9)

When a tool call hits the destructive gate, the modal replaces the
inspector pane and pins to the stream:

```
┌─────────────────────────────────────────────────┐
│  ⏸ Awaiting approval                            │
│  ─────────────────────────────────────────────  │
│  Tool:    shell.run                             │
│  Tier:    restricted                            │
│  Trigger: command in destructive-list (M4.x)    │
│           `rm` matches `^(rm|del|drop)`        │
│                                                  │
│  Args:                                           │
│    cmd:  rm                                     │
│    args: [-rf, ./build]                         │
│                                                  │
│  Preview:                                       │
│    $ rm -rf ./build                             │
│    ⚠  14 files / 3 dirs would be deleted        │
│                                                  │
│  [Approve]  [Edit args]  [Deny + cancel run]    │
└─────────────────────────────────────────────────┘
```

The `Edit args` option is the differentiator vs the CLI: in the CLI
the user has to abort and re-run with different args; in the GUI they
edit in place.

---

## Layout sketch — read-only viewer (M8)

`smolcode web --read-only` mounts only the GET endpoints. No agent
runs, no mutations. The home screen shows:

- **Top bar**: smolcode version, current config snapshot, link to
  docs.
- **Sidebar**: Sessions (sorted by date), Audit (last 100 entries),
  Tiers, Providers.
- **Main**: Selected artifact rendered as a timeline.

The read-only mode is the **default for v1.x of the GUI** — even
after M9 lands, `smolcode web --read-only` remains a flag for
auditing without execution risk.

---

## Layout sketch — uploads (M8, part of chat input)

The chat input grows a **drag-drop area + file picker** that
previews uploads before the user sends the message:

```
┌──────────────────────────────────────────────────────────────────────┐
│ PLAN     │  EXECUTION STREAM                       │ INSPECTOR       │
│          │                                         │                 │
│ Task:    │  ✓ Thought: "read the user's CSV"       │ Selected:       │
│ ┌──────┐ │  ⏺ list_uploads() →                     │  users.csv      │
│ │ Summa│ │     1. users.csv (4 KB, text/csv)       │  ─────────────  │
│ │ rize │ │     2. logo.png  (12 KB, image/png)     │  Size:  4 KB    │
│ │ the  │ │  ⏺ read_upload('users.csv') →           │  MIME:  csv     │
│ │ user'│ │     "id,name,plan\n1,Alice,pro\n..."     │  SHA:   a1b2c3… │
│ │ s CSV│ │  ⏸ Awaiting approval                  │  Uploaded:      │
│ │ and  │ │   shell.run  python summarize.py       │  2026-08-20     │
│ │ rank │ │   [Approve] [Edit] [Deny]              │  12:34:56       │
│ │ them │ │                                         │                 │
│ └──────┘ │  ── audit ───────────────────────────   │  Tier:          │
│          │  12:34:55 upload.add   users.csv 4 KB   │  uploads=read   │
│ Uploads: │  12:34:55 upload.add   logo.png  12 KB  │                 │
│ • users.cs│  12:34:56 upload.read users.csv        │  Preview:       │
│ • logo.pn│  12:34:57 shell.run   summarize.py ✓    │  ┌────────────┐ │
│ [Clear al│                                        │  │ id, name…  │ │
│          │                                         │  │ 1,Alice,pro│ │
│          │                                         │  │ 2,Bob,free │ │
│          │                                         │  └────────────┘ │
└──────────┴─────────────────────────────────────────┴─────────────────┘

┌─ chat input ──────────────────────────────────────────────────────────┐
│ ┌─ drop zone ──────────────────────────────────────────────────────┐   │
│ │  📎  Drop files here, or click to browse                        │   │
│ │     PDF, CSV, images, code — up to 50 MB each                   │   │
│ └─────────────────────────────────────────────────────────────────┘   │
│ [users.csv ×] [logo.png ×]                                            │
│                                                                      │
│ ┌─ text area ─────────────────────────────────────────────────────┐   │
│ │ Summarize the user's CSV and rank them by plan value.           │   │
│ └────────────────────────────────────────────────────────────────┘   │
│                                                       [Send ▶]        │
└──────────────────────────────────────────────────────────────────────┘
```

**Drop-zone behavior**:

- Empty state: dashed border, hint text, click to open file picker.
- Hover/drag-over: border becomes solid + tinted; cursor changes.
- After upload: thumbnails / file chips appear above the text area;
  each chip has an `×` to remove before sending.
- Rejected upload (size / MIME / name): red toast with the reason;
  no chip is added.

**Inspector behavior**:

- Clicking a chip in the chat input selects it in the inspector
  pane, showing size, MIME, SHA, timestamp, and a preview
  (text → first 1 KB; image → scaled thumbnail; PDF → "PDF preview
  not supported in v1").

**"Send" behavior**:

- Send = "submit task with these uploads attached".
- The agent's system prompt receives the upload list as a hint.
- The user can edit / remove chips between sending and the agent
  starting (M9 only; for M8 read-only, "Send" runs a stub).

---

## Validation strategy (when implementation starts)

For each phase:

1. **`make quality`** — ruff check + format (Python); `pnpm lint`
   + `pnpm format` (TypeScript).
2. **`make test`** — pytest must remain green; new tests added per
   feature; coverage gate stays ≥80%.
3. **Cross-platform smoke** — `smolcode web` opens a browser tab
   on Windows / Linux / macOS.
4. **Security smoke** — `smolcode web --bind 0.0.0.0` is rejected
   (only `127.0.0.1` allowed); no secret value ever appears in any
   HTTP response (tested by feeding a fixture secret and grepping
   responses).
5. **M7 invariants preserved** — redaction still installed; audit
   still append-only; tiers still enforced.

---

## Code Impact

**None yet.** This decision captures design only.

When implementation begins, expected files (preliminary, not committed):

| Phase | New files | Updated files |
|---|---|---|
| **M8** | `smolcode/web/server.py`, `smolcode/web/api.py`, `smolcode/web/uploads.py` (sanitize, MIME sniff, sidecar), `smolcode/web/dist/` (Vite output), `smolcode/web/src/` (React), `smolcode/src/smolcode/uploads/__init__.py` (CLI subcommand), `tests/test_web_server.py`, `tests/test_web_api.py`, `tests/test_uploads.py` (sanitize, MIME, sidecar, audit events, tier policy) | `smolcode/cli.py` (new `web` + `uploads` subcommands), `smolcode/src/smolcode/config.py` (new `uploads_dir` + `SMOLCODE_UPLOAD_*` env vars), `smolcode/src/smolcode/tiers.py` (`uploads = "read"` for restricted), `smolcode/src/smolcode/audit.py` (`upload.add/delete/read` events), `smolcode/src/smolcode/tools/fs.py` (block writes to uploads for restricted), `pyproject.toml` (add FastAPI/uvicorn to web extra), `docs/roadmap.md` (M8 SHIPPED), `docs/security.md` §3 (uploads tier matrix) |
| **M9** | `smolcode/web/runs.py` (SSE bridge), `smolcode/web/approval.py`, `smolcode/src/smolcode/tools/uploads.py` (`list_uploads` + `read_upload` tools) | `tests/test_web_runs.py`, `tests/test_uploads_tools.py` |
| **M10** | `smolcode/web/src/components/DiffViewer.tsx` | `tests/test_web_diff.py` |
| **M11** | `smolcode/web/src/components/SpecialistEditor.tsx`, `smolcode/audit_reader.py` | `tests/test_web_specialists.py`, `tests/test_audit_reader.py` |

New dependencies (recorded here, **not installed yet**):

- `fastapi>=0.115`
- `uvicorn[standard]>=0.32`
- `pydantic>=2.0` (likely already pulled transitively)
- Frontend (dev only): `react`, `react-dom`, `vite`, `typescript`,
  `tailwindcss`, `@shadcn/ui` (manual), `zustand`, `@tanstack/react-query`,
  `diff2html`, `xterm`, `react-arborist`

---

## Followups (post-0010)

1. **User approval**: this doc is the gate. If approved → schedule M8.
2. **M8 risks to watch**:
   - Bundle size pressure: keep the JS dep tree minimal.
   - Pydantic v1 vs v2: we use Pydantic v2 already in models.py;
     confirm FastAPI matches.
   - Browser auto-open: skip on headless servers; flag
     `--no-browser`.
3. **M8.5 optional**: a **VS Code extension** that consumes the same
   `/api` endpoints. Defers if M8 reveals UX problems.
4. **Hash-chained audit + GUI badge** — M7.5 + GUI integration; the
   GUI should show a "tamper-evident" badge once the chain is enabled.
5. **Theme**: light + dark from day 1; system-follow is cheap.
6. **Upload open questions** (D8) — defaults proposed; user may override:
   - **Folder visibility**: hidden (`.smolcode/uploads/`, default) vs
     visible (`uploads/`)?
   - **Default size cap**: 50 MB. Reasonable for personal use; too
     low for video; too high for shared hosting.
   - **Allowed MIME set**: the default allowlist (text + docs +
     images + code) is broad. Should `.exe`, `.so`, `.dll`, archives
     be allowed under any condition?
   - **Image handling**: direct multimodal content vs path reference?
     Direct needs a vision-capable model; path reference works for all.
   - **Cleanup UX**: should the GUI surface a "30-day-old uploads"
     filter even without `SMOLCODE_UPLOAD_TTL_DAYS` set, to nudge the
     user toward cleanup?
   - **Cross-session visibility**: should uploaded files from a prior
     session be auto-attached to the next run, or always require
     re-upload? Default: cross-session visible (because they persist
     on disk), but the system-prompt hint only mentions uploads added
     in the *current* session unless `--include-prior-uploads` is set.

---

## References

- `docs/architecture.md` — current components and contracts.
- `docs/security.md` — tier model, audit pipeline, redaction.
- `smolcode/docs/audit-log-retention.md` — audit rotation policy (M7).
- `docs/decisions/0006-m4-elevated-full-access-tiers.md` — tier policies.
- `docs/decisions/0007-m4x-per-tool-confirmation-checkpoint.md` — destructive-op gate (the modal's backend).
- `docs/decisions/0009-m7-polish-security-review.md` — M7 invariants the GUI must preserve.
- Claude Code / OpenCode GUI transcripts (reference UX, not code).
- shadcn/ui (https://ui.shadcn.com) — component library.
- FastAPI (https://fastapi.tiangolo.com) — backend framework.
- diff2html (https://diff2html.xyz) — diff rendering.
