"""Tests for tools/policy.py (PathPolicy + CommandPolicy)."""

from __future__ import annotations

import os

import pytest

from smolcode.tools.policy import CommandPolicy, PathPolicy, PolicyViolation


class TestPathPolicy:
    def test_workspace_path_is_resolved(self, tmp_path):
        # Create a workspace containing some non-canonical characters.
        ws = tmp_path / "ws"
        ws.mkdir()
        policy = PathPolicy(ws)
        assert policy.workspace.is_absolute()
        assert policy.workspace == ws.resolve()

    def test_path_inside_workspace_resolves(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        f = ws / "file.txt"
        f.write_text("hi", encoding="utf-8")
        policy = PathPolicy(ws)
        result = policy.resolve_under_workspace(f)
        assert result == f.resolve()

    def test_path_outside_workspace_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        policy = PathPolicy(ws)
        with pytest.raises(PolicyViolation):
            policy.resolve_under_workspace(outside)

    def test_traversal_via_dotdot_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        policy = PathPolicy(ws)
        with pytest.raises(PolicyViolation):
            policy.resolve_under_workspace(str(ws / ".." / "outside.txt"))

    def test_none_or_empty_path_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        policy = PathPolicy(ws)
        with pytest.raises(PolicyViolation):
            policy.resolve_under_workspace(None)
        with pytest.raises(PolicyViolation):
            policy.resolve_under_workspace("")

    def test_must_exist_true_missing_path_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        policy = PathPolicy(ws)
        missing = ws / "nope.txt"
        with pytest.raises(PolicyViolation):
            policy.resolve_under_workspace(missing, must_exist=True)

    def test_must_exist_false_missing_path_allowed(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        policy = PathPolicy(ws)
        missing = ws / "nope.txt"
        # Should not raise.
        policy.resolve_under_workspace(missing, must_exist=False)

    def test_symlink_inside_workspace_resolves(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        target = ws / "target.txt"
        target.write_text("hi", encoding="utf-8")
        link = ws / "link.txt"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as e:
            pytest.skip("symlinks not supported on this filesystem: " + repr(e))
        policy = PathPolicy(ws)
        result = policy.resolve_under_workspace(link, must_exist=True)
        assert result == target.resolve()

    def test_is_under_true_and_false(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        policy = PathPolicy(ws)
        assert policy.is_under(ws) is True
        assert policy.is_under(ws / "file.txt") is True
        assert policy.is_under(tmp_path / "outside.txt") is False


class TestCommandPolicy:
    def test_allowed_basename_passes(self):
        policy = CommandPolicy(("python", "git", "pytest"))
        assert policy.check_basename("python") == "python"
        assert policy.check_basename("git") == "git"

    def test_disallowed_basename_rejected(self):
        policy = CommandPolicy(("python", "git"))
        with pytest.raises(PolicyViolation):
            policy.check_basename("rm")
        with pytest.raises(PolicyViolation):
            policy.check_basename("curl")

    def test_full_path_basename_still_checked(self):
        policy = CommandPolicy(("python",))
        # On Windows, /usr/bin/python is just a basename "python".
        # The policy only checks the basename; absolute paths pass.
        assert policy.check_basename("/usr/bin/python") == "python"

    def test_empty_cmd_rejected(self):
        policy = CommandPolicy(("python",))
        with pytest.raises(PolicyViolation):
            policy.check_basename("")

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific suffix test")
    def test_windows_exe_suffix_stripped(self):
        policy = CommandPolicy(("python",))
        assert policy.check_basename("python.exe") == "python"
        assert policy.check_basename("python.bat") == "python"

    def test_allowlist_is_tuple(self):
        policy = CommandPolicy(["python", "git"])
        assert policy.allowlist == ("python", "git")
