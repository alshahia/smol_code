"""Demo MCP server for smolcode M3 (decision 0005).

This server is shipped in `smolcode.tools` so users can wire it into
`mcp_config.json` as a working example. It is **not** registered by
default. v1 ships with zero MCP servers configured (per
`docs/architecture.md` section 6 and `docs/roadmap.md` section 6).
To enable it, add a block like this to `<workspace>/mcp_config.json`:

```json
{
  "servers": [
    {
      "name": "docs",
      "transport": "stdio",
      "command": ["python", "-m", "smolcode.tools._mcp_demo_server"],
      "tools": "readonly"
    }
  ]
}
```

Tools exposed (both readonly):
  - `search_docs(query: str) -> str`: keyword search over a tiny
    hardcoded corpus.
  - `get_doc(key: str) -> str`: fetch one entry by key.

Implementation note
-------------------
Uses `mcp.server.mcpserver.MCPServer` (the mcp 2.0.0 high-level
class). The older `mcp.server.fastmcp.FastMCP` was moved to a separate
`fastmcp` package and is not installed in this environment (decision
0005 section 2.2).
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer


# A tiny hardcoded corpus so the demo is fully self-contained.
_CORPUS: dict[str, str] = {
    "docker executor": (
        "smolagents DockerExecutor runs Python in a Jupyter kernel "
        "gateway container. The container is bind-mounted to the host "
        "workspace at /workspace and runs with network_mode=none for "
        "the restricted tier."
    ),
    "mcp": (
        "MCP (Model Context Protocol) is the tool integration layer "
        "used by smolcode. Servers are described in mcp_config.json "
        "and may expose read-only, read-write, or full tools."
    ),
    "tier": (
        "smolcode has three trust tiers: restricted (default; workspace "
        "only), elevated (workspace + declared extras; allow-listed "
        "network), and full_access (explicit, audited; broader scope)."
    ),
    "workspace": (
        "The workspace is a host directory that the restricted tier "
        "can read, write, and run commands in. It defaults to "
        "<repo>/workspace/ and is overridden via SMOLCODE_WORKSPACE."
    ),
}


mcp = MCPServer("smolcode-docs-demo")


@mcp.tool()
def search_docs(query: str) -> str:
    """Search the smolcode docs corpus for a query string.

    Returns matching snippets (key: value), one per line, or a message
    if nothing matched.
    """
    q = query.lower()
    matches: list[str] = []
    for key, value in _CORPUS.items():
        if q in key.lower() or q in value.lower():
            matches.append(key + ": " + value)
    if not matches:
        return "No docs found for query " + repr(query) + "."
    return "\n".join(matches)


@mcp.tool()
def get_doc(key: str) -> str:
    """Get a single doc entry by key.

    Returns "key: value" if found, or a not-found message listing the
    known keys.
    """
    value = _CORPUS.get(key)
    if value is None:
        return "Doc key " + repr(key) + " not found. Known keys: " + str(sorted(_CORPUS)) + "."
    return key + ": " + value


if __name__ == "__main__":
    mcp.run(transport="stdio")
    sys.exit(0)
