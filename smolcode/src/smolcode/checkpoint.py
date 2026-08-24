"""Git checkpoint before full_access runs (M4.x, decision 0007).

If the workspace is a git repo with uncommitted changes, create a
`git stash push -u -m "smolcode-checkpoint-<ISO8601>-<pid>"` and
record the stash ref in the audit log.

If the workspace is not a git repo, OR is clean, the checkpoint is
SKIPPED (not an error). Skipping is recorded in the audit log so
the user can verify after the fact.

The stash ref is returned in CheckpointResult so the caller (cli.py)
can print it. The user manually rolls back with `git stash pop`
(after verifying the run was acceptable) or `git stash drop` (to
discard the checkpoint). We do NOT auto-pop on success; that's too
magical and surprising.

Failure modes (all surfaced in the result, not raised):
  - Not a git repo: status="skipped", reason="not-a-git-repo".
  - Clean tree: status="skipped", reason="clean-tree".
  - git stash failed: status="failed", reason="stash-failed",
    stderr captured for the user.
  - Workspace path doesn't exist: status="skipped", reason="no-workspace".
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_STASH_TIMEOUT_S = 30.0


@dataclass
class CheckpointResult:
    """Outcome of one checkpoint attempt."""

    status: str  # "created" | "skipped" | "failed"
    reason: str = ""  # empty for created; "clean-tree" | "not-a-git-repo" | ...
    ref: str = ""  # e.g. "stash@{0}"
    message: str = ""  # the stash message
    files: int = 0  # approximate count from `git stash list` line for our ref
    stderr: str = ""  # captured on failure
    timestamp: str = ""  # ISO 8601 UTC at checkpoint time

    def to_audit_fields(self):
        """Return a dict suitable for AuditSink.record(...)."""
        out = {"kind": "stash", "status": self.status}
        if self.reason:
            out["reason"] = self.reason
        if self.ref:
            out["ref"] = self.ref
        if self.message:
            out["message"] = self.message
        if self.files:
            out["files"] = self.files
        if self.timestamp:
            out["ts"] = self.timestamp
        if self.stderr:
            out["stderr_tail"] = self.stderr[-500:]
        return out


def create_checkpoint(workspace, audit_sink=None):
    """Create a git-stash checkpoint for `workspace`.

    Args:
        workspace: Path-like. The directory the agent will operate on.
        audit_sink: optional AuditSink. If provided, a `checkpoint`
            event is recorded with the result.

    Returns:
        CheckpointResult. Never raises for the documented skip
        reasons; raises only on programmer error (e.g. workspace is
        None).
    """
    if workspace is None:
        raise ValueError("workspace is required")
    ws = Path(workspace)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pid = os.getpid()

    if not ws.exists():
        res = CheckpointResult(status="skipped", reason="no-workspace", timestamp=ts)
        _audit(audit_sink, res)
        return res

    # 1. Is it a git repo?
    inside = _run_git(ws, ["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        res = CheckpointResult(status="skipped", reason="not-a-git-repo", timestamp=ts)
        _audit(audit_sink, res)
        return res

    # 2. Is the tree clean?
    status = _run_git(ws, ["status", "--porcelain"])
    if status.returncode != 0:
        res = CheckpointResult(
            status="skipped",
            reason="git-status-failed",
            stderr=status.stderr,
            timestamp=ts,
        )
        _audit(audit_sink, res)
        return res
    if not status.stdout.strip():
        res = CheckpointResult(status="skipped", reason="clean-tree", timestamp=ts)
        _audit(audit_sink, res)
        return res

    # 3. Stash.
    msg = "smolcode-checkpoint-" + ts + "-" + str(pid)
    stash = _run_git(ws, ["stash", "push", "-u", "-m", msg], timeout_s=_STASH_TIMEOUT_S)
    if stash.returncode != 0:
        res = CheckpointResult(
            status="failed",
            reason="stash-failed",
            stderr=stash.stderr,
            message=msg,
            timestamp=ts,
        )
        _audit(audit_sink, res)
        return res

    # 4. Look up the stash ref (top of stash list = stash@{0}).
    refs = _run_git(ws, ["stash", "list"])
    ref = ""
    files = 0
    if refs.returncode == 0:
        first = refs.stdout.splitlines()[0] if refs.stdout else ""
        if first.startswith("stash@{"):
            # Format: "stash@{0}: On <branch>: <message>"
            head = first.split(":", 1)[0].strip()
            ref = head
            # Count untracked + modified files roughly: lines in
            # `git status --porcelain` were already captured above;
            # use that as a "files affected" indicator.
            files = len([line for line in status.stdout.splitlines() if line.strip()])

    res = CheckpointResult(
        status="created",
        ref=ref,
        message=msg,
        files=files,
        timestamp=ts,
    )
    _audit(audit_sink, res)
    return res


def _run_git(cwd, args, timeout_s=10.0):
    """Run a git subprocess; never raises (returns CompletedProcess)."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        # CompletedProcess-like
        return _FakeCompletedProcess(returncode=124, stdout="", stderr="timeout: " + str(e))
    except FileNotFoundError:
        return _FakeCompletedProcess(returncode=127, stdout="", stderr="git not found in PATH")
    except Exception as e:
        return _FakeCompletedProcess(returncode=1, stdout="", stderr=repr(e))


@dataclass
class _FakeCompletedProcess:
    returncode: int
    stdout: str
    stderr: str


def _audit(audit_sink, result):
    """Record the checkpoint event in the audit sink (if installed)."""
    if audit_sink is None:
        return
    try:
        audit_sink.record("checkpoint", **result.to_audit_fields())
    except Exception:
        pass


def format_checkpoint_message(result):
    """Human-friendly single-line summary for the CLI."""
    if result.status == "created":
        return (
            "checkpoint created: "
            + (result.ref or "stash@?{?}")
            + " ("
            + str(result.files)
            + " file(s)); rollback with `git stash pop`"
        )
    if result.status == "skipped":
        return "checkpoint skipped: " + (result.reason or "unknown")
    if result.status == "failed":
        return (
            "checkpoint FAILED: "
            + (result.reason or "unknown")
            + (" -- " + result.stderr[:200] if result.stderr else "")
        )
    return "checkpoint: " + result.status


__all__ = ["CheckpointResult", "create_checkpoint", "format_checkpoint_message"]


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) < 2:
        print("usage: python -m smolcode.checkpoint <workspace>", file=sys.stderr)
        sys.exit(2)
    res = create_checkpoint(sys.argv[1])
    print(format_checkpoint_message(res), file=sys.stderr)
    sys.exit(0 if res.status in ("created", "skipped") else 1)
