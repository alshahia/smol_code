"""M4.x - git checkpoint tests.

Covers `smolcode.checkpoint.create_checkpoint`:
  - Not a git repo -> skipped: not-a-git-repo.
  - Workspace path doesn't exist -> skipped: no-workspace.
  - Clean tree -> skipped: clean-tree.
  - Dirty tree -> created (stash entry recorded).
  - Workspace=None -> raises ValueError.
  - Audit emission on each path.

Plus the `CheckpointResult.to_audit_fields` and
`format_checkpoint_message` helpers.

Tests that actually run git use `tmp_path` (pytest fixture) so they
don't touch the user's repo. Tests that just need a path use
`tmp_path` too, never the cwd.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from smolcode.checkpoint import (
    CheckpointResult,
    create_checkpoint,
    format_checkpoint_message,
)


# ---- Workspace = None ------------------------------------------------------


class TestWorkspaceRequired:
    def test_workspace_none_raises(self):
        with pytest.raises(ValueError):
            create_checkpoint(None)

    def test_workspace_none_raises_even_with_audit(self):
        with pytest.raises(ValueError):
            create_checkpoint(None, audit_sink=_FakeAudit())


# ---- Not a git repo --------------------------------------------------------


class TestNotAGitRepo:
    def test_non_git_directory_skipped(self, tmp_path_factory):
        # pytest's default tmp_path is under the repository, so Git
        # would discover the parent worktree. Use a path outside the repo.
        workspace = _non_git_workspace(tmp_path_factory)
        assert not (workspace / ".git").exists()
        res = create_checkpoint(workspace)
        assert res.status == "skipped"
        assert res.reason == "not-a-git-repo"
        assert res.ref == ""
        assert res.timestamp != ""

    def test_non_git_directory_emits_audit(self, tmp_path_factory):
        audit = _FakeAudit()
        workspace = _non_git_workspace(tmp_path_factory)
        res = create_checkpoint(workspace, audit_sink=audit)
        assert res.status == "skipped"
        assert audit.events and audit.events[0][0] == "checkpoint"


def _non_git_workspace(tmp_path_factory):
    """Create a directory outside the repository for Git-discovery tests.

    pytest's default ``tmp_path`` is under the repository, so Git
    discovers the parent worktree and treats the test directory as
    part of it. We need a fresh empty directory *outside* the
    repository's working tree. We use ``tempfile.mkdtemp`` under
    the OS temp directory; cleanup relies on the OS temp policy
    (pytest's finalizer hooks vary by version).
    """
    return Path(tempfile.mkdtemp(prefix="smolcode-not-a-git-repo-"))


# ---- Workspace path doesn't exist -----------------------------------------


class TestNoWorkspace:
    def test_missing_path_skipped(self, tmp_path):
        ghost = tmp_path / "does_not_exist"
        res = create_checkpoint(ghost)
        assert res.status == "skipped"
        assert res.reason == "no-workspace"

    def test_missing_path_emits_audit(self, tmp_path):
        ghost = tmp_path / "nope"
        audit = _FakeAudit()
        res = create_checkpoint(ghost, audit_sink=audit)
        assert res.status == "skipped"
        assert audit.events and audit.events[0][0] == "checkpoint"


# ---- Clean git repo --------------------------------------------------------


class TestCleanRepo:
    def test_clean_repo_skipped(self, tmp_path):
        _init_repo(tmp_path)
        # No file modifications -> clean tree.
        res = create_checkpoint(tmp_path)
        assert res.status == "skipped"
        assert res.reason == "clean-tree"
        assert res.ref == ""

    def test_clean_repo_emits_audit(self, tmp_path):
        _init_repo(tmp_path)
        audit = _FakeAudit()
        res = create_checkpoint(tmp_path, audit_sink=audit)
        assert res.status == "skipped"
        assert audit.events and audit.events[0][0] == "checkpoint"


# ---- Dirty git repo --------------------------------------------------------


class TestDirtyRepo:
    def test_dirty_repo_creates_stash(self, tmp_path):
        repo = _init_repo(tmp_path)
        # Create an untracked file so the tree is dirty.
        (repo / "new.txt").write_text("hello\n")

        res = create_checkpoint(repo)
        assert res.status == "created"
        assert res.ref == "stash@{0}"
        assert res.message.startswith("smolcode-checkpoint-")
        assert res.timestamp != ""
        assert res.files >= 1

    def test_dirty_repo_stash_list_contains_message(self, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "new.txt").write_text("hi\n")
        res = create_checkpoint(repo)
        assert res.status == "created"
        # Verify the stash entry actually exists.
        out = subprocess.run(
            ["git", "stash", "list"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
        assert res.message in out.stdout

    def test_dirty_repo_emits_audit(self, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "x.txt").write_text("x\n")
        audit = _FakeAudit()
        res = create_checkpoint(repo, audit_sink=audit)
        assert res.status == "created"
        # First event is checkpoint; verify the shape.
        assert audit.events and audit.events[0][0] == "checkpoint"
        fields = audit.events[0][1]
        assert fields.get("status") == "created"
        assert fields.get("ref") == "stash@{0}"

    def test_dirty_repo_then_run_again_is_clean(self, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "x.txt").write_text("x\n")
        first = create_checkpoint(repo)
        assert first.status == "created"
        # After stashing, the tree is clean.
        second = create_checkpoint(repo)
        assert second.status == "skipped"
        assert second.reason == "clean-tree"


# ---- Helpers ---------------------------------------------------------------


def _init_repo(path):
    """Create a git repo at `path` with an initial commit on main."""
    path = str(path)
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    for args in [
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "test"],
        ["config", "commit.gpgsign", "false"],
        ["commit", "--allow-empty", "-m", "init"],
    ]:
        subprocess.run(
            ["git", *args],
            cwd=path,
            env=env,
            capture_output=True,
            check=True,
        )
    # Return as Path so callers can do (repo / "x.txt").write_text(...).
    import pathlib

    return pathlib.Path(path)


class _FakeAudit:
    """In-memory audit sink stand-in for unit tests."""

    def __init__(self):
        self.events = []

    def record(self, event, **fields):
        self.events.append((event, fields))


# ---- format_checkpoint_message --------------------------------------------


class TestFormatMessage:
    def test_created_message_includes_ref_and_files(self):
        r = CheckpointResult(
            status="created",
            ref="stash@{0}",
            message="m",
            files=3,
            timestamp="2026-01-01T00:00:00Z",
        )
        msg = format_checkpoint_message(r)
        assert "stash@{0}" in msg
        assert "3" in msg
        assert "git stash pop" in msg

    def test_skipped_message_includes_reason(self):
        r = CheckpointResult(status="skipped", reason="clean-tree", timestamp="x")
        msg = format_checkpoint_message(r)
        assert "clean-tree" in msg

    def test_failed_message_includes_stderr(self):
        r = CheckpointResult(
            status="failed",
            reason="stash-failed",
            stderr="boom",
            timestamp="x",
        )
        msg = format_checkpoint_message(r)
        assert "FAILED" in msg
        assert "boom" in msg

    def test_unknown_status_falls_back(self):
        r = CheckpointResult(status="weird", timestamp="x")
        msg = format_checkpoint_message(r)
        assert "weird" in msg


# ---- to_audit_fields ------------------------------------------------------


class TestAuditFields:
    def test_created_fields_include_ref_and_message(self):
        r = CheckpointResult(
            status="created",
            ref="stash@{0}",
            message="m",
            files=5,
            timestamp="2026-01-01T00:00:00Z",
        )
        f = r.to_audit_fields()
        assert f["kind"] == "stash"
        assert f["status"] == "created"
        assert f["ref"] == "stash@{0}"
        assert f["message"] == "m"
        assert f["files"] == 5
        assert f["ts"] == "2026-01-01T00:00:00Z"

    def test_skipped_fields_only_include_reason(self):
        r = CheckpointResult(status="skipped", reason="clean-tree", timestamp="x")
        f = r.to_audit_fields()
        assert f["kind"] == "stash"
        assert f["status"] == "skipped"
        assert f["reason"] == "clean-tree"
        assert "ref" not in f
        assert "message" not in f

    def test_failed_fields_include_stderr_tail(self):
        r = CheckpointResult(
            status="failed",
            reason="stash-failed",
            stderr="abc",
            timestamp="x",
        )
        f = r.to_audit_fields()
        assert f["status"] == "failed"
        assert f["reason"] == "stash-failed"
        assert f["stderr_tail"] == "abc"

    def test_long_stderr_truncated_in_audit_fields(self):
        long = "x" * 1000
        r = CheckpointResult(
            status="failed",
            reason="stash-failed",
            stderr=long,
            timestamp="x",
        )
        f = r.to_audit_fields()
        assert len(f["stderr_tail"]) <= 500
