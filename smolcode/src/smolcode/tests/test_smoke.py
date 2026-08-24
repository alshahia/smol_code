"""End-to-end smoke tests for an agent + tools using the stub model."""

from __future__ import annotations

from smolcode.agents.base import make_agent
from smolcode.config import load_settings
from smolcode.models import _StubLiteLLMModel


def test_stub_agent_terminates_in_one_step(tmp_path, monkeypatch):
    """A stub agent returns final_answer on the first step."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = load_settings(cli_overrides={"workspace": str(ws)})
    agent = make_agent(settings.tiers["restricted"], settings, _StubLiteLLMModel())
    answer = agent.run("say hi")
    assert "hi" in str(answer).lower()


def _make_code_step_stub(code_blocks):
    """Stub that emits one <code>...</code> block per CodeAgent step."""
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


def test_stub_agent_uses_write_file_tool(tmp_path, monkeypatch):
    """Two-step agent: write_file then final_answer."""
    step1 = (
        chr(60)
        + "code>write_file(path="
        + chr(34)
        + "x.txt"
        + chr(34)
        + ", content="
        + chr(34)
        + "smoke"
        + chr(34)
        + ")</"
        + "code"
        + chr(62)
    )
    step2 = chr(60) + "code>final_answer(" + chr(34) + "done" + chr(34) + ")</" + "code" + chr(62)
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = load_settings(cli_overrides={"workspace": str(ws)})
    agent = make_agent(settings.tiers["restricted"], settings, _make_code_step_stub([step1, step2]))
    answer = agent.run("create x.txt with content smoke, then report done")
    assert "done" in str(answer).lower()
    assert (ws / "x.txt").exists()
    assert (ws / "x.txt").read_text(encoding="utf-8") == "smoke"


def test_stub_agent_uses_write_then_shell(tmp_path, monkeypatch):
    """Three-step: write a python script, run it, final_answer."""
    step1 = (
        chr(60)
        + "code>write_file(path="
        + chr(34)
        + "script.py"
        + chr(34)
        + ", content="
        + chr(34)
        + "print("
        + chr(39)
        + "shell-ok"
        + chr(39)
        + ")"
        + chr(34)
        + ")</"
        + "code"
        + chr(62)
    )
    step2 = (
        chr(60)
        + "code>print(run(cmd="
        + chr(34)
        + "python"
        + chr(34)
        + ", args=["
        + chr(34)
        + "script.py"
        + chr(34)
        + "]))</"
        + "code"
        + chr(62)
    )
    step3 = chr(60) + "code>final_answer(" + chr(34) + "wrote+ran" + chr(34) + ")</" + "code" + chr(62)
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    ws = tmp_path / "ws"
    ws.mkdir()
    settings = load_settings(cli_overrides={"workspace": str(ws)})
    agent = make_agent(settings.tiers["restricted"], settings, _make_code_step_stub([step1, step2, step3]))
    answer = agent.run("create a python script that prints shell-ok, then run it, then report")
    assert "wrote+ran" in str(answer)
    assert (ws / "script.py").exists()
