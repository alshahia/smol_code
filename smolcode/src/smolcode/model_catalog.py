"""`model_catalog` — 5-provider catalog for smolcode (M6).

Lifted from smolagents-ui/smolagents_ui/services/model_catalog.py
(PB-5.7..5.13) with the following adjustments:

  * SYNC instead of async (smolcode is a CLI; there is no event loop
    to coordinate against). The public function signatures are
    otherwise unchanged.
  * Providers trimmed to the FIVE presets that are wired in
    smolcode/src/smolcode/models.py:PROVIDER_PRESETS — opencode-go,
    MiniMax, openai, anthropic, custom. (smolagents-ui ships 9; the
    smolcode CLI does not yet have hf / gemini / mistral / groq /
    openrouter presets. Adding a new preset here requires ALSO adding
    it to PROVIDER_PRESETS in models.py — keep both in sync.)
  * `set_verbose` field removed from the ProviderSpec dataclass
    (unused in smolcode).
  * No HTTP /models endpoint — the smolcode CLI does not ship a UI;
    the catalog is consumed by host-side helpers and tests only. If
    a UI ships in v1.1 (per docs/roadmap.md 5M6), this is the
    natural place to wire it.
  * `host_env_var` retained: opencode-go and MiniMax each allow the
    base URL to be overridden via OPENCODE_HOST / MINIMAX_HOST.
    Other providers use litellm defaults.

This module owns the list of providers smolcode knows about and the
per-provider model-fetching logic. Conventions:

  * Provider id `"MiniMax"` (capital X) — canonical, NOT `minimax`.
    Mirrors smolagents-ui D-2 and docs/decisions/0001-initial-setup.md.
  * `custom` is INCLUDED here (unlike smolagents-ui's D-10 which
    excludes it from the UI's PROVIDERS registry). smolcode's catalog
    exposes it because the CLI surfaces it as a first-class provider
    in models.py and the user picks it via `--provider custom`.

Behavior:
  * `fetch_models(provider, keys, refresh=False)` uses
    `httpx.Client(timeout=httpx.Timeout(5.0, connect=3.0))` and
    returns `{"models": [...], "fetched_at": <epoch>, "error": "..."}`.
    On failure, the previously-cached value is returned with
    `error="fetch_failed"`.
  * Cached per-process for 1 hour. `refresh=True` bypasses the TTL.
  * `get_providers(keys)` returns the per-provider `key_state` (set /
    missing) plus the cached `model_count` (None until the first
    fetch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .config import Settings

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx


# A fetcher is `(keys: dict[str, str], base_url: str) -> list[str]`.
Fetcher = Callable[[dict[str, str], str], list[str]]


@dataclass(frozen=True)
class ProviderSpec:
    """Static description of one provider."""

    id: str
    name: str
    env_vars: tuple[str, ...]
    default_model: str
    base_url: str
    list_path: str
    auth_style: str  # "bearer" | "query" | "none" | "header"
    fetcher: Fetcher | None  # None => generic openai-compatible fetcher
    host_env_var: str | None = None


# Default per-provider base URLs. OPENCODE_HOST and MINIMAX_HOST env
# vars override these at fetch time.
_DEFAULT_BASE_URLS: dict[str, str] = {
    "opencode-go": "https://opencode.ai/zen/go/v1",
    "MiniMax": "https://api.minimax.io/v1",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "custom": "",  # required (no default); resolved at fetch time
}


def _is_api_key_env(env_name: str) -> bool:
    """True if `env_name` conventionally holds an API key/token.

    Recognises both the standard suffix `_API_KEY` (e.g. `MINIMAX_API_KEY`,
    `OPENAI_API_KEY`) and the smolcode-specific `_APIKEY` (e.g.
    `OPENCODE_GO_APIKEY`, per docs/decisions/0001-initial-setup.md).
    Also matches `HF_TOKEN` for HuggingFace tokens.
    """
    return env_name.endswith("_API_KEY") or env_name.endswith("_APIKEY") or env_name == "HF_TOKEN"


def _auth_headers(auth_style: str, keys: dict[str, str], provider_id: str) -> dict[str, str]:
    if auth_style == "bearer":
        spec = get_provider(provider_id)
        env_vars = spec.env_vars if spec else (f"{provider_id.upper()}_API_KEY",)
        key = ""
        for env in env_vars:
            if _is_api_key_env(env) and keys.get(env):
                key = keys[env]
                break
        return {"Authorization": f"Bearer {key}"}
    if auth_style == "none":
        return {}
    raise ValueError(f"Unknown auth_style: {auth_style!r}")


def _openai_compatible_fetcher(
    provider_id: str, list_path: str, auth_style: str, keys: dict[str, str], base_url: str
) -> list[str]:
    """Generic OpenAI-compatible /models fetcher (used by opencode-go,
    MiniMax, openai, custom)."""
    headers = _auth_headers(auth_style, keys, provider_id)
    timeout = httpx.Timeout(5.0, connect=3.0)
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(f"{base_url}{list_path}", headers=headers)
        if resp.status_code in (401, 403):
            raise PermissionError(f"auth failed for {provider_id}: {resp.status_code}")
        resp.raise_for_status()
        body = resp.json()
    data = body.get("data", body) if isinstance(body, dict) else body
    if not isinstance(data, list):
        raise ValueError(f"{provider_id} /models returned unexpected shape: {type(data).__name__}")
    out: list[str] = []
    for item in data:
        if isinstance(item, dict) and "id" in item:
            out.append(str(item["id"]))
        elif isinstance(item, str):
            out.append(item)
    return out


def _anthropic_fetcher(keys: dict[str, str], base_url: str) -> list[str]:
    """Anthropic has no public /models list endpoint. Return a hardcoded
    list of common model ids. The user can still pass a custom model
    via --model on the CLI; this just provides defaults.
    """
    return [
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
    ]


def _make_fetcher(provider_id: str, list_path: str, auth_style: str) -> Fetcher:
    if provider_id == "anthropic":
        return _anthropic_fetcher

    def _fetcher(keys: dict[str, str], base_url: str) -> list[str]:
        return _openai_compatible_fetcher(provider_id, list_path, auth_style, keys, base_url)

    return _fetcher


def _build_providers() -> tuple[ProviderSpec, ...]:
    out: list[ProviderSpec] = []
    for provider_id, base_url in _DEFAULT_BASE_URLS.items():
        if provider_id == "anthropic":
            env_vars = ("ANTHROPIC_API_KEY",)
            list_path = ""
            auth_style = "bearer"
            default_model = "claude-3-5-sonnet-latest"
            host_env_var = None
        elif provider_id == "openai":
            env_vars = ("OPENAI_API_KEY",)
            list_path = "/v1/models"
            auth_style = "bearer"
            default_model = "gpt-4o-mini"
            host_env_var = None
        elif provider_id == "opencode-go":
            env_vars = ("OPENCODE_GO_APIKEY", "OPENCODE_HOST")
            list_path = "/v1/models"
            auth_style = "bearer"
            default_model = "deepseek-v4-flash"
            host_env_var = "OPENCODE_HOST"
        elif provider_id == "MiniMax":
            env_vars = ("MINIMAX_API_KEY", "MINIMAX_HOST")
            list_path = "/v1/models"
            auth_style = "bearer"
            default_model = "MiniMax-M3"
            host_env_var = "MINIMAX_HOST"
        elif provider_id == "custom":
            env_vars = ("CUSTOM_API_KEY", "CUSTOM_BASE_URL")
            list_path = "/v1/models"
            auth_style = "bearer"
            default_model = "custom-model"
            host_env_var = "CUSTOM_BASE_URL"
        else:
            continue

        fetcher = _make_fetcher(provider_id, list_path, auth_style)
        out.append(
            ProviderSpec(
                id=provider_id,
                name={
                    "opencode-go": "opencode-go",
                    "MiniMax": "MiniMax",
                    "openai": "OpenAI",
                    "anthropic": "Anthropic",
                    "custom": "Custom (OpenAI-compatible)",
                }[provider_id],
                env_vars=env_vars,
                default_model=default_model,
                base_url=base_url,
                list_path=list_path,
                auth_style=auth_style,
                fetcher=fetcher,
                host_env_var=host_env_var,
            )
        )
    return tuple(out)


PROVIDERS: tuple[ProviderSpec, ...] = _build_providers()


def get_provider(provider_id: str) -> ProviderSpec | None:
    for p in PROVIDERS:
        if p.id == provider_id:
            return p
    return None


# --- Cost rates (Phase 3, decision 0025 sec 6.5 / Q5) ----------------------------

# Per-1k-token USD rates. Tuple = (input_per_1k, output_per_1k, cache_hit_per_1k).
# Hardcoded defaults; users override per provider/model via the
# SMOLCODE_COST_RATES JSON env var (Settings.cost_rates).
DEFAULT_COST_RATES: dict[str, dict[str, tuple[float, float, float]]] = {
    "openai": {
        "gpt-4o": (0.005, 0.015, 0.0),
        "gpt-4o-mini": (0.00015, 0.0006, 0.0),
        "o1-preview": (0.015, 0.06, 0.0),
        "o1-mini": (0.003, 0.012, 0.0),
    },
    "anthropic": {
        "claude-3-5-sonnet-latest": (0.003, 0.015, 0.0),
        "claude-3-5-haiku-latest": (0.0008, 0.004, 0.0),
        "claude-3-opus-latest": (0.015, 0.075, 0.0),
    },
    "MiniMax": {
        "MiniMax-M3": (0.001, 0.002, 0.0),
    },
    "opencode-go": {
        "deepseek-v4-flash": (0.0002, 0.0006, 0.0),
    },
}

# --- Context windows (Phase 3 F2, decision 0036) -------------------------------

# Hardcoded per-provider/model context-window sizes in tokens. The SPA's
# Inspector.tsx renders a fill bar against context_window so the user
# can see how much room the agent has before truncation. Unknown models
# return None (no bar); users override per provider/model via a future
# Settings.context_windows JSON env (mirrors cost_rates pattern).
DEFAULT_CONTEXT_WINDOWS: dict[str, dict[str, int]] = {
    "opencode-go": {
        "deepseek-v4-flash": 128000,
    },
    "MiniMax": {
        "MiniMax-M3": 2_000_000,
    },
    "openai": {
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "o1-preview": 128000,
    },
    "anthropic": {
        "claude-3-5-sonnet-latest": 200000,
        "claude-3-5-haiku-latest": 200000,
        "claude-3-opus-latest": 200000,
    },
}


def resolve_context_window(
    provider: str | None,
    model: str | None,
    settings: "Settings | None" = None,
    # Settings is a forward reference (only used for type hints).,
) -> int | None:
    """Return the context-window size in tokens for provider/model, or None.

    Looks up the provider/model in DEFAULT_CONTEXT_WINDOWS, with
    an optional override via settings.context_windows (same JSON env
    pattern as cost_for's settings.cost_rates -- mirroring
    _resolve_rates). Returns None (NOT a KeyError) when the
    provider/model is unknown, empty, or None; the SPA renders no
    fill bar in that case rather than crashing the Inspector.
    """
    if not provider or not model:
        return None
    override = getattr(settings, "context_windows", None) or {}
    prov_override = override.get(provider) or {}
    if model in prov_override:
        try:
            return int(prov_override[model])
        except (TypeError, ValueError):
            pass
    prov_default = DEFAULT_CONTEXT_WINDOWS.get(provider) or {}
    if model in prov_default:
        return prov_default[model]
    return None


def _resolve_rates(
    provider: str | None,
    model: str | None,
    settings: "Settings | None" = None,
    # `Settings` is a forward reference (only used for type hints).,
) -> tuple[float, float, float] | None:
    """Return (in, out, cache) rates for provider/model, or None.

    Override > default > None. The override is read from
    ``settings.cost_rates`` (Phase 3 sec 6.5 / Q5).
    """
    if not provider or not model:
        return None
    override = getattr(settings, "cost_rates", None) or {}
    prov_override = override.get(provider) or {}
    if model in prov_override:
        rates_tuple = prov_override[model]
        # Stored as list[str] from JSON env; normalize to tuple[float].
        if isinstance(rates_tuple, (list, tuple)) and len(rates_tuple) == 3:
            return (float(rates_tuple[0]), float(rates_tuple[1]), float(rates_tuple[2]))
    prov_default = DEFAULT_COST_RATES.get(provider) or {}
    if model in prov_default:
        return prov_default[model]
    return None


def cost_for(
    provider: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_hit: int = 0,
    settings: "Settings | None" = None,
    # `Settings` is a forward reference (only used for type hints).,
) -> float:
    """Compute USD cost for a token-bucket.

    Returns 0.0 when provider/model is unknown or tokens are zero.
    Cache-hit tokens are charged at the cache rate when set > 0.
    """
    rates = _resolve_rates(provider, model, settings)
    if rates is None:
        return 0.0
    in_rate, out_rate, cache_rate = rates
    cost = (input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate
    if cache_hit and cache_rate:
        cost += (cache_hit / 1000.0) * cache_rate
    return round(cost, 6)


def rate_source_for(
    provider: str | None,
    model: str | None,
    settings: "Settings | None" = None,
    # `Settings` is a forward reference (only used for type hints).,
) -> str:
    """Return 'override' | 'default' | 'unknown'."""
    if not provider or not model:
        return "unknown"
    override = getattr(settings, "cost_rates", None) or {}
    if provider in override and model in (override.get(provider) or {}):
        return "override"
    if provider in DEFAULT_COST_RATES and model in DEFAULT_COST_RATES[provider]:
        return "default"
    return "unknown"


# --- Per-process cache ------------------------------------------------------


@dataclass
class _CacheEntry:
    models: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    error: str | None = None


_CACHE: dict[str, _CacheEntry] = {}
_CACHE_TTL_S: float = 3600.0  # 1 hour


def _resolve_base_url(spec: ProviderSpec) -> str:
    """Return the effective base URL for `spec`, honoring host_env_var."""
    if spec.host_env_var:
        override = os.environ.get(spec.host_env_var, "").strip()
        if override:
            return override.rstrip("/")
    return spec.base_url


def _key_state(spec: ProviderSpec, keys: dict[str, str]) -> str:
    """'set' if every required env-var for spec is present, else 'missing'.

    Uses `_is_api_key_env` so that non-standard suffixes like
    `OPENCODE_GO_APIKEY` are also recognised (per docs/decisions/0001).
    """
    for env in spec.env_vars:
        if _is_api_key_env(env):
            if not keys.get(env):
                return "missing"
    return "set"


def fetch_models(
    provider_id: str,
    keys: dict[str, str],
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """Fetch the model list for `provider_id`.

    Returns `{"models": [...], "cached": bool, "fetched_at": float,
    "error": str|None}`. On fetch failure the previously-cached value
    is returned (if any) with `error="fetch_failed"`. If no key is set,
    returns `{"models": [], ..., "error": "no_key"}` without making an
    HTTP call.
    """
    spec = get_provider(provider_id)
    if spec is None:
        return {
            "models": [],
            "cached": False,
            "fetched_at": 0.0,
            "error": f"unknown provider: {provider_id!r}",
        }

    state = _key_state(spec, keys)
    if state == "missing":
        return {"models": [], "cached": False, "fetched_at": 0.0, "error": "no_key"}

    now = time.time()
    cached = _CACHE.get(provider_id)
    if cached is not None and not refresh and (now - cached.fetched_at) < _CACHE_TTL_S:
        return {
            "models": list(cached.models),
            "cached": True,
            "fetched_at": cached.fetched_at,
            "error": cached.error,
        }

    if spec.fetcher is None:
        return {
            "models": [],
            "cached": False,
            "fetched_at": now,
            "error": "no_fetcher_configured",
        }

    base_url = _resolve_base_url(spec)
    if not base_url:
        # Custom provider with no CUSTOM_BASE_URL set — cannot fetch.
        return {
            "models": [],
            "cached": False,
            "fetched_at": now,
            "error": "no_base_url",
        }

    try:
        models = spec.fetcher(keys, base_url)
    except PermissionError as exc:
        entry = _CacheEntry(models=cached.models if cached else [], fetched_at=now, error=str(exc))
        _CACHE[provider_id] = entry
        return {
            "models": list(entry.models),
            "cached": bool(cached),
            "fetched_at": now,
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        err_msg = f"fetch_failed: {exc}"
        if cached is not None:
            # Keep the previously-good models but surface the error and
            # remember WHEN it happened (M12.4). We do NOT overwrite
            # ``fetched_at`` here — the cached models' age is still
            # meaningful, and we'd rather not pretend the failed attempt
            # succeeded. The error is preserved as a separate field.
            failed_entry = _CacheEntry(
                models=list(cached.models),
                fetched_at=cached.fetched_at,
                error=err_msg,
            )
            _CACHE[provider_id] = failed_entry
            return {
                "models": list(failed_entry.models),
                "cached": True,
                "fetched_at": failed_entry.fetched_at,
                "error": err_msg,
            }
        # No prior cache: write a failure-only entry so /api/providers
        # can still report cached_at (= time of failure) + cached_error
        # to the SPA. Without this, the SPA would forever see null/null
        # and have no way to surface "your last fetch failed".
        failed_entry = _CacheEntry(models=[], fetched_at=now, error=err_msg)
        _CACHE[provider_id] = failed_entry
        return {
            "models": [],
            "cached": False,
            "fetched_at": now,
            "error": err_msg,
        }

    entry = _CacheEntry(models=models, fetched_at=now, error=None)
    _CACHE[provider_id] = entry
    return {
        "models": list(models),
        "cached": False,
        "fetched_at": now,
        "error": None,
    }


def get_providers(keys: dict[str, str]) -> list[dict[str, Any]]:
    """Return the per-provider list (mirrors smolagents-ui PB-5.12).

    M12 (decision 0015): each row now also carries ``cached_at``
    (epoch seconds of the most recent model-list fetch, or ``None``
    if no fetch has occurred yet in this process). Backwards-
    compatible additive field; consumers that do not know about it
    ignore it.

    M12.4: also carries ``cached_error``: when the most recent fetch
    attempt failed, this is a short single-line summary (e.g.
    ``"fetch_failed: 401 Unauthorized"``); ``None`` otherwise. When
    both fields are set, the SPA can render "last fetch FAILED 5m
    ago" alongside the existing age badge. Both fields additive.
    """
    out: list[dict[str, Any]] = []
    for spec in PROVIDERS:
        cached = _CACHE.get(spec.id)
        out.append(
            {
                "id": spec.id,
                "name": spec.name,
                "env_vars": list(spec.env_vars),
                "default_model": spec.default_model,
                "key_state": _key_state(spec, keys),
                "model_count": len(cached.models) if cached else None,
                "host_env_var": spec.host_env_var,
                # M12: epoch seconds of the most recent fetch_models
                # call for this provider; None if never fetched. The
                # SPA's <ModelAgeBadge> uses this to render
                # "just now" / "5m ago" / "stale (>1h)" inline.
                "cached_at": cached.fetched_at if cached else None,
                # M12.4: error string from the most recent failed
                # fetch (or None). When set, cached_at is the time of
                # the failed attempt; the SPA renders a warning badge.
                "cached_error": cached.error if cached else None,
            }
        )
    return out


def clear_cache(provider_id: str | None = None) -> None:
    """Reset the in-memory cache (used by tests)."""
    if provider_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(provider_id, None)


__all__ = [
    "PROVIDERS",
    "ProviderSpec",
    "Fetcher",
    "get_provider",
    "fetch_models",
    "get_providers",
    "clear_cache",
    "_CACHE_TTL_S",
    # Phase 3 (decision 0025 sec 6.5): per-provider cost rates.
    "DEFAULT_COST_RATES",
    "cost_for",
    "rate_source_for",
    # Phase 3 F2 (decision 0036): per-provider/model context-window sizes.
    "DEFAULT_CONTEXT_WINDOWS",
    "resolve_context_window",
    # Public alias for the env-var whitelist used by the web layer.
    "is_api_key_env",
]


# Module-level alias. The function was already declared private but
# tested widely. Keeping `_is_api_key_env` lets existing call sites
# keep working; new external callers should use `is_api_key_env`.
is_api_key_env = _is_api_key_env
