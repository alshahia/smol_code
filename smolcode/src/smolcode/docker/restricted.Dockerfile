# smolcode restricted-tier sandbox image.
#
# Built/refreshed automatically by smolcode.images.ensure_tier_images()
# (boot-time), or manually: make docker-images /
# python -m smolcode.images ensure --tier restricted.
#
# Hardening applied here:
#   - non-root user (`smolagent`)
#   - no curl/wget/network tools (use api_key over the LiteLLM socket only)
#   - the restricted import allowlist is enforced by smolagents
#     LocalPythonExecutor inside the container, not by this image

ARG PYTHON_BASE=3.12-bullseye
# Pin note: convert to a digest pin (python@sha256:<digest>) for
# supply-chain hardening; obtain the digest via
# docker image inspect --format "{{index .RepoDigests 0}}" python:3.12-bullseye
FROM python:${PYTHON_BASE}

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
