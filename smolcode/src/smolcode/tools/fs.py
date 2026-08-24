"""Filesystem tools (M2).

Three host-side tools (read_file, write_file, list_dir) all routed
through path policy before any I/O. Per docs/architecture.md 5.3 and
docs/security.md 5.

Why the workspace path is a CLASS attribute (not an __init__ arg)
----------------------------------------------------------------
smolagents' Docker executor re-instantiates each Tool on the remote
side with NO arguments (``tool_name = ClassName()``), so any state
passed via ``__init__`` is lost. State that must reach the remote
must be a class attribute. We use ``bind_attrs`` in
``build_fs_tools`` to generate a one-off subclass with the workspace
baked in.

The policy check logic is INLINED in each ``forward()`` so the
source is self-contained when smolagents serialises the tool for
the Docker executor.
"""

from __future__ import annotations

from smolagents import Tool

from ._bind import bind_attrs


class _ReadFileTool(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file under the workspace. Args: path (str)."
    inputs = {"path": {"type": "string", "description": "Absolute or workspace-relative path."}}
    output_type = "string"
    workspace = ""  # overridden per-build by build_fs_tools via bind_attrs

    def __init__(self):
        super().__init__()

    def forward(self, path: str) -> str:
        import os
        from pathlib import Path

        if path is None or path == "":
            raise PermissionError("path is required")
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(self.workspace) / p
        abs_str = os.path.realpath(str(p))
        workspace_norm = os.path.normcase(os.path.realpath(str(self.workspace)))
        try:
            common = os.path.commonpath([os.path.normcase(abs_str), workspace_norm])
        except ValueError:
            raise PermissionError("path resolves outside workspace")
        if common != workspace_norm:
            raise PermissionError("path resolves outside workspace")
        re_abs = os.path.realpath(abs_str)
        try:
            re_common = os.path.commonpath([os.path.normcase(re_abs), workspace_norm])
        except ValueError:
            raise PermissionError("path changed during resolution")
        if re_common != workspace_norm:
            raise PermissionError("path changed during resolution")
        resolved = Path(re_abs)
        if not resolved.exists():
            raise PermissionError("path does not exist: " + str(resolved))
        if not resolved.is_file():
            raise PermissionError("path is not a file: " + str(resolved))
        return resolved.read_text(encoding="utf-8")


class _WriteFileTool(Tool):
    name = "write_file"
    description = "Write a UTF-8 text file under the workspace. Args: path (str), content (str)."
    inputs = {
        "path": {"type": "string", "description": "Absolute or workspace-relative path."},
        "content": {"type": "string", "description": "UTF-8 text content."},
    }
    output_type = "string"
    workspace = ""  # overridden per-build
    # M8: tier name + uploads_dir path. Empty defaults preserve legacy
    # test behaviour (no upload write-block when tier="" or uploads_dir="").
    tier = ""  # overridden per-build by build_fs_tools
    uploads_dir = ""  # overridden per-build by build_fs_tools

    def __init__(self):
        super().__init__()

    def forward(self, path: str, content: str) -> str:
        import os
        from pathlib import Path

        if path is None or path == "":
            raise PermissionError("path is required")
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(self.workspace) / p
        abs_str = os.path.realpath(str(p))
        workspace_norm = os.path.normcase(os.path.realpath(str(self.workspace)))
        try:
            common = os.path.commonpath([os.path.normcase(abs_str), workspace_norm])
        except ValueError:
            raise PermissionError("path resolves outside workspace")
        if common != workspace_norm:
            raise PermissionError("path resolves outside workspace")
        # M8: restricted tier is read-only on the uploads folder.
        # The user can still delete / re-upload via the GUI or
        # `smolcode uploads clean`; the agent just cannot mutate.
        if self.tier == "restricted" and self.uploads_dir:
            uploads_norm = os.path.normcase(os.path.realpath(str(self.uploads_dir)))
            try:
                up_common = os.path.commonpath([os.path.normcase(abs_str), uploads_norm])
            except ValueError:
                up_common = ""
            if up_common == uploads_norm:
                raise PermissionError(
                    "restricted tier cannot modify files under the uploads folder; "
                    "the user uploaded these files and only the user can change them"
                )
        re_abs = os.path.realpath(abs_str)
        try:
            re_common = os.path.commonpath([os.path.normcase(re_abs), workspace_norm])
        except ValueError:
            raise PermissionError("path changed during resolution")
        if re_common != workspace_norm:
            raise PermissionError("path changed during resolution")
        resolved = Path(re_abs)
        if resolved.exists() and not resolved.is_file():
            raise PermissionError("path exists and is not a file: " + str(resolved))
        # M10: diff gate. Reads the existing file (if any), asks the
        # session to approve the proposed content, then writes the
        # (possibly edited) content. No diff_callback -> behaves as
        # before (writes `content` directly). The session consult is
        # inlined here because smolagents' AST validator rejects
        # calls to module-level helpers from a Tool's forward().
        before = ""
        if resolved.exists():
            try:
                before = resolved.read_text(encoding="utf-8")
            except OSError:
                before = ""
        from smolcode.session import DiffDecision as _DiffDecision  # M10
        from smolcode.session import current_session as _current_session  # M10

        sess = _current_session()
        cb = sess.diff_callback
        if cb is not None and not sess.auto_approve_diff:
            try:
                decision = cb(
                    "write_file",
                    {"path": path, "content": content},
                    str(resolved),
                    before,
                    str(content),
                    "write_file(" + str(resolved) + ", " + str(len(content)) + " bytes)",
                )
            except Exception as e:
                raise PermissionError("diff gate failed: " + str(e))
            if not isinstance(decision, _DiffDecision):
                raise PermissionError("diff gate returned a non-DiffDecision result")
            if decision.auto_approve_now:
                sess.auto_approve_diff = True
            if not decision.approved:
                raise PermissionError("diff gate denied write_file (" + str(decision.reason or "user-denied") + ")")
            final_content = decision.edited_after if decision.edited_after is not None else content
        else:
            final_content = content
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(final_content, encoding="utf-8")
        return str(resolved)


class _ListDirTool(Tool):
    name = "list_dir"
    description = "List immediate entries of a directory under the workspace. Args: path (str)."
    inputs = {"path": {"type": "string", "description": "Absolute or workspace-relative path."}}
    output_type = "string"
    workspace = ""  # overridden per-build

    def __init__(self):
        super().__init__()

    def forward(self, path: str) -> str:
        import os
        from pathlib import Path

        if path is None or path == "":
            raise PermissionError("path is required")
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(self.workspace) / p
        abs_str = os.path.realpath(str(p))
        workspace_norm = os.path.normcase(os.path.realpath(str(self.workspace)))
        try:
            common = os.path.commonpath([os.path.normcase(abs_str), workspace_norm])
        except ValueError:
            raise PermissionError("path resolves outside workspace")
        if common != workspace_norm:
            raise PermissionError("path resolves outside workspace")
        re_abs = os.path.realpath(abs_str)
        try:
            re_common = os.path.commonpath([os.path.normcase(re_abs), workspace_norm])
        except ValueError:
            raise PermissionError("path changed during resolution")
        if re_common != workspace_norm:
            raise PermissionError("path changed during resolution")
        resolved = Path(re_abs)
        if not resolved.exists():
            raise PermissionError("path does not exist: " + str(resolved))
        if not resolved.is_dir():
            raise PermissionError("path is not a directory: " + str(resolved))
        entries = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = []
        for e in entries:
            lines.append(e.name + ("/" if e.is_dir() else ""))
        if not lines:
            return "(empty)"
        return chr(10).join(lines)


# --- M10: patch_file tool --------------------------------------------------


class _PatchFileTool(Tool):
    """Apply a GNU unified-diff text to a file under the workspace.

    M10: introduced to support surgical edits with smaller diffs than
    a full ``write_file``. The diff text is parsed hunk by hunk
    (``@@ -OLD_START,OLD_COUNT +NEW_START,NEW_COUNT @@``); each
    hunk's context/deletion/addition lines are applied to the
    pre-image in order. The pre-image is read from disk inside
    ``forward()``; the post-image is committed atomically (write to a
    temp file in the same directory, then ``os.replace``).

    Note: ``difflib.restore`` is *not* used because it only consumes
    ``Differ`` output (2-char prefixes), not GNU unified-diff format
    (1-char prefixes). Hand-rolling the applier keeps the behaviour
    explicit and easy to test.

    Tier policy mirrors ``_WriteFileTool``: restricted tier cannot
    modify files under the uploads folder.
    """

    name = "patch_file"
    description = (
        "Apply a unified-diff text to a UTF-8 text file under the workspace. Args: path (str), diff_text (str)."
    )
    inputs = {
        "path": {"type": "string", "description": "Absolute or workspace-relative path."},
        "diff_text": {"type": "string", "description": "GNU unified-diff text."},
    }
    output_type = "string"
    workspace = ""
    tier = ""
    uploads_dir = ""

    def __init__(self):
        super().__init__()

    @staticmethod
    def _apply_unified(before_text, diff_text):
        """Apply ``diff_text`` to ``before_text`` and return the result.

        Parses one or more GNU unified-diff hunks and applies them in
        order. Raises ``ValueError`` on parse failure or if any hunk
        does not match the source (one-based line counts, content
        match). The trailing-newline state of ``before_text`` is
        preserved.

        We do not delegate to ``difflib.restore`` because it only
        accepts ``Differ`` output (2-char prefixes), not GNU
        unified-diff format (1-char prefixes).
        """
        import re

        if not isinstance(diff_text, str) or not diff_text:
            raise ValueError("diff_text is required")
        lines = diff_text.splitlines()
        # Skip file headers (--- / +++) and parse hunks.
        hunks = []
        i = 0
        n = len(lines)
        while i < n and not lines[i].startswith("@@"):
            i += 1
        while i < n:
            header = lines[i]
            if not header.startswith("@@"):
                raise ValueError("expected hunk header at line " + str(i + 1))
            m = re.match(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", header)
            if not m:
                raise ValueError("malformed hunk header: " + header)
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            i += 1
            body = []
            while i < n and not lines[i].startswith("@@"):
                cur = lines[i]
                if cur.startswith("\\"):
                    # ``\ No newline at end of file`` marker — ignore.
                    i += 1
                    continue
                if cur == "":
                    # Blank line between hunks / trailing blank line.
                    i += 1
                    continue
                tag = cur[0]
                if tag in (" ", "-", "+"):
                    body.append((tag, cur[1:]))
                    i += 1
                    continue
                raise ValueError("malformed hunk line " + str(i + 1) + ": " + repr(cur))
            # smolagents' MethodChecker has no visit_GeneratorExp handler,
            # so a generator expression like ``sum(1 for t, _ in body ...)``
            # leaves ``t`` undefined and the tool is rejected at startup.
            # Use a regular loop instead.
            body_old = 0
            body_new = 0
            for tag, _ in body:
                if tag == " " or tag == "-":
                    body_old += 1
                if tag == " " or tag == "+":
                    body_new += 1
            if body_old != old_count:
                raise ValueError("hunk header says " + str(old_count) + " old lines but body has " + str(body_old))
            if body_new != new_count:
                raise ValueError("hunk header says " + str(new_count) + " new lines but body has " + str(body_new))
            hunks.append((old_start, old_count, new_start, new_count, body))
        if not hunks:
            raise ValueError("diff_text has no @@ hunks")
        # Apply hunks left-to-right against the source.
        before_lines = before_text.splitlines()
        after_lines = []
        cursor = 0
        for old_start, _old_count, _new_start, _new_count, body in hunks:
            # old_start is 1-based; a value of 0 means insert at top.
            target = old_start - 1 if old_start > 0 else 0
            if target < cursor:
                raise ValueError(
                    "hunk out of order (old_start " + str(old_start) + " is before cursor " + str(cursor + 1) + ")"
                )
            after_lines.extend(before_lines[cursor:target])
            cursor = target
            for tag, content in body:
                if tag == " ":
                    if cursor >= len(before_lines) or before_lines[cursor] != content:
                        raise ValueError("context line does not match source at old line " + str(cursor + 1))
                    after_lines.append(content)
                    cursor += 1
                elif tag == "-":
                    if cursor >= len(before_lines) or before_lines[cursor] != content:
                        raise ValueError("deletion line does not match source at old line " + str(cursor + 1))
                    cursor += 1
                elif tag == "+":
                    after_lines.append(content)
        # Append any trailing unchanged lines.
        after_lines.extend(before_lines[cursor:])
        if before_text.endswith("\n"):
            return "\n".join(after_lines) + "\n"
        return "\n".join(after_lines)

    def forward(self, path: str, diff_text: str) -> str:
        import os
        import tempfile
        from pathlib import Path

        if path is None or path == "":
            raise PermissionError("path is required")
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(self.workspace) / p
        abs_str = os.path.realpath(str(p))
        workspace_norm = os.path.normcase(os.path.realpath(str(self.workspace)))
        try:
            common = os.path.commonpath([os.path.normcase(abs_str), workspace_norm])
        except ValueError:
            raise PermissionError("path resolves outside workspace")
        if common != workspace_norm:
            raise PermissionError("path resolves outside workspace")
        if self.tier == "restricted" and self.uploads_dir:
            uploads_norm = os.path.normcase(os.path.realpath(str(self.uploads_dir)))
            try:
                up_common = os.path.commonpath([os.path.normcase(abs_str), uploads_norm])
            except ValueError:
                up_common = ""
            if up_common == uploads_norm:
                raise PermissionError(
                    "restricted tier cannot modify files under the uploads folder; "
                    "the user uploaded these files and only the user can change them"
                )
        re_abs = os.path.realpath(abs_str)
        try:
            re_common = os.path.commonpath([os.path.normcase(re_abs), workspace_norm])
        except ValueError:
            raise PermissionError("path changed during resolution")
        if re_common != workspace_norm:
            raise PermissionError("path changed during resolution")
        resolved = Path(re_abs)
        if not resolved.exists():
            raise PermissionError("path does not exist: " + str(resolved))
        if not resolved.is_file():
            raise PermissionError("path is not a file: " + str(resolved))
        before = resolved.read_text(encoding="utf-8")
        after = self._apply_unified(before, diff_text)
        # M10: diff gate (inlined; see write_file for the rationale).
        from smolcode.session import DiffDecision as _DiffDecision  # M10
        from smolcode.session import current_session as _current_session  # M10

        sess = _current_session()
        cb = sess.diff_callback
        if cb is not None and not sess.auto_approve_diff:
            try:
                decision = cb(
                    "patch_file",
                    {"path": path, "diff_text": diff_text},
                    str(resolved),
                    before,
                    after,
                    "patch_file(" + str(resolved) + ", " + str(len(diff_text)) + " bytes of diff)",
                )
            except Exception as e:
                raise PermissionError("diff gate failed: " + str(e))
            if not isinstance(decision, _DiffDecision):
                raise PermissionError("diff gate returned a non-DiffDecision result")
            if decision.auto_approve_now:
                sess.auto_approve_diff = True
            if not decision.approved:
                raise PermissionError("diff gate denied patch_file (" + str(decision.reason or "user-denied") + ")")
            final_after = decision.edited_after if decision.edited_after is not None else after
        else:
            final_after = after
        # Atomic write: temp file in same dir, then os.replace.
        # ``newline=""`` keeps ``\n`` as-is on Windows instead of the
        # default behaviour that translates ``\n`` to ``\r\n`` on write.
        fd, tmp_path = tempfile.mkstemp(prefix=".patch.", dir=str(resolved.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(final_after)
            os.replace(tmp_path, str(resolved))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return str(resolved)


def build_fs_tools(workspace_path, *, tier="", uploads_dir=""):
    """Return four Tool instances bound to workspace_path.

    Each instance is of a per-build subclass whose workspace
    class attribute equals str(workspace_path).

    M8: tier and uploads_dir are bound onto _WriteFileTool only
    (so write_file can enforce the restricted-tier upload
    write-block). Both default to empty strings so existing
    tests that pass only workspace_path keep working unchanged.

    M10: _PatchFileTool is bound with the same tier + uploads_dir
    so it inherits the restricted-tier upload read-only policy.
    """
    ws = str(workspace_path)
    r_cls = bind_attrs(_ReadFileTool, {"workspace": ws})
    w_cls = bind_attrs(
        _WriteFileTool,
        {
            "workspace": ws,
            "tier": str(tier),
            "uploads_dir": str(uploads_dir),
        },
    )
    l_cls = bind_attrs(_ListDirTool, {"workspace": ws})
    p_cls = bind_attrs(
        _PatchFileTool,
        {
            "workspace": ws,
            "tier": str(tier),
            "uploads_dir": str(uploads_dir),
        },
    )
    return [r_cls(), w_cls(), l_cls(), p_cls()]
