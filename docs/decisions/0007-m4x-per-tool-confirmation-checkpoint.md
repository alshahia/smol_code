# 0007 — M4.x: per-tool destructive-op confirmation + git checkpoint

**Date:** 2026-08-19
**Status:** active
**Supersedes:** — (none; extends 0006)
**Related:** `0006-m4-elevated-full-access-tiers.md`, `docs/roadmap.md` §6, `docs/security.md` §10

## Question

Once a `full_access` run is confirmed (per decision 0006), how do we
narrow the window of damage from individual destructive tool calls
inside the run? Specifically:

1. **Granular destructive gate.** The M4 prompt gates the run, not
   the individual tool calls. A run that calls `git_push` 12 times
   gets one prompt, then 12 silent pushes. Some of those pushes are
   to `origin/main` (fine, intentional), some are to
   `production-east` (the user did not want that).
2. **Auto-approve toggle.** Sometimes the user wants every
   `git_push` (or every `docker rm`) approved automatically. Other
   times they want to be prompted for every one. They want to
   toggle this *during* the run, not just before it.
3. **Pre-run checkpoint.** If a `full_access` agent nukes the user's
   working tree, they should be able to roll back. The current run
   prompt doesn't help — once the user types `y`, the agent has the
   keys. We need a pre-run snapshot so a typo doesn't destroy
   unsaved work.

## Findings

### Threat model delta from M4

M4 (decision 0006) stopped the user from accidentally entering
`full_access` tier. M4.x stops the `full_access` agent from
accidentally doing irreversible harm *inside* the run, AND gives the
user a way to recover when it does.

Three concrete harms to defend against:

1. **A push to the wrong branch / wrong remote.** A common agent
   failure mode: the model picks `master` instead of `main`, or
   `origin` instead of the user's fork. M4.x prompts before every
   `git_push`.
2. **A bulk-delete or cloud destroy.** `rm -rf ./build`, `aws s3
   rm s3://prod-data`, `kubectl delete deployment`. M4.x prompts
   before any of these.
3. **A `--hard` git operation.** `git reset --hard HEAD~5`,
   `git checkout -- file.py` are destructive but easy to do by
   accident. M4.x prompts before any of these.

### What "destructive" means (the heuristic table)

A tool call is destructive in v1 iff it matches one of:

| Tool | Trigger | Rationale |
|---|---|---|
| `git_push` | always | pushes code to a remote; cannot be undone |
| `run` with `cmd` ∈ {ssh, scp, rsync, docker, kubectl, terraform, ansible, aws, gcloud, az} | always for `full_access` | "external surface" — these CLIs can affect remote state |
| `run` with `cmd` ∈ {rm, del, rmdir, rd} + a recursive / force flag | always for that flag set | bulk / force deletes are destructive |
| `run` with `rm` / `del` + glob in target | always | `rm *.txt` is a wildcard delete |
| `run` with `cmd` ∈ {aws, gcloud, az} + `subcommand` ∈ {destroy, delete, rm, drop, terminate} | always | explicit cloud teardown verbs |
| `git_reset` / `git_checkout` via the tool wrapper with `--hard` or `-f` | always | hard reset / force checkout loses work |

NOT destructive in v1 (no prompt):

- `read_file`, `write_file`, `list_dir` — workspace writes are
  sandboxed; no host-side damage.
- `git_status`, `git_diff`, `git_log`, `git_add`, `git_commit`,
  `git_clone`, `git_fetch`, `git_checkout` (without `--`).
- `run` with `python`, `pytest`, `ruff`, `make`, `pip`, `npm`,
  `node`, `jq` — build / test / lint; safe.
- All MCP tools (M3) — already tier-filtered and don't carry
  host-side power beyond the MCP server's own scope.

**Heuristic philosophy:** narrow is safer than wide. False negatives
("should have prompted but didn't") are recoverable (`git stash
pop`); false positives ("prompted but shouldn't have") are annoying
(user types `y` a lot). We err on the side of false positives.

### Confirmation flow: `y / N / a / o`

The M4 prompt format `[y/N]` was too coarse for M4.x. M4.x uses
`[y/N/a(ll)/o(ff)]`:

- `y` → approve this call, prompt again on next destructive.
- `yes` → same as `y`.
- `a` / `all` → approve this call AND flip auto-approve ON for the
  rest of the run (no more prompts for any destructive call).
- `n` / `no` → deny this call, run aborts (exit code 4).
- `o` / `off` → deny this call AND flip auto-approve OFF for the
  rest of the run (the user just toggled `a` earlier and now
  regrets it).
- Empty / EOF / timeout / anything else → deny.

Same threading-based timeout as M4 (cross-platform, no `signal.alarm`
/ `kbhit` dependencies). 30 s default, configurable via
`SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S` env var and
`--destructive-confirm-timeout` flag. Setting to 0 means "wait
forever" (require `y` even on instant-decline).

### Auto-approve toggle — three surfaces

The user wanted auto-approve "enable/disable any time". Three
surfaces:

1. **Before the run.** `--auto-approve-destructive` flag or
   `SMOLCODE_AUTO_APPROVE_DESTRUCTIVE=1` env var. Sets the
   per-run default.
2. **Mid-run (enable).** User types `a` at any prompt → flips
   auto-approve ON for the rest of the run.
3. **Mid-run (disable).** User types `o` at any prompt → flips
   auto-approve OFF for the rest of the run. This is the escape
   hatch if the user types `a` accidentally.

State storage: a single `bool` field on `SessionState`
(`auto_approve_destructive`). Mutated by the confirm callback (in
the agent loop's thread). Read by the gate in tool `forward()` (also
in the agent loop's thread). Single-threaded for smolagents'
current architecture; we wrap with `threading.Lock` anyway so
future async / multi-agent code is safe.

### Git checkpoint before full_access

Before any `full_access` run, the CLI captures the workspace's
working tree via `git stash push -u -m
"smolcode-checkpoint-<ISO8601-UTC>-<pid>"`. If the agent then does
something destructive, the user can roll back with `git stash pop`.

Skipped (not an error) when:

- `--no-checkpoint` flag is passed (user opts out).
- Workspace path doesn't exist (`reason="no-workspace"`).
- Workspace is not inside a git repo (`reason="not-a-git-repo"`).
- Working tree is clean (`reason="clean-tree"`).

Failed (still recorded in audit) when:

- `git stash` returns non-zero (`reason="stash-failed"`, stderr
  captured).
- `git status --porcelain` errors out (`reason="git-status-failed"`).

The result (created / skipped / failed + reason + stash ref +
message + file count + timestamp) is:

1. Printed to stderr so the user sees the stash ref for
   `git stash pop`.
2. Recorded in the audit log as event `checkpoint` (after the
   audit sink is installed, so it appears in JSONL).

We do **not** auto-pop on success — too magical / surprising. The
user pops manually after verifying the run was acceptable.

### Module-level session registry

Host-side tools (`git_push`, `run`) need to find the
`auto_approve_destructive` flag and the `confirm_callback` without
importing `cli.py` (which would create a circular import + make the
tools untestable in isolation). Solution: a module-level
`_session: SessionState | None` in `smolcode.session`, with
`set_session` / `get_session` / `current_session` helpers.

`current_session()` is safe-by-default: returns a fresh
`SessionState()` with `confirm_callback=None` and
`auto_approve_destructive=False` if no session is installed. A
tool that tries to do a destructive op outside a CLI session will
hit `PermissionError("destructive <tool> denied: no confirm session")`
— deny by default.

### The rstrip suffix bug

During implementation we discovered that `'rsync'.rstrip('.exe')`
returns `'rsyn'` — `str.rstrip(chars)` treats its argument as a
*set* of characters, not a suffix. The character `c` is in the set
`{.exe}`, so the trailing `c` of `rsync` got eaten. Same for
`gcloud.rstrip('.cmd')` → `'gclou'`. Fixed by a literal-suffix
check (`if cmd_lower.endswith(ext): cmd_lower = cmd_lower[:-len(ext)]`).

## Decisions

| ID | Decision |
|---|---|
| D1 | Destructive gate is per-tool inside `full_access` tier only. Other tiers use their command allowlist (no per-tool prompt). |
| D2 | Destructive predicate lives in `smolcode.destructive.is_destructive(tool_name, kwargs)`. Returns `False` on any unparseable input (safe default). |
| D3 | Heuristic table covers: `git_push` always; `run` with ssh/scp/rsync/docker/kubectl/terraform/ansible/aws/gcloud/az always; `run` with rm/del/rmdir + recursive/force flag OR glob; `run` with aws/gcloud/az + destroy/delete/rm/drop/terminate subcommand; `git_reset`/`git_checkout` with `--hard`/`-f`. |
| D4 | Prompt format: `[y/N/a(ll)/o(ff)]` (timeout 30s). `y`/`yes` → approve; `a`/`all` → approve + auto-approve ON; `n`/`no`/`o`/`off` → deny; `o`/`off` additionally flips auto-approve OFF. Anything else (empty, garbage, EOF, timeout) → deny. |
| D5 | Auto-approve toggle is exposed three ways: `--auto-approve-destructive` flag, `SMOLCODE_AUTO_APPROVE_DESTRUCTIVE=1` env var, and mid-run `a` (on) / `o` (off). |
| D6 | Session state lives in `smolcode.session.SessionState`; registered via module-level `set_session` / `current_session`. Tools reach the confirm callback without importing `cli.py`. |
| D7 | `current_session()` is safe-by-default: returns `SessionState()` with `confirm_callback=None` and `auto_approve_destructive=False`. Outside a CLI run, destructive ops are denied with `PermissionError("destructive <tool> denied: no confirm session")`. |
| D8 | Git checkpoint before every `full_access` run: `git stash push -u -m "smolcode-checkpoint-<ISO8601>-<pid>"`. Skip-if-not-repo, skip-if-clean, skip-if-`--no-checkpoint`. Stash ref + file count printed to stderr + recorded in audit log. |
| D9 | Audit event `checkpoint` carries `kind="stash"` + `status` + `reason` (if skipped/failed) + `ref` (if created) + `message` + `files` + `ts` + `stderr_tail` (truncated to 500 chars on failure). |
| D10 | Destructive gate lives in tool `forward()` inline (local `from smolcode.session import current_session` and `from smolcode.destructive import ...` imports). Imports are ABSOLUTE (not relative) so the source survives `smolagents.tools.instance_to_source`'s hoist into the remote Docker container, where the parent package IS importable on PYTHONPATH. |
| D11 | `--auto-approve-destructive` flag is per-run (not persisted). The user must pass it on each run; we don't write a config file. Rationale: prevents "I forgot I had auto-approve on" foot-guns. |
| D12 | Destructive decision (the user's prompt reply) is recorded in the audit log as event `destructive_decision` with `tool`, `summary`, `approved`, `reason`, `auto_approve_now`, `auto_approve_off` fields. |
| D13 | Destructive gate is bypassed for tiers `restricted` and `elevated` (those tiers' command allowlists are the only enforcement). The gate is `full_access`-only. |
| D14 | Exit codes (re-affirmed from 0006): destructive denial = exit code 4 (same as the M4 per-run confirmation denial). Audit emission is best-effort: an exception during `audit.record()` is swallowed and the run continues. |
| D15 | `_env_flag(name)` helper in `cli.py` reads truthy env vars (`1`, `true`, `yes`, `on`, case-insensitive). Used for `SMOLCODE_AUTO_APPROVE_DESTRUCTIVE`. |

## Files added / changed

| Path | Purpose |
|---|---|
| `smolcode/src/smolcode/destructive.py` | NEW. `is_destructive`, `destructive_reason`, pattern tables. |
| `smolcode/src/smolcode/session.py` | NEW. `SessionState`, `DestructiveDecision`, `set_session`, `get_session`, `current_session`. |
| `smolcode/src/smolcode/checkpoint.py` | NEW. `CheckpointResult`, `create_checkpoint`, `format_checkpoint_message`. |
| `smolcode/src/smolcode/confirm.py` | EXTENDED. Added `prompt_destructive`, `resolve_destructive_timeout_s`. |
| `smolcode/src/smolcode/cli.py` | EXTENDED. Added `--auto-approve-destructive`, `--no-checkpoint`, `--destructive-confirm-timeout` flags; checkpoint creation block before `factory()`; session install/clear in `finally`; `_confirm_callback` reads live `current_session()`. |
| `smolcode/src/smolcode/tools/git.py` | EXTENDED. `git_push` `forward()` has inline destructive gate. |
| `smolcode/src/smolcode/tools/shell.py` | EXTENDED. `_RunTool` `forward()` has inline destructive gate after the allowlist check. |
| `smolcode/src/smolcode/tests/test_destructive.py` | NEW. 81 tests covering the heuristic table, `destructive_reason`, bad-input safety. |
| `smolcode/src/smolcode/tests/test_checkpoint.py` | NEW. 20 tests: not-a-repo, clean tree, dirty tree, no workspace, audit emission, message + audit-field formatters. |
| `smolcode/src/smolcode/tests/test_confirm.py` | EXTENDED. +27 tests for `prompt_destructive` (`y`/`yes`/`a`/`all`/`n`/`no`/`o`/`off`/empty/garbage/EOF/exception/timeout/timeout=0) and `resolve_destructive_timeout_s`. |
| `smolcode/src/smolcode/tests/test_bind_roundtrip.py` | EXTENDED. Switched the gate's imports to absolute (`from smolcode.session import current_session`) so the `instance_to_source` hoist works in the synthetic remote exec namespace. |
| `smolcode/README.md` | TO UPDATE — mention M4.x in the feature list, add the destructive-op section. |
| `docs/roadmap.md` | TO UPDATE — M4.x sketch → SHIPPED, Q8 resolved. |

## Rejected alternatives

- **Confirm every tool call (not just destructive ones).** Rejected
  — far too noisy. The user can't review 200 prompts for `ls` /
  `cat` / `pytest`. The destructive heuristic narrows to the
  ~5–20 calls that actually matter.
- **Auto-pop the stash on success.** Rejected — too magical. If
  the run was destructive, the user wants to verify the result
  before popping. Manual `git stash pop` is one keystroke.
- **Snapshot via `git worktree` instead of `git stash`.**
  Considered — `worktree add` would give the agent a separate copy
  to mutate, leaving the main tree untouched. Rejected for v1:
  ~10x more setup code, the agent doesn't know about the worktree
  boundary without invasive changes, and the user can't trivially
  see what happened. v1.1 may revisit.
- **Snapshot via filesystem copy (cp -r).** Rejected — slow for
  large repos, uses 2x disk, and `cp -r` doesn't capture
  uncommitted changes inside `.git/`.
- **Block destructive ops entirely in v1.** Rejected — defeats the
  point of `full_access`. The user opted in.
- **Use `git diff` + `git apply -R` for rollback.** Rejected —
  doesn't capture untracked files, and `git apply -R` is not
  guaranteed to succeed if the agent committed over them.
- **Track per-tool auto-approve (different toggle per tool).**
  Rejected for v1 — too much surface area. One global
  auto-approve-destruct flag covers 95% of the use case. v1.1 may
  add per-tool scopes if users ask.

## Acceptance gates

| Gate | Status |
|---|---|
| `ruff check src` green | PASS |
| `ruff format --check src` green | PASS |
| `pytest src/` green | PASS (326 tests: 198 prior + 81 destructive + 20 checkpoint + 27 new confirm = 326) |
| `smolcode --smoke --tier full_access --confirm-timeout 1 --no-checkpoint "echo hi"` (denied) | TO RUN |
| `smolcode --smoke --tier full_access --auto-approve-destructive --no-checkpoint "echo hi"` (runs) | TO RUN |
| `smolcode --smoke --tier restricted --destructive-confirm-timeout 1 "echo hi"` (no prompt) | TO RUN (gate is full_access-only) |
| Live: dirty repo + `full_access` + interactive `y` to one git push → audit log records `destructive_decision` | TO RUN |
| Live: dirty repo + `full_access` + interactive `a` to one prompt → subsequent `git push` does NOT prompt | TO RUN |
| Live: dirty repo + `full_access` + interactive `o` mid-run → next prompt appears again | TO RUN |
| `destructive.py` heuristic coverage on every entry of the pattern table | PASS (`test_destructive.py`) |
| `checkpoint.py` skip paths + dirty-tree path covered | PASS (`test_checkpoint.py`) |
| `prompt_destructive` accepts `y`/`yes`/`a`/`all`/`n`/`no`/`o`/`off`/empty/garbage/EOF/exception/timeout | PASS (`test_confirm.py`) |

## Open questions deferred

1. **`RedactSecretsFilter` for the audit log.** The audit log
   currently records the raw task description. If a user pastes a
   `Bearer ...` token in the task, the token lands in the JSONL.
   The redaction filter (~30 lines) is small enough to ship; will
   land in M4.x polish alongside this decision. Tracked in
   `docs/security.md` §10.
2. **Per-tool auto-approve scopes.** v1 ships a single global
   "auto-approve all destructive ops" flag. A user may want "auto-
   approve `git_push` only, prompt for `aws destroy`". Deferred
   to v1.1.
3. **`git worktree` snapshot instead of `git stash`.** Considered
   in rejected alternatives; revisit if users complain that
   `git stash pop` is awkward.
4. **Checkpoint for elevated tier.** Currently checkpoint is
   `full_access`-only. Could be useful for elevated too (the
   elevated tier can install packages, push branches). Deferred
   to v1.1; for v1 the cost-benefit isn't there (elevated rarely
   touches the user's tree).
5. **M7 polish: docs/operations.md.** Documents where the audit
   log lives, how to grep it, how to prune it (logrotate snippet +
   Python helper), and how to interpret destructive_decision
   events. Deferred from M4.
