# Audit Log Retention

**Status:** active
**Added:** v1.5 (M14, decision 0018)
**Replaces:** the gap noted in `scripts/rotate_audit_log.py:18` (which
referenced this doc but the doc did not exist).

This document describes how the smolcode audit log is grown, verified,
and rotated. It is the operator-facing reference; the cryptographic
construction is in `docs/security.md` section 9 and the implementation
is in `smolcode/src/smolcode/audit.py`.

---

## 1. Where the log lives

By default:

    <cwd>/logs/audit.jsonl

Overridable via:

- `SMOLCODE_AUDIT_LOG` env var - absolute path
- `smolcode audit <verb> --audit-log PATH` - per-invocation override

Only the `full_access` tier (and the elevated tier when explicitly
wired) write to this log. `restricted` runs are excluded by default
to avoid unbounded volume; they are still captured in the INFO log
when `SMOLCODE_LOG_LEVEL=DEBUG` is set.

## 2. How the log is written

`AuditSink` (`smolcode/src/smolcode/audit.py`) opens the file in append
mode and refuses any other mode (`AuditError` raised for write, exclusive-create,
read, read-plus modes). Every entry is one JSON object terminated with a newline.

Starting with M13 (decision 0016), each entry also carries a SHA-256
hash chain:

    {
      "ts": "2026-08-23T14:30:01Z",
      "event": "start",
      "tier": "full_access",
      "task": "deploy commit abc123 to staging",
      "prev_hash": "0000...64-zeros",          // genesis for line 1
      "entry_hash": "<sha256(prev_hash + canonical_json(payload))>"
    }

`prev_hash` of line N equals `entry_hash` of line N-1. Modifying
any prior line invalidates the hash of that line AND every line that
follows - silent tampering is detectable.

The chain is **on by default**. Disable only for debugging via
`SMOLCODE_AUDIT_HASH_CHAIN=1` (decision 0016 section 6 risk register).

## 3. How to read the log

Four entry points (all apply `RedactSecretsFilter` so leaked keys
cannot escape):

| Tool | Use when |
|---|---|
| `smolcode audit ls [-n N]` | Quick terminal scan of the last N entries |
| `smolcode audit grep <pattern>` | Case-insensitive substring search |
| `smolcode audit grep --patterns <re1> <re2> ...` | Regex search (M14.4) |
| `smolcode audit verify` | Replay + verify the chain; exit 0 = clean |
| `GET /api/audit?limit=&grep=&verify=1` | SPA view (`web/api.py:get_audit`) |

The SPA viewer (Inspector pane -> "Recent audit") auto-pads every 5
seconds and supports an inline "verify" toggle.

## 4. When to rotate

The chain only protects a log that is still in use. Once a log
becomes large enough that the next write is slow, or once it crosses
your operator-set age threshold, rotate it. **Do not** simply delete
or `truncate` it: the hash chain loses its anchor and downstream
verifiers report the file as unverifiable.

Recommended trigger:

    size > 50 MB  OR  age > 30 days  OR  monthly (whichever first)

These thresholds are operator defaults; tune to your disk budget
and throughput. The tool does not enforce a limit.

## 5. How to rotate

The v1.5 CLI verb (M14.3) supersedes `scripts/rotate_audit_log.py`:

    # Preview (no files touched)
    smolcode audit rotate --dry-run --audit-log logs/audit.jsonl

    # Rotate now, keep compressed archives for 90 days
    smolcode audit rotate --keep-days 90 --audit-log logs/audit.jsonl

What it does (per call):

1. Run `verify_chain()` on the live log. **If the chain is broken, the
   call refuses to rotate and exits with code 4.** This is the
   critical guarantee: a tampered log is never silently gzipped and
   held forever.
2. Rename `audit.jsonl` -> `audit-<YYYYMMDD>.jsonl` (collision-safe
   via `-1`, `-2`, ... suffix when the stamp is already in use).
3. gzip the rotated file to `audit-<YYYYMMDD>.jsonl.gz`.
4. Sweep `audit-*.jsonl.gz` files whose mtime is older than
   `--keep-days N` (default 365).

Exit codes (full table in `smolcode/src/smolcode/cli.py:_audit_main`):

| code | meaning |
|---|---|
| 0 | rotated (or would-rotate in `--dry-run`) |
| 1 | (unused by rotate; reserved) |
| 2 | usage error (`--keep-days` not an int, etc.) |
| 3 | log not found / empty (no-op) |
| 4 | **chain broken - refuse to rotate** |

The next `AuditSink` write after a successful rotation creates a new
genesis line at `audit.jsonl` and the chain resumes from there.

## 6. The standalone script (deprecated)

`scripts/rotate_audit_log.py` predates M14 and still works for cron
jobs that pre-date the v1.5 CLI. It does NOT verify the chain
before compressing, so **prefer `smolcode audit rotate`** for any new
deployment. The script will be removed in v1.6 (decision 0018 section 6
R-M14-D).

## 7. Cron example

    # Daily 02:13 - rotate and keep 90 days of archives
    13 2 * * *  cd /home/smolcode && smolcode audit rotate --keep-days 90 \
      >> /var/log/smolcode-rotate.log 2>&1

    # Weekly Sun 03:00 - verify the chain; alert on non-zero exit
    0 3 * * 0   cd /home/smolcode && smolcode audit verify \
      || /usr/local/bin/smolcode-audit-alert.sh

## 8. Backup and offload

The rotated `.jsonl.gz` files are the source of truth for prior
activity. Offload them to your backup target (S3, B2, tape) before
the `--keep-days` sweep deletes them locally. Decompressing returns
the original JSONL byte-for-byte; `verify_chain` still works on the
decompressed contents because the chain anchor (`entry_hash`) is
inside each line.

## 9. See also

- `docs/security.md` section 9 - Audit log integrity model
- `docs/decisions/0016-m13-audit-integrity-redact-expansion.md` -
  M13 hash chain construction
- `docs/decisions/0018-m14-audit-operational-hardening.md` - M14
  rotate + reader + SPA panel
- `smolcode/src/smolcode/audit.py` - `AuditSink`, `verify_chain`,
  `RotateResult`, `rotate_audit_log`
- `smolcode/src/smolcode/audit_reader.py` - `read_audit_entries`,
  `audit_chain_status` (SPA + CLI backend)
- `smolcode/src/smolcode/cli.py` - `_audit_main` (all verbs)
