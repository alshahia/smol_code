# smolcode full_access-tier sandbox image (M4).
#
# Built once per repo by `make docker-full_access` (or by the
# DockerExecutor itself on first run).
#
# !!! WARNING !!!
#
# The full_access tier is the ONLY tier that allows ssh, scp, rsync,
# docker, kubectl, terraform, ansible, and the aws/gcloud/az CLIs.
# Combined with the per-run confirmation prompt (cli.py) and the
# audit log (smolcode/audit.py), this is the most powerful smolcode
# tier and should only be used when the user has explicitly confirmed
# a destructive or external operation.
#
# Compared to elevated.Dockerfile, this image adds:
#   - openssh-client, rsync         (matches full_access command allowlist)
#   - docker CLI (the agent CAN run other containers, but not via
#     docker-in-docker; this is the host's docker socket is NOT
#     bind-mounted)
#   - kubectl, terraform, ansible   (infra / orchestration CLIs)
#   - awscli, google-cloud-cli, azure-cli  (cloud provider CLIs)
#
# Network: full_access declares network="open". The Docker container
# is started without network_mode=none, so it can reach any host
# the agent can resolve. This is intentional and is the documented
# behaviour of the full_access tier (see docs/security.md section
# 3.3 + docs/roadmap.md 6). The CLI confirmation prompt + audit
# log are the human-in-the-loop backstop.
#
# Hardening (matches restricted/elevated, then UNCONDITIONALLY relaxed):
#   - still non-root user (smolagent, UID 1000) -- the agent must
#     escalate to root itself if it needs to, which is logged
#   - no /etc/shadow bind, no docker socket bind (no socket mount)
#   - full_access import allowlist is enforced by smolagents
#     LocalPythonExecutor inside the container, not by this image

FROM python:3.12-bullseye

# Jupyter kernel gateway is required by smolagents DockerExecutor
RUN pip install --no-cache-dir \
    jupyter_kernel_gateway \
    jupyter_client \
    ipykernel

# Full-access extras. These match the full_access tier's command
# allowlist in smolcode/config.py.
#
# Note: docker CLI is installed but the Docker socket is NOT
# bind-mounted into the container. The agent can spawn other
# containers only if it can reach a Docker daemon over the network
# (e.g. a remote Docker host), which is its full_access prerogative.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git \
        curl \
        jq \
        make \
        openssh-client \
        rsync \
        docker.io \
        kubectl \
        terraform \
        ansible \
        awscli \
        google-cloud-cli \
        azure-cli \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user; the runtime executes model-written code as this uid
RUN useradd --create-home --shell /bin/bash --uid 1000 smolagent
USER 1000
WORKDIR /home/smolagent
ENV PATH=/home/smolagent/.local/bin:$PATH

EXPOSE 8888
CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888"]
