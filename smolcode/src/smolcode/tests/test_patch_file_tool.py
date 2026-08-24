"""Tests for _PatchFileTool (M10).

Covers:
- basic patch apply
- rejects empty diff_text
- rejects diff that doesn't match source
- preserves unchanged lines (context)
- workspace boundary
- restricted-tier upload read-only block
- atomic-write temp file is cleaned up on failure
- diff gate integration (session.diff_callback consulted)
"""

from __future__ import annotations

import pytest

from smolcode.session import DiffDecision, SessionState, set_session
from smolcode.tools.fs import build_fs_tools


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def fs_tools(workspace):
    return {t.name: t for t in build_fs_tools(str(workspace))}


@pytest.fixture(autouse=True)
def clear_session():
    set_session(None)
    yield
    set_session(None)


# --- direct _PatchFileTool tests -----------------------------------------


def _make_diff(before, after, *, ctx=1):
    """Build a GNU unified diff text from ``before`` -> ``after``."""
    import difflib

    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="before",
        tofile="after",
        n=ctx,
    )
    return "".join(diff)


def test_patch_file_basic_apply(workspace, fs_tools):
    f = workspace / "x.txt"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    diff = _make_diff("a\nb\nc\n", "a\nB\nc\n")
    res = fs_tools["patch_file"].forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\nB\nc\n"
    assert res == str(f.resolve())


def test_patch_file_insert_lines(workspace, fs_tools):
    f = workspace / "x.txt"
    f.write_text("a\nb\n", encoding="utf-8")
    diff = _make_diff("a\nb\n", "a\nb\nc\n")
    fs_tools["patch_file"].forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\nb\nc\n"


def test_patch_file_delete_lines(workspace, fs_tools):
    f = workspace / "x.txt"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    diff = _make_diff("a\nb\nc\n", "a\nc\n")
    fs_tools["patch_file"].forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\nc\n"


def test_patch_file_rejects_empty_diff(workspace, fs_tools):
    f = workspace / "x.txt"
    f.write_text("a\n", encoding="utf-8")
    with pytest.raises(ValueError):
        fs_tools["patch_file"].forward(path=str(f), diff_text="")


def test_patch_file_rejects_no_hunks(workspace, fs_tools):
    f = workspace / "x.txt"
    f.write_text("a\n", encoding="utf-8")
    with pytest.raises(ValueError):
        fs_tools["patch_file"].forward(path=str(f), diff_text="--- before\n+++ after\n")


def test_patch_file_rejects_non_matching_diff(workspace, fs_tools):
    f = workspace / "x.txt"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    # Diff says we're removing line 2 "Z" but source has "b"
    diff = "--- before\n+++ after\n@@ -1,3 +1,3 @@\n a\n-Z\n c\n"
    with pytest.raises(ValueError):
        fs_tools["patch_file"].forward(path=str(f), diff_text=diff)
    # File unchanged
    assert f.read_text(encoding="utf-8") == "a\nb\nc\n"


def test_patch_file_outside_workspace_rejected(workspace, tmp_path, fs_tools):
    outside = tmp_path / "outside.txt"
    outside.write_text("a\n", encoding="utf-8")
    diff = _make_diff("a\n", "b\n")
    with pytest.raises(PermissionError):
        fs_tools["patch_file"].forward(path=str(outside), diff_text=diff)
    assert outside.read_text(encoding="utf-8") == "a\n"


def test_patch_file_missing_rejected(workspace, fs_tools):
    diff = _make_diff("a\n", "b\n")
    with pytest.raises(PermissionError):
        fs_tools["patch_file"].forward(path=str(workspace / "missing.txt"), diff_text=diff)


def test_patch_file_atomic_write_cleans_up_tmp(workspace):
    # Build a tool bound to the workspace via build_fs_tools so the
    # tier check works the way the real agent uses it.
    tools = {t.name: t for t in build_fs_tools(str(workspace))}
    f = workspace / "x.txt"
    f.write_text("a\nb\n", encoding="utf-8")
    diff = _make_diff("a\nb\n", "a\nb\nc\n")
    tools["patch_file"].forward(path=str(f), diff_text=diff)
    # No .patch.* temp files left over.
    leftover = [p.name for p in workspace.iterdir() if p.name.startswith(".patch.")]
    assert leftover == []


def test_patch_file_via_build_fs_tools(workspace):
    tools = {t.name: t for t in build_fs_tools(str(workspace))}
    assert "patch_file" in tools
    f = workspace / "x.txt"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    diff = _make_diff("a\nb\nc\n", "a\nB\nc\n")
    tools["patch_file"].forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\nB\nc\n"


# --- restricted-tier upload policy (mirrors write_file) -----------------


def test_patch_file_restricted_tier_blocked_from_uploads(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    uploads = ws / ".smolcode" / "uploads"
    uploads.mkdir(parents=True)
    f = uploads / "doc.txt"
    f.write_text("a\n", encoding="utf-8")
    tools = {t.name: t for t in build_fs_tools(str(ws), tier="restricted", uploads_dir=str(uploads))}
    diff = _make_diff("a\n", "b\n")
    with pytest.raises(PermissionError):
        tools["patch_file"].forward(path=str(f), diff_text=diff)
    # file unchanged
    assert f.read_text(encoding="utf-8") == "a\n"


def test_patch_file_elevated_tier_allowed_to_uploads(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    uploads = ws / ".smolcode" / "uploads"
    uploads.mkdir(parents=True)
    f = uploads / "doc.txt"
    f.write_text("a\n", encoding="utf-8")
    tools = {t.name: t for t in build_fs_tools(str(ws), tier="elevated", uploads_dir=str(uploads))}
    diff = _make_diff("a\n", "b\n")
    tools["patch_file"].forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "b\n"


# --- diff gate integration -----------------------------------------------


def test_patch_file_calls_session_diff_callback(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\n", encoding="utf-8")
    decisions = []

    def cb(tool_name, kwargs, path, before, after, summary):
        decisions.append(
            {
                "tool": tool_name,
                "path": path,
                "before": before,
                "after": after,
            }
        )
        return DiffDecision(approved=True)

    set_session(SessionState(diff_callback=cb))
    diff = _make_diff("a\nb\n", "a\nB\n")
    tools = {t.name: t for t in build_fs_tools(str(workspace))}
    tools["patch_file"].forward(path=str(f), diff_text=diff)
    assert len(decisions) == 1
    d = decisions[0]
    assert d["tool"] == "patch_file"
    assert d["before"] == "a\nb\n"
    assert d["after"] == "a\nB\n"
    assert f.read_text(encoding="utf-8") == "a\nB\n"


def test_patch_file_diff_callback_uses_edited_after(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\n", encoding="utf-8")

    def cb(tool_name, kwargs, path, before, after, summary):
        # User edits the proposed content.
        return DiffDecision(approved=True, edited_after="a\nUSER_EDITED\n")

    set_session(SessionState(diff_callback=cb))
    diff = _make_diff("a\nb\n", "a\nB\n")
    tools = {t.name: t for t in build_fs_tools(str(workspace))}
    tools["patch_file"].forward(path=str(f), diff_text=diff)
    # File now has the edited content, NOT the agent's proposal.
    assert f.read_text(encoding="utf-8") == "a\nUSER_EDITED\n"


def test_patch_file_diff_callback_deny_blocks_write(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\n", encoding="utf-8")

    def cb(tool_name, kwargs, path, before, after, summary):
        return DiffDecision(approved=False, reason="user-denied")

    set_session(SessionState(diff_callback=cb))
    diff = _make_diff("a\nb\n", "a\nB\n")
    tools = {t.name: t for t in build_fs_tools(str(workspace))}
    with pytest.raises(PermissionError):
        tools["patch_file"].forward(path=str(f), diff_text=diff)
    # File unchanged
    assert f.read_text(encoding="utf-8") == "a\nb\n"


def test_patch_file_auto_approve_diff_skips_callback(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\n", encoding="utf-8")
    calls = []

    def cb(tool_name, kwargs, path, before, after, summary):
        calls.append(tool_name)
        return DiffDecision(approved=True)

    sess = SessionState(diff_callback=cb, auto_approve_diff=True)
    set_session(sess)
    diff = _make_diff("a\nb\n", "a\nB\n")
    tools = {t.name: t for t in build_fs_tools(str(workspace))}
    tools["patch_file"].forward(path=str(f), diff_text=diff)
    assert calls == []  # callback was NOT called
    assert f.read_text(encoding="utf-8") == "a\nB\n"


def test_patch_file_diff_callback_non_DiffDecision_treated_as_deny(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\n", encoding="utf-8")

    def cb(tool_name, kwargs, path, before, after, summary):
        return "not a DiffDecision"  # type: ignore

    set_session(SessionState(diff_callback=cb))
    diff = _make_diff("a\nb\n", "a\nB\n")
    tools = {t.name: t for t in build_fs_tools(str(workspace))}
    with pytest.raises(PermissionError):
        tools["patch_file"].forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\nb\n"


def test_patch_file_diff_callback_exception_becomes_permission_error(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\n", encoding="utf-8")

    def cb(tool_name, kwargs, path, before, after, summary):
        raise RuntimeError("boom")

    set_session(SessionState(diff_callback=cb))
    diff = _make_diff("a\nb\n", "a\nB\n")
    tools = {t.name: t for t in build_fs_tools(str(workspace))}
    with pytest.raises(PermissionError):
        tools["patch_file"].forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\nb\n"


def test_patch_file_diff_callback_auto_approve_now_persists(workspace):
    f1 = workspace / "a.txt"
    f2 = workspace / "b.txt"
    f1.write_text("a\n", encoding="utf-8")
    f2.write_text("x\n", encoding="utf-8")
    calls = []

    def cb(tool_name, kwargs, path, before, after, summary):
        calls.append(tool_name)
        return DiffDecision(approved=True, auto_approve_now=True)

    set_session(SessionState(diff_callback=cb))
    tools = {t.name: t for t in build_fs_tools(str(workspace))}
    tools["patch_file"].forward(path=str(f1), diff_text=_make_diff("a\n", "A\n"))
    # Second call: session.auto_approve_diff should now be True,
    # so the callback is NOT invoked again.
    tools["patch_file"].forward(path=str(f2), diff_text=_make_diff("x\n", "X\n"))
    assert calls == ["patch_file"]
    assert f1.read_text(encoding="utf-8") == "A\n"
    assert f2.read_text(encoding="utf-8") == "X\n"


# --- _apply_unified edge cases (no diff gate; bind directly) ---------------


def _patch_from_workspace(workspace):
    return {t.name: t for t in build_fs_tools(str(workspace))}["patch_file"]


def test_apply_unified_preserves_no_trailing_newline(workspace):
    f = workspace / "x.txt"
    f.write_bytes(b"a\nb\nc")  # no trailing newline
    diff = _make_diff("a\nb\nc", "a\nB\nc")
    _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)
    assert f.read_bytes() == b"a\nB\nc"


def test_apply_unified_multiple_hunks(workspace):
    f = workspace / "x.txt"
    f.write_text("a1\na2\nb1\nb2\nc1\nc2\n", encoding="utf-8")
    diff = "--- x\n+++ y\n@@ -1,2 +1,2 @@\n a1\n-a2\n+A2\n@@ -3,2 +3,2 @@\n b1\n-b2\n+B2\n"
    _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a1\nA2\nb1\nB2\nc1\nc2\n"


def test_apply_unified_out_of_order_hunks_rejected(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\nc\nd\n", encoding="utf-8")
    # Second hunk goes before the first.
    diff = "--- x\n+++ y\n@@ -3,1 +3,1 @@\n-c\n+C\n@@ -1,1 +1,1 @@\n a\n"
    with pytest.raises(ValueError):
        _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)
    # File unchanged.
    assert f.read_text(encoding="utf-8") == "a\nb\nc\nd\n"


def test_apply_unified_malformed_hunk_header_rejected(workspace):
    f = workspace / "x.txt"
    f.write_text("a\n", encoding="utf-8")
    diff = "--- x\n+++ y\n@@broken@@\n a\n"
    with pytest.raises(ValueError):
        _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)


def test_apply_unified_old_count_mismatch_rejected(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    # Header claims 2 old lines but body only has 1 context line.
    diff = "--- x\n+++ y\n@@ -1,2 +1,2 @@\n a\n"
    with pytest.raises(ValueError):
        _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)


def test_apply_unified_new_count_mismatch_rejected(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    # Header claims 2 new lines but body only has 1 context + 1 insertion = 2; tweak.
    # Header claims 3 new lines but body has 2.
    diff = "--- x\n+++ y\n@@ -1,2 +1,3 @@\n a\n+b\n"
    with pytest.raises(ValueError):
        _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)


def test_apply_unified_blank_hunk_line_tolerated(workspace):
    f = workspace / "x.txt"
    f.write_text("a\n\nc\n", encoding="utf-8")
    # Blank line between hunks. Standard parsers tolerate it.
    diff = "--- x\n+++ y\n@@ -1,3 +1,4 @@\n a\n \n+b\n c\n"
    _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\n\nb\nc\n"


def test_apply_unified_context_mismatch_rejected(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    # Header claims context line matches "Z" but source has "b".
    diff = "--- x\n+++ y\n@@ -1,3 +1,3 @@\n a\n Z\n c\n"
    with pytest.raises(ValueError):
        _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\nb\nc\n"


def test_apply_unified_no_newline_at_eof_marker_tolerated(workspace):
    f = workspace / "x.txt"
    f.write_text("a\nb\n", encoding="utf-8")
    # ``\ No newline at end of file`` marker must be ignored.
    diff = "--- x\n+++ y\n@@ -1,2 +1,2 @@\n a\n-b\n+B\n\\ No newline at end of file\n"
    _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\nB\n"


def test_apply_unified_insert_at_top_of_file(workspace):
    f = workspace / "x.txt"
    f.write_text("b\nc\n", encoding="utf-8")
    diff = "--- x\n+++ y\n@@ -0,0 +1,1 @@\n+a\n"
    _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)
    assert f.read_text(encoding="utf-8") == "a\nb\nc\n"


def test_apply_unified_handles_empty_file(workspace):
    f = workspace / "x.txt"
    f.write_text("", encoding="utf-8")
    diff = "--- x\n+++ y\n@@ -0,0 +1,2 @@\n+a\n+b\n"
    _patch_from_workspace(workspace).forward(path=str(f), diff_text=diff)
    # Empty source has no trailing newline; result preserves that state.
    assert f.read_text(encoding="utf-8") == "a\nb"
