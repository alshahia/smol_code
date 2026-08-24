"""Read-only audit log reader (M14.1, decision 0018).

A small, dependency-free reader for the JSONL audit log that powers
the SPA's `/api/audit` endpoint and is also reusable from the CLI
for one-off queries.

Why a separate module?

* The SPA wants JSON-ready dicts (not dataclasses).
* The reader is testable without spinning up FastAPI / the audit
  sink. Tests construct an AuditSink, then call the reader.
* The reader is the single place that decides how `RedactSecretsFilter`
  is applied to audit entries on read; the SPA does not duplicate
  the policy.

Public surface:

    read_audit_entries(path, *, limit, grep, redact, max_bytes)
        -> {"entries": [...], "total": N, "truncated": bool,
            "note": str|None}

    audit_chain_status(path) -> dict (JSON-safe VerifyResult)

    DEFAULT_LIMIT     = 50
    MAX_LIMIT         = 500
    DEFAULT_MAX_BYTES = 10 * 1024 * 1024   # 10 MB safety cap

Design notes:

* The reader is deliberately NOT streaming. A 10 MB cap + 500-line
  ceiling keep memory bounded; the long-term answer is rotation
  (`smolcode audit rotate`, M14.3).
* Malformed JSONL lines are SKIPPED (not raised). The audit log
  is append-only; a corrupted line means upstream bug, not a
  read-side error.
* Redaction runs on every string field via `_redact_value` (from
  `redact.py`), recursively over dicts and lists. The redactor is
  the SAME one used by the logging factory; the reader does NOT
  introduce a second filter implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

from .audit import verify_chain
from .redact import DEFAULT_PATTERNS, _redact_value


DEFAULT_LIMIT: int = 50
MAX_LIMIT: int = 500
# Per docs/security.md section 8 the audit log is append-only and may
# grow indefinitely if rotation is skipped. The reader enforces a
# 10 MB safety cap on the file it loads; truncation is reported,
# not silently dropped, so the SPA can prompt the operator to
# rotate.
DEFAULT_MAX_BYTES: int = 10 * 1024 * 1024

# Fields used by `grep`. Matches the haystack built by the CLI's
# `audit grep` so the SPA's search box behaves the same way.
_GREP_FIELDS = ("event", "tier", "task", "action", "message", "kind")


def read_audit_entries(
    path: Union[str, Path],
    *,
    limit: int = DEFAULT_LIMIT,
    grep: Optional[str] = None,
    redact: bool = True,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Read recent audit entries from a JSONL audit log.

    Args:
        path: log file path. Missing file is not an error -- the
            function returns an empty payload with a ``note`` so
            the SPA can render a graceful empty state.
        limit: maximum number of entries to return (most-recent
            tail). Clamped to ``[1, MAX_LIMIT]``.
        grep: optional case-insensitive substring filter; matches
            across ``event``, ``tier``, ``task``, ``action``,
            ``message``, ``kind``. Empty string = no filter.
        redact: when True (default) every string value in each
            returned entry is passed through ``RedactSecretsFilter``
            (``_redact_value``), recursively.
        max_bytes: cap on the file size that will be loaded. If the
            log is larger than this, the function reads the LAST
            ``max_bytes`` bytes (so the most-recent entries are
            always preserved) and sets ``truncated=True``.

    Returns:
        ``{"entries": [...], "total": <int>, "truncated": <bool>,
        "note": <str|None>}``. ``total`` is the count of entries
        AFTER grep filtering but BEFORE limit truncation. The
        ``note`` field is populated only when the file is missing
        or empty so the SPA can render a hint.
    """
    p = Path(path)
    if not p.exists():
        return {
            "entries": [],
            "total": 0,
            "truncated": False,
            "note": "no audit log",
        }
    if p.is_dir():
        return {
            "entries": [],
            "total": 0,
            "truncated": False,
            "note": "audit path is a directory",
        }

    clamped_limit = max(1, min(int(limit), MAX_LIMIT))

    raw_text, truncated = _read_tail(p, max_bytes)
    entries: list[dict[str, Any]] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            # Malformed JSONL is a tolerable read-side condition
            # for an append-only log; skip the bad line rather than
            # crash the SPA. `audit verify` will surface the bad
            # line number separately.
            continue
        if not isinstance(obj, dict):
            continue
        entries.append(obj)

    # grep filter
    if grep:
        needle = str(grep).lower()
        entries = [e for e in entries if _matches_grep(e, needle)]

    total_after_grep = len(entries)

    # Tail by `clamped_limit`. `entries[-N:]` is the most-recent N.
    if len(entries) > clamped_limit:
        entries = entries[-clamped_limit:]

    if redact and entries:
        # Single-shot: build a tuple of patterns once.
        entries = [_redact_value(e, DEFAULT_PATTERNS) for e in entries]

    note: Optional[str] = None
    if total_after_grep == 0 and not grep:
        note = "audit log is empty"

    return {
        "entries": entries,
        "total": total_after_grep,
        "truncated": truncated,
        "note": note,
    }


def audit_chain_status(path: Union[str, Path]) -> dict[str, Any]:
    """Return `verify_chain(path)` as a JSON-safe dict.

    The shape is intentionally flat (no VerifyResult import on the
    SPA side) so it can travel through JSON without a custom
    encoder. Missing file raises ``FileNotFoundError`` -- the caller
    (the SPA endpoint) catches it and sets a graceful ``note``.
    """
    r = verify_chain(path)
    return {
        "ok": bool(r.ok),
        "entries": int(r.entries),
        "chained_entries": int(r.chained_entries),
        "bad_line": r.bad_line,
        "first_unverifiable_line": r.first_unverifiable_line,
        "malformed_lines": list(r.malformed_lines),
    }


# --- helpers ---------------------------------------------------------------


def _read_tail(p: Path, max_bytes: int) -> tuple[str, bool]:
    """Return ``(text, truncated)``.

    If the file is smaller than ``max_bytes``, the entire file is
    returned and ``truncated=False``. Otherwise the LAST
    ``max_bytes`` bytes are returned and ``truncated=True``. (We
    always prefer the tail because the audit log is most useful
    for the most-recent entries; the head is the historical
    archive, which rotation handles.)
    """
    size = p.stat().st_size
    if size <= max_bytes:
        with p.open("r", encoding="utf-8", errors="replace") as fp:
            return fp.read(), False
    with p.open("rb") as fp:
        fp.seek(-max_bytes, 2)
        data = fp.read()
    # Strip a partial leading line if the seek landed mid-line.
    text = data.decode("utf-8", errors="replace")
    nl = text.find("\n")
    if 0 <= nl < len(text) - 1:
        text = text[nl + 1 :]
    return text, True


def _matches_grep(entry: dict[str, Any], needle_lower: str) -> bool:
    for key in _GREP_FIELDS:
        v = entry.get(key)
        if v is None:
            continue
        if needle_lower in str(v).lower():
            return True
    return False


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "DEFAULT_MAX_BYTES",
    "read_audit_entries",
    "audit_chain_status",
]
