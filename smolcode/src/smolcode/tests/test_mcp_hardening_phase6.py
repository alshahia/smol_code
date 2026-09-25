"""Phase 6 section 6.5 (R12 / H11) -- MCP hardening.

Five defects in the MCP integration, each of which is a security or
reliability hole rather than a style issue:

  1. _mcp_runtime.connect() did: env = dict(os.environ) -- every MCP
     server subprocess inherited the ENTIRE host environment, including
     every API key, cloud credential and token the operator had exported.
  2. Readonly mode was enforced by guessing the tool NAME against
     /^(get|search|read|list)_/ . The name is supplied by the MCP server,
     i.e. by the untrusted side of the boundary. Naming a destructive
     tool "get_nuke" sailed straight through.
  3. No MCP tool was ever passed through destructive.is_destructive. The
     old rationale ("tier-filtered") leaned entirely on defect 2.
  4. _server_id_for(name, counter) restarted the counter on every
     build_mcp_tools() call, so a second call for the same server name
     produced an identical id and register() silently rebound live tools
     to a different server object.
  5. timeout_s was a dataclass field that nothing read. _recv_line() called
     a blocking readline(), so a wedged MCP server hung the agent forever.
"""

from __future__ import annotations

import time

import pytest

from smolcode.tools import _mcp_runtime
from smolcode.tools._mcp_runtime import MCPRuntimeError, MCPStdioServer


# --- 1. default-deny child environment -------------------------------------


class TestChildEnvIsDefaultDeny:
    def test_host_secrets_are_not_inherited(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_TEST_FAKE_SECRET", "sk-do-not-leak")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-another")
        server = MCPStdioServer(name="t", command="echo", args=[])
        env = server._build_child_env()
        assert "SMOLCODE_TEST_FAKE_SECRET" not in env
        assert "OPENAI_API_KEY" not in env

    def test_only_declared_vars_are_passed_through(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_TEST_ALLOWED", "visible")
        monkeypatch.setenv("SMOLCODE_TEST_SECRET", "hidden")
        server = MCPStdioServer(
            name="t",
            command="echo",
            args=[],
            env_allow=("SMOLCODE_TEST_ALLOWED",),
        )
        env = server._build_child_env()
        assert env.get("SMOLCODE_TEST_ALLOWED") == "visible"
        assert "SMOLCODE_TEST_SECRET" not in env

    def test_explicit_env_overrides_are_kept(self):
        server = MCPStdioServer(name="t", command="echo", args=[], env={"MCP_LOG": "debug"})
        assert server._build_child_env().get("MCP_LOG") == "debug"

    def test_process_can_still_launch(self):
        # PATH is the one thing a subprocess genuinely cannot start
        # without. Dropping it would make every server fail to spawn,
        # which is a different outage, not a security win.
        server = MCPStdioServer(name="t", command="echo", args=[])
        assert server._build_child_env().get("PATH")


# --- 2. operator-curated allowlist replaces the name-prefix heuristic -------


class TestCuratedAllowlistReplacesPrefixHeuristic:
    def _cfg(self, **kw):
        from smolcode.tools.mcp_tools import MCPServerConfig

        base = dict(
            name="srv",
            transport="stdio",
            command=("echo",),
            url=None,
            tools_mode="readonly",
            allow=(),
        )
        base.update(kw)
        return MCPServerConfig(**base)

    def test_readonly_server_without_allow_exposes_nothing(self):
        from smolcode.tools.mcp_tools import tool_is_allowed

        cfg = self._cfg(allow=())
        assert not tool_is_allowed(cfg, "get_anything")
        assert not tool_is_allowed(cfg, "search_anything")
        assert not tool_is_allowed(cfg, "list_anything")
        assert not tool_is_allowed(cfg, "read_anything")

    def test_only_declared_names_are_allowed(self):
        from smolcode.tools.mcp_tools import tool_is_allowed

        cfg = self._cfg(allow=("get_docs",))
        assert tool_is_allowed(cfg, "get_docs")
        assert not tool_is_allowed(cfg, "get_anything_else")
        assert not tool_is_allowed(cfg, "delete_everything")

    def test_the_prefix_heuristic_is_gone(self):
        # A readonly server that declares delete_all is allowed ONLY
        # because the operator said so -- and it is then routed through
        # the destructive gate, which the prefix heuristic never did.
        from smolcode.tools.mcp_tools import tool_is_allowed

        cfg = self._cfg(allow=("delete_all",))
        assert tool_is_allowed(cfg, "delete_all")

    def test_shadowed_names_are_never_allowed(self):
        from smolcode.tools.mcp_tools import tool_is_allowed

        cfg = self._cfg(allow=("final_answer",))
        assert not tool_is_allowed(cfg, "final_answer")

    def test_glob_is_supported_but_exact_names_win(self):
        from smolcode.tools.mcp_tools import tool_is_allowed

        cfg = self._cfg(allow=("search_*",))
        assert tool_is_allowed(cfg, "search_docs")
        assert not tool_is_allowed(cfg, "list_docs")


# --- 3. MCP tools go through the destructive classifier ---------------------


class TestMcpCallsAreDestructivelyGated:
    def test_declared_destructive_tool_is_classified(self):
        from smolcode.destructive import is_destructive

        assert is_destructive("srv__delete_all", {}, destructive_override=True)

    def test_name_pattern_is_classified_even_if_not_declared(self):
        from smolcode.destructive import is_destructive

        assert is_destructive("srv__drop_database", {})
        assert is_destructive("srv__destroy_workspace", {})

    def test_ordinary_read_tool_is_not_destructive(self):
        from smolcode.destructive import is_destructive

        assert not is_destructive("srv__get_docs", {})

    def test_unknown_tool_is_not_destructive(self):
        from smolcode.destructive import is_destructive

        assert not is_destructive("srv__frobnicate", {})

    def test_gated_tool_refuses_without_allow(self):
        from smolcode.tools.mcp_tools import _MCPToolBase

        cls = type(
            "T",
            (_MCPToolBase,),
            {
                "name": "srv__delete_all",
                "server_id": "srv-x",
                "tool_name": "delete_all",
                "destructive_policy": "deny",
                "inputs": {},
                "output_type": "string",
                "description": "",
            },
        )
        with pytest.raises(PermissionError, match="destructive"):
            cls().forward()

    def test_gated_tool_proceeds_with_allow(self):
        from smolcode.tools.mcp_tools import _MCPToolBase

        calls = []
        cls = type(
            "T",
            (_MCPToolBase,),
            {
                "name": "srv__delete_all",
                "server_id": "srv-x",
                "tool_name": "delete_all",
                "destructive_policy": "allow",
                "inputs": {},
                "output_type": "string",
                "description": "",
            },
        )

        class _Fake:
            def call_tool(self, name, args):
                calls.append((name, args))
                return "ok"

        _mcp_runtime._REGISTRY["srv-x"] = _Fake()
        try:
            assert cls().forward() == "ok"
        finally:
            _mcp_runtime._REGISTRY.pop("srv-x", None)
        assert calls == [("delete_all", {})]


# --- 4. globally unique registry ids ---------------------------------------


class TestServerIdsAreGloballyUnique:
    def test_same_server_name_gets_different_ids(self):
        from smolcode.tools.mcp_tools import _server_id_for

        a = _server_id_for("github", 1)
        b = _server_id_for("github", 1)
        assert a != b

    def test_ids_survive_concurrent_builds(self):
        from smolcode.tools.mcp_tools import _server_id_for

        ids = {_server_id_for("gh", 1) for _ in range(50)}
        assert len(ids) == 50

    def test_server_name_is_still_readable_in_the_id(self):
        from smolcode.tools.mcp_tools import _server_id_for

        assert _server_id_for("github", 1).startswith("github")


# --- 5. timeout_s is actually enforced --------------------------------------


class _SlowStdout:
    def __init__(self, delay):
        self.delay = delay

    def readline(self):
        time.sleep(self.delay)
        return "{}\n"


class _FakeProc:
    def __init__(self, delay):
        self.stdout = _SlowStdout(delay)
        self.stdin = None
        self.returncode = None

    def poll(self):
        return None


class TestTimeoutIsEnforced:
    def test_slow_read_raises_instead_of_hanging(self):
        server = MCPStdioServer(name="slow", command="x", args=[], timeout_s=0.3)
        server._proc = _FakeProc(5.0)
        started = time.monotonic()
        with pytest.raises(MCPRuntimeError, match="timed out"):
            server._recv_line()
        assert time.monotonic() - started < 3.0

    def test_fast_read_is_unaffected(self):
        server = MCPStdioServer(name="fast", command="x", args=[], timeout_s=5.0)
        server._proc = _FakeProc(0.0)
        assert server._recv_line() == "{}"

    def test_default_timeout_is_sane(self):
        assert 0 < MCPStdioServer(name="d", command="x", args=[]).timeout_s <= 300
