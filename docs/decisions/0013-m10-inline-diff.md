# 0013 — M10 inline diff viewer + workspace tree implementation log

**Date:** 2026-08-23
**Status:** active
**Trigger:** M9 SHIPPED (decision 0012). User asked to proceed to M10
(decision 0010 F5 phase 5: inline diff viewer for write_file/patch_file,
apply/reject per step, workspace tree in inspector).
**Related:** decision 0010 (design D2, F5), decision 0012 (M9
implementation log + the diff.proposed/diff.resolved event design that
was deferred from M9), roadmap.md M10, architecture.md §14 (new),
security.md §3.6 (new), README M10 section.

---

## Question

How do we ship the M10 slice of decision 0010 (inline diff viewer for
write_file and patch_file, per-step apply/reject, workspace tree in the
inspector pane) end-to-end while preserving the M0–M9 invariants
(tier policy, audit log, sandbox isolation, bind allowlist, 80%
coverage gate, SSE event naming, audit "diff_decision" event,
`SMOLCODE_WEB_DIFF_GATE` CLI parity opt-out, restricted-tier upload
read-only block)?

## Findings

### F1. M10 was the deferred v1.3 work in decision 0012

0012 §Followups projected M10 as the next slice:

> **M10** (inline diffs + tree): inline diff viewer for
> write_file / patch_file; apply / reject per step; workspace tree.

Decision 0010 also lists M10 in the F5 phasing table as ~5 days, with
the explicit note "no new execution surface" — every M10 capability is
a UI/UX layer on top of the M9 diff gate plumbing.

### F2. The diff gate plumbing already exists (0012 §F4)

The `diff.proposed` / `diff.resolved` SSE event pair, the
`SessionState.diff_callback` hook, the `EVT_DIFF_PROPOSED` /
`EVT_DIFF_RESOLVED` constants, and the `PendingDecision.kind = "diff"`
extension were all shipped in M9. What was deferred to M10 was:

- The backend `diffs.py` helpers that build structured hunks + stats
  + a raw unified-diff text for the SPA.
- The frontend `DiffViewer` component that color-codes added /
  removed / context lines.
- The frontend `WorkspaceTree` component that calls
  `/api/workspace/tree` and highlights paths the run has touched.
- The extension of `ApprovalModal` to render `DiffViewer` for diff
  proposals (vs. the existing JSON-args layout for destructive
  approvals).
- The `postApproval` API helper extension to forward `edited_after`.
- The `/api/workspace/tree` endpoint + its `TreeEntry` /
  `WorkspaceTreeResponse` schema.
- The new `patch_file` fs tool (the M10 part of the F5 surface).

### F3. `difflib.restore` is broken for unified-diff input

The Python 3.12 standard library ships `difflib.restore(sequence,
which)` with documentation claiming it accepts "lines produced by
`Differ`". For any input that is NOT a `Differ` output — including
GNU unified-diff text — the implementation returns `[]` for both
`which=1` and `which=2`. This was confirmed by direct experiment
against `python -c "list(difflib.restore(['--- a','+++ b','@@ -1 +1
@@','-x','+y'], which=2))"` which yields `[]`.

The first cut of `_PatchFileTool._apply_unified` relied on this. The
fix is to hand-roll a hunk applier that walks `@@ -OLD,COUNT +NEW,COUNT
@@` headers, parses each ` ` / `-` / `+` body line, and applies them
left-to-right against the BEFORE text. This also gives us proper
error messages ("deletion line does not match source at old line 5")
and supports trailing-newline preservation.

### F4. smolagents' AST validator rejects undefined Names in tool bodies

When the diff-gate consult is inlined in `_WriteFileTool.forward()`
and `_PatchFileTool.forward()`, the validator
(`tool_validation.MethodChecker`) walks the method body and rejects
any `Name` that it cannot prove is locally bound. The original attempt
put a `_resolve_diff_decision(...)` helper at module scope; that name
was rejected. The fixed pattern — used in `tools/shell.py` for years
— is to put the absolute `from ... import ...` statements INSIDE the
method body so the validator sees them as local imports.

This is documented as a Standing rule for M10+ tools that need to
talk back to the host process.

### F5. Windows atomic write needs `newline=""`

`_PatchFileTool.forward()` writes the post-image via
`os.fdopen(fd, "w", encoding="utf-8")`. On Windows, default text
mode translates `\n` → `\r\n` on write. The first test that
asserted no-trailing-newline preservation
(`test_apply_unified_preserves_no_trailing_newline`) failed because
the file on disk contained `a\r\nB\r\nc` instead of `a\nB\nc`. The
fix is `newline=""` (preserves LF verbatim).

### F6. Coverage gate: M9 → M10

- M9 closure (decision 0012): 596 tests, 80.0%.
- M10 closure: 667 tests, 81.48%.
- 71 new tests:
  - 23 in `test_diffs.py` (diffs.py helpers).
  - 30 in `test_patch_file_tool.py` (_PatchFileTool + _apply_unified
    hunk applier, including 11 edge cases for malformed headers,
    multiple hunks, no-trailing-newline preservation, out-of-order
    hunks, hunk body count mismatch, blank hunk lines, no-newline-at-eof
    markers, insert at top, empty file).
  - 7 in `test_web_runs_api.py` (`/api/workspace/tree` + approval
    with `edited_after` + touched_paths summary).
  - 11 in `test_agent_runner.py` (4 _rel_path, 7 _build_diff_callback:
    stop-flag deny, publish diff.proposed, timeout deny, touched_path
    recording, audit sink, edited_after end-to-end, diff compute
    failure tolerance).
  - 1 fix in `test_tools_build.py` (`patch_file` in the combined
    tool name list).

## Decision

### D1. New `patch_file` tool (M10 fs surface)

The M10 F5 phasing table calls for an inline diff viewer for
write_file/patch_file. The viewer requires a tool that takes a
unified-diff text and applies it. The M9 tool surface had
`write_file(path, content)` only; M10 adds
`patch_file(path, diff_text)`:

- Workspace boundary checks (mirrors `write_file`).
- Tier policy (restricted tier cannot patch files under uploads).
- Atomic write (tempfile + os.replace) — partial writes do not leave
  a truncated file on disk.
- Diff gate consult (session.diff_callback) — see D2.
- Custom `_apply_unified` (see F3) — `difflib.restore` is not
  suitable for unified-diff input.

### D2. The diff gate is inlined in `write_file` and `patch_file`

The `SessionState.diff_callback` was added in M9 (decision 0012
§F4) but was not yet consumed by the fs tools. M10 wires the
callback into both `_WriteFileTool.forward()` and
`_PatchFileTool.forward()`. Pattern (smolagents AST validator
constraint — see F4):

```python
def forward(self, path, content):
    # ... workspace / tier checks ...
    before = ""
    if resolved.exists():
        try:
            before = resolved.read_text(encoding="utf-8")
        except OSError:
            before = ""
    from smolcode.session import DiffDecision as _DiffDecision  # M10
    from smolcode.session import current_session as _current_session  # M10
    sess = _current_session()
    cb = sess.diff_callback
    if cb is not None and not sess.auto_approve_diff:
        # ... publish diff, block on event, return DiffDecision ...
```

The callback returns a `DiffDecision(approved, edited_after=None,
reason=...)`. If `approved=False` the tool raises `PermissionError`
and the agent sees the failure (the smolagents loop will report it
in `step.action.observations`).

`SMOLCODE_WEB_DIFF_GATE` env var controls the gate at the runner
level — when set to `0` (CLI parity), `session.diff_callback` is
left as `None` and the tools write directly. Default is `1`.

### D3. New `diffs.py` module (`src/smolcode/web/diffs.py`)

Helpers used by the runner to build the diff payload:

- `unified_hunks(before, after) -> list[DiffHunk]` — SequenceMatcher
  ops with `equal | replace | insert | delete` tagged rows.
- `unified_text(before, after, context=3) -> str` — GNU unified-diff
  text (the raw_diff field of the SSE payload).
- `summarize(before, after) -> {added, removed, same, changed}` —
  counts for the diff stats badge.
- `walk_tree(root, max_entries=5000, max_depth=10,
  skip_dirs=(".git", "__pycache__", "node_modules", ".venv", "venv",
  ".tox")) -> (entries, truncated)` — the workspace tree. Hidden
  dotfile dirs are skipped EXCEPT `.smolcode` (so the uploads
  folder is visible).
- `read_text_for_diff(path) -> (text, truncated, error)` — UTF-8
  read with size cap and binary-rejection.

### D4. New `/api/workspace/tree` endpoint

```
GET /api/workspace/tree?max_entries=5000&max_depth=10
-> WorkspaceTreeResponse{workspace, entries[], truncated, max_entries, max_depth}
```

`max_entries` is clamped 1..20000; `max_depth` is 1..20. The
endpoint walks the workspace via `diffs.walk_tree` and serialises
via `TreeEntryOut`. Frontend polls every 10 s via the new
`WorkspaceTree` component.

### D5. Approval endpoint accepts `edited_after`

`POST /api/runs/<id>/approval` now accepts an optional
`edited_after: str | None` field. The backend stores it on the
`PendingDecision.edited_args = {"__edited_after__": str(...)}` dict
and the runner's `_build_diff_callback` plucks it back out when it
constructs the `DiffDecision` returned to the tool.

### D6. `RunSummary.touched_paths: list[str]`

The `Run` dataclass gains a `touched_paths: set` (with lock) and
`record_touch(rel_path)` / `touched_list()` helpers. The diff
callback calls `run.record_touch(rel_path)` so the workspace tree
in the inspector pane can highlight files the agent has written
or patched this run. The list is exposed via `GET /api/runs/<id>`.

### D7. Frontend: DiffViewer + extended ApprovalModal + WorkspaceTree

- `components/DiffViewer.tsx` (NEW) — color-coded unified-diff
  renderer. Reads `hunks` if the backend provided structured hunks,
  falls back to parsing `raw_diff`. Per-line tags: ` ` (context,
  default), `-` (red), `+` (green). Stats badge: `+N -N unchanged M`.
  Optional inline editor that lets the user rewrite the proposed
  content; on Apply-edit the modal passes `edited_after` to the
  approval POST.

- `components/ApprovalModal.tsx` — when `pending.kind === 'diff'`,
  render `DiffViewer` with `editable=true` (the editor is the M10
  "edit + approve" flow). Destructive approvals keep the original
  JSON-args layout.

- `components/WorkspaceTree.tsx` (NEW) — collapsible tree with
  refresh button. Files + dirs from `/api/workspace/tree`,
  highlighted (yellow background + amber border) when the path
  appears in `activeRun.touched_paths`.

- `components/EventStream.tsx` — renderers for `diff.proposed` (with
  a collapsible raw-diff body) and `diff.resolved` (muted,
  one-liner). Forwards `diff.proposed` events to the parent via a
  new `onDiffProposed` prop.

- `App.tsx` — adds the diff-proposal handler (sets `pending.kind =
  'diff'` and copies the diff payload into `pending`). Extends
  `onDecide` to forward `editedAfter` to `postApproval`. Mounts
  `WorkspaceTree` in the Inspector pane (Workspace section) and
  passes `activeRun.touched_paths` for highlighting.

### D8. No CLI / agent-runtime changes

M10 is purely a web UX layer. The CLI flow (`smolcode run`,
`smolcode --tier elevated ...`) is unchanged. Agents running under
the CLI get the same `SessionState.diff_callback == None` path as
M9; the patch_file tool does its work directly without UI
consultation. The `SMOLCODE_WEB_DIFF_GATE=0` env var gives CLI
parity under the web view.

### D9. Audit logging

Every diff gate decision emits a `diff_decision` audit event via
`run.audit_sink.record(...)`, mirroring the M9
`destructive_decision` audit event. Fields: `tool`, `path`,
`summary`, `approved`, `reason`, `edited`, `run_id`. This lets
post-hoc reviewers reconstruct exactly which file changes the user
approved / denied / edited.

## Code Impact

### New files

- `src/smolcode/web/diffs.py` — helpers for diff computation + tree
  walk (D3).
- `src/smolcode/tests/test_diffs.py` — 23 tests.
- `src/smolcode/tests/test_patch_file_tool.py` — 30 tests.
- `web/src/components/DiffViewer.tsx` — inline diff renderer (D7).
- `web/src/components/WorkspaceTree.tsx` — workspace tree (D7).

### Modified files

- `src/smolcode/tools/fs.py` — added `_PatchFileTool` (D1),
  inlined the diff-gate consult in `_WriteFileTool.forward()` and
  `_PatchFileTool.forward()` (D2), wired the new tool into
  `build_fs_tools()`. Custom `_apply_unified` (F3). `newline=""`
  on the atomic write (F5).
- `src/smolcode/session.py` — `DiffDecision` dataclass,
  `DiffCallback` type, `SessionState.diff_callback`,
  `SessionState.auto_approve_diff` (already shipped in 0012 F4,
  now consumed).
- `src/smolcode/web/runs.py` — `EVT_DIFF_PROPOSED` /
  `EVT_DIFF_RESOLVED` constants, `PendingDecision.kind/path/before/after`
  extension (0012 F4), `Run.touched_paths` + `record_touch` /
  `touched_list()` (D6), `RunManager.decide(..., edited_after=...)`
  that stores `edited_after` in `edited_args` and publishes
  `EVT_DIFF_RESOLVED` when `kind == "diff"`.
- `src/smolcode/web/agent_runner.py` — `_rel_path`,
  `_build_diff_callback` that publishes `diff.proposed` with the
  full structured payload (hunks + raw_diff + stats + timeout) and
  blocks on the decision event (D2). Wired into
  `session.diff_callback` in `run_in_thread` (gated by
  `SMOLCODE_WEB_DIFF_GATE`).
- `src/smolcode/web/schemas.py` — `RunSummary.touched_paths`,
  `ApprovalDecisionRequest.edited_after`,
  `TreeEntryOut` / `WorkspaceTreeResponse` (D4, D5, D6).
- `src/smolcode/web/api.py` — `/api/workspace/tree` endpoint (D4),
  approval endpoint extended with `edited_after` (D5),
  `_run_summary()` now passes `touched_paths=run.touched_list()`
  (D6).
- `src/smolcode/tests/test_tools_build.py` — `patch_file` in the
  combined tool-name list.
- `src/smolcode/tests/test_web_runs_api.py` — 7 new tests:
  approval with `edited_after`, workspace tree endpoint (returns
  entries / dotdir skip / marks dirs / truncates / rejects bad
  params), run summary includes touched_paths.
- `src/smolcode/tests/test_agent_runner.py` — 11 new tests for
  `_rel_path` and `_build_diff_callback`.
- `web/src/api.ts` — `StreamEvent` extended with `diff.proposed`
  / `diff.resolved` and the diff payload fields,
  `postApproval(..., editedAfter)`, `getWorkspaceTree(...)` plus
  `TreeEntry`, `DiffHunk`, `DiffStats`, `WorkspaceTreeResponse`.
- `web/src/components/ApprovalModal.tsx` — supports `kind='diff'`
  and renders `DiffViewer` with the editor; destructive kind keeps
  the existing JSON-args layout (D7).
- `web/src/components/EventStream.tsx` — renderers for
  `diff.proposed` / `diff.resolved`; forwards diff events to the
  parent (D7).
- `web/src/App.tsx` — diff-proposal handler, `WorkspaceTree`
  mounted in Inspector pane, `onDecide` forwards `editedAfter`.
- `web/src/index.css` — styles for diff viewer, wide approval card,
  workspace tree, diff event rows.

## Validation

- `ruff check src` — clean.
- `ruff format --check src` — clean.
- `pytest src/smolcode/tests` — 667 passed, 1 skipped (the existing
  pre-M10 skip), coverage 81.48% (gate 80%).
- `pnpm --dir web lint` — 0 errors, 1 pre-existing warning in
  StopButton.tsx (out of M10 scope).
- `pnpm --dir web build` — 213.65 kB JS (gzip 66.33 kB), 11.36 kB
  CSS (gzip 2.83 kB). 0 errors.
- Manual end-to-end smoke: start the server, run a task, observe
  the diff modal open, edit the content, apply + approve, see the
  workspace tree update with the touched path highlighted.

## Followups

- **M11** (future): MCP tool result preview — when an MCP server
  returns a structured payload (PR description, ticket body), render
  it inline in the stream instead of dumping JSON. Decision 0010
  F5 phase 6.
- **M11** (future): cross-run search across `diff_decision` audit
  events so the user can replay past approvals / edits.
- **M11+** (deferred from 0011): WebSocket transport for SSE
  (not needed yet — SSE works fine over loopback and EventSource
  reconnects automatically on disconnect).

## References

- Decision 0010 §F5 (M10 phasing table).
- Decision 0011 §Followups (M10 deferred to v1.3).
- Decision 0012 §F4 (M9 diff-gate plumbing; deferred diff.proposed
  / diff.resolved to M10).
- `docs/architecture.md` §14 (M10 architecture).
- `docs/security.md` §3.6 (diff gate audit model).
- `docs/roadmap.md` M10 row.
- `smolcode/README.md` M10 section.
