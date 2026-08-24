"""Tests for tools/__init__.py (build_tools factory)."""

from __future__ import annotations

import pytest

from smolcode.config import Tier, load_settings
from smolcode.tools import build_tools


def _settings_for_workspace(workspace):
    """Build a minimal Settings with default tiers."""
    return load_settings(cli_overrides={"workspace": str(workspace)})


def test_build_tools_returns_combined_list(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = _settings_for_workspace(ws)
    tier = settings.tiers["restricted"]
    tools = build_tools(tier, settings)
    names = sorted(t.name for t in tools)
    # M10: 4 fs (read_file, write_file, list_dir, patch_file) + 1 shell + 9 git = 14 tools.
    assert names == sorted(
        [
            "read_file",
            "write_file",
            "list_dir",
            "patch_file",
            "run",
            "git_status",
            "git_diff",
            "git_add",
            "git_commit",
            "git_log",
            "git_push",
            "git_clone",
            "git_fetch",
            "git_checkout",
        ]
    )


def test_build_tools_rejects_non_tier(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = _settings_for_workspace(ws)
    with pytest.raises(TypeError):
        build_tools("not a tier", settings)
    with pytest.raises(TypeError):
        build_tools(settings.tiers["restricted"], "not settings")


def test_build_tools_uses_tier_command_allowlist(tmp_path):
    """Custom tier with empty commands allowlist: shell tools reject all cmds."""
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = _settings_for_workspace(ws)
    empty_tier = Tier(
        name="custom",
        imports=(),
        commands=(),  # empty allowlist
        paths=(),
        network="none",
        network_allowlist=(),
        mcp_servers=(),
        max_steps=5,
        timeout_s=10.0,
        docker_image="x:y",
    )
    tools = build_tools(empty_tier, settings)
    shell_tool = next(t for t in tools if t.name == "run")
    with pytest.raises(PermissionError):
        shell_tool.forward(cmd="python", args=["-c", "print()"])


def test_build_tools_uses_workspace_path_policy(tmp_path):
    """The fs tools resolve paths under settings.workspace."""
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = _settings_for_workspace(ws)
    tools = build_tools(settings.tiers["restricted"], settings)
    write_tool = next(t for t in tools if t.name == "write_file")
    # Writing to ws/<file> should succeed.
    f = ws / "inside.txt"
    write_tool.forward(path=str(f), content="x")
    assert f.exists()
    # Writing to tmp_path/<file> (outside ws) should be rejected.
    outside = tmp_path / "outside.txt"
    with pytest.raises(PermissionError):
        write_tool.forward(path=str(outside), content="x")


def test_build_tools_workspace_path_override(tmp_path):
    """Passing workspace_path overrides settings.workspace for fs tools."""
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = _settings_for_workspace(ws)
    alt = tmp_path / "alt"
    alt.mkdir()
    tools = build_tools(settings.tiers["restricted"], settings, workspace_path=str(alt))
    write_tool = next(t for t in tools if t.name == "write_file")
    target = alt / "inside_alt.txt"
    write_tool.forward(path=str(target), content="x")
    assert target.exists()
