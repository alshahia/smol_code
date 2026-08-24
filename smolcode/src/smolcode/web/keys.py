"""keys.py -- whitelist API key extraction for /api/runs (M11, decision 0014).

The SPA's provider/model/key UI sends user-supplied API keys inside the
``keys`` field of ``POST /api/runs``. This module is the single
authority on which entries from that body are forwarded to the model
factory and which are discarded silently.

Rules:

  * Only env-var names whose shape matches a known API-key convention
    are kept. The whitelist is the SAME predicate used by
    ``model_catalog.fetch_models`` -- see ``model_catalog.is_api_key_env``.
    Recognised:

        ``*_API_KEY``     -- e.g. ``OPENAI_API_KEY``, ``MINIMAX_API_KEY``,
                             ``ANTHROPIC_API_KEY``, ``CUSTOM_API_KEY``
        ``*_APIKEY``      -- the smolcode-specific suffix used by
                             ``OPENCODE_GO_APIKEY`` (decision 0001)
        ``HF_TOKEN``      -- HuggingFace hub token

    Any other key name in the body is silently DROPPED (no error,
    no log line) so that adding a future provider requires no body
    shape change for the SPA.

  * ``None`` and empty-string values are dropped (key still considered
    "missing" on the server side).

  * Total entries are capped at 16; per-value length capped at 4 KB.
    Both limits prevent trivial request-body abuse.

  * Values are reduced to their first line (split on ``\\n``, take
    the head, strip trailing ``\\r``) so accidental logging cannot
    leak trailing newlines.

The function returns a new dict; the input is left intact. Callers
must NEVER persist this dict to disk (see decision 0014 -- keys are
memory-only for the duration of one run).
"""

from __future__ import annotations

from ..model_catalog import is_api_key_env


# Caps prevent trivial request-body abuse. Tightening is fine; loosening
# needs an explicit decision.
_MAX_KEYS_PER_REQUEST = 16
_MAX_KEY_VALUE_LEN = 4096


def extract_keys(body: dict) -> dict[str, str]:
    """Filter ``body`` down to a whitelisted ``{env_var: key_value}`` dict.

    See module docstring for the exact rules. The function does not
    raise on malformed or unknown entries; it silently drops them so
    the SPA can send its full stored map without coordinating with the
    server about which provider it currently has selected.
    """
    if not isinstance(body, dict):
        return {}
    out: dict[str, str] = {}
    for raw_k, raw_v in body.items():
        if len(out) >= _MAX_KEYS_PER_REQUEST:
            break
        if not isinstance(raw_k, str) or not raw_k:
            continue
        if not is_api_key_env(raw_k):
            continue
        if raw_v is None:
            continue
        if not isinstance(raw_v, str):
            continue
        # First non-empty line only; trailing CR + trailing newline
        # stripped so log injection via "key\\nsecret" is not possible.
        # Trailing whitespace trimmed so accidental spaces typed into
        # a form field do not silently cause an auth failure.
        head = raw_v.split("\n", 1)[0].rstrip("\r").strip()
        if not head:
            continue
        out[raw_k] = head[:_MAX_KEY_VALUE_LEN]
    return out


__all__ = ["extract_keys"]
