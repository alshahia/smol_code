"""Per-run session state (M4.x, decision 0007).

The CLI sets a SessionState at the start of main() and clears it
at the end. Host-side tools (git, shell) read auto_approve_destructive
from the session via current_session() and consult the confirm
callback before executing destructive operations.

Why a module-level singleton? The tool's forward() runs on the host
(not in the Docker container) but doesn't have a reference to the
calling cli.py:main() stack frame. A module-level registry gives
host tools a way to find the session without importing cli (which
would create a circular import + make the tool untestable in
isolation).

Threading: SessionState is mutated by the confirm callback (in the
agent loop's thread) and read by tool forward() (also in the agent
loop's thread). Both run on the same thread for smolagents' current
loop architecture; we use a Lock anyway so future async / multi-
agent code is safe.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class DestructiveDecision:
    """Result of a destructive-op confirmation prompt."""

    approved: bool
    auto_approve_now: bool = False  # user typed `a` -> flip auto-approve ON for rest of run
    auto_approve_off: bool = False  # user typed `o` -> flip auto-approve OFF for rest of run
    reason: str = ""  # why approved/denied (e.g. "timeout", "user-denied", "user-approved")


# Callback signature: given (tool_name, kwargs, summary) -> DestructiveDecision.
# The session owner (CLI) installs the real one that calls
# confirm.prompt_destructive(); tests install a fake.
DestructiveCallback = Callable[[str, dict, str], DestructiveDecision]


# M10: diff-gate callback. Used by the web GUI to gate every
# ``write_file`` / ``patch_file`` call. The tool's forward() reads
# the file's current content (``before``), computes the proposed
# ``after``, and calls the callback with all of that. The callback
# may approve, deny, or approve with an edited ``after`` text.
@dataclass
class DiffDecision:
    """Result of a write_file / patch_file diff gate."""

    approved: bool
    edited_after: str | None = None  # if approved and edited, replace the proposed content
    auto_approve_now: bool = False  # flip auto_approve_diff ON for rest of run
    reason: str = ""


# Callback signature: given (tool_name, kwargs, path, before, after,
# summary) -> DiffDecision.
DiffCallback = Callable[[str, dict, str, str, str, str], DiffDecision]


@dataclass
class SessionState:
    """Per-run mutable state read by host-side tools."""

    tier: str = "restricted"
    auto_approve_destructive: bool = False
    confirm_callback: DestructiveCallback | None = None
    # Optional audit sink so destructive decisions + checkpoints
    # land in the run's JSONL.
    audit_sink: Any = None  # AuditSink | None
    # M10: diff gate. When set, write_file and patch_file forward()
    # call this before touching disk. Empty default -> tools behave
    # exactly as before (CLI / tests without a web session).
    diff_callback: DiffCallback | None = None
    auto_approve_diff: bool = False  # flipped by auto_approve_now=True in DiffDecision


_session: SessionState | None = None
_session_lock = threading.Lock()


def set_session(session):
    """Install the active session. Pass None to clear."""
    global _session
    with _session_lock:
        _session = session


def get_session():
    """Return the active session, or None if none is installed."""
    with _session_lock:
        return _session


def current_session():
    """Return the active session, or a safe default if none installed.

        The default has auto_approve_destructive=False and a None
        confirm_callback. The None callback means "if you reach this,
    you're being called outside a smolcode run; deny for safety".
    """
    s = get_session()
    if s is None:
        return SessionState()
    return s


def _ensure_default_session():
    """Internal: install a default session if none exists. Used by
    host tools that want to be safe even if main() never ran."""
    global _session
    with _session_lock:
        if _session is None:
            _session = SessionState()


__all__ = [
    "DestructiveCallback",
    "DestructiveDecision",
    "DiffCallback",
    "DiffDecision",
    "SessionState",
    "current_session",
    "get_session",
    "set_session",
]
