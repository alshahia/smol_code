#!/bin/bash
# iptables-init.sh -- M16 (decision 0020) kernel-level network enforcement
# for the elevated tier, extended in decision 0034 with parallel ip6tables
# rules so IPv6 egress is also default-deny + per-CIDR allowlist.
# Runs as root inside the container (PID 1).
#
# Reads ELEVATED_NET_ALLOWLIST (comma-separated CIDRs) and applies:
#   - iptables (IPv4):
#       -P OUTPUT DROP
#       -A OUTPUT -o lo -j ACCEPT
#       -A OUTPUT -p udp --dport 53 -d <nameserver> -j ACCEPT   (each v4 NS)
#       -A OUTPUT -p tcp --dport 53 -d <nameserver> -j ACCEPT   (each v4 NS)
#       -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
#       -A OUTPUT -d <each v4 CIDR in allowlist> -j ACCEPT
#   - ip6tables (IPv6):
#       -P OUTPUT DROP
#       -A OUTPUT -o lo -j ACCEPT
#       -A OUTPUT -p udp --dport 53 -d <each v6 nameserver> -j ACCEPT
#       -A OUTPUT -p tcp --dport 53 -d <each v6 nameserver> -j ACCEPT
#       -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
#       -A OUTPUT -d <each v6 CIDR in allowlist> -j ACCEPT
# Then drops to the non-root smolagent user (UID 1000) via gosu and execs
# the agent. The kill switch ELEVATED_DISABLE_IPTABLES=1 bypasses both
# chains (and the Python side writes a WARN entry to the audit log).

set -euo pipefail

# --- 0. Kill switch ---------------------------------------------------------

if [[ "${ELEVATED_DISABLE_IPTABLES:-0}" == "1" ]]; then
    echo "[iptables-init] WARNING: ELEVATED_DISABLE_IPTABLES=1; firewall NOT applied" >&2
    exec /usr/local/bin/gosu 1000:1000 "$@"
fi

# --- 1. Resolve binaries ----------------------------------------------------
# On Debian Bullseye+ both iptables and ip6tables live at /usr/sbin (the
# python:3.12-bullseye base image merged /sbin -> /usr/sbin). Using absolute
# paths keeps the script portable across Debian/Ubuntu/Alpine variants.

IPT=/usr/sbin/iptables
IP6T=/usr/sbin/ip6tables

if [[ ! -x "$IPT" ]]; then
    echo "[iptables-init] FATAL: $IPT not found or not executable" >&2
    exit 78  # EX_CONFIG
fi
if [[ ! -x "$IP6T" ]]; then
    echo "[iptables-init] FATAL: $IP6T not found or not executable (cannot enforce IPv6)" >&2
    exit 78  # EX_CONFIG
fi

# --- 2. Validate every CIDR in the allowlist BEFORE touching either chain ----
# Fail-closed: if any CIDR is malformed we exit 78 and never apply a partial
# firewall (so the operator can fix the config without chasing a half-applied
# state across both iptables and ip6tables).

ALLOWLIST="${ELEVATED_NET_ALLOWLIST:-}"

declare -a V4_CIDRS=()
declare -a V6_CIDRS=()

if [[ -n "$ALLOWLIST" ]]; then
    IFS=',' read -ra CIDRS <<< "$ALLOWLIST"
    for cidr_raw in "${CIDRS[@]}"; do
        # Strip whitespace.
        cidr=$(echo -n "$cidr_raw" | tr -d ' \t')
        [[ -z "$cidr" ]] && continue
        # Validate via python3 (always available in python:3.12 base image) so
        # we use the same parser as the Python-side helper container.py.
        class=$(python3 -c "
import ipaddress, sys
n = ipaddress.ip_network(sys.argv[1], strict=False)
print('v4' if n.version == 4 else 'v6')
" "$cidr" 2>/dev/null) || {
            echo "[iptables-init] FATAL: invalid CIDR in ELEVATED_NET_ALLOWLIST: '$cidr'" >&2
            echo "[iptables-init] no allowlist rules applied; container locked to loopback + DNS" >&2
            exit 78  # EX_CONFIG
        }
        if [[ "$class" == "v4" ]]; then
            V4_CIDRS+=("$cidr")
        else
            V6_CIDRS+=("$cidr")
        fi
    done
fi

# --- 3. IPv4 (iptables) chain ----------------------------------------------
# Default-deny OUTPUT first; this is the fail-closed baseline.

"$IPT" -P OUTPUT DROP

# Loopback must always work (inter-process comms, jupyter kernel socket).
"$IPT" -A OUTPUT -o lo -j ACCEPT

# DNS to the resolvers listed in /etc/resolv.conf. On Linux Docker the
# embedded DNS is 127.0.0.11; on Docker Desktop and other hosts the
# nameserver may be the host gateway (e.g. 192.168.65.7). We parse
# resolv.conf at init time so we follow whatever Docker injected.
NAMESERVERS_V4=$(awk '/^nameserver[[:space:]]+/{ print $2 }' /etc/resolv.conf 2>/dev/null)
for ns in $NAMESERVERS_V4; do
    # Only apply v4 rules to v4 nameservers. python3 -c ipaddress.version
    # returns 4 for dotted-quad and 6 for colon-hex.
    ns_class=$(python3 -c "
import ipaddress, sys
try:
    print('v' + str(ipaddress.ip_address(sys.argv[1]).version))
except ValueError:
    pass
" "$ns" 2>/dev/null || true)
    if [[ "$ns_class" == "v4" ]]; then
        "$IPT" -A OUTPUT -p udp --dport 53 -d "$ns" -j ACCEPT
        "$IPT" -A OUTPUT -p tcp --dport 53 -d "$ns" -j ACCEPT
    fi
done

# Established/related return traffic (so established connections reply).
"$IPT" -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Apply operator-supplied v4 allowlist.
for cidr in "${V4_CIDRS[@]}"; do
    "$IPT" -A OUTPUT -d "$cidr" -j ACCEPT
done

# --- 4. IPv6 (ip6tables) chain ----------------------------------------------
# Mirrors the v4 chain. Default-deny IPv6 OUTPUT (ip6tables policy is ACCEPT
# by default on Debian Bullseye, so without this the elevated container's
# IPv6 egress would be unrestricted; this was the v1.7 gap closed in
# decision 0034).

"$IP6T" -P OUTPUT DROP

# Loopback (::1).
"$IP6T" -A OUTPUT -o lo -j ACCEPT

# Phase 1 (H1 fix): ICMPv6 control traffic must traverse even a
# default-deny OUTPUT chain or IPv6 breaks subtly:
#   type 2    = Packet Too Big (PMTUD; without it large v6 packets black-hole)
#   type 133/134 = Router Solicitation / Advertisement
#   type 135/136 = Neighbor Solicitation / Advertisement (NDP)
# These are link-local control messages, not application egress.
for icmp_type in 2 133 134 135 136; do
    "$IP6T" -A OUTPUT -p ipv6-icmp --icmpv6-type "$icmp_type" -j ACCEPT
done

# DNS to v6 nameservers from /etc/resolv.conf.
for ns in $NAMESERVERS_V4; do
    ns_class=$(python3 -c "
import ipaddress, sys
try:
    print('v' + str(ipaddress.ip_address(sys.argv[1]).version))
except ValueError:
    pass
" "$ns" 2>/dev/null || true)
    if [[ "$ns_class" == "v6" ]]; then
        "$IP6T" -A OUTPUT -p udp --dport 53 -d "$ns" -j ACCEPT
        "$IP6T" -A OUTPUT -p tcp --dport 53 -d "$ns" -j ACCEPT
    fi
done

# Established/related return traffic for v6 connections.
"$IP6T" -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Apply operator-supplied v6 allowlist.
for cidr in "${V6_CIDRS[@]}"; do
    "$IP6T" -A OUTPUT -d "$cidr" -j ACCEPT
done

# --- 5. Log + drop privileges ----------------------------------------------

if [[ "${SMOLCODE_QUIET_INIT:-0}" != "1" ]]; then
    echo "[iptables-init] firewall active (v4 + v6 default-deny OUTPUT)" >&2
    v4_summary="${V4_CIDRS[*]:-<none>}"
    v6_summary="${V6_CIDRS[*]:-<none>}"
    echo "[iptables-init] allowlist v4=${v4_summary} v6=${v6_summary}" >&2
    echo "[iptables-init] applied iptables OUTPUT chain:" >&2
    "$IPT" -L OUTPUT -n -v --line-numbers >&2 || true
    echo "[iptables-init] applied ip6tables OUTPUT chain:" >&2
    "$IP6T" -L OUTPUT -n -v --line-numbers >&2 || true
fi

# gosu is at /usr/local/bin/gosu (installed by elevated.Dockerfile).
# UID 1000 matches the smolagent user created by the Dockerfile.
exec /usr/local/bin/gosu 1000:1000 "$@"
