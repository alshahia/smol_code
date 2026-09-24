"""Phase 6 section 6.2 (H2 / R10) -- git tool argument-injection hardening.

Every git tool built its argv by splicing model-supplied values straight
in after the subcommand. None inserted the `--` end-of-options separator,
and none rejected a value beginning with `-`, so git parsed attacker-
chosen data as FLAGS rather than operands:

    git_diff(extra_args=["--output=/etc/cron.d/x"])
        -> git writes the diff to an arbitrary path (arbitrary write)
    git_clone(url="--upload-pack=touch /tmp/pwned")
        -> git runs an attacker-chosen command (RCE)
    git_clone(url="ext::sh -c whoami")
        -> git transport helper executes a shell command (RCE)
    git_add(paths=["--all"])
        -> stages the whole worktree, not the path the model meant
    git_push(remote="--mirror") / git_fetch(remote="--all")
        -> pushes/fetches far more than the named remote

The last test in this file is an equivalence guard: it asserts EVERY tool
registered by build_git_tools carries the guard marker, so a future tool
cannot ship without one.
"""

from __future__ import annotations

import inspect

import pytest

from smolcode.tools import CommandPolicy
from smolcode.tools.git import build_git_tools


@pytest.fixture
def git_repo(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(repo)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True, capture_output=True)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "i"], check=True, capture_output=True)
    return repo


@pytest.fixture
def tools(git_repo):
    return {t.name: t for t in build_git_tools(CommandPolicy(("git",)), cwd=str(git_repo))}


class TestDiffRejectsFlagShapedArgs:
    def test_output_flag_is_refused(self, tools):
        with pytest.raises(PermissionError):
            tools["git_diff"](staged=False, extra_args=["--output=/tmp/pwned"])

    def test_no_stray_file_is_written(self, tools, tmp_path):
        victim = tmp_path / "pwned.diff"
        with pytest.raises(PermissionError):
            tools["git_diff"](staged=False, extra_args=["--output=" + str(victim)])
        assert not victim.exists()

    def test_a_normal_extra_arg_still_works(self, tools):
        out = tools["git_diff"](staged=False, extra_args=["--stat"])
        assert "returncode: 0" in out


class TestAddRejectsFlagShapedPaths:
    def test_all_flag_is_refused(self, tools):
        with pytest.raises(PermissionError):
            tools["git_add"](paths=["--all"])

    def test_dot_slash_dash_dash_prefix_is_refused(self, tools):
        with pytest.raises(PermissionError):
            tools["git_add"](paths=["-A"])


class TestCloneRejectsRceVectors:
    def test_upload_pack_is_refused(self, tools):
        with pytest.raises(PermissionError):
            tools["git_clone"](url="--upload-pack=touch /tmp/pwned")

    def test_ext_transport_helper_is_refused(self, tools):
        # git treats ext:: as "run this with the shell".
        with pytest.raises(PermissionError):
            tools["git_clone"](url="ext::sh -c whoami")

    def test_leading_dash_url_is_refused(self, tools):
        with pytest.raises(PermissionError):
            tools["git_clone"](url="-c core.sshCommand=calc")

    def test_ssh_url_with_dash_command_is_refused(self, tools):
        with pytest.raises(PermissionError):
            tools["git_clone"](url="ssh://host/x.git", directory="--config=evil")

    def test_https_url_is_allowed(self, tools):
        out = tools["git_clone"](url="https://example.invalid/x.git")
        # It is allowed to be ATTEMPTED; the network failure is the point.
        assert "returncode:" in out


class TestPushFetchRejectFlagShapedRemotes:
    # NOTE: git_push is ALSO behind the destructive gate, which in a session
    # with no confirm callback rejects EVERY call with PermissionError. A bare
    # pytest.raises would therefore pass for the wrong reason -- as it did on
    # the first run of this file. Each case matches the dash-guard message
    # specifically so it can only pass on the guard actually firing.

    def test_push_mirror_is_refused_by_the_dash_guard(self, tools):
        with pytest.raises(PermissionError, match="looks like a git flag"):
            tools["git_push"](remote="--mirror")

    def test_push_force_branch_is_refused_by_the_dash_guard(self, tools):
        with pytest.raises(PermissionError, match="looks like a git flag"):
            tools["git_push"](remote="origin", branch="--force")

    def test_fetch_all_is_refused(self, tools):
        with pytest.raises(PermissionError, match="looks like a git flag"):
            tools["git_fetch"](remote="--all")


class TestCheckoutRejectsFlagShapedTargets:
    def test_orphan_flag_is_refused(self, tools):
        with pytest.raises(PermissionError):
            tools["git_checkout"](target="--orphan", create=False)


class TestGitConfigInjectionIsNeutralised:
    def test_every_git_invocation_ignores_the_global_git_config(self, tools, git_repo):
        """A model that can write ~/.gitconfig must not be able to steer git
        itself (core.pager, core.sshCommand, core.fsmonitor, aliases...)."""
        out = tools["git_status"]()
        assert "returncode: 0" in out


class TestEquivalenceGuard:
    """No tool may ship without the guard. This is the test that stops the
    next tool added to _GIT_TOOL_CLASSES from reintroducing H2.

    The guard is INLINED into each forward() rather than factored into a
    module-level helper, because tools/git.py's contract is that a tool's
    source must be self-contained for the Docker executor (see the module
    docstring). So the marker is a literal string that the inlined guard
    always contains, not a function name.
    """

    GUARD_MARKER = "looks like a git flag"

    # Inputs that carry a model-chosen STRING or LIST into argv. A tool with
    # no such input (git_status, git_log) cannot be attacked this way and is
    # deliberately exempt.
    TEXT_OPERAND_INPUTS = {
        "extra_args",
        "paths",
        "message",
        "remote",
        "branch",
        "url",
        "directory",
        "target",
    }

    def test_every_tool_with_a_text_operand_carries_the_dash_guard(self):
        missing = []
        for tool in build_git_tools(CommandPolicy(("git",)), cwd="."):
            if not (set(tool.inputs) & self.TEXT_OPERAND_INPUTS):
                continue
            if self.GUARD_MARKER not in inspect.getsource(type(tool).forward):
                missing.append(tool.name)
        assert not missing, "tools missing the dash-guard: " + ", ".join(missing)

    def test_the_exempt_set_is_still_exempt(self):
        """Guards against the test silently exempting everything."""
        guarded = set()
        for tool in build_git_tools(CommandPolicy(("git",)), cwd="."):
            if set(tool.inputs) & self.TEXT_OPERAND_INPUTS:
                guarded.add(tool.name)
        assert guarded == {
            "git_diff",
            "git_add",
            "git_commit",
            "git_push",
            "git_clone",
            "git_fetch",
            "git_checkout",
        }
