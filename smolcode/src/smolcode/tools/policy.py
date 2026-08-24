"""Policy helpers for the workspace tools (M2).

See docs/security.md 5 (path policy) and 6 (command policy).
These classes are used by the host process (test assertions, CLI
logging). The Docker executor does NOT see this module — each tool
inlines its policy logic so the source is self-contained when
serialised by smolagents. See tools/fs.py and tools/shell.py for the
tool-side policy check.
"""

from __future__ import annotations

import os
from pathlib import Path


class PolicyViolation(PermissionError):
    """Raised when an operation violates the workspace or command policy."""


class PathPolicy:
    __slots__ = ("workspace", "_workspace_norm")

    def __init__(self, workspace):
        self.workspace = Path(workspace).expanduser().resolve()
        self._workspace_norm = os.path.normcase(str(self.workspace))

    def resolve_under_workspace(self, path, *, must_exist=False):
        if path is None or path == "":
            raise PolicyViolation("path is required")
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.workspace / p
        abs_str = os.path.realpath(str(p))
        if not _is_relative_to(os.path.normcase(abs_str), self._workspace_norm):
            raise PolicyViolation("path " + repr(str(path)) + " resolves to " + repr(abs_str) + " outside workspace")
        re_abs = os.path.realpath(abs_str)
        if not _is_relative_to(os.path.normcase(re_abs), self._workspace_norm):
            raise PolicyViolation("path " + repr(str(path)) + " changed during resolution")
        resolved = Path(re_abs)
        if must_exist and not resolved.exists():
            raise PolicyViolation(
                "path " + repr(str(path)) + " does not exist (resolved to " + repr(str(resolved)) + ")"
            )
        return resolved

    def is_under(self, path):
        try:
            self.resolve_under_workspace(path)
        except PolicyViolation:
            return False
        return True


def _is_relative_to(child, parent):
    try:
        common = os.path.commonpath([child, parent])
    except ValueError:
        return False
    return common == parent


class CommandPolicy:
    __slots__ = ("allowlist",)

    def __init__(self, allowlist):
        self.allowlist = tuple(allowlist)

    def check_basename(self, cmd):
        if not cmd:
            raise PolicyViolation("cmd is required")
        basename = os.path.basename(cmd)
        normalized = _strip_exe_suffix(basename)
        if normalized not in self.allowlist:
            raise PolicyViolation("command " + repr(normalized) + " not in allowlist " + repr(list(self.allowlist)))
        return normalized


def _strip_exe_suffix(name):
    if os.name != "nt":
        return name
    lower = name.lower()
    for ext in (".exe", ".bat", ".cmd", ".com"):
        if lower.endswith(ext):
            return name[: -len(ext)]
    return name
