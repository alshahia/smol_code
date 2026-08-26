#!/usr/bin/env python3
"""Cross-platform audit log rotation helper (M7, decision 0009).

See docs/audit-log-retention.md for the full design. This script is
intended to be invoked by an external scheduler (cron on Linux,
launchd on macOS, Task Scheduler on Windows). It does NOT change
the audit log while smolcode is running: the AuditSink keeps the
file handle open in append mode, and on POSIX the rename is atomic
so the next write goes to the newly-created audit.jsonl.

Usage:
    python3 scripts/rotate_audit_log.py
    SMOLCODE_REPO=/path/to/repo SMOLCODE_AUDIT_RETENTION_DAYS=90 \
        python3 scripts/rotate_audit_log.py

Exit codes:
    0  rotation (or no-op) succeeded.
    1  an error occurred; stderr has the traceback.
"""

from __future__ import annotations

import gzip
import os
import shutil
import sys
import time
from pathlib import Path


def main() -> int:
    repo = Path(os.environ.get("SMOLCODE_REPO", ".")).resolve()
    log_dir = repo / "logs"
    log_file = log_dir / "audit.jsonl"
    retention_days = int(os.environ.get("SMOLCODE_AUDIT_RETENTION_DAYS", "365"))

    if not log_dir.exists():
        log_dir.mkdir(parents=True, exist_ok=True)
    if not log_file.exists() or log_file.stat().st_size == 0:
        print("no audit log to rotate", file=sys.stderr)
    else:
        stamp = time.strftime("%Y%m%d")
        rotated = log_dir / ("audit-" + stamp + ".jsonl")
        # If the stamp already exists, add a counter so we never lose
        # data by overwriting a previous run's rotation.
        counter = 1
        while rotated.exists():
            rotated = log_dir / ("audit-" + stamp + "-" + str(counter) + ".jsonl")
            counter += 1
        log_file.rename(rotated)
        gz_path = rotated.with_suffix(".jsonl.gz")
        with rotated.open("rb") as src:
            with gzip.open(gz_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
        rotated.unlink()
        print("rotated", str(rotated), "->", str(gz_path), file=sys.stderr)

    # Delete old compressed logs.
    now = time.time()
    for old in log_dir.glob("audit-*.jsonl.gz"):
        try:
            age_days = (now - old.stat().st_mtime) / 86400
        except FileNotFoundError:
            continue
        if age_days > retention_days:
            old.unlink()
            print("deleted", str(old), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
