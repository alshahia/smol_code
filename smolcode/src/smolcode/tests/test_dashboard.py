"""Phase 3 (decision 0025 sec 6.5): dashboard aggregator."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from smolcode.config import Settings
from smolcode.web.dashboard import _sparkline_24h, compute_dashboard


def _run(*, started_at, status="done", provider="openai", model="gpt-4o", tokens_in=0, tokens_out=0, run_id=None):
    return SimpleNamespace(
        id=run_id or f"r-{started_at}",
        status=status,
        provider=provider,
        model=model,
        started_at=started_at,
        tokens=SimpleNamespace(input=tokens_in, output=tokens_out, total=tokens_in + tokens_out),
        error=None,
    )


class TestSparkline24h:
    def test_empty(self):
        assert _sparkline_24h([], now=1_000_000) == [0] * 24

    def test_single_run_in_current_hour(self):
        now = 1_000_000.0
        # Run started 100s ago -> bucket 23 (current hour)
        runs = [_run(started_at=now - 100, tokens_in=50, tokens_out=50)]
        spark = _sparkline_24h(runs, now=now)
        assert spark[23] == 100
        assert sum(spark) == 100

    def test_run_24h_ago_lands_in_bucket_0(self):
        now = 1_000_000.0
        # Run started 23h ago -> bucket 0 (oldest)
        runs = [_run(started_at=now - 23 * 3600, tokens_in=10, tokens_out=10)]
        spark = _sparkline_24h(runs, now=now)
        assert spark[0] == 20
        assert sum(spark) == 20

    def test_runs_older_than_24h_are_dropped(self):
        now = 1_000_000.0
        runs = [_run(started_at=now - 25 * 3600, tokens_in=999)]
        spark = _sparkline_24h(runs, now=now)
        assert sum(spark) == 0

    def test_caps_at_24_buckets(self):
        # Even with 1000 runs, sparkline has at most 24 buckets
        now = 1_000_000.0
        runs = [_run(started_at=now - i * 100, tokens_in=1) for i in range(1000)]
        spark = _sparkline_24h(runs, now=now)
        assert len(spark) == 24


class TestComputeDashboard:
    def _settings(self):
        return Settings(
            workspace=__import__("pathlib").Path("/tmp/ws"),
            executor="local",
            provider="openai",
            model="gpt-4o",
            litellm_proxy=None,
            log_level="INFO",
            tiers={},
        )

    def test_empty_run_list(self):
        mgr = MagicMock()
        mgr.list_all_runs.return_value = []
        audit = MagicMock()
        audit.count_since.return_value = 0
        settings = self._settings()
        result = compute_dashboard(mgr, audit, settings)
        assert result.runs_today == 0
        assert result.tokens_today.input == 0
        assert result.tokens_today.output == 0
        assert result.tokens_today.total == 0
        assert result.errors_today == 0
        assert result.cost_estimate_usd_today == 0.0
        assert len(result.sparkline) == 24

    def test_single_run_today(self):
        now = time.time()
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [
            _run(started_at=now - 100, provider="openai", model="gpt-4o", tokens_in=1000, tokens_out=500)
        ]
        audit = MagicMock()
        audit.count_since.return_value = 1
        result = compute_dashboard(mgr, audit, self._settings())
        assert result.runs_today == 1
        assert result.tokens_today.input == 1000
        assert result.tokens_today.output == 500
        assert result.tokens_today.total == 1500
        assert result.errors_today == 1
        assert result.cost_estimate_usd_today == pytest.approx(0.0125)

    def test_multiple_runs_aggregate_by_provider(self):
        now = time.time()
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [
            _run(started_at=now - 100, provider="openai", model="gpt-4o", tokens_in=1000, tokens_out=500),
            _run(started_at=now - 200, provider="openai", model="gpt-4o", tokens_in=2000, tokens_out=1000),
            _run(
                started_at=now - 300,
                provider="anthropic",
                model="claude-3-5-sonnet-latest",
                tokens_in=4000,
                tokens_out=2000,
            ),
        ]
        audit = MagicMock()
        audit.count_since.return_value = 0
        result = compute_dashboard(mgr, audit, self._settings())
        assert result.runs_today == 3
        assert "openai" in result.by_provider
        assert "anthropic" in result.by_provider
        assert result.by_provider["openai"].total == 4500
        assert result.by_provider["anthropic"].total == 6000
        # cost = (3/1000)*0.005 + (1.5/1000)*0.015 + (4/1000)*0.003 + (2/1000)*0.015
        #      = 0.015 + 0.0225 + 0.012 + 0.03 = 0.0795
        assert result.cost_estimate_usd_today == pytest.approx(0.0795)

    def test_yesterday_runs_excluded(self):
        now = time.time()
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [
            _run(started_at=now - 100, provider="openai", tokens_in=100),
            _run(started_at=now - 90000, provider="openai", tokens_in=999),  # > 24h ago
        ]
        audit = MagicMock()
        audit.count_since.return_value = 0
        result = compute_dashboard(mgr, audit, self._settings())
        assert result.runs_today == 1
        assert result.tokens_today.total == 100

    def test_unknown_provider_cost_is_zero(self):
        now = time.time()
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [_run(started_at=now - 100, provider="unknown", model="x", tokens_in=100)]
        audit = MagicMock()
        audit.count_since.return_value = 0
        result = compute_dashboard(mgr, audit, self._settings())
        assert result.cost_estimate_usd_today == 0.0
        assert result.runs_today == 1  # runs counted, just no cost

    def test_cache_hit_tokens_included_in_cost(self):
        """cache_hit is read from run.tokens.cache_hit if present."""
        now = time.time()
        run = _run(started_at=now - 100, provider="openai", model="gpt-4o", tokens_in=1000, tokens_out=500)
        run.tokens.cache_hit = 0  # default cache hit; doesn't affect default rate (0)
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [run]
        audit = MagicMock()
        audit.count_since.return_value = 0
        result = compute_dashboard(mgr, audit, self._settings())
        assert result.cost_estimate_usd_today == pytest.approx(0.0125)

    def test_audit_error_count_is_queried(self):
        now = time.time()
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [_run(started_at=now - 100)]
        audit = MagicMock()
        audit.count_since.return_value = 7
        result = compute_dashboard(mgr, audit, self._settings())
        assert result.errors_today == 7
        # audit.count_since was called with (day_start, level='ERROR')
        args, kwargs = audit.count_since.call_args
        assert kwargs.get("level") == "ERROR"

    def test_run_without_started_at_is_ignored(self):
        now = time.time()
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [
            _run(started_at=None),  # no started_at -> ignore
            _run(started_at=now - 100),
        ]
        audit = MagicMock()
        audit.count_since.return_value = 0
        result = compute_dashboard(mgr, audit, self._settings())
        assert result.runs_today == 1
