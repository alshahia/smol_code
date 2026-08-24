"""Tests for smolcode.model_catalog (M6).

Covers:
  * ProviderSpec + PROVIDERS tuple shape
  * 1-hour TTL behavior (cache hit / miss / refresh)
  * `no_key` guard (no HTTP call made when key is missing)
  * Network failure returns cached value when present
  * Anthropic hardcoded list (no /models endpoint)
  * Unknown provider returns a clear error
  * `custom` provider without CUSTOM_BASE_URL returns `no_base_url`
  * `get_providers()` shape + `model_count` is None until first fetch
  * `clear_cache()` semantics
"""

from __future__ import annotations

import time
from unittest.mock import patch

import httpx
import pytest

from smolcode.model_catalog import (
    _CACHE,
    _CACHE_TTL_S,
    PROVIDERS,
    _is_api_key_env,
    clear_cache,
    fetch_models,
    get_provider,
    get_providers,
)


# ---- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """Each test starts with an empty cache."""
    clear_cache()
    yield
    clear_cache()


def _fake_response(json_body, status_code=200):
    # httpx.Response requires a Request to call .raise_for_status(). Build
    # one matching the URL we expect the catalog to hit.
    request = httpx.Request("GET", "https://example.test/v1/models")
    return httpx.Response(status_code=status_code, json=json_body, request=request)


def _patch_client(json_body, status_code=200, side_effect=None):
    """Return a context manager that patches httpx.Client.get.

    When entered, `httpx.Client().get(url)` returns `_fake_response(json_body)`
    or raises `side_effect` if provided.
    """

    def _get(self, url, headers=None, params=None):
        if side_effect is not None:
            raise side_effect
        return _fake_response(json_body, status_code=status_code)

    return patch("httpx.Client.get", _get)


# ---- _is_api_key_env helper ------------------------------------------------


def test_is_api_key_env_recognises_standard_suffix():
    assert _is_api_key_env("OPENAI_API_KEY")
    assert _is_api_key_env("MINIMAX_API_KEY")
    assert _is_api_key_env("ANTHROPIC_API_KEY")
    assert _is_api_key_env("CUSTOM_API_KEY")


def test_is_api_key_env_recognises_opencode_apikey_suffix():
    """OPENCODE_GO_APIKEY ends in _APIKEY (no underscore) per decision 0001."""
    assert _is_api_key_env("OPENCODE_GO_APIKEY")


def test_is_api_key_env_recognises_hf_token():
    assert _is_api_key_env("HF_TOKEN")


def test_is_api_key_env_rejects_non_key_vars():
    assert not _is_api_key_env("OPENCODE_HOST")
    assert not _is_api_key_env("MINIMAX_HOST")
    assert not _is_api_key_env("CUSTOM_BASE_URL")
    assert not _is_api_key_env("PATH")


# ---- ProviderSpec + PROVIDERS tuple ----------------------------------------


def test_providers_tuple_has_five_entries():
    assert len(PROVIDERS) == 5
    ids = [p.id for p in PROVIDERS]
    assert ids == ["opencode-go", "MiniMax", "openai", "anthropic", "custom"]


def test_minimax_provider_uses_capital_x_id():
    spec = get_provider("MiniMax")
    assert spec is not None
    assert spec.id == "MiniMax"
    assert "MINIMAX_API_KEY" in spec.env_vars
    assert "MINIMAX_HOST" in spec.env_vars
    assert spec.host_env_var == "MINIMAX_HOST"
    assert spec.default_model == "MiniMax-M3"


def test_opencode_go_provider_has_host_env_var():
    spec = get_provider("opencode-go")
    assert spec is not None
    assert spec.host_env_var == "OPENCODE_HOST"
    assert spec.default_model == "deepseek-v4-flash"


def test_get_provider_unknown_returns_none():
    assert get_provider("nope") is None


def test_get_providers_shape_includes_required_keys():
    rows = get_providers(keys={"OPENCODE_GO_APIKEY": "k", "MINIMAX_API_KEY": "k"})
    assert len(rows) == 5
    row_opencode = next(r for r in rows if r["id"] == "opencode-go")
    for k in ("id", "name", "env_vars", "default_model", "key_state", "model_count", "host_env_var"):
        assert k in row_opencode
    assert row_opencode["model_count"] is None


# ---- key_state -------------------------------------------------------------


def test_key_state_set_when_opencode_key_present():
    rows = get_providers(keys={"OPENCODE_GO_APIKEY": "k"})
    row = next(r for r in rows if r["id"] == "opencode-go")
    assert row["key_state"] == "set"


def test_key_state_missing_when_opencode_key_absent():
    rows = get_providers(keys={})
    row = next(r for r in rows if r["id"] == "opencode-go")
    assert row["key_state"] == "missing"


def test_key_state_missing_when_minimax_key_absent():
    rows = get_providers(keys={})
    row = next(r for r in rows if r["id"] == "MiniMax")
    assert row["key_state"] == "missing"


# ---- no_key guard ----------------------------------------------------------


def test_fetch_models_returns_no_key_without_http_call():
    """fetch_models must NOT hit the network when the provider key is missing."""
    with _patch_client(json_body={}):
        result = fetch_models("opencode-go", keys={})
    assert result["error"] == "no_key"
    assert result["models"] == []
    assert result["cached"] is False


# ---- TTL behavior ---------------------------------------------------------


def test_fetch_models_first_call_makes_http_and_caches():
    fake = {"data": [{"id": "deepseek-v4-flash"}, {"id": "deepseek-v4-flash-2"}]}
    with _patch_client(fake):
        result = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    assert result["error"] is None
    assert result["models"] == ["deepseek-v4-flash", "deepseek-v4-flash-2"]
    assert result["cached"] is False
    assert "opencode-go" in _CACHE


def test_fetch_models_cache_hit_within_ttl():
    fake = {"data": [{"id": "m1"}]}
    with _patch_client(fake):
        first = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    assert first["cached"] is False

    # Within TTL: no HTTP call, cached=True, same models.
    with _patch_client({"data": [{"id": "SHOULD-NOT-SEE"}]}):
        second = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    assert second["cached"] is True
    assert second["models"] == ["m1"]
    assert second["fetched_at"] == first["fetched_at"]


def test_fetch_models_ttl_expired_refetches():
    """Force the cache entry to look older than _CACHE_TTL_S."""
    fake = {"data": [{"id": "m1"}]}
    with _patch_client(fake):
        first = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    assert first["cached"] is False

    # Backdate the cache to 1s past TTL.
    _CACHE["opencode-go"].fetched_at = time.time() - _CACHE_TTL_S - 1.0

    fake2 = {"data": [{"id": "m2"}]}
    with _patch_client(fake2):
        second = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    assert second["cached"] is False
    assert second["models"] == ["m2"]


def test_fetch_models_refresh_true_bypasses_ttl():
    fake = {"data": [{"id": "m1"}]}
    with _patch_client(fake):
        fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})

    fake2 = {"data": [{"id": "m2"}]}
    with _patch_client(fake2):
        result = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"}, refresh=True)
    assert result["cached"] is False
    assert result["models"] == ["m2"]


# ---- network failure handling ---------------------------------------------


def test_fetch_models_network_failure_returns_cached_value():
    """If a network error happens after a successful cache, return the
    cached models with error='fetch_failed: ...'.

    Uses `refresh=True` on the second call to force the HTTP path; the
    1-hour TTL otherwise short-circuits before the network is touched.
    """
    fake_ok = {"data": [{"id": "m1"}]}
    with _patch_client(fake_ok):
        first = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    assert first["models"] == ["m1"]
    assert first["error"] is None

    with _patch_client({}, side_effect=httpx.ConnectError("boom")):
        second = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"}, refresh=True)
    assert second["models"] == ["m1"]
    assert second["cached"] is True
    assert second["error"] is not None
    assert "fetch_failed" in second["error"]


def test_fetch_models_network_failure_no_cache_returns_empty():
    with _patch_client({}, side_effect=httpx.ConnectError("boom")):
        result = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    assert result["models"] == []
    assert result["cached"] is False
    assert "fetch_failed" in result["error"]


# ---- auth failure ----------------------------------------------------------


def test_fetch_models_auth_failure_returns_no_cached_value():
    """401/403 raises PermissionError; no cache to fall back to => empty."""
    with _patch_client({}, status_code=401):
        result = fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    assert result["models"] == []
    assert "auth failed" in result["error"]


# ---- anthropic hardcoded list ---------------------------------------------


def test_anthropic_returns_hardcoded_list_without_http():
    with _patch_client({}):
        result = fetch_models("anthropic", keys={"ANTHROPIC_API_KEY": "k"})
    assert result["error"] is None
    assert "claude-3-5-sonnet-latest" in result["models"]
    assert "claude-3-5-haiku-latest" in result["models"]
    assert result["cached"] is False


# ---- unknown provider ------------------------------------------------------


def test_fetch_models_unknown_provider_returns_error():
    result = fetch_models("nope-not-a-provider", keys={"NOPE_API_KEY": "k"})
    assert "unknown provider" in result["error"]
    assert result["models"] == []


# ---- custom provider without base URL --------------------------------------


def test_custom_provider_without_base_url_returns_no_base_url(monkeypatch):
    """`custom` requires CUSTOM_BASE_URL. With no host_env_var override
    and an empty base_url, fetch must short-circuit with no_base_url
    rather than attempt a connection to a malformed URL."""
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    result = fetch_models("custom", keys={"CUSTOM_API_KEY": "k"})
    assert result["error"] == "no_base_url"
    assert result["models"] == []


def test_custom_provider_with_base_url_attempts_fetch(monkeypatch):
    monkeypatch.setenv("CUSTOM_BASE_URL", "https://example.local/v1")
    fake = {"data": [{"id": "my-model"}]}
    with _patch_client(fake):
        result = fetch_models("custom", keys={"CUSTOM_API_KEY": "k"})
    assert result["error"] is None
    assert result["models"] == ["my-model"]


# ---- clear_cache -----------------------------------------------------------


def test_clear_cache_specific_provider():
    with _patch_client({"data": [{"id": "m1"}]}):
        fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    with _patch_client({"data": [{"id": "m2"}]}):
        fetch_models("MiniMax", keys={"MINIMAX_API_KEY": "k"})
    assert "opencode-go" in _CACHE
    assert "MiniMax" in _CACHE

    clear_cache("opencode-go")
    assert "opencode-go" not in _CACHE
    assert "MiniMax" in _CACHE


def test_clear_cache_all():
    with _patch_client({"data": [{"id": "m1"}]}):
        fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "k"})
    with _patch_client({"data": [{"id": "m2"}]}):
        fetch_models("MiniMax", keys={"MINIMAX_API_KEY": "k"})
    assert _CACHE

    clear_cache()
    assert _CACHE == {}


# ---- TTL constant ---------------------------------------------------------


def test_cache_ttl_is_one_hour():
    assert _CACHE_TTL_S == 3600.0
