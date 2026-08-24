#!/bin/bash
# iptables-init.sh -- M16 (decision 0020) kernel-level network enforcement
# for the elevated tier. Runs as root inside the container (PID 1).
#
# Reads ELEVATED_NET_ALLOWLIST (comma-separated CIDRs) and applies
# default-deny OUTPUT + explicit ACCEPT rules. Then drops to the
# non-root smolagent user (UID 1000) via gosu and execs the agent.
#
# Kill switch: ELEVATED_DISABLE_IPTABLES=1 bypasses the firewall setup
# entirely. Use of this switch MUST be logged by the Python side
# (smolcode writes a WARN entry to the audit log when set).

set -euo pipefail

# --- 0. Kill switch ---------------------------------------------------------

if [[ "${ELEVATED_DISABLE_IPTABLES:-0}" == "1" ]]; then
    echo "[iptables-init] WARNING: ELEVATED_DISABLE_IPTABLES=1; firewall NOT applied" >&2
    exec /usr/local/bin/gosu 1000:1000 "$@"
fi

# --- 1. Parse + validate allowlist -----------------------------------------

ALLOWLIST="${ELEVATED_NET_ALLOWLIST:-}"

# Default-deny OUTPUT first; this is the fail-closed baseline.
# Resolve iptables from PATH; on Debian Bullseye+ this is /usr/sbin/iptables
# (the python:3.12-bullseye base image merged /sbin -> /usr/sbin). Using
# PATH resolution makes the script portable across Debian/Ubuntu/Alpine
# variants without hard-coding the absolute path.
/usr/sbin/iptables -P OUTPUT DROP

# Loopback must always work (inter-process comms, jupyter kernel socket).
/usr/sbin/iptables -A OUTPUT -o lo -j ACCEPT

# DNS to the resolvers listed in /etc/resolv.conf. On Linux Docker
# the embedded DNS is 127.0.0.11; on Docker Desktop and other hosts
# the nameserver may be the host gateway (e.g. 192.168.65.7). We
# parse resolv.conf at init time so we follow whatever Docker injected.
NAMESERVERS=$(awk '/^nameserver[[:space:]]+/{ print $2 }' /etc/resolv.conf 2>/dev/null)
for ns in $NAMESERVERS; do
    /usr/sbin/iptables -A OUTPUT -p udp --dport 53 -d "$ns" -j ACCEPT
    /usr/sbin/iptables -A OUTPUT -p tcp --dport 53 -d "$ns" -j ACCEPT
done

# Established/related return traffic (so established connections reply).
/usr/sbin/iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# --- 2. Apply operator-supplied allowlist -----------------------------------

if [[ -n "$ALLOWLIST" ]]; then
    # Validate every CIDR before applying the first rule; fail-closed on
    # the first invalid entry. We use python3 (always available in the
    # python:3.12 base image) rather than depending on iptables-CIDR-
    # parsing semantics, so the validation matches the Python-side check.
    IFS=',' read -ra CIDRS <<< "$ALLOWLIST"
    for cidr_raw in "${CIDRS[@]}"; do
        # Strip whitespace.
        cidr=$(echo -n "$cidr_raw" | tr -d ' 	')
        [[ -z "$cidr" ]] && continue
        if ! python3 -c "import ipaddress,sys; ipaddress.ip_network(sys.argv[1], strict=False); print('ok')" "$cidr" >/dev/null 2>&1; then
            echo "[iptables-init] FATAL: invalid CIDR in ELEVATED_NET_ALLOWLIST: '$cidr'" >&2
            echo "[iptables-init] no allowlist rules applied; container locked to loopback + DNS" >&2
            exit 78  # EX_CONFIG (sysexits.h)
        fi
    done
    # All CIDRs valid; apply the ACCEPT rules.
    for cidr_raw in "${CIDRS[@]}"; do
        cidr=$(echo -n "$cidr_raw" | tr -d ' 	')
        [[ -z "$cidr" ]] && continue
        /usr/sbin/iptables -A OUTPUT -d "$cidr" -j ACCEPT
    done
    echo "[iptables-init] firewall active; allowlist=$ALLOWLIST" >&2
else
    echo "[iptables-init] firewall active; allowlist=<empty> (loopback + DNS only)" >&2
fi

# --- 3. Drop to non-root + exec the agent -----------------------------------

# Dump applied OUTPUT chain rules to stderr for operator debugging.
# Comment out SMOLCODE_QUIET_INIT=1 to suppress this dump.
if [[ "${SMOLCODE_QUIET_INIT:-0}" != "1" ]]; then
    echo "[iptables-init] applied OUTPUT chain:" >&2
    /usr/sbin/iptables -L OUTPUT -n -v --line-numbers >&2 || true
fi

# gosu is at /usr/local/bin/gosu (installed by elevated.Dockerfile).
# UID 1000 matches the smolagent user created by the Dockerfile.
exec /usr/local/bin/gosu 1000:1000 "$@"