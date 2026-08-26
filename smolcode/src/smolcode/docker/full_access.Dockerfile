# smolcode full_access-tier sandbox image (M4 + Phase 1 C2).
#
# Built/refreshed automatically by smolcode.images.ensure_tier_images()
# (boot-time), or manually: make docker-images /
# python -m smolcode.images ensure --tier full_access.
#
# !!! WARNING !!!
#
# The full_access tier is the ONLY tier that allows ssh, scp, rsync,
# docker, kubectl, terraform, ansible, and the aws/gcloud/az CLIs, on an
# open network. The per-run confirmation (direct tier) / delegation gate
# (orchestrator) plus the audit log are the human-in-the-loop backstop.
#
# Phase 1 (C2) repairs this Dockerfile: the previous version apt-get
# installed kubectl/terraform/google-cloud-cli/azure-cli straight from
# Debian repos - which do not ship them - so the build failed or the
# allowlist lied. Now:
#   - Debian-provided: git curl jq make openssh-client rsync docker.io
#     ansible awscli nodejs npm (+ pytest/ruff via pip)
#   - vendor repos with signed keys: google-cloud-cli (packages.cloud.
#     google.com), azure-cli (packages.microsoft.com), kubectl
#     (pkgs.k8s.io stable), terraform (apt.releases.hashicorp.com)
#
# Network: full_access declares network="open"; the container runs on a
# normal bridge with egress. Intentional and documented (docs/security.md
# section 3.3).

ARG PYTHON_BASE=3.12-bullseye
# Pin note: convert to a digest pin for supply-chain hardening; obtain via
# docker image inspect --format "{{index .RepoDigests 0}}" python:3.12-bullseye
FROM python:${PYTHON_BASE}

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        curl \
        gnupg \
        wget \
        apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# Jupyter kernel gateway required by smolagents DockerExecutor;
# pytest + ruff are advertised in every tier command allowlist.
RUN pip install --no-cache-dir \
    jupyter_kernel_gateway \
    jupyter_client \
    ipykernel \
    pytest \
    ruff

# --- Debian-provided CLIs (subset of config.py full_access.commands) -----
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git \
        jq \
        make \
        openssh-client \
        rsync \
        docker.io \
        ansible \
        awscli \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

# --- Vendor repositories (signed keys; standard upstream recipes) --------
RUN mkdir -p /etc/apt/keyrings /usr/share/keyrings

# kubectl from pkgs.k8s.io (community-owned, replaces deprecated
# packages.cloud.google.com apt); stable channel pinned to v1.30 line.
RUN curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key \
      | gpg --dearmor --yes -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /" \
       > /etc/apt/sources.list.d/kubernetes.list

# terraform from HashiCorp's official apt repo.
RUN wget -qO- https://apt.releases.hashicorp.com/gpg \
      | gpg --dearmor --yes -o /usr/share/keyrings/hashicorp-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com bullseye main" \
       > /etc/apt/sources.list.d/hashicorp.list

# google-cloud-cli (gcloud + friends) from Google Cloud SDK apt repo.
RUN curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
      | gpg --dearmor --yes -o /usr/share/keyrings/cloud.google.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
       > /etc/apt/sources.list.d/google-cloud-sdk.list

# azure-cli from Microsoft.
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor --yes -o /usr/share/keyrings/microsoft.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ bullseye main" \
       > /etc/apt/sources.list.d/azure-cli.list

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        kubectl \
        terraform \
        google-cloud-cli \
        azure-cli \
    && rm -rf /var/lib/apt/lists/*

# Non-root user; the agent escalates deliberately if it truly needs to.
RUN useradd --create-home --shell /bin/bash --uid 1000 smolagent
USER 1000
WORKDIR /home/smolagent
ENV PATH=/home/smolagent/.local/bin:$PATH

EXPOSE 8888
CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888"]
