"""M11 (decision 0014) -- unit tests for RunManager.start_run with
per-run overrides.

These tests exercise ``RunManager.start_run`` directly (no FastAPI /
no agent loop) to verify that the provider / model / key overrides
land on the ``Run`` dataclass correctly, that unknown providers are
rejected early, and that ``api_key_value`` is treated as a private
field -- it is on the Run object but is NOT included in the
``run.started`` event payload.
"""

from __future__ import annotations

import json

import pytest

from smolcode.web.runs import (
    STATUS_PENDING,
    Run,
    RunManager,
)


# ---- minimal Settings for testing ----------------------------------------


class _FakeSettings:
    """Bare-minimum object that duck-types the Settings attribute
    surface consumed by ``RunManager.start_run``."""

    workspace = "/tmp/test-ws"
    executor = "local"
    provider = "opencode-go"
    model = "deepseek-v4-flash"
    litellm_proxy = None


@pytest.fixture
def mgr():
    return RunManager()


# ---- TestStartRunOverrides ----------------------------------------------


class TestStartRunOverrides:
    def test_no_overrides_uses_settings_defaults(self, mgr):
        run_id = mgr.start_run(task="hi", tier="restricted", settings=_FakeSettings())
        run = mgr.get(run_id)
        assert run.provider == "opencode-go"
        assert run.model == "deepseek-v4-flash"
        assert run.provider_override is None
        assert run.model_override is None
        assert run.api_key_value is None

    def test_provider_override_recorded(self, mgr):
        run_id = mgr.start_run(
            task="hi",
            tier="restricted",
            settings=_FakeSettings(),
            provider_override="MiniMax",
        )
        run = mgr.get(run_id)
        assert run.provider_override == "MiniMax"
        assert run.provider == "MiniMax"  # effective value

    def test_model_override_recorded(self, mgr):
        run_id = mgr.start_run(
            task="hi",
            tier="restricted",
            settings=_FakeSettings(),
            model_override="claude-3-5-sonnet-latest",
        )
        run = mgr.get(run_id)
        assert run.model_override == "claude-3-5-sonnet-latest"
        assert run.model == "claude-3-5-sonnet-latest"  # effective value

    def test_api_key_value_recorded_when_non_empty(self, mgr):
        run_id = mgr.start_run(
            task="hi",
            tier="restricted",
            settings=_FakeSettings(),
            api_key_value="sk-supplied-via-spa",
        )
        run = mgr.get(run_id)
        assert run.api_key_value == "sk-supplied-via-spa"

    def test_empty_api_key_value_normalised_to_none(self, mgr):
        # An empty string is a common "user has not entered one" state
        # from the SPA's localStorage. We must NOT store it -- build_model
        # should fall back to env / preset defaults.
        run_id = mgr.start_run(
            task="hi",
            tier="restricted",
            settings=_FakeSettings(),
            api_key_value="   ",  # whitespace-only
        )
        run = mgr.get(run_id)
        assert run.api_key_value is None

    def test_unknown_provider_override_rejected(self, mgr):
        with pytest.raises(ValueError) as ei:
            mgr.start_run(
                task="hi",
                tier="restricted",
                settings=_FakeSettings(),
                provider_override="not-a-provider",
            )
        assert "not-a-provider" in str(ei.value)

    def test_run_started_payload_carries_overrides_but_no_keys(self, mgr):
        """run.started event payload must include the EFFECTIVE
        provider + model (so the SPA can show them) but must NEVER
        include the api_key_value (decision 0014 security contract)."""
        run_id = mgr.start_run(
            task="hi",
            tier="restricted",
            settings=_FakeSettings(),
            provider_override="MiniMax",
            model_override="MiniMax-M3",
            api_key_value="sk-SECRETKEY1234",
        )
        run = mgr.get(run_id)
        # Drain the event queue and find the first published event.
        events = []
        while not run.events.empty():
            events.append(run.events.get_nowait())
        # Find the run.started frame.
        started_frame = next(e for e in events if "run.started" in e)
        # Extract the data line and parse its JSON.
        data_line = next(line for line in started_frame.splitlines() if line.startswith("data:"))
        payload = json.loads(data_line[len("data: ") :])

        assert payload["provider"] == "MiniMax"
        assert payload["model"] == "MiniMax-M3"
        # The api_key_value must NOT be present.
        assert "SECRETKEY1234" not in started_frame
        assert "api_key" not in started_frame


class TestRunDataclass:
    def test_run_dataclass_has_m11_fields(self):
        run = Run(id="x", task="t", tier="restricted")
        # Default values are None for the new fields.
        assert run.provider_override is None
        assert run.model_override is None
        assert run.api_key_value is None

    def test_run_default_status_is_pending(self):
        run = Run(id="x", task="t", tier="restricted")
        assert run.status == STATUS_PENDING
