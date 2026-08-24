"""Shared pytest fixtures for smolcode M1 tests.

Two responsibilities:
   (a) clear SMOLCODE_* + provider-key env vars so tests use defaults
   (b) disable dotenv loading so the parent .env file does not leak
       real API keys into the test environment
"""

import pytest

from smolcode import config as _config_module


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Per-test isolation: cleared env, fresh tmp workspace, no dotenv."""
    # Clear all SMOLCODE_* and provider-key env vars
    for var in [
        "SMOLCODE_WORKSPACE",
        "SMOLCODE_EXECUTOR",
        "SMOLCODE_PROVIDER",
        "SMOLCODE_MODEL",
        "SMOLCODE_LITELLM_PROXY",
        "SMOLCODE_LOG_LEVEL",
        "OPENCODE_GO_APIKEY",
        "OPENCODE_HOST",
        "MINIMAX_API_KEY",
        "MINIMAX_HOST",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CUSTOM_BASE_URL",
        "CUSTOM_API_KEY",
    ]:
        monkeypatch.delenv(var, raising=False)
    # Point workspace at a fresh tmp dir
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path / "ws"))
    # Disable dotenv loading so tests do not pick up the real parent .env
    monkeypatch.setattr(_config_module, "load_dotenv_into_environ", lambda *a, **kw: None)
    return tmp_path
