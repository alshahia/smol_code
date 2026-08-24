"""The restricted tier. See docs/architecture.md 5.4 + docs/security.md 3.3."""

from __future__ import annotations

from .base import make_agent


def build_restricted_agent(settings, model, *, max_steps=None):
    """Build the restricted-tier CodeAgent."""
    return make_agent(
        tier=settings.tiers["restricted"],
        settings=settings,
        model=model,
        max_steps=max_steps,
    )
