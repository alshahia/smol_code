"""smolcode tools package (M2 + M3).

Tools are host-side: they run on the agent host (not inside the Docker
executor) and enforce PathPolicy + CommandPolicy before mutating state
or invoking a subprocess. See docs/architecture.md section 5.3 and
docs/security.md section 5-6.

Public surface:
    build_tools(tier, settings, workspace_path=None, mcp_configs=None)
        Assemble the right tool list for a tier. workspace_path defaults
        to settings.workspace (host path); pass an alternate path for
        docker-mode (where the container sees /workspace instead of the
        host path). mcp_configs is a list[MCPServerConfig]; when
        non-empty, MCP tools are opened and added to the returned list.

MCP lifecycle (M3, decision 0005):
    build_tools() opens MCP servers lazily via
    smolcode.tools.mcp_tools.build_mcp_tools. The opened servers are
    tracked in smolcode.tools._mcp_runtime._REGISTRY. The CLI calls
    close_all() in a try/finally to reap subprocesses. An atexit
    handler is also armed as a safety net.
"""

from __future__ import annotations

from ..config import Settings, Tier
from ._mcp_runtime import close_all
from .fs import build_fs_tools
from .git import build_git_tools
from .mcp_tools import MCPServerConfig, build_mcp_tools, load_mcp_config
from .policy import CommandPolicy, PathPolicy, PolicyViolation
from .shell import build_shell_tools


__all__ = [
    "build_tools",
    "CommandPolicy",
    "PathPolicy",
    "PolicyViolation",
    "MCPServerConfig",
    "load_mcp_config",
    "close_mcp_servers",
]


def build_tools(tier, settings, workspace_path=None, mcp_configs=None):
    """Assemble the Tool list for one (tier, settings) pair.

    Args:
        tier: Active tier.
        settings: Resolved settings.
        workspace_path: Path the tools treat as the workspace. Defaults
            to str(settings.workspace). For docker-mode execution,
            pass the container-side path (e.g. "/workspace") that is
            bind-mounted to the host workspace.
        mcp_configs: Optional list[MCPServerConfig]. When non-empty
            (and the tier allows MCP), MCP servers are spawned and
            their tools are appended to the returned Tool list. Servers
            that fail to start are logged and skipped; the remaining
            servers still contribute tools (decision 0005 section 4).
    """
    if not isinstance(tier, Tier):
        raise TypeError("tier must be a Tier instance")
    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")
    workspace = workspace_path or str(settings.workspace)
    command_policy = CommandPolicy(tier.commands)
    tools = []
    # M8: pass tier name + uploads_dir so write_file can enforce the
    # restricted-tier upload write-block. Both default to "" via
    # build_fs_tools' signature, so callers without M8 settings still work.
    uploads_dir_str = str(getattr(settings, "uploads_dir", "")) if getattr(settings, "uploads_dir", None) else ""
    tools.extend(build_fs_tools(workspace, tier=tier, uploads_dir=uploads_dir_str))
    tools.extend(build_shell_tools(command_policy))
    tools.extend(build_git_tools(command_policy, cwd=workspace))
    if mcp_configs:
        tools.extend(build_mcp_tools(tier, mcp_configs))
    return tools


def close_mcp_servers():
    """Close every registered MCP server (idempotent)."""
    close_all()
