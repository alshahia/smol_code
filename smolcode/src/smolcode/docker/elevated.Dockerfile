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

# Phase 6: bumped bullseye -> bookworm (2026-09-24). See
# restricted.Dockerfile for why the bullseye base no longer builds.
# Supply-chain pin (Phase 8, decision 0043): the base image is referenced by
# DIGEST, not by tag. A tag is mutable in the registry, so a rebuild could
# silently swap the OS/interpreter under a sandbox whose policy we reviewed.
# The digest is also part of smolcode.images.source_hash(), so bumping it
# forces ensure_tier_images() to rebuild instead of reusing the old image.
#   python:3.12-bookworm@sha256:14a4933e6cef421424f7a66d89a3f4eafcbd0d90e0a822251f298e05132dc735
# Refresh procedure: pull the new digest, update this ARG, then rebuild via
#   python -m smolcode.images ensure --tier elevated
ARG PYTHON_BASE=3.12-bookworm@sha256:14a4933e6cef421424f7a66d89a3f4eafcbd0d90e0a822251f298e05132dc735
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
#
# Phase 8 (decision 0043): the GPG signature proves authenticity but the
# artifact is fetched over the network twice (binary + signature), so the
# exact upstream SHA-256 is ALSO pinned per architecture. If a release asset
# is ever re-uploaded or a mirror serves a different file, the build fails
# instead of installing it. Values were computed from the official v1.17
# release assets (`sha256sum gosu-<arch>`).
ARG GOSU_VERSION=1.17
RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "$ARCH" in \
        amd64)  GOSU_SHA256=bbc4136d03ab138b1ad66fa4fc051bafc6cc7ffae632b069a53657279a450de3 ;; \
        arm64)  GOSU_SHA256=c3805a85d17f4454c23d7059bcb97e1ec1af272b90126e79ed002342de08389b ;; \
        armhf)  GOSU_SHA256=e5866286277ff2a2159fb9196fea13e0a59d3f1091ea46ddb985160b94b6841b ;; \
        i386)   GOSU_SHA256=087dbb8fe479537e64f9c86fa49ff3b41dee1cbd28739a19aaef83dc8186b1ca ;; \
        ppc64el) GOSU_SHA256=1891acdcfa70046818ab6ed3c52b9d42fa10fbb7b340eb429c8c7849691dbd76 ;; \
        s390x)  GOSU_SHA256=69873bab588192f760547ca1f75b27cfcf106e9f7403fee6fd0600bc914979d0 ;; \
        *) echo "unsupported architecture for gosu: $ARCH" >&2; exit 1 ;; \
    esac; \
    wget -O /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/${GOSU_VERSION}/gosu-${ARCH}"; \
    echo "${GOSU_SHA256}  /usr/local/bin/gosu" | sha256sum -c -; \
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
