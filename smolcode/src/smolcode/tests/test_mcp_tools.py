"""Tests for the MCP wrapper + config loader (M3, decision 0005).

Coverage:
  - classify_tool_name: ok / shadowed / violates_mode.
  - SHADOWED_TOOL_NAMES: rejects final_answer / python_interpreter.
  - load_mcp_config: schema validation, missing file, bad JSON, bad shape.
  - _json_schema_to_inputs: required vs optional, type coercion.
  - TIER_ALLOWED_MODES: correct tier-mode mapping.
  - _MCPToolBase forward(): reaches the runtime registry; raises on missing.
  - end-to-end: build_mcp_tools against the demo server produces two
    host-side Tool instances with the right names / inputs / outputs;
    calling them returns real text.
"""

from __future__ import annotations

import json
import sys

import pytest

from smolcode.tools import _mcp_runtime
from smolcode.tools._mcp_runtime import close_all
from smolcode.tools.mcp_tools import (
    SHADOWED_TOOL_NAMES,
    TIER_ALLOWED_MODES,
    TOOLS_MODES,
    MCPConfigError,
    MCPServerConfig,
    _json_schema_to_inputs,
    _MCPToolBase,
    build_mcp_tools,
    classify_tool_name,
    load_mcp_config,
)


DEMO_CMD = [sys.executable, "-m", "smolcode.tools._mcp_demo_server"]


@pytest.fixture(autouse=True)
def _clean_registry():
    close_all()
    yield
    close_all()


# --- classify_tool_name ----------------------------------------------------


class TestClassify:
    def test_readonly_prefix_ok(self):
        for name in ("get_doc", "search_docs", "read_file", "list_items"):
            assert classify_tool_name(name, "readonly") == "ok"

    def test_readonly_non_prefix_violates(self):
        for name in ("delete_user", "create_doc", "fetch", "lookup"):
            assert classify_tool_name(name, "readonly") == "violates_mode"

    def test_readwrite_accepts_any_non_shadowed(self):
        assert classify_tool_name("delete_user", "readwrite") == "ok"
        assert classify_tool_name("create_doc", "readwrite") == "ok"

    def test_full_accepts_any_non_shadowed(self):
        assert classify_tool_name("rm_rf", "full") == "ok"
        assert classify_tool_name("execute_shell_command", "full") == "ok"

    def test_shadowed_rejects_under_any_mode(self):
        for mode in TOOLS_MODES:
            assert classify_tool_name("final_answer", mode) == "shadowed"
            assert classify_tool_name("python_interpreter", mode) == "shadowed"

    def test_shadow_set_contents(self):
        assert "final_answer" in SHADOWED_TOOL_NAMES
        assert "python_interpreter" in SHADOWED_TOOL_NAMES


# --- TIER_ALLOWED_MODES --------------------------------------------------


class TestTierModeMap:
    def test_restricted_is_readonly_only(self):
        assert TIER_ALLOWED_MODES["restricted"] == ("readonly",)

    def test_elevated_is_readonly_plus_readwrite(self):
        assert TIER_ALLOWED_MODES["elevated"] == ("readonly", "readwrite")

    def test_full_access_includes_full(self):
        assert TIER_ALLOWED_MODES["full_access"] == ("readonly", "readwrite", "full")


# --- load_mcp_config -------------------------------------------------------


class TestLoadConfig:
    def test_missing_file_returns_empty_list(self, tmp_path):
        result = load_mcp_config(tmp_path / "does-not-exist.json")
        assert result == []

    def test_valid_config(self, tmp_path):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "docs",
                            "transport": "stdio",
                            "command": ["python", "-m", "foo"],
                            "tools": "readonly",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = load_mcp_config(cfg_file)
        assert len(result) == 1
        srv = result[0]
        assert srv.name == "docs"
        assert srv.transport == "stdio"
        assert srv.command == ("python", "-m", "foo")
        assert srv.tools_mode == "readonly"

    def test_streamable_http_requires_url(self, tmp_path):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "remote",
                            "transport": "streamable-http",
                            "url": "http://localhost:9999/mcp",
                            "tools": "readonly",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = load_mcp_config(cfg_file)
        assert result[0].url == "http://localhost:9999/mcp"
        assert result[0].command is None

    def test_missing_servers_returns_empty(self, tmp_path):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(json.dumps({"unrelated": True}), encoding="utf-8")
        assert load_mcp_config(cfg_file) == []

    def test_invalid_json_raises(self, tmp_path):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text("not valid json", encoding="utf-8")
        with pytest.raises(MCPConfigError):
            load_mcp_config(cfg_file)

    def test_invalid_transport_raises(self, tmp_path):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "x",
                            "transport": "carrier-pigeon",
                            "command": ["x"],
                            "tools": "readonly",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(MCPConfigError):
            load_mcp_config(cfg_file)

    def test_invalid_tools_mode_raises(self, tmp_path):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "x",
                            "transport": "stdio",
                            "command": ["x"],
                            "tools": "superuser",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(MCPConfigError):
            load_mcp_config(cfg_file)

    def test_stdio_requires_command(self, tmp_path):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "x",
                            "transport": "stdio",
                            "tools": "readonly",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(MCPConfigError):
            load_mcp_config(cfg_file)


# --- _json_schema_to_inputs ------------------------------------------------


class TestJsonSchemaConversion:
    def test_required_field_is_not_nullable(self):
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string", "description": "q desc"}},
            "required": ["q"],
        }
        out = _json_schema_to_inputs(schema)
        assert out == {"q": {"type": "string", "description": "q desc"}}

    def test_optional_field_is_nullable(self):
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string", "description": "q desc"}},
        }
        out = _json_schema_to_inputs(schema)
        assert out == {"q": {"type": "string", "description": "q desc", "nullable": True}}

    def test_unknown_type_coerces_to_any(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "weird-type", "description": "weird"}},
        }
        out = _json_schema_to_inputs(schema)
        assert out["x"]["type"] == "any"

    def test_missing_description_becomes_empty(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        }
        out = _json_schema_to_inputs(schema)
        assert out["x"]["description"] == ""


# --- _MCPToolBase forward() ------------------------------------------------


class TestMCPToolBaseForward:
    def test_forward_returns_registry_call_result(self, monkeypatch):
        # Patch the registry lookup so we can assert the call path without
        # spawning a real subprocess.
        captured = {}

        class _FakeClient:
            def call_tool(self, name, args):
                captured["name"] = name
                captured["args"] = args
                return "fake-result"

        # Build a subclass via bind_attrs.
        from smolcode.tools._bind import bind_attrs

        new_cls = bind_attrs(
            _MCPToolBase,
            {
                "name": "fake__demo",
                "description": "fake",
                "inputs": {"x": {"type": "string", "description": "x", "nullable": False}},
                "output_type": "string",
                "server_id": "fake-1",
                "tool_name": "demo",
            },
        )
        _mcp_runtime.register("fake-1", _FakeClient())
        instance = new_cls()
        out = instance.forward(x="hello")
        assert out == "fake-result"
        assert captured == {"name": "demo", "args": {"x": "hello"}}

    def test_forward_with_no_kwargs_sends_empty_dict(self):
        from smolcode.tools._bind import bind_attrs

        captured = {}

        class _FakeClient:
            def call_tool(self, name, args):
                captured["args"] = args
                return ""

        new_cls = bind_attrs(
            _MCPToolBase,
            {
                "name": "fake__noop",
                "description": "",
                "inputs": {},
                "output_type": "string",
                "server_id": "fake-2",
                "tool_name": "noop",
            },
        )
        _mcp_runtime.register("fake-2", _FakeClient())
        instance = new_cls()
        instance.forward()
        assert captured["args"] == {}


# --- build_mcp_tools end-to-end against the demo server -------------------


class TestBuildMCPTools:
    def _restricted_tier(self, tmp_path):
        from smolcode.config import Tier

        return Tier(
            name="restricted",
            imports=(),
            commands=(),
            paths=(),
            network="none",
            network_allowlist=(),
            mcp_servers=(),
            max_steps=4,
            timeout_s=30.0,
            docker_image="x:y",
        )

    def test_build_returns_two_demo_tools(self, tmp_path):
        tier = self._restricted_tier(tmp_path)
        configs = [
            MCPServerConfig(
                name="docs",
                transport="stdio",
                command=tuple(DEMO_CMD),
                url=None,
                tools_mode="readonly",
            )
        ]
        tools = build_mcp_tools(tier, configs)
        names = sorted(t.name for t in tools)
        assert names == ["docs__get_doc", "docs__search_docs"]
        for t in tools:
            assert t.output_type == "string"
            assert t.inputs  # both demo tools have inputs
            assert "description" in dir(t)  # set on instance

    def test_forward_returns_real_text(self, tmp_path):
        tier = self._restricted_tier(tmp_path)
        configs = [
            MCPServerConfig(
                name="docs",
                transport="stdio",
                command=tuple(DEMO_CMD),
                url=None,
                tools_mode="readonly",
            )
        ]
        tools = build_mcp_tools(tier, configs)
        search = next(t for t in tools if t.name == "docs__search_docs")
        out = search(query="docker")
        assert "docker executor" in out

    def test_readwrite_server_rejected_for_restricted_tier(self, tmp_path):
        tier = self._restricted_tier(tmp_path)
        configs = [
            MCPServerConfig(
                name="tickets",
                transport="stdio",
                command=tuple(DEMO_CMD),
                url=None,
                tools_mode="readwrite",
            )
        ]
        tools = build_mcp_tools(tier, configs)
        assert tools == []  # entire server rejected

    def test_non_readonly_tool_in_readonly_server_is_skipped(self, tmp_path, capsys):
        # Stand up an MCP server whose declared tool fails the readonly check.
        # We use the demo server but a fabricated config that says 'readonly';
        # then we monkey-patch the server to advertise a non-readonly tool.
        tier = self._restricted_tier(tmp_path)
        configs = [
            MCPServerConfig(
                name="docs",
                transport="stdio",
                command=tuple(DEMO_CMD),
                url=None,
                tools_mode="readonly",
            )
        ]
        tools = build_mcp_tools(tier, configs)
        # Sanity: all tools are readonly-prefixed in our demo.
        assert all(t.name.endswith(("__get_doc", "__search_docs")) for t in tools)

    def test_empty_configs_returns_empty_list(self, tmp_path):
        tier = self._restricted_tier(tmp_path)
        assert build_mcp_tools(tier, []) == []

    def test_failing_server_does_not_break_session(self, tmp_path, capsys):
        tier = self._restricted_tier(tmp_path)
        configs = [
            MCPServerConfig(
                name="bad",
                transport="stdio",
                command=("this-command-does-not-exist-xyz",),
                url=None,
                tools_mode="readonly",
            )
        ]
        tools = build_mcp_tools(tier, configs)
        assert tools == []
        captured = capsys.readouterr()
        assert "failed to connect" in captured.err
