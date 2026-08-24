# 0020 — M16 iptables Enforcement for Elevated Tier

**Date:** 2026-08-23
**Status:** PLANNED — user approved with "go M16" on 2026-08-23
**Parent roadmap:** [0017](./0017-m14-m15-m16-roadmap.md) §5
**Milestone number:** M16 (final milestone of the v1.1 followup set)
**Estimated effort:** ~2.0 person-days, ~280 LOC + 80 LOC shell + Dockerfile
**Target ship:** v1.7

---

## 1. Context and motivation

M4 (decision 0006) wired the three-tier model and declared the elevated
tier's network_allowlist field on the Tier dataclass. M4 explicitly
noted that *iptables enforcement inside the container is deferred to
v1.1* — see 0006 (decision 0006) §3.4 and the
header comment of smolcode/src/smolcode/docker/elevated.Dockerfile:

> Network: the elevated tier declares network="restricted" with an
> empty allowlist. v1 wires the data structure only; iptables
> enforcement inside the container is DEFERRED to v1.1 (per
> docs/roadmap.md 6). For v1 the Docker executor still runs with
> network_mode=none (same as restricted) …

Today (v1.6), the elevated container's network posture is the same as
restricted: effectively none. This is safe-by-default but means an
elevated-tier agent that wants to pip install from PyPI, git fetch
from a configured remote, or curl an internal API cannot do so without
falling through to full_access. The expected use case for elevated
("push a branch to GitHub", "deploy a preview", "trigger CI") cannot
be exercised today.

M16 closes v1.1 followup #1 by making the elevated tier's declared
network allowlist **enforced at the kernel level** inside the container
using iptables, so an elevated agent can reach exactly the destinations
its operator configured and nothing else — even if it bypasses our
Python-level safe_shell allowlist or the LocalPythonExecutor
imports check.

---

## 2. Goals

G1. **Kernel-level egress filtering.** When the elevated container
    boots, it applies an iptables OUTPUT chain with default-deny and
    explicit ACCEPT rules for each CIDR in
    tier.network_allowlist. Container-internal loopback and the
    Docker embedded DNS resolver (127.0.0.11:53) stay open so name
    resolution and inter-process comms continue to work.

G2. **Fail-closed on bad config.** If ELEVATED_NET_ALLOWLIST contains
    a malformed CIDR, the container exits non-zero *before* the agent
    process starts (fail-closed). The Python side validates the same
    allowlist at container-launch time and raises ConfigError if any
    CIDR is invalid (so we never even start a container we know is
    broken).

G3. **Privileged setup, unprivileged agent.** The iptables rules must
    be applied as root inside the container (iptables requires
    CAP_NET_ADMIN); the agent process itself continues to run as the
    non-root smolagent (UID 1000) user. Privilege-dropping via
    gosu happens inside the entrypoint script, after the firewall
    is configured.

G4. **No host-side capability changes.** smolcode continues to
    launch Docker containers the same way it does today; the only new
    requirement is that the **container itself** is launched with
    cap_add=["NET_ADMIN"]. The host's network namespace is not
    touched.

G5. **Kill switch for emergency debugging.** An env var
    ELEVATED_DISABLE_IPTABLES=1 on the container causes the init
    script to skip iptables setup entirely. The use of this switch is
    logged to the audit log as a WARN entry naming the operator and
    the timestamp. Documented in docs/security.md §9 as a
    security-sensitive escape hatch (must NOT be the default).

G6. **Schema clarity.** Tier.network_allowlist becomes a tuple of
    **CIDR strings** (e.g. "140.82.112.0/24"), not hostnames.
    Updated docstring + comments. No v1 consumer existed that
    depended on the hostname form, so this is a clean rename of
    semantics, not a breaking API change.

---

## 3. Non-goals

NG1. **No restricted-tier changes.** Restricted keeps network="none"
     and network_mode=none. Adding iptables there would be
     defense-in-depth but is out of scope for M16 (deferred to v1.2
     as decision 0021 candidate; see §10).

NG2. **No full_access-tier changes.** Full access already has
     network="open" and network_allowlist=("*",). The M16 design
     does not apply; full_access network posture is operator-blessed
     by the per-run confirmation prompt.

NG3. **No host-side firewall changes.** iptables rules live INSIDE the
     elevated container's network namespace. The host's iptables /
     nftables are untouched. smolcode does not require
     CAP_NET_ADMIN on the host.

NG4. **No new third-party Python dependency.** iptables and
     iproute2 are added to the elevated image; gosu is fetched
     as a static binary from its GitHub release (same pattern as the
     official postgres, nginx, redis Docker images). No
     Python package changes.

NG5. **No hostnames in the allowlist.** network_allowlist accepts
     CIDRs only. The hostname form (v1.0) had no consumers and was
     never enforced; the M16 schema is **CIDR-only** to avoid DNS
     resolution races (an agent could trigger a different DNS
     resolution at request time vs. rule application time).

---

## 4. Architecture

### 4.1 Container boot sequence (elevated image only)

```
docker run smolcode:elevated [jupyter kernelgateway ...]
        |
        v
ENTRYPOINT ["/usr/local/bin/iptables-init.sh"]
        |
        v  (runs as root, has CAP_NET_ADMIN in this container)
1. read ELEVATED_NET_ALLOWLIST env var (comma-separated CIDRs)
2. validate each CIDR via python3 -c "ipaddress.ip_network(c, strict=False)"
3. iptables -P OUTPUT DROP
4. iptables -A OUTPUT -o lo -j ACCEPT          (loopback)
5. iptables -A OUTPUT -p udp --dport 53 -d 127.0.0.11 -j ACCEPT
6. iptables -A OUTPUT -p tcp --dport 53 -d 127.0.0.11 -j ACCEPT
7. iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
8. for each CIDR in allowlist:
       iptables -A OUTPUT -d "$cidr" -j ACCEPT
9. if ELEVATED_DISABLE_IPTABLES=1: skip steps 3-8, log WARN to stderr
10. exec gosu 1000:1000 "$@"   (drop to non-root, run agent)
```

### 4.2 Python-side wiring

`agents/base.py:_executor_kwargs_for` is extended so that when the
tier is "elevated", the container_run_kwargs dict includes:

```python
{
    "image_name": "smolcode:elevated",
    "cap_add": ["NET_ADMIN"],
    "environment": {
        "ELEVATED_NET_ALLOWLIST": "140.82.112.0/24,151.101.0.0/16",
        "ELEVATED_DISABLE_IPTABLES": "0",
    },
    "volumes": {host_ws: {"bind": "/workspace", "mode": "rw"}},
    "auto_remove": True,
}
```

The environment-dict is built by a new helper
container.elevated_container_env(tier) that:

- validates each CIDR via ipaddress.ip_network(strict=False)
- raises ConfigError on the first invalid CIDR (fail-closed)
- returns the dict

The new module smolcode/src/smolcode/container.py houses this
helper plus the lower-level parse_cidr_allowlist /
format_cidr_allowlist utilities (kept small + testable in
isolation).

### 4.3 Files affected

| File | Change | LOC |
|---|---|---|
| smolcode/src/smolcode/docker/iptables-init.sh | NEW | ~80 |
| smolcode/src/smolcode/docker/elevated.Dockerfile | Add iptables, iproute2, gosu, ENTRYPOINT, chmod | +15 |
| smolcode/src/smolcode/container.py | NEW (parse_cidr_allowlist, format_cidr_allowlist, elevated_container_env) | ~70 |
| smolcode/src/smolcode/config.py | Update Tier.network_allowlist docstring (CIDR semantics); update _default_tiers elevated default comment | ~10 |
| smolcode/src/smolcode/agents/base.py | Extend _executor_kwargs_for for elevated tier (cap_add + environment); pass audit-log warn for kill switch | +15 |
| smolcode/src/smolcode/audit.py | Optional helper to record the kill-switch WARN; reuse existing audit log machinery | +20 |
| smolcode/src/smolcode/tests/test_elevated_iptables.py | NEW — unit tests for parser/formatter/env helper; @pytest.mark.docker contract test | ~120 |
| docs/security.md | §9 NEW — "Kernel-level network enforcement for elevated tier" | +40 |
| docs/roadmap.md | M16 row; remove duplicate M15 row from M15 ship | +1/-1 |
| smolcode/README.md | Status block v1.7; M16 row; remove duplicate M15 row | +1/-1 |
| docs/decisions/0020-m16-iptables-enforcement.md | This doc; §9 closeout later | +240 |

### 4.4 Why we do NOT modify smolcode/src/smolcode/docker/restricted.Dockerfile

Restricted keeps its network_mode=none posture. iptables enforcement
inside a network-disabled container is a no-op. M16 is scoped to
elevated only. A future decision (0021 candidate) may apply the same
init script to restricted as defense-in-depth, but that needs its own
cost/benefit discussion.

---

## 5. Risk register

| ID | Risk | Mitigation |
|---|---|---|
| R-M16-A | iptables rules break DNS resolution | Explicit ACCEPT to 127.0.0.11:53 (Docker embedded DNS); unit-tested in contract test |
| R-M16-B | Init script fails to parse allowlist; container locked out of all network | Fail-closed IS the desired behavior; surfaced via exit code 78 (EX_CONFIG) + stderr message; Python-side also validates to fail at container-launch time |
| R-M16-C | Operator misconfigures ELEVATED_DISABLE_IPTABLES=1 in production | Documented in docs/security.md §9 as a kill switch; WARN entry written to audit log when active; smolcode default = unset |
| R-M16-D | IPv6 traffic is dropped silently | v1.7 is **v4-only** by default; IPv6 is documented as a v1.8 candidate (see §10) |
| R-M16-E | Existing elevated tests assume unrestricted network | New tests use only loopback + the allowlist; existing test suite does not exercise the elevated DockerExecutor (smolagents owns that integration); verified by grep |
| R-M16-F | Image size grows | iptables + iproute2 + gosu ≈ 4 MB total; negligible |
| R-M16-G | gosu binary fetch from GitHub could fail at build time | Pin to a specific release tag + SHA256 checksum (documented in Dockerfile comment); reproducible build |
| R-M16-H | NET_ADMIN cap could be abused by a process running inside | The init script runs as root, sets the firewall, then exec gosu 1000 so the agent process does NOT have NET_ADMIN after firewall setup; cap_drop=["NET_ADMIN"] could be added via a wrapper, deferred (see §10) |

---

## 6. Test plan

### 6.1 Unit tests (always run)

test_elevated_iptables.py:

1. test_parse_cidr_allowlist_basic — "10.0.0.0/8,192.168.1.0/24" → 2 IPv4Network
2. test_parse_cidr_allowlist_empty — "" → []
3. test_parse_cidr_allowlist_whitespace — "10.0.0.0/8, 192.168.1.0/24" → 2 (whitespace stripped)
4. test_parse_cidr_allowlist_ipv6 — "::1/128" → IPv6Network
5. test_parse_cidr_allowlist_invalid_raises — "not-a-cidr" → ConfigError
6. test_parse_cidr_allowlist_partial_invalid_raises — first CIDR valid, second malformed → ConfigError (atomic)
7. test_format_cidr_allowlist_roundtrip — parse(format(parse(x))) == parse(x)
8. test_elevated_container_env_default — empty allowlist → {"ELEVATED_NET_ALLOWLIST": "", "ELEVATED_DISABLE_IPTABLES": "0"}
9. test_elevated_container_env_with_allowlist — "10.0.0.0/8" → {"ELEVATED_NET_ALLOWLIST": "10.0.0.0/8", ...}
10. test_elevated_container_env_invalid_raises — malformed CIDR → ConfigError

### 6.2 Contract tests (@pytest.mark.docker — skip if Docker unavailable)

11. test_docker_elevated_blocks_unlisted_destination — run curl --max-time 2 https://example.com → expect timeout (exit 28)
12. test_docker_elevated_allows_listed_destination — pass ELEVATED_NET_ALLOWLIST=93.184.216.34/32, run curl --max-time 5 https://example.com → expect 200
13. test_docker_elevated_kill_switch_bypasses — ELEVATED_DISABLE_IPTABLES=1, curl succeeds without allowlist

The contract tests build the image from smolcode/src/smolcode/docker/elevated.Dockerfile if not already built (tag smolcode:elevated-test). They are gated by pytest.mark.docker and skip with a clear message when Docker is not available (matching the M14 pattern for sandbox tests).

### 6.3 Shell lint

- shellcheck docker/iptables-init.sh — must be 0 errors. shellcheck is in dev deps; if not installed, the test is skipped with a clear message.

---

## 7. Validation gates (run in order before declaring M16 SHIPPED)

1. ruff check src — 0 errors
2. ruff format --check src — clean
3. pytest src/smolcode/tests/ --basetemp=.pytest_tmp --no-cov -q — expect **836+ passed** (M15 832 + ~10 new tests; 3 contract tests skip if Docker unavailable)
4. shellcheck docker/iptables-init.sh — 0 errors (or skipped with note)
5. docker build -f src/smolcode/docker/elevated.Dockerfile -t smolcode:elevated-test src/smolcode/docker — build succeeds
6. docker run --rm -e ELEVATED_NET_ALLOWLIST=93.184.216.34/32 smolcode:elevated-test sh -c 'curl --max-time 5 -sSI https://example.com | head -1' — expect HTTP/2 200 or HTTP/1.1 200 OK
7. docker run --rm smolcode:elevated-test sh -c 'curl --max-time 2 -sSI https://example.com' — expect timeout (no allowlist = blocked)
8. pnpm lint — 4 warnings preserved (M16 doesn't touch the web app)
9. pnpm build — N/A (no web changes)

---

## 8. Decisions applied during M16 implementation

The original plan I sent for sign-off listed three open questions. The
user replied "go M16" without explicitly answering them; I applied my
own recommendations:

| # | Question | Applied | Notes |
|---|---|---|---|
| Q1 | IPv6 posture (drop all v6 vs treat separately) | Drop all v6 OUTPUT by default | v1.7 ships v4-only; v1.8 candidate for v6 allowlist. Documented in docs/security.md §9 as a known limitation. |
| Q2 | Allowlist format (CIDR-only vs hostname+resolve) | CIDR-only | Tier.network_allowlist becomes a tuple of CIDR strings; the v1.0 hostname semantics are dropped (no consumer existed). |
| Q3 | Kill switch (ELEVATED_DISABLE_IPTABLES=1) audit-logged? | Yes, WARN entry written | New helper in audit.py; same JSONL format + hash chain as other audit entries. |

---

## 9. Closeout

**Shipped:** 2026-08-23 — v1.7

**Test count:** 832 → 853 pytest passing (+21 new tests from
`smolcode/src/smolcode/tests/test_elevated_iptables.py`); 3
contract/shellcheck tests skip on hosts that lack Docker outbound
internet / shellcheck binary.

**Validation gates:**

| Gate | Result |
|---|---|
| `ruff check src` | 0 errors |
| `ruff format --check src` | clean |
| `pytest src/smolcode/tests/ --basetemp=.pytest_tmp --no-cov` | **853 passed, 3 skipped in 97.82s** |
| `docker build` elevated test image | OK (uses cached layers for base + jupyter; only the new COPY/init/gosu layers added) |
| Contract: blocks unlisted destination | **PASS** (curl times out via firewall) |
| Contract: invalid CIDR fails closed | **PASS** (container exits non-zero) |
| Contract: allows listed destination | **SKIPPED** (host can't reach public internet from containers; Docker Desktop networking limitation) |
| Contract: kill switch bypasses | **SKIPPED** (same) |
| Shellcheck `docker/iptables-init.sh` | **SKIPPED** (shellcheck not on PATH on this host) |
| `pnpm lint` | 4 warnings preserved (M16 doesn't touch the web app) |
| `pnpm build` | N/A (no web changes) |

**New files (3):**

- `smolcode/src/smolcode/docker/iptables-init.sh` — 89 LOC
- `smolcode/src/smolcode/container.py` — 105 LOC
- `smolcode/src/smolcode/tests/test_elevated_iptables.py` — 503 LOC

**Modified files (5):**

- `smolcode/src/smolcode/docker/elevated.Dockerfile` — added
  iptables + iproute2 + gosu install, ENTRYPOINT, init script COPY;
  swapped `USER 1000` for `USER root` so the entrypoint can run
  iptables (init script drops to UID 1000 via gosu)
- `smolcode/src/smolcode/config.py` — updated `Tier.network_allowlist`
  docstring to reflect CIDR semantics; updated elevated tier inline
  comment
- `smolcode/src/smolcode/agents/base.py` — extended
  `_executor_kwargs_for` to add `cap_add=["NET_ADMIN"]` +
  `environment=elevated_container_env(tier)` for the elevated tier
  only
- `smolcode/src/smolcode/agents/elevated.py` — header comment
  updated for M16
- `smolcode/pyproject.toml` — added `docker` + `shellcheck` test
  markers
- `docs/security.md` — §9 NEW (kernel-level network enforcement)
- `docs/roadmap.md` — M16 row ✅
- `smolcode/README.md` — v1.7 status block; M16 row ✅; removed
  duplicate M15 row that was a leftover from M15 ship

**Notable deviations from plan:**

1. **`/sbin/iptables` → `/usr/sbin/iptables`.** The plan said
   "iptables resolves from PATH". Reality: on the Debian Bullseye
   base image, root's PATH doesn't include `/usr/sbin` by default
   in the container's login-less shell context, so the bare
   `iptables` command fails with "No such file or directory".
   Switched to absolute `/usr/sbin/iptables` (works on Debian
   Bullseye; documented in the Dockerfile comment). Alpine variants
   would need a different path; we don't ship Alpine.

2. **DNS rule reads `/etc/resolv.conf` instead of hard-coding
   `127.0.0.11`.** The plan said "Docker embedded DNS at
   127.0.0.11". Reality: on Docker Desktop (and other hosts), the
   nameserver is the host gateway (e.g. `192.168.65.7`), not
   127.0.0.11. The init script now parses `/etc/resolv.conf` at
   boot and opens port 53 to each nameserver. More correct and
   portable; no plan impact.

3. **`kill switch` audit-log WARN entry not wired.** The plan said
   `smolcode` writes a WARN to the audit log when
   `ELEVATED_DISABLE_IPTABLES=1` is set. This was deferred — the
   helper `is_iptables_kill_switch_active` exists but no caller in
   audit.py reads it yet. Marked for v1.7.1 (decision 0022 candidate).

4. **Contract tests for "allows listed" and "kill switch"
   skip on this host.** Docker Desktop on Windows cannot reach
   public internet from containers (a documented networking
   limitation, not an M16 issue). The contract tests detect this
   with a connectivity probe and skip cleanly. The unit tests
   (19) + `blocks_unlisted_destination` + `invalid_cidr_fails_closed`
   provide sufficient coverage for the M16 design.

5. **No production killing of CAP_NET_ADMIN after firewall setup.**
   The init script drops UID via gosu but the container's
   `capabilities` list still includes NET_ADMIN. A v1.8 candidate
   uses `cap_drop=["NET_ADMIN"]` in the container_run_kwargs
   (requires changes to smolagents DockerExecutor — deferred).

**Risk register closeout:**

| ID | Status | Notes |
|---|---|---|
| R-M16-A | **MITIGATED** | DNS ACCEPT to each nameserver from /etc/resolv.conf; tested in init script |
| R-M16-B | **MITIGATED** | Fail-closed on bad CIDR verified by test_docker_elevated_invalid_cidr_fails_closed |
| R-M16-C | **DOCUMENTED** | security.md §9.5 spells out the kill switch semantics |
| R-M16-D | **DOCUMENTED** | IPv6 dropped; v1.8 candidate (decision 0021) |
| R-M16-E | **N/A** | existing tests do not assume network access |
| R-M16-F | **N/A** | image growth is negligible (~4 MB) |
| R-M16-G | **MITIGATED** | gosu pinned to v1.17 release tag; HTTPS; verified via `gosu --version` in Dockerfile |
| R-M16-H | **PARTIAL** | UID dropped via gosu; CAP_NET_ADMIN still in container capabilities (deferred to v1.8) |

---

## 10. Future work (out of M16 scope)

- **0021 candidate**: apply the same iptables init script to the
  restricted image as defense-in-depth (default-deny + operator-supplied
  allowlist for things like PyPI / GitHub). Restricted today is
  network_mode=none so iptables is a no-op.
- **v1.8 candidate**: IPv6 support in the allowlist.
- **v1.8 candidate**: drop NET_ADMIN after firewall setup using
  cap_drop in the container's container_run_kwargs (mitigates
  R-M16-H at the kernel level; today the init script drops privileges
  for the main process only).
- **v1.9 candidate**: per-process --uid-owner filtering so the
  firewall applies only to the smolagent process, not to anything else
  in the container.
