"""Tests for web/diffs.py (M10, decision 0010 D5).

Covers:
- unified_hunks (structured diff hunks)
- unified_text (GNU unified-diff text)
- summarize (added / removed / same counts)
- walk_tree (workspace tree walker + skip rules)
- read_text_for_diff (read with size cap)
"""

from __future__ import annotations

import pytest

from smolcode.web.diffs import (
    read_text_for_diff,
    summarize,
    unified_hunks,
    unified_text,
    walk_tree,
)


# --- unified_hunks --------------------------------------------------------


def test_unified_hunks_empty_returns_empty():
    assert unified_hunks("", "") == []


def test_unified_hunks_identical_returns_empty():
    a = "line1\nline2\n"
    assert unified_hunks(a, a) == []


def test_unified_hunks_pure_insert():
    before = "a\nb\n"
    after = "a\nb\nc\n"
    hunks = unified_hunks(before, after)
    assert any(h.op == "insert" and "c" in h.after_lines for h in hunks)


def test_unified_hunks_pure_delete():
    before = "a\nb\nc\n"
    after = "a\nc\n"
    hunks = unified_hunks(before, after)
    assert any(h.op == "delete" and "b" in h.before_lines for h in hunks)


def test_unified_hunks_replace_emits_op():
    before = "a\nold\nc\n"
    after = "a\nnew\nc\n"
    hunks = unified_hunks(before, after)
    replace = [h for h in hunks if h.op == "replace"]
    assert replace
    assert replace[0].before_lines == ["old"]
    assert replace[0].after_lines == ["new"]


def test_unified_hunks_to_dict_shape():
    hunks = unified_hunks("a\n", "a\nb\n")
    d = hunks[0].to_dict()
    assert set(d.keys()) == {"op", "before", "after"}


# --- unified_text ---------------------------------------------------------


def test_unified_text_identical_returns_empty():
    assert unified_text("a\nb\n", "a\nb\n") == ""


def test_unified_text_includes_diff_markers():
    out = unified_text("a\n", "b\n")
    assert "--- before" in out
    assert "+++ after" in out
    assert "@@" in out
    assert "-a" in out or "- a" in out
    assert "+b" in out or "+ b" in out


# --- summarize ------------------------------------------------------------


def test_summarize_no_change():
    s = summarize("a\nb\n", "a\nb\n")
    assert s["changed"] is False
    assert s["added"] == 0
    assert s["removed"] == 0


def test_summarize_counts_added_removed():
    s = summarize("a\n", "a\nb\n")
    assert s["changed"] is True
    assert s["added"] == 1
    assert s["removed"] == 0


def test_summarize_counts_replace():
    s = summarize("a\nold\n", "a\nnew\n")
    assert s["added"] == 1
    assert s["removed"] == 1


# --- walk_tree ------------------------------------------------------------


def _make_tree(root, files):
    """Helper: write (relpath, content) pairs under root."""
    for rel, content in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_walk_tree_empty(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    entries, truncated = walk_tree(str(ws))
    assert truncated is False
    assert entries == []


def test_walk_tree_returns_files(tmp_path):
    ws = tmp_path / "ws"
    _make_tree(ws, [("a.txt", "a"), ("b.txt", "b"), ("sub/c.txt", "c")])
    entries, truncated = walk_tree(str(ws))
    assert truncated is False
    rels = sorted(e.rel_path for e in entries)
    assert "a.txt" in rels
    assert "b.txt" in rels
    assert "sub" in rels
    assert "sub/c.txt" in rels


def test_walk_tree_skips_dotdirs_except_smolcode(tmp_path):
    ws = tmp_path / "ws"
    _make_tree(ws, [("visible.txt", "v"), (".hidden/x.txt", "h"), (".smolcode/uploads/y.txt", "y")])
    entries, _ = walk_tree(str(ws))
    rels = [e.rel_path for e in entries]
    assert "visible.txt" in rels
    assert ".hidden/x.txt" not in rels
    assert ".hidden" not in rels
    assert ".smolcode" in rels
    assert ".smolcode/uploads/y.txt" in rels


def test_walk_tree_skips_noise_dirs(tmp_path):
    ws = tmp_path / "ws"
    _make_tree(ws, [("a.txt", "a"), (".git/HEAD", "ref"), ("node_modules/x.js", "x"), ("__pycache__/x.pyc", "x")])
    entries, _ = walk_tree(str(ws))
    rels = [e.rel_path for e in entries]
    assert "a.txt" in rels
    assert not any(r.startswith(".git") for r in rels)
    assert not any(r.startswith("node_modules") for r in rels)
    assert not any(r.startswith("__pycache__") for r in rels)


def test_walk_tree_truncates_at_max_entries(tmp_path):
    ws = tmp_path / "ws"
    _make_tree(ws, [(f"f{i}.txt", str(i)) for i in range(20)])
    entries, truncated = walk_tree(str(ws), max_entries=5)
    assert len(entries) == 5
    assert truncated is True


def test_walk_tree_rejects_missing_root(tmp_path):
    with pytest.raises(PermissionError):
        walk_tree(str(tmp_path / "missing"))


def test_walk_tree_rejects_file(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x")
    with pytest.raises(PermissionError):
        walk_tree(str(f))


def test_walk_tree_sorts_dirs_first(tmp_path):
    ws = tmp_path / "ws"
    _make_tree(ws, [("a.txt", "a"), ("zdir/x.txt", "x"), ("b.txt", "b")])
    entries, _ = walk_tree(str(ws))
    rels = [e.rel_path for e in entries]
    # directories should come before files in the listing.
    dir_idxs = [i for i, r in enumerate(rels) if r == "zdir"]
    file_idxs = [i for i, r in enumerate(rels) if r.endswith(".txt") and "/" not in r]
    if dir_idxs and file_idxs:
        assert min(dir_idxs) < max(file_idxs)


# --- read_text_for_diff ---------------------------------------------------


def test_read_text_for_diff_basic(tmp_path):
    p = tmp_path / "x.txt"
    # On Windows Path.write_text uses CRLF; bypass newline translation
    # so the assertion is portable.
    p.write_bytes(b"hello\n")
    text, truncated, err = read_text_for_diff(str(p))
    assert err is None
    assert text == "hello\n"
    assert truncated is False


def test_read_text_for_diff_missing(tmp_path):
    text, truncated, err = read_text_for_diff(str(tmp_path / "missing"))
    assert text == ""
    assert truncated is False
    assert err and err.startswith("io:")


def test_read_text_for_diff_binary(tmp_path):
    p = tmp_path / "x.bin"
    # Use bytes that are NOT valid UTF-8 so decode fails. (Pure ASCII
    # control chars decode as U+0000..U+001F which is valid UTF-8.)
    p.write_bytes(b"\xff\xfe\x00\x01")
    text, truncated, err = read_text_for_diff(str(p))
    assert text == ""
    assert err == "binary"


def test_read_text_for_diff_truncated(tmp_path, monkeypatch):
    p = tmp_path / "big.txt"
    # write a file larger than the cap to test truncation
    from smolcode.web.diffs import _MAX_FILE_BYTES

    p.write_bytes(b"x" * (_MAX_FILE_BYTES + 100))
    text, truncated, err = read_text_for_diff(str(p))
    assert err is None
    assert truncated is True
    assert len(text) == _MAX_FILE_BYTES
