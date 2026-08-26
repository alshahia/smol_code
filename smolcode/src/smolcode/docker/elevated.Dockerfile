# smolcode elevated-tier sandbox image (M4 + M16).
#
# Built once per repo by `make docker-elevated` (or by the DockerExecutor
# itself on first run, per smolagents/remote_executors.py:595-604).
#
# Compared to restricted.Dockerfile, this image adds:
#   - git, curl, jq, make  (matches elevated tier command allowlist)
#   - pip is available via the python base image (no extra install needed)
#
# M16 (decision 0020) further adds:
#   - iptables + iproute2 + gosu (for kernel-level network enforcement)
#   - ENTRYPOINT = iptables-init.sh
#     -- reads ELEVATED_NET_ALLOWLIST (comma-separated CIDRs) from env,
#     -- applies default-deny OUTPUT + explicit ACCEPT rules for the
#        allowlist (plus loopback + Docker embedded DNS at 127.0.0.11),
#     -- drops privileges to UID 1000 (smolagent) via gosu, then execs
#        the original CMD (jupyter kernelgateway).
#   - The container must be launched with cap_add=["NET_ADMIN"] for the
#     firewall to take effect; smolcode does this in
#     agents/base.py:_executor_kwargs_for (elevated tier only).
#
# v1.7 network posture (M16) + v1.9.x IPv6 followup (decision 0034):
#   - default-deny OUTPUT chain on iptables (IPv4)
#   - default-deny OUTPUT chain on ip6tables (IPv6): closes the v1.7 gap
#     where the elevated container's IPv6 egress was unrestricted (the
#     default ip6tables policy is ACCEPT on Debian Bullseye, so without
#     this rule an elevated agent could leak IPv6 packets freely). Both
#     chains are configured by the ENTRYPOINT script below.
#   - loopback ACCEPT on both chains (::1 + 127.0.0.1)
#   - DNS (resolvers from /etc/resolv.conf) ACCEPT on both chains;
#     only the v4 rules apply to v4 nameservers and only v6 rules to v6
#   - ESTABLISHED,RELATED ACCEPT on both chains (return traffic)
#   - per-CIDR ACCEPT from ELEVATED_NET_ALLOWLIST (CIDR-only; no
#     hostnames); IPv4 entries apply to iptables, IPv6 entries to
#     ip6tables. The Python-side container.classify_cidrs() (added in
#     decision 0034) splits the allowlist on parse so each chain only
#     sees its family.
#   - ELEVATED_DISABLE_IPTABLES=1 is a documented kill switch; when set,
#     the init script skips firewall setup (BOTH chains) and emits a WARN
#     to stderr (smolcode also writes a WARN entry to the audit log when
#     set).
#
# Hardening (same as restricted):
#   - non-root user (smolagent, UID 1000) for the agent process
#   - no SSH / no docker CLI / no kubectl in this image
#   - elevated import allowlist is enforced by smolagents
#     LocalPythonExecutor inside the container, not by this image
#
# IMPORTANT: The image's ENTRYPOINT runs as ROOT (last USER directive is
# USER root, right before ENTRYPOINT) so it can invoke iptables. The
# init script then drops to UID 1000 via gosu before exec'ing the CMD.
# If the container is launched without cap_add=["NET_ADMIN"], the
# iptables commands fail and the init script exits non-zero.

FROM python:3.12-bullseye

# Jupyter kernel gateway is required by smolagents DockerExecutor
RUN pip install --no-cache-dir \
    jupyter_kernel_gateway \
    jupyter_client \
    ipykernel

# Elevated-tier extras: git, curl, jq, make. These match the
# elevated tier's command allowlist in smolcode/config.py.
# M16: also install iptables + iproute2 for the init script.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git \
        curl \
        jq \
        make \
        iptables \
        iproute2 \
        ca-certificates \
        wget \
    && rm -rf /var/lib/apt/lists/*

# M16: install gosu (used to drop from root -> UID 1000 after the
# firewall setup). gosu is a tiny static binary; we pin to a specific
# release tag and verify the download succeeded by running --version.
ARG GOSU_VERSION=1.17
RUN set -eux; \
    ARCH=$(dpkg --print-architecture); \
    echo "Fetching gosu ${GOSU_VERSION} for ${ARCH}"; \
    wget -O /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/${GOSU_VERSION}/gosu-${ARCH}"; \
    chmod +x /usr/local/bin/gosu; \
    /usr/local/bin/gosu --version; \
    rm -rf /var/lib/apt/lists/*

# M16: copy the iptables init script (root-owned, executable).
COPY iptables-init.sh /usr/local/bin/iptables-init.sh
RUN chmod +x /usr/local/bin/iptables-init.sh

# Create a non-root user; the runtime executes model-written code as this uid
RUN useradd --create-home --shell /bin/bash --uid 1000 smolagent

# ENTRYPOINT must run as ROOT for iptables (CAP_NET_ADMIN is also needed;
# smolcode adds it via cap_add=["NET_ADMIN"] in container_run_kwargs).
# The init script drops to UID 1000 via gosu before exec'ing the CMD, so
# the agent process itself never runs as root.
# WORKDIR is set AFTER the user is created so /home/smolagent exists.
USER root
WORKDIR /home/smolagent
ENV PATH=/home/smolagent/.local/bin:$PATH

EXPOSE 8888
ENTRYPOINT ["/usr/local/bin/iptables-init.sh"]
CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888"]
