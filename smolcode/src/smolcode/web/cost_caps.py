"""Decision 0032: per-provider usage caps ("stop at $1").

This module owns the in-process mutable cap registry. The settings
layer (``Settings.cost_caps``) seeds the *defaults* on startup; the
runtime state (``caps``) is what the run-start and per-step checks
actually consult. ``PUT /api/cost-caps`` mutates ``caps`` and leaves
``defaults`` intact so the SPA can show the original baseline alongside
the current override.

Thread safety: a single ``threading.Lock`` guards every mutation. Reads
take the lock briefly so concurrent ``GET /api/cost-caps`` + ``PUT``
cannot interleave to surface a half-updated dict. The cap is treated
as "reached" when ``current_spend_usd >= cap`` (decision 0032 sec 2:
"stop at 1 dollar"; we accept == as reached so the user cannot squeeze
one more cent through).
"""

from __future__ import annotations

import threading


class CostCapTracker:
    """Thread-safe per-provider USD cap registry (decision 0032).

    ``caps`` is the LIVE state (mutated by ``update``). ``defaults`` is
    the baseline captured at construction time and is never changed by
    ``update``; this lets the SPA render "current" vs "env default" in
    one GET round-trip without the BE re-reading ``Settings.cost_caps``.
    """

    def __init__(self, defaults=None):
        # Defaults are cleaned via the same drop-values-<=0 rule as the
        # runtime state so the user cannot seed a negative baseline by
        # typo. Values <= 0 are dropped entirely (no cap configured).
        self._defaults = self._clean(defaults or {})
        self._caps = dict(self._defaults)
        self._lock = threading.Lock()

    @staticmethod
    def _clean(values):
        """Drop values that are not coercible to a positive float.

        ``update`` silently ignores bad types vs raising so a stale
        PUT payload from a misbehaving client cannot wedge the cap
        registry. ``float(x)`` succeeds for ``int``, ``float``, and any
        string that parses as a number (e.g. ``"1.5"`` -> ``1.5``).
        Bools are rejected (they would coerce to 1.0/0.0).
        Anything <= 0 is dropped, matching ``__init__`` semantics.
        """
        out = {}
        if not isinstance(values, dict):
            return out
        for k, v in values.items():
            if isinstance(v, bool):
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f <= 0:
                continue
            out[str(k)] = f
        return out

    def get_state(self):
        """Return ``{caps, defaults}`` for the GET response.

        Both dicts are independent copies so a caller mutating the
        result cannot corrupt the registry. ``caps`` reflects the LIVE
        state after the last ``update`` (may equal ``defaults`` when the
        user has not overridden anything).
        """
        with self._lock:
            return {"caps": dict(self._caps), "defaults": dict(self._defaults)}

    def get_cap(self, provider):
        """Return the current cap for ``provider`` (0.0 when none set).

        Read under the lock for parity with ``update``; the lock is cheap
        and this path is hit on every run-start check.
        """
        if not isinstance(provider, str) or not provider:
            return 0.0
        with self._lock:
            return float(self._caps.get(provider, 0.0))

    def update(self, new_caps):
        """Replace the LIVE cap state with ``new_caps`` (after cleaning).

        Returns the resulting ``caps`` dict so the API layer can echo it
        back without a follow-up ``get_state`` call. ``defaults`` is NOT
        modified by this method -- it represents the boot-time baseline.
        """
        cleaned = self._clean(new_caps or {})
        with self._lock:
            self._caps = cleaned
            return dict(self._caps)

    def reset(self):
        """Restore ``caps`` to ``defaults`` (or {} when no defaults).

        Returns the resulting ``caps`` dict. Used by tests + the API layer
        when the SPA wants a single "clear all overrides" gesture.
        """
        with self._lock:
            self._caps = dict(self._defaults)
            return dict(self._caps)

    def check_reached(self, provider, current_spend_usd):
        """Return ``(reached, reason)`` for ``provider`` vs ``current_spend_usd``.

        ``reached`` is True when the cap is set and the current spend is
        at or above the cap. We use ``>=`` so "exactly at the cap" still
        trips the gate (decision 0032 sec 2: "stop at 1 dollar"). The
        reason string uses ``%``-format (NOT f-string) per the design spec,
        which gives us an explicit surface to grep for in tests.
        """
        if not isinstance(provider, str) or not provider:
            return (False, "")
        try:
            spend = float(current_spend_usd)
        except (TypeError, ValueError):
            spend = 0.0
        with self._lock:
            cap = self._caps.get(provider, 0.0)
        if cap <= 0:
            return (False, "")
        if spend < cap:
            return (False, "")
        reason = "cost cap reached for provider %s: $%.4f >= cap $%.4f" % (provider, spend, cap)
        return (True, reason)


__all__ = ["CostCapTracker"]
