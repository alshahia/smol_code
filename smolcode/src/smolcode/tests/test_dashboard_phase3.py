"""Phase 3 (decision 0025 sec 6.5 follow-on) RED tests for F1.

Bug surface:
    Run.started_at is stamped with time.monotonic() (boot-relative seconds)
    while web/dashboard.py:compute_dashboard filters with time.time() (Unix
    epoch) and computes
        age_h = (now - r.started_at) / 3600.
    After more than ~1 s of server uptime the gap exceeds the 24 h window
    and every counter silently reports zero. Phase 0 dashboard probes
    against the live pwsh-2 server confirmed this exactly:

        wall now        = ~1 787 814 830 s
        run.started_at  = ~1 216 264 s
        -> gap = 56.6 years
        -> runs_today = 0, sparkline = all zeros.

These tests FAIL today (RED) and pass after Phase 1 changes Run's default
stamp factory + every other timestamp default to time.time() (specifically
listed in PHASED-PLAN.md Phase 1: Run.started_at, Run.ended_at,
Run.snapshot_at, cancel_queue's run.ended_at = time.monotonic(), and
append_subagent's started_at default).

The fix surface explicitly does NOT touch Run.remaining_s() or
summary_dict()'s countdown math - those legitimately stay monotonic so the
countdown does not jump if the wall clock changes mid-run.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from smolcode.config import Settings


def _settings() -> Settings:
    return Settings(
        workspace=__import__("pathlib").Path("/tmp/ws"),
        executor="local",
        provider="opencode-go",
        model="deepseek-v4-flash",
        litellm_proxy=None,
        log_level="INFO",
        tiers={},
    )


def _run_simple(
    *, started_at, status="done", provider="opencode-go", model="deepseek-v4-flash", tokens_in=0, tokens_out=0
):
    """A SimpleNamespace run, mirroring test_dashboard.py:_run()."""
    return SimpleNamespace(
        id="r-" + str(started_at),
        status=status,
        provider=provider,
        model=model,
        started_at=started_at,
        tokens=SimpleNamespace(input=tokens_in, output=tokens_out, total=tokens_in + tokens_out, cache_hit=0),
        error=None,
    )


class TestClockDomain:
    """F1 - RED: any Run stamped via the dataclass default must live in
    the same clock domain as compute_dashboard's now."""

    def test_run_dataclass_stamps_started_at_with_wall_clock(self):
        """Atomic RED: Run.started_at default factory must use time.time().

        Today the default is time.monotonic() and the diff to wall clock
        equals the server's uptime (seconds -> millions of seconds). After
        Phase 1 the default is wall clock and the diff is bounded by
        sub-second noise.
        """
        from smolcode.web.runs import Run

        now_wall = time.time()
        r = Run(id="phase3-f1-stamp", task="x", tier="restricted")
        delta = abs(r.started_at - now_wall)
        assert delta < 60.0, (
            "Run.started_at="
            + repr(r.started_at)
            + " is more than 60s away from wall clock now="
            + repr(now_wall)
            + " (|delta|="
            + repr(delta)
            + "s). "
            + "Default factory is using a non-wall clock (likely time.monotonic)."
        )

    def test_compute_dashboard_counts_a_real_run_stamped_by_default(self):
        """Integration RED: Run(...) invoked without explicit stamp must
        still be visible to compute_dashboard. Today the Run comes in
        with a boot-relative stamp and the dashboard filter rejects it.
        After Phase 1 the default is wall clock so the filter accepts it.
        """
        from smolcode.web.dashboard import compute_dashboard
        from smolcode.web.runs import Run

        r = Run(id="phase3-f1-real-run", task="x", tier="restricted")
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [r]
        audit = MagicMock()
        audit.count_since.return_value = 0
        result = compute_dashboard(mgr, audit, _settings())
        assert result.runs_today == 1, (
            "compute_dashboard returned runs_today="
            + repr(result.runs_today)
            + " for a freshly-created Run; the dashboard filter and the Run"
            + " stamp are on different clocks."
        )

    def test_compute_dashboard_handles_run_stamped_one_hour_ago(self):
        """Characterization (Phase 1 happy path). A Run explicitly
        stamped with time.time() - 3600 must be counted as today. Today
        the test passes because compute_dashboard is wall-vs-wall; Phase 1
        keeps that property and adds the same property to Run.
        """
        from smolcode.web.dashboard import compute_dashboard

        now = time.time()
        run = _run_simple(started_at=now - 100, tokens_in=100, tokens_out=50)
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [run]
        audit = MagicMock()
        audit.count_since.return_value = 0
        result = compute_dashboard(mgr, audit, _settings())
        assert result.runs_today == 1
        assert result.tokens_today.input == 100
        assert result.tokens_today.output == 50
        assert result.tokens_today.total == 150
        assert result.sparkline[23] >= 150

    def test_compute_dashboard_drops_run_older_than_24h(self):
        """Characterization: a Run stamped >24h ago is not counted in
        runs_today and does not appear in the sparkline.
        """
        from smolcode.web.dashboard import compute_dashboard

        now = time.time()
        run = _run_simple(started_at=now - 86400 - 10)
        mgr = MagicMock()
        mgr.list_all_runs.return_value = [run]
        audit = MagicMock()
        audit.count_since.return_value = 0
        result = compute_dashboard(mgr, audit, _settings())
        assert result.runs_today == 0
        assert sum(result.sparkline) == 0
