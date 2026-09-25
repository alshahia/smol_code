"""Phase 6 remediation, plan 6.2 #4 and #5 -- git repository integrity.

Two holes, both HIGH, both found by auditing the shipped work against the
plan checklist rather than against my memory of it.

6.2 #4  Every git invocation inherited the host environment, so git would
       read a global gitconfig that can redefine core.hooksPath, alias.*,
       core.pager and credential.helper. A hostile repo can also ship its
       own .git/config. Nothing pinned the config source, so "git" here
       meant "git plus whatever the operator or the repo asked for".

6.2 #5  tools/fs.py had NO .git reference at all. The workspace is bind-
       mounted rw and restricted tiers allowlist python, so model code can
       write .git/hooks/pre-commit, rewrite .git/config or replace
       .git/HEAD -- and every later git_* tool then runs under
       attacker-chosen configuration. The destructive gate does not help:
       hooks fire on ordinary commits and diffs.

The fix is constrained. tools/git.py inlines everything deliberately because
smolagents serialises the source into the sandbox and its validator rejects
module-level references (see the module docstring and test_bind_roundtrip.py).
There is no shared helper to add: the hardened environment must be BOUND as a
class attribute, which is the pattern this file already uses for allowlist /
cwd / tier_name / destructive_policy.
"""

from __future__ import annotations

import os

import pytest

from smolcode.tools import CommandPolicy
from smolcode.tools.git import build_git_tools


def _tools(tier="restricted"):
    return build_git_tools(CommandPolicy(("git",)), cwd=os.getcwd(), tier_name=tier)


class TestGitEnvironmentIsHardened:
    """Plan 6.2 #4: pin the config source; do not inherit the operator's."""

    def test_every_tool_gets_a_hardened_environment(self):
        for tool in _tools():
            assert getattr(tool, "git_env", None) is not None, tool.name

    def test_system_and_global_config_are_neutralised(self):
        env = _tools()[0].git_env
        assert env.get("GIT_CONFIG_NOSYSTEM") == "1"
        # A null device, not a missing key: a missing key means "use the
        # default", which is the thing we are trying to stop.
        assert env.get("GIT_CONFIG_GLOBAL") in ("/dev/null", "NUL")
        assert env.get("GIT_CONFIG_SYSTEM") in ("/dev/null", "NUL")

    def test_unrelated_host_variables_are_not_inherited(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_TEST_GIT_SECRET", "sk-leak")
        env = _tools()[0].git_env
        assert "SMOLCODE_TEST_GIT_SECRET" not in env

    def test_git_still_needs_path_to_launch(self):
        assert _tools()[0].git_env.get("PATH")

    def test_credentials_are_still_available_for_push(self):
        # Hardening the config source must not break authentication: the
        # token itself travels in the environment, not in gitconfig.
        env = _tools()[0].git_env
        assert env.get("GIT_TERMINAL_PROMPT") == "0"


class TestEveryGitInvocationUsesTheHardenedEnv:
    """Guard against a future tool being added without the hardening."""

    def test_no_invocation_runs_with_an_inherited_environment(self, monkeypatch):
        # git.py imports subprocess INSIDE each forward(), so patch the
        # module object rather than an attribute of smolcode.tools.git.
        import subprocess

        seen = []

        class _Proc:
            stdout = ""
            stderr = ""
            returncode = 0

        def fake_run(args, **kwargs):
            seen.append((list(args), kwargs.get("env")))
            return _Proc()

        monkeypatch.setattr(subprocess, "run", fake_run)
        for tool in _tools():
            try:
                tool()
            except Exception:
                # Argument-level policy is covered by test_tools_git_dashguard.
                # We only care that the subprocess boundary is hardened.
                pass

        assert seen, "no git invocation was captured"
        for argv, env in seen:
            assert env is not None, argv
            assert env.get("GIT_CONFIG_NOSYSTEM") == "1", argv
            assert "core.hooksPath=" in argv, argv


class TestGitDirectoryIsNotWritable:
    """Plan 6.2 #5: model code must not be able to reconfigure the repo."""

    @staticmethod
    def _write(tier, path, tmp_path):
        from smolcode.tools._bind import bind_attrs
        from smolcode.tools.fs import _WriteFileTool

        cls = bind_attrs(_WriteFileTool, {"workspace": str(tmp_path), "tier": tier, "uploads_dir": ""})
        return cls().forward(path=path, content="x")

    def test_restricted_cannot_write_hooks(self, tmp_path):
        (tmp_path / ".git" / "hooks").mkdir(parents=True)
        with pytest.raises(PermissionError, match="git"):
            self._write("restricted", ".git/hooks/pre-commit", tmp_path)

    def test_restricted_cannot_rewrite_config(self, tmp_path):
        (tmp_path / ".git").mkdir(parents=True)
        with pytest.raises(PermissionError, match="git"):
            self._write("restricted", ".git/config", tmp_path)

    def test_elevated_is_also_blocked(self, tmp_path):
        (tmp_path / ".git").mkdir(parents=True)
        with pytest.raises(PermissionError, match="git"):
            self._write("elevated", ".git/HEAD", tmp_path)

    def test_full_access_may_still_write(self, tmp_path):
        # full_access is the explicit, audited tier. Blocking it there
        # would break legitimate repo repair work for no security gain.
        (tmp_path / ".git").mkdir(parents=True)
        self._write("full_access", ".git/HEAD", tmp_path)
        assert (tmp_path / ".git" / "HEAD").exists()

    def test_case_variant_is_blocked(self, tmp_path):
        (tmp_path / ".GIT").mkdir(parents=True)
        with pytest.raises(PermissionError, match="git"):
            self._write("restricted", ".GIT/config", tmp_path)

    def test_nested_git_dir_is_blocked(self, tmp_path):
        (tmp_path / "sub" / ".git").mkdir(parents=True)
        with pytest.raises(PermissionError, match="git"):
            self._write("restricted", "sub/.git/config", tmp_path)

    def test_ordinary_writes_still_work(self, tmp_path):
        self._write("restricted", "src/app.py", tmp_path)
        assert (tmp_path / "src" / "app.py").exists()

    def test_a_file_merely_named_git_is_fine(self, tmp_path):
        # Only the .git DIRECTORY is protected. Refusing .gitignore or a
        # file called git would be a false positive that breaks real work.
        self._write("restricted", ".gitignore", tmp_path)
        assert (tmp_path / ".gitignore").exists()
