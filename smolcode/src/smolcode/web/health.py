"""Real health/readiness snapshot for GET /api/health (Phase 8, decision 0043).

Before this module the endpoint returned a hard-coded `{"status": "ok"}`
(web/api.py:144-151, review ops-medium). That made a container HEALTHCHECK
built on it worthless: it reported healthy while the Docker daemon was
unreachable, while the tier images were stale, while the queue drain had
failed, or while the served SPA bundle was older than its sources.

`build_health_snapshot(...)` returns `(payload, status_code)`:

* `200` - healthy or degraded;
* `503` - ONLY when `SMOLCODE_EXECUTOR=docker` and the Docker daemon is
  unreachable. Under the local executor a dead daemon is informational
  (nothing needs it), so the historical 200/`status="ok"` contract holds.
* `degraded` - ONLY when `SMOLCODE_EXECUTOR=docker`: a tier image is missing
  or stale. Under the local executor the images are not used at all, so their
  state is reported in `images` but never changes the status (CI caught the
  earlier version reporting degraded just because a runner happens to have a
  Docker daemon with no smolcode images; see decision 0043 validation).

Every body key that existed before is preserved; all new keys are additive
(the SPA's HealthResponse interface is a subset and ignores unknown keys).

The Docker probe is bounded by a short client timeout (`docker.from_env(
timeout=2)`) so a wedged daemon cannot hang the endpoint, and it is never
allowed to raise.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .. import __version__
from ..images import IMAGE_SRC_LABEL, SANDBOXED_TIERS, source_hash


_log = logging.getLogger(__name__)

# docker-py's default request timeout is 60s. A health endpoint must answer in
# seconds, so pass an explicit bound instead of inheriting it.
DOCKER_PROBE_TIMEOUT_S = 2.0

# Run statuses that occupy the single execution slot (matches
# RunManager.is_busy(): running + awaiting_approval + paused).
_ACTIVE_RUN_STATUSES = frozenset({"running", "awaiting_approval", "paused"})

__all__ = ["DOCKER_PROBE_TIMEOUT_S", "build_health_snapshot"]


def _spa_stale() -> bool | None:
    """Return the SPA freshness verdict, or None when spa.py is unavailable.

    Phase 7 added `web/spa.py` (`spa_is_stale()`). This phase may land before
    or after that file in a cherry-pick, so the import is lazy AND guarded by
    an existence check: a missing helper is reported as None ("unknown"),
    never as a 500 or a false "fresh" claim.
    """
    spa_module = Path(__file__).with_name("spa.py")
    if not spa_module.is_file():
        return None
    try:
        from .spa import spa_is_stale

        return bool(spa_is_stale())
    except Exception as e:  # pragma: no cover - defensive
        _log.debug("SPA freshness check failed: %s", e)
        return None


def probe_docker(timeout_s: float = DOCKER_PROBE_TIMEOUT_S):
    """Return `(client, error)`; `client` is None when the daemon is unreachable.

    Never raises. The timeout bounds the initial connection and every request
    made by the returned client (docker-py applies `timeout` per request).
    """
    try:
        import docker
    except Exception as e:
        return None, "docker SDK not importable (" + type(e).__name__ + ")"
    try:
        client = docker.from_env(timeout=timeout_s)
    except Exception as e:
        return None, type(e).__name__ + ": " + str(e)
    try:
        client.ping()
    except Exception as e:
        return None, "daemon ping failed (" + type(e).__name__ + ")"
    return client, None


def _image_states(client, settings) -> dict[str, str]:
    """Map each sandboxed tier to current | stale | missing | unknown.

    `current` means the local image carries the source-hash label computed
    from the Dockerfiles shipped in THIS wheel - the same check
    `images.ensure_tier_images` uses to decide whether to rebuild.
    """
    tiers = getattr(settings, "tiers", None) or {}
    states: dict[str, str] = {}
    for tier_name in SANDBOXED_TIERS:
        if client is None:
            states[tier_name] = "unknown"
            continue
        try:
            expected = source_hash(tier_name)
        except Exception as e:  # pragma: no cover - shipped context is present
            _log.debug("cannot hash tier %s: %s", tier_name, e)
            states[tier_name] = "unknown"
            continue
        tier = tiers.get(tier_name)
        tag = getattr(tier, "docker_image", "") or ""
        if not tag:
            states[tier_name] = "missing"
            continue
        try:
            image = client.images.get(tag)
        except Exception:
            # ImageNotFound OR a daemon hiccup: both mean "cannot reuse it".
            states[tier_name] = "missing"
            continue
        labels = getattr(image, "labels", None) or {}
        states[tier_name] = "current" if labels.get(IMAGE_SRC_LABEL) == expected else "stale"
    return states


def _queue_and_active(run_manager) -> tuple[int, str | None]:
    """Return `(queue_depth, active_run_id)` without raising."""
    if run_manager is None:
        return 0, None
    try:
        queue_depth = len(run_manager.queue())
    except Exception:
        queue_depth = 0
    active_run = None
    try:
        for run in run_manager.list():
            if getattr(run, "status", None) in _ACTIVE_RUN_STATUSES:
                active_run = getattr(run, "id", None)
                break
    except Exception:
        pass
    return queue_depth, active_run


def _uploads_summary(uploads_store) -> tuple[str, int]:
    if uploads_store is None:
        return "", 0
    try:
        uploads_dir = str(uploads_store.dir)
    except Exception:
        uploads_dir = ""
    try:
        uploads_count = len(uploads_store.list_metadata())
    except Exception:
        uploads_count = 0
    return uploads_dir, uploads_count


def build_health_snapshot(settings, run_manager, uploads_store, *, docker_client=None) -> tuple[dict, int]:
    """Build the `/api/health` body and the HTTP status code.

    Args:
        settings: resolved `Settings` (executor + tier image tags).
        run_manager: `RunManager` or None (queue depth / active run / drain error).
        uploads_store: `UploadsStore` or None (legacy keys).
        docker_client: injectable Docker client (tests); when None the daemon
            is probed with a bounded timeout.

    Returns:
        `(payload, status_code)`.
    """
    docker_error = None
    if docker_client is None:
        docker_client, docker_error = probe_docker()
    docker_state = "reachable" if docker_client is not None else "unreachable"
    executor = getattr(settings, "executor", "") or ""

    uploads_dir, uploads_count = _uploads_summary(uploads_store)
    queue_depth, active_run = _queue_and_active(run_manager)
    images = _image_states(docker_client, settings)
    queue_drain_error = getattr(run_manager, "queue_drain_error", None) if run_manager is not None else None

    status = "ok"
    status_code = 200
    if docker_state == "unreachable" and executor == "docker":
        # A docker-executor deployment that cannot reach the daemon cannot run
        # ANY sandboxed tier. This is the one condition worth failing a
        # container healthcheck over (decision 0043).
        status = "unhealthy"
        status_code = 503
        _log.warning("health: executor=docker but the Docker daemon is unreachable: %s", docker_error)
    elif executor == "docker" and docker_state == "reachable" and any(state != "current" for state in images.values()):
        # Serving is still possible (the boot check already refuses stale
        # images), but an operator should see it before the first run does.
        status = "degraded"

    payload = {
        "status": status,
        "version": __version__,
        "uploads_dir": uploads_dir,
        "uploads_count": uploads_count,
        "docker": docker_state,
        "images": images,
        "queue_depth": queue_depth,
        "active_run": active_run,
        "queue_drain_error": queue_drain_error,
        "spa_stale": _spa_stale(),
    }
    return payload, status_code
