"""Phase 6 section 6.3 -- bounding the run tool and the workspace boundary.

Four concrete gaps, all reachable from a model-chosen argument:

  * timeout is taken verbatim from the model. A single call could pin a
    worker for arbitrarily long.
  * stdout/stderr are concatenated with no cap, so one command emitting a
    large stream exhausts memory and floods the context window.
  * build_shell_tools never accepted a cwd, so the bound class attribute
    stayed "" and the subprocess inherited the SERVER process's working
    directory rather than the workspace. The subprocess was therefore not
    bound to the workspace at all.
  * args were not checked for flag shapes, so run("git", ["push",
    "--force"]) walks straight past the dash-guards that f090b93 added to
    the first-class git_push tool.

These tests need no Docker daemon.
"""

from __future__ import annotations

import pytest

from smolcode.tools import CommandPolicy
from smolcode.tools.shell import build_shell_tools


@pytest.fixture
def policy():
    return CommandPolicy(("python", "git", "pytest"))


class TestTimeoutIsClamped:
    # The first version of this class asserted only that the call returned,
    # which a fast command satisfies whether or not the clamp exists. These
    # drive a real sleep and assert the EFFECTIVE timeout that was applied,
    # so they fail when the model's number is passed through.

    def test_model_timeout_above_the_ceiling_is_clamped(self, policy, tmp_path):
        tool = build_shell_tools(policy, tier_name="restricted", cwd=str(tmp_path), max_timeout=2)[0]
        out = tool.forward(cmd="python", args=["-c", "import time; time.sleep(30)"], timeout=100000)
        assert "TIMEOUT after 2s" in out

    def test_model_timeout_below_the_ceiling_is_respected(self, policy, tmp_path):
        tool = build_shell_tools(policy, tier_name="restricted", cwd=str(tmp_path), max_timeout=30)[0]
        out = tool.forward(cmd="python", args=["-c", "import time; time.sleep(30)"], timeout=2)
        assert "TIMEOUT after 2s" in out

    def test_build_shell_tools_accepts_a_max_timeout(self, policy):
        import inspect

        assert "max_timeout" in inspect.signature(build_shell_tools).parameters


class TestOutputIsCapped:
    def test_huge_stdout_is_truncated_with_a_marker(self, policy):
        tool = build_shell_tools(policy, tier_name="restricted")[0]
        result = tool.forward(
            cmd="python",
            args=["-c", "print('A' * (5 * 1024 * 1024))"],
        )
        assert len(result) < 2 * 1024 * 1024, "output cap did not apply"
        assert "TRUNCATED" in result or "truncated" in result.lower()

    def test_ordinary_output_is_not_marked_truncated(self, policy):
        tool = build_shell_tools(policy, tier_name="restricted")[0]
        result = tool.forward(cmd="python", args=["-c", "print('small')"])
        assert "small" in result
        assert "TRUNCATED" not in result


class TestCwdIsBoundToTheWorkspace:
    def test_cwd_is_recorded_on_the_bound_tool(self, policy, tmp_path):
        tool = build_shell_tools(policy, tier_name="restricted", cwd=str(tmp_path))[0]
        assert str(tmp_path) in tool.cwd

    def test_subprocess_runs_in_the_workspace(self, policy, tmp_path):
        tool = build_shell_tools(policy, tier_name="restricted", cwd=str(tmp_path))[0]
        result = tool.forward(cmd="python", args=["-c", "import os; print(os.getcwd())"])
        assert str(tmp_path) in result

    def test_build_shell_tools_accepts_a_cwd_argument(self, policy, tmp_path):
        # Previously there was no cwd parameter at all, so the subprocess ran
        # in whatever directory the server happened to be started from.
        import inspect

        sig = inspect.signature(build_shell_tools)
        assert "cwd" in sig.parameters


class TestArgsAreFlaggedByDesign:
    """The run tool is the sanctioned escape hatch, so its args MAY carry flags.

    A dash-guard on args was implemented during Phase 6 and reverted: it
    broke python -c, pytest -q and ruff, which is most of what the tool is
    for. git.py's module docstring is explicit that higher-level operations
    are deliberately NOT exposed as first-class tools and the agent "must use
    the shell tool directly and accept the allowlist".

    The allowlist on cmd is therefore the boundary for this tool. These tests
    pin that intent so the guard is not re-added as a "security fix" later.
    """

    def test_flagged_args_are_permitted(self, policy):
        tool = build_shell_tools(policy, tier_name="restricted")[0]
        result = tool.forward(cmd="python", args=["-c", "print('fine')"])
        assert "fine" in result

    def test_the_boundary_is_the_cmd_allowlist(self, policy):
        tool = build_shell_tools(policy, tier_name="restricted")[0]
        with pytest.raises(PermissionError):
            tool.forward(cmd="rm", args=["-rf", "/"])
