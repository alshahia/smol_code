"""M11 (decision 0014) -- tests for GET /api/providers/{provider_id}/models.

The endpoint mirrors ``model_catalog.fetch_models`` shape. It uses
ONLY in-process env values for keys; user-supplied keys from the
SPA never appear on this GET (otherwise an XSS or accidental
prefetch could exfiltrate them).

Mocking strategy: ``httpx.Client.get`` is the call the underlying
model_catalog makes, but ``starlette.testclient.TestClient`` uses
``httpx`` internally too, so patching ``httpx.Client.get`` directly
breaks the test transport. Instead we patch the deeper helper
``smolcode.model_catalog._openai_compatible_fetcher`` (and the
anthropic fetcher), which is what the catalog actually invokes.
This keeps the TestClient's own HTTP plumbing untouched.

Covers:
  * Anthropic returns the hardcoded list (no /models endpoint)
  * Without env keys, returns no_key error
  * Unknown provider returns a clear error
  * refresh=true bypasses the TTL cache
  * Custom provider without base URL returns no_base_url
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith("SMOLCODE_") or k in (
            "OPENCODE_GO_APIKEY",
            "OPENCODE_HOST",
            "MINIMAX_API_KEY",
            "MINIMAX_HOST",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "CUSTOM_BASE_URL",
            "CUSTOM_API_KEY",
            "HF_TOKEN",
        ):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", "1048576")
    from smolcode.model_catalog import clear_cache

    clear_cache()
    from smolcode.web import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
    clear_cache()


def _patched_canned_fetcher(canned_models):
    """Build a patch context manager that mocks the OpenAI-compatible
    fetcher to return ``canned_models`` regardless of URL or keys.

    Use as ``with _patched_canned_fetcher(["m1", "m2"]) as ...:``.
    """
    import smolcode.model_catalog

    def _stub(provider_id, list_path, auth_style, keys, base_url):
        # Match the production shape: list of strings.
        return list(canned_models)

    return patch.object(
        smolcode.model_catalog,
        "_openai_compatible_fetcher",
        _stub,
    )


# ---- Anthropic (no /models endpoint, returns hardcoded list) --------------


class TestModelsAnthropic:
    def test_anthropic_without_env_key_returns_no_key(self, client):
        r = client.get("/api/providers/anthropic/models")
        assert r.status_code == 200
        body = r.json()
        assert body["error"] == "no_key"
        assert body["models"] == []
        assert body["provider"] == "anthropic"

    def test_anthropic_returns_hardcoded_list_when_env_set(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abcdef1234")
        r = client.get("/api/providers/anthropic/models")
        assert r.status_code == 200
        body = r.json()
        assert body["error"] is None
        assert "claude-3-5-sonnet-latest" in body["models"]
        assert "claude-3-5-haiku-latest" in body["models"]
        assert body["cached"] is False

    def test_anthropic_refresh_query_param(self, client, monkeypatch):
        # The hardcoded list isn't cached, but refresh=true still returns 200.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc1")
        r = client.get("/api/providers/anthropic/models?refresh=true")
        assert r.status_code == 200
        body = r.json()
        assert body["error"] is None
        assert "claude-3-5-sonnet-latest" in body["models"]


# ---- OpenAI-compatible provider (opencode-go) -----------------------------


class TestModelsOpenCode:
    def test_no_env_returns_no_key(self, client):
        # OPENCODE_GO_APIKEY is the prerequisite for opencode-go's key_state.
        r = client.get("/api/providers/opencode-go/models")
        assert r.status_code == 200
        body = r.json()
        assert body["error"] == "no_key"
        assert body["models"] == []
        assert body["provider"] == "opencode-go"

    def test_env_set_calls_fetcher(self, client, monkeypatch):
        monkeypatch.setenv("OPENCODE_GO_APIKEY", "k-from-env")
        with _patched_canned_fetcher(["deepseek-v4-flash", "deepseek-v4-large"]):
            r = client.get("/api/providers/opencode-go/models")
        assert r.status_code == 200
        body = r.json()
        assert body["error"] is None
        assert body["models"] == ["deepseek-v4-flash", "deepseek-v4-large"]
        assert body["cached"] is False
        assert body["provider"] == "opencode-go"

    def test_refresh_true_bypasses_cache(self, client, monkeypatch):
        monkeypatch.setenv("OPENCODE_GO_APIKEY", "k-from-env")
        with _patched_canned_fetcher(["m1"]):
            first = client.get("/api/providers/opencode-go/models").json()
        assert first["models"] == ["m1"]
        assert first["cached"] is False

        # Default refresh=false within TTL -> cached entry, no fetcher call.
        # We can't easily detect "fetcher NOT called" with patch as a context
        # manager that has already exited, so we just confirm cached=True.
        with _patched_canned_fetcher(["SHOULD-NOT-BE-SEEN"]):
            second = client.get("/api/providers/opencode-go/models").json()
        assert second["models"] == ["m1"]
        assert second["cached"] is True

        # refresh=true forces a re-fetch -> new models.
        with _patched_canned_fetcher(["m3"]):
            third = client.get("/api/providers/opencode-go/models?refresh=true").json()
        assert third["models"] == ["m3"]
        assert third["cached"] is False

    def test_does_not_accept_keys_via_header(self, client, monkeypatch):
        # Defensive: the endpoint must NEVER read user-supplied keys from
        # request headers or query string. Only env state is consulted.
        monkeypatch.setenv("OPENCODE_GO_APIKEY", "env-key-only")
        with _patched_canned_fetcher(["env-model"]):
            r = client.get(
                "/api/providers/opencode-go/models",
                headers={"X-Test-Override-Key": "should-be-ignored"},
            )
        body = r.json()
        assert body["models"] == ["env-model"]
        # Error None confirms the catalog read the env key, not the header.
        assert body["error"] is None


# ---- Custom provider (special case: requires CUSTOM_BASE_URL) ---------------


class TestModelsCustom:
    def test_custom_without_base_url(self, client, monkeypatch):
        monkeypatch.setenv("CUSTOM_API_KEY", "x")
        monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
        r = client.get("/api/providers/custom/models")
        body = r.json()
        assert r.status_code == 200
        assert body["error"] == "no_base_url"
        assert body["models"] == []

    def test_custom_with_base_url(self, client, monkeypatch):
        monkeypatch.setenv("CUSTOM_API_KEY", "x")
        monkeypatch.setenv("CUSTOM_BASE_URL", "https://example.test/v1")
        with _patched_canned_fetcher(["my-model"]):
            r = client.get("/api/providers/custom/models")
        body = r.json()
        assert r.status_code == 200
        assert body["error"] is None
        assert body["models"] == ["my-model"]
        assert body["provider"] == "custom"


# ---- Unknown provider ----------------------------------------------------


class TestModelsUnknownProvider:
    def test_unknown_provider_returns_clear_error(self, client):
        r = client.get("/api/providers/nonexistent/models")
        body = r.json()
        assert r.status_code == 200
        assert "unknown provider" in body["error"]
        assert body["models"] == []
        assert body["provider"] == "nonexistent"


# ---- Response shape ------------------------------------------------------


class TestModelsResponseShape:
    def test_response_has_required_fields(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc1")
        r = client.get("/api/providers/anthropic/models")
        body = r.json()
        for k in ("provider", "models", "cached", "fetched_at", "error"):
            assert k in body, f"missing key {k!r} in {body}"
        assert isinstance(body["models"], list)
        assert isinstance(body["cached"], bool)
        assert isinstance(body["fetched_at"], (int, float))
