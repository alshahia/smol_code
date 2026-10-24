"""Phase 8 (decision 0043): container limits + no-cost-cap warning.

Pure-unit tests: no Docker daemon, no network, no subprocesses.
"""

from __future__ import annotations

import logging

import pytest

from smolcode import config as config_module
from smolcode.agents.base import _container_limit_kwargs, _executor_kwargs_for
from smolcode.config import (
    DEFAULT_CONTAINER_LIMITS,
    Settings,
    as_dict,
    load_settings,
    warn_if_no_cost_caps,
)


# ---- container limits ------------------------------------------------------


class TestContainerLimitDefaults:
    def test_defaults_are_conservative(self):
        assert DEFAULT_CONTAINER_LIMITS["restricted"] == {"mem_limit": "2g", "cpus": 1.0, "pids_limit": 256}
        assert DEFAULT_CONTAINER_LIMITS["elevated"] == {"mem_limit": "4g", "cpus": 2.0, "pids_limit": 512}
        # full_access is the explicit power tier: no hidden ceiling.
        assert DEFAULT_CONTAINER_LIMITS["full_access"] == {}

    def test_settings_default_is_a_defensive_copy(self):
        first = load_settings()
        second = load_settings()
        first.container_limits["restricted"]["mem_limit"] = "16g"
        assert second.container_limits["restricted"]["mem_limit"] == "2g"
        assert DEFAULT_CONTAINER_LIMITS["restricted"]["mem_limit"] == "2g"

    def test_with_executor_and_with_overrides_preserve_limits(self):
        settings = load_settings()
        assert settings.with_executor("local").container_limits == settings.container_limits
        assert settings.with_overrides(provider="MiniMax").container_limits == settings.container_limits

    def test_explicit_mapping_replaces_defaults(self):
        settings = Settings(
            workspace=".",
            executor="docker",
            provider="opencode-go",
            model="m",
            litellm_proxy=None,
            log_level="INFO",
            tiers={},
            container_limits={"restricted": {"mem_limit": "512m"}},
        )
        assert settings.container_limits == {"restricted": {"mem_limit": "512m"}}
        assert "elevated" not in settings.container_limits

    def test_with_overrides_can_replace_the_mapping(self):
        settings = load_settings()
        narrowed = settings.with_overrides(container_limits={"restricted": {"pids_limit": 64}})
        assert narrowed.container_limits == {"restricted": {"pids_limit": 64}}
        assert "elevated" in settings.container_limits

    def test_as_dict_exposes_effective_limits(self):
        data = as_dict(load_settings())
        assert data["container_limits"]["restricted"]["mem_limit"] == "2g"
        assert data["container_limits"]["full_access"] == {}


class TestContainerLimitKwargs:
    def test_restricted_defaults_become_docker_sdk_kwargs(self):
        settings = load_settings().with_executor("docker")
        kwargs = _container_limit_kwargs("restricted", settings)
        assert kwargs == {"mem_limit": "2g", "nano_cpus": 1_000_000_000, "pids_limit": 256}

    def test_elevated_defaults(self):
        settings = load_settings().with_executor("docker")
        kwargs = _container_limit_kwargs("elevated", settings)
        assert kwargs == {"mem_limit": "4g", "nano_cpus": 2_000_000_000, "pids_limit": 512}

    def test_full_access_has_no_implicit_ceiling(self):
        settings = load_settings().with_executor("docker")
        assert _container_limit_kwargs("full_access", settings) == {}

    def test_limits_reach_the_executor_run_kwargs(self):
        settings = load_settings().with_executor("docker")
        executor_kwargs = _executor_kwargs_for("docker", settings.tiers["restricted"], settings)
        run_kwargs = executor_kwargs["container_run_kwargs"]
        assert run_kwargs["mem_limit"] == "2g"
        assert run_kwargs["nano_cpus"] == 1_000_000_000
        assert run_kwargs["pids_limit"] == 256
        # The pre-existing keys must still be there (no regression).
        assert run_kwargs["auto_remove"] is True
        assert run_kwargs["volumes"]

    def test_local_executor_gets_no_docker_kwargs(self):
        settings = load_settings()
        assert _executor_kwargs_for("local", settings.tiers["restricted"], settings) == {}

    def test_invalid_cpus_fails_loudly(self):
        settings = load_settings().with_overrides(container_limits={"restricted": {"cpus": "not-a-number"}})
        with pytest.raises(ValueError, match="cpus"):
            _container_limit_kwargs("restricted", settings)

    def test_invalid_pids_fails_loudly(self):
        settings = load_settings().with_overrides(container_limits={"restricted": {"pids_limit": "many"}})
        with pytest.raises(ValueError, match="pids_limit"):
            _container_limit_kwargs("restricted", settings)

    def test_string_values_from_env_like_config_are_accepted(self):
        settings = load_settings().with_overrides(container_limits={"elevated": {"cpus": "1.5", "pids_limit": "128"}})
        kwargs = _container_limit_kwargs("elevated", settings)
        assert kwargs == {"nano_cpus": 1_500_000_000, "pids_limit": 128}


# ---- no-cost-cap warning ---------------------------------------------------


@pytest.fixture
def uncapped(monkeypatch):
    monkeypatch.setattr(config_module, "_COST_CAP_WARNING_EMITTED", False)
    return load_settings()


class TestCostCapWarning:
    def test_warns_once_when_no_cap_configured(self, uncapped, caplog):
        with caplog.at_level(logging.WARNING, logger="smolcode.config"):
            assert warn_if_no_cost_caps(uncapped) is True
            assert warn_if_no_cost_caps(uncapped) is False
        records = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == "smolcode.config"]
        assert len(records) == 1
        assert "SMOLCODE_COST_CAPS" in records[0].getMessage()
        assert "cap" in records[0].getMessage().lower()

    def test_does_not_warn_when_caps_are_configured(self, uncapped, caplog):
        uncapped.cost_caps = {"MiniMax": 1.0}
        with caplog.at_level(logging.WARNING, logger="smolcode.config"):
            assert warn_if_no_cost_caps(uncapped) is False
        assert not [r for r in caplog.records if "SMOLCODE_COST_CAPS" in r.getMessage()]

    def test_never_raises_on_partial_settings(self, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(config_module, "_COST_CAP_WARNING_EMITTED", False)
        assert warn_if_no_cost_caps(SimpleNamespace(cost_caps=None)) is True

    def test_uses_the_injected_logger(self, uncapped):
        records = []

        class _Capture:
            def warning(self, message):
                records.append(message)

        assert warn_if_no_cost_caps(uncapped, logger=_Capture()) is True
        assert len(records) == 1

    def test_cli_session_warns_before_a_missing_key_failure(self, monkeypatch, caplog):
        monkeypatch.setattr(config_module, "_COST_CAP_WARNING_EMITTED", False)
        from smolcode.cli import main

        with caplog.at_level(logging.WARNING, logger="smolcode.config"):
            exit_code = main(["--tier", "restricted", "explain the repo"])
        # Local executor + no provider key: startup fails AFTER the warning.
        assert exit_code == 3
        assert any("SMOLCODE_COST_CAPS" in r.getMessage() for r in caplog.records)
