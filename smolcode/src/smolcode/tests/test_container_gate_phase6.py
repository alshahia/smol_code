"""Phase 6 section 6.1 (R8) -- does the destructive gate survive the
container boundary?

This file exists to turn an architectural question into a measurement.

The two comments in the codebase contradict each other:
  * sandbox_guard.py says smolcode is NOT installed inside the sandbox
    Jupyter kernel.
  * tools/shell.py and tools/git.py justify their absolute
    "from smolcode.destructive import ..." imports by claiming the parent
    package IS importable on PYTHONPATH in the remote container.

Only one can be true, and the tier Dockerfiles settle it: they pip install
only jupyter_kernel_gateway, jupyter_client, ipykernel, pytest and ruff.

These tests run a REAL container and assert what actually happens, so ADR
0041 can record a demonstrated fact instead of an assumption. They are
marked docker and skip cleanly when the daemon is unavailable.
"""

from __future__ import annotations

import shutil

import pytest

docker_required = pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not on PATH")


def _docker_available() -> bool:
    import subprocess

    try:
        r = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


needs_daemon = pytest.mark.skipif(not _docker_available(), reason="docker daemon not reachable")

RESTRICTED = "smolcode:restricted"


class TestSmolcodeIsNotInstalledInTheSandbox:
    """The premise of the whole decision. If smolcode WERE installed,
    tools/shell.py would be right and sandbox_guard.py would be wrong."""

    @docker_required
    @needs_daemon
    def test_importing_smolcode_inside_the_container_fails(self):
        import subprocess

        proc = subprocess.run(
            ["docker", "run", "--rm", RESTRICTED, "python", "-c", "import smolcode.destructive"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode != 0, (
            "smolcode IS importable inside smolcode:restricted -- the in-container "
            "gate would work and ADR 0041 option (c) applies."
        )
        assert "ModuleNotFoundError" in proc.stderr or "ImportError" in proc.stderr

    @docker_required
    @needs_daemon
    def test_the_shell_py_comment_is_known_false(self):
        """Pin the contradictory shell.py rationale as KNOWN-FALSE, so a future
        edit that quietly makes it true has to come update this test."""
        import inspect

        from smolcode.tools.shell import _RunTool

        src = inspect.getsource(_RunTool.forward)
        assert "IS importable on PYTHONPATH" in src, "the contradictory shell.py comment changed; re-check ADR 0041"


class TestTheGateCannotRunInContainerToday:
    @docker_required
    @needs_daemon
    def test_a_tool_body_importing_smolcode_fails_in_the_container(self):
        """Exactly what smolagents does when it serialises the run tool: the
        tool's source text is executed in the container, so the guard line
        raises ImportError there -- the gate is not merely bypassed, the tool
        becomes unusable under the docker executor."""
        import subprocess

        body = "from smolcode.destructive import is_destructive\nprint(is_destructive)"
        proc = subprocess.run(
            ["docker", "run", "--rm", RESTRICTED, "python", "-c", body],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode != 0
        assert "ModuleNotFoundError" in proc.stderr

    @docker_required
    @needs_daemon
    def test_restricted_image_has_git_so_the_push_vector_is_real(self):
        """The test above only matters if the image can actually run git --
        and it can, which is what makes the missing gate a real hole."""
        import subprocess

        proc = subprocess.run(
            ["docker", "run", "--rm", RESTRICTED, "sh", "-c", "git --version"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode == 0, proc.stderr
        assert "git version" in proc.stdout


class TestWorkspaceMountIsCurrentlyRwForEveryTier:
    """Evidence for section 6.3. agents/base.py hands every tier the same rw
    bind mount of the whole workspace, uploads dir included."""

    def test_base_py_mounts_the_whole_workspace_rw(self):
        import pathlib

        p = pathlib.Path(__file__).resolve().parents[1] / "agents" / "base.py"
        src = p.read_text(encoding="utf-8")
        q = chr(34)
        assert q + "mode" + q + ": " + q + "rw" + q in src
        # No :ro mount for uploads exists yet -- that is the 6.3 work.
        assert "uploads" not in src
