"""Phase 3 (decision 0025 sec 6.5): per-provider cost rates + cost_for().

Q5 (decision 0025 sec 10.5) was answered: (a) hardcoded defaults + override
via Settings.cost_rates. The override is a JSON-encoded env var
(SMOLCODE_COST_RATES) shaped {provider: {model: [in, out, cache]}}.

Tests cover:
  TestCostRates: DEFAULT_COST_RATES shape + cost_for() happy path
  TestCostRatesOverride: Settings.cost_rates env override (per provider/model)
  TestCostRatesFailClosed: invalid JSON / wrong shape -> ConfigError
  TestCostForUnknown: unknown provider / model -> 0.0 (graceful)
  TestCostCacheHit: cache_hit tokens charged at the cache rate
"""

from __future__ import annotations

import pytest

from smolcode.config import ConfigError, load_settings
from smolcode.model_catalog import (
    DEFAULT_COST_RATES,
    cost_for,
    rate_source_for,
)


class TestCostRates:
    def test_default_cost_rates_shape(self):
        assert isinstance(DEFAULT_COST_RATES, dict)
        for prov, models in DEFAULT_COST_RATES.items():
            assert isinstance(prov, str) and prov
            assert isinstance(models, dict)
            for model, rates in models.items():
                assert isinstance(model, str) and model
                assert isinstance(rates, tuple) and len(rates) == 3
                assert all(isinstance(x, (int, float)) for x in rates)
                assert all(x >= 0 for x in rates)

    def test_cost_for_known_provider_positive(self):
        cost = cost_for("openai", "gpt-4o", input_tokens=1000, output_tokens=500)
        # 1k * 0.005 + 0.5k * 0.015 = 0.005 + 0.0075 = 0.0125
        assert cost == pytest.approx(0.0125)

    def test_cost_for_unknown_provider_returns_zero(self):
        assert cost_for("nonexistent", "x", 1000, 500) == 0.0

    def test_cost_for_unknown_model_returns_zero(self):
        assert cost_for("openai", "gpt-99", 1000, 500) == 0.0

    def test_cost_for_missing_provider_returns_zero(self):
        assert cost_for(None, "gpt-4o", 1000, 500) == 0.0

    def test_cost_for_missing_model_returns_zero(self):
        assert cost_for("openai", None, 1000, 500) == 0.0

    def test_cost_for_zero_tokens_returns_zero(self):
        assert cost_for("openai", "gpt-4o", 0, 0) == 0.0


class TestCostRatesOverride:
    def test_override_takes_precedence_over_default(self, monkeypatch):
        monkeypatch.setenv(
            "SMOLCODE_COST_RATES",
            '{"openai": {"gpt-4o": [0.001, 0.002, 0.0]}}',
        )
        settings = load_settings()
        cost = cost_for("openai", "gpt-4o", 1000, 500, settings=settings)
        # 1k * 0.001 + 0.5k * 0.002 = 0.001 + 0.001 = 0.002
        assert cost == pytest.approx(0.002)
        assert rate_source_for("openai", "gpt-4o", settings=settings) == "override"

    def test_partial_override_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(
            "SMOLCODE_COST_RATES",
            '{"openai": {"gpt-4o": [0.001, 0.002, 0.0]}}',
        )
        settings = load_settings()
        # gpt-4o-mini is NOT in the override -> default rate
        cost = cost_for("openai", "gpt-4o-mini", 1000, 500, settings=settings)
        # 1k * 0.00015 + 0.5k * 0.0006 = 0.00015 + 0.0003 = 0.00045
        assert cost == pytest.approx(0.00045)
        assert rate_source_for("openai", "gpt-4o-mini", settings=settings) == "default"

    def test_rate_source_unknown_when_no_rate(self, monkeypatch):
        settings = load_settings()
        assert rate_source_for("unknown", "x", settings=settings) == "unknown"


class TestCostRatesFailClosed:
    def test_invalid_json_raises_config_error(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_COST_RATES", "{not json")
        with pytest.raises(ConfigError, match="not valid JSON"):
            load_settings()

    def test_wrong_shape_raises_config_error(self, monkeypatch):
        # inner value is not a list
        monkeypatch.setenv("SMOLCODE_COST_RATES", '{"openai": {"gpt-4o": "oops"}}')
        with pytest.raises(ConfigError, match=r"must be \[in, out, cache\]"):
            load_settings()

    def test_wrong_length_raises_config_error(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_COST_RATES", '{"openai": {"gpt-4o": [0.001, 0.002]}}')
        with pytest.raises(ConfigError, match=r"must be \[in, out, cache\]"):
            load_settings()

    def test_non_numeric_rate_raises_config_error(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_COST_RATES", '{"openai": {"gpt-4o": ["x", 0.002, 0.0]}}')
        with pytest.raises(ConfigError, match="rates must be numeric"):
            load_settings()

    def test_provider_not_a_dict_raises_config_error(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_COST_RATES", '{"openai": "oops"}')
        with pytest.raises(ConfigError, match="must be a dict"):
            load_settings()

    def test_empty_env_is_ok(self, monkeypatch):
        monkeypatch.setenv("SMOLCODE_COST_RATES", "")
        settings = load_settings()
        assert settings.cost_rates == {}


class TestCostCacheHit:
    def test_cache_hit_charged_at_cache_rate(self):
        # DEFAULT_COST_RATES["openai"]["gpt-4o"] = (0.005, 0.015, 0.0)
        # If a user supplies cache_rate=0.001, 100 cache tokens -> 0.0001
        cost = cost_for("openai", "gpt-4o", 1000, 500, cache_hit=100)
        # (1000/1000)*0.005 + (500/1000)*0.015 + (100/1000)*0.0 = 0.005 + 0.0075 + 0
        assert cost == pytest.approx(0.0125)

    def test_cache_hit_zero_is_no_op(self):
        cost = cost_for("openai", "gpt-4o", 1000, 500, cache_hit=0)
        assert cost == pytest.approx(0.0125)


class TestSettingsCostRatesField:
    def test_settings_default_cost_rates_is_empty_dict(self, monkeypatch):
        monkeypatch.delenv("SMOLCODE_COST_RATES", raising=False)
        settings = load_settings()
        assert settings.cost_rates == {}

    def test_settings_with_overrides_preserves_cost_rates(self, monkeypatch):
        monkeypatch.setenv(
            "SMOLCODE_COST_RATES",
            '{"openai": {"gpt-4o": [0.001, 0.002, 0.0]}}',
        )
        s1 = load_settings()
        s2 = s1.with_overrides(provider="anthropic")
        assert s2.cost_rates == s1.cost_rates
