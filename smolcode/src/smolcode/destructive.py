"""Per-tool destructive-op classification (M4.x, decision 0007).

A tool call is "destructive" inside the full_access tier if it
matches one of the patterns in DESTRUCTIVE_PATTERNS. The CLI hooks
this into a confirmation prompt that the user can auto-approve
once, or for the rest of the run, or never.

Scope (v1):
  - git_push: always destructive (pushes code to a remote).
  - git checkout / reset via run: heuristic on extra_args.
  - run with rm / del / rmdir and recursive flags.
  - run with ssh / scp / rsync / kubectl / docker / terraform /
    ansible / aws / gcloud / az: always destructive for full_access
    (the "external surface" tools).
  - run with aws/gcloud/az + destructive subcommand (destroy/delete/
    rm/drop): heuristic on the joined command line.

NOT destructive in v1:
  - read_file / write_file / list_dir (workspace writes are
    sandboxed; no host fs damage).
  - git_status / git_diff / git_log / git_add / git_commit /
    git_clone / git_fetch / git_checkout (without --).
  - run with python / pytest / ruff / make / pip / npm / node / jq
    (build/test/lint; safe).
  - All MCP tools (already tier-filtered; don't have host-side
    power beyond the MCP server's own scope).

Heuristic philosophy: narrow is safer than wide. False negatives
("should have prompted but didn't") are recoverable (the user
undoes with `git stash pop`); false positives ("prompted but
shouldn't have") are annoying (user types y a lot). We err on the
side of false positives.
"""

from __future__ import annotations


# --- The pattern table -----------------------------------------------------


# Tools that are unconditionally destructive for full_access.
_ALWAYS_DESTRUCTIVE_TOOLS = frozenset(
    {
        "git_push",
    }
)


# `run` invocations that are destructive.
# The cmd list matches the full_access tier's command allowlist in
# config.py (ssh, scp, rsync, docker, kubectl, terraform, ansible,
# aws, gcloud, az). Anything in this set is destructive for
# full_access; for elevated/restricted, run() is not gated by this
# module (the tier's command allowlist is the only enforcement).
_DESTRUCTIVE_RUN_COMMANDS = frozenset(
    {
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
    }
)

# Subcommands of aws / gcloud / az that are explicitly destructive
# (delete / destroy / drop). Other subcommands (describe, list, get)
# are NOT destructive.
_DESTRUCTIVE_CLOUD_SUBCOMMANDS = frozenset(
    {
        "destroy",
        "delete",
        "rm",
        "drop",
        "terminate",
    }
)

# Commands that are unconditionally destructive when invoked (with
# recursive / force flags or always).
_DESTRUCTIVE_FS_COMMANDS = frozenset(
    {
        "rm",
        "rmdir",
        "del",
        "rd",
    }
)

# Flags that make a fs command definitely destructive even for a
# single file.
_DESTRUCTIVE_FS_FLAGS = frozenset(
    {
        "-rf",
        "-fr",
        "-r",
        "-f",
        "/q",
        "/s",
        "/f",
        "--force",
        "--recursive",
    }
)


# --- The public classifier -------------------------------------------------


def is_destructive(tool_name, kwargs):
    """Return True iff the given tool call is destructive.

    Args:
        tool_name: name of the tool (e.g. "git_push", "run").
        kwargs:    kwargs dict the tool was called with.

    Returns:
        bool. False on any error (a non-deterministic heuristic is
        worse than no heuristic; we prefer to over-prompt than to
        under-prompt, so this function is conservative: anything it
        can't classify definitively, it does NOT mark destructive.
    """
    if not isinstance(tool_name, str) or not isinstance(kwargs, dict):
        return False
    if tool_name in _ALWAYS_DESTRUCTIVE_TOOLS:
        return True
    if tool_name == "run":
        return _is_destructive_run(kwargs)
    if tool_name in ("git_reset", "git_checkout"):
        return _is_destructive_git_via_run(kwargs)
    return False


def destructive_reason(tool_name, kwargs):
    """Human-readable explanation of why the call is destructive.

    Returns None if not destructive. Used by the CLI to format
    the confirmation prompt.
    """
    if not is_destructive(tool_name, kwargs):
        return None
    if tool_name == "git_push":
        remote = kwargs.get("remote", "<unset>")
        branch = kwargs.get("branch") or "<current>"
        return "git_push(remote=" + repr(remote) + ", branch=" + repr(branch) + ")"
    if tool_name == "run":
        cmd = kwargs.get("cmd", "<unset>")
        args = kwargs.get("args") or []
        joined = " ".join([cmd] + list(args))
        return "run(" + joined + ")"
    if tool_name in ("git_reset", "git_checkout"):
        target = kwargs.get("target", "<unset>")
        return tool_name + "(target=" + repr(target) + ", flags=destructive)"
    return tool_name + "(...)"


# --- Heuristics (private) --------------------------------------------------


def _is_destructive_run(kwargs):
    """Return True iff a run(cmd=..., args=...) call is destructive."""
    cmd = kwargs.get("cmd")
    if not isinstance(cmd, str):
        return False
    # Strip Windows-style suffixes (.exe / .bat / .cmd / .com) ONLY if
    # they appear at the end as a literal suffix. ``str.rstrip(chars)``
    # treats the argument as a *set* of characters, not a suffix, which
    # would otherwise eat unrelated letters ("rsync".rstrip(".cmd")
    # returns "rsyn" because ``c`` is in the set {".","c","m","d"}).
    cmd_lower = cmd.lower()
    for ext in (".exe", ".bat", ".cmd", ".com"):
        if cmd_lower.endswith(ext):
            cmd_lower = cmd_lower[: -len(ext)]
            break
    cmd_norm = cmd_lower
    args = kwargs.get("args") or []
    if not isinstance(args, (list, tuple)):
        return False
    args_str = [str(a) for a in args]

    # Always-destructive external-surface commands.
    if cmd_norm in _DESTRUCTIVE_RUN_COMMANDS:
        return True

    # Filesystem commands: destructive when a recursive / force flag is
    # present OR when target is an absolute / rooted path.
    if cmd_norm in _DESTRUCTIVE_FS_COMMANDS:
        # ``rmdir`` removes a directory; treat it as destructive even
        # without a flag (it's non-recursive by definition, but still
        # deletes data the user might care about).
        if cmd_norm == "rmdir":
            return True
        for a in args_str:
            if a.lower() in _DESTRUCTIVE_FS_FLAGS:
                return True
            # "rm -rf <anything>" is destructive even without the flag
            # spelled out (the recursive glob is enough).
            if cmd_norm in ("rm", "del") and ("*" in a or "?" in a):
                return True
        # rm against a path outside the workspace would also be
        # destructive; we don't have workspace context here, so we
        # only flag the obvious cases above.
        return False

    # Cloud CLIs: destructive only when the second arg matches the
    # destructive subcommand set.
    if cmd_norm in ("aws", "gcloud", "az") and args_str:
        return args_str[0].lower() in _DESTRUCTIVE_CLOUD_SUBCOMMANDS

    return False


def _is_destructive_git_via_run(kwargs):
    """git_reset / git_checkout are destructive when extra_args contain --hard."""
    extra = kwargs.get("extra_args") or []
    if not isinstance(extra, (list, tuple)):
        return False
    for a in extra:
        s = str(a).lower()
        if s == "--hard" or s.startswith("--hard=") or s == "-f":
            return True
    return False


__all__ = ["destructive_reason", "is_destructive"]
