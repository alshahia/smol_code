# 0005 — Milestone 3 MCP integration: hand-rolled sync stdio client

**Date:** 2026-08-19
**Status:** active
**Supersedes:** n/a
**Related:** [`docs/roadmap.md` §6](../roadmap.md), [`docs/architecture.md` §6](../architecture.md), [`docs/security.md` §3.1, §7.4](../security.md), [`0004-m2-workspace-tools.md`](./0004-m2-workspace-tools.md)

---

## 1. Context

M3 wires the **Model Context Protocol** (MCP) into smolcode. The
architecture (`docs/architecture.md` §6) commits to:

- an `mcp_config.json` schema (server name, transport, command/url, `tools` mode);
- per-tier mode filtering (`readonly` ⊂ restricted+elevated;
  `readwrite` ⊂ elevated+full_access; `full` ⊂ full_access);
- shadow-name rejection (`final_answer`, `python_interpreter`);
- one demo MCP server, usable by the `restricted` tier for the M3 end-to-end
  test (`smolcode --tier restricted "search the docs for 'docker executor'"`).

The user's M0 brief and the M3 sketch agreed: **v1 ships with zero MCP
servers configured by default**; the demo lives in `docs/` as an opt-in
example. This decision is **not** about whether MCP is integrated — that is
already decided — it is about **how** we integrate it given the constraints
we discovered during the M3 inspection pass.

## 2. Constraints discovered during inspection

The M2 inspection (`tools/_bind.py`) already validated two patterns we have
to honour here:

- `MethodChecker` (in `smolagents/tool_validation.py:11-151`) AST-walks
  every method of every `Tool` subclass and rejects names that are not
  builtin, stdlib-module, argument, `self`, class-attribute, import, or
  in-function assigned. **`forward()` cannot reference module-level
  functions or module-level globals** unless they are imported INSIDE the
  method body or exposed as class attributes.
- `validate_tool_attributes` (in `smolagents/tool_validation.py:157-249`)
  AST-walks the class body and rejects class attributes whose `ast.walk`
  yields anything other than `Constant`, `Dict`, `List`, or `Set`. **No
  function references, no module instances, no live objects** as class
  attributes — only literal constants and dict/list/set literals are
  accepted.

Three new constraints surfaced during the M3 inspection:

### 2.1 `mcpadapt` is broken against mcp 2.0.0

`smolagents[mcp]` depends on `mcpadapt` 0.1.20. On import it does:

```python
from mcp.client.streamable_http import streamablehttp_client
```

mcp 2.0.0 renamed `streamablehttp_client` → `streamable_http_client`. Result:

```
ImportError: cannot import name 'streamablehttp_client' from
'mcp.client.streamable_http'. Did you mean: 'streamable_http_client'?
```

So `smolagents.MCPClient` (which wraps `mcpadapt.MCPAdapt`) is unusable in
this environment. This blocks every documented "use the smolagents MCP
client" pattern.

### 2.2 `mcp.server.fastmcp` no longer ships in the `mcp` package

`FastMCP` (the high-level decorator-based server framework) was moved to a
separate `fastmcp` package in mcp 2.0.0. The `mcp` package on this host
exposes `mcp.server.mcpserver.MCPServer` instead — same add_tool / tool
decorator / run(transport="stdio") surface, different module path. Most
third-party tutorials and `smolagents`' own test fixtures still reference
the old `from mcp.server.fastmcp import FastMCP` import; those will fail
on a fresh mcp 2.0 install.

### 2.3 The container cannot import `smolcode`

The `restricted.Dockerfile` (per `tools/../docker/restricted.Dockerfile`)
ships `python:3.12-bullseye` + `jupyter_kernel_gateway` only. The
`smolcode` package is not installed in the container and never will be
(container is the **code-execution** environment, not the tool host).
This means:

- Any `Tool.forward()` body that does `from smolcode.tools import _mcp_runtime`
  (or equivalent) will **parse** on the host (MethodChecker only sees the
  AST) and **fail at exec time** in the container. The container **does**
  run the tool source via `run_code_raise_errors(code)` in
  `smolagents/remote_executors.py:111` — it must be syntactically valid
  Python even if the body is never called.

## 3. Options considered

### 3.1 Option A — Install `fastmcp` (3.4.7) and use `smolagents.MCPClient`

Pros:

- Aligns with smolagents' documented pattern.
- Uses the standard `MCPClient` + `SmolAgentsAdapter` plumbing.

Cons:

- **`fastmcp` 3.4.7 downgrades `mcp` from 2.0.0 to 1.29.0** and adds 30
  transitive deps (`authlib`, `joserfc`, `py-key-value-aio`, `watchfiles`,
  `websockets`, `keyring`, `platformdirs`, …). This violates
  `CLAUDE.md §9`: *"Before adding a dependency, check whether the
  dependency is compatible with the runtime. Explain why it is needed."*
  We would be downgrading a security-critical sandbox library (`mcp`) and
  shipping 30 new packages just to use the standard adapter.
- Even with the downgrade, `mcpadapt` 0.1.20 still imports the old
  `streamablehttp_client` symbol against the older mcp. We would need to
  pin `mcpadapt<0.1.20` and check if it works — likely a deeper rabbit hole.
- Smolagents' `MCPClient` uses an async runtime via mcpadapt; wrapping
  that as a sync `forward()` would still leave us needing a background
  asyncio loop — the same complexity we'd implement ourselves.

**Rejected.**

### 3.2 Option B — Use the low-level `mcp.client.stdio` + a background asyncio loop

Pros:

- Stays on mcp 2.0.0.
- Uses the upstream `mcp` package's own client primitives.

Cons:

- Requires a persistent background-thread event loop on the host (per
  `MCPClient` instance) to bridge smolagents' sync `forward()` and the
  async `mcp.ClientSession`.
- The async `forward()` body inside the Tool subclass would reference
  `async def` and module-level coroutine helpers — both fail
  `MethodChecker`. Workable only if we route the call via a class attr
  pointing to a coroutine runner, which would itself fail the
  complex-attribute check (function refs are not `Constant/Dict/List/Set`).
- More moving parts (loop thread + cancellation + cleanup) for the same
  capability.

**Rejected.** Hand-rolled sync is simpler at this scale.

### 3.3 Option C — Hand-rolled sync JSON-RPC 2.0 client over stdio

Pros:

- **Zero new dependencies.** Pure stdlib (`subprocess`, `json`,
  `threading`).
- **Pure sync.** `forward()` can be a plain sync method using only
  `subprocess.run` / `proc.stdin.write` / `proc.stdout.readline`.
- **`forward()` body uses only stdlib + assigned names + self.X** — passes
  `MethodChecker`.
- One small module (`_mcp_runtime.py`, ~150 lines). Easy to test, easy to
  reason about.
- Server-side: the demo uses `mcp.server.mcpserver.MCPServer` (already
  present in mcp 2.0.0). We do not depend on `FastMCP`.
- Future-proof: if mcpadapt gets fixed upstream, we can replace
  `_mcp_runtime.MCPStdioServer` with `smolagents.MCPClient` without
  changing `mcp_tools.py` — the surface is `MCPStdioServer.list_tools()` /
  `.call_tool(name, arguments)` / `.close()`, the same shape as the
  upstream client.

Cons:

- We own the JSON-RPC wire format. Spec coverage is minimal: `initialize`,
  `initialized` notification, `tools/list`, `tools/call`. No resources,
  prompts, sampling, or notifications from the server.
- One round-trip = one subprocess-stdio exchange, no streaming. Acceptable
  for the v1 use case (docs search / ticket lookup / simple CRUD).
- Reading server stderr / progress notifications is deferred to v1.1.

**Accepted.**

## 4. Decision

We adopt **Option C**.

- New module `smolcode/src/smolcode/tools/_mcp_runtime.py` implements a
  sync JSON-RPC 2.0 client over stdio. It exposes
  `MCPStdioServer` (the one server connection) and a module-level
  registry `_REGISTRY: dict[str, MCPStdioServer]` plus
  `register(server_id, server)` / `unregister(server_id)` /
  `close_all()` helpers.
- New module `smolcode/src/smolcode/tools/_mcp_demo_server.py` ships a
  tiny demo "docs search" server (two readonly tools: `search_docs` and
  `get_doc`) using `mcp.server.mcpserver.MCPServer`. It is **not
  registered by default** — the user opts in by adding an example
  `mcp_config.json` block (documented in `docs/architecture.md` §6 and
  the README).
- New module `smolcode/src/smolcode/tools/mcp_tools.py` implements:
  - `MCPServerConfig` dataclass (name, transport, command OR url,
    `tools_mode` ∈ {"readonly", "readwrite", "full"}).
  - `load_mcp_config(path) -> list[MCPServerConfig]` (JSON loader).
  - `_MCPToolBase(Tool)` — class attrs are strings/dict only; the
    forward body reaches the registry via
    `sys.modules.get("smolcode.tools._mcp_runtime")._REGISTRY`.
    Empty / None registry entries raise `RuntimeError` (treated like a
    tool error by the agent loop).
  - `classify_tool_name(name, mode)` — readonly requires
    `^(get|search|read|list)_`; readwrite / full accept any name except
    shadow names.
  - `SHADOWED_TOOL_NAMES = frozenset({"final_answer", "python_interpreter"})`.
  - `build_mcp_tools(tier, configs) -> list[Tool]` — opens each server,
    fetches the tool list, classifies each name against the tier, builds
    `_MCPToolBase` subclasses via `bind_attrs` (per M2 lesson).
- Wire-up:
  - `tools/__init__.py` re-exports `build_mcp_tools`, `MCPServerConfig`,
    `load_mcp_config`, `SHADOWED_TOOL_NAMES`.
  - `agents/base.py` opens MCP servers before `build_tools` and stashes
    them in a per-`make_agent` context the CLI can clean up.
  - `cli.py` wraps `agent.run(...)` in `try/finally: mcp_runtime.close_all()`.
  - `config.py` adds the `SMOLCODE_MCP_CONFIG` env var (default:
    `<workspace>/mcp_config.json` if it exists; otherwise an empty
    config — zero servers). The config path is optional and resolved
    lazily.

## 5. Why this aligns with M2's `bind_attrs` lesson

M2's decision doc (`0004-m2-workspace-tools.md`) established:

- Tools are `Tool` subclasses (not `@tool` closures) because
  `MethodChecker` rejects undefined names.
- Per-build state lives as class attributes baked into a one-off subclass
  via `bind_attrs`.
- Class attributes must be `Constant` / `Dict` / `List` / `Set` only.

M3 honours the same three rules:

- `_MCPToolBase` is a `Tool` subclass. `forward()` references only
  `self.X`, local imports, and argument names.
- Per-server / per-tool state is baked into each subclass via
  `bind_attrs(_MCPToolBase, {"name": ..., "description": ...,
  "server_id": ..., "tool_name": ...})`. All baked-in values are
  strings or dicts (compliant with the complex-attribute check).
- The live `MCPStdioServer` connection is **not** a class attribute — it
  lives in the module-level `_REGISTRY` and is reached by `server_id`
  (a string class attribute). The registry is populated by
  `_mcp_runtime.register(...)` during agent construction and emptied by
  `_mcp_runtime.close_all()` at the end of the run.

## 6. Security alignment

This decision does **not** weaken any layer in
`docs/security.md §4`:

- **Layer 1-6 (container)** unchanged — MCP tools are host-side, not
  container-side.
- **Layer 7 (`additional_authorized_imports`)** unchanged — MCP tool
  forward bodies use stdlib only (`json`, `subprocess`, `sys`); no new
  imports are exposed to the agent's container executor.
- **Layer 8-9 (`PathPolicy` / `CommandPolicy`)** unchanged — MCP tools
  do not touch the filesystem or shell.
- **Layer 10 (`tier policy`)** strengthened — the readonly/readwrite/full
  classification now happens **at registration time** (per server's
  declared `tools_mode`), so the agent can never see a tool that its
  tier is not allowed to call. A misconfigured server (e.g. a
  `readonly`-mode server that declares a `delete_*` tool) fails closed:
  the offending tool is rejected by `classify_tool_name` and the
  remaining tools from that server are still registered (so a partial
  misconfiguration does not break the whole session).
- **Layer 11 (`asyncio.wait_for` wall-clock timeout)** added at the MCP
  call site: `subprocess.Popen(...).wait(timeout=...)` plus a
  `select`-style read with timeout on `proc.stdout.readline()` so a
  misbehaving MCP server cannot wedge the agent.
- **Layer 13 (`AuditSink`)** not affected — full_access audit logging is
  M4.

`docs/security.md §7.4 (Outbound MCP servers)` is honoured: MCP servers
are subject to the same network policy as any other outbound call. For
v1 the restricted tier runs with `network_mode="none"` (set by the
Docker executor), so a stdio-spawned MCP server that itself tries to
open a socket fails; a streamable-http MCP server on an unreachable
host fails the same way. iptables-level enforcement lands in M4 per
the existing schedule.

## 7. Implementation notes (post-M3 — to be filled in)

(To be appended at the end of the milestone with anything that
surprised us during implementation.)

## 8. Open questions

- **Q1**: Should `mcp_config.json` validation happen at startup (fail
  closed) or per-tool (fail the offending tool only)? Current decision:
  per-tool — partial misconfigurations should not break the session.
- **Q2**: Do we want a `logs/mcp.jsonl` audit log of every MCP call,
  analogous to the M4 audit log? Decision deferred to M4.
