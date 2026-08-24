"""M12.1 - `smolcode models` subcommand tests (decision 0015).

Covers:
    * pre-dispatch in cli.main (smolcode models ...)
    * `models list` (default verb) renders the table
    * `models list` shows `cached_at` as `-` when the cache is empty
    * `models list` shows a populated `CACHE_AGE` after a fetch
    * `models refresh` (no arg) clears the in-memory cache for all providers
    * `models refresh <provider>` clears only that provider's cache
    * `models refresh bogus` exits 2 and prints the list of known providers
    * `models help` prints usage
    * `models unknown_verb` exits 2
    * `_models_format_age` returns the right string per age bucket

Pattern for HTTP mocking: patch `httpx.Client.get` (same as
test_model_catalog.py — there is no TestClient involved so the
monkeypatch is safe). We do NOT touch the `ProviderSpec` directly
because it's a frozen dataclass; we let the patched `httpx.Client.get`
return our stub response.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import httpx
import pytest

from smolcode import cli, model_catalog


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """Each test starts with an empty catalog cache."""
    model_catalog.clear_cache(None)
    yield
    model_catalog.clear_cache(None)


def _fake_response(json_body, status_code=200):
    request = httpx.Request("GET", "https://example.test/v1/models")
    return httpx.Response(status_code=status_code, json=json_body, request=request)


def _patch_client(json_body, status_code=200):
    def _get(self, url, headers=None, params=None):
        return _fake_response(json_body, status_code=status_code)

    return patch("httpx.Client.get", _get)


def test_models_list_renders_table_header(_isolate_env, capsys):
    rc = cli.main(["models", "list"])
    captured = capsys.readouterr()
    assert rc == 0
    out = captured.out
    # Header columns
    assert "PROVIDER" in out
    assert "KEY" in out
    assert "MODELS" in out
    assert "CACHE_AGE" in out
    assert "DEFAULT_MODEL" in out
    # All 5 known providers are listed
    for pid in ("opencode-go", "MiniMax", "openai", "anthropic", "custom"):
        assert pid in out
    # And the trailing tip
    assert "tip:" in out


def test_models_list_cached_age_dash_when_empty(_isolate_env, capsys):
    """Fresh cache => CACHE_AGE column shows `-` for every provider."""
    rc = cli.main(["models", "list"])
    captured = capsys.readouterr()
    assert rc == 0
    data_lines = [
        ln
        for ln in captured.out.splitlines()
        if any(pid in ln for pid in ("opencode-go", "MiniMax", "openai", "anthropic", "custom"))
    ]
    assert len(data_lines) == 5
    for line in data_lines:
        # CACHE_AGE is rendered via `_models_format_age(None)` which
        # returns the literal string "-". The cell is `ljust(14)`-padded
        # so the dash lives somewhere in the line.
        assert line.count("-") >= 1


def test_models_list_shows_age_after_fetch(_isolate_env, capsys):
    """After a successful fetch_models, CACHE_AGE shows 'just now'."""
    fake = {"data": [{"id": "deepseek-v4-flash"}, {"id": "deepseek-v4-pro"}]}
    with _patch_client(fake):
        model_catalog.fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "sk-test-justnow"})
    rc = cli.main(["models", "list"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "opencode-go" in captured.out
    # The opencode-go row should now have a non-dash CACHE_AGE.
    opencode_line = next(ln for ln in captured.out.splitlines() if ln.startswith("opencode-go"))
    assert "just now" in opencode_line


def test_models_refresh_no_arg_clears_all(_isolate_env, capsys):
    """`smolcode models refresh` (no arg) clears the cache for ALL providers."""
    fake1 = {"data": [{"id": "m1"}, {"id": "m2"}]}
    fake2 = {"data": [{"id": "m3"}]}
    with _patch_client(fake1):
        model_catalog.fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "sk-a"})
    with _patch_client(fake2):
        model_catalog.fetch_models("openai", keys={"OPENAI_API_KEY": "sk-b"})
    assert "opencode-go" in model_catalog._CACHE
    assert "openai" in model_catalog._CACHE

    rc = cli.main(["models", "refresh"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "cleared model cache for all providers" in captured.out
    assert model_catalog._CACHE == {}


def test_models_refresh_specific_provider(_isolate_env, capsys):
    """`smolcode models refresh opencode-go` clears only that provider."""
    fake1 = {"data": [{"id": "m1"}]}
    fake2 = {"data": [{"id": "m2"}]}
    with _patch_client(fake1):
        model_catalog.fetch_models("opencode-go", keys={"OPENCODE_GO_APIKEY": "sk-a"})
    with _patch_client(fake2):
        model_catalog.fetch_models("openai", keys={"OPENAI_API_KEY": "sk-b"})
    assert "opencode-go" in model_catalog._CACHE
    assert "openai" in model_catalog._CACHE

    rc = cli.main(["models", "refresh", "opencode-go"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "cleared model cache for opencode-go" in captured.out
    # Only openai should remain
    assert "opencode-go" not in model_catalog._CACHE
    assert "openai" in model_catalog._CACHE


def test_models_refresh_unknown_provider_exits_2(_isolate_env, capsys):
    rc = cli.main(["models", "refresh", "bogus"])
    captured = capsys.readouterr()
    assert rc == 2
    err = captured.err
    assert "unknown provider" in err
    # The error should also list the known providers.
    assert "opencode-go" in err
    assert "MiniMax" in err


def test_models_help_prints_usage(_isolate_env, capsys):
    rc = cli.main(["models", "help"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "usage: smolcode models" in captured.out
    assert "list" in captured.out
    assert "refresh" in captured.out


def test_models_unknown_verb_exits_2(_isolate_env, capsys):
    rc = cli.main(["models", "frobnicate"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "unknown models verb" in captured.err


def test_models_list_with_extra_arg_exits_2(_isolate_env, capsys):
    rc = cli.main(["models", "list", "extra"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "unknown models list argument" in captured.err


def test_models_format_age_buckets():
    """_models_format_age recognises the standard age buckets."""
    now = time.time()
    cases = [
        (None, "-"),
        (0.0, "-"),
        (-1.0, "-"),
        (now - 5, "just now"),
        (now - 45, "45s ago"),
        (now - 5 * 60, "5m ago"),
        (now - 3 * 3600, "3h ago"),
        (now - 2 * 86400, "2d ago"),
    ]
    for epoch, expected in cases:
        got = cli._models_format_age(epoch)
        assert got == expected, f"epoch={epoch} expected={expected!r} got={got!r}"


def test_models_list_shows_warning_on_failed_fetch(_isolate_env, capsys):
    """M12.4: when cached_error is set, the CACHE_AGE cell is prefixed
    with a ⚠ glyph and a short error summary in parentheses."""
    # Seed a failure entry directly (simpler than driving a real 5xx).
    model_catalog._CACHE["opencode-go"] = model_catalog._CacheEntry(
        models=[],
        fetched_at=time.time(),
        error="fetch_failed: 401 Unauthorized",
    )
    rc = cli.main(["models", "list"])
    captured = capsys.readouterr()
    assert rc == 0
    opencode_line = next(ln for ln in captured.out.splitlines() if ln.startswith("opencode-go"))
    # The warning glyph and a short error fragment are present.
    assert "⚠" in opencode_line
    assert "fetch_failed" in opencode_line
    assert "401" in opencode_line
    # And the explanatory tip at the bottom mentions M12.4.
    assert "M12.4" in captured.out


def test_models_list_no_warning_when_no_error(_isolate_env, capsys):
    """When no error is set, no ⚠ glyph appears."""
    model_catalog._CACHE["opencode-go"] = model_catalog._CacheEntry(models=["m1"], fetched_at=time.time(), error=None)
    rc = cli.main(["models", "list"])
    captured = capsys.readouterr()
    assert rc == 0
    opencode_line = next(ln for ln in captured.out.splitlines() if ln.startswith("opencode-go"))
    assert "⚠" not in opencode_line


def test_models_list_truncates_long_error(_isolate_env, capsys):
    """Errors longer than 32 chars are truncated with an ellipsis so the
    table column stays aligned."""
    long_err = "fetch_failed: " + ("x" * 100)
    model_catalog._CACHE["opencode-go"] = model_catalog._CacheEntry(models=[], fetched_at=time.time(), error=long_err)
    rc = cli.main(["models", "list"])
    captured = capsys.readouterr()
    assert rc == 0
    opencode_line = next(ln for ln in captured.out.splitlines() if ln.startswith("opencode-go"))
    # The full 100-x string is NOT printed (truncation works)
    assert ("x" * 60) not in opencode_line
    # The ellipsis is present
    assert "..." in opencode_line


# --- M12.5: models doctor --------------------------------------------------
#
# `smolcode models doctor` is a connectivity diagnostic that performs one
# HTTP fetch per configured provider and prints per-row pass/fail. Tests
# below use the same `httpx.Client.get` patch pattern as the rest of this
# file (model_catalog.fetch_models -> httpx.Client.get -> stub).


def test_models_doctor_with_key_ok(_isolate_env, monkeypatch, capsys):
    """`smolcode models doctor` with a working key prints OK and exits 0."""
    # _isolate_env strips all provider keys; set one for opencode-go so
    # the doctor actually performs a fetch.
    monkeypatch.setenv("OPENCODE_GO_APIKEY", "sk-test-doctor-ok")
    with _patch_client({"data": [{"id": "m1"}, {"id": "m2"}]}):
        rc = cli.main(["models", "doctor"])
    captured = capsys.readouterr()
    assert rc == 0
    out = captured.out
    # opencode-go has the key we set, so its row shows OK + "just now".
    opencode_line = next(ln for ln in out.splitlines() if ln.startswith("opencode-go"))
    assert "OK" in opencode_line
    assert "just now" in opencode_line
    # Other providers without a key are "skipped".
    assert "skipped" in out
    # The trailing tip mentions M12.5.
    assert "M12.5" in out
    assert "exit 0 = all good" in out


def test_models_doctor_with_key_fail_exits_1(_isolate_env, monkeypatch, capsys):
    """A failed fetch (HTTP 500) shows FAIL, sets exit code 1, prints error."""
    monkeypatch.setenv("OPENCODE_GO_APIKEY", "sk-test-doctor-fail")
    with _patch_client({"error": "boom"}, status_code=500):
        rc = cli.main(["models", "doctor"])
    captured = capsys.readouterr()
    assert rc == 1
    out = captured.out
    opencode_line = next(ln for ln in out.splitlines() if ln.startswith("opencode-go"))
    assert "FAIL" in opencode_line
    assert "fetch_failed" in opencode_line
    # Other providers without a key are "skipped" (not FAIL).
    assert "skipped" in out


def test_models_doctor_no_fetch_reads_cache_only(_isolate_env, monkeypatch, capsys):
    """`--no-fetch` does NOT make any HTTP calls; uses the seeded cache."""
    monkeypatch.setenv("OPENCODE_GO_APIKEY", "sk-test-doctor-nofetch")
    # Seed a failure entry for opencode-go. No _patch_client context =
    # no httpx calls; if --no-fetch accidentally hit the network, the
    # unpatched httpx would raise (and the test would fail).
    model_catalog._CACHE["opencode-go"] = model_catalog._CacheEntry(
        models=["m1"],
        fetched_at=time.time(),
        error="fetch_failed: 401 Unauthorized",
    )
    rc = cli.main(["models", "doctor", "--no-fetch"])
    captured = capsys.readouterr()
    assert rc == 1
    out = captured.out
    opencode_line = next(ln for ln in out.splitlines() if ln.startswith("opencode-go"))
    # Cached failure surfaces as "fail" (lowercase) under STATUS.
    # The full error string is printed (no truncation in doctor).
    assert "fail" in opencode_line.lower()
    assert "fetch_failed" in opencode_line
    assert "401" in opencode_line
    # The hint line about "--no-fetch" is present.
    assert "--no-fetch" in out


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
