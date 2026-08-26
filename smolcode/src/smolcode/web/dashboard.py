"""Phase 3 (decision 0025 sec 6.5): dashboard aggregator.

Computes the per-day dashboard payload served by GET /api/dashboard.
Reads from RunManager (run history) + audit reader (error count) +
Settings (cost rates). Bounded to last-24h for the sparkline + last-24h
for the top counters (decision 0025 sec 6.5 risk register: dashboard
reads may be slow on long-running installations; aggregate in-memory
and cap the sparkline at 24 buckets).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from smolcode.model_catalog import cost_for


if TYPE_CHECKING:
    from smolcode.config import Settings


_DAY_S = 86400.0
_SPARKLINE_BUCKETS = 24


@dataclass
class TokenSummary:
    input: int = 0
    output: int = 0
    total: int = 0
    # Decision 0032: per-bucket USD cost accumulator. The dashboard
    # computes this once (per provider / per global) via
    # ``model_catalog.cost_for`` so the SPA can render the dollar
    # figure alongside the token counts without re-deriving on the
    # client. Zero when no rate is known for the provider/model pair.
    cost_usd: float = 0.0

    @classmethod
    def from_tokens(cls, t) -> "TokenSummary":
        """Build from a Run.tokens dataclass; tolerates missing cache_hit."""
        return cls(
            input=getattr(t, "input", 0) or 0, output=getattr(t, "output", 0) or 0, total=getattr(t, "total", 0) or 0
        )


@dataclass
class DashboardResponse:
    runs_today: int = 0
    tokens_today: TokenSummary = field(default_factory=TokenSummary)
    errors_today: int = 0
    by_provider: dict[str, TokenSummary] = field(default_factory=dict)
    sparkline: list[int] = field(default_factory=list)  # 24 buckets, oldest first
    cost_estimate_usd_today: float = 0.0
    generated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.sparkline:
            self.sparkline = [0] * _SPARKLINE_BUCKETS


def _sparkline_24h(runs, now: float) -> list[int]:
    """24 buckets, oldest first. Bucket 0 = 23h ago; bucket 23 = current hour."""
    buckets = [0] * _SPARKLINE_BUCKETS
    for r in runs:
        if not getattr(r, "started_at", None):
            continue
        age_h = (now - r.started_at) / 3600.0
        if age_h < 0 or age_h >= 24:
            continue
        bucket = 23 - int(age_h)  # 0 = oldest, 23 = current hour
        if 0 <= bucket < _SPARKLINE_BUCKETS:
            tokens_total = getattr(getattr(r, "tokens", None), "total", 0) or 0
            buckets[bucket] += tokens_total
    return buckets


def compute_dashboard(mgr, audit, settings: "Settings") -> DashboardResponse:
    """Aggregate runs + audit errors + cost estimate for the Dashboard tab."""
    now = time.time()
    day_start = now - _DAY_S

    runs = list(mgr.list_all_runs())
    today = [r for r in runs if getattr(r, "started_at", None) and r.started_at >= day_start]

    tokens_today = TokenSummary(
        input=sum(getattr(getattr(r, "tokens", None), "input", 0) or 0 for r in today),
        output=sum(getattr(getattr(r, "tokens", None), "output", 0) or 0 for r in today),
        total=sum(getattr(getattr(r, "tokens", None), "total", 0) or 0 for r in today),
        # ``cost_usd`` is filled in AFTER the per-provider loop below so we
        # can fold the (already-rounded) per-provider bucket totals into a
        # single global figure. Filling it in here would double-count or
        # diverge from ``cost_estimate_usd_today`` due to rounding order.
    )

    # Per-provider breakdown (only providers that appear in today).
    # Decision 0032: also accumulate ``cost_usd`` per provider via
    # ``cost_for`` so the SPA can render a per-row dollar figure
    # alongside the token counts. Unknown provider/model returns
    # 0.0 from ``cost_for`` so the accumulator stays at 0 -- matches
    # the existing "unknown provider cost is zero" semantics.
    by_provider: dict[str, TokenSummary] = {}
    for r in today:
        prov = getattr(r, "provider", None)
        if not prov:
            continue
        cur = by_provider.get(prov) or TokenSummary()
        t = getattr(r, "tokens", None)
        cur.input += getattr(t, "input", 0) or 0
        cur.output += getattr(t, "output", 0) or 0
        cur.total += getattr(t, "total", 0) or 0
        if t is not None:
            cache_hit = getattr(t, "cache_hit", 0) or 0
            cur.cost_usd += cost_for(
                getattr(r, "provider", None),
                getattr(r, "model", None),
                getattr(t, "input", 0) or 0,
                getattr(t, "output", 0) or 0,
                cache_hit=cache_hit,
                settings=settings,
            )
        by_provider[prov] = cur

    sparkline = _sparkline_24h(today, now)

    cost = 0.0
    for r in today:
        t = getattr(r, "tokens", None)
        if t is None:
            continue
        cache_hit = getattr(t, "cache_hit", 0) or 0
        cost += cost_for(
            getattr(r, "provider", None),
            getattr(r, "model", None),
            getattr(t, "input", 0) or 0,
            getattr(t, "output", 0) or 0,
            cache_hit=cache_hit,
            settings=settings,
        )
    cost = round(cost, 6)
    # Per-provider costs were accumulated unrounded; round once at the
    # end so the dashboard payload is stable across re-renders. Also
    # fold the per-provider totals into ``tokens_today.cost_usd`` so the
    # top-level summary carries the global USD figure alongside the
    # token counts (single source of truth -- mirrors by_provider math).
    for prov_name, cur in by_provider.items():
        rounded = round(cur.cost_usd, 6)
        by_provider[prov_name] = TokenSummary(
            input=cur.input,
            output=cur.output,
            total=cur.total,
            cost_usd=rounded,
        )
        tokens_today.cost_usd += rounded
    tokens_today.cost_usd = round(tokens_today.cost_usd, 6)

    errors_today = 0
    try:
        errors_today = int(audit.count_since(day_start, level="ERROR"))
    except (TypeError, AttributeError):
        try:
            errors_today = int(audit.count_since(day_start))
        except Exception:
            errors_today = 0

    return DashboardResponse(
        runs_today=len(today),
        tokens_today=tokens_today,
        errors_today=errors_today,
        by_provider=by_provider,
        sparkline=sparkline,
        cost_estimate_usd_today=cost,
        generated_at=now,
    )
