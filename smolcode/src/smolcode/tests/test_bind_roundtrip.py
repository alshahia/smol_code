"""Tests for tools/_bind.py + per-build class attribute binding (M2).

Why this test exists
--------------------
smolagents' Docker executor serialises a Tool by capturing the class
source via ``instance_to_source``, then on the remote side calls the
class with NO arguments. Any state that lives in ``__init__`` is
therefore lost. To preserve per-build state (workspace path, command
allowlist, git cwd) we use ``bind_attrs`` to generate a one-off
subclass whose state is baked in as CLASS attributes, and verify here
that:

1. ``validate_tool_attributes`` accepts the bound subclass.
2. ``instance_to_source`` emits the class with the new class attrs.
3. The remote-side ``exec`` produces a Tool whose attribute reflects
   the bound value.
4. ``forward()`` on the remote instance uses the bound value.
"""

from __future__ import annotations

import pytest
from smolagents.tools import get_tools_definition_code

from smolcode.tools import CommandPolicy
from smolcode.tools._bind import bind_attrs
from smolcode.tools.fs import _ReadFileTool, build_fs_tools
from smolcode.tools.git import build_git_tools
from smolcode.tools.shell import build_shell_tools


def _remote_instance(tool):
    """Mirror what the Docker executor does: capture source + exec it."""
    code = get_tools_definition_code({tool.name: tool})
    ns = {}
    exec(code, ns)  # noqa: S102 (intentional eval)
    return ns[tool.name]


class TestBindAttrsHelper:
    def test_returns_subclass_with_attrs(self):
        sub = bind_attrs(_ReadFileTool, {"workspace": "/w"})
        assert issubclass(sub, _ReadFileTool)
        assert sub.workspace == "/w"

    def test_subclass_instance_inherits_attrs(self):
        sub = bind_attrs(_ReadFileTool, {"workspace": "/w"})
        inst = sub()
        assert inst.workspace == "/w"

    def test_subclass_has_source(self):
        sub = bind_attrs(_ReadFileTool, {"workspace": "/w"})
        assert hasattr(sub, "__source__")
        assert "_ReadFileTool" in sub.__source__


class TestFsRoundtrip:
    def test_remote_read_file_sees_bound_workspace(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        tools = {t.name: t for t in build_fs_tools(str(ws))}
        remote = _remote_instance(tools["read_file"])
        assert remote.workspace == str(ws)

    def test_remote_write_then_read_round_trip(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        tools = {t.name: t for t in build_fs_tools(str(ws))}
        remote_write = _remote_instance(tools["write_file"])
        remote_read = _remote_instance(tools["read_file"])
        target = str(ws / "x.txt")
        remote_write.forward(path=target, content="ok")
        assert remote_read.forward(path=target) == "ok"

    def test_remote_write_outside_workspace_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        tools = {t.name: t for t in build_fs_tools(str(ws))}
        remote = _remote_instance(tools["write_file"])
        outside = str(tmp_path / "outside.txt")
        with pytest.raises(PermissionError):
            remote.forward(path=outside, content="bad")


class TestShellRoundtrip:
    def test_remote_run_sees_bound_allowlist(self):
        policy = CommandPolicy(("python", "git"))
        tools = build_shell_tools(policy)
        remote = _remote_instance(tools[0])
        assert remote.allowlist == "python|git"

    def test_remote_run_allowed_command(self):
        policy = CommandPolicy(("python",))
        tools = build_shell_tools(policy)
        remote = _remote_instance(tools[0])
        result = remote.forward(cmd="python", args=["-c", "print('M2')"])
        assert "M2" in result
        assert "returncode: 0" in result

    def test_remote_run_disallowed_command_rejected(self):
        policy = CommandPolicy(("python",))
        tools = build_shell_tools(policy)
        remote = _remote_instance(tools[0])
        with pytest.raises(PermissionError):
            remote.forward(cmd="curl", args=["http://example.com"])


class TestGitRoundtrip:
    def test_remote_git_status_sees_bound_state(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        policy = CommandPolicy(("git",))
        tools = {t.name: t for t in build_git_tools(policy, cwd=str(repo))}
        remote = _remote_instance(tools["git_status"])
        assert remote.allowlist == "git"
        assert remote.cwd == str(repo)
