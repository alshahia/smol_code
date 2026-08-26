"""Tier sandbox image lifecycle (Phase 1, C2).

Problem this module exists to solve
-----------------------------------
smolagents DockerExecutor (1.26.0) defaults to build_new_image=True
and, when no dockerfile_content is supplied, builds the image tag from
its OWN generic jupyter-kernel Dockerfile. smolcode passes only
image_name - so on the first CodeAgent run the executor silently
OVERWROTE any hand-built smolcode:{tier} image (non-root user, iptables
ENTRYPOINT, allowlisted CLIs) with a plain kernel image. The tier
images referenced by Tier.docker_image were never reliably real.

Contract
--------
ensure_tier_images(settings, tier_names) makes the declared images REAL
before anything launches a container:

1. Compute the source hash of docker/<tier>.Dockerfile plus every file
   it COPYs (currently iptables-init.sh for elevated).
2. If the local image exists AND carries our source-hash label equal
   to the current hash -> reuse (fast path).
3. Otherwise BUILD once from the repo docker context with the label
   baked in. Failures raise ImageBuildError whose message names the
   tag, the context, and the fix.

Callers refuse to start sandboxed tiers when this fails: cli.main
exits with code 6; the web server refuses to boot. Executor kwargs set
build_new_image=False so smolagents can never clobber these images
again (see agents/base.py).

CLI helper:
    python -m smolcode.images ensure [--tier NAME]
    python -m smolcode.images hash <tier>
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path


_log = logging.getLogger(__name__)

# Label carrying the content hash of the image build inputs.
IMAGE_SRC_LABEL = "org.opencontainers.image.smolcode.source-hash"

# Files COPYed by tier Dockerfiles (build-context dependencies).
_TIER_CONTEXT_FILES = {
    "restricted": ("restricted.Dockerfile",),
    "elevated": ("elevated.Dockerfile", "iptables-init.sh"),
    "full_access": ("full_access.Dockerfile",),
}

_SANDBOXED_TIERS = ("restricted", "elevated", "full_access")
# Public alias for callers enumerating sandboxed tiers.
SANDBOXED_TIERS = _SANDBOXED_TIERS

__all__ = [
    "ImageBuildError",
    "SANDBOXED_TIERS",
    "ensure_tier_images",
    "image_is_current",
    "source_hash",
    "tier_build_context",
]


class ImageBuildError(RuntimeError):
    """A tier sandbox image is missing/stale and could not be built."""


def tier_build_context(settings=None):
    """Return the docker build-context directory shipped with smolcode."""
    return Path(__file__).resolve().parent / "docker"


def _context_files(tier_name):
    """Return the sorted list of build-input files for one tier."""
    try:
        names = _TIER_CONTEXT_FILES[tier_name]
    except KeyError:
        raise ImageBuildError(
            "unknown sandboxed tier " + repr(tier_name) + "; expected one of " + repr(sorted(_TIER_CONTEXT_FILES))
        ) from None
    return sorted(names)


def source_hash(tier_name, context_dir=None):
    """sha256 over the tier build inputs (name-prefixed, order-stable)."""
    ctx = Path(context_dir) if context_dir else tier_build_context()
    h = hashlib.sha256()
    for name in _context_files(tier_name):
        p = ctx / name
        if not p.is_file():
            raise ImageBuildError("build input missing: " + str(p))
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
    return h.hexdigest()


@dataclass
class _BuildPlan:
    tag: str
    context_dir: Path
    src_hash: str
    dockerfile: str


def _plans_for(settings, tier_names, context_dir=None):
    plans = []
    ctx = Path(context_dir) if context_dir else tier_build_context()
    for t in tier_names:
        tier = settings.tiers.get(t)
        if tier is None:
            raise ImageBuildError("settings has no tier " + repr(t))
        plans.append(
            _BuildPlan(
                tag=tier.docker_image,
                context_dir=ctx,
                src_hash=source_hash(t, context_dir),
                dockerfile=_context_files(t)[0],
            )
        )
    return plans


def _get_client(docker_client=None):
    if docker_client is not None:
        return docker_client
    import docker

    return docker.from_env()


def image_is_current(client, tag, expected_hash):
    """True iff local image ``tag`` exists and its label matches."""
    try:
        img = client.images.get(tag)
    except Exception:
        # ImageNotFound or daemon hiccup -> treat as stale/missing.
        return False
    labels = getattr(img, "labels", None) or {}
    return labels.get(IMAGE_SRC_LABEL) == expected_hash


def ensure_tier_images(settings, tier_names=_SANDBOXED_TIERS, *, docker_client=None, context_dir=None):
    """Make every requested tier image present + current.

    Returns the list of tags that were BUILT (empty when all were
    already current). Raises ImageBuildError (actionable message) on
    failure so callers can REFUSE to launch sandboxed tiers instead of
    falling back to whatever the executor would improvise.
    """
    client = _get_client(docker_client)
    built = []
    for plan in _plans_for(settings, tuple(tier_names), context_dir):
        if image_is_current(client, plan.tag, plan.src_hash):
            _log.debug("tier image %s up-to-date (hash %s)", plan.tag, plan.src_hash[:12])
            continue
        _log.info("building tier image %s from %s", plan.tag, plan.context_dir)
        try:
            log_stream = client.api.build(
                path=str(plan.context_dir),
                tag=plan.tag,
                rm=True,
                labels={IMAGE_SRC_LABEL: plan.src_hash},
                decode=True,
            )
        except Exception as e:
            raise ImageBuildError(_failure_message(plan, e)) from e
        try:
            for chunk in log_stream:
                msg = chunk.get("stream") or chunk.get("errorDetail", {}).get("message", "")
                if msg:
                    _log.debug("[%s build] %s", plan.tag, msg.rstrip())
                if chunk.get("errorDetail"):
                    raise ImageBuildError(_failure_message(plan, str(chunk.get("error"))))
        except ImageBuildError:
            raise
        except Exception as e:
            raise ImageBuildError(_failure_message(plan, e)) from e
        built.append(plan.tag)
    return built


def _failure_message(plan, err):
    return (
        "failed to build sandbox image "
        + repr(plan.tag)
        + " from "
        + str(plan.context_dir / plan.dockerfile)
        + ": "
        + repr(err)
        + ". Fix the Dockerfile/network problem and restart; smolcode "
        + "refuses to run sandboxed tiers on unverified images."
    )


def _main(argv=None):
    """CLI: python -m smolcode.images ensure|hash ..."""
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(prog="python -m smolcode.images")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ensure = sub.add_parser("ensure", help="build/refresh tier sandbox images")
    p_ensure.add_argument("--tier", action="append", default=[], help="tier (repeatable; default all)")
    p_hash = sub.add_parser("hash", help="print the source hash for a tier")
    p_hash.add_argument("tier")
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.environ.get("SMOLCODE_LOG_LEVEL", "INFO"))
    if args.cmd == "hash":
        print(source_hash(args.tier))
        return 0
    from .config import load_settings

    settings = load_settings()
    tiers = args.tier or list(_SANDBOXED_TIERS)
    try:
        built = ensure_tier_images(settings, tiers)
    except ImageBuildError as e:
        print("error: " + str(e), file=sys.stderr)
        return 6
    print("up-to-date" if not built else "built: " + ", ".join(built))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(_main())
