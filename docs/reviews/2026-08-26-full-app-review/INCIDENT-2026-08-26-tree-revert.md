# Incident note — working-tree revert during Phase 0 validation (2026-08-26)

**Status:** resolved-for-reapply · **Severity:** data-loss event (uncommitted work only; no committed history affected)

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

## Consequence for the plan
- Full-suite validation deferred until the Phase-0 change set is committed or
  otherwise protected.
- New finding folded into the consolidated report follow-ups: any code path
  that could ever mutate the parent repo from tests must be structurally
  impossible (guards + CI assertion); tracked under REMEDIATION-PLAN Phase 5.
