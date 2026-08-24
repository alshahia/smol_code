"""Audit sink for full_access + elevated runs (M4, decision 0006).

Append-only JSONL log of every run started under smolcode. Records
start, end, step, and error events. The CLI wires one AuditSink per
run and emits a small number of well-typed events.

Why append-only?
- Per docs/security.md section 8 the audit log must be tamper-evident
  at the file-handle level: opening in mode "w" or "x" destroys
  prior evidence. AuditSink.__init__ refuses any mode other than "a".
- Per docs/roadmap.md section 6 (M4) the test suite verifies the
  rejection.

Schema (one JSON object per line):
    {"ts": "<iso8601-utc>", "event": "start", "tier": ..., "task": ..., ...}
    {"ts": "<iso8601-utc>", "event": "step",  "step": <int>, "action": "<str>"}
    {"ts": "<iso8601-utc>", "event": "end",   "exit_code": <int>, "duration_s": <float>}
    {"ts": "<iso8601-utc>", "event": "error", "kind": "<ExceptionType>", "message": "<str>"}

M13 added a hash-chain extension for tamper evidence:

    {"ts": "...", "event": "start", ..., "prev_hash": "<64-hex>", "entry_hash": "<64-hex>"}

Each line carries ```prev_hash``` (the previous line's ```entry_hash```,
or 64 zero hex chars for the genesis line) and ```entry_hash```
(```sha256(prev_hash + canonical_json(payload_without_hash_fields))```).
```verify_chain(path)``` replays the chain and returns a ```VerifyResult```
with ```ok```, ```bad_line``` (1-based; the first tampered line), and
```first_unverifiable_line``` (1-based; the first line without chain
fields, when reading a partially-chained log written by an older
build).

Backwards-compatibility: logs written before M13 are still readable
but reported as "unverifiable from line N" by ```verify_chain```. The
AuditSink opt-out ```SMOLCODE_AUDIT_HASH_CHAIN=0``` skips chain
computation on the write side (not recommended; default is ON).

Public surface:
    AuditSink(path, hash_chain=True)   - constructor, opens append-only.
    .record(event, **fields)           - write one JSONL line.
    .start(tier, task, ...)            - convenience for the "start" event.
    .step(n, action)                   - convenience for the "step" event.
    .end(exit_code, duration_s)        - convenience for the "end" event.
    .error(exc)                        - convenience for the "error" event.
    .close()                           - flush + close the file handle.
    default_audit_path()               - <cwd>/logs/audit.jsonl (default).
    verify_chain(path)                 - replay + verify the hash chain.
    VerifyResult                       - dataclass returned by verify_chain.
    HASH_CHAIN_ENV                     - env var name for the opt-out toggle.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_ALLOWED_MODES = ("a", "a+")  # text modes only; JSONL is utf-8 text

# Env var to disable hash-chain computation on write. Default is ON.
# Recommended only for debugging - disabling the chain makes the log
# silently mutable. Documented in security.md section 9.
HASH_CHAIN_ENV = "SMOLCODE_AUDIT_HASH_CHAIN"

# Genesis prev_hash: 64 zero hex chars. The "first line" sentinel so
# the chain has a deterministic anchor independent of any other state.
_GENESIS_HASH = "0" * 64

# Field names we add to each record for the chain. The chain fields
# MUST NOT appear in the canonical payload that we hash - otherwise
# the hash would include itself.
_HASH_FIELDS = ("prev_hash", "entry_hash")


class AuditError(RuntimeError):
    """Raised when an AuditSink cannot be constructed or written to."""


class AuditSink:
    """Append-only JSONL audit log writer. Thread-safe.

    Args:
        path: target log path. Parent dirs are created.
        mode: must be an append mode. "w", "x", "r", "r+" are rejected.
        hash_chain: optional override for the chain toggle. ```None```
            (default) reads ```SMOLCODE_AUDIT_HASH_CHAIN```; truthy values
            (```"1"```, ```"true"```, ```"yes"```, ```"on"```, case-insensitive)
            disable the chain. The chain is ON when the env var is unset
            or set to a non-truthy value.
        _open: open() injection point for tests (defaults to builtin open).
    """

    def __init__(
        self,
        path,
        *,
        mode: str = "a",
        hash_chain: Optional[bool] = None,
        _open=open,
    ):
        if mode not in _ALLOWED_MODES:
            raise AuditError(
                "AuditSink requires append mode (one of "
                + repr(_ALLOWED_MODES)
                + "), got "
                + repr(mode)
                + ". Refusing to truncate the audit log."
            )
        p = Path(path)
        # Resolve to absolute so path comparisons in tests are stable.
        self.path = p.resolve()
        self.mode = mode
        if p.parent and not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        # Use line-buffered text mode for predictable flushing on close.
        self._fp = _open(str(p), mode, encoding="utf-8", buffering=1)
        self._lock = threading.Lock()
        self._closed = False
        self._pid = os.getpid()

        # Hash chain state. Lazy resolve: explicit kwarg wins over env.
        if hash_chain is None:
            raw = os.environ.get(HASH_CHAIN_ENV, "").strip().lower()
            self.hash_chain = raw not in ("1", "true", "yes", "on")
        else:
            self.hash_chain = bool(hash_chain)
        self._prev_hash = _GENESIS_HASH

    def record(self, event, **fields):
        """Write one JSONL line with the given event name and fields.

        When ```hash_chain``` is enabled, ```prev_hash``` and ```entry_hash```
        are computed and appended to the line. The hash is computed
        over a canonical JSON serialization of the payload WITHOUT
        the hash fields, then concatenated with the previous line's
        ```entry_hash``` (or the genesis sentinel for line 1).
        """
        if self._closed:
            raise AuditError("AuditSink is closed")
        payload = {"ts": _now_iso(), "event": event, "pid": self._pid}
        payload.update(fields)
        if self.hash_chain:
            prev_hash = self._prev_hash
            entry_hash = _compute_entry_hash(prev_hash, payload)
            payload["prev_hash"] = prev_hash
            payload["entry_hash"] = entry_hash
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            try:
                self._fp.write(line + "\n")
            except (OSError, ValueError) as e:
                raise AuditError("failed to write audit entry: " + repr(e)) from e
            if self.hash_chain:
                # Advance the chain AFTER the write so a failed write
                # does not poison the next line's prev_hash.
                self._prev_hash = payload["entry_hash"]

    # Convenience methods -----------------------------------------------------

    def start(self, *, tier, task, model, provider, executor, workspace):
        """Emit the canonical "start" event for one run."""
        self.record(
            "start",
            tier=tier,
            task=task,
            model=model,
            provider=provider,
            executor=executor,
            workspace=str(workspace),
        )

    def step(self, n, action):
        """Emit a "step" event for one agent reasoning step."""
        self.record("step", step=int(n), action=str(action))

    def end(self, *, exit_code, duration_s):
        """Emit the canonical "end" event with run outcome + duration."""
        self.record(
            "end",
            exit_code=int(exit_code),
            duration_s=float(duration_s),
        )

    def error(self, exc):
        """Emit an "error" event from a caught exception."""
        self.record(
            "error",
            kind=type(exc).__name__,
            message=str(exc),
        )

    # Lifecycle ---------------------------------------------------------------

    def close(self):
        """Flush + close the file handle. Safe to call multiple times."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._fp.flush()
            except Exception:
                pass
            try:
                self._fp.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# --- Hash chain verification (M13) -----------------------------------------


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of ```verify_chain(path)```.

    Attributes:
        ok: True iff every chained line's ```entry_hash``` matches its
            payload + ```prev_hash```. ```False``` when a tampered line is
            found.
        entries: total number of JSONL lines read (including
            unparseable ones - those are reported as ```bad_line```).
        chained_entries: count of lines that carried ```prev_hash``` +
            ```entry_hash``` fields AND verified. A subset of ```entries```.
        bad_line: 1-based line number of the first tampered line, or
            ```None``` when ```ok``` is True.
        first_unverifiable_line: 1-based line number of the first line
            without chain fields. ```None``` when every line was chained
            (i.e. the log was written entirely by an M13+ build).
            NOT a failure: pre-M13 logs are still readable.
        malformed_lines: 1-based line numbers of lines that failed to
            parse as JSON. Each is also reported as ```bad_line```.
    """

    ok: bool
    entries: int
    chained_entries: int
    bad_line: Optional[int] = None
    first_unverifiable_line: Optional[int] = None
    malformed_lines: tuple = ()


def verify_chain(path) -> VerifyResult:
    """Replay and verify the hash chain of a JSONL audit log.

    The log is opened read-only. Each line is parsed as JSON; if the
    line carries ```prev_hash``` + ```entry_hash```, the hash is recomputed
    and compared. If the chain breaks (either because a field is
    missing or because the recomputed hash does not match), the
    failure is recorded and the function returns.

    Lines that pre-date M13 (no chain fields) are NOT considered
    failures - the log simply becomes unverifiable from that point
    onward. The first such line number is exposed as
    ```first_unverifiable_line```.

    Args:
        path: file path or path-like. The file must exist.

    Returns:
        VerifyResult.

    Raises:
        FileNotFoundError: when the path does not exist.
        AuditError: when the path resolves to a directory or is
            otherwise unreadable.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError("audit log not found: " + str(p))
    if p.is_dir():
        raise AuditError("audit path is a directory: " + str(p))

    chained_entries = 0
    bad_line: Optional[int] = None
    first_unverifiable: Optional[int] = None
    malformed: list = []
    entries = 0
    prev_hash = _GENESIS_HASH

    with p.open("r", encoding="utf-8", errors="replace") as fp:
        for lineno_raw, raw in enumerate(fp, start=1):
            line = raw.rstrip("\r\n")
            if not line:
                continue
            entries += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                malformed.append(lineno_raw)
                if bad_line is None:
                    bad_line = lineno_raw
                continue
            if not isinstance(obj, dict):
                malformed.append(lineno_raw)
                if bad_line is None:
                    bad_line = lineno_raw
                continue
            prev = obj.get("prev_hash")
            entry = obj.get("entry_hash")
            if not isinstance(prev, str) or not isinstance(entry, str):
                # Pre-M13 line (or non-chained writer).
                if first_unverifiable is None:
                    first_unverifiable = lineno_raw
                # Once the chain is broken we cannot continue verifying
                # downstream lines because we no longer have a valid
                # prev_hash anchor. Stop here.
                break
            expected = _compute_entry_hash(prev, obj)
            if prev != prev_hash or entry != expected:
                if bad_line is None:
                    bad_line = lineno_raw
                break
            chained_entries += 1
            prev_hash = entry

    ok = bad_line is None and first_unverifiable is None
    return VerifyResult(
        ok=ok,
        entries=entries,
        chained_entries=chained_entries,
        bad_line=bad_line,
        first_unverifiable_line=first_unverifiable,
        malformed_lines=tuple(malformed),
    )


@dataclass(frozen=True)
class RotateResult:
    """Outcome of rotate_audit_log() (M14.3, decision 0018)."""

    rotated_from: Optional[str] = None
    rotated_to: Optional[str] = None
    deleted: tuple = ()
    chain_ok: bool = True
    chain_message: str = ""
    dry_run: bool = False


def rotate_audit_log(
    path,
    *,
    keep_days: int = 365,
    dry_run: bool = False,
    verify: bool = True,
    stamp=None,
):
    """Rotate the audit log: verify chain, gzip, sweep old archives.

    Pre-rotation chain verification (M13.1, decision 0016): when
    verify=True (default), verify_chain(path) runs first. If the chain
    is broken, the function returns a RotateResult with chain_ok=False
    and does NOT touch any file. The caller (CLI) maps this to exit
    code 4.

    On a clean chain:
        1. If the log is empty / missing, no-op.
        2. Rename audit.jsonl -> audit-<stamp>.jsonl (collision-safe).
        3. gzip the rotated file to audit-<stamp>.jsonl.gz.
        4. Sweep audit-*.jsonl.gz files older than keep_days.

    Args:
        path: log path. Need not exist (no-op).
        keep_days: retention in days for compressed archives.
        dry_run: when True, return a RotateResult describing what
            WOULD happen without touching any file.
        verify: when True (default), refuse to rotate a broken chain.
        stamp: YYYYMMDD stamp for the rotated name (test hook).

    Returns:
        RotateResult.
    """
    import gzip
    import shutil

    p = Path(path)
    if verify:
        chain = verify_chain(p)
        if not chain.ok:
            msg_parts = []
            if chain.bad_line is not None:
                msg_parts.append("chain broken at line " + str(chain.bad_line))
            elif chain.first_unverifiable_line is not None:
                msg_parts.append("chain unverifiable from line " + str(chain.first_unverifiable_line))
            if chain.malformed_lines:
                msg_parts.append("malformed JSONL lines: " + ", ".join(str(n) for n in chain.malformed_lines))
            return RotateResult(
                rotated_from=str(p),
                rotated_to=None,
                deleted=(),
                chain_ok=False,
                chain_message="; ".join(msg_parts) or "chain verification failed",
                dry_run=dry_run,
            )
    if stamp is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    parent = p.parent if p.parent else Path(".")
    rotated_raw = parent / ("audit-" + stamp + ".jsonl")
    rotated_gz = parent / ("audit-" + stamp + ".jsonl.gz")
    sweep_deleted = []
    if p.exists() and p.is_file():
        try:
            cutoff = p.stat().st_mtime - keep_days * 86400
        except OSError:
            cutoff = 0
        for old in sorted(parent.glob("audit-*.jsonl.gz")):
            try:
                if old.stat().st_mtime < cutoff:
                    sweep_deleted.append(str(old))
            except OSError:
                continue
    if dry_run:
        would_archive = p.exists() and p.stat().st_size > 0
        return RotateResult(
            rotated_from=str(p),
            rotated_to=str(rotated_gz) if would_archive else None,
            deleted=tuple(sweep_deleted),
            chain_ok=True,
            chain_message="dry run; no changes made",
            dry_run=True,
        )
    if not p.exists():
        raise FileNotFoundError("audit log not found: " + str(p))
    size = p.stat().st_size
    if size == 0:
        return RotateResult(
            rotated_from=str(p),
            rotated_to=None,
            deleted=tuple(sweep_deleted),
            chain_ok=True,
            chain_message="empty log; no rotation performed",
            dry_run=False,
        )
    if rotated_raw.exists():
        n = 1
        while True:
            cand = parent / ("audit-" + stamp + "-" + str(n) + ".jsonl")
            if not cand.exists():
                rotated_raw = cand
                rotated_gz = parent / (cand.name + ".gz")
                break
            n += 1
    p.rename(rotated_raw)
    with rotated_raw.open("rb") as src, gzip.open(str(rotated_gz), "wb") as dst:
        shutil.copyfileobj(src, dst)
    rotated_raw.unlink()
    for path_str in sweep_deleted:
        try:
            Path(path_str).unlink()
        except OSError:
            continue
    return RotateResult(
        rotated_from=str(p),
        rotated_to=str(rotated_gz),
        deleted=tuple(sweep_deleted),
        chain_ok=True,
        chain_message="rotated; chain verified",
        dry_run=False,
    )


def _compute_entry_hash(prev_hash: str, payload: dict) -> str:
    """Compute the sha256 entry_hash for a payload + prev_hash.

    The hash is over the UTF-8 concatenation of:
        * prev_hash (64 hex chars)
        * canonical JSON of the payload with the chain fields removed

    Canonical = sorted keys, ```separators=(",", ":")```, ASCII-safe
    (the audit sink writes ```ensure_ascii=False``` but the values are
    also re-serialised through the verifier's own encoder, so the
    verifier MUST use ```ensure_ascii=True``` for a stable byte stream
    independent of the system locale).

    Returns the lowercase hex digest.
    """
    sanitised = {k: v for k, v in payload.items() if k not in _HASH_FIELDS}
    canonical = json.dumps(sanitised, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(canonical.encode("ascii"))
    return h.hexdigest()


# --- Helpers -----------------------------------------------------------------


def _now_iso():
    """Return current UTC time in ISO 8601 (seconds resolution + 'Z')."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_audit_path():
    """Default audit log path: <cwd>/logs/audit.jsonl.

    SMOLCODE_AUDIT_LOG overrides. The path is returned as a string
    (not resolved) so the caller decides whether to absolutise it.
    """
    override = os.environ.get("SMOLCODE_AUDIT_LOG")
    if override:
        return override
    return str(Path.cwd() / "logs" / "audit.jsonl")


__all__ = [
    "AuditSink",
    "AuditError",
    "VerifyResult",
    "RotateResult",
    "HASH_CHAIN_ENV",
    "default_audit_path",
    "verify_chain",
    "rotate_audit_log",
]


if __name__ == "__main__":  # pragma: no cover
    sink = AuditSink(default_audit_path())
    sink.record("manual", note="audit module self-test")
    sink.close()
    print("ok", sink.path, file=sys.stderr)
