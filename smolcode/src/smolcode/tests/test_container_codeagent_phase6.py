"""Phase 6 leftover (2026-10-24 assessment): a REAL CodeAgent tool call
inside the smolcode:restricted image.

test_container_gate_phase6.py proved with ``docker run`` probes that
smolcode is not importable in the sandbox and that the destructive gate exists
in the serialized tool source. It did not exercise the product path: CodeAgent
serialising its tools into the container, a model-issued tool call executing
there, and the inlined gate denying it.

This file pins that end-to-end contract (ADR 0041, limitation #1/#2):
  * a restricted CodeAgent asked to run ``git push`` inside the container
    receives a denial (PermissionError from the inlined gate), does not hang,
    and completes the run;
  * the denial is visible in the agent's recorded observations.

Marked ``docker`` and skipped when the daemon is unreachable, so the
Docker-less suite stays green. Run with: pytest -m docker.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from smolcode.agents.base import make_agent
from smolcode.config import load_settings
from smolcode.container import ensure_internal_network
from smolcode.images import ensure_tier_images
from smolcode.models import _StubLiteLLMModel


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


pytestmark = [pytest.mark.docker, pytest.mark.skipif(not _docker_available(), reason="docker daemon not reachable")]


def _make_code_step_stub(code_blocks):
    """Stub model that emits one <code>...</code> block per CodeAgent step."""

    it = iter(code_blocks)

    class CodeStepStub(_StubLiteLLMModel):
        def generate(self, messages, stop_sequences=None, **kwargs):
            from smolagents.models import ChatMessage, TokenUsage

            return ChatMessage(
                role="assistant",
                content=next(it),
                tool_calls=None,
                raw=None,
                token_usage=TokenUsage(input_tokens=0, output_tokens=0),
            )

    return CodeStepStub()


def _block(code: str) -> str:
    return "<" + "code>" + code + "</" + "code" + ">"


def test_restricted_codeagent_denies_git_push_inside_container(tmp_path, monkeypatch):
    """The in-container gate denies a destructive tool call (fail closed).

    Before Phase 6 this path was unverified: the host-plane unit tests passed
    while the container could not import smolcode at all. The serialized tool
    source now carries the inlined classifier, and the bound policy is "deny"
    (no approval can reach a container), so the call must be refused.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "docker")
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
    settings = load_settings()
    assert settings.executor == "docker"

    try:
        ensure_tier_images(settings, ["restricted"])
        ensure_internal_network()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"restricted tier image/network unavailable: {exc}")

    step1 = _block("run(cmd='git', args=['push', 'origin', 'main'])")
    step2 = _block("final_answer('push-denied')")
    agent = make_agent(
        settings.tiers["restricted"],
        settings,
        _make_code_step_stub([step1, step2]),
    )
    try:
        answer = agent.run("Attempt to push the current branch, then report the outcome.")
    finally:
        cleanup = getattr(agent.python_executor, "cleanup", None)
        if callable(cleanup):
            cleanup()

    assert "push-denied" in str(answer).lower()
    observations = " ".join(
        str(getattr(step, "observations", "")) + " " + str(getattr(step, "error", "")) for step in agent.memory.steps
    ).lower()
    assert "blocked" in observations or "permissionerror" in observations.replace(" ", ""), (
        "the in-container destructive gate did not deny git push; observations=" + observations[:600]
    )
