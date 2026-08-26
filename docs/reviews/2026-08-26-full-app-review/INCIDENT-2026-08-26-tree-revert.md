# Incident note — working-tree revert during Phase 0 validation (2026-08-26)

**Status:** root-caused & closed · **Severity:** data-loss event (recovered; no committed history affected)

## What happened
At ~13:48:01 (+0300), while the full pytest suite ran in the background, every
uncommitted Phase-0 edit in the working tree was reverted to HEAD `b014e22`.
Git reflog records the cause:

    b014e22 HEAD@{2026-08-26 13:48:01 +0300}: reset: moving to HEAD

i.e. a `git reset [--hard]` / IDE "discard all changes" style operation executed
against the repository while edits were uncommitted. All edits were re-applied
afterwards and re-verified.

## Ruled out
- `checkpoint.py`: reviewed in full — every git invocation is `cwd`-scoped to its
  target workspace and it never calls `git reset`.
- No `git reset`/`checkout`/`restore` call sites exist anywhere in
  `smolcode/src/smolcode` outside test fixtures operating on tmp dirs.
- Harness tooling performed no git mutations (review-only constraints).

## Residual suspicion
The revert window overlaps a full-suite pytest run. A causal link is considered
unlikely (no code path reaches the parent repo) but cannot be fully excluded
until the suite is rerun under observation. If an editor session discarded
changes around 13:48, that explains the event entirely.

## Resolution (same day, later)
Root cause found while recovering the review reports: an external **
`smolcode-checkpoint`** tool (14 occurrences in `git stash list`, dating back to
2026-08-25) periodically runs `git stash push --include-untracked`. The 13:48
stash (`stash@{0}` = `40ca0a6`, message
`smolcode-checkpoint-2026-08-26T10:48:01Z-12988`) did exactly that:
- The reflog line `reset: moving to HEAD` is the reset `git stash push`
  performs internally — matching timestamp to the second.
- Tracked Phase-0 edits went into the stash worktree commit; the eight untracked
  review/plan documents went into its third parent `4571f7c`
  (`untracked files on main`). Only the tracked half was ever restored by hand;
  the documents sat in the stash until recovery.
- `checkpoint.py` in this repo was correctly exonerated — the culprit is an
  editor/tool-side auto-checkpoint feature.

**Recovery:** all eight files restored byte-for-byte via
`git checkout 4571f7c -- docs/reviews/2026-08-26-full-app-review/` and committed.
The stash itself is left untouched (it also holds the superseded first-draft
edits; dropping stashes is destructive and unnecessary now).

**Standing risk:** the checkpoint tool can swallow untracked work at any moment.
Mitigation going forward: keep uncommitted-work windows short; commit validated
increments promptly; treat sudden "empty tree" during long test runs as this
tool firing, not as code misbehaving.

## Consequence for the plan
- Full-suite validation deferred until the Phase-0 change set is committed or
  otherwise protected.
- New finding folded into the consolidated report follow-ups: any code path
  that could ever mutate the parent repo from tests must be structurally
  impossible (guards + CI assertion); tracked under REMEDIATION-PLAN Phase 5.
