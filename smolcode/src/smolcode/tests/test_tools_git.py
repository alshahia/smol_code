"""Tests for tools/git.py (git wrappers)."""

from __future__ import annotations

import subprocess

import pytest

from smolcode.tools import CommandPolicy
from smolcode.tools.git import build_git_tools


@pytest.fixture
def git_repo(tmp_path):
    """A fresh git repo with one commit (initial)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(repo)], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test"], check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True, text=True)
    f = repo / "a.txt"
    f.write_text("a")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True, text=True)
    return repo


@pytest.fixture
def git_tools(git_repo):
    policy = CommandPolicy(("git",))
    return {t.name: t for t in build_git_tools(policy, cwd=str(git_repo))}


def test_build_git_tools_returns_nine(git_tools):
    expected = {
        "git_status",
        "git_diff",
        "git_add",
        "git_commit",
        "git_log",
        "git_push",
        "git_clone",
        "git_fetch",
        "git_checkout",
    }
    assert set(git_tools.keys()) == expected


def test_git_status_clean(git_repo, git_tools):
    result = git_tools["git_status"].forward()
    assert "returncode: 0" in result
    # nothing to commit in a clean tree
    assert "nothing to commit" in result or "clean" in result.lower() or "On branch" in result


def test_git_status_dirty(git_repo, git_tools):
    (git_repo / "new.txt").write_text("new")
    result = git_tools["git_status"].forward()
    assert "returncode: 0" in result
    assert "new.txt" in result


def test_git_log(git_repo, git_tools):
    result = git_tools["git_log"].forward(max_count=5)
    assert "returncode: 0" in result
    assert "initial" in result


def test_git_log_max_count_validated(git_repo, git_tools):
    with pytest.raises(PermissionError):
        git_tools["git_log"].forward(max_count=0)
    with pytest.raises(PermissionError):
        git_tools["git_log"].forward(max_count=1001)
    with pytest.raises(PermissionError):
        git_tools["git_log"].forward(max_count="not an int")


def test_git_add_and_commit(git_repo, git_tools):
    (git_repo / "b.txt").write_text("b")
    add_result = git_tools["git_add"].forward(paths=[str(git_repo / "b.txt")])
    assert "returncode: 0" in add_result
    commit_result = git_tools["git_commit"].forward(message="add b")
    assert "returncode: 0" in commit_result
    log_result = git_tools["git_log"].forward(max_count=2)
    assert "add b" in log_result


def test_git_commit_empty_message_rejected(git_repo, git_tools):
    with pytest.raises(PermissionError):
        git_tools["git_commit"].forward(message="")


def test_git_diff_no_changes(git_repo, git_tools):
    result = git_tools["git_diff"].forward(staged=False, extra_args=[])
    assert "returncode: 0" in result


def test_git_diff_with_changes(git_repo, git_tools):
    (git_repo / "a.txt").write_text("a-modified")
    result = git_tools["git_diff"].forward(staged=False, extra_args=[])
    assert "returncode: 0" in result
    assert "a-modified" in result


def test_git_diff_staged(git_repo, git_tools):
    (git_repo / "a.txt").write_text("a-modified-staged")
    subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True, capture_output=True)
    result = git_tools["git_diff"].forward(staged=True, extra_args=[])
    assert "returncode: 0" in result
    assert "a-modified-staged" in result


def test_git_add_empty_rejected(git_repo, git_tools):
    with pytest.raises(PermissionError):
        git_tools["git_add"].forward(paths=[])


def test_git_checkout_requires_target(git_repo, git_tools):
    with pytest.raises(PermissionError):
        git_tools["git_checkout"].forward(target="", create=False)


def test_git_push_requires_remote(git_repo, git_tools):
    with pytest.raises(PermissionError):
        git_tools["git_push"].forward(remote="", branch="main")


def test_git_fetch_requires_remote(git_repo, git_tools):
    with pytest.raises(PermissionError):
        git_tools["git_fetch"].forward(remote="")


def test_git_clone_requires_url(git_repo, git_tools):
    with pytest.raises(PermissionError):
        git_tools["git_clone"].forward(url="", directory="")
