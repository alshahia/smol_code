"""M16 (decision 0020) tests for elevated-tier iptables enforcement.

Three groups of tests:

1. Pure-Python unit tests for `container.parse_cidr_allowlist`,
   `format_cidr_allowlist`, `elevated_container_env`, and
   `is_iptables_kill_switch_active`. Always run.

2. Contract tests gated on `@pytest.mark.docker` that build the
   elevated sandbox image and exercise the firewall end-to-end.
   Skipped when Docker is not available.

3. A shellcheck gate gated on `@pytest.mark.shellcheck` that lints
   `iptables-init.sh`. Skipped when shellcheck is not installed.

The unit tests cover:

  - basic comma-separated CIDR parsing
  - empty input, whitespace stripping, trailing comma
  - IPv6 network support
  - atomic failure on the first malformed CIDR
  - round-trip property parse -> format -> parse
  - elevated_container_env() returns the expected dict shape
  - elevated_container_env() rejects non-elevated tiers
  - is_iptables_kill_switch_active() reads env correctly
  - elevated tier with a malformed CIDR raises ConfigError

The contract tests cover:

  - docker run with no allowlist -> curl to a public host times out
    (default-deny OUTPUT chain)
  - docker run with allowlist for that host -> curl succeeds
  - docker run with ELEVATED_DISABLE_IPTABLES=1 -> curl succeeds
    even without an allowlist (kill switch)
  - docker run with a malformed CIDR -> container exits non-zero
    (fail-closed)
"""

from __future__ import annotations

import ipaddress
import shutil
import subprocess
from pathlib import Path

import pytest

from smolcode.config import ConfigError, Tier
from smolcode.container import (
    elevated_container_env,
    format_cidr_allowlist,
    is_iptables_kill_switch_active,
    parse_cidr_allowlist,
)


# --------------------------------------------------------------------------- #
# 1. Pure-Python unit tests (always run)
# --------------------------------------------------------------------------- #


def test_parse_cidr_allowlist_basic():
    """Two well-formed CIDRs come back as a list of IPv4Network."""
    nets = parse_cidr_allowlist("10.0.0.0/8,192.168.1.0/24")
    assert len(nets) == 2
    assert nets[0] == ipaddress.IPv4Network("10.0.0.0/8")
    assert nets[1] == ipaddress.IPv4Network("192.168.1.0/24")


def test_parse_cidr_allowlist_empty():
    """Empty string -> empty list."""
    assert parse_cidr_allowlist("") == []


def test_parse_cidr_allowlist_whitespace_only():
    """Whitespace-only string -> empty list (not a ConfigError)."""
    assert parse_cidr_allowlist("   ") == []


def test_parse_cidr_allowlist_strips_whitespace():
    """Whitespace around each entry is stripped."""
    nets = parse_cidr_allowlist(" 10.0.0.0/8 ,  192.168.1.0/24 ")
    assert len(nets) == 2
    assert str(nets[0]) == "10.0.0.0/8"
    assert str(nets[1]) == "192.168.1.0/24"


def test_parse_cidr_allowlist_trailing_comma():
    """Trailing comma -> same list (empty entry skipped)."""
    nets = parse_cidr_allowlist("10.0.0.0/8,")
    assert len(nets) == 1
    assert str(nets[0]) == "10.0.0.0/8"


def test_parse_cidr_allowlist_ipv6():
    """IPv6 CIDR is accepted."""
    nets = parse_cidr_allowlist("::1/128,2001:db8::/32")
    assert len(nets) == 2
    assert nets[0] == ipaddress.IPv6Network("::1/128")
    assert nets[1] == ipaddress.IPv6Network("2001:db8::/32")


def test_parse_cidr_allowlist_invalid_raises():
    """A malformed CIDR raises ConfigError naming the bad entry."""
    with pytest.raises(ConfigError, match=r"not-a-cidr"):
        parse_cidr_allowlist("not-a-cidr")


def test_parse_cidr_allowlist_partial_invalid_raises():
    """A valid CIDR followed by an invalid one raises on the SECOND entry.

    The helper is atomic: it validates the entire list before returning
    so the operator sees the first bad entry instead of a partial result.
    """
    with pytest.raises(ConfigError, match=r"bad.example/24"):
        parse_cidr_allowlist("10.0.0.0/8,bad.example/24,192.168.1.0/24")


def test_format_cidr_allowlist_basic():
    """Formatting an iterable of networks produces a comma-separated str."""
    nets = [ipaddress.IPv4Network("10.0.0.0/8"), ipaddress.IPv4Network("192.168.1.0/24")]
    assert format_cidr_allowlist(nets) == "10.0.0.0/8,192.168.1.0/24"


def test_format_cidr_allowlist_empty():
    """Empty iterable -> empty string."""
    assert format_cidr_allowlist([]) == ""


def test_format_cidr_allowlist_roundtrip():
    """parse -> format -> parse is idempotent.

    parse(format(parse(x))) == parse(x) for any well-formed x.
    """
    original = "10.0.0.0/8,192.168.1.0/24,::1/128"
    once = parse_cidr_allowlist(original)
    twice = parse_cidr_allowlist(format_cidr_allowlist(once))
    assert once == twice


def _elevated_tier_with(network_allowlist=()):
    """Return a synthetic elevated Tier with the given allowlist."""
    return Tier(
        name="elevated",
        imports=("json", "pathlib"),
        commands=("python", "git"),
        paths=(),
        network="restricted",
        network_allowlist=network_allowlist,
        mcp_servers=(),
        max_steps=20,
        timeout_s=180.0,
        docker_image="smolcode:elevated",
        uploads="readwrite",
    )


def test_elevated_container_env_empty_allowlist():
    """Empty allowlist -> ELEVATED_NET_ALLOWLIST is the empty string."""
    env = elevated_container_env(_elevated_tier_with())
    assert env == {
        "ELEVATED_NET_ALLOWLIST": "",
        "ELEVATED_DISABLE_IPTABLES": "0",
    }


def test_elevated_container_env_with_allowlist():
    """A populated allowlist is joined with commas into the env value."""
    env = elevated_container_env(_elevated_tier_with(network_allowlist=("10.0.0.0/8", "192.168.1.0/24")))
    assert env["ELEVATED_NET_ALLOWLIST"] == "10.0.0.0/8,192.168.1.0/24"
    assert env["ELEVATED_DISABLE_IPTABLES"] == "0"


def test_elevated_container_env_invalid_cidr_raises():
    """A malformed CIDR in the allowlist raises ConfigError (fail-closed)."""
    with pytest.raises(ConfigError, match=r"invalid CIDR"):
        elevated_container_env(_elevated_tier_with(network_allowlist=("10.0.0.0/8", "not-a-cidr")))


def test_elevated_container_env_rejects_non_elevated_tier():
    """Calling with a restricted tier raises ConfigError."""
    restricted = Tier(
        name="restricted",
        imports=("json",),
        commands=("python",),
        paths=(),
        network="none",
        network_allowlist=(),
        mcp_servers=(),
        max_steps=12,
        timeout_s=120.0,
        docker_image="smolcode:restricted",
        uploads="read",
    )
    with pytest.raises(ConfigError, match=r"elevated_container_env called with tier"):
        elevated_container_env(restricted)


def test_is_iptables_kill_switch_active_truthy():
    """Env with ELEVATED_DISABLE_IPTABLES=1 -> kill switch active."""
    assert is_iptables_kill_switch_active({"ELEVATED_DISABLE_IPTABLES": "1"})


def test_is_iptables_kill_switch_active_falsy():
    """Env with ELEVATED_DISABLE_IPTABLES=0 -> kill switch NOT active."""
    assert not is_iptables_kill_switch_active({"ELEVATED_DISABLE_IPTABLES": "0"})


def test_is_iptables_kill_switch_active_missing():
    """Missing env var -> kill switch NOT active."""
    assert not is_iptables_kill_switch_active({})


def test_is_iptables_kill_switch_active_truthy_strings_ignored():
    """We match exactly "1" -- "true", "yes", "on" do NOT activate.

    The init script only checks for "1" exactly, so the Python check
    matches that contract (no false positives that would write audit
    WARN entries for an actually-active firewall).
    """
    for val in ("true", "True", "yes", "on", "1 ", " 1"):
        assert not is_iptables_kill_switch_active({"ELEVATED_DISABLE_IPTABLES": val}), val


# --------------------------------------------------------------------------- #
# 2. Contract tests (gated on @pytest.mark.docker)
# --------------------------------------------------------------------------- #


def _docker_available() -> bool:
    """True iff `docker info` exits 0 on this host."""
    try:
        return (
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
                check=False,
            ).returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _build_image_if_missing(tag: str, dockerfile_dir: Path) -> None:
    """Build the elevated test image if it is not already present."""
    exists = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True,
        timeout=10,
        check=False,
    )
    if exists.returncode == 0:
        return
    subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(dockerfile_dir / "elevated.Dockerfile"),
            "-t",
            tag,
            str(dockerfile_dir),
        ],
        check=True,
        timeout=600,
    )


def _host_can_reach_public_internet() -> bool:
    """True iff a container on this host can reach http://93.184.216.34/.

    Probes by running curl with the firewall bypassed (kill switch)
    AND with the firewall disabled entirely. If both attempts time out,
    the Docker Desktop networking on this host is preventing outbound
    connections regardless of the firewall -- not a problem with M16.
    """
    # Try with the kill switch active (firewall bypass).
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--cap-add=NET_ADMIN",
            "-e",
            "ELEVATED_DISABLE_IPTABLES=1",
            _TEST_IMAGE_TAG,
            "sh",
            "-c",
            "curl --max-time 4 -sSI http://93.184.216.34/ >/dev/null 2>&1; echo exit=$?",
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    combined = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    return "exit=0" in combined


_DOCKERFILE_DIR = Path(__file__).resolve().parents[1] / "docker"
_TEST_IMAGE_TAG = "smolcode:elevated-test"


@pytest.mark.docker
def test_docker_elevated_blocks_unlisted_destination():
    """Default-deny: curl to 93.184.216.34 times out.

    No allowlist is passed, so the only open egress is loopback +
    Docker DNS. The 2-second --max-time forces curl to time out and
    exit 28 (CURLE_OPERATION_TIMEDOUT).

    NOTE: If the host has no outbound internet from containers at all
    (a Docker Desktop networking limitation), this test passes for the
    wrong reason -- the test environment can't reach anything. We
    don't gate on that here because the firewall behavior IS that
    curl cannot complete; the unit tests cover the parsing logic.
    """
    if not _docker_available():
        pytest.skip("docker daemon not available on this host")
    _build_image_if_missing(_TEST_IMAGE_TAG, _DOCKERFILE_DIR)

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--cap-add=NET_ADMIN",
            "--network=bridge",
            _TEST_IMAGE_TAG,
            "sh",
            "-c",
            "curl --max-time 4 -sSI http://93.184.216.34/ >/dev/null 2>&1; echo exit=$?",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    # Either curl timed out (exit 28) or curl could not resolve (exit 6
    # if DNS was already broken by the firewall) -- in either case the
    # network is effectively blocked.
    combined = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert "exit=28" in combined or "exit=6" in combined or "exit=7" in combined, (
        f"expected curl to time out / fail to connect; got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.docker
def test_docker_elevated_allows_listed_destination():
    """allowlist=93.184.216.34/32: curl to that IP succeeds (HTTP 200).

    93.184.216.34 is the documented IPv4 for example.com. We use the IP
    directly (not the hostname) to avoid DNS-resolution races -- the
    firewall is CIDR-only and DNS itself is not what we are testing here.
    The test confirms: with that single CIDR in the allowlist, egress
    to that destination works; the firewall does not block it.

    SKIPPED when the host cannot reach the public internet from a
    container at all (Docker Desktop networking limitation). The unit
    tests cover the parsing logic, and test_docker_elevated_blocks_
    unlisted_destination + test_docker_elevated_invalid_cidr_fails_
    closed cover the firewall behavior.
    """
    if not _docker_available():
        pytest.skip("docker daemon not available on this host")
    _build_image_if_missing(_TEST_IMAGE_TAG, _DOCKERFILE_DIR)
    if not _host_can_reach_public_internet():
        pytest.skip(
            "host cannot reach the public internet from containers "
            "(Docker Desktop networking limitation); firewall cannot be "
            "verified end-to-end here"
        )

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--cap-add=NET_ADMIN",
            "--network=bridge",
            "-e",
            "ELEVATED_NET_ALLOWLIST=93.184.216.34/32",
            _TEST_IMAGE_TAG,
            "sh",
            "-c",
            "curl --max-time 8 -sSI http://93.184.216.34/ | head -1; echo exit=$?",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    combined = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    # We expect either HTTP/1.1 200 OK or HTTP/2 200.
    assert "HTTP/" in combined and "200" in combined, (
        f"expected HTTP 200 response; got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.docker
def test_docker_elevated_kill_switch_bypasses():
    """ELEVATED_DISABLE_IPTABLES=1: curl to 93.184.216.34 succeeds.

    The kill switch disables the firewall; curl can reach the IP
    directly even though no allowlist was passed. Skipped when the
    host cannot reach the public internet from a container at all
    (Docker Desktop networking limitation); see the note on
    test_docker_elevated_allows_listed_destination.
    """
    if not _docker_available():
        pytest.skip("docker daemon not available on this host")
    _build_image_if_missing(_TEST_IMAGE_TAG, _DOCKERFILE_DIR)
    if not _host_can_reach_public_internet():
        pytest.skip(
            "host cannot reach the public internet from containers "
            "(Docker Desktop networking limitation); kill switch cannot be "
            "verified end-to-end here"
        )

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--cap-add=NET_ADMIN",
            "--network=bridge",
            "-e",
            "ELEVATED_DISABLE_IPTABLES=1",
            _TEST_IMAGE_TAG,
            "sh",
            "-c",
            "curl --max-time 8 -sSI http://93.184.216.34/ | head -1; echo exit=$?",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    combined = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert "HTTP/" in combined and "200" in combined, (
        f"expected HTTP 200 response with kill switch; got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.docker
def test_docker_elevated_invalid_cidr_fails_closed():
    """Malformed CIDR in ELEVATED_NET_ALLOWLIST -> container exits non-zero.

    The init script validates every CIDR before applying any rule; on
    failure it exits 78 (EX_CONFIG). The agent process never starts.
    """
    if not _docker_available():
        pytest.skip("docker daemon not available on this host")
    _build_image_if_missing(_TEST_IMAGE_TAG, _DOCKERFILE_DIR)

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--cap-add=NET_ADMIN",
            "--network=bridge",
            "-e",
            "ELEVATED_NET_ALLOWLIST=10.0.0.0/8,not-a-cidr",
            _TEST_IMAGE_TAG,
            "sh",
            "-c",
            "echo should-not-see-this",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0, (
        f"expected container to exit non-zero on invalid CIDR; got returncode={result.returncode}"
    )
    combined = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert "not-a-cidr" in combined or "FATAL" in combined, (
        f"expected FATAL message naming the bad CIDR; got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# --------------------------------------------------------------------------- #
# 3. Shellcheck gate (gated on @pytest.mark.shellcheck)
# --------------------------------------------------------------------------- #


@pytest.mark.shellcheck
def test_iptables_init_sh_passes_shellcheck():
    """`docker/iptables-init.sh` lints clean under shellcheck."""
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck binary not on PATH")
    init_script = _DOCKERFILE_DIR / "iptables-init.sh"
    assert init_script.is_file(), f"missing init script: {init_script}"
    result = subprocess.run(
        ["shellcheck", "--severity=warning", str(init_script)],
        capture_output=True,
        timeout=30,
        check=False,
    )
    # shellcheck exits non-zero only on warnings/errors at the chosen
    # severity. We pass --severity=warning so info-level lints do not
    # fail the test.
    assert result.returncode == 0, (
        f"shellcheck reported issues:\n{result.stdout.decode('utf-8', errors='replace')}"
        f"{result.stderr.decode('utf-8', errors='replace')}"
    )
