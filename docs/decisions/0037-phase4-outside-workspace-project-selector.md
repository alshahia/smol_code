# Phase 4 F4 - outside-workspace project selector

**Date:** 2026-08-27
**Trigger:** phase-completion (Phase 4 of the 2026-08-27 web UI user-feedback remediation)
**Sources:**
- docs/reviews/2026-08-27-web-ui-user-feedback/PHASED-PLAN.md sec "Phase 4 - F4" (line 168+)
- docs/reviews/2026-08-27-web-ui-user-feedback/POLICY-DECISIONS.md (Q1/Q2/Q3 decisions)
- docs/reviews/2026-08-27-web-ui-user-feedback/REPORT.md sec F4 (Root cause: SPA wires half of what the BE supports)
- Source prior art: docs/decisions/0025-web-ui-ux-review-and-roadmap.md sec 6.3 (per-project scope), docs/decisions/0036-phase2-audit-integrity.md (audit chain contract this work inherits)
- Commits: chore pre-Phase-4 (8a0a055) + Phase 4 FE (108b145) + Phase 4 tests + _helpers.ts extension + e2e + this ADR

---

## Question

F4 from the 2026-08-27 user-feedback report: the project selector only lists projects the server has been told about in advance, and there is no UI to attach an arbitrary outside-workspace folder as a project. The BE POST /api/projects already accepts {name, root?} and validates that the root exists (see smolcode/src/smolcode/web/schemas.py:63-92 and api.py:352-398). The SPA's <ProjectSwitcher> pre-Phase-4 only ever sent {name}, so the SPA lost half the BE's contract.

How should Phase 4 close the gap without changing the BE, and without lying about the limitations of the <input webkitdirectory> browser API?

## Findings

- The BE POST /api/projects is already correct and has 4 characterization tests in test_projects_phase3.py::TestProjectCreateWithRoot (all pass since dc2c094).
- Browsers do NOT expose an absolute path to a folder selected via <input type="file" webkitdirectory> (W3C File API spec + Chrome bug 1147690 + long-standing browser security stance). The SPA can only read File.webkitRelativePath which is rooted at the picked folder's top-level name; the user has to paste the absolute path themselves. Lying about this would be the bug F1-F3 carefully avoided.
- localStorage.smolcode.activeProject.v1 is already established as the persistence convention (App.tsx:104-113). The recent-projects list persists under smolcode.recentProjects.v1 in the same shape.
- The Inspector already surfaces effective_cwd (Phase 3 F3) and the workspace path is already on ConfigResponse (api.ts:22-33), so the FE has everything it needs to compute the outside-workspace notice without any new wire field.
- The BE's POST /api/projects only enforces that root.exists() (400 otherwise) - there is no "is the root inside the workspace" check. The FE must do the "outside-workspace" hint itself; the BE's 400 is authoritative.

## Decision

Make the SPA preserve the BE's {name, root?} contract end-to-end:

1. Path input + Browse button in <ProjectSwitcher>. The Browse button prefills the Path field with a hint string ("<paste absolute path containing <top-folder-name>>") when the user picks a folder; the user must paste the absolute path manually. We do not pretend we got the absolute path from the browser - that is impossible.
2. Recent projects dropdown persisted under localStorage.smolcode.recentProjects.v1, capped at 8 entries, FIFO + dedupe by project name. Clicking a recent fills Name + Path. xR button clears the list. Delete-project also drops the entry.
3. Outside-workspace notice rendered when the typed path resolves outside the live workspace (case-insensitive containment after normalising path separators). Tolerant - not a security boundary; the BE's 400 is authoritative.
4. workspace prop on <ProjectSwitcher> (passed from <App> as config?.workspace ?? '') so the SPA can compare paths without re-fetching config.
5. Backward-compatible: when the Path input is left empty, handleCreate still sends {name} and the BE defaults the root to <workspace>/<name> exactly as before.
6. New tests:
   - src/__tests__/ProjectSwitcher.test.tsx (7 vitest cases) - basic create / select / Browse visibility.
   - src/__tests__/ProjectSwitcherOutside.test.tsx (14 vitest cases) - outside-workspace notice + recent-projects persistence / dedup / cap / click-fill / clear / delete-eviction.
   - e2e/project-switcher.spec.ts (5 Playwright cases) - happy paths through the real mockBackend.
7. Test-helper extension: _helpers.ts gains MockProject type + opts.projects + POST /api/projects (with BE-faithful 400 on duplicate name) + DELETE /api/projects/{name} mocks. Existing e2e tests still pass.

## Why we did not extend the BE

POST /api/projects is already correct (PHASED-PLAN task 7: the BE already supports this). The 4 characterization tests in test_projects_phase3.py document the contract. Modifying the BE for this phase would have changed behaviour with no semantic gain - the right fix is on the SPA side, where the contract was being half-used.

## Code impact

- smolcode/web/src/components/ProjectSwitcher.tsx (rewrite, +~140 / -~20): adds Name/Path pair, Browse (<input webkitdirectory>), Recents select, Outside-workspace notice, isOutsideWorkspace helper.
- smolcode/web/src/App.tsx (+1 / -0): passes workspace={config?.workspace ?? ''} to <ProjectSwitcher> (in chore pre-Phase-4 commit 8a0a055).
- smolcode/web/src/__tests__/ProjectSwitcher.test.tsx (new, ~75 LOC).
- smolcode/web/src/__tests__/ProjectSwitcherOutside.test.tsx (new, ~166 LOC).
- smolcode/web/src/__tests__/EventStream.test.tsx (3-line assertion sync): onApprovalRequest was extended in commit eb892e0 with (kind, absoluteTarget?, effectiveCwd?, allowedActions?) trailing args; the test now asserts the 8-arg form.
- smolcode/web/e2e/_helpers.ts (+~70 / -5): MockProject type + projects response + POST/DELETE handlers.
- smolcode/web/e2e/project-switcher.spec.ts (new, ~75 LOC).

## Limitations + honesty

- The Browse button cannot yield an absolute path. We surface this in the title ("Pick a folder (prefills the path field with its name; browsers cannot expose absolute paths)") and in the hint we render into the path field.
- The "outside workspace" notice is a SPA-level heuristic (case-insensitive containment). It will produce false positives on symlinks that span drives and false negatives when the workspace mount-point differs between OS / container / host. The BE does the authoritative 400 if the root does not exist; the SPA cannot make a stronger statement than that.
- LocalStorage recents are per-browser-profile, not per-user-account; switching browsers does not bring your recents along.
- The duplicate-key React warning in the vitest output for the dedup-and-rewrite test is a test artifact (the test forces three back-to-back creates with the same name to validate recent-projects eviction); in production the BE rejects the duplicate with 400 before it can reach the projects list.

## Validation

- pnpm test (vitest) - 114 / 114 PASS, 0 fail. New tests: 21/21 in Phase 4 + 1 pre-existing EventStream assertion sync.
- uv run ruff check src + uv run ruff format --check src - clean (no BE changes this phase).
- uv run pytest src/smolcode/tests -q -m 'not docker' - 1311 passed, 1 skipped, 12 deselected in 121.16s.
- Manual probe: with project 1 anchored + RunComposer checkbox, write x.py from inside the agent - Inspector shows the file landed under <project root> (Phase 3 F3, preserved). Selecting "outside" in the new Path field + pressing Enter sends POST /api/projects {name, root: '<abs path>'} and the project becomes selectable.

## References

- Source plan: docs/reviews/2026-08-27-web-ui-user-feedback/PHASED-PLAN.md sec "Phase 4" (lines 168-198)
- Source review: docs/reviews/2026-08-27-web-ui-user-feedback/REPORT.md sec F4
- Policy: docs/reviews/2026-08-27-web-ui-user-feedback/POLICY-DECISIONS.md
- BE contract pinned by: smolcode/src/smolcode/tests/test_projects_phase3.py
- Prior art: docs/decisions/0025-web-ui-ux-review-and-roadmap.md sec 6.3 (per-project scope shape this expansion preserves)
- Workspace prop chain: Phase 3 F3 (decision 0036 in commit messages, ADR code 0037) added effective_cwd; this Phase reuses the live workspace from /api/config (which already exposes workspace) without any new wire field.
- Honest-limitation precedent: same philosophy as Phase 1 (no fake counters), Phase 2 (no fake context windows), Phase 3 (no fake path-suppression). The Browse button is the only "we can't do this truthfully" affordance in the SPA, and we surface that in copy rather than fake it.
- Commit-message numbering note: earlier commits in the user-feedback batch were tagged "[decision 0036]" but 0036 is the Phase 2 audit-integrity ADR. This 0037 doc is the canonical home for the F1+F2+F3+F4 batch as a single user-feedback remediation, even though its work ship time spans multiple commits.

