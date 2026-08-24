"""MCP tool wrapper for smolcode M3 (decision 0005).

Public surface
--------------
    MCPServerConfig(name, transport, command=None, url=None, tools_mode)
        Dataclass for one entry in mcp_config.json.
    load_mcp_config(path) -> list[MCPServerConfig]
        JSON loader. Raises MCPConfigError on schema violations.
    classify_tool_name(name, mode) -> str
        Returns one of: ok, shadowed, violates_mode.
    SHADOWED_TOOL_NAMES = frozenset({final_answer, python_interpreter})
    build_mcp_tools(tier, configs) -> list[Tool]
        Opens each server, fetches tool list, applies the readonly /
        readwrite / full filter, builds _MCPToolBase subclasses.

Tier mode map (from docs/architecture.md section 6 + docs/security.md section 3):
    restricted  accepts readonly only
    elevated    accepts readonly + readwrite
    full_access accepts readonly + readwrite + full

The Tool subclass follows the M2 bind_attrs lesson (decision 0004):
    - All per-build state is class attrs of a one-off subclass.
    - forward() references only self.X, local imports, and arg names
      (per MethodChecker constraints).
    - The live MCPStdioServer connection lives in _mcp_runtime._REGISTRY
      and is reached by string server_id.

Attribution
-----------
The MCP integration design is described in
docs/decisions/0005-m3-mcp-integration.md.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Literal

from smolagents.tools import Tool

from . import _mcp_runtime
from ._bind import bind_attrs


__all__ = [
    "MCPServerConfig",
    "load_mcp_config",
    "classify_tool_name",
    "SHADOWED_TOOL_NAMES",
    "TOOLS_MODES",
    "TIER_ALLOWED_MODES",
    "build_mcp_tools",
]


# Tool names that smolagents reserves; MCP tools with these names would
# shadow built-ins and confuse the agent loop.
SHADOWED_TOOL_NAMES: frozenset[str] = frozenset({"final_answer", "python_interpreter"})

# MCP mode names per docs/architecture.md section 6.
TOOLS_MODES = ("readonly", "readwrite", "full")

# Per-tier mode allow-list (decision 0005).
TIER_ALLOWED_MODES: dict[str, tuple[str, ...]] = {
    "restricted": ("readonly",),
    "elevated": ("readonly", "readwrite"),
    "full_access": ("readonly", "readwrite", "full"),
}

# Readonly tool-name prefix check.
_READONLY_PREFIX_RE = re.compile(r"^(get|search|read|list)_")


@dataclass(frozen=True)
class MCPServerConfig:
    """One MCP server entry from mcp_config.json."""

    name: str
    transport: Literal["stdio", "streamable-http"]
    command: tuple[str, ...] | None
    url: str | None
    tools_mode: str


class MCPConfigError(ValueError):
    """Raised when mcp_config.json violates the schema."""


def _require_str(obj, key, ctx):
    val = obj.get(key)
    if not isinstance(val, str):
        raise MCPConfigError(ctx + ": '" + key + "' must be a string, got " + type(val).__name__)
    return val


def _require_list_of_str(obj, key, ctx):
    val = obj.get(key)
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise MCPConfigError(ctx + ": '" + key + "' must be a list of strings, got " + type(val).__name__)
    return tuple(val)


def load_mcp_config(path):
    """Load mcp_config.json from path. Returns [] if path does not exist.

    Raises MCPConfigError on schema violations.
    """
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise MCPConfigError(
            str(p) + ": invalid JSON (" + e.msg + " at line " + str(e.lineno) + " col " + str(e.colno) + ")"
        ) from e
    if not isinstance(raw, dict):
        raise MCPConfigError(str(p) + ": top-level value must be an object, got " + type(raw).__name__)
    servers = raw.get("servers")
    if servers is None:
        return []
    if not isinstance(servers, list):
        raise MCPConfigError(str(p) + ": 'servers' must be a list, got " + type(servers).__name__)

    out = []
    for i, srv in enumerate(servers):
        ctx = str(p) + ": servers[" + str(i) + "]"
        if not isinstance(srv, dict):
            raise MCPConfigError(ctx + ": must be an object, got " + type(srv).__name__)
        name = _require_str(srv, "name", ctx)
        transport = _require_str(srv, "transport", ctx)
        if transport not in ("stdio", "streamable-http"):
            raise MCPConfigError(ctx + ": 'transport' must be 'stdio' or 'streamable-http', got " + repr(transport))
        mode = _require_str(srv, "tools", ctx)
        if mode not in TOOLS_MODES:
            raise MCPConfigError(ctx + ": 'tools' must be one of " + repr(TOOLS_MODES) + ", got " + repr(mode))
        command = None
        url = None
        if transport == "stdio":
            command = _require_list_of_str(srv, "command", ctx)
        else:
            url = _require_str(srv, "url", ctx)
        out.append(MCPServerConfig(name=name, transport=transport, command=command, url=url, tools_mode=mode))
    return out


def classify_tool_name(name, mode):
    """Classify an MCP tool name against a server's declared mode.

    Returns:
        ok              name is allowed under mode.
        shadowed        name collides with a smolagents built-in.
        violates_mode   name does not satisfy the mode's prefix rule.

    Note: violates_mode only ever fires for readonly servers.
    """
    if name in SHADOWED_TOOL_NAMES:
        return "shadowed"
    if mode == "readonly":
        if not _READONLY_PREFIX_RE.match(name):
            return "violates_mode"
    return "ok"


class _MCPToolBase(Tool):
    """Host-side Tool wrapping one MCP tool call.

    Per-build state is supplied via bind_attrs:
        name           (str)  name exposed to the model
        description    (str)  tool description from the MCP server
        inputs         (dict) converted JSON Schema
        output_type    (str)  string for all MCP tools in v1
        server_id      (str)  key into _mcp_runtime._REGISTRY
        tool_name      (str)  server-side tool name

    The forward body uses only stdlib + assigned names + self.X so it
    passes smolagents MethodChecker (decision 0004 + 0005).
    """

    name = ""
    description = ""
    inputs = {}
    output_type = "string"
    server_id = ""
    tool_name = ""
    # The forward signature is **kwargs (MCP tools can have any schema);
    # smolagents normally rejects this when 'inputs' lists specific keys,
    # but we own the call path on the host and pass kwargs as a dict to
    # the MCP client. decision 0005 section 5.
    skip_forward_signature_validation = True

    def forward(self, **kwargs):
        import sys as _sys

        runtime_mod = _sys.modules.get("smolcode.tools._mcp_runtime")
        if runtime_mod is None:
            raise RuntimeError("MCP runtime module not importable")
        client = runtime_mod._REGISTRY.get(self.server_id)
        if client is None:
            raise RuntimeError("MCP server " + repr(self.server_id) + " not registered (was it closed?)")
        if not kwargs:
            return client.call_tool(self.tool_name, {})
        return client.call_tool(self.tool_name, dict(kwargs))


_AUTHORIZED_TYPES = {"string", "integer", "number", "boolean", "array", "object", "null"}


def _json_schema_to_inputs(schema):
    """Convert one MCP JSON Schema object to a smolagents inputs dict."""
    out = {}
    props = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    for key, spec in props.items():
        if not isinstance(spec, dict):
            continue
        jtype = spec.get("type", "string")
        if jtype not in _AUTHORIZED_TYPES:
            jtype = "any"
        desc = spec.get("description") or ""
        entry = {"type": jtype, "description": desc}
        if key not in required:
            entry["nullable"] = True
        out[key] = entry
    return out


def _exposed_tool_name(server_name, tool_name):
    """Compute the tool name exposed to smolagents.

    Prefixed with <server_name>__ so two servers can declare the same
    tool name without collision.
    """
    return server_name + "__" + tool_name


def _server_id_for(server_name, counter):
    return server_name + "-" + str(counter)


def build_mcp_tools(tier, configs):
    """Open each MCP server, fetch tools, classify, build host-side Tools.

    Per decision 0005 section 4: failures are partial.
    """
    if not configs:
        return []

    tier_modes = TIER_ALLOWED_MODES.get(tier.name, ())
    if not tier_modes:
        return []

    tools = []
    counter = 0
    for cfg in configs:
        if cfg.tools_mode not in tier_modes:
            continue
        if cfg.transport != "stdio":
            continue
        if not cfg.command:
            continue
        counter += 1
        server_id = _server_id_for(cfg.name, counter)
        server = _mcp_runtime.MCPStdioServer(
            name=cfg.name,
            command=cfg.command[0],
            args=list(cfg.command[1:]),
        )
        try:
            server.connect()
        except Exception as e:
            print("mcp: server " + repr(cfg.name) + " failed to connect: " + str(e), file=sys.stderr)
            try:
                server.close()
            except Exception:
                pass
            continue
        try:
            server_tools = server.list_tools()
        except Exception as e:
            print("mcp: server " + repr(cfg.name) + " failed to list tools: " + str(e), file=sys.stderr)
            try:
                server.close()
            except Exception:
                pass
            continue
        _mcp_runtime.register(server_id, server)
        used_names = set()
        for info in server_tools:
            if not isinstance(info, dict):
                continue
            raw_name = info.get("name", "")
            if not isinstance(raw_name, str) or not raw_name:
                continue
            cls = classify_tool_name(raw_name, cfg.tools_mode)
            if cls != "ok":
                print(
                    "mcp: server " + repr(cfg.name) + " tool " + repr(raw_name) + " rejected (" + cls + ")",
                    file=sys.stderr,
                )
                continue
            exposed = _exposed_tool_name(cfg.name, raw_name)
            if exposed in used_names:
                continue
            used_names.add(exposed)
            description = info.get("description") or ""
            if not isinstance(description, str):
                description = ""
            inputs = _json_schema_to_inputs(info.get("inputSchema", {}) or {})
            output_type = "string"
            new_cls = bind_attrs(
                _MCPToolBase,
                {
                    "name": exposed,
                    "description": description,
                    "inputs": inputs,
                    "output_type": output_type,
                    "server_id": server_id,
                    "tool_name": raw_name,
                },
            )
            tools.append(new_cls())
    return tools
