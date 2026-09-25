"""Phase 6 remediation, plan 6.2 #3 -- the remote must be a configured one.

Before: git_push / git_fetch accepted any remote NAME the model supplied.
The dash-guard (6.2 #2) stopped `--receive-pack=...`, but a plain name like
"upstream" or a name planted in .git/config by a previous step sailed
straight through. The model could publish a workspace to a third-party
remote the user never chose.

These tests use REAL git repositories and REAL remotes. A mocked
`subprocess.run` would have passed whether or not the real `git remote`
output was parsed correctly, which is the only thing that matters here.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from smolcode.session import DestructiveDecision
from smolcode.tools import CommandPolicy
from smolcode.tools.git import build_git_tools


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git CLI not on PATH")


def _git(cwd, *args):
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return p.stdout


@pytest.fixture
def repo(tmp_path):
    """A working repo with two real, local remotes."""

    upstream = tmp_path / "upstream.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(tmp_path, "init", "--bare", str(upstream))
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    (work / "a.txt").write_text("hello", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "init")
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(origin))
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "remote", "add", "upstream", str(upstream))
    return work


def _tool(name, cwd, tier="elevated"):
    tools = {t.name: t for t in build_git_tools(CommandPolicy(("git",)), cwd=str(cwd), tier_name=tier)}
    return tools[name]


@pytest.fixture
def approved(monkeypatch):
    """Install a real auto-approving session for the destructive gate.

    current_session() returns a NEW default-deny SessionState on every call
    when none is installed, so monkeypatching the return value does nothing.
    The session has to be installed with set_session.
    """
    from smolcode.session import SessionState, set_session

    st = SessionState()
    st.auto_approve_destructive = True
    set_session(st)
    yield st
    set_session(None)


@pytest.fixture
def unapproved(monkeypatch):
    """Install a session whose callback records whether it was asked."""
    from smolcode.session import SessionState, set_session

    asked = []

    def cb(name, kwargs, summary):
        asked.append(name)
        return DestructiveDecision(approved=False, reason="test-denied")

    st = SessionState()
    st.auto_approve_destructive = False
    st.confirm_callback = cb
    set_session(st)
    yield asked
    set_session(None)


class TestPushValidatesRemote:
    def test_a_configured_remote_is_accepted(self, repo, approved):
        # The point of the control is to refuse unconfigured remotes. If it
        # also breaks real pushes it is worse than useless, so this pushes
        # for real against a local bare repo and expects success.
        out = _tool("git_push", repo)(remote="origin", branch="main")
        assert "returncode: 0" in out, out

    def test_the_second_configured_remote_is_also_accepted(self, repo, approved):
        out = _tool("git_push", repo)(remote="upstream", branch="main")
        assert "returncode: 0" in out, out

    def test_an_unconfigured_remote_is_refused(self, repo, approved):
        with pytest.raises(PermissionError, match="not configured"):
            _tool("git_push", repo)(remote="attacker", branch="main")

    def test_refusal_happens_before_any_push_runs(self, repo, approved, monkeypatch):
        # Nothing may be sent anywhere when the name is unknown.
        calls = []
        real = subprocess.run

        def spy(args, **kwargs):
            if "push" in list(args):
                calls.append(list(args))
            return real(args, **kwargs)

        monkeypatch.setattr(subprocess, "run", spy)
        with pytest.raises(PermissionError):
            _tool("git_push", repo)(remote="attacker", branch="main")
        assert not calls, calls

    def test_refusal_does_not_cost_the_user_a_prompt(self, repo, unapproved):
        # Same rationale as the dash-guards: a name the repo does not have
        # is a user error, and errors should not raise approval dialogs.
        with pytest.raises(PermissionError, match="not configured"):
            _tool("git_push", repo)(remote="attacker", branch="main")
        assert not unapproved, unapproved


class TestFetchValidatesRemote:
    def test_a_configured_remote_is_accepted(self, repo):
        out = _tool("git_fetch", repo)(remote="origin")
        assert "returncode: 0" in out, out

    def test_an_unconfigured_remote_is_refused(self, repo):
        with pytest.raises(PermissionError, match="not configured"):
            _tool("git_fetch", repo)(remote="attacker")


class TestNonRepositoryIsRefused:
    @staticmethod
    def _outside_any_repo():
        # NOT tmp_path: pytest puts tmp_path under .pytest_tmp/ inside this
        # repository, so "git remote" there correctly walks UP and finds
        # smol_code own remotes. That is right in production -- the workspace
        # IS the repo -- but it makes this test assert the opposite of what
        # it means. Use a real system temp dir with no repo above it.
        import shutil
        import tempfile

        d = tempfile.mkdtemp(prefix="smolcode-norepo-")
        return d, lambda: shutil.rmtree(d, ignore_errors=True)

    def test_outside_a_repo_the_tool_refuses_rather_than_guessing(self):
        # git remote fails outside a repository. The safe reading of that
        # failure is "we cannot verify the remote", not "allow it".
        d, cleanup = self._outside_any_repo()
        try:
            with pytest.raises(PermissionError):
                _tool("git_fetch", d)(remote="origin")
        finally:
            cleanup()

    def test_the_message_says_why(self):
        d, cleanup = self._outside_any_repo()
        try:
            with pytest.raises(PermissionError, match="(?i)repositor|verif"):
                _tool("git_fetch", d)(remote="origin")
        finally:
            cleanup()

    def test_a_repo_with_no_remotes_says_so_distinctly(self):
        # "no remotes" and "not a repository" are different user problems and
        # deserve different messages.
        import shutil
        import subprocess as sp
        import tempfile

        d = tempfile.mkdtemp(prefix="smolcode-noremote-")
        try:
            sp.run(["git", "init", "-b", "main"], cwd=d, capture_output=True, timeout=60)
            with pytest.raises(PermissionError, match="no configured remotes"):
                _tool("git_fetch", d)(remote="origin")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestDashGuardStillWins:
    def test_a_flag_shaped_remote_is_still_rejected(self, repo, approved):
        with pytest.raises(PermissionError, match="flag"):
            _tool("git_push", repo)(remote="--receive-pack=/bin/sh", branch="main")
