"""M1.3 - model factory tests (5 tests)."""

import pytest
from smolagents.models import ChatMessage

from smolcode.config import load_settings
from smolcode.models import (
    PROVIDER_PRESETS,
    MissingAPIKey,
    _StubLiteLLMModel,
    build_model,
    get_preset,
)


KEY_PROVIDERS = [
    ("opencode-go", "OPENCODE_GO_APIKEY"),
    ("MiniMax", "MINIMAX_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
]


@pytest.mark.parametrize("provider,env_var", KEY_PROVIDERS)
def test_missing_key_raises(provider, env_var, _isolate_env, monkeypatch):
    monkeypatch.setenv("SMOLCODE_PROVIDER", provider)
    monkeypatch.setenv("SMOLCODE_MODEL", PROVIDER_PRESETS[provider].default_model)
    monkeypatch.delenv(env_var, raising=False)
    s = load_settings()
    with pytest.raises(MissingAPIKey) as ei:
        build_model(s)
    assert ei.value.provider == provider
    assert ei.value.env_var == env_var


def test_custom_provider_no_key_required(_isolate_env, monkeypatch):
    monkeypatch.setenv("SMOLCODE_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
    s = load_settings()
    m = build_model(s)  # must not raise
    assert m is not None


def test_stub_model_returns_fixed_string(_isolate_env):
    m = _StubLiteLLMModel()
    reply = m.generate(messages=[{"role": "user", "content": "hi"}])
    assert isinstance(reply, ChatMessage)
    assert reply.content == '<code>final_answer("[stub] hi")</code>'


def test_get_preset_unknown_raises(_isolate_env):
    with pytest.raises(ValueError):
        get_preset("nope")


def test_opencode_go_default_model_and_base(_isolate_env, monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_APIKEY", "fake-key-for-test-only-not-a-secret")
    s = load_settings()
    m = build_model(s)
    assert m.model_id == "deepseek-v4-flash"
    assert m.api_base == "https://opencode.ai/zen/go/v1"
    assert m.api_key == "fake-key-for-test-only-not-a-secret"
