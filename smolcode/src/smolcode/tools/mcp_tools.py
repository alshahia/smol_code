"""MCP tool wrapper for smolcode M3 (decision 0005).

Public surface
--------------
    MCPServerConfig(name, transport, command=None, url=None, tools_mode)
        Dataclass for one entry in mcp_config.json.
    load_mcp_config(path) -> list[MCPServerConfig]
        JSON loader. Raises MCPConfigError on schema violations.
    tool_is_allowed(cfg, name) -> bool
        Phase 6 (6.5) replacement for the old name-prefix classifier.
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

import fnmatch
import json
import sys
import uuid
from dataclasses import dataclass, field
from typing import Literal

from smolagents.tools import Tool

from . import _mcp_runtime
from ._bind import bind_attrs


__all__ = [
    "MCPServerConfig",
    "load_mcp_config",
    "tool_is_allowed",
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

# Phase 6 (6.5): the readonly tool-name prefix check is GONE.
#
# It read 'a name beginning get_/search_/read_/list_ is safe', but the name
# comes from the MCP server, which is the untrusted side of the boundary. A
# server could ship a destructive tool called get_nuke and pass the gate
# unimpeded. Safety is now an explicit operator-curated allowlist per
# server (cfg.allow), and a tool the operator allowlists that still looks
# destructive is routed through smolcode.destructive instead of trusted.
# _READONLY_PREFIX_RE was removed rather than left beside the new control,
# so it cannot be quietly re-adopted.


@dataclass(frozen=True)
class MCPServerConfig:
    """One MCP server entry from mcp_config.json.

    Phase 6 (6.5) added three fields, all of them default-deny:
      allow      exact tool names (or shell globs) the operator exposes.
                Empty means NOTHING is exposed from this server.
      env        literal env values for the child process.
      env_allow  host env var NAMES the child may read.
    """

    name: str
    transport: Literal["stdio", "streamable-http"]
    command: tuple[str, ...] | None
    url: str | None
    tools_mode: str
    allow: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    env_allow: tuple[str, ...] = ()
    timeout_s: float = 30.0


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


def _optional_list_of_str(obj, key, ctx):
    val = obj.get(key)
    if val is None:
        return ()
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
        # Phase 6 (6.5). allow/env/env_allow/timeout_s are all optional and
        # all default-deny: an entry that omits them exposes no tools and
        # passes the child no credentials.
        allow = _optional_list_of_str(srv, "allow", ctx)
        env_allow = _optional_list_of_str(srv, "env_allow", ctx)
        env = {}
        raw_env = srv.get("env")
        if raw_env is not None:
            if not isinstance(raw_env, dict):
                raise MCPConfigError(ctx + ": 'env' must be an object, got " + type(raw_env).__name__)
            for k, v in raw_env.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise MCPConfigError(ctx + ": 'env' keys and values must be strings")
            env = dict(raw_env)
        timeout_s = 30.0
        raw_timeout = srv.get("timeout_s")
        if raw_timeout is not None:
            if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, (int, float)):
                raise MCPConfigError(ctx + ": 'timeout_s' must be a number, got " + type(raw_timeout).__name__)
            if raw_timeout <= 0:
                raise MCPConfigError(ctx + ": 'timeout_s' must be positive, got " + repr(raw_timeout))
            timeout_s = float(raw_timeout)
        out.append(
            MCPServerConfig(
                name=name,
                transport=transport,
                command=command,
                url=url,
                tools_mode=mode,
                allow=allow,
                env=env,
                env_allow=env_allow,
                timeout_s=timeout_s,
            )
        )
    return out


def tool_is_allowed(cfg, name):
    """Phase 6 (6.5): may this server expose this tool to the agent?

    Default-deny. A tool is exposed only if the operator listed it in
    cfg.allow, either exactly or through a shell glob. An empty allow
    list exposes NOTHING, which is the correct outcome for a server whose
    tool inventory the operator has not reviewed.

    Returns False for smolagents-reserved names regardless of cfg.allow:
    a server declaring final_answer must not be able to shadow it, and
    that must hold even if an operator allowlists it by mistake.
    """
    if not isinstance(name, str) or not name:
        return False
    if name in SHADOWED_TOOL_NAMES:
        return False
    if name in cfg.allow:
        return True
    for pattern in cfg.allow:
        if pattern != name and fnmatch.fnmatchcase(name, pattern):
            return True
    return False


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
    # Phase 6 (6.5): host-decided destructive policy, same contract as the
    # shell and git tools. Only an explicit "allow" permits a call that
    # smolcode.destructive classifies as destructive.
    destructive_policy = "deny"
    # Operator-declared: this tool mutates or destroys even if its name
    # does not look like it. Forces the gate regardless of the verb table.
    force_destructive = False
    # The forward signature is **kwargs (MCP tools can have any schema);
    # smolagents normally rejects this when 'inputs' lists specific keys,
    # but we own the call path on the host and pass kwargs as a dict to
    # the MCP client. decision 0005 section 5.
    skip_forward_signature_validation = True

    def forward(self, **kwargs):
        import sys as _sys

        # Phase 6 (6.5): MCP calls are routed through the destructive
        # classifier. They previously had no gate at all, on the reasoning
        # that tier filtering already covered them -- but that filtering was
        # a prefix guess over server-supplied names. MCP tools execute on
        # the HOST, outside every container, so an ungated one is the worst
        # case in the system rather than a marginal one.
        from smolcode.destructive import is_destructive as _is_dest

        if _is_dest(self.name, kwargs, destructive_override=self.force_destructive):
            if self.destructive_policy != "allow":
                raise PermissionError(
                    "destructive MCP tool blocked: "
                    + str(self.name)
                    + " (policy="
                    + repr(self.destructive_policy)
                    + ")"
                )

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


# Phase 6 (6.5): registry ids must be globally unique.
#
# The pre-fix form was server_name + '-' + str(counter), and counter was a
# local that restarted at 0 on every build_mcp_tools() call. Building tools
# twice for the same server therefore produced the SAME id, and
# _mcp_runtime.register() silently rebound every already-built Tool to the
# second server object -- the first agent's tools then called a different
# server, or a closed one. The counter is kept in the signature only so
# callers and logs still read naturally; uniqueness comes from uuid4.
_ID_SALT = uuid.uuid4().hex[:6]


def _server_id_for(server_name, counter):
    # counter is deliberately still accepted: it keeps the id readable in
    # logs and keeps existing call sites honest about which server this is.
    return server_name + "-" + str(counter) + "-" + _ID_SALT + "-" + uuid.uuid4().hex[:8]


def build_mcp_tools(tier, configs, destructive_policy="deny"):
    """Open each MCP server, fetch tools, filter, build host-side Tools.

    Per decision 0005 section 4: failures are partial.

    Phase 6 (6.5): destructive_policy is bound into every built tool, so a
    destructive MCP call obeys the same host-decided contract as run and
    git_push. MCP tools run on the HOST, outside any container, so this is
    the boundary that matters most.
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
            env=dict(cfg.env),
            env_allow=cfg.env_allow,
            timeout_s=cfg.timeout_s,
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
            if not tool_is_allowed(cfg, raw_name):
                print(
                    "mcp: server "
                    + repr(cfg.name)
                    + " tool "
                    + repr(raw_name)
                    + " not in the operator allowlist; refusing to expose it",
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
                    "destructive_policy": str(destructive_policy or "deny"),
                },
            )
            tools.append(new_cls())
    return tools
