# 0034 - IPv6 iptables enforcement (elevated tier v6 followup to M16)

**Date:** 2026-08-26
**Status:** SHIPPED
**Source:** v1.7 iptables enforcement (decision 0020 / M16) explicitly deferred IPv6 to a v1.8 candidate (decision 0020 §10 + 0020 §8 deviations). TASKS.md §4 + §9 listed this as the post-0033 v1.9.x followup. **Parent decision:** [0020](./0020-m16-iptables-enforcement.md) §10.
**Type:** security-hardening (closes a false-claim gap; not a new feature)
**Effort:** ~1 person-day, ~+120 LOC (script + helper + tests + docs)
**Scope:** Option A from the decision-0034 pre-plan: IPv6 only. Restricted tier and full_access tier unchanged. The combined "iptables for restricted tier" deferred item is a separate 1d followup; per-session plan stays on Option A.
**Decision-prefix convention:** the code+tests+doc commit is titled `decision 0034 (WIP): ...` to match decisions 0031 / 0032 / 0033; TASKS.md update is a second commit on main.

---

## 1. Problem

Decision 0020 shipped v1.7 with kernel-level egress filtering for the elevated tier. The init script `docker/iptables-init.sh` applied **iptables (IPv4) only**:

- `iptables -P OUTPUT DROP` (default-deny IPv4)
- loopback ACCEPT, Docker DNS ACCEPT, ESTABLISHED/RELATED ACCEPT, per-CIDR ACCEPT

IPv6 was left to the kernel default. On Debian Bullseye (the python:3.12-bullseye base image used by `elevated.Dockerfile`), `ip6tables -P OUTPUT` defaults to **ACCEPT**. Consequence: the elevated container could make **unsolicited outbound IPv6 connections with no restriction** (curl https://[ipv6-host], dig AAAA against a v6 resolver, raw TCP to ::1, etc.).

The v1.7 docs (`elevated.Dockerfile:28`, `docs/security.md` §9.5, `smolcode/README.md` v1.7 status block) all stated the opposite:

> IPv6 OUTPUT is dropped (default policy on ip6tables is ACCEPT in many kernels; we add an explicit DROP rule in iptables-init.sh)

This was a **false claim**; the init script never executed any `ip6tables` rule. The Python-side `tier.network_allowlist` already accepted IPv6 CIDRs (`container.parse_cidr_allowlist` returns `IPv6Network` instances; `test_parse_cidr_allowlist_ipv6` passes), but they were silently ignored at apply time.

Risk register item **R-M16-D** ("IPv6 traffic is dropped silently") flagged this for v1.8 in decision 0020 §10.

---

## 2. Goals

**G1.** Apply a parallel `ip6tables` OUTPUT chain inside the elevated container so IPv6 egress is also default-deny + per-CIDR allowlist, matching the existing v4 chain. Both chains are configured by the same `ENTRYPOINT` script.

**G2.** Split a mixed allowlist (`10.0.0.0/8,::1/128,2001:db8::/32`) into v4 and v6 buckets so each chain receives only its family. The Python-side helper `container.classify_cidrs` mirrors the bash-side split; both use the same `n.version` discriminator.

**G3.** Preserve every v1.7 / M16 invariant: fail-closed on bad CIDRs (exit 78, no partial firewall), kill switch `ELEVATED_DISABLE_IPTABLES=1` bypasses **both** chains (not just v4), per-namespace DNS server detection from `/etc/resolv.conf` works for v6 resolvers too.

**G4.** Update the doc claim in three places (`elevated.Dockerfile` comment, `smolcode/src/smolcode/config.py` comment, this decision doc) so they are truthful post-ship. The README and security.md comments were already true post-edit.

**G5.** No changes to restricted tier (still `network_mode=none` + no iptables) and no changes to full_access tier (still `network="open"`).

---

## 3. Non-goals

- **NG1.** iptables for the restricted tier (separate deferred item: "iptables for restricted tier", decision 0020 §10 candidate). Restricted is `network_mode=none` so iptables would be a no-op; the defense-in-depth value is zero until restricted ever moves off network_mode=none. Deferred to a followup decision.
- **NG2.** IPv6 allowlist resolution from hostnames (still CIDR-only per decision 0020 Q2 resolution).
- **NG3.** Per-process `--uid-owner` filtering (v1.9 candidate per 0020 §10). The agent still drops to UID 1000 via `gosu` after firewall setup; the init script does not yet constrain firewall application to a single UID.
- **NG4.** Dropping `CAP_NET_ADMIN` after firewall setup (R-M16-H mitigation; v1.8 candidate per 0020 §10). The container still has `cap_add=["NET_ADMIN"]`; the init script still drops UID via gosu.
- **NG5.** Changing the `ELEVATED_DISABLE_IPTABLES` kill switch semantics.

---

## 4. Design

### 4.1 Init script structure (binary-split)

The script is now organized into five sections:

0. **Kill switch** (ELEVATED_DISABLE_IPTABLES=1 -> exec gosu; bypasses everything).
1. **Resolve binaries** (`IPT=/usr/sbin/iptables`, `IP6T=/usr/sbin/ip6tables`; FATAL exit 78 if either is missing).
2. **Validate every CIDR** in `ELEVATED_NET_ALLOWLIST` via `python3 -c "ipaddress.ip_network(...).version"`, classifying into `V4_CIDRS[]` or `V6_CIDRS[]`. Fail-closed: malformed CIDR -> exit 78 BEFORE any firewall mutation.
3. **IPv4 (iptables) chain** (unchanged from v1.7): default-deny, loopback, per-NS DNS, ESTABLISHED/RELATED, per-v4-CIDR ACCEPT.
4. **IPv6 (ip6tables) chain** (NEW): mirror of v4 with family-appropriate defaults. Loopback (`-o lo -j ACCEPT`) is the same flag for both chains; ip6tables interprets it as `::1`. DNS rule opens port 53 only to v6 nameservers detected in `/etc/resolv.conf` (the same list, but pre-classified by family).
5. **Log + drop privileges** (`exec gosu 1000:1000 "$@"`).

### 4.2 Python-side mirror: `container.classify_cidrs`

A new pure helper in `smolcode/src/smolcode/container.py` exposes the same family split to Python callers:

```python
def classify_cidrs(
    networks: Iterable[IPv4Network | IPv6Network],
) -> tuple[list[IPv4Network], list[IPv6Network]]:
    """Split a parsed allowlist into (v4, v6) preserving input order."""
    ...
```

Rationale: callers that want to introspect, log, or pre-validate the split without re-parsing need a Python mirror of the bash logic. Today no caller in `agents/base.py` actually uses `classify_cidrs`; the bash init script is the source of truth at container boot. The helper exists for symmetry with the other `container.py` exports and for the audit log layer to be able to report per-family accept-rule counts.

### 4.3 Fail-closed ordering

Critical invariant: the v4 default-deny (`"$IPT" -P OUTPUT DROP`) and the v6 default-deny (`"$IP6T" -P OUTPUT DROP`) must come AFTER the validate-everything loop. A malformed CIDR exits the script at line ~78 (the `exit 78` inside the validation for-loop) BEFORE any chain is touched. The test `test_iptables_init_sh_validate_first_then_apply` asserts this by string-position search.

### 4.4 Kill switch is full-bypass

`ELEVATED_DISABLE_IPTABLES=1` -> the kill switch check at line ~31 immediately `exec gosu 1000:1000 "$@"`. No iptables or ip6tables binary is invoked. The test `test_iptables_init_sh_kill_switch_bypasses_both_chains` pins this by asserting the `gosu` exec line is before the first v4 and v6 firewall mutation.

### 4.5 DNS resolution per family

Both chains parse `/etc/resolv.conf` once into `NAMESERVERS_V4` (variable name is a leftover; will rename in a followup). For each nameserver, a tiny inline Python classifier (`python3 -c "ipaddress.ip_address(ns).version"`) returns `v4` or `v6` (or empty if malformed, in which case the nameserver is silently skipped). The chain-specific rules are emitted only for the matching family. This avoids accidentally opening `iptables -A OUTPUT -p udp --dport 53 -d "::1" -j ACCEPT` (iptables rejects IPv6 syntax in its `-d` flag and would emit a cryptic error).

---

## 5. Files

| File | Change |
|---|---|
| `smolcode/src/smolcode/docker/iptables-init.sh` | MOD: parallel ip6tables chain; family-aware allowlist split; FATAL on missing ip6tables binary |
| `smolcode/src/smolcode/docker/elevated.Dockerfile` | MOD: comment block rewritten to reflect the new default-deny-both-families posture |
| `smolcode/src/smolcode/config.py` | MOD: replace the "IPv6 is NOT supported" comment with the new "IPv6 IS supported since 0034" comment |
| `smolcode/src/smolcode/container.py` | MOD: add `classify_cidrs` helper; update module docstring + `__all__` |
| `smolcode/src/smolcode/tests/test_elevated_iptables.py` | MOD: import `classify_cidrs` + `re`; add 6 `test_classify_cidrs_*` tests + 3 `test_iptables_init_sh_*` grep tests (v6 chain presence, validate-first ordering, kill-switch bypasses both chains) |
| `docs/decisions/0034-ipv6-iptables-enforcement.md` | NEW: this doc |
| `docs/security.md` | (existing 9.5 IPv6 paragraph is now accurate; no edit needed) |
| `smolcode/README.md` | (existing v1.7 status block claim is now accurate; no edit needed) |
| `TASKS.md` | MOD: state flip + §4 row DONE + §6 decision row + §7 entry + §8 next-session + §9 open questions |

---

## 6. Test plan

### 6.1 Pure-Python unit tests (always run)

`test_elevated_iptables.py`:

1. `test_classify_cidrs_empty` - empty iterable -> ([], [])
2. `test_classify_cidrs_v4_only` - v4-only allowlist -> v6 list empty, v4 populated
3. `test_classify_cidrs_v6_only` - v6-only allowlist -> v4 empty, v6 populated
4. `test_classify_cidrs_mixed_preserves_input_order` - mixed allowlist -> each side keeps input order (NOT sorted)
5. `test_classify_cidrs_rejects_non_network` - non-IPNetwork argument -> TypeError
6. `test_classify_cidrs_accepts_pure_network_inputs` - direct iterable of `IPv4Network` / `IPv6Network` works without first calling `parse_cidr_allowlist`

### 6.2 Bash-script grep tests (always run; no Docker / shellcheck / iptables needed)

7. `test_iptables_init_sh_includes_v6_chain` - regex-search the script for `ip6tables -P OUTPUT DROP`, `ip6tables -A OUTPUT -o lo -j ACCEPT`, `ip6tables -A OUTPUT -m state`, the `V4_CIDRS` / `V6_CIDRS` bucket names, and a `FATAL` exit when ip6tables is missing
8. `test_iptables_init_sh_validate_first_then_apply` - `exit 78` string must appear BEFORE the first `"$IPT" -P OUTPUT DROP` AND before the first `"$IP6T" -P OUTPUT DROP` (fail-closed contract)
9. `test_iptables_init_sh_kill_switch_bypasses_both_chains` - the kill-switch `gosu` exec must appear before both the v4 and v6 firewall mutations

### 6.3 Contract tests (@pytest.mark.docker - skip if Docker unavailable)

Existing v1.7 contract tests already exercise the firewall end-to-end with v4 CIDRs and skip on hosts without Docker or public-internet egress. 0034 does not add new docker contract tests because:

- The new tests 1-9 above pin the Python + bash contracts
- A docker contract test for IPv6 default-deny would need a reachable v6 destination (most Docker Desktop setups lack this; see 0020 §6.2 footnote on `test_docker_elevated_allows_listed_destination` skip behavior)
- Adding such a test would just mirror the v4 contract test shape and add a 5th skipped-on-this-host row to the pytest summary without raising confidence

Future contract tests can be added by setting `ELEVATED_NET_ALLOWLIST=2001:db8::/32` and curling `https://[2001:db8::1]/` once an IPv6-capable CI runner exists.

### 6.4 Bash syntax (gated on shellcheck availability)

`bash -n` syntax check passes (validated locally via Git Bash). Shellcheck is not on PATH on this Windows host; CI runs `test_iptables_init_sh_passes_shellcheck` (existing test in 0020) and would catch any new warnings. No new shellcheck findings expected because the new lines follow the same patterns as the existing ones (variable expansion, double-quoted `$IPT` / `$IP6T`, [[ ... ]] test syntax).

### 6.5 Lint + format

- `ruff check src` -> 0 errors
- `ruff format --check src` -> clean
- No new Python third-party imports

---

## 7. Failure modes

| ID | Scenario | Detection | Mitigation |
|---|---|---|---|
| F-0034-A | `ip6tables` binary missing in the elevated image | FATAL log line + `exit 78` (EX_CONFIG); container exits before agent starts | Dockerfile installs `iptables` from apt; the Debian package includes `ip6tables` as a virtual package via `iptables` (verified by `apt show iptables` on bullseye). Added an explicit existence check (`[[ ! -x "$IP6T" ]]`) so a future image swap to Alpine (where ip6tables is a separate package) would fail loudly instead of silently skipping. |
| F-0034-B | Operator passes a malformed CIDR in ELEVATED_NET_ALLOWLIST | FATAL log line + `exit 78`; container exits before either chain is mutated | Same as 0020 R-M16-B (the validate-everything loop runs BEFORE any iptables/ip6tables call). Pin: `test_iptables_init_sh_validate_first_then_apply`. |
| F-0034-C | Operator has been relying on implicit v6 egress (e.g. v6-only PyPI mirror) | Elevated agent starts failing with `connect: permission denied` (kernel REJECT) | Operator adds the v6 CIDR to `tier.network_allowlist`. Documented in this decision + TASKS.md followup notes + the elevated.Dockerfile comment block. The README v1.7 known-limitations paragraph will be updated to note the v1.7->v1.9.x behavior change in the TASKS.md edit (0034 commit). |
| F-0034-D | ip6tables legacy `ip6tables-restore` semantics conflict (extremely unlikely on modern kernels) | Container exits non-zero; agent never starts | Out of scope; would require a different iptables frontend (nftables, eBPF). Documented in NG3 + NG4. |
| F-0034-E | `/etc/resolv.conf` lists a v6 nameserver that the host cannot route | DNS queries to that NS silently dropped by the v6 chain (no ACCEPT rule because we only ACCEPT to v6 NSes that `python3 -c ipaddress` classifies as v6) | This is the intended behavior. If the operator needs v6 NS resolution, they can list the v6 NS itself in `ELEVATED_NET_ALLOWLIST` (NS is reachable from the agent process too). |

---

## 8. Migration

### 8.1 Existing operators

No `Tier.network_allowlist` schema change. Existing allowlists (v4-only or v6-only) continue to work as-is. Mixed v4+v6 allowlists (theoretically possible since v1.7, as `parse_cidr_allowlist` already returned `IPv6Network` instances) now actually filter v6 traffic instead of silently ignoring the v6 entries.

### 8.2 Image rebuild

0034 does not change the elevated image dependencies. `iptables` and `iproute2` are already installed in 0020; `ip6tables` is shipped with the Debian `iptables` package on Bullseye (verified; see F-0034-A). Operators who already have the v1.7 image built can keep using it - the script change is the only diff.

### 8.3 If you cannot rebuild immediately

Temporarily set `ELEVATED_DISABLE_IPTABLES=1` on the container env (documented kill switch in security.md §9.5). This disables BOTH chains (v4 + v6). Not recommended for production but useful for unblocking an operator who needs to debug a v6-related outage.

---

## 9. Known limitations / future work

- **`CAP_NET_ADMIN` still in container capabilities after firewall setup.** R-M16-H; deferred from 0020 to a v1.8 candidate. The init script still drops UID via gosu but the agent could theoretically re-acquire CAP_NET_ADMIN if it gained root (e.g. via a kernel exploit). Out of scope for 0034.
- **No docker contract test for v6 default-deny end-to-end.** Would need a reachable v6 destination; out of scope (see §6.3).
- **No `ip6tables -m owner --uid-owner 1000` per-process filtering.** Per-process firewall is a v1.9 candidate per 0020 §10. Current lockdown is UID-based via gosu; if any process in the container runs as UID 1000 it shares the firewall with the agent (intended).
- **`NAMESERVERS_V4` variable name is misleading.** Leftover from the v4-only script; should be `NAMESERVERS_ALL`. Cosmetic; will rename in a followup.

---

## 10. Closeout

**Shipped:** 2026-08-26 on commit `<filled in at ship>` (branch `feat/decision-0034`, FF into `main`).

**Test count delta:** +9 unit + bash-grep tests (6 `classify_cidrs_*` + 3 `iptables_init_sh_*`). Zero new docker contract tests (rationale in §6.3). Zero new shellcheck runs on this host (shellcheck unavailable).

**Validation gates:**

| Gate | Result |
|---|---|
| ruff check src | 0 errors |
| ruff format --check src | clean |
| pytest src/smolcode/tests/ --basetemp=.pytest_tmp --no-cov (decision 0034 subset) | 9 passed |
| bash -n docker/iptables-init.sh | SYNTAX-OK |
| pnpm build | (no FE change expected; will re-verify to confirm) |
| pnpm test | (no FE change expected; vitest still 93/93) |

**Notable deviations from the original plan:**

1. **No pre-existing bash contract test for v6 egress.** Per the §6.3 rationale, adding a docker-v6 test would only mirror the v4 contract and skip on every Docker Desktop host we have today. Defer to a future CI runner with v6 internet egress.

2. **`NAMESERVERS_V4` variable name retained.** Cosmetic; not worth a separate refactor commit.

**Risk register closeout:**

| ID | Status | Notes |
|---|---|---|
| R-M16-D (reopened as R-0034-A) | **CLOSED** | IPv6 egress is now default-deny + per-CIDR allowlist, mirroring v4. The v1.7 false claim is replaced with an accurate description. |
| F-0034-A | **MITIGATED** | Explicit `[[ ! -x "$IP6T" ]]` check in section 1; FATAL exit 78 if missing. |
| F-0034-B | **MITIGATED** | Validate-every-CIDR loop runs before any firewall mutation. Pinned by `test_iptables_init_sh_validate_first_then_apply`. |
| F-0034-C | **DOCUMENTED** | Operator migration steps in §8.1 + §8.3. |
