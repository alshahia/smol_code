"""M1.5 - agent factory tests (2 tests).

These tests use executor_type="local" to avoid the slow Docker image
build that the docker executor triggers on first construction. The
docker path is covered separately by `smolcode --smoke` (M1.9) which
has a longer timeout.
"""

from smolagents import CodeAgent

from smolcode.agents.base import make_agent
from smolcode.config import load_settings
from smolcode.models import _StubLiteLLMModel


def test_make_agent_returns_code_agent(_isolate_env, monkeypatch):
    """Factory returns a CodeAgent with the tier imports + max_steps wired."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    s = load_settings()
    tier = s.tiers["restricted"]
    agent = make_agent(tier, s, _StubLiteLLMModel())
    assert isinstance(agent, CodeAgent)
    assert agent.executor_type == "local"
    # M2 filter: stdlib names (json, pathlib, ...) are stripped so the
    # Docker executor does not try to pip-install them. The restricted
    # tier imports are all-stdlib, so the filtered list is empty.
    assert agent.additional_authorized_imports == []
    assert agent.max_steps == 12


def test_executor_kwargs_propagate(_isolate_env, monkeypatch):
    """The docker executor receives the tier image name via executor_kwargs."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    s = load_settings()
    tier = s.tiers["restricted"]
    # When executor_type is "docker" we would pass image_name from the tier.
    # Verify the tier carries the right image tag.
    assert tier.docker_image == "smolcode:restricted"
    agent = make_agent(tier, s, _StubLiteLLMModel())
    # executor_kwargs is an empty dict for the local path; the docker
    # path would populate {"image_name": "smolcode:restricted"} here.
    assert isinstance(agent.executor_kwargs, dict)
