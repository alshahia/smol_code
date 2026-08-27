"""Phase 3 RED tests for the context-window catalog.

Bug surface:
    web/inspector.tsx needs a context-window value to render the
    context-fill circle. There is no source of truth for this in
    model_catalog today - a grep for context_window / max_context /
    context_length against smolcode/src/smolcode/model_catalog.py
    returns no matches.
    The fix surface adds:
        - ProviderSpec.default_context_window
        - DEFAULT_CONTEXT_WINDOWS: dict[provider][model] -> int
        - resolve_context_window(provider, model) -> int | None
          (with overrides via Settings.cost_rates JSON env, mirroring
          the existing _resolve_rates pattern)

These tests FAIL today (RED) by way of ImportError or AttributeError,
since resolve_context_window does not exist yet. They pass after
Phase 2 adds the helper.
"""

from __future__ import annotations

import pytest


class TestContextWindow:
    """F2 - RED: model_catalog exposes resolve_context_window."""

    def test_resolve_context_window_is_public(self):
        """RED today: ImportError - function does not exist."""
        try:
            from smolcode.model_catalog import resolve_context_window  # noqa: F401
        except ImportError as e:
            pytest.fail("smolcode.model_catalog.resolve_context_window is missing (F2 Phase 2 adds it): " + repr(e))

    def test_known_models_return_expected_context(self):
        """RED today: ImportError at the import site."""
        from smolcode.model_catalog import resolve_context_window

        assert resolve_context_window("opencode-go", "deepseek-v4-flash") == 128000
        assert resolve_context_window("MiniMax", "MiniMax-M3") == 2_000_000
        assert resolve_context_window("openai", "gpt-4o") == 128000
        assert resolve_context_window("openai", "gpt-4o-mini") == 128000
        assert resolve_context_window("openai", "o1-preview") == 128000
        assert resolve_context_window("anthropic", "claude-3-5-sonnet-latest") == 200000
        assert resolve_context_window("anthropic", "claude-3-5-haiku-latest") == 200000
        assert resolve_context_window("anthropic", "claude-3-opus-latest") == 200000

    def test_unknown_provider_returns_none(self):
        """RED today (function doesn't exist). After Phase 2: unknown
        provider/model returns None, NOT a KeyError."""
        from smolcode.model_catalog import resolve_context_window

        assert resolve_context_window("unknown-provider", "unknown-model") is None
        assert resolve_context_window(None, None) is None
        assert resolve_context_window("", "") is None
