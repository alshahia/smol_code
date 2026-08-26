"""Phase 1 (C2/H1): docker-marked tier-image consistency tests.

Run ONLY where a Docker daemon exists (CI Job B / local dev with
Docker running): pytest -m docker

Contract: for every sandboxed tier, after ensure_tier_images():
  1. the image exists locally and carries the current source-hash label;
  2. EVERY command in the tier command allowlist resolves inside the
     container (image <-> allowlist consistency, both directions that
     matter operationally);
  3. the elevated image keeps its iptables ENTRYPOINT;
  4. a restricted-tier container attached to the internal bridge has no
     external egress (network=none enforced by topology).
"""

from __future__ import annotations

import pytest

from smolcode.config import load_settings
from smolcode.container import INTERNAL_NETWORK_NAME, ensure_internal_network
from smolcode.images import (
    IMAGE_SRC_LABEL,
    SANDBOXED_TIERS,
    ensure_tier_images,
    source_hash,
)


pytestmark = pytest.mark.docker


@pytest.fixture(scope="session")
def dclient():
    import docker

    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"docker daemon unavailable: {exc}")
    return client


@pytest.fixture(scope="session")
def settings():
    s = load_settings()
    ensure_tier_images(s, SANDBOXED_TIERS)
    return s


def _run_probe(client, image, probe, network=None):
    """Run sh -lc probe; return stdout text. Raises on nonzero exit."""
    kwargs = {
        "entrypoint": ["/bin/sh"],
        "command": ["-lc", probe],
        "remove": True,
        "stdout": True,
        "stderr": False,
    }
    if network:
        kwargs["network"] = network
    out = client.containers.run(image, **kwargs)
    return out.decode("utf-8", errors="replace") if isinstance(out, bytes) else str(out)


@pytest.mark.parametrize("tier", SANDBOXED_TIERS)
def test_tier_image_label_is_current(dclient, settings, tier):
    tag = settings.tiers[tier].docker_image
    img = dclient.images.get(tag)
    assert img.labels.get(IMAGE_SRC_LABEL) == source_hash(tier), f"{tag} is stale - rebuild via make docker-images"


@pytest.mark.parametrize("tier", SANDBOXED_TIERS)
def test_every_allowlisted_command_resolves_in_image(dclient, settings, tier):
    """Image<->allowlist consistency: the allowlist must not lie."""
    tag = settings.tiers[tier].docker_image
    cmds = list(settings.tiers[tier].commands)
    probe = "; ".join(f"command -v {c} >/dev/null 2>&1 || echo MISSING:{c}" for c in cmds)
    out = _run_probe(dclient, tag, probe)
    missing = [line for line in out.splitlines() if line.startswith("MISSING:")]
    assert missing == [], f"{tag} lacks allowlisted commands: {missing}"


def test_elevated_image_keeps_iptables_entrypoint(dclient, settings):
    tag = settings.tiers["elevated"].docker_image
    img = dclient.images.get(tag)
    entrypoint = img.attrs.get("Config", {}).get("Entrypoint") or []
    assert any("iptables-init.sh" in part for part in entrypoint), entrypoint


def test_restricted_container_has_no_external_egress(dclient, settings):
    """H1: restricted containers attached to the internal net cannot dial out."""
    ensure_internal_network(dclient)
    tag = settings.tiers["restricted"].docker_image
    probe = (
        'python -c "import socket; socket.setdefaulttimeout(3); '
        + "socket.create_connection(('93.184.216.34', 80)); "
        + "print('EGRESS-LEAK')\""
    )
    from docker.errors import ContainerError

    with pytest.raises(ContainerError):
        _run_probe(dclient, tag, probe, network=INTERNAL_NETWORK_NAME)
