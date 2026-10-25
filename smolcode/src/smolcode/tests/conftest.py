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
    "GOOGLE_API_KEY",
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
    # Phase 3 (decision 0038, review R5): default the suite to the local
    # executor. create_app()'s lifespan calls ensure_tier_images when the
    # executor is docker, so every TestClient(app) boot tried to build the
    # tier images; with no Docker daemon that surfaced as ~98 setup
    # errors/failures on any Docker-less machine (including CI's
    # windows-latest / ubuntu-latest runners) rather than as real test
    # results. Tests that genuinely need the docker executor request the
    # docker_executor fixture below and are marked @pytest.mark.docker.
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    # Phase 2 (H5): create_app now builds a real AuditSink; keep the
    # default log inside tmp so tests never write logs/audit.jsonl
    # into the repo working tree.
    monkeypatch.setenv("SMOLCODE_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    # Disable dotenv loading so tests do not pick up the real parent .env
    monkeypatch.setattr(_config_module, "load_dotenv_into_environ", lambda *a, **kw: None)
    return tmp_path


@pytest.fixture
def docker_executor(monkeypatch):
    """Opt back in to the docker executor for tests that need it.

    _isolate_env runs first (autouse) and sets SMOLCODE_EXECUTOR=local;
    this fixture flips it back for the duration of one test. Pair it with
    @pytest.mark.docker so the test is deselected in Docker-less runs
    instead of failing at setup.
    """
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "docker")
    return "docker"
