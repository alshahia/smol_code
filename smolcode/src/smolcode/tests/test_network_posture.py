"""Phase 1 (H1): network posture - unit-level pins.

Covers:
- restricted executor kwargs attach ONLY to the internal bridge
- ensure_internal_network creates with internal=True, idempotent
- iptables-init.sh carries the ICMPv6 NDP/PMTUD allowances (script pin;
  full end-to-end firewall behavior stays in test_elevated_iptables)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from smolcode.agents.base import _executor_kwargs_for
from smolcode.config import load_settings
from smolcode.container import INTERNAL_NETWORK_NAME, ensure_internal_network


@pytest.fixture
def docker_settings(monkeypatch):
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "docker")
    return load_settings()


def test_restricted_container_attaches_internal_network(docker_settings):
    kw = _executor_kwargs_for("docker", docker_settings.tiers["restricted"], docker_settings)
    rkw = kw["container_run_kwargs"]
    assert rkw["network"] == INTERNAL_NETWORK_NAME == "smolcode-internal"
    assert "cap_add" not in rkw  # no NET_ADMIN needed for restricted


def test_elevated_container_keeps_iptables_posture(docker_settings):
    kw = _executor_kwargs_for("docker", docker_settings.tiers["elevated"], docker_settings)
    rkw = kw["container_run_kwargs"]
    assert rkw["cap_add"] == ["NET_ADMIN"]
    assert "network" not in rkw  # default bridge + kernel firewall


class FakeNet:
    def __init__(self, name):
        self.name = name


class FakeNetworks:
    def __init__(self, existing, created):
        self._existing = existing
        self._created = created
        self.create_kwargs = None

    def list(self, names=None):
        return [n for n in self._existing if not names or n.name in names[0] or n.name in names]

    def create(self, name, **kwargs):
        self.create_kwargs = {"name": name, **kwargs}
        net = FakeNet(name)
        self._created.append(net)
        return net


class FakeClient:
    def __init__(self):
        self.created = []
        self.networks = FakeNetworks([], self.created)


def test_ensure_internal_network_creates_internal_bridge():
    c = FakeClient()
    net = ensure_internal_network(c)
    assert net.name == INTERNAL_NETWORK_NAME
    assert c.networks.create_kwargs["internal"] is True
    assert c.networks.create_kwargs["driver"] == "bridge"


def test_ensure_internal_network_is_idempotent():
    c = FakeClient()
    c.networks._existing.append(FakeNet(INTERNAL_NETWORK_NAME))
    net = ensure_internal_network(c)
    assert net.name == INTERNAL_NETWORK_NAME
    assert c.created == []  # nothing new created


# --- script pin: ICMPv6 NDP/PMTUD allowances -------------------------------


def _init_script() -> str:
    p = Path(__file__).resolve().parents[1] / "docker" / "iptables-init.sh"
    return p.read_text(encoding="utf-8")


def test_ip6tables_allows_ndp_pmtud_control_traffic():
    script = _init_script()
    assert "--icmpv6-type" in script, "ICMPv6 type allowances missing from ip6tables chain"
    for t in ("2", "133", "134", "135", "136"):
        assert t in script.split("--icmpv6-type")[-1] or any(
            t in line for line in script.splitlines() if "icmpv6-type" in line or "for icmp_type" in line
        ), f"missing ICMPv6 type {t}"
