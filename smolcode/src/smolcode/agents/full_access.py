"""The full_access tier (M4). See docs/architecture.md 5.4 + docs/security.md 3.3.

Full access is the most powerful tier: wider imports, wider commands,
open network. The CLI enforces a per-run confirmation prompt BEFORE
the agent is built (cli.py:confirm_full_access). The audit log
captures every full_access run.

This module is intentionally tiny: the confirmation + audit
enforcement happens in cli.py, not here, because the prompt must fire
before any model call. Keeping it out of the factory keeps the
factory easy to test.
"""

from __future__ import annotations

from .base import make_agent


def build_full_access_agent(settings, model, *, max_steps=None):
    """Build the full_access-tier CodeAgent."""
    return make_agent(
        tier=settings.tiers["full_access"],
        settings=settings,
        model=model,
        max_steps=max_steps,
    )
