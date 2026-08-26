"""Shared pytest fixtures for smolcode M1 tests.

Two responsibilities:
   (a) clear SMOLCODE_* + provider-key env vars so tests use defaults
   (b) disable dotenv loading so the parent .env file does not leak
       real API keys into the test environment
"""

import os

import pytest

from smolcode import config as _config_module


# Provider-key / provider-host variables do not share a common prefix,
# so they are listed explicitly. Anything SMOLCODE_-prefixed is cleared
# by the loop below, which stays correct as new settings are added
# (SMOLCODE_UPLOAD_DIR, SMOLCODE_PROJECTS, SMOLCODE_MCP_CONFIG, ...).
_PROVIDER_ENV_VARS = (
    "OPENCODE_GO_APIKEY",
    "OPENCODE_HOST",
    "MINIMAX_API_KEY",
    "MINIMAX_HOST",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CUSTOM_BASE_URL",
    "CUSTOM_API_KEY",
    "HF_TOKEN",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Per-test isolation: cleared env, fresh tmp workspace, no dotenv."""
    # Prefix-based clear so new SMOLCODE_* settings cannot silently
    # drift past this fixture.
    for var in list(os.environ):
        if var.startswith("SMOLCODE_"):
            monkeypatch.delenv(var, raising=False)
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Point workspace at a fresh tmp dir
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path / "ws"))
    # Disable dotenv loading so tests do not pick up the real parent .env
    monkeypatch.setattr(_config_module, "load_dotenv_into_environ", lambda *a, **kw: None)
    return tmp_path
