"""LLM model factory with five provider presets.

Lifted pattern from smolagents-hybrid-search/src/smolagents_hybrid/providers.py
(MiniMaxProvider at lines 85-118, OpencodeGoProvider at lines 121-151).
That file uses an ABC + instance-method pattern; this module uses
plain dataclasses + a single factory function because we do not need
the network-list_models capability in v1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from smolagents import LiteLLMModel


# --- Provider preset definition ----------------------------------------------


@dataclass(frozen=True)
class ProviderPreset:
    """One provider preset (see docs/architecture.md 5.2)."""

    name: str
    api_key_env: str | None  # None for keyless providers
    api_base_env: str | None
    api_base_default: str | None
    default_model: str
    custom_llm_provider: str | None  # "openai" or None (let litellm decide)
    required_for_key: bool  # if True, the env var MUST be set to build the model
    tier: str  # "first-class" | "secondary"


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "opencode-go": ProviderPreset(
        name="opencode-go",
        api_key_env="OPENCODE_GO_APIKEY",
        api_base_env="OPENCODE_HOST",
        api_base_default="https://opencode.ai/zen/go/v1",
        default_model="deepseek-v4-flash",
        custom_llm_provider="openai",
        required_for_key=True,
        tier="first-class",
    ),
    "MiniMax": ProviderPreset(
        name="MiniMax",
        api_key_env="MINIMAX_API_KEY",
        api_base_env="MINIMAX_HOST",
        api_base_default="https://api.minimax.io/v1",
        default_model="MiniMax-M3",
        custom_llm_provider="openai",
        required_for_key=True,
        tier="first-class",
    ),
    "openai": ProviderPreset(
        name="openai",
        api_key_env="OPENAI_API_KEY",
        api_base_env=None,
        api_base_default=None,
        default_model="gpt-4o-mini",
        custom_llm_provider=None,  # litellm native
        required_for_key=True,
        tier="secondary",
    ),
    "anthropic": ProviderPreset(
        name="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        api_base_env=None,
        api_base_default=None,
        default_model="claude-3-5-sonnet-latest",
        custom_llm_provider=None,
        required_for_key=True,
        tier="secondary",
    ),
    "custom": ProviderPreset(
        name="custom",
        api_key_env="CUSTOM_API_KEY",
        api_base_env="CUSTOM_BASE_URL",
        api_base_default=None,  # required for custom
        default_model="custom-model",
        custom_llm_provider="openai",
        required_for_key=False,  # key is optional for self-hosted endpoints
        tier="secondary",
    ),
}


# --- Public exceptions --------------------------------------------------------


class MissingAPIKey(RuntimeError):
    """Raised when a preset is requested but its key env var is unset."""

    def __init__(self, provider, env_var):
        super().__init__(
            f"Provider {provider!r} requires environment variable {env_var!r} to be set. "
            f"See docs/environment.md section 11."
        )
        self.provider = provider
        self.env_var = env_var


# --- Public factory ----------------------------------------------------------


def get_preset(name):
    if name not in PROVIDER_PRESETS:
        raise ValueError(f"unknown provider {name!r}; known: {sorted(PROVIDER_PRESETS)}")
    return PROVIDER_PRESETS[name]


def _api_base_for(preset, litellm_proxy):
    """Resolve api_base: explicit LiteLLM proxy wins; otherwise env, otherwise default."""
    if litellm_proxy:
        return litellm_proxy
    if preset.api_base_env:
        env_val = os.environ.get(preset.api_base_env)
        if env_val:
            return env_val
    return preset.api_base_default


def build_model(settings, *, model_override=None, preset_name=None, api_key_override=None):
    """Build a LiteLLMModel from a Settings + optional overrides.

    Raises MissingAPIKey if the preset requires a key and it is unset.
    """
    preset = get_preset(preset_name or settings.provider)
    model_id = model_override or settings.model or preset.default_model

    api_key = api_key_override
    if api_key is None and preset.api_key_env:
        api_key = os.environ.get(preset.api_key_env)
    if preset.required_for_key and not api_key:
        raise MissingAPIKey(preset.name, preset.api_key_env or "<unset>")

    api_base = _api_base_for(preset, settings.litellm_proxy)

    kwargs = {"model_id": model_id, "api_key": api_key}
    if api_base:
        kwargs["api_base"] = api_base
    if preset.custom_llm_provider:
        kwargs["custom_llm_provider"] = preset.custom_llm_provider

    return LiteLLMModel(**kwargs)


# --- Stub model (for offline --smoke tests) ----------------------------------


class _StubLiteLLMModel(LiteLLMModel):
    """Deterministic stub used by --smoke and by tests that exercise

    the agent loop without a real model. Returns a fixed string so the

    parser terminates the run in step 1. The reply text is parametrised

    so tests can substitute their own marker.


    Inherits from LiteLLMModel so it satisfies the type contract for

    CodeAgent; only generate() is overridden.
    """

    _DEFAULT_REPLY = '<code>final_answer("[stub] hi")</code>'

    def __init__(self, reply=None):
        super().__init__(model_id="stub")
        self._reply = reply if reply is not None else self._DEFAULT_REPLY

    def generate(self, messages, stop_sequences=None, **kwargs):
        from smolagents.models import ChatMessage, TokenUsage

        return ChatMessage(
            role="assistant",
            content=self._reply,
            tool_calls=None,
            raw=None,
            token_usage=TokenUsage(input_tokens=0, output_tokens=0),
        )
