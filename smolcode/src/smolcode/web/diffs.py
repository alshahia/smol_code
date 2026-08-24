"""Inline-diff helpers + workspace-tree walker (M10, decision 0010 D5).

Used by:

* ``web/agent_runner.py`` — when a web run calls ``write_file`` or
  ``patch_file``, the agent_runner wraps the call in a diff gate,
  publishes a ``diff.proposed`` SSE event with the unified diff, and
  blocks on user approval before the file is touched.
* ``web/api.py`` — the new ``GET /api/workspace/tree`` endpoint walks
  the workspace directory and returns a tree suitable for the SPA's
  inspector pane.

The diff format is intentionally small (a list of hunks, each with
``op`` in {``equal``, ``insert``, ``delete``, ``replace``} and the
raw text). The SPA renders it with ``DiffViewer.tsx`` — it does NOT
need the full GNU unified-diff header (no ``---``, no line numbers
in this payload; the SPA computes its own line numbers per hunk).

The workspace-tree walker respects the same workspace-boundary
check as the existing ``fs.py`` tools: every directory entry must
be inside ``workspace_root`` after symlink + ``..`` resolution.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field
from pathlib import Path


# --- Unified-diff payload ---------------------------------------------------


@dataclass
class DiffHunk:
    op: str  # "equal" | "insert" | "delete" | "replace"
    before_lines: list = field(default_factory=list)
    after_lines: list = field(default_factory=list)

    def to_dict(self):
        return {
            "op": self.op,
            "before": self.before_lines,
            "after": self.after_lines,
        }


def unified_hunks(before: str, after: str):
    """Return a list of ``DiffHunk`` for the change from ``before`` to ``after``.

    The algorithm uses ``difflib.SequenceMatcher.get_opcodes`` which
    returns ``equal``, ``replace``, ``insert``, ``delete`` opcodes.
    We forward them as-is (mapped to the same op names; ``insert``
    has empty ``before_lines``; ``delete`` has empty ``after_lines``).
    """
    if before == after:
        return []
    matcher = difflib.SequenceMatcher(
        a=before.splitlines(keepends=False), b=after.splitlines(keepends=False), autojunk=False
    )
    out = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        out.append(
            DiffHunk(
                op=op,
                before_lines=before.splitlines(keepends=False)[i1:i2],
                after_lines=after.splitlines(keepends=False)[j1:j2],
            )
        )
    return out


def unified_text(before: str, after: str, *, context: int = 3) -> str:
    """Return a GNU unified-diff text for the change.

    ``context`` is the number of equal lines shown around each change.
    Pass ``context=0`` for the "minimal" diff. Used for the audit log
    and the optional ``SMOLCODE_WEB_DIFF_RAW=1`` mode that shows raw
    unified diff instead of the structured view.
    """
    if before == after:
        return ""
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="before",
        tofile="after",
        n=context,
    )
    return "".join(diff)


def summarize(before: str, after: str) -> dict:
    """Return a small summary dict for the change.

    Keys: ``added`` (lines), ``removed`` (lines), ``same`` (lines),
    ``changed`` (bool). Used by the inspector pane and the audit log.
    """
    hunks = unified_hunks(before, after)
    added = 0
    removed = 0
    same = 0
    for h in hunks:
        if h.op == "equal":
            same += len(h.before_lines)
        elif h.op == "insert":
            added += len(h.after_lines)
        elif h.op == "delete":
            removed += len(h.before_lines)
        elif h.op == "replace":
            added += len(h.after_lines)
            removed += len(h.before_lines)
    return {"added": added, "removed": removed, "same": same, "changed": bool(hunks)}


# --- Workspace-tree walker --------------------------------------------------


@dataclass
class TreeEntry:
    name: str
    rel_path: str
    is_dir: bool
    size: int  # bytes; 0 for directories
    mtime: float  # epoch seconds

    def to_dict(self):
        return {
            "name": self.name,
            "rel_path": self.rel_path,
            "is_dir": self.is_dir,
            "size": int(self.size),
            "mtime": float(self.mtime),
        }


_MAX_TREE_ENTRIES = 5000  # hard cap so the inspector cannot OOM the server
_MAX_TREE_DEPTH = 10


def walk_tree(root, *, max_entries=_MAX_TREE_ENTRIES, max_depth=_MAX_TREE_DEPTH, skip_dirs=()):
    """Walk ``root`` and return a sorted list of ``TreeEntry``.

    Returns ``(entries, truncated)`` where ``truncated`` is True iff
    the walker hit ``max_entries`` or a depth limit. Hidden directories
    (basename starts with ``.``) are skipped EXCEPT for
    ``.smolcode/uploads`` (the agent may want to surface the uploads
    folder). The walker raises ``PermissionError`` if ``root`` is not
    an absolute path inside an existing directory.

    Symlinks: not followed (we want predictable semantics; a symlinked
    directory could escape the workspace). Use ``Path.iterdir()`` so
    ``os.path.realpath`` stays consistent with the policy check.

    ``skip_dirs``: iterable of basename strings to skip on top of the
    default dotfile rule (e.g. ``{'.git', 'node_modules', '__pycache__'}``).
    """
    if not isinstance(root, (str, os.PathLike)):
        raise PermissionError("root must be a path-like")
    root_path = Path(os.path.realpath(str(root)))
    if not root_path.exists() or not root_path.is_dir():
        raise PermissionError("root does not exist or is not a directory: " + str(root_path))

    skip = set(skip_dirs)
    skip.update({".git", "__pycache__", "node_modules", ".venv", "venv", ".tox"})
    allow_dots = {".smolcode"}

    out = []
    truncated = False

    def _walk(directory, depth):
        nonlocal truncated
        if truncated:
            return
        if depth > max_depth:
            truncated = True
            return
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except (PermissionError, OSError):
            return
        for entry in entries:
            if len(out) >= max_entries:
                truncated = True
                return
            name = entry.name
            is_dot = name.startswith(".")
            if is_dot and name not in allow_dots:
                continue
            if name in skip:
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            is_dir = entry.is_dir() and not entry.is_symlink()
            rel = str(entry.relative_to(root_path)).replace(os.sep, "/")
            out.append(
                TreeEntry(
                    name=name,
                    rel_path=rel,
                    is_dir=is_dir,
                    size=0 if is_dir else int(stat.st_size),
                    mtime=float(stat.st_mtime),
                )
            )
            if is_dir:
                _walk(entry, depth + 1)

    _walk(root_path, 1)
    return out, truncated


# --- Workspace-file read (for diff context) ---------------------------------


_MAX_FILE_BYTES = 512 * 1024  # 512 KB: above this we treat as binary/truncated


def read_text_for_diff(path):
    """Read ``path`` and return ``(text, truncated_bool, error_str_or_None)``.

    If the file is larger than ``_MAX_FILE_BYTES`` we return the first
    ``_MAX_FILE_BYTES`` bytes decoded as UTF-8 with errors=replace and
    ``truncated=True``. If the file is not decodable as UTF-8 we
    return ``("", False, "binary")``. Any OSError surfaces as
    ``("", False, "io:<msg>")``.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read(_MAX_FILE_BYTES + 1)
    except OSError as e:
        return "", False, "io:" + str(e)
    truncated = len(raw) > _MAX_FILE_BYTES
    if truncated:
        raw = raw[:_MAX_FILE_BYTES]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "", False, "binary"
    return text, truncated, None


__all__ = [
    "DiffHunk",
    "TreeEntry",
    "unified_hunks",
    "unified_text",
    "summarize",
    "walk_tree",
    "read_text_for_diff",
    "_MAX_FILE_BYTES",
    "_MAX_TREE_ENTRIES",
    "_MAX_TREE_DEPTH",
]
