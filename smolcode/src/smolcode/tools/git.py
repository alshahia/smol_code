"""Git tools (M2).

Thin wrappers around subprocess.run that hard-code the subcommand. Per
docs/architecture.md 5.3: higher-level operations (rebase, reset --hard,
push --force, etc.) are NOT exposed; the agent must use the shell tool
directly and accept the allowlist.

Each tool is a Tool subclass. Allowlist and cwd are CLASS attributes
set by ``build_git_tools`` via ``bind_attrs``. The basename check +
subprocess invocation are INLINE in each forward() so the source is
self-contained for the Docker executor.

The allowlist is encoded as a pipe-separated string because
``validate_tool_attributes`` rejects list/tuple class attributes.
"""

from __future__ import annotations

from smolagents import Tool

from ._bind import bind_attrs


def _check_basename_string(self_allowlist, cmd):
    """Inline-friendly basename check.

    Kept as a module-level helper purely for unit tests; the same
    logic is inlined inside each forward() so it survives Docker
    serialisation (MethodChecker rejects sibling-class method
    references and module-level helpers when serialised SimpleTool
    source is inspected).
    """
    import os

    if not cmd:
        raise PermissionError("cmd is required")
    basename = os.path.basename(cmd)
    if os.name == "nt":
        lower = basename.lower()
        for ext in (".exe", ".bat", ".cmd", ".com"):
            if lower.endswith(ext):
                basename = basename[: -len(ext)]
                break
    allowed = [s for s in self_allowlist.split("|") if s]
    if basename not in allowed:
        raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
    return basename


class _GitStatusTool(Tool):
    name = "git_status"
    description = "Show the working tree status (git status)."
    inputs = {}
    output_type = "string"
    allowlist = ""  # pipe-separated, overridden per-build
    cwd = ""  # overridden per-build

    def __init__(self):
        super().__init__()

    def forward(self) -> str:
        import os
        import subprocess

        cmd_args = ["git", "status"]
        for a in cmd_args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        first = cmd_args[0]
        if not first:
            raise PermissionError("cmd is required")
        basename = os.path.basename(first)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
        try:
            proc = subprocess.run(
                list(cmd_args),
                shell=False,
                check=False,
                timeout=60,
                capture_output=True,
                text=True,
                cwd=self.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(60) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


class _GitDiffTool(Tool):
    name = "git_diff"
    description = "Show changes (git diff). Pass staged=True for --staged."
    inputs = {
        "staged": {"type": "boolean", "description": "If True, pass --staged."},
        "extra_args": {"type": "array", "description": "Additional positional args."},
    }
    output_type = "string"
    allowlist = ""
    cwd = ""

    def __init__(self):
        super().__init__()

    def forward(self, staged: bool, extra_args) -> str:
        import os
        import subprocess

        cmd_args = ["git", "diff"]
        if staged:
            cmd_args.append("--staged")
        if extra_args:
            # extra_args is spliced straight into argv, so "--output=<path>"
            # turns "show me a diff" into "write a file wherever the model
            # likes". Allowlisting the read-only options is the safe shape
            # here -- a blanket dash-rejection would break the legitimate
            # --stat / -U5 that this input exists to allow.
            allowed_extra = {
                "--stat",
                "--shortstat",
                "--numstat",
                "--name-only",
                "--name-status",
                "--raw",
                "-p",
                "--patch",
                "-w",
                "--ignore-all-space",
                "--ignore-space-change",
            }
            for a in extra_args:
                if not isinstance(a, str):
                    raise PermissionError("each arg must be a string")
                unified = (a.startswith("-U") and a[2:].isdigit()) or (a.startswith("--unified=") and a[10:].isdigit())
                if a not in allowed_extra and not unified:
                    raise PermissionError("refusing diff option that looks like a git flag: " + repr(a))
            cmd_args.extend(extra_args)
        for a in cmd_args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        first = cmd_args[0]
        if not first:
            raise PermissionError("cmd is required")
        basename = os.path.basename(first)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
        try:
            proc = subprocess.run(
                list(cmd_args),
                shell=False,
                check=False,
                timeout=60,
                capture_output=True,
                text=True,
                cwd=self.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(60) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


class _GitAddTool(Tool):
    name = "git_add"
    description = "Stage file contents for the next commit (git add)."
    inputs = {"paths": {"type": "array", "description": "List of workspace-relative paths."}}
    output_type = "string"
    allowlist = ""
    cwd = ""

    def __init__(self):
        super().__init__()

    def forward(self, paths) -> str:
        import os
        import subprocess

        if not paths or not isinstance(paths, list):
            raise PermissionError("paths must be a non-empty list")
        for p in paths:
            if isinstance(p, str) and p.startswith("-"):
                raise PermissionError("refusing path that looks like a git flag: " + repr(p))
        # "--" ends option parsing, so a file genuinely named "-foo" still
        # works while "--all" / "-A" cannot be smuggled in as an operand.
        cmd_args = ["git", "add", "--", *paths]
        for a in cmd_args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        first = cmd_args[0]
        if not first:
            raise PermissionError("cmd is required")
        basename = os.path.basename(first)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
        try:
            proc = subprocess.run(
                list(cmd_args),
                shell=False,
                check=False,
                timeout=60,
                capture_output=True,
                text=True,
                cwd=self.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(60) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


class _GitCommitTool(Tool):
    name = "git_commit"
    description = "Record changes to the repository (git commit -m)."
    inputs = {"message": {"type": "string", "description": "Commit message."}}
    output_type = "string"
    allowlist = ""
    cwd = ""

    def __init__(self):
        super().__init__()

    def forward(self, message: str) -> str:
        import os
        import subprocess

        if not message:
            raise PermissionError("message must be a non-empty string")
        if message.startswith("-"):
            # "-m" takes the next argv as a VALUE, so this is belt-and-braces
            # rather than a live hole -- but it keeps the rule uniform across
            # every tool that accepts model text, which is what the
            # equivalence guard in the test suite asserts.
            raise PermissionError("refusing message that looks like a git flag: " + repr(message))
        cmd_args = ["git", "commit", "-m", message]
        for a in cmd_args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        first = cmd_args[0]
        if not first:
            raise PermissionError("cmd is required")
        basename = os.path.basename(first)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
        try:
            proc = subprocess.run(
                list(cmd_args),
                shell=False,
                check=False,
                timeout=60,
                capture_output=True,
                text=True,
                cwd=self.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(60) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


class _GitLogTool(Tool):
    name = "git_log"
    description = "Show commit logs (git log [-n N])."
    inputs = {"max_count": {"type": "integer", "description": "Limit entries (-n).", "nullable": True}}
    output_type = "string"
    allowlist = ""
    cwd = ""

    def __init__(self):
        super().__init__()

    def forward(self, max_count: int = None) -> str:
        import os
        import subprocess

        cmd_args = ["git", "log"]
        if max_count is None:
            pass
        elif isinstance(max_count, int) and not isinstance(max_count, bool) and 1 <= max_count <= 1000:
            cmd_args.extend(["-n", str(int(max_count))])
        else:
            raise PermissionError("max_count must be int between 1 and 1000")
        for a in cmd_args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        first = cmd_args[0]
        if not first:
            raise PermissionError("cmd is required")
        basename = os.path.basename(first)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
        try:
            proc = subprocess.run(
                list(cmd_args),
                shell=False,
                check=False,
                timeout=60,
                capture_output=True,
                text=True,
                cwd=self.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(60) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


class _GitPushTool(Tool):
    name = "git_push"
    description = "Update remote refs (git push <remote> [<branch>])."
    inputs = {
        "remote": {"type": "string", "description": "Remote name."},
        "branch": {"type": "string", "description": "Branch name (empty for default).", "nullable": True},
    }
    output_type = "string"
    allowlist = ""
    cwd = ""
    # Phase 1 (C1): the EXECUTING tool's effective tier (bound per build).
    tier_name = ""

    def __init__(self):
        super().__init__()

    def forward(self, remote: str, branch: str = "") -> str:
        import os
        import subprocess

        # Validate BEFORE the destructive gate. The gate denies every call
        # in a session with no confirm callback, so a guard placed after it
        # is unreachable in exactly the configuration it is meant to cover
        # -- and rejecting malformed input should never cost the user a
        # prompt. No "--" is valid for git push (it takes no pathspec), so
        # this is dash-rejection only: --mirror / --force / --delete are
        # flags, and a positional operand is what the caller meant.
        if not remote:
            raise PermissionError("remote is required")
        if remote.startswith("-"):
            raise PermissionError("refusing remote that looks like a git flag: " + repr(remote))
        if branch and branch.startswith("-"):
            raise PermissionError("refusing branch that looks like a git flag: " + repr(branch))

        from smolcode.destructive import destructive_reason, is_destructive

        # M4.x / Phase 1 (C1): per-tool destructive gate. Fires on
        # is_destructive() regardless of the ambient session tier; the
        # tool's OWN bound tier decides prompt vs auto-deny.
        #
        # Phase 6 CORRECTION (R8): the comment here used to claim the package
        # IS importable on PYTHONPATH inside the remote Docker container. It is
        # not -- see the measured evidence and the full note in tools/shell.py,
        # and docs/decisions/0041-*.md. Under the docker executor this import
        # raises ImportError and git_push does not work.
        from smolcode.session import current_session

        kwargs = {"remote": remote, "branch": branch}
        if is_destructive("git_push", kwargs):
            sess = current_session()
            if self.tier_name == "restricted":
                raise PermissionError(
                    "destructive git_push denied at restricted tier: " + (destructive_reason("git_push", kwargs) or "")
                )
            if not sess.auto_approve_destructive:
                summary = destructive_reason("git_push", kwargs) or ""
                if sess.confirm_callback is None:
                    raise PermissionError("destructive git_push denied: no confirm session")
                decision = sess.confirm_callback("git_push", kwargs, summary)
                if decision.auto_approve_now:
                    sess.auto_approve_destructive = True
                if decision.auto_approve_off:
                    sess.auto_approve_destructive = False
                if not decision.approved:
                    raise PermissionError("destructive git_push denied: " + decision.reason)

        cmd_args = ["git", "push", remote]
        if branch:
            cmd_args.append(branch)
        for a in cmd_args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        first = cmd_args[0]
        if not first:
            raise PermissionError("cmd is required")
        basename = os.path.basename(first)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
        try:
            proc = subprocess.run(
                list(cmd_args),
                shell=False,
                check=False,
                timeout=120,
                capture_output=True,
                text=True,
                cwd=self.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(120) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


class _GitCloneTool(Tool):
    name = "git_clone"
    description = "Clone a repository (git clone)."
    inputs = {
        "url": {"type": "string", "description": "Repository URL."},
        "directory": {"type": "string", "description": "Optional target dir.", "nullable": True},
    }
    output_type = "string"
    allowlist = ""
    cwd = ""

    def __init__(self):
        super().__init__()

    def forward(self, url: str, directory: str = "") -> str:
        import os
        import subprocess

        if not url:
            raise PermissionError("url is required")
        # Phase 6 (H2/R10). This is the sharpest edge of the set: git treats
        # a clone URL as a transport spec, not just a location, and several
        # forms of that spec execute a program the caller chooses --
        #   ext::sh -c ...        -> runs a shell command
        #   --upload-pack=<cmd>   -> runs <cmd> on the "remote"
        #   -c core.sshCommand=... -> rewrites how git shells out
        # So a leading dash is refused AND the scheme is allowlisted.
        if url.startswith("-"):
            raise PermissionError("refusing url that looks like a git flag: " + repr(url))
        scheme = url.split("://", 1)[0].lower() if "://" in url else ""
        if scheme and scheme not in ("https", "http", "ssh", "git", "file"):
            raise PermissionError("refusing clone url with scheme " + repr(scheme) + ": not in allowlist")
        if not scheme and ":" in url.split("/", 1)[0]:
            # scp-like "user@host:path" is legitimate; "ext::..." is not.
            head = url.split("/", 1)[0]
            if not head.endswith(":") and ":" in head:
                raise PermissionError("refusing clone url that looks like a git flag: " + repr(url))
        if directory:
            if directory.startswith("-"):
                raise PermissionError("refusing directory that looks like a git flag: " + repr(directory))
            # Contain the clone target: otherwise the model can write a repo
            # anywhere the server process can reach.
            import os as _os

            base = _os.path.abspath(self.cwd) if self.cwd else _os.path.abspath(".")
            dest = _os.path.abspath(_os.path.join(base, directory))
            if dest != base and not dest.startswith(base + _os.sep):
                raise PermissionError("clone directory escapes the workspace: " + repr(directory))
            cmd_args = ["git", "clone", "--", url, directory]
        else:
            cmd_args = ["git", "clone", "--", url]
        for a in cmd_args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        first = cmd_args[0]
        if not first:
            raise PermissionError("cmd is required")
        basename = os.path.basename(first)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
        try:
            proc = subprocess.run(
                list(cmd_args),
                shell=False,
                check=False,
                timeout=600,
                capture_output=True,
                text=True,
                cwd=self.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(600) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


class _GitFetchTool(Tool):
    name = "git_fetch"
    description = "Download objects/refs from another repository (git fetch)."
    inputs = {"remote": {"type": "string", "description": "Remote name."}}
    output_type = "string"
    allowlist = ""
    cwd = ""

    def __init__(self):
        super().__init__()

    def forward(self, remote: str) -> str:
        import os
        import subprocess

        if not remote:
            raise PermissionError("remote is required")
        if remote.startswith("-"):
            raise PermissionError("refusing remote that looks like a git flag: " + repr(remote))
        cmd_args = ["git", "fetch", remote]
        for a in cmd_args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        first = cmd_args[0]
        if not first:
            raise PermissionError("cmd is required")
        basename = os.path.basename(first)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
        try:
            proc = subprocess.run(
                list(cmd_args),
                shell=False,
                check=False,
                timeout=300,
                capture_output=True,
                text=True,
                cwd=self.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(300) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


class _GitCheckoutTool(Tool):
    name = "git_checkout"
    description = "Switch branches or restore working tree files (git checkout)."
    inputs = {
        "target": {"type": "string", "description": "Branch / commit / path."},
        "create": {"type": "boolean", "description": "If True, pass -b."},
    }
    output_type = "string"
    allowlist = ""
    cwd = ""

    def __init__(self):
        super().__init__()

    def forward(self, target: str, create: bool) -> str:
        import os
        import subprocess

        if not target:
            raise PermissionError("target is required")
        if target.startswith("-"):
            # --orphan / --detach / a stray -b would otherwise be read as the
            # mode rather than the thing to check out.
            raise PermissionError("refusing target that looks like a git flag: " + repr(target))
        cmd_args = ["git", "checkout"]
        if create:
            # With -b the target is the NEW BRANCH NAME, and inserting "--"
            # there would make git read it as the start-point instead, so
            # this branch relies on the dash-rejection above alone.
            cmd_args.append("-b")
            cmd_args.append(target)
        else:
            cmd_args.extend(["--", target])
        for a in cmd_args:
            if not isinstance(a, str):
                raise PermissionError("each arg must be a string")
        first = cmd_args[0]
        if not first:
            raise PermissionError("cmd is required")
        basename = os.path.basename(first)
        if os.name == "nt":
            lower = basename.lower()
            for ext in (".exe", ".bat", ".cmd", ".com"):
                if lower.endswith(ext):
                    basename = basename[: -len(ext)]
                    break
        allowed = [s for s in self.allowlist.split("|") if s]
        if basename not in allowed:
            raise PermissionError("command " + repr(basename) + " not in allowlist " + repr(allowed))
        try:
            proc = subprocess.run(
                list(cmd_args),
                shell=False,
                check=False,
                timeout=60,
                capture_output=True,
                text=True,
                cwd=self.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            return "TIMEOUT after " + str(60) + "s: " + repr(str(e))
        except FileNotFoundError as e:
            return "NOT FOUND: " + repr(str(e))
        out_parts = []
        if proc.stdout:
            out_parts.append("stdout:" + chr(10) + proc.stdout.rstrip())
        if proc.stderr:
            out_parts.append("stderr:" + chr(10) + proc.stderr.rstrip())
        out_parts.append("returncode: " + str(proc.returncode))
        return chr(10).join(out_parts)


_GIT_TOOL_CLASSES = [
    _GitStatusTool,
    _GitDiffTool,
    _GitAddTool,
    _GitCommitTool,
    _GitLogTool,
    _GitPushTool,
    _GitCloneTool,
    _GitFetchTool,
    _GitCheckoutTool,
]


def build_git_tools(command_policy, cwd=None, tier_name=""):
    """Build git Tool wrappers, bound to command_policy.allowlist, cwd + tier."""
    if command_policy is None:
        raise PermissionError("command_policy is required")
    allowlist = "|".join(command_policy.allowlist) if command_policy.allowlist else ""
    cwd_str = str(cwd) if cwd is not None else ""
    tools = []
    for cls in _GIT_TOOL_CLASSES:
        bound = bind_attrs(cls, {"allowlist": allowlist, "cwd": cwd_str, "tier_name": str(tier_name or "")})
        tools.append(bound())
    return tools
