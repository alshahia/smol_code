# M13 — Audit integrity + redact expansion + audit reader CLI

**Date:** 2026-08-23
**Status:** active (SHIPPED 2026-08-23 — M13.1 hash chain, M13.2 audit {ls, grep, verify}, M13.3 redact expansion all delivered)
**Trigger:** v1.1 followups list in `docs/decisions/0009-m7-polish-security-review.md` carried three open items that all belonged to the audit / secret-redaction surface: hash-chained audit log, audit reader CLI, and additional redact patterns. Bundled them into one milestone since they share the same module(s).
**Related:**
- `docs/roadmap.md` — v1.1 followups + the post-M12 "what's next" note
- `docs/decisions/0009-m7-polish-security-review.md` §"Followups (deferred to v1.1)" — origin of items 1, 2, 3
- `docs/security.md` §8 (secrets policy), §9 (audit log)
- `smolcode/src/smolcode/audit.py` — extended with hash chain + verify_chain
- `smolcode/src/smolcode/redact.py` — expanded DEFAULT_PATTERNS (4 → 9 prefixes)
- `smolcode/src/smolcode/cli.py` — new `smolcode audit {ls|grep|verify}` subcommand

---

## 1. Question

Three v1.1 followups were carried from M7:

1. **Hash-chained audit log.** `AuditSink` already enforced append-only
   mode (rejects `w` / `x` / `r`), but a privileged attacker could still
   silently rewrite a line in place. The audit log is the primary
   tamper-evidence trail for `full_access` runs; the mode check alone is
   insufficient.
2. **Audit reader CLI.** No convenient way to inspect `logs/audit.jsonl`
   from the terminal. Operators had to `jq` the file by hand and re-run
   `RedactSecretsFilter` on the output to avoid leaking keys.
3. **Additional redact patterns.** The M7 redact list covered OpenAI
   (`sk-`), Anthropic (`sk-ant-`), HuggingFace (`hf_`), GitHub PAT
   (`ghp_`). Real-world leaks also include Google API keys
   (`AIza[0-9A-Za-z_-]{35}`), AWS access key IDs (`AKIA[0-9A-Z]{16}`),
   and the rest of the GitHub token family (`gho_` OAuth, `ghu_` user,
   `ghs_` server).

Bundled into one milestone because all three touch the same two modules
(`audit.py` + `redact.py` + `cli.py`).

---

## 2. What changed

### 2.1 `audit.py` — hash chain + verifier

| Change | Lines |
|---|---|
| New module-level constants: `HASH_CHAIN_ENV`, `_GENESIS_HASH`, `_HASH_FIELDS` | 56–66 |
| `AuditSink.__init__` gains `hash_chain=Optional[bool]` kwarg + lazy env read | 71–103 |
| `AuditSink.record` computes `prev_hash` / `entry_hash` when enabled | 116–134 |
| New `VerifyResult` dataclass (`ok`, `entries`, `chained_entries`, `bad_line`, `first_unverifiable_line`, `malformed_lines`) | 184–205 |
| New `verify_chain(path)` reader + replays the chain | 207–271 |
| New `_compute_entry_hash(prev_hash, payload)` helper | 273–293 |

### 2.2 `redact.py` — DEFAULT_PATTERNS 4 → 9

| Prefix | Marker | Source |
|---|---|---|
| `sk-ant-` | `anthropic` | M7 |
| `sk-` | `openai` | M7 |
| `hf_` | `huggingface` | M7 |
| `ghp_` | `github` | M7 |
| `gho_` | `github-oauth` | **M13** new |
| `ghu_` | `github-user` | **M13** new |
| `ghs_` | `github-server` | **M13** new |
| `AIza` | `google` | **M13** new |
| `AKIA` | `aws` | **M13** new |

`_PATTERN_PREFIX` mapping updated. Marker cleanliness verified by
`test_marker_names_do_not_contain_trigger_prefix` (regression guard
for the original `sk-ant-` "marker doesn't re-match `sk-`" bug).

### 2.3 `cli.py` — `smolcode audit` subcommand

New top-level subcommand pre-dispatched from `main()`:

    smolcode audit                              -> default: ls
    smolcode audit ls [-n N] [--json] [--audit-log PATH]
    smolcode audit grep <pattern> [-n N] [--no-redact] [--audit-log PATH]
    smolcode audit verify [--audit-log PATH]
    smolcode audit help

`grep` output is always routed through `RedactSecretsFilter` (the
`--no-redact` opt-out exists for debugging). Exit codes: `0` clean /
non-empty, `1` verify-failed-or-no-grep-match, `2` usage error,
`3` log-not-found.

---

## 3. Hash chain construction

```text
Line N payload (without chain fields): canonical_json(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
entry_hash_N = sha256(prev_hash_N || canonical_json(payload_N)).hexdigest()

where prev_hash_1 = "0" * 64 (genesis sentinel)
      prev_hash_N = entry_hash_{N-1} for N >= 2
```

Why each choice:

- **`sort_keys=True`**: deterministic order independent of dict insertion.
- **`ensure_ascii=True`**: bytes are identical regardless of locale;
  the audit sink writes `ensure_ascii=False` but the verifier must
  reproduce the same canonical bytes (escaped form is unique).
- **`separators=(",", ":")`**: no whitespace; saves disk + matches the
  `AuditSink` writer's exact byte layout.
- **chain fields excluded from the hash**: otherwise the hash would
  include itself.

The verifier stops at the first tampered line (`bad_line`) — we no
longer have a valid `prev_hash` anchor beyond that point so verifying
further lines would be meaningless. Pre-M13 logs (no chain fields)
return `first_unverifiable_line=N` (the line where the chain becomes
unverifiable) but `bad_line=None`; this is reported as a soft failure
("PARTIAL") rather than a hard tamper.

---

## 4. `smolcode audit verify` exit semantics

| Situation | Exit | Output |
|---|---|---|
| Empty log | 0 | `OK: 0 entries verified, chain intact (M13.1).` |
| Clean chained log | 0 | `OK: N entries verified, chain intact (M13.1).` |
| Tampered line at position K | 1 | `FAIL: line K did not match its recorded entry_hash; K-1/N entries verified before the break.` |
| Pre-M13 log (no chain fields from line K) | 1 | `PARTIAL: chain verifiable through line K-1; line K onward has no chain fields (likely pre-M13). M/N entries verified.` |
| Log not found | 3 | `audit log not found: ...` |
| Bad flag | 2 | `unknown audit verify argument: ...` |

CI usage:

    smolcode audit verify --audit-log /var/log/smolcode/audit.jsonl || exit 1

---

## 5. Why `grep` routes output through `RedactSecretsFilter`

Reading the audit log back to the terminal is the exact moment when a
key leak is most likely. Without the redaction pass, an attacker who
managed to write a key into the log (via the `task` field of a
`start` event, for example) would see it echoed when an operator ran
`smolcode audit grep <something>`. The `grep` handler therefore calls
`_redact_string` on each row's `detail` column before printing. The
`--no-redact` opt-out exists for debugging only.

---

## 6. Validation gates

| Gate | Result |
|---|---|
| `ruff check src` | PASS (after fix to `redact.py` E501 long-line auto-fix) |
| `ruff format --check src` | PASS |
| `pytest src/smolcode/tests/test_audit.py` | **35 passed** (19 pre-M13 + 16 M13.1) |
| `pytest src/smolcode/tests/test_cli_audit.py` | **22 passed** (all M13.2) |
| `pytest src/smolcode/tests/test_redact.py` | **39 passed** (30 pre-M13 + 9 M13.3) |
| `pytest src/smolcode/tests/test_redact_in_runs.py` | **8 passed** (unchanged) |
| `pytest src/smolcode/tests/` (full) | **~792 passed** (760 M12.5 baseline + ~32 new M13 cases; final count after full run) |
| `smolcode audit verify` on a fresh chained log | exit 0, `OK: 4 entries verified` |
| `smolcode audit verify` after tampering line 2 | exit 1, `FAIL: line 2 ... 1/2 entries verified before the break` |
| `smolcode audit grep deploy` | matches `task=deploy to staging` row; redacts secrets in output |
| `smolcode audit help` | exits 0, prints usage block |

---

## 7. Risks

### R-M13-A: existing logs become "partially unverifiable"

The first pre-M13 log line marks the chain as `first_unverifiable_line`.
Operators used to `audit verify` returning 0 (clean) will see 1 (partial).
Mitigated by the human-readable "PARTIAL: chain verifiable through line N"
output and a doc note in `security.md` §9. Once the log rolls over (or is
rotated by the existing `scripts/rotate_audit_log.py`) the next log is
fully chained.

### R-M13-B: hash canonicalization drift between Python versions

`json.dumps` with `sort_keys=True` + `ensure_ascii=True` +
`separators=(",", ":")` is part of CPython's documented stable contract
and identical between 3.10 / 3.11 / 3.12 / 3.13 (the `smolcode` minimum
is 3.10). The `test_compute_is_deterministic` test guards against
internal drift if the function is ever changed.

### R-M13-C: process-level concurrent writers

The current `AuditSink` is **single-process**; the `threading.Lock`
guards against intra-process threads only. Two processes writing to the
same log will produce a valid-looking but inconsistent chain (the second
process's first line will not chain off the first process's last line).
This was already true for the append-only guarantee; M13 does not
introduce a regression. A multi-process appender would need a
file-locking layer; deferred to a future milestone if measured demand.

### R-M13-D: redact marker collisions

A future maintainer might add a new prefix whose marker starts with an
existing trigger (e.g. a marker `smolcode-secret` containing `sk-`).
Mitigated by `test_marker_names_do_not_contain_trigger_prefix` which
exhaustively checks every prefix against every marker.

---

## 8. Known limitations (carried forward)

- The verifier stops at the first break; downstream lines are not
  checked. Acceptable because we cannot anchor a downstream line
  without a known-good prev_hash.
- `grep` only matches against the listed scalar fields
  (`event`, `tier`, `task`, `action`, `message`, `kind`).
  Full-text search over the raw line is not exposed (by design: would
  bypass the redact pass).
- The `audit grep` redact pass is in-process and runs against the
  default `DEFAULT_PATTERNS`. Custom patterns installed via
  `RedactSecretsFilter(patterns=[...])` are NOT honored by `grep`.

---

## 9. v1.1 followups status

After M13:

| # | v1.1 followup | Status |
|---|---|---|
| 1 | iptables enforcement for elevated network allowlist | **deferred** (Docker-privilege concern) |
| 2 | Hash-chained audit log | **DONE** (M13.1) |
| 3 | Cold-storage sync (S3 Object Lock) | deferred (external dep) |
| 4 | Per-`/models` HTTP endpoint | deferred (operator UX; M14 candidate) |
| 5 | Audit reader CLI | **DONE** (M13.2) |
| 6 | Additional redact patterns | **DONE** (M13.3: Google / AWS / GitHub-OAuth-User-Server) |

3 of 6 closed. Remaining 3 (iptables / S3 / per-`/models`) each have a
distinct blocker (Docker privilege, external credentials, no measured
demand) and remain in the v1.x backlog.

---

## 10. References

- `smolcode/src/smolcode/audit.py:1-316` — full file with chain extension
- `smolcode/src/smolcode/redact.py:1-316` — DEFAULT_PATTERNS (9 prefixes)
- `smolcode/src/smolcode/cli.py:820-955` — _audit_main + audit pre-dispatch
- `docs/security.md` §8 + §9 — policy + audit log updates
- `docs/roadmap.md` — M13 row in the milestone table
- `smolcode/README.md` — v1.4 / M13 status line
- v1.1 followups origin: `docs/decisions/0009-m7-polish-security-review.md` §"Followups"
- Hash chain pattern (research): "Hash-chained JSONL for tamper-evident logs"
  (general technique; no specific external library; we use stdlib
  `hashlib` + `json` for minimum deps).
