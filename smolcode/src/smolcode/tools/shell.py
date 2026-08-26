"""Shell tool (M2).

Host-side ``run(cmd, args, timeout)`` that delegates to
``subprocess.run`` with ``shell=False``. The basename of ``cmd`` must
be in the tier command allowlist. Per docs/architecture.md 5.3 and
docs/security.md 6.

Tool state (allowlist, cwd) is a CLASS attribute so it survives
smolagents' Docker serialisation round-trip. ``bind_attrs`` in
``build_shell_tools`` generates a per-build subclass with the state
baked in. The allowlist is encoded as a pipe-separated string
(``"python|git|pytest"``) because ``validate_tool_attributes``
rejects list/tuple class attributes (ast.Load contexts in
``ast.walk`` cause them to be flagged as "complex").

Policy logic is INLINED in ``forward()`` so the source is
self-contained for the Docker executor.
"""

from __future__ import annotations

from smolagents import Tool

from ._bind import bind_attrs


class _RunTool(Tool):
    name = "run"
    description = (
        "Run an allowlisted subprocess and return a formatted result. Args: cmd (str), args (list), timeout (int)."
    )
    inputs = {
        "cmd": {"type": "string", "description": "Command basename (e.g. git, python)."},
        "args": {"type": "array", "description": "List of argument strings."},
        "timeout": {"type": "integer", "description": "Max seconds to wait.", "nullable": True},
    }
    output_type = "string"
    allowlist = ""  # pipe-separated, overridden per-build by build_shell_tools
    cwd = ""  # overridden per-build
    # Phase 1 (C1): the EXECUTING tool's effective tier, bound per build.
    # The destructive gate keys on this - never on the ambient session's
    # tier, which under the orchestrator describes a different agent.
    tier_name = ""

    def __init__(self):
        super().__init__()

    def forward(self, cmd: str, args, timeout=60) -> str:
        import os
        import subprocess

        if not isinstance(args, list):
            raise PermissionError("args must be a list of strings")
        for a in args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        # Inlined basename allowlist check + Windows suffix strip.
        if not cmd:
            raise PermissionError("cmd is required")
        basename = os.path.basename(cmd)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        # allowlist is a pipe-separated string; split on "|".
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))

        # M4.x / Phase 1 (C1): per-tool destructive gate. The gate fires
        # on is_destructive() REGARDLESS of the ambient session tier; the
        # tool's OWN (bound) tier decides prompt vs auto-deny. Imports are
        # absolute (not relative) so the emitted source survives
        # smolagents' instance_to_source hoist into the remote Docker
        # container, where the parent package IS importable on PYTHONPATH.
        from smolcode.destructive import destructive_reason, is_destructive
        from smolcode.session import current_session

        rk = {"cmd": cmd, "args": list(args)}
        if is_destructive("run", rk):
            sess = current_session()
            if self.tier_name == "restricted":
                # Restricted may auto-deny instead of prompting: its
                # allowlist has no legitimate destructive surface.
                raise PermissionError(
                    "destructive run denied at restricted tier: " + (destructive_reason("run", rk) or "")
                )
            if not sess.auto_approve_destructive:
                summary = destructive_reason("run", rk) or ""
                if sess.confirm_callback is None:
                    raise PermissionError("destructive run denied: no confirm session")
                decision = sess.confirm_callback("run", rk, summary)
                if decision.auto_approve_now:
                    sess.auto_approve_destructive = True
                if decision.auto_approve_off:
                    sess.auto_approve_destructive = False
                if not decision.approved:
                    raise PermissionError("destructive run denied: " + decision.reason)

        try:
            proc = subprocess.run(
                [cmd, *args],
                shell=False,
                check=False,
                timeout=timeout,
                cwd=self.cwd or None,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(timeout) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


def build_shell_tools(command_policy, tier_name=""):
    """Return the run Tool bound to command_policy.allowlist + tier name."""
    allowlist = "|".join(command_policy.allowlist) if command_policy.allowlist else ""
    cls = bind_attrs(_RunTool, {"allowlist": allowlist, "tier_name": str(tier_name or "")})
    return [cls()]
