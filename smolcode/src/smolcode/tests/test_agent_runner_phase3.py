"""Phase 3 RED tests for F2 (cache-token extraction).

Bug surface:
    web/agent_runner.py:_action_step_payload reads only
    input_tokens + output_tokens from step.token_usage. OpenAI responses
    include usage.prompt_tokens_details.cached_tokens; Anthropic
    responses include usage.cache_read_input_tokens +
    usage.cache_creation_input_tokens. smolagents 1.26.0's
    TokenUsage dataclass exposes only input/output - cache data is
    reachable via step.model_output_message.raw.usage (smolagents
    stores the raw response on the ChatMessage). Today the extractor
    ignores it; Phase 2 will read it.
"""

from __future__ import annotations

from types import SimpleNamespace


def _make_step_with_openai_cache(*, token_input=1000, token_output=50, cached=400):
    """ActionStep-like with model_output_message.raw.usage carrying the
    OpenAI-shape cache field. The smolagents ChatMessage.raw field is
    duck-typed; the test mirrors the actual library structure without
    importing smolagents."""
    usage = SimpleNamespace(prompt_tokens_details=SimpleNamespace(cached_tokens=cached))
    mom = SimpleNamespace(raw=SimpleNamespace(usage=usage), content="thought")
    return SimpleNamespace(
        step_number=1,
        model_output_message=mom,
        token_usage=SimpleNamespace(input_tokens=token_input, output_tokens=token_output),
    )


def _make_step_with_anthropic_cache(*, token_input=1000, token_output=50, cache_read=200, cache_creation=50):
    usage = SimpleNamespace(
        prompt_tokens_details=SimpleNamespace(cached_tokens=None),
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )
    mom = SimpleNamespace(raw=SimpleNamespace(usage=usage), content="thought")
    return SimpleNamespace(
        step_number=1,
        model_output_message=mom,
        token_usage=SimpleNamespace(input_tokens=token_input, output_tokens=token_output),
    )


def _make_step_without_cache(*, token_input=100, token_output=10):
    """A step where neither field is present (or where raw is None)."""
    return SimpleNamespace(
        step_number=1,
        model_output_message=SimpleNamespace(raw=SimpleNamespace(usage=None), content="t"),
        token_usage=SimpleNamespace(input_tokens=token_input, output_tokens=token_output),
    )


class TestCacheTokenExtraction:
    """F2 - RED: _action_step_payload must surface cache_hit from the
    provider response, regardless of which provider shape the API
    returns."""

    def test_cache_hit_extracted_from_openai_usage(self):
        """RED today: extractor returns {"input": .., "output": ..} and
        ignores usage.prompt_tokens_details.cached_tokens. After Phase 2,
        the tokens dict includes cache_hit == 400."""
        from smolcode.web.agent_runner import _action_step_payload

        step = _make_step_with_openai_cache(cached=400)
        payload = _action_step_payload(step)
        assert payload["tokens"].get("cache_hit") == 400, (
            "_action_step_payload did not extract cache_hit from "
            "usage.prompt_tokens_details.cached_tokens; got tokens=" + repr(payload.get("tokens"))
        )

    def test_cache_hit_falls_back_to_anthropic_fields(self):
        """RED today: Anthropic-shape usage is ignored. After Phase 2,
        cache_read_input_tokens + cache_creation_input_tokens sum into
        cache_hit."""
        from smolcode.web.agent_runner import _action_step_payload

        step = _make_step_with_anthropic_cache(cache_read=200, cache_creation=50)
        payload = _action_step_payload(step)
        assert payload["tokens"].get("cache_hit") == 250, (
            "Anthropic-shaped cache fields should sum to cache_hit=250; got " + repr(payload.get("tokens"))
        )

    def test_no_cache_data_does_not_break(self):
        """Guard: when the provider response carries no cache fields at all,
        the extractor must NOT raise; cache_hit defaults to 0."""
        from smolcode.web.agent_runner import _action_step_payload

        step = _make_step_without_cache()
        payload = _action_step_payload(step)
        assert payload["tokens"].get("cache_hit", 0) == 0
