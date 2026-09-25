"""Phase 6 section 6.1 / R8 -- the inlined destructive gate (option b).

Why this file exists
--------------------
The run and git_push tools did their destructive gating by importing
smolcode.destructive and smolcode.session INSIDE forward(). Under the
docker executor that import cannot resolve -- measured, not assumed:

    docker run --rm smolcode:restricted python -c "import smolcode.destructive"
    -> ModuleNotFoundError: No module named 'smolcode'

so the gate was either dead or the tool was outright broken.

ADR 0041 option (b) is to make the tool source SELF-CONTAINED: the host
remains the sole authority for policy, and the container carries only a
mechanical enforcement copy of the classifier. The duplication is the
price, and TestGateDoesNotDrift is what pays it -- it runs a case table
through BOTH the real smolcode.destructive.is_destructive and the actual
tool, so the two cannot diverge silently.

The approval half
-----------------
A host-side SessionState.confirm_callback cannot be reached from inside
the container, so per-call interactive approval is NOT possible for an
in-container tool. The tool therefore enforces a bound, host-decided
policy and fails CLOSED when the host has not granted authority:

    destructive_policy == "allow" -> proceed (host pre-authorised)
    otherwise                      -> raise

This is a real behavioural limitation, not an oversight; it is recorded
in docs/decisions/0041 and in the product docs.
"""

from __future__ import annotations

import pytest

from smolcode.destructive import is_destructive
from smolcode.tools import CommandPolicy
from smolcode.tools.shell import build_shell_tools


# Cases exercised through BOTH implementations. (cmd, args) plus whether
# smolcode.destructive considers the call destructive.
CASES = [
    ("python", ["-c", "print(1)"], False),
    ("pytest", ["-q"], False),
    ("ruff", ["check"], False),
    ("git", ["status"], False),
    ("git", ["push", "origin", "main"], True),
    ("git", ["reset", "--hard"], True),
    ("git", ["diff"], False),
    ("rm", ["-rf", "/"], True),
    ("rm", ["file.txt"], False),
    ("rm", ["*.log"], True),
    ("rmdir", ["somedir"], True),
    ("del", ["/f", "x"], True),
    ("ssh", ["host"], True),
    ("scp", ["a", "b"], True),
    ("rsync", ["-a", "/a", "/b"], True),
    ("docker", ["run"], True),
    ("kubectl", ["delete", "pod"], True),
    ("terraform", ["apply"], True),
    ("ansible", ["playbook"], True),
    # NOTE: aws / gcloud / az / docker / kubectl etc. are destructive for
    # EVERY invocation, not only their delete-ish subcommands -- they are in
    # _DESTRUCTIVE_RUN_COMMANDS, so the cloud-subcommand branch below it is
    # unreachable for them. An earlier version of this table expected False
    # here and the drift test caught it, which is the point of the test.
    ("aws", ["s3", "rm"], True),
    ("aws", ["ec2", "describe-instances"], True),
    ("gcloud", ["compute", "instances", "delete"], True),
    ("az", ["group", "delete"], True),
    ("SSH", ["host"], True),
    ("rm.EXE", ["-rf", "x"], True),
]


class TestGateDoesNotDrift:
    """The inlined classifier must agree with the host one, case for case."""

    def test_every_case_agrees(self):
        policy = CommandPolicy(
            (
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
        )
        # policy "allow" means a destructive call PROCEEDS. So with
        # allow=True the tool must succeed exactly when is_destructive is
        # False, and with allow=False it must raise exactly when it is True.
        allow_tool = build_shell_tools(policy, tier_name="elevated", destructive_policy="allow")[0]
        deny_tool = build_shell_tools(policy, tier_name="restricted", destructive_policy="deny")[0]

        for cmd, args, expected_destructive in CASES:
            kwargs = {"cmd": cmd, "args": args}
            assert is_destructive("run", kwargs) is expected_destructive, (
                "the host classifier itself changed for " + repr(kwargs)
            )
            if expected_destructive:
                with pytest.raises(PermissionError):
                    deny_tool.forward(cmd=cmd, args=args)
            else:
                # Non-destructive: must NOT be blocked by the gate.
                allow_tool.forward(cmd=cmd, args=args)

    def test_deny_blocks_and_allow_permits_the_same_call(self):
        policy = CommandPolicy(("git",))
        deny = build_shell_tools(policy, tier_name="restricted", destructive_policy="deny")[0]
        allow = build_shell_tools(policy, tier_name="elevated", destructive_policy="allow")[0]
        with pytest.raises(PermissionError):
            deny.forward(cmd="git", args=["push", "origin", "main"])
        # "origin" is not a configured remote here, so git itself will
        # complain -- but it must COMPLAIN, not be blocked by the gate.
        out = allow.forward(cmd="git", args=["push", "origin", "main"])
        assert "returncode:" in out


class TestGateFailsClosed:
    def test_unknown_policy_blocks_rather_than_permits(self):
        # A tool built without an explicit policy must not silently allow
        # destructive work. Anything that is not exactly "allow" blocks.
        policy = CommandPolicy(("git",))
        tool = build_shell_tools(policy, destructive_policy="unrecognised")[0]
        with pytest.raises(PermissionError):
            tool.forward(cmd="git", args=["push", "origin", "main"])

    def test_default_policy_is_not_allow(self):
        policy = CommandPolicy(("git",))
        tool = build_shell_tools(policy)[0]
        assert getattr(tool, "destructive_policy", "") != "allow"
        with pytest.raises(PermissionError):
            tool.forward(cmd="git", args=["push", "origin", "main"])


def _imported_modules(src):
    """Modules actually imported by src, via the AST.

    String matching is not good enough: these tools carry long comments
    QUOTING the old import lines and the ModuleNotFoundError they produced,
    so 'import smolcode' appears in the prose. Only the syntax tree counts.
    """
    import ast
    import textwrap

    mods = set()
    for node in ast.walk(ast.parse(textwrap.dedent(src))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


class TestNoHostImportsRemainInForward:
    """The whole point: the serialised source must not import smolcode."""

    def test_shell_forward_has_no_smolcode_import(self):
        import inspect

        from smolcode.tools.shell import _RunTool

        assert "smolcode" not in _imported_modules(inspect.getsource(_RunTool.forward))

    def test_git_push_forward_has_no_smolcode_import(self):
        import inspect

        from smolcode.tools.git import _GitPushTool

        assert "smolcode" not in _imported_modules(inspect.getsource(_GitPushTool.forward))

    def test_the_gate_marker_is_present_in_both(self):
        import inspect

        from smolcode.tools.git import _GitPushTool
        from smolcode.tools.shell import _RunTool

        assert "destructive_policy" in inspect.getsource(_RunTool.forward)
        assert "destructive_policy" in inspect.getsource(_GitPushTool.forward)
