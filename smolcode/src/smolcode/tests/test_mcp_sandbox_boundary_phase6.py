"""R13: MCP tools execute on the HOST, outside every container.

Plan 6.5 #1, decided with the operator: option B, with the documentation from
option A alongside. Under SMOLCODE_EXECUTOR=docker an MCP tool call runs in
the server process on the host while model-written code runs in a container,
so enabling MCP quietly reintroduces exactly the capability the docker
executor exists to remove.

The Phase 6 work made MCP safer (default-deny allowlist, env floor,
destructive gate) but did not change WHERE it runs. This closes that by
making the acceptance explicit and refused by default:

  * docker executor + MCP configured + not opted in  -> refuse to build
  * docker executor + MCP configured + opted in      -> allowed
  * local executor                                   -> allowed (already
    unsandboxed, and the NOT SANDBOXED banner says so)
  * no MCP configured                                -> unaffected

This is deliberately a refusal, not a warning. A warning printed every run on
a default-on path is a warning nobody reads.
"""

from __future__ import annotations

import pytest

from smolcode.config import Settings, _default_tiers
from smolcode.tools import build_tools
from smolcode.tools.mcp_tools import MCPServerConfig


def _tier(name="full_access"):
    return _default_tiers()[name]


def _settings(tmp_path, executor="docker", allow=False):
    return Settings(
        workspace=tmp_path,
        executor=executor,
        provider="opencode-go",
        model="m",
        litellm_proxy=None,
        log_level="INFO",
        tiers=_default_tiers(),
        allow_unsandboxed_mcp=allow,
    )


def _cfg(name="docs"):
    return MCPServerConfig(
        name=name,
        transport="streamable-http",
        command=None,
        url="http://127.0.0.1:9/mcp",
        tools_mode="full",
    )


class TestDockerExecutorRefusesUnsandboxedMcp:
    def test_mcp_under_docker_is_refused_by_default(self, tmp_path):
        with pytest.raises(PermissionError) as ei:
            build_tools(_tier(), _settings(tmp_path), mcp_configs=[_cfg()])
        msg = str(ei.value)
        assert "MCP" in msg
        assert "--allow-unsandboxed-mcp" in msg

    def test_the_message_says_why(self, tmp_path):
        # The operator has to learn this is a LOCATION difference, not a
        # permissions one, or they will assume the flag sandboxes it.
        with pytest.raises(PermissionError) as ei:
            build_tools(_tier(), _settings(tmp_path), mcp_configs=[_cfg()])
        assert "host" in str(ei.value).lower()

    def test_the_message_names_the_executor(self, tmp_path):
        with pytest.raises(PermissionError) as ei:
            build_tools(_tier(), _settings(tmp_path), mcp_configs=[_cfg()])
        assert "docker" in str(ei.value).lower()

    def test_explicit_opt_in_allows_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr("smolcode.tools.mcp_tools.build_mcp_tools", lambda *a, **k: [])
        assert build_tools(_tier(), _settings(tmp_path, allow=True), mcp_configs=[_cfg()]) is not None

    def test_no_mcp_configured_is_unaffected(self, tmp_path):
        assert build_tools(_tier(), _settings(tmp_path)) is not None


class TestLocalExecutorIsUnaffected:
    def test_local_executor_still_allows_mcp(self, tmp_path, monkeypatch):
        # local is ALREADY unsandboxed and prints a banner. Refusing MCP there
        # would break working setups for no additional safety.
        monkeypatch.setattr("smolcode.tools.mcp_tools.build_mcp_tools", lambda *a, **k: [])
        assert build_tools(_tier(), _settings(tmp_path, executor="local"), mcp_configs=[_cfg()]) is not None


class TestSettingPlumbing:
    def test_defaults_to_false(self, tmp_path):
        assert _settings(tmp_path).allow_unsandboxed_mcp is False

    def test_with_executor_preserves_it(self, tmp_path):
        assert _settings(tmp_path, allow=True).with_executor("local").allow_unsandboxed_mcp is True

    def test_with_overrides_preserves_it(self, tmp_path):
        s = _settings(tmp_path, allow=True).with_overrides(model="other")
        assert s.allow_unsandboxed_mcp is True


class TestEnvVar:
    def test_env_var_enables_it(self, tmp_path, monkeypatch):
        from smolcode.config import load_settings

        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
        monkeypatch.setenv("SMOLCODE_ALLOW_UNSANDBOXED_MCP", "1")
        assert load_settings().allow_unsandboxed_mcp is True

    def test_env_var_defaults_off(self, tmp_path, monkeypatch):
        from smolcode.config import load_settings

        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
        monkeypatch.delenv("SMOLCODE_ALLOW_UNSANDBOXED_MCP", raising=False)
        assert load_settings().allow_unsandboxed_mcp is False
