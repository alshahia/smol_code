"""Phase 6 section 6.1 (R8) -- the two-path destructive gate (ADR 0041 b).

run() and git_push() used to import smolcode.destructive and
smolcode.session unconditionally inside forward(). Under the docker executor
that import cannot resolve -- measured, not assumed:

    docker run --rm smolcode:restricted python -c "import smolcode.destructive"
    -> ModuleNotFoundError: No module named smolcode

so the gate raised ImportError and both tools were outright BROKEN in the
container, not merely unguarded. ADR 0041 option (b) makes the source
self-contained instead. The gate therefore has two paths:

  HOST PATH       smolcode imports; the real classifier decides and the
                  interactive confirm_callback still runs. This is what the
                  web approval modal drives, so it must keep working.
  CONTAINER PATH  the import raises; a classifier inlined into the tool body
                  decides against the host-bound destructive_policy and
                  fails CLOSED.

The duplication is the price of (b). TestGateDoesNotDrift is what pays it:
one case table through BOTH the real smolcode.destructive.is_destructive and
the tool forced down its container path, requiring identical verdicts.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import inspect
import tempfile
import textwrap

import pytest

from smolcode.destructive import is_destructive
from smolcode.tools import CommandPolicy
from smolcode.tools.git import _GitPushTool
from smolcode.tools.shell import _RunTool, build_shell_tools


# (cmd, args, is_destructive) -- the shared verdict table.
CASES = [
    ("python", ["-c", "print(1)"], False),
    ("pytest", ["-q"], False),
    ("ruff", ["check"], False),
    ("git", ["status"], False),
    ("git", ["diff"], False),
    ("git", ["push", "origin", "main"], True),
    ("git", ["reset", "--hard"], True),
    ("rm", ["file.txt"], False),
    ("rm", ["*.log"], True),
    ("rm", ["-rf", "/"], True),
    ("rmdir", ["somedir"], True),
    ("del", ["/f", "x"], True),
    ("ssh", ["host"], True),
    ("scp", ["a", "b"], True),
    ("rsync", ["-a", "/a", "/b"], True),
    ("docker", ["run"], True),
    ("kubectl", ["delete", "pod"], True),
    ("terraform", ["apply"], True),
    ("ansible", ["playbook"], True),
    # aws / gcloud / az are destructive for EVERY invocation, not only their
    # delete-ish subcommands: they sit in _DESTRUCTIVE_RUN_COMMANDS, so the
    # cloud-subcommand branch below it is unreachable for them. A first
    # draft of this table expected False here and the drift test caught it,
    # which is exactly what the test is for.
    ("aws", ["s3", "ls"], True),
    ("gcloud", ["compute", "instances", "delete"], True),
    ("az", ["group", "delete"], True),
    ("SSH", ["host"], True),
    ("rm.EXE", ["-rf", "x"], True),
]

ALLOWLIST = (
    "python",
    "pytest",
    "ruff",
    "git",
    "rm",
    "rmdir",
    "del",
    "ssh",
    "scp",
    "rsync",
    "docker",
    "kubectl",
    "terraform",
    "ansible",
    "aws",
    "gcloud",
    "az",
)


@contextlib.contextmanager
def no_smolcode():
    """Make importing smolcode fail, exactly as it does in the container.

    The inlined classifier only runs when that import raises, and on the host
    it always succeeds. A drift test that exercised the host path would be
    testing smolcode.destructive against itself, and would pass no matter how
    far the inlined copy had rotted -- which is the exact failure this file
    exists to prevent.

    An earlier version deleted the import lines from the source and exec-ed
    the result. That was fragile, and worse, it tested a MODIFIED copy of the
    tool rather than the tool. Patching __import__ exercises the real
    forward() body on the exact text that ships.
    """
    real = builtins.__import__

    def fake(name, *args, **kwargs):
        if name == "smolcode" or name.startswith("smolcode."):
            raise ImportError("No module named " + repr(name))
        return real(name, *args, **kwargs)

    builtins.__import__ = fake
    try:
        yield
    finally:
        builtins.__import__ = real


class TestGateDoesNotDrift:
    """The inlined classifier must agree with the host one, case for case."""

    def test_every_case_agrees(self):
        tool = _RunTool()
        tool.allowlist = "|".join(ALLOWLIST)
        # Run in a scratch dir: git diff at the repo root would print the
        # whole tree, including this file.
        tool.cwd = tempfile.gettempdir()

        with no_smolcode():
            for cmd, args, expected in CASES:
                kwargs = {"cmd": cmd, "args": args}
                assert is_destructive("run", kwargs) is expected, "host classifier changed for " + repr(kwargs)
                if expected:
                    # The inlined copy must see it as destructive and block it.
                    tool.destructive_policy = "deny"
                    with pytest.raises(PermissionError):
                        tool.forward(cmd=cmd, args=args)
                else:
                    # ...and must not block a harmless call.
                    #
                    # Assert on the GATE exception type, not on the output
                    # text. A substring check is wrong here: git diff in the
                    # repo root prints source files, one of which contains
                    # the literal gate message, so the test detected its own
                    # source. Whether rm even exists on Windows is likewise
                    # irrelevant to the gate.
                    try:
                        tool.forward(cmd=cmd, args=args)
                    except PermissionError as exc:
                        pytest.fail("gate blocked a non-destructive call " + repr(kwargs) + ": " + str(exc))

    def test_both_paths_agree_on_every_case(self):
        """The HOST path (real classifier) must reach the same verdicts."""
        policy = CommandPolicy(ALLOWLIST)
        tool = build_shell_tools(policy, tier_name="elevated", destructive_policy="deny")[0]
        for cmd, args, expected in CASES:
            if expected:
                with pytest.raises(PermissionError):
                    tool.forward(cmd=cmd, args=args)
            else:
                # Gate did not fire; see the note in the container-path test
                # for why the assertion is on the exception, not the text.
                try:
                    tool.forward(cmd=cmd, args=args)
                except PermissionError as exc:
                    pytest.fail("gate blocked a non-destructive call " + repr((cmd, args)) + ": " + str(exc))


class TestGateFailsClosed:
    def _tool(self, policy):
        return build_shell_tools(CommandPolicy(("git",)), tier_name="restricted", destructive_policy=policy)[0]

    def test_unknown_policy_blocks_rather_than_permits(self):
        tool = self._tool("unrecognised")
        with pytest.raises(PermissionError):
            tool.forward(cmd="git", args=["push", "origin", "main"])

    def test_default_policy_is_not_allow(self):
        policy = CommandPolicy(("git",))
        tool = build_shell_tools(policy)[0]
        assert getattr(tool, "destructive_policy", "") != "allow"
        with pytest.raises(PermissionError):
            tool.forward(cmd="git", args=["push", "origin", "main"])

    def test_container_path_blocks_git_push_without_allow(self):
        tool = _GitPushTool()
        tool.allowlist = "git"
        tool.destructive_policy = "deny"
        with no_smolcode(), pytest.raises(PermissionError):
            tool.forward(remote="origin", branch="")

    def test_container_path_permits_git_push_with_allow(self):
        tool = _GitPushTool()
        tool.allowlist = "git"
        tool.destructive_policy = "allow"
        with no_smolcode():
            out = tool.forward(remote="origin", branch="")
        assert "returncode:" in out

    def test_container_path_still_runs_ordinary_commands(self):
        # The whole point of the fix: a NON-destructive call must not be
        # collateral damage of the gate.
        tool = _RunTool()
        tool.allowlist = "|".join(ALLOWLIST)
        tool.destructive_policy = "deny"
        with no_smolcode():
            assert "returncode:" in tool.forward(cmd="python", args=["-c", "print(1)"])


class TestHostImportIsGuarded:
    """The smolcode import must exist but be OPTIONAL.

    An earlier cut of this change deleted the import outright and kept only
    the inlined classifier. That was wrong: the host path is where the web
    approval modal lives, and removing it took out a product feature while
    looking like a security improvement. The 8 approval tests in
    test_gate_context.py failed, which was the correct signal. The invariant
    is that the import is wrapped in try/except ImportError, NOT that it is
    absent.
    """

    def test_shell_import_is_optional(self):
        src = inspect.getsource(_RunTool.forward)
        assert "smolcode" in _imported_modules(src)
        assert "except ImportError:" in src
        assert "is_destructive = None" in src

    def test_git_push_import_is_optional(self):
        src = inspect.getsource(_GitPushTool.forward)
        assert "smolcode" in _imported_modules(src)
        assert "except ImportError:" in src
        assert "is_destructive = None" in src

    def test_both_paths_are_reachable(self):
        for cls in (_RunTool, _GitPushTool):
            src = inspect.getsource(cls.forward)
            assert "if is_destructive is not None" in src
            assert "elif is_destructive is None:" in src

    def test_the_gate_marker_is_present_in_both(self):
        assert "destructive_policy" in inspect.getsource(_RunTool.forward)
        assert "destructive_policy" in inspect.getsource(_GitPushTool.forward)


def _imported_modules(src):
    """Modules actually imported by src, via the AST.

    String matching is not good enough: these tools carry long comments
    QUOTING the old import lines and the ModuleNotFoundError they produced,
    so a substring check matches prose. Only the syntax tree counts.
    """
    mods = set()
    for node in ast.walk(ast.parse(textwrap.dedent(src))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods
