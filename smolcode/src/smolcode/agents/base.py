"""Agent factory (M1 + M2 + M3 wiring).

`make_agent(tier, settings, model)` is the single place a CodeAgent is
constructed. M2 wires the workspace tools (fs + shell + git) and filters
non-stdlib entries out of `tier.imports` before passing them to
`additional_authorized_imports`. M3 wires MCP tools via the
`mcp_configs` argument (loaded from `SMOLCODE_MCP_CONFIG`).

Docker-mode workspace handling: the host workspace path is bind-mounted
into the container at `/workspace`. Tools use `/workspace` as their
workspace path so writes inside the container appear in the host
workspace. For local mode, tools use the host workspace directly.

MCP lifecycle (decision 0005): `build_tools` opens MCP servers via
`smolcode.tools._mcp_runtime` and registers them. The CLI calls
`close_mcp_servers()` in a try/finally to reap subprocesses; an
atexit handler is also armed.
"""

from __future__ import annotations

import sys

from smolagents import CodeAgent

from ..config import Settings, Tier
from ..models import build_model
from ..sandbox_guard import wrap_executor
from ..tools import build_tools
from .prompting import sandbox_boundary_instructions


def _resolve_mcp_configs(settings):
    """Load MCP configs from SMOLCODE_MCP_CONFIG if set.

    v1 default: empty list (zero MCP servers). The CLI sets
    SMOLCODE_MCP_CONFIG before calling `make_agent` to opt in.
    """
    import os

    from ..tools import load_mcp_config

    path = os.environ.get("SMOLCODE_MCP_CONFIG")
    if not path:
        return []
    return load_mcp_config(path)


__all__ = ["make_agent"]

# Path inside the Docker container where the host workspace is bind-mounted.
_CONTAINER_WORKSPACE = "/workspace"

# Python 3.10+ exposes the full stdlib name set via sys.stdlib_module_names.
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", set()))


def _filter_third_party_imports(imports):
    """Return only entries in `imports` that are NOT in the stdlib.

    smolagents RemotePythonExecutor.install_packages attempts to
    `pip install` every entry in `additional_authorized_imports`.
    Stdlib names fail harmlessly but pollute the log.
    """
    out = []
    for name in imports:
        top = name.split(".")[0]
        if top in _STDLIB:
            continue
        out.append(name)
    return out


def _executor_kwargs_for(executor_type, tier, settings):
    """Build executor_kwargs filtered for the executor type.

    For Docker, includes container_run_kwargs with:
      * bind mount from the host workspace to /workspace so host-side
        tools (write_file, run, git, etc.) can mutate files inside the
        container and have those changes visible to the host,
      * ``auto_remove=True`` so Docker removes the container when its
        main process exits (normally when the agent's run ends). This
        avoids stale containers piling up when the server is restarted.

    M16 (decision 0020) adds for the **elevated** tier only:
      * ``cap_add=["NET_ADMIN"]`` so the container's ENTRYPOINT
        (iptables-init.sh) can apply the kernel-level egress firewall,
      * ``environment={"ELEVATED_NET_ALLOWLIST": ..., ...}`` carrying
        the operator-supplied CIDR allowlist to the init script.

    The audit log gets a WARN entry when the kill switch
    ``ELEVATED_DISABLE_IPTABLES=1`` is active (see audit.py).
    """
    if executor_type == "docker":
        host_ws = str(settings.workspace)
        run_kwargs = {
            "volumes": {host_ws: {"bind": _CONTAINER_WORKSPACE, "mode": "rw"}},
            "auto_remove": True,
        }
        if tier.name == "elevated":
            # M16: kernel-level network enforcement (decision 0020).
            # Lazy import keeps base.py import-cost flat for tests
            # that never exercise the elevated Docker executor.
            from ..container import elevated_container_env

            run_kwargs["cap_add"] = ["NET_ADMIN"]
            run_kwargs["environment"] = elevated_container_env(tier)
        return {
            "image_name": tier.docker_image,
            "container_run_kwargs": run_kwargs,
        }
    return {}


def _workspace_for(executor_type, settings):
    """Return the workspace path to bind into tools.

    For local executor: settings.workspace (host path).
    For docker: /workspace (container path; bind-mounted from host).
    """
    if executor_type == "docker":
        return _CONTAINER_WORKSPACE
    return str(settings.workspace)


def make_agent(tier, settings, model=None, *, max_steps=None, mcp_configs=None, tools_override=None):
    """Build a CodeAgent for one (tier, settings) pair.

    Args:
        mcp_configs: Optional list[MCPServerConfig]. If None, the MCP
            config is loaded from the SMOLCODE_MCP_CONFIG env var (which
            the CLI sets from --mcp-config or settings). Pass an empty
            list to skip MCP entirely.
        tools_override: Optional list of pre-built Tool instances. When
            provided, the factory skips build_tools() and uses this list
            directly. Used by specialists (M5, decision 0008 D6) to narrow
            the toolset.
    """
    if not isinstance(tier, Tier):
        raise TypeError("tier must be a Tier instance")
    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")
    if model is None:
        model = build_model(settings)
    workspace_path = _workspace_for(settings.executor, settings)
    if mcp_configs is None:
        mcp_configs = _resolve_mcp_configs(settings)
    if tools_override is None:
        tools = build_tools(tier, settings, workspace_path=workspace_path, mcp_configs=mcp_configs)
    else:
        # Specialist: caller has already narrowed the toolset.
        tools = list(tools_override)
    imports = _filter_third_party_imports(tier.imports)
    steps = max_steps if max_steps is not None else tier.max_steps
    executor_kwargs = _executor_kwargs_for(settings.executor, tier, settings)
    # Sandbox-boundary note: tells the LLM `smolcode` is host-only and
    # not available inside the elevated/restricted/full_access Docker
    # sandbox (decision 0021; bugfix for the "create todo app" Web UI
    # failure that ended in `ModuleNotFoundError: No module named
    # 'smolcode'`). For non-sandbox tiers (orchestrator, which runs on
    # the host with executor_type='local'), this is "" and a no-op.
    instructions = sandbox_boundary_instructions(tier)
    agent = CodeAgent(
        tools=tools,
        model=model,
        max_steps=steps,
        additional_authorized_imports=imports,
        executor_type=settings.executor,
        executor_kwargs=executor_kwargs,
        instructions=instructions,
    )
    # Decision 0023: defense-in-depth. The system-prompt note alone is
    # not enough -- the model often ignores it and writes
    # ``import smolcode`` or ``!pip install smolcode``. Wrap the executor
    # in a Proxy that pre-scans every code block and raises a clear
    # ``SandboxBoundaryViolation`` if the model tries to reach a
    # host-only module. The error message tells the model exactly how to
    # recover. No-op for non-sandbox tiers (orchestrator runs on the
    # host where ``smolcode`` IS available).
    if agent.python_executor is not None:
        agent.python_executor = wrap_executor(agent.python_executor, tier)
    return agent
