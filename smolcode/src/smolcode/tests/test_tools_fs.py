"""Tests for tools/fs.py (read_file, write_file, list_dir)."""

from __future__ import annotations

import pytest

from smolcode.tools.fs import build_fs_tools


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def fs_tools(workspace):
    return {t.name: t for t in build_fs_tools(workspace)}


def test_build_fs_tools_returns_four(workspace):
    # M10: patch_file joined read_file/write_file/list_dir.
    tools = build_fs_tools(workspace)
    assert len(tools) == 4
    names = sorted(t.name for t in tools)
    assert names == ["list_dir", "patch_file", "read_file", "write_file"]


def test_read_file_inside_workspace(workspace, fs_tools):
    f = workspace / "x.txt"
    f.write_text("hello", encoding="utf-8")
    assert fs_tools["read_file"].forward(path=str(f)) == "hello"


def test_read_file_outside_workspace_rejected(workspace, fs_tools, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(PermissionError):
        fs_tools["read_file"].forward(path=str(outside))


def test_read_file_missing_rejected(workspace, fs_tools):
    with pytest.raises(PermissionError):
        fs_tools["read_file"].forward(path=str(workspace / "missing.txt"))


def test_write_file_creates_file(workspace, fs_tools):
    target = workspace / "subdir" / "new.txt"
    result = fs_tools["write_file"].forward(path=str(target), content="created")
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "created"
    assert result == str(target.resolve())


def test_write_file_overwrites_existing(workspace, fs_tools):
    f = workspace / "x.txt"
    f.write_text("old", encoding="utf-8")
    fs_tools["write_file"].forward(path=str(f), content="new")
    assert f.read_text(encoding="utf-8") == "new"


def test_write_file_outside_workspace_rejected(workspace, fs_tools, tmp_path):
    outside = tmp_path / "outside.txt"
    with pytest.raises(PermissionError):
        fs_tools["write_file"].forward(path=str(outside), content="bad")
    assert not outside.exists()


def test_list_dir_returns_entries(workspace, fs_tools):
    (workspace / "a.txt").write_text("a")
    (workspace / "b").mkdir()
    listing = fs_tools["list_dir"].forward(path=str(workspace))
    assert "a.txt" in listing
    assert "b/" in listing  # directory marker


def test_list_dir_empty(workspace, fs_tools):
    listing = fs_tools["list_dir"].forward(path=str(workspace))
    assert listing == "(empty)"


def test_list_dir_on_file_rejected(workspace, fs_tools):
    f = workspace / "x.txt"
    f.write_text("x")
    with pytest.raises(PermissionError):
        fs_tools["list_dir"].forward(path=str(f))


def test_read_file_on_directory_rejected(workspace, fs_tools):
    with pytest.raises(PermissionError):
        fs_tools["read_file"].forward(path=str(workspace))
