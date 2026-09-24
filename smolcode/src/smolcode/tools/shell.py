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
    # Phase 6 (6.3): hard ceiling on the model-supplied timeout, in seconds.
    # Before this existed, timeout went straight to subprocess.run, so a
    # model could pin a worker indefinitely. Bound per build.
    max_timeout = 600
    # Phase 6 (6.3): hard cap on captured output. 1 MiB is far above any
    # useful git/pytest transcript and far below anything that would exhaust
    # memory or blow the context window.
    # Written as a literal, not 1024 * 1024: smolagents' class-attribute
    # validator rejects any expression, treating computed values as
    # "complex attributes [that] should be defined in __init__".
    max_output_bytes = 1048576
    # Phase 1 (C1): the EXECUTING tool's effective tier, bound per build.
    # The destructive gate keys on this - never on the ambient session's
    # tier, which under the orchestrator describes a different agent.
    tier_name = ""

    def __init__(self):
        super().__init__()

    def forward(self, cmd: str, args, timeout=60) -> str:
        import os
        import subprocess

        # Phase 6 (6.3): clamp BEFORE anything else runs, and report the
        # effective value so a silently-shortened timeout cannot look like
        # the command simply finished.
        if timeout is None:
            timeout = 60
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            raise PermissionError("timeout must be an integer")
        if timeout <= 0:
            raise PermissionError("timeout must be positive")
        ceiling = int(self.max_timeout or 600)
        effective_timeout = timeout if timeout < ceiling else ceiling
        if effective_timeout != timeout:
            timeout = effective_timeout

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

        # Phase 6 NOTE: a dash-guard on args was TRIED HERE AND REVERTED.
        # It looked like a hole -- run("git", ["push", "--force"]) does walk
        # past the dash-guards on the first-class git_push tool -- but the run
        # tool is the SANCTIONED escape hatch by design: git.py's own module
        # docstring says the higher-level operations are deliberately not
        # exposed as tools and "the agent must use the shell tool directly and
        # accept the allowlist". A blanket dash-rejection breaks python -c,
        # pytest -q and ruff, so the allowlist on cmd is the boundary for this
        # tool, and the git-specific guards apply to the first-class git tools
        # only. Recorded here so it is not re-added as a security fix later.

        # M4.x / Phase 1 (C1): per-tool destructive gate. The gate fires
        # on is_destructive() REGARDLESS of the ambient session tier; the
        # tool's OWN (bound) tier decides prompt vs auto-deny.
        #
        # Phase 6 CORRECTION (R8): this comment used to claim the absolute
        # imports below were safe because "the parent package IS importable
        # on PYTHONPATH" in the remote container. That is FALSE and has been
        # measured, not assumed:
        #
        #   docker run --rm smolcode:restricted python -c "import smolcode.destructive"
        #   -> ModuleNotFoundError: No module named 'smolcode'
        #
        # The tier images install only jupyter/ipykernel/pytest/ruff, exactly
        # as sandbox_guard.py:181 already said. The consequence is not a silent
        # bypass: smolagents serialises this source into the container, so the
        # import below raises ImportError there and the run tool is BROKEN under
        # the docker executor. See docs/decisions/0041-*.md and
        # test_container_gate_phase6.py. Do not "fix" this by reverting to
        # relative imports -- there is no relative package in the container
        # either. ADR 0041 is the open decision.
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
        cap = int(self.max_output_bytes or 1048576)
        out_parts = []
        # A nested helper was tried and reverted: smolagents' MethodChecker
        # reports "Name '_clip' is undefined" for a def inside forward, so
        # the loop has to carry the logic inline. Same reason everything else
        # in this file is inlined.
        for label, text in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            if not text:
                continue
            raw = text.encode("utf-8", "replace")
            if len(raw) <= cap:
                out_parts.append(label + ":" + chr(10) + text.rstrip())
            else:
                kept = raw[:cap].decode("utf-8", "replace")
                out_parts.append(
                    label
                    + ":"
                    + chr(10)
                    + kept
                    + chr(10)
                    + "...[TRUNCATED "
                    + label
                    + ": "
                    + str(len(raw) - cap)
                    + " of "
                    + str(len(raw))
                    + " bytes omitted, cap="
                    + str(cap)
                    + "]"
                )
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


def build_shell_tools(command_policy, tier_name="", cwd=None, max_timeout=600):
    """Return the run Tool bound to allowlist, tier, cwd and timeout ceiling.

    Phase 6 (6.3): cwd and max_timeout are new. cwd was absent entirely, so the
    bound class attribute stayed "" and subprocess.run(cwd=None) made the
    subprocess inherit the SERVER process's working directory instead of the
    workspace -- the command was not bound to the workspace at all.
    """
    allowlist = "|".join(command_policy.allowlist) if command_policy.allowlist else ""
    cls = bind_attrs(
        _RunTool,
        {
            "allowlist": allowlist,
            "tier_name": str(tier_name or ""),
            "cwd": str(cwd) if cwd is not None else "",
            "max_timeout": int(max_timeout or 600),
        },
    )
    return [cls()]
