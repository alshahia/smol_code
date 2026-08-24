"""Per-run + per-tool confirmation prompts (M4 + M4.x, decisions 0006 + 0007).

Two prompts live in this module:

  1. confirm_full_access() / prompt_confirmation()
     Per-run prompt emitted by cli.py BEFORE the full_access agent
     is built. Asks `Confirm full-access run? [y/N]`. 30 s hard
     timeout. Timeout = deny. Decision 0006.

  2. prompt_destructive()
     Per-tool prompt emitted from host-side tools (git_push, run)
     when the call matches is_destructive() (decision 0007). Asks
     `Approve? [y/N/a(ll)/o(ff)]`. y = run, N = abort run, a = run
     + auto-approve for rest of run, o = deny + auto-approve OFF
     for rest of run. 30 s timeout (configurable via
     SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S).

Both prompts share the threading-based timeout (cross-platform; no
select / kbhit / signal.alarm dependencies).
"""

from __future__ import annotations

import os
import sys
import threading

from .session import DestructiveDecision


_DEFAULT_TIMEOUT_S = 30.0
_MIN_TIMEOUT_S = 0.0
_ENV_VAR = "SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S"


class ConfirmationDenied(RuntimeError):
    """Raised when the user denies (or times out on) a confirmation prompt."""


def resolve_timeout_s(arg_value=None):
    """Resolve the confirmation timeout in seconds.

    Order (highest priority first):
        1. explicit `arg_value` from --confirm-timeout (str or float)
        2. SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S env var
        3. _DEFAULT_TIMEOUT_S = 30.0

    Negative values are clamped to 0. Non-numeric / unparseable
    values fall back to 30.0 (safe default).
    """
    raw = arg_value
    if raw is None:
        raw = os.environ.get(_ENV_VAR)
    if raw is None or raw == "":
        return _DEFAULT_TIMEOUT_S
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_S
    if v < _MIN_TIMEOUT_S:
        return _MIN_TIMEOUT_S
    return v


def prompt_confirmation(
    prompt="Confirm full-access run? [y/N] ",
    *,
    timeout_s=30.0,
    read_fn=None,
    write_fn=None,
):
    """Prompt for y/N; return True iff the user typed `y` (case-insensitive).

    Returns False on any of:
        - the user typed anything other than `y` (empty, "n", "no", ...)
        - the timeout elapsed before any input
        - stdin returned EOF without input
        - the underlying read raised an exception

    Args:
        prompt: text to write to stdout before reading.
        timeout_s: seconds to wait before giving up. <= 0 means
            "wait forever" (the user must hit Enter).
        read_fn: injectable read callable; defaults to sys.stdin.readline.
            Must return a single line including the trailing newline,
            or an empty string on EOF.
        write_fn: injectable write callable; defaults to
            sys.stdout.write + flush.

    Returns:
        True if the user confirmed, False otherwise.
    """
    if read_fn is None:
        read_fn = sys.stdin.readline
    if write_fn is None:

        def write_fn(s):
            sys.stdout.write(s)
            sys.stdout.flush()

    try:
        write_fn(prompt)
    except Exception:
        pass

    if timeout_s <= 0:
        # No timeout: wait forever for a line.
        try:
            line = read_fn() or ""
        except Exception:
            return False
        s = line.strip().lower()
        return s == "y" or s == "yes"

    result = []
    done = threading.Event()

    def _do_read():
        try:
            line = read_fn()
            if line is None:
                line = ""
            result.append(line)
        except Exception:
            result.append("")
        finally:
            done.set()

    t = threading.Thread(target=_do_read, daemon=True)
    t.start()
    if not done.wait(timeout=timeout_s):
        # Timeout. The reader thread is daemon so it won't block exit.
        return False
    line = result[0] if result else ""
    s = line.strip().lower()
    return s == "y" or s == "yes"


def confirm_full_access(*, timeout_s=None, read_fn=None, write_fn=None):
    """High-level helper: prompt and raise ConfirmationDenied on deny.

    Returns silently on confirm. Raises ConfirmationDenied on any
    non-y answer (including timeout and EOF).
    """
    if timeout_s is None:
        timeout_s = resolve_timeout_s()
    if prompt_confirmation(timeout_s=timeout_s, read_fn=read_fn, write_fn=write_fn):
        return
    raise ConfirmationDenied(
        "full_access run not confirmed" + (" (timed out after " + repr(timeout_s) + "s)" if timeout_s > 0 else "")
    )


__all__ = [
    "ConfirmationDenied",
    "DestructiveDecision",
    "confirm_full_access",
    "prompt_confirmation",
    "prompt_destructive",
    "resolve_timeout_s",
    "resolve_destructive_timeout_s",
]


# --- M4.x: per-tool destructive confirmation --------------------------------


_DESTRUCTIVE_ENV_VAR = "SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S"
_DESTRUCTIVE_DEFAULT_TIMEOUT_S = 30.0


def resolve_destructive_timeout_s(arg_value=None):
    """Resolve the destructive-op confirmation timeout in seconds.

    Order (highest priority first):
        1. explicit `arg_value` from --destructive-confirm-timeout (str/float)
        2. SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S env var
        3. _DESTRUCTIVE_DEFAULT_TIMEOUT_S = 30.0

    Negative values are clamped to 0. Non-numeric / unparseable
    values fall back to 30.0.
    """
    raw = arg_value
    if raw is None:
        raw = os.environ.get(_DESTRUCTIVE_ENV_VAR)
    if raw is None or raw == "":
        return _DESTRUCTIVE_DEFAULT_TIMEOUT_S
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return _DESTRUCTIVE_DEFAULT_TIMEOUT_S
    if v < 0:
        return 0.0
    return v


def prompt_destructive(
    tool_name,
    summary,
    *,
    timeout_s=30.0,
    read_fn=None,
    write_fn=None,
):
    """Per-tool confirmation prompt for destructive operations (M4.x).

    Returns a DestructiveDecision with:
        - approved=True  if user typed `y` or `yes` (or `a`/`all`).
        - approved=False if user typed anything else, EOF, or timeout.
        - auto_approve_now=True  if user typed `a` (auto-approve ON
          for the remainder of the run after this approval).
        - auto_approve_off=True if user typed `o` (auto-approve OFF
          for the remainder of the run after this denial).

    Recognised inputs (case-insensitive, after strip):
        y, yes           -> approve this call.
        a, all           -> approve this call + flip auto-approve ON.
        n, no, o, off    -> deny. `o`/`off` also flips auto-approve OFF.
        anything else    -> deny.
        empty            -> deny (safe default).
        EOF / exception  -> deny.
        timeout          -> deny.
    """
    if read_fn is None:
        read_fn = sys.stdin.readline
    if write_fn is None:

        def write_fn(s):
            sys.stdout.write(s)
            sys.stdout.flush()

    prompt = (
        "\n[DESTRUCTIVE] "
        + str(tool_name)
        + "("
        + str(summary)
        + ")\n"
        + "Approve? [y/N/a(ll)/o(ff)] (timeout "
        + repr(timeout_s)
        + "s) "
    )
    try:
        write_fn(prompt)
    except Exception:
        pass

    line = ""
    if timeout_s <= 0:
        try:
            line = read_fn() or ""
        except Exception:
            line = ""
    else:
        result = []
        done = threading.Event()

        def _do_read():
            try:
                ln = read_fn()
                if ln is None:
                    ln = ""
                result.append(ln)
            except Exception:
                result.append("")
            finally:
                done.set()

        t = threading.Thread(target=_do_read, daemon=True)
        t.start()
        if done.wait(timeout=timeout_s):
            line = result[0] if result else ""
        else:
            line = ""

    s = line.strip().lower()
    if s == "y" or s == "yes":
        return DestructiveDecision(approved=True, reason="user-approved")
    if s == "a" or s == "all":
        return DestructiveDecision(
            approved=True,
            auto_approve_now=True,
            reason="user-approved-all",
        )
    if s == "o" or s == "off":
        return DestructiveDecision(
            approved=False,
            auto_approve_off=True,
            reason="user-off",
        )
    if not s:
        return DestructiveDecision(approved=False, reason="empty")
    # Timeout / EOF / unknown -> deny.
    if not line and not s:
        return DestructiveDecision(approved=False, reason="timeout-or-eof")
    return DestructiveDecision(approved=False, reason="user-denied")
