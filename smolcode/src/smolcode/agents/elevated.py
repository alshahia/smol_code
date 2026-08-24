"""The elevated tier (M4 + M16). See docs/architecture.md 5.4 + docs/security.md 3.2/9.

Elevated adds extra imports + commands vs restricted. M16 (decision
0020) wires kernel-level network enforcement: the elevated container
boots with `docker/iptables-init.sh` as its ENTRYPOINT, which applies a
default-deny OUTPUT chain + explicit ACCEPT rules for each CIDR in
`settings.tiers["elevated"].network_allowlist` (plus loopback and the
Docker embedded DNS resolver at 127.0.0.11). The Python side passes
the allowlist to the container via the `ELEVATED_NET_ALLOWLIST` env
var (see `container.elevated_container_env`); smolcode also adds
`cap_add=["NET_ADMIN"]` so the entrypoint can invoke iptables.

The agent process itself still runs as UID 1000 (smolagent) -- the
init script drops privileges via `gosu` before exec'ing the CMD, so
the kernel-level firewall is set up by root and then the model-written
code never sees CAP_NET_ADMIN.
"""

from __future__ import annotations

from .base import make_agent


def build_elevated_agent(settings, model, *, max_steps=None):
    """Build the elevated-tier CodeAgent."""
    return make_agent(
        tier=settings.tiers["elevated"],
        settings=settings,
        model=model,
        max_steps=max_steps,
    )
