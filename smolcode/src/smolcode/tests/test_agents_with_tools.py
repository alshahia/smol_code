"""Tests for agents/base.py wiring of tools + import filter."""

from __future__ import annotations

import pytest
from smolagents import CodeAgent

from smolcode.agents.base import _filter_third_party_imports, make_agent
from smolcode.config import load_settings
from smolcode.models import _StubLiteLLMModel


def test_filter_drops_stdlib_imports():
    out = _filter_third_party_imports(
        [
            "json",
            "pathlib",
            "requests",
            "subprocess",
            "pytest",
            "yaml",
            "ast",
            "textwrap",
        ]
    )
    assert out == ["requests", "pytest", "yaml"]


def test_filter_drops_dotted_stdlib():
    # "collections.abc" -> top-level "collections" (stdlib).
    out = _filter_third_party_imports(["collections.abc", "requests.sessions"])
    assert out == ["requests.sessions"]


def test_filter_preserves_empty():
    assert _filter_third_party_imports([]) == []


def test_filter_preserves_unknown_modules():
    # Modules not in sys.stdlib_module_names are treated as third-party.
    out = _filter_third_party_imports(["smolcode", "smolagents"])
    assert out == ["smolcode", "smolagents"]


def test_make_agent_with_local_executor_returns_code_agent(tmp_path, monkeypatch):
    # Force local executor to avoid Docker image build during tests.
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = load_settings(cli_overrides={"workspace": str(ws)})
    agent = make_agent(settings.tiers["restricted"], settings, _StubLiteLLMModel())
    assert isinstance(agent, CodeAgent)


def test_make_agent_attaches_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = load_settings(cli_overrides={"workspace": str(ws)})
    agent = make_agent(settings.tiers["restricted"], settings, _StubLiteLLMModel())
    # CodeAgent stores tools in agent.tools dict.
    tool_names = sorted(agent.tools.keys())
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "list_dir" in tool_names
    assert "run" in tool_names
    assert "git_status" in tool_names


def test_make_agent_filters_stdlib_imports(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = load_settings(cli_overrides={"workspace": str(ws)})
    agent = make_agent(settings.tiers["restricted"], settings, _StubLiteLLMModel())
    # agent.additional_authorized_imports is the list passed to CodeAgent.
    # Restricted tier defaults to all-stdlib, so after filtering it should be empty.
    assert agent.additional_authorized_imports == []


def test_make_agent_rejects_non_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = load_settings(cli_overrides={"workspace": str(ws)})
    with pytest.raises(TypeError):
        make_agent("not a tier", settings, _StubLiteLLMModel())


def test_make_agent_max_steps_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = load_settings(cli_overrides={"workspace": str(ws)})
    agent = make_agent(settings.tiers["restricted"], settings, _StubLiteLLMModel(), max_steps=3)
    assert agent.max_steps == 3
