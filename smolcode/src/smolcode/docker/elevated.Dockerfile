# smolcode elevated-tier sandbox image (M4 + M16 + Phase 1 C2).
#
# Built/refreshed automatically by smolcode.images.ensure_tier_images()
# (boot-time), or manually: make docker-images /
# python -m smolcode.images ensure --tier elevated.
#
# Compared to restricted.Dockerfile, this image adds:
#   - git, curl, jq, make        (matches elevated command allowlist)
#   - nodejs + npm               (matches elevated allowlist: node, npm)
#   - pytest + ruff              (matches elevated allowlist)
#   - pip via the python base image
#
# M16 (decision 0020) adds kernel-level network enforcement:
#   - iptables + iproute2 + gosu (for the ENTRYPOINT firewall)
#   - ENTRYPOINT = iptables-init.sh: reads ELEVATED_NET_ALLOWLIST
#     (comma-separated CIDRs), applies default-deny OUTPUT on BOTH
#     iptables (v4) and ip6tables (v6) incl. ICMPv6 NDP/PMTUD
#     allowances, then drops privileges to UID 1000 via gosu and execs
#     the CMD. Requires cap_add=["NET_ADMIN"] at launch (smolcode sets
#     it in agents/base.py:_executor_kwargs_for, elevated tier only).
#
# Hardening:
#   - agent process runs as non-root (smolagent, UID 1000); only the
#     short-lived init runs as root
#   - no SSH / no docker CLI / no kubectl in this image

ARG PYTHON_BASE=3.12-bullseye
# Pin note: convert to a digest pin (python@sha256:<digest>) for
# supply-chain hardening; obtain the digest via
# docker image inspect --format "{{index .RepoDigests 0}}" python:3.12-bullseye
FROM python:${PYTHON_BASE}

# Jupyter kernel gateway required by smolagents DockerExecutor;
# pytest + ruff are advertised in the elevated command allowlist.
RUN pip install --no-cache-dir \
    jupyter_kernel_gateway \
    jupyter_client \
    ipykernel \
    pytest \
    ruff

# Elevated-tier extras matching config.py elevated.commands exactly.
# M16: iptables + iproute2 for the init script; ca-certificates for TLS;
# wget + gnupg needed below for gosu verification (Phase 1 C2).
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git \
        curl \
        jq \
        make \
        nodejs \
        npm \
        iptables \
        iproute2 \
        ca-certificates \
        wget \
        gnupg \
    && rm -rf /var/lib/apt/lists/*

# M16: gosu drops root -> UID 1000 after firewall setup. Phase 1 (C2):
# signature-verified against the upstream release (tianon/gosu README
# procedure; signing key B42F6819007F00F88E364FD4036A9C25BF357DD4),
# replacing the previous download-and-hope verification.
ARG GOSU_VERSION=1.17
RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    wget -O /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/${GOSU_VERSION}/gosu-${ARCH}"; \
    wget -O /usr/local/bin/gosu.asc "https://github.com/tianon/gosu/releases/download/${GOSU_VERSION}/gosu-${ARCH}.asc"; \
    export GNUPGHOME="$(mktemp -d)"; \
    gpg --batch --keyserver hkps://keys.openpgp.org --recv-keys B42F6819007F00F88E364FD4036A9C25BF357DD4; \
    gpg --batch --verify /usr/local/bin/gosu.asc /usr/local/bin/gosu; \
    gpgconf --kill all; \
    rm -rf "$GNUPGHOME" /usr/local/bin/gosu.asc; \
    chmod +x /usr/local/bin/gosu; \
    /usr/local/bin/gosu --version; \
    gosu nobody true 2>/dev/null || true

# M16: copy the iptables init script (root-owned, executable).
COPY iptables-init.sh /usr/local/bin/iptables-init.sh
RUN chmod +x /usr/local/bin/iptables-init.sh

# Non-root user for the agent process itself.
RUN useradd --create-home --shell /bin/bash --uid 1000 smolagent

# ENTRYPOINT runs as ROOT so it can invoke iptables (with NET_ADMIN);
# the init script drops to UID 1000 before exec'ing CMD.
USER root
WORKDIR /home/smolagent
ENV PATH=/home/smolagent/.local/bin:$PATH

EXPOSE 8888
ENTRYPOINT ["/usr/local/bin/iptables-init.sh"]
CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888"]
