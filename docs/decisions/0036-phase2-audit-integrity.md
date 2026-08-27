# ADR 0036 — Phase 2: audit & evidence integrity (H5 + H6 + related Ms)

**Date:** 2026-08-26
**Status:** active
**Supersedes:** none (extends decisions 0006/0016/0018)
**Related:** `docs/reviews/2026-08-26-full-app-review/REMEDIATION-PLAN.md` Phase 2; incident note "tree reverted during review session"; Phase 1 ADR 0035

## Context

The 2026-08-26 full review found the evidence layer mostly present but
wrongly wired:

- **H5** - the web app factory hardcoded `audit=None`, so web-started
  runs produced ZERO audit records while `docs/security.md` section 9
  claimed all four read paths showed a live trail.
- **H6** - every `AuditSink` restarted its hash chain at the genesis
  sentinel. The CLI deliberately appends every run to ONE shared
  `logs/audit.jsonl`, so any log with more than one run failed
  `verify_chain` at the seam - legitimate evidence read as tampering.
- **M** - `AuditSink.record()` computed `prev_hash`/`entry_hash` OUTSIDE
  the sink lock; two threads could anchor on the same prev_hash and
  interleave writes, corrupting the chain.
- **M** - `smolcode audit ls --json` dumped raw JSONL with NO redaction
  while the table/grep paths routed through `RedactSecretsFilter`.
- **M** - `Run.snapshot(path=None)` created `smolcode-snap-*` NamedTemp-
  oraryFiles that nothing ever deleted: one full-transcript JSON leaked
  to the system temp dir per web run.
- **M** - docs/security.md claimed redaction of generic `KEY=` shapes
  and that restricted/elevated runs were not audited; both false.

## Decision

1. **Chain continuation (H6).** `AuditSink.__init__` seeds `_prev_hash`
   from the LAST complete line of the existing file (bounded 64 KB tail
   read): tail chained AND verifying -> continue; tail chained but
   broken -> raise `AuditError` (fail-closed; extending a tampered log
   would launder evidence); tail unchained/malformed/absent -> genesis
   anchor as before. Multi-PROCESS concurrent appends remain unsupported
   (documented limitation; single-writer-per-log assumption unchanged).
2. **Hash under lock (M).** `record()` computes and advances the chain
   entirely inside `self._lock`. Serialization cost is negligible next
   to the file write it guards.
3. **Web sink is real (H5).** `create_app(*, no_audit=False)` builds one
   `AuditSink` exactly like cli.py resolves the path (`SMOLCODE_AUDIT_LOG`
   override, else `<cwd>/logs/audit.jsonl`); construction failure refuses
   the boot. The sink is shared by UploadsStore, GET /api/audit, AND
   `RunManager(audit_sink=...)` - runs started without an explicit
   `audit=` argument (retry, rerun, queue drain) inherit the manager
   default instead of silently skipping the trail. Explicit per-call
   sinks still win. `smolcode web --no-audit` keeps the opt-out.
4. **`audit ls --json` redacts (M).** JSON entries pass through the same
   `DEFAULT_PATTERNS` redactor as table/grep output; `--no-redact`
   suppresses (flag was already parsed for every verb).
5. **Snapshot temp cleanup (M).** `Run.cleanup_temp_snapshot()` deletes
   only files matching the `smolcode-snap-*` prefix (caller-supplied
   paths are never touched); called from `run_in_thread` after the
   terminal event publish. `snapshot()` also removes its `.tmp` sidecar
   on write failure. Resume-before-terminal still reads the file.
6. **Docs reconciled over new patterns (M).** We AMENDED security.md
   rather than implementing a generic `KEY=` redaction rule: prefix
   families are precise and testable; a broad `KEY=` regex would
   over-redact benign text for marginal safety. Section 9 now states
   the real audit scope (all tiers by default), the continuation and
   tampered-tail-refusal semantics, and that `ls --json` is redacted.

## Consequences

- Multi-run logs verify end-to-end for the first time; rotation of such
  logs now succeeds (`audit rotate` pre-verifies).
- A corrupted/tampered shared log BLOCKS new CLI runs at sink construction
  with an actionable message - operators rotate or restore. Accepted:
  silent continuation would legitimize tampered history.
- Web boots now fail closed when the audit log cannot be opened (mirrors
  the C2 image-gate posture from ADR 0035).
- The legacy module-bottom `RunManager.__init__` re-bind (runs.py bottom)
  was extended in place for `audit_sink=`; folding it back into the class
  remains Phase 5 scope per the remediation plan.
- Test-env isolation: conftest now defaults `SMOLCODE_AUDIT_LOG` into
  `tmp_path` so factory-built sinks never touch the repo tree.

## Test map (red -> green, suite `test_audit_integrity_phase2.py`)

| Finding | Tests | Pre-fix result | Post-fix |
|---|---|---|---|
| H6 | two/three-sink chain verify; tampered middle; tampered-tail refusal; unchained fallback | 14 failed / 3 passed whole-suite RED run (two-sink: bad_line=2 genesis seam) | 17/17 green |
| M race | 8-thread x 40-record concurrency chain verify | failed (chain break mid-log) | green |
| M ls --json | json redacts / --no-redact raw / table still redacts | raw secret printed | green |
| H5 | create_app attaches real sink; no_audit opt-out; manager-default fallback; explicit wins; web-run start/end + verify=true integration | sink None / note branch / zero records | green |
| M snapshot | temp deleted on cleanup; explicit path preserved; no-op without snapshot | AttributeError | green |

## References

- `smolcode/src/smolcode/audit.py` (_seed_prev_hash_from_tail, record lock scope)
- `smolcode/src/smolcode/web/server.py` (factory sink + no_audit)
- `smolcode/src/smolcode/web/runs.py` (manager default sink, cleanup_temp_snapshot)
- `smolcode/src/smolcode/web/agent_runner.py` (terminal cleanup call)
- `smolcode/src/smolcode/_cli_subcommands.py` (ls --json redaction, web --no-audit)
- `docs/security.md` sections 8-9 (reconciled claims)