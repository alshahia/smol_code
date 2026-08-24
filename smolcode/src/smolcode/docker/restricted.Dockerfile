# smolcode restricted-tier sandbox image.
#
# Built once per repo by `make docker-restricted` (or by the DockerExecutor
# itself on first run, per smolagents/remote_executors.py:595-604).
#
# Hardening applied here:
#   - non-root user (`smolagent`)
#   - no curl/wget/network tools (use api_key over the LiteLLM socket only)
#   - the restricted import allowlist is enforced by smolagents
#     LocalPythonExecutor inside the container, not by this image

FROM python:3.12-bullseye

# Jupyter kernel gateway is required by smolagents DockerExecutor
RUN pip install --no-cache-dir \
    jupyter_kernel_gateway \
    jupyter_client \
    ipykernel

# Create a non-root user; the runtime executes model-written code as this uid
RUN useradd --create-home --shell /bin/bash --uid 1000 smolagent
USER 1000
WORKDIR /home/smolagent
ENV PATH=/home/smolagent/.local/bin:$PATH

EXPOSE 8888
CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888"]
