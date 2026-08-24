"""Sync stdio JSON-RPC 2.0 client for MCP servers (M3, decision 0005).

Background
----------
The smolagents MCPClient path is unavailable in this environment
because `mcpadapt` 0.1.20 is broken against `mcp` 2.0.0 (renamed
`streamablehttp_client` to `streamable_http_client`). Installing
`fastmcp` 3.4.7 to repair this would downgrade `mcp` from 2.0.0 to
1.29.0 and add 30 transitive deps, which violates CLAUDE.md section 9.

This module is the minimal alternative: a synchronous JSON-RPC 2.0
client that speaks the MCP "tools" subset (`initialize`,
`initialized` notification, `tools/list`, `tools/call`) over a
stdin/stdout subprocess. No new dependency, no async, no background
event-loop thread.

Wire format
-----------
MCP over stdio is line-delimited JSON-RPC 2.0. Each line is a single
JSON object terminated by a newline. Notifications (no `id`) are
dropped on the client side; v1 does not surface progress or log
notifications.

Public surface
--------------
    MCPStdioServer(name, command, args, env=None, timeout_s=30.0)
        .connect()                -> None
        .list_tools()             -> list[dict]    one MCP tools entry per item
        .call_tool(name, args)    -> str            text content concatenated
        .close()                  -> None

Module-level registry
--------------------
`_REGISTRY: dict[str, MCPStdioServer]` keys are stable `server_id`
strings (typically `{server_name}-{counter}`). The Tool subclass in
`mcp_tools.py` reaches the live `MCPStdioServer` via
`sys.modules["smolcode.tools._mcp_runtime"]._REGISTRY[server_id]` so
the per-build Tool subclass does not have to hold a function or
subprocess reference as a class attribute (which would fail
`validate_tool_attributes`; see decision 0004 + 0005).

Lifecycle
---------
`make_agent` opens each server in `mcp_tools.build_mcp_tools` via
`register(server_id, server)`. The CLI's main wraps `agent.run(...)`
in a `try/finally: close_all()` so subprocesses are torn down even
on interruption.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field


# Module-level registry: server_id -> MCPStdioServer
_REGISTRY: dict[str, "MCPStdioServer"] = {}
_REGISTRY_LOCK = threading.Lock()


# --- Helpers ------------------------------------------------------------------


class MCPRuntimeError(RuntimeError):
    """Raised when the MCP server replies with an error or breaks protocol."""


# --- Server connection --------------------------------------------------------


@dataclass
class MCPStdioServer:
    """One MCP server connection over stdio (sync, one process)."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 30.0

    # Filled in on connect().
    _proc: subprocess.Popen | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _next_id: int = 0
    _tools_cache: list[dict] | None = None

    # --- lifecycle ---

    def connect(self) -> None:
        """Spawn the subprocess and run the MCP initialize handshake."""
        if self._proc is not None and self._proc.poll() is None:
            return  # already connected
        env = dict(os.environ)
        env.update(self.env)
        # text=True + bufsize=1 -> line-buffered text I/O.
        # stderr=DEVNULL: the MCP server logs go to stderr, we drop them.
        self._proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            bufsize=1,
        )
        # MCP initialize handshake.
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smolcode", "version": "0.1.0"},
            },
        )
        # Send "initialized" notification (no response expected).
        self._send_notification("notifications/initialized", {})

    def close(self) -> None:
        """Terminate the subprocess; safe to call multiple times."""
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
        except Exception:
            pass
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # --- JSON-RPC plumbing (private) ---

    def _send_line(self, line: str) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise MCPRuntimeError("MCP server " + repr(self.name) + ": not connected")
        try:
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as e:
            raise MCPRuntimeError("MCP server " + repr(self.name) + ": write failed (" + str(e) + ")") from e

    def _send_notification(self, method: str, params: dict) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._send_line(json.dumps(msg, separators=(",", ":")))

    def _recv_line(self) -> str:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise MCPRuntimeError("MCP server " + repr(self.name) + ": not connected")
        line = proc.stdout.readline()
        if not line:
            raise MCPRuntimeError("MCP server " + repr(self.name) + ": closed stdout unexpectedly")
        return line.rstrip("\n").rstrip("\r")

    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            self._send_line(json.dumps(req, separators=(",", ":")))
            while True:
                raw = self._recv_line()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if "id" in msg and msg["id"] == req_id:
                    if "error" in msg:
                        err = msg["error"]
                        raise MCPRuntimeError(
                            "MCP server "
                            + repr(self.name)
                            + " returned error for "
                            + repr(method)
                            + ": "
                            + repr(err.get("code"))
                            + " "
                            + repr(err.get("message"))
                        )
                    return msg.get("result", {})
                # else: notification (no id) or stale response; skip.

    # --- public MCP API ---

    def list_tools(self) -> list[dict]:
        """Return the server tool list, one MCP tools entry per item."""
        if self._tools_cache is not None:
            return self._tools_cache
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise MCPRuntimeError(
                "MCP server " + repr(self.name) + ": tools/list returned non-list " + type(tools).__name__
            )
        self._tools_cache = tools
        return tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool by name with arguments; return concatenated text content."""
        result = self._request("tools/call", {"name": tool_name, "arguments": arguments})
        if not isinstance(result, dict):
            raise MCPRuntimeError(
                "MCP server " + repr(self.name) + ": tools/call returned non-dict " + type(result).__name__
            )
        if result.get("isError"):
            content = result.get("content", [])
            msg = (
                "; ".join(item.get("text", str(item)) for item in content if isinstance(item, dict))
                or "tool reported an error"
            )
            raise MCPRuntimeError(
                "MCP tool " + repr(tool_name) + " on " + repr(self.name) + " reported an error: " + msg
            )
        parts: list[str] = []
        for item in result.get("content", []):
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                else:
                    parts.append(str(item))
        return "\n".join(parts)


# --- Module-level registry helpers --------------------------------------------


def register(server_id: str, server: MCPStdioServer) -> None:
    """Insert a server into the module-level registry."""
    with _REGISTRY_LOCK:
        _REGISTRY[server_id] = server


def unregister(server_id: str) -> None:
    """Remove a server from the registry and close it."""
    with _REGISTRY_LOCK:
        server = _REGISTRY.pop(server_id, None)
    if server is not None:
        try:
            server.close()
        except Exception:
            pass


def get(server_id: str) -> MCPStdioServer | None:
    """Look up a registered server; returns None if absent."""
    with _REGISTRY_LOCK:
        return _REGISTRY.get(server_id)


def all_server_ids() -> list[str]:
    """Snapshot of registered server IDs (for tests / diagnostics)."""
    with _REGISTRY_LOCK:
        return sorted(_REGISTRY.keys())


def close_all() -> None:
    """Close every registered server; safe to call multiple times."""
    with _REGISTRY_LOCK:
        servers = list(_REGISTRY.values())
        _REGISTRY.clear()
    for s in servers:
        try:
            s.close()
        except Exception:
            pass


# --- atexit safety net -------------------------------------------------------


# If the CLI exits without going through close_all() (e.g. an unhandled
# exception in user code that the framework doesn't catch), atexit gives
# us one last chance to reap subprocesses.
_atexit_registered = False


def _ensure_atexit_registered():
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(close_all)
        _atexit_registered = True


_ensure_atexit_registered()


# --- Module diagnostics ------------------------------------------------------


def _format_registry_state() -> str:
    """For debug / test assertions."""
    with _REGISTRY_LOCK:
        ids = sorted(_REGISTRY.keys())
    return "registry has " + str(len(ids)) + " server(s): " + str(ids)


if __name__ == "__main__":  # pragma: no cover
    print(_format_registry_state(), file=sys.stderr)
    sys.exit(0)
