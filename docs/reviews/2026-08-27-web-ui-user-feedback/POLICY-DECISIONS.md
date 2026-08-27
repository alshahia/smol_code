# Web UI Feedback - Phase 3 Policy Decisions

**Date:** 2026-08-27
**Captured by:** user (in reply to the F1-F4 remediation plan question)
**Status:** active - all three questions resolved; Phase 3 work may proceed.
**Source plan:** `PHASED-PLAN.md` (Phase 0 task 9 calls for this file).
**Source report:** `REPORT.md` (F3 + the "Decision needed before Phase 3 starts" section).

---

## Why this file exists

Phase 3 of the Web UI feedback plan modifies `write_file` / `patch_file` path resolution and adds two new affordances (a confirmation modal for outside-root writes, and an Open-in-Explorer endpoint). Three policy decisions affect the design and must be locked before Phase 3 starts so the implementation does not have to be redone.

## Decisions

### Q1 - Anchor-mode default (which determines whether selecting a project redirects writes by default)

**Decision: OFF per-run** (user picked option 1).

Implications for Phase 3 implementation:

- `RunStartRequest.anchor_to_project_root: bool = False` is the wire default; the SPA renders a per-run checkbox below the project selector, **default unchecked**.
- Existing runs without a project selected continue to behave exactly as today (writes anchored to `settings.workspace`).
- `effective_cwd` is resolved as `(anchor_to_project_root AND run.project AND matching project root exists) ? Path(matching_project_root) : Path(settings.workspace)`.
- Documentation and Inspector banner copy will say: "this run's files landed in {effective_cwd}, not in project {run.project} ({project.root}). Enable **Anchor writes to this project's root** in the composer next time."

### Q2 - Outside-root policy (what happens when an anchored run tries to write a path outside the project root)

**Decision: BLOCK + confirmation modal that shows the FULL absolute path + a per-session per-path auto-approve option.**

This is more nuanced than the three options originally offered in the plan; the user's answer combines the strictness of "block" with the UX of a confirmation gate.

**Flow:**

1. The diff callback (`_build_diff_callback`) is invoked with a `path` that resolves outside `effective_cwd`.
2. The callback computes `absolute_target = str(Path(path).resolve())`.
3. If `absolute_target in SessionState.outside_root_allowlist` -> auto-approve (no modal), emit `diff_decision` audit record with `outside_root=true, auto_approved=true`.
4. Else -> raise a NEW kind of approval: `kind="outside_root"`. Set run status to `STATUS_AWAITING_APPROVAL`. Publish `approval.requested` SSE event with payload `{decision_id, absolute_target, effective_cwd, allowed_actions: ["deny", "approve_once", "approve_session_for_path"]}`. Block on `PendingDecision.event`.
5. SPA renders an `<ApprovalModal>` variant titled **"Outside-project write"** showing:
   - **Full absolute target path** (prominent monospace, e.g. `E:\python projects\smol_code\smolcode\.web-ws\..\etc\passwd`).
   - Effective cwd (the project root) for context.
   - Three buttons: **Deny** / **Approve once** / **Approve for this session for THIS path**.
6. On **Deny**: `DiffDecision(approved=False)` -> tool raises `PermissionError`. Audit emits `outside_root=true, approved=false, action=deny`.
7. On **Approve once**: `DiffDecision(approved=True, reason="user-once")`. Audit emits `outside_root=true, approved=true, action=approve_once`.
8. On **Approve for this session for THIS path**: add `absolute_target` to `SessionState.outside_root_allowlist`. Then `DiffDecision(approved=True, reason="user-session-for-path")`. Audit emits `outside_root=true, approved=true, action=approve_session_for_path, allowlist_size=<len>+1`.
9. `SessionState.outside_root_allowlist` lives on the per-run SessionState (matches the existing `auto_approve_destructive` field's lifecycle); it is RESET on a new run (new SessionState = fresh allowlist). The "for this session" wording in the UI is honest - it means "for the lifetime of THIS run's session".

**Data model:**

```python
# smolcode/src/smolcode/session.py (SessionState extension)
@dataclass
class SessionState:
    # ... existing fields ...
    # Phase 3 (F3 outside-root policy): per-session per-path allowlist for
    # outside-project writes. Populated when the user picks
    # "Approve for this session for THIS path" in the outside-root modal.
    # Reset on every new SessionState() (every new run).
    outside_root_allowlist: set[str] = field(default_factory=set)
```

**Implications for Phase 3 implementation:**

- New audit `event="outside_root_decision"` (or extend `diff_decision` with `outside_root` field; prefer extending to keep audit taxonomy tight).
- New SPA component or `<ApprovalModal>` variant for the three-button flow (or a new `kind="outside_root"` branch in the existing modal).
- `RunManager.set_auto_approve` is the existing mechanism for the global auto-approve flag; the new per-path allowlist lives on `SessionState` (read via `current_session()` inside the diff callback), NOT on `RunManager`.
- The check `absolute_target in current_session().outside_root_allowlist` must be race-free under the existing `Run.pending_lock`.
- Test fixtures must cover all four outcomes (auto-allow hit / deny / approve once / approve session).

### Q3 - Open-in-Explorer scope (what paths the new POST /api/open-path endpoint accepts)

**Decision: any path under `effective_cwd`** (user picked option 1).

Implications for Phase 3 implementation:

- The endpoint accepts `{"run_id"?: str, "path": str}`. When `run_id` is provided, the whitelist is `run.effective_cwd`; when omitted, the whitelist is `settings.workspace`.
- The check is the same containment helper used by `GET /api/files` (path-resolve + commonpath) - one source of truth.
- `full_access` tier is exempt from the whitelist (consistent with the rest of the system - full_access can already reach anywhere). The endpoint records `outside_whitelisted=true` in the audit for full_access opens, for forensic traceability.
- Return codes: 200 on success; 403 on path-escape; 404 if path missing; 500 with redacted detail on subprocess failure.

---

## Resolution summary

| # | Question | Decision | Surface code (Phase 3 task) |
|---|---|---|---|
| 1 | Anchor-mode default | OFF per-run | Task 1-2 (Run / RunStartRequest) |
| 2 | Outside-root policy | BLOCK + full-path modal + per-session per-path allowlist | Task 5 (diff callback), new Task 10a (SessionState extension + new modal variant) |
| 3 | Open-in-Explorer scope | any path under effective_cwd | Task 6 (open-path endpoint) |

---

## What this file unblocks

- Phase 3 TASKS can be scoped tightly (no re-work needed when implementation lands).
- The Phase 0 RED tests can be written deterministically (each test asserts exactly the behaviour above).
- The Inspector banner copy is fixed.

## What this file does NOT cover

- Decisions abouts skills vs tools in the context-circle breakdown (F2) - left to the Phase 2 implementation; the user can revisit at any time without changing Phase 3.
- The `full_access` tier's open-path exemption (Q3 note above) - if the user wants to narrow this, the change is a single-line whitelist flip in the endpoint.

---

## Sign-off

- User (verbal, 2026-08-27): "Q1 OFF per-run / Q2 Block + full path + auto-approve for session for this path / Q3 any path under effective_cwd".
- Captured into this file by the assistant on the same date.
- Phase 0 task 9 marked RESOLVED.