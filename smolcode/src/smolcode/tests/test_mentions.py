"""Tests for Phase 2 (decision 0025 §6.4): file mention parsing + attach.

Covers A5 (P0): the ``@path`` mention syntax. Backend accepts a task
string, parses ``@<path>`` tokens, resolves them under the active project
root, and inlines the file content (when under the size cap) as a
fenced code block.

These tests cover the pure parser + resolver; the API integration is
exercised by ``test_web_runs_api.py``.
"""

from __future__ import annotations

from smolcode.web.agent_runner import (
    _MAX_MENTION_BYTES,
    _attach_mentions,
    _parse_mentions,
)


# ---- TestParseMentions -----------------------------------------------------


class TestParseMentions:
    def test_no_mentions_returns_empty(self):
        result = _parse_mentions("just a plain task with no mentions")
        assert result == []

    def test_single_relative_mention(self):
        result = _parse_mentions("please review @src/foo.py")
        assert len(result) == 1
        assert result[0]["raw"] == "@src/foo.py"
        assert result[0]["path"] == "src/foo.py"

    def test_absolute_path_mention(self):
        result = _parse_mentions("see @/etc/hosts for context")
        assert len(result) == 1
        assert result[0]["path"] == "/etc/hosts"

    def test_multiple_mentions(self):
        result = _parse_mentions("compare @a.py and @b/c.py please")
        assert [r["path"] for r in result] == ["a.py", "b/c.py"]

    def test_mention_in_code_block_is_ignored(self):
        """A `@` inside a fenced code block is not a mention (avoids
        the user accidentally expanding example paths)."""
        task = "Look at:\n```python\n@not/a/mention.py\n```\nand also @real/mention.py"
        result = _parse_mentions(task)
        assert [r["path"] for r in result] == ["real/mention.py"]

    def test_traversal_attempt_rejected(self):
        """``@../etc/passwd`` is parsed but flagged for server-side rejection."""
        result = _parse_mentions("see @../etc/passwd")
        assert len(result) == 1
        assert result[0]["path"] == "../etc/passwd"
        # The PARSER does not reject; _attach_mentions does (next suite).

    def test_mention_with_spaces(self):
        """Whitespace terminates the path; only the first token is the path."""
        result = _parse_mentions("open @file.py and read it")
        assert result[0]["path"] == "file.py"

    def test_mention_at_end_of_line(self):
        result = _parse_mentions("check @pkg/mod.py\nthen summarise")
        assert result[0]["path"] == "pkg/mod.py"


# ---- TestAttachMentions ----------------------------------------------------


class TestAttachMentions:
    def test_no_mentions_returns_task_unchanged(self, tmp_path):
        task = "plain task"
        out = _attach_mentions(task, project_root=tmp_path)
        assert out == task

    def test_existing_file_inlined(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("print('hi')", encoding="utf-8")
        task = "review @foo.py"
        out = _attach_mentions(task, project_root=tmp_path)
        # The original task must still appear (verbatim).
        assert "review @foo.py" in out
        # And the file content must be embedded.
        assert "print('hi')" in out
        # And it must be fenced with the path as the language tag.
        assert "```foo.py" in out

    def test_missing_file_marked_unresolved(self, tmp_path):
        task = "review @missing.py"
        out = _attach_mentions(task, project_root=tmp_path)
        # Missing files are NOT inlined -- they are listed in an "unresolved"
        # section so the agent can choose to read them itself.
        assert "missing.py" in out
        assert "Unresolved" in out or "unresolved" in out or "could not" in out.lower()

    def test_path_traversal_rejected(self, tmp_path):
        task = "review @../escape.py"
        out = _attach_mentions(task, project_root=tmp_path)
        # The traversal attempt must NOT be resolved against the project
        # root; it should appear in the unresolved list, NOT inlined.
        assert "../escape.py" in out
        assert "```../escape.py" not in out

    def test_oversized_file_marked_unresolved(self, tmp_path):
        f = tmp_path / "big.py"
        # Write past the size cap.
        f.write_text("x" * (_MAX_MENTION_BYTES + 1), encoding="utf-8")
        task = "review @big.py"
        out = _attach_mentions(task, project_root=tmp_path)
        assert "big.py" in out
        # Content is NOT inlined (would exceed cap).
        assert "x" * 100 not in out

    def test_multiple_files_inlined_in_order(self, tmp_path):
        (tmp_path / "a.py").write_text("AAA", encoding="utf-8")
        (tmp_path / "b.py").write_text("BBB", encoding="utf-8")
        task = "compare @a.py and @b.py"
        out = _attach_mentions(task, project_root=tmp_path)
        a_idx = out.find("AAA")
        b_idx = out.find("BBB")
        assert a_idx != -1 and b_idx != -1
        assert a_idx < b_idx

    def test_absolute_path_mention_must_be_inside_project_root(self, tmp_path):
        f = tmp_path / "inside.py"
        f.write_text("INSIDE", encoding="utf-8")
        # Absolute mention OUTSIDE the project root must be rejected.
        task = "see @/etc/passwd"
        out = _attach_mentions(task, project_root=tmp_path)
        assert "/etc/passwd" in out
        assert "```/etc/passwd" not in out

    def test_binary_file_falls_through_to_unresolved(self, tmp_path):
        # Non-utf8 bytes should not crash the parser.
        (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
        task = "look at @blob.bin"
        out = _attach_mentions(task, project_root=tmp_path)
        assert "blob.bin" in out
        # No fenced content for the binary blob.
        assert "```blob.bin" not in out


# ---- TestAttachMentionsIntegration ---------------------------------------


class TestAttachMentionsIntegration:
    def test_full_audit_trail_in_returned_task(self, tmp_path):
        """The returned task must include a short header so the agent
        knows the mentions were already resolved + inlined (so it does
        NOT call ``read_file`` on them a second time)."""
        f = tmp_path / "x.py"
        f.write_text("x = 1", encoding="utf-8")
        task = "review @x.py"
        out = _attach_mentions(task, project_root=tmp_path)
        assert "Mentions" in out or "Attached" in out or "files attached" in out.lower()
        assert "review @x.py" in out
