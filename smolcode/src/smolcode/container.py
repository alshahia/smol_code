"""Container-side helpers (M16, decision 0020).

Currently exposes:
- parse_cidr_allowlist(str) -> list[IPv4Network | IPv6Network]
- format_cidr_allowlist(iterable) -> str
- elevated_container_env(Tier) -> dict[str, str]
- is_iptables_kill_switch_active(env dict) -> bool

These helpers are used by `agents/base.py:_executor_kwargs_for` to
build the `environment` dict passed to the elevated Docker container.
The same parsing logic is also run inside the container by
`docker/iptables-init.sh` (via `python3 -c "ipaddress.ip_network(...)"`)
so the validation is consistent on both sides.

The kill switch check is exported separately so `audit.py` can decide
whether to write a WARN entry to the audit log without depending on
the Tier object directly.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping

from .config import ConfigError, Tier


__all__ = [
    "parse_cidr_allowlist",
    "format_cidr_allowlist",
    "elevated_container_env",
    "is_iptables_kill_switch_active",
]


def parse_cidr_allowlist(value: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse a comma-separated CIDR allowlist string.

    Whitespace around each entry is stripped. Empty entries (e.g. trailing
    comma) are skipped. Raises ConfigError on the FIRST invalid CIDR so
    the operator gets an actionable message ("CIDR #3 is malformed: ...").

    Returns a list of ipaddress.IPv4Network / IPv6Network in input order.

    Examples:
        >>> parse_cidr_allowlist("")
        []
        >>> parse_cidr_allowlist("10.0.0.0/8")
        [IPv4Network('10.0.0.0/8')]
        >>> [str(n) for n in parse_cidr_allowlist("10.0.0.0/8, ::1/128")]
        ['10.0.0.0/8', '::1/128']
    """
    if not value or not value.strip():
        return []
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for idx, raw in enumerate(value.split(","), start=1):
        cidr = raw.strip()
        if not cidr:
            # Skip empties (trailing comma, double comma) silently.
            continue
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError as e:
            raise ConfigError(f"invalid CIDR #{idx} in ELEVATED_NET_ALLOWLIST: {cidr!r} ({e})") from e
    return networks


def format_cidr_allowlist(networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> str:
    """Format an iterable of CIDR networks into the env-var string format.

    Each network is rendered via `str(network)` (canonical form, e.g.
    "10.0.0.0/8" not "10.0.0.000/8"). Empty iterable returns "".

    Round-trip property: parse_cidr_allowlist(format_cidr_allowlist(parse_cidr_allowlist(x)))
    equals parse_cidr_allowlist(x) for any well-formed input x.
    """
    return ",".join(str(n) for n in networks)


def elevated_container_env(tier: Tier) -> dict[str, str]:
    """Build the env-var dict passed to the elevated Docker container.

    Validates tier.network_allowlist as CIDRs up front (fail-closed: any
    malformed entry raises ConfigError BEFORE we try to launch the
    container, so the operator sees the error immediately). The same
    validation runs inside the container via iptables-init.sh; doing it
    here too means we never even start a container we know is broken.

    The returned dict contains:
        ELEVATED_NET_ALLOWLIST: comma-separated CIDR string (may be empty)
        ELEVATED_DISABLE_IPTABLES: the string "0" (smolcode never sets
            the kill switch itself; operators can set it via the
            container env at launch time if they need to debug)

    The audit log gets a WARN entry when the kill switch is active;
    see audit.py:_check_iptables_kill_switch.
    """
    if tier.name != "elevated":
        raise ConfigError(f"elevated_container_env called with tier {tier.name!r}; expected 'elevated'")
    # Force evaluation of parse_cidr_allowlist so any malformed CIDR
    # raises BEFORE the container is launched.
    networks = parse_cidr_allowlist(",".join(tier.network_allowlist))
    return {
        "ELEVATED_NET_ALLOWLIST": format_cidr_allowlist(networks),
        "ELEVATED_DISABLE_IPTABLES": "0",
    }


def is_iptables_kill_switch_active(env: Mapping[str, str]) -> bool:
    """True iff the ELEVATED_DISABLE_IPTABLES=1 kill switch is set in env.

    Used by audit.py to decide whether to record a WARN entry. We accept
    any string equal to "1" exactly; other truthy-looking values
    ("true", "yes", "on") are ignored -- the init script only checks
    for "1" exactly, so we match that contract.
    """
    val = env.get("ELEVATED_DISABLE_IPTABLES", "")
    return val == "1"
