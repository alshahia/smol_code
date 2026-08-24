"""Tests for tools/shell.py (shell.run with CommandPolicy)."""

from __future__ import annotations

import sys

import pytest

from smolcode.tools import CommandPolicy
from smolcode.tools.shell import build_shell_tools


@pytest.fixture
def shell_tools():
    policy = CommandPolicy(("python", "git", "pytest"))
    return build_shell_tools(policy)


def test_build_shell_tools_returns_one(shell_tools):
    assert len(shell_tools) == 1
    assert shell_tools[0].name == "run"


def test_run_allowed_command(shell_tools):
    # Use python to print a marker string; verify capture works.
    result = shell_tools[0].forward(cmd="python", args=["-c", "print('marker')"])
    assert "stdout:" in result
    assert "marker" in result
    assert "returncode: 0" in result


def test_run_disallowed_command_rejected(shell_tools):
    with pytest.raises(PermissionError):
        shell_tools[0].forward(cmd="rm", args=["-rf", "/"])
    with pytest.raises(PermissionError):
        shell_tools[0].forward(cmd="curl", args=["http://example.com"])


def test_run_args_must_be_list_of_strings(shell_tools):
    with pytest.raises(PermissionError):
        shell_tools[0].forward(cmd="python", args="not a list")
    with pytest.raises(PermissionError):
        shell_tools[0].forward(cmd="python", args=[1, 2, 3])


def test_run_timeout_kills_long_process(shell_tools):
    # python -c with a sleep; use a very short timeout.
    if sys.platform == "win32":
        sleep_code = "import time; time.sleep(5)"
    else:
        sleep_code = "import time; time.sleep(5)"
    result = shell_tools[0].forward(cmd="python", args=["-c", sleep_code], timeout=1)
    assert "TIMEOUT" in result


def test_run_captures_stderr(shell_tools):
    result = shell_tools[0].forward(cmd="python", args=["-c", "import sys; sys.stderr.write('errline'); sys.exit(2)"])
    assert "stderr:" in result
    assert "errline" in result
    assert "returncode: 2" in result


def test_run_shell_metachars_passed_safely(shell_tools):
    # Even with ;, &, | in args, shell=False prevents interpretation.
    # The python -c receives the literal string and echoes it.
    result = shell_tools[0].forward(
        cmd="python",
        args=["-c", "import sys; print(sys.argv[1])", "echo ; ls & rm | cat"],
    )
    assert "echo ; ls & rm | cat" in result
    assert "returncode: 0" in result


def test_run_missing_executable_returns_not_found():
    policy = CommandPolicy(("definitely_not_a_real_command_xyz",))
    tools = build_shell_tools(policy)
    result = tools[0].forward(cmd="definitely_not_a_real_command_xyz", args=[])
    assert "NOT FOUND" in result or "returncode" in result


# --- M7 coverage-lift tests -----------------------------------------------


def test_run_rejects_empty_cmd(shell_tools):
    """An empty cmd string raises PermissionError before subprocess is invoked."""
    with pytest.raises(PermissionError, match="cmd is required"):
        shell_tools[0].forward(cmd="", args=["-c", "print(1)"], timeout=5)


def test_run_strips_windows_exe_suffix(shell_tools):
    """cmd="python.exe" should match the "python" allowlist entry."""
    if sys.platform != "win32":
        pytest.skip("windows-specific basename strip")
    result = shell_tools[0].forward(cmd="python.exe", args=["-c", "print(1)"], timeout=5)
    assert "returncode: 0" in result
