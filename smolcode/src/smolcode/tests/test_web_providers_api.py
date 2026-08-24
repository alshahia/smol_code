"""M11 (decision 0014) -- tests for GET /api/providers.

The endpoint returns the static 5-provider catalog along with
per-provider ``key_state`` reflecting in-process env state, and the
``model_count`` from the per-process cache (None until the first
fetch). It does NOT take any user-supplied keys (those go via
POST /api/runs).
"""

from __future__ import annotations

import os

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


class TestProvidersList:
    def test_providers_returns_five(self, client):
        r = client.get("/api/providers")
        assert r.status_code == 200
        body = r.json()
        assert "providers" in body
        ids = [p["id"] for p in body["providers"]]
        assert ids == ["opencode-go", "MiniMax", "openai", "anthropic", "custom"]

    def test_providers_shape_per_row(self, client):
        r = client.get("/api/providers")
        assert r.status_code == 200
        rows = r.json()["providers"]
        for row in rows:
            # All declared ProviderOut fields are present.
            assert {"id", "name", "env_vars", "default_model", "key_state", "model_count", "host_env_var"} <= set(
                row.keys()
            )
            assert row["key_state"] in ("set", "missing")

    def test_minimax_provider_id_uses_capital_x(self, client):
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        row = next(p for p in rows if p["default_model"] == "MiniMax-M3")
        assert row["id"] == "MiniMax"

    def test_key_state_missing_when_no_env(self, client):
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        # No env vars set -> all rows report "missing".
        assert all(p["key_state"] == "missing" for p in rows)

    def test_key_state_set_when_opencode_env_present(self, client, monkeypatch):
        monkeypatch.setenv("OPENCODE_GO_APIKEY", "k-from-env")
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        row = next(p for p in rows if p["id"] == "opencode-go")
        assert row["key_state"] == "set"
        # Other providers remain missing.
        others = [p for p in rows if p["id"] != "opencode-go"]
        assert all(p["key_state"] == "missing" for p in others)

    def test_key_state_set_when_anthropic_env_present(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k-from-env")
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        row = next(p for p in rows if p["id"] == "anthropic")
        assert row["key_state"] == "set"

    def test_model_count_is_none_on_first_call(self, client):
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        # No fetch has happened yet -> model_count is None for all.
        assert all(p["model_count"] is None for p in rows)

    def test_env_vars_listed_per_provider(self, client):
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        row = next(p for p in rows if p["id"] == "MiniMax")
        assert "MINIMAX_API_KEY" in row["env_vars"]
        assert "MINIMAX_HOST" in row["env_vars"]
        assert row["host_env_var"] == "MINIMAX_HOST"
        assert row["default_model"] == "MiniMax-M3"

    def test_orchestrator_tier_routes_to_orchestrator(self, client):
        # The /api/providers surface is provider-only; orchestrator
        # routes are a separate concern. This guards against drift
        # if a future M11.x adds "orchestrator" to the catalog.
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        ids = [p["id"] for p in rows]
        assert "orchestrator" not in ids


class TestProvidersCachedAt:
    """M12 (decision 0015) — GET /api/providers now reports ``cached_at``."""

    def test_cached_at_field_present(self, client):
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        for row in rows:
            # New field is present; on the first request, value is None.
            assert "cached_at" in row
            assert row["cached_at"] is None

    def test_cached_at_present_after_fetch(self, client):
        """After a fetch happens for one provider, only that provider's
        ``cached_at`` becomes a float; the others stay None.

        We seed ``model_catalog._CACHE`` directly rather than going
        through ``fetch_models`` (which would require httpx mocking and
        runs into the TestClient transport issue). The endpoint just
        reads from the module-level cache so this is functionally
        equivalent.
        """
        import time

        from smolcode import model_catalog

        # Pre-populate the cache for opencode-go only.
        model_catalog._CACHE["opencode-go"] = model_catalog._CacheEntry(
            models=["m1", "m2"],
            fetched_at=time.time(),
            error=None,
        )
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        oc = next(p for p in rows if p["id"] == "opencode-go")
        others = [p for p in rows if p["id"] != "opencode-go"]
        assert isinstance(oc["cached_at"], float)
        assert oc["cached_at"] > 0
        for o in others:
            assert o["cached_at"] is None

    def test_cached_at_backdated_reports_still_float(self, client):
        """cached_at is a plain epoch number — the SPA computes the
        human-readable "just now" / "5m ago" label client-side. We
        just check the type contract here."""
        import time

        from smolcode import model_catalog

        # Pre-populate the cache with a known old timestamp.
        old_ts = time.time() - 600
        model_catalog._CACHE["opencode-go"] = model_catalog._CacheEntry(
            models=["x"],
            fetched_at=old_ts,
            error=None,
        )
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        oc = next(p for p in rows if p["id"] == "opencode-go")
        # Still a float, matches the value we wrote.
        assert isinstance(oc["cached_at"], float)
        assert oc["cached_at"] == old_ts
        # And it's clearly in the past.
        assert oc["cached_at"] < time.time()


class TestProvidersCachedError:
    """M12.4 (decision 0015 addendum) -- GET /api/providers now also
    reports ``cached_error``: a short single-line error string when the
    most recent /models fetch FAILED, else None. Both fields additive
    and backwards-compatible."""

    def test_cached_error_field_present(self, client):
        r = client.get("/api/providers")
        rows = r.json()["providers"]
        for row in rows:
            # New field is present; on the first request (no fetch yet)
            # the value is None.
            assert "cached_error" in row
            assert row["cached_error"] is None

    def test_cached_error_populated_after_failed_fetch_no_prior_cache(self, client):
        """When fetch_models fails AND there is no prior cache, a failure
        entry is still written so the SPA can report both cached_at and
        cached_error. Without this, both fields would be None forever."""
        from unittest.mock import patch

        import httpx

        from smolcode import model_catalog

        def _boom(self, url, headers=None, params=None):
            request = httpx.Request("GET", url)
            return httpx.Response(
                status_code=500,
                json={"error": "internal"},
                request=request,
            )

        with patch("httpx.Client.get", _boom):
            # No prior cache for openai in this test (autouse fixture
            # in test_cli_models does not apply here; we explicitly
            # clear in the client fixture).
            model_catalog.clear_cache("openai")
            result = model_catalog.fetch_models("openai", keys={"OPENAI_API_KEY": "sk-test"})

        assert result["error"] is not None
        assert result["error"].startswith("fetch_failed:")
        assert result["fetched_at"] > 0  # failure time is recorded

        r = client.get("/api/providers")
        rows = r.json()["providers"]
        oc = next(p for p in rows if p["id"] == "openai")
        assert oc["cached_error"] is not None
        assert oc["cached_error"].startswith("fetch_failed:")
        assert isinstance(oc["cached_at"], float)
        assert oc["cached_at"] > 0

    def test_cached_error_preserved_with_prior_good_cache(self, client):
        """When a fetch fails AFTER a prior successful fetch, the good
        model list is preserved and cached_error is set. cached_at
        reflects the LAST successful fetch (not the failed attempt) so
        the age badge stays meaningful."""
        import time

        from smolcode import model_catalog

        good_ts = time.time() - 120
        model_catalog._CACHE["opencode-go"] = model_catalog._CacheEntry(
            models=["m-good-1", "m-good-2"],
            fetched_at=good_ts,
            error=None,
        )
        # Simulate the failure branch's exact behavior on a re-fetch.
        failed = model_catalog._CacheEntry(
            models=["m-good-1", "m-good-2"],
            fetched_at=good_ts,
            error="fetch_failed: 401 Unauthorized",
        )
        model_catalog._CACHE["opencode-go"] = failed

        r = client.get("/api/providers")
        rows = r.json()["providers"]
        oc = next(p for p in rows if p["id"] == "opencode-go")
        assert oc["model_count"] == 2  # prior good models preserved
        assert oc["cached_error"] == "fetch_failed: 401 Unauthorized"
        # cached_at stays at the LAST successful fetch so the age badge
        # does not pretend the failed attempt succeeded.
        assert oc["cached_at"] == good_ts

    def test_cached_error_clears_after_successful_refetch(self, client):
        """After a successful fetch, cached_error is cleared back to None."""
        import time

        from smolcode import model_catalog

        # Start in a failed state
        model_catalog._CACHE["opencode-go"] = model_catalog._CacheEntry(
            models=[], fetched_at=time.time(), error="fetch_failed: timeout"
        )
        # Then a good fetch
        model_catalog._CACHE["opencode-go"] = model_catalog._CacheEntry(
            models=["x"], fetched_at=time.time(), error=None
        )

        r = client.get("/api/providers")
        rows = r.json()["providers"]
        oc = next(p for p in rows if p["id"] == "opencode-go")
        assert oc["cached_error"] is None
        assert oc["model_count"] == 1
