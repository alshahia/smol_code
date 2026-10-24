# smolcode restricted-tier sandbox image.
#
# Built/refreshed automatically by smolcode.images.ensure_tier_images()
# (boot-time), or manually: make docker-images /
# python -m smolcode.images ensure --tier restricted.
#
# Hardening applied here:
#   - non-root user (`smolagent`)
#   - no curl/wget/network tools (use api_key over the LiteLLM socket only)
#   - THERE IS NO IMPORT ALLOWLIST INSIDE THIS IMAGE. smolagents'
#     LocalPythonExecutor allowlist is a LOCAL-executor feature; under
#     DockerExecutor model-written code runs in the Jupyter kernel inside
#     this container, and additional_authorized_imports is only used to
#     pip-install names. The image itself is the boundary here (plus the
#     runtime flags: network=none internal bridge, read-only uploads,
#     non-root uid). Anything installed below is reachable by model code.

# Phase 6: bumped bullseye -> bookworm (2026-09-24). bullseye-security
# has superseded the exact git version python:3.12-bullseye pins, so the
# install now 404s and THIS IMAGE CANNOT BUILD AT ALL. The sandboxed
# executor was therefore entirely non-functional; the docker-marked tests
# had been skipping because the daemon was down, which hid it.
# Supply-chain pin (Phase 8, decision 0043): the base image is referenced by
# DIGEST, not by tag. A tag is mutable in the registry, so a rebuild could
# silently swap the OS/interpreter under a sandbox whose policy we reviewed.
# The digest is also part of smolcode.images.source_hash(), so bumping it
# forces ensure_tier_images() to rebuild instead of reusing the old image.
#   python:3.12-bookworm@sha256:14a4933e6cef421424f7a66d89a3f4eafcbd0d90e0a822251f298e05132dc735
# Refresh procedure: pull the new digest, update this ARG, then rebuild via
#   python -m smolcode.images ensure --tier restricted
ARG PYTHON_BASE=3.12-bookworm@sha256:14a4933e6cef421424f7a66d89a3f4eafcbd0d90e0a822251f298e05132dc735
FROM python:${PYTHON_BASE}
# 2026-09-02 review finding 6: the restricted command allowlist includes
# git, so the binary must exist in the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Jupyter kernel gateway is required by smolagents DockerExecutor.
# Phase 1 (C2): pytest + ruff are advertised in the restricted tier's
# command allowlist - they must actually exist inside the image.
RUN pip install --no-cache-dir \
    jupyter_kernel_gateway \
    jupyter_client \
    ipykernel \
    pytest \
    ruff

# Create a non-root user; the runtime executes model-written code as this uid
RUN useradd --create-home --shell /bin/bash --uid 1000 smolagent
USER 1000
WORKDIR /home/smolagent
ENV PATH=/home/smolagent/.local/bin:$PATH

EXPOSE 8888
CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888"]
