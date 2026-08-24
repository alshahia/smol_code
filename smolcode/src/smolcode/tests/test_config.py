"""M1.2 — config tests (3 tests)."""

from smolcode.config import (
    ConfigError,
    as_dict,
    load_settings,
)


def test_defaults_resolve_when_no_env_set(_isolate_env):
    s = load_settings()
    assert s.provider == "opencode-go"
    assert s.model == "deepseek-v4-flash"
    assert s.executor == "docker"
    assert s.log_level == "INFO"
    assert s.litellm_proxy is None


def test_cli_overrides_win_over_env(_isolate_env, monkeypatch):
    monkeypatch.setenv("SMOLCODE_PROVIDER", "openai")
    monkeypatch.setenv("SMOLCODE_MODEL", "gpt-4o")
    s = load_settings(cli_overrides={"provider": "MiniMax", "model": "MiniMax-M3"})
    assert s.provider == "MiniMax"
    assert s.model == "MiniMax-M3"


def test_invalid_provider_raises(_isolate_env, monkeypatch):
    monkeypatch.setenv("SMOLCODE_PROVIDER", "not-a-provider")
    try:
        load_settings()
    except ConfigError as e:
        assert "unknown provider" in str(e)
    else:
        raise AssertionError("expected ConfigError")


def test_as_dict_round_trip(_isolate_env):
    s = load_settings()
    d = as_dict(s)
    assert d["provider"] == "opencode-go"
    assert d["tiers"]["restricted"]["network"] == "none"
    assert d["tiers"]["restricted"]["docker_image"] == "smolcode:restricted"
