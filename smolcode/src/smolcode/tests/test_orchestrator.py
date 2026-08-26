from __future__ import annotations

import json

import pytest
from smolagents import CodeAgent

from smolcode.agents.orchestrator import (
    build_orchestrator_agent,
)
from smolcode.agents.specialists import (
    USER_SPECIALISTS_PATH,
    Specialist,
    SpecialistError,
    bundled_specialists,
    load_user_specialists,
    resolve_specialist,
)
from smolcode.agents.specialists.deploy_staging import (
    build_deploy_staging_specialist,
)
from smolcode.config import load_settings
from smolcode.models import _StubLiteLLMModel


def test_bundled_specialists_contains_deploy_staging():
    """Decision 0008 D6: v1 ships exactly one bundled specialist."""
    bundled = bundled_specialists()
    assert len(bundled) == 1
    assert bundled[0].name == "deploy_staging"
    assert bundled[0].tier == "full_access"
    assert "run" in bundled[0].tools
    assert "git_push" in bundled[0].tools


def test_specialist_dataclass_validates_tier():
    """Specialist dataclass rejects unknown tiers."""
    with pytest.raises(SpecialistError):
        Specialist(
            name="x",
            tier="made_up",
            description="",
            tools=("run",),
        )


def test_specialist_dataclass_validates_name():
    """Specialist dataclass rejects empty names."""
    with pytest.raises(SpecialistError):
        Specialist(
            name="",
            tier="full_access",
            description="",
            tools=("run",),
        )


def test_resolve_specialist_returns_none_for_unknown():
    """resolve_specialist returns None (does not raise) for unknown names."""
    found = resolve_specialist("does_not_exist")
    assert found is None


def test_resolve_specialist_returns_bundled():
    """resolve_specialist finds the bundled deploy_staging."""
    found = resolve_specialist("deploy_staging")
    assert found is not None
    assert found.name == "deploy_staging"


def test_user_specialists_path_default():
    """USER_SPECIALISTS_PATH defaults to ~/.smolcode/specialists.toml."""
    assert str(USER_SPECIALISTS_PATH).endswith("specialists.toml")
    assert ".smolcode" in str(USER_SPECIALISTS_PATH)


def test_load_user_specialists_returns_empty_when_no_file(tmp_path, monkeypatch):
    """Missing specialists.toml yields an empty list, not an error."""
    monkeypatch.setattr(
        "smolcode.agents.specialists.USER_SPECIALISTS_PATH",
        tmp_path / "specialists.toml",
    )
    out = load_user_specialists(None)
    assert out == []


def test_load_user_specialists_parses_valid_file(tmp_path, monkeypatch):
    """A well-formed specialists.toml yields Specialist instances."""
    path = tmp_path / "specialists.toml"
    toml_text = '[[specialists]]\nname = "nightly_backup"\ntier = "full_access"\ndescription = "Run the nightly backup job"\ntools = ["run"]\nextra_paths = ["./infra"]\n[[specialists]]\nname = "lint_only"\ntier = "restricted"\ndescription = "Lint code without edits"\ntools = ["run"]\n'
    path.write_text(toml_text, encoding="utf-8")
    monkeypatch.setattr(
        "smolcode.agents.specialists.USER_SPECIALISTS_PATH",
        path,
    )
    out = load_user_specialists(None)
    assert len(out) == 2
    names = {s.name for s in out}
    assert "nightly_backup" in names
    assert "lint_only" in names
    nightly = [s for s in out if s.name == "nightly_backup"][0]
    assert nightly.tier == "full_access"
    assert nightly.tools == ("run",)
    assert nightly.extra_paths == ("./infra",)


def test_build_orchestrator_agent_returns_code_agent(_isolate_env, monkeypatch):
    """Factory returns a CodeAgent with the right shape."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel())
    assert isinstance(agent, CodeAgent)
    assert agent.executor_type == "local"
    assert "do_restricted_task" in agent.tools
    assert "do_elevated_task" in agent.tools
    assert "do_full_access_task" in agent.tools
    assert "do_specialist" in agent.tools


def test_build_orchestrator_agent_without_specialists(_isolate_env, monkeypatch):
    """When specialists=[], the do_specialist tool is NOT added."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel(), specialists=[])
    assert "do_specialist" not in agent.tools
    assert "do_restricted_task" in agent.tools
    assert "do_elevated_task" in agent.tools
    assert "do_full_access_task" in agent.tools


def test_orchestrator_prompt_contains_specialist_block(_isolate_env, monkeypatch):
    """The orchestrator system prompt mentions the bundled specialist."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel())
    prompt = agent.prompt_templates.get("system_prompt", "")
    assert "do_restricted_task" in prompt
    assert "do_elevated_task" in prompt
    assert "do_full_task" in prompt
    assert "deploy_staging" in prompt
    assert "do_specialist" in prompt
    assert "default to restricted" in prompt


def test_orchestrator_max_steps_override(_isolate_env, monkeypatch):
    """max_steps kwarg overrides the default restricted max_steps."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel(), max_steps=3)
    assert agent.max_steps == 3


def test_orchestrator_rejects_non_settings(_isolate_env, monkeypatch):
    """build_orchestrator_agent rejects non-Settings inputs."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    with pytest.raises(TypeError):
        build_orchestrator_agent("not a settings", _StubLiteLLMModel())


def test_render_specialist_block_no_specialists():
    """_render_specialist_block returns a placeholder when list is empty."""
    from smolcode.agents.orchestrator import _render_specialist_block

    out = _render_specialist_block([])
    assert "no specialists" in out


def test_render_specialist_block_with_one_specialist():
    """_render_specialist_block renders the specialist name + tier."""
    from smolcode.agents.orchestrator import _render_specialist_block

    spec = build_deploy_staging_specialist()
    out = _render_specialist_block([spec])
    assert spec.name in out
    assert spec.tier in out
    assert "do_specialist" in out


def test_specialist_loads_with_workspace_path(_isolate_env, monkeypatch):
    """Specialist loads with the user-workspace path when given settings."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    out = load_user_specialists(settings)
    assert out == []


def test_make_agent_accepts_tools_override(_isolate_env, monkeypatch):
    """make_agent honors tools_override for specialists (M5 D6)."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    from smolcode.agents.base import make_agent
    from smolcode.tools import build_tools

    full_tier = settings.tiers["full_access"]
    all_tools = build_tools(full_tier, settings, workspace_path=str(settings.workspace))
    narrowed = all_tools[:2]
    agent = make_agent(full_tier, settings, _StubLiteLLMModel(), tools_override=narrowed)
    # CodeAgent auto-injects a final_answer tool; check our tools are present.
    tool_values = list(agent.tools.values())
    for t in narrowed:
        assert t in tool_values


def test_specialist_tools_override_actually_narrows(_isolate_env, monkeypatch):
    """Specialist agent has ONLY the requested tools."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    from smolcode.agents.orchestrator import _build_specialist_agent

    spec = build_deploy_staging_specialist()
    tier_obj = settings.tiers[spec.tier]
    agent = _build_specialist_agent(spec, tier_obj, settings, _StubLiteLLMModel())
    names = set(agent.tools.keys())
    assert "read_file" not in names
    assert "write_file" not in names
    assert "git_status" not in names
    assert "run" in names
    assert "git_push" in names


def test_orchestrator_runs_and_delegates_to_restricted(_isolate_env, monkeypatch):
    """End-to-end: stub orchestrator emits do_restricted_task; sub-agent returns."""
    from smolagents.models import ChatMessage, TokenUsage

    from smolcode.agents import orchestrator as orch_mod

    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()

    open_angle = chr(60)
    close_angle = chr(62)
    slash = chr(47)
    q = chr(34)

    # Sub-agent stub: ALWAYS returns final_answer("done-via-restricted") so the
    # nested run terminates immediately on every delegation.
    sub_step = (
        open_angle
        + "code"
        + close_angle
        + "final_answer("
        + q
        + "done-via-restricted"
        + q
        + ")"
        + open_angle
        + slash
        + "code"
        + close_angle
    )

    class _SubStub(_StubLiteLLMModel):
        def generate(self, messages, stop_sequences=None, **kwargs):
            return ChatMessage(
                role="assistant",
                content=sub_step,
                tool_calls=None,
                raw=None,
                token_usage=TokenUsage(input_tokens=0, output_tokens=0),
            )

    # Patch make_agent so the orchestrator's delegation creates a sub-agent
    # backed by _SubStub instead of the orchestrator's model.
    original_make_agent = orch_mod.make_agent

    def patched_make_agent(tier, settings_arg, model, **kwargs):
        return original_make_agent(tier, settings_arg, _SubStub(), **kwargs)

    monkeypatch.setattr(orch_mod, "make_agent", patched_make_agent)

    # Orchestrator stub: emits do_restricted_task once, then final_answer.
    orch_steps = [
        (
            open_angle
            + "code"
            + close_angle
            + "do_restricted_task(task="
            + q
            + "ping"
            + q
            + ")"
            + open_angle
            + slash
            + "code"
            + close_angle
        ),
        (
            open_angle
            + "code"
            + close_angle
            + "final_answer("
            + q
            + "all-done"
            + q
            + ")"
            + open_angle
            + slash
            + "code"
            + close_angle
        ),
    ]
    it = iter(orch_steps)

    class _OrchestratorStub(_StubLiteLLMModel):
        def generate(self, messages, stop_sequences=None, **kwargs):
            return ChatMessage(
                role="assistant",
                content=next(it),
                tool_calls=None,
                raw=None,
                token_usage=TokenUsage(input_tokens=0, output_tokens=0),
            )

    agent = build_orchestrator_agent(settings, _OrchestratorStub())
    ans = agent.run("ping")
    # The orchestrator's final_answer is "all-done" -- so the answer contains that.
    assert "all-done" in str(ans)


def test_orchestrator_emits_subagent_audit_event(_isolate_env, monkeypatch, tmp_path):
    """Every delegation emits a 'subagent' event in the audit log."""
    from smolagents.models import ChatMessage, TokenUsage

    from smolcode.agents import orchestrator as orch_mod
    from smolcode.audit import AuditSink

    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    audit_path = tmp_path / "audit.jsonl"

    open_angle = chr(60)
    close_angle = chr(62)
    slash = chr(47)
    q = chr(34)

    sub_step = (
        open_angle
        + "code"
        + close_angle
        + "final_answer("
        + q
        + "audited"
        + q
        + ")"
        + open_angle
        + slash
        + "code"
        + close_angle
    )

    class _SubStub(_StubLiteLLMModel):
        def generate(self, messages, stop_sequences=None, **kwargs):
            return ChatMessage(
                role="assistant",
                content=sub_step,
                tool_calls=None,
                raw=None,
                token_usage=TokenUsage(input_tokens=0, output_tokens=0),
            )

    original_make_agent = orch_mod.make_agent

    def patched_make_agent(tier, settings_arg, model, **kwargs):
        return original_make_agent(tier, settings_arg, _SubStub(), **kwargs)

    monkeypatch.setattr(orch_mod, "make_agent", patched_make_agent)

    orch_steps = [
        (
            open_angle
            + "code"
            + close_angle
            + "do_restricted_task(task="
            + q
            + "audit-ping"
            + q
            + ")"
            + open_angle
            + slash
            + "code"
            + close_angle
        ),
        (
            open_angle
            + "code"
            + close_angle
            + "final_answer("
            + q
            + "all-done"
            + q
            + ")"
            + open_angle
            + slash
            + "code"
            + close_angle
        ),
    ]
    it = iter(orch_steps)

    class _OrchestratorStub(_StubLiteLLMModel):
        def generate(self, messages, stop_sequences=None, **kwargs):
            return ChatMessage(
                role="assistant",
                content=next(it),
                tool_calls=None,
                raw=None,
                token_usage=TokenUsage(input_tokens=0, output_tokens=0),
            )

    audit = AuditSink(str(audit_path))
    agent = build_orchestrator_agent(settings, _OrchestratorStub(), audit_sink=audit)
    agent.run("audit-ping")
    audit.close()

    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    subagent_events = [e for e in events if e.get("event") == "subagent"]
    assert len(subagent_events) == 1
    assert subagent_events[0]["tier"] == "restricted"
    assert subagent_events[0]["specialist"] == ""
    assert subagent_events[0]["status"] == "ok"
    assert "audit-ping" in subagent_events[0]["task"]


def test_orchestrator_unknown_specialist_raises(_isolate_env, monkeypatch):
    """Calling do_specialist with an unknown name raises SpecialistError."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel())
    spec_tool = agent.tools["do_specialist"]
    with pytest.raises(SpecialistError):
        spec_tool.forward(name="no_such_specialist", task="x")


def test_specialist_unknown_tool_raises(_isolate_env, monkeypatch):
    """Specialist with a tool name that does not exist in the tier raises."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    bad = Specialist(
        name="broken",
        tier="full_access",
        description="x",
        tools=("run", "definitely_not_a_real_tool"),
    )
    with pytest.raises(SpecialistError):
        build_orchestrator_agent(settings, _StubLiteLLMModel(), specialists=[bad])


def test_delegation_tool_rejects_empty_task(_isolate_env, monkeypatch):
    """do_<tier>_task.forward rejects empty task."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel())
    for tier in ("do_restricted_task", "do_elevated_task", "do_full_access_task"):
        tool = agent.tools[tier]
        with pytest.raises(ValueError):
            tool.forward(task="   ")


def test_specialist_tool_rejects_empty_name(_isolate_env, monkeypatch):
    """do_specialist.forward rejects empty name or task."""
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel())
    spec_tool = agent.tools["do_specialist"]
    with pytest.raises(ValueError):
        spec_tool.forward(name="", task="x")
    with pytest.raises(ValueError):
        spec_tool.forward(name="deploy_staging", task="")


def test_cli_parser_has_orchestrator_flag():
    """The --orchestrator flag is wired into the CLI."""
    from smolcode.cli import _build_parser

    p = _build_parser()
    ns = p.parse_args(["task", "--orchestrator"])
    assert ns.orchestrator is True
    ns2 = p.parse_args(["task"])
    assert ns2.orchestrator is False


def test_cli_orchestrator_uses_orchestrator_factory(_isolate_env, monkeypatch):
    """main() with --orchestrator builds the orchestrator (smoke)."""
    import sys as _sys

    from smolcode import cli

    monkeypatch.setattr(_sys, "argv", ["smolcode", "--smoke", "--orchestrator", "--no-audit", "x"])
    captured = {}

    def fake_build(settings, model, *, max_steps=None, audit_sink=None, **kwargs):
        captured["called"] = True

        class _Stub(CodeAgent):
            def run(self, task, **kwargs):
                return "orch-stub-answer"

        return _Stub(tools={}, model=model)

    monkeypatch.setattr(cli, "build_orchestrator_agent", fake_build)
    rc = cli.main()
    assert captured.get("called") is True
    assert rc == 0


def test_cli_orchestrator_overrides_tier(_isolate_env, monkeypatch):
    """--orchestrator + --tier full_access: orchestrator wins (D11)."""
    import sys as _sys

    from smolcode import cli

    monkeypatch.setattr(
        _sys, "argv", ["smolcode", "--smoke", "--orchestrator", "--tier", "full_access", "--no-audit", "x"]
    )
    called = {"orch": 0, "full": 0}

    def fake_orch(settings, model, *, max_steps=None, audit_sink=None, **kwargs):
        called["orch"] += 1

        class _Stub(CodeAgent):
            def run(self, task, **kwargs):
                return "x"

        return _Stub(tools={}, model=model)

    def fake_full(settings, model, *, max_steps=None):
        called["full"] += 1

        class _Stub(CodeAgent):
            def run(self, task, **kwargs):
                return "x"

        return _Stub(tools={}, model=model)

    monkeypatch.setattr(cli, "build_orchestrator_agent", fake_orch)
    monkeypatch.setattr(cli, "build_full_access_agent", fake_full)
    cli.main()
    assert called["orch"] == 1
    assert called["full"] == 0


def test_audit_subagent_event_on_subagent_error(_isolate_env, monkeypatch, tmp_path):
    """If the sub-agent raises, the orchestrator records an error subagent event.

    Note: smolagents swallows per-step tool errors and continues (the
    orchestrator's do_restricted_task raises RuntimeError, the orchestrator
    catches + records it + re-raises; smolagents logs the re-raise and the
    orchestrator's NEXT model call emits final_answer to end the run). So
    agent.run() returns normally, but the audit log records the subagent
    error event for post-hoc inspection.
    """
    from smolagents.models import ChatMessage, TokenUsage

    from smolcode.agents import orchestrator as orch_mod
    from smolcode.audit import AuditSink

    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    settings = load_settings()
    audit_path = tmp_path / "audit.jsonl"

    open_angle = chr(60)
    close_angle = chr(62)
    slash = chr(47)
    q = chr(34)

    class _Boom(CodeAgent):
        def run(self, task, **kwargs):
            raise RuntimeError("boom")

    def boom_make_agent(tier, settings, model, *, max_steps=None, mcp_configs=None, tools_override=None):
        return _Boom(tools={}, model=model)

    monkeypatch.setattr(orch_mod, "make_agent", boom_make_agent)

    fallback = (
        open_angle
        + "code"
        + close_angle
        + "final_answer("
        + q
        + "recovered"
        + q
        + ")"
        + open_angle
        + slash
        + "code"
        + close_angle
    )
    orch_steps = [
        (
            open_angle
            + "code"
            + close_angle
            + "do_restricted_task(task="
            + q
            + "explode"
            + q
            + ")"
            + open_angle
            + slash
            + "code"
            + close_angle
        ),
    ]
    it = iter(orch_steps)

    class _OrchestratorStub(_StubLiteLLMModel):
        def generate(self, messages, stop_sequences=None, **kwargs):
            try:
                content = next(it)
            except StopIteration:
                content = fallback
            return ChatMessage(
                role="assistant",
                content=content,
                tool_calls=None,
                raw=None,
                token_usage=TokenUsage(input_tokens=0, output_tokens=0),
            )

    audit = AuditSink(str(audit_path))
    agent = build_orchestrator_agent(settings, _OrchestratorStub(), audit_sink=audit)
    # agent.run returns normally (smolagents caught the RuntimeError from
    # the per-step tool execution); the orchestrator should have recorded
    # an error subagent event BEFORE that catch.
    agent.run("explode")
    audit.close()

    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    subagent_events = [e for e in events if e.get("event") == "subagent"]
    assert len(subagent_events) == 1
    assert subagent_events[0]["status"] == "error"
    assert subagent_events[0]["error"] == "RuntimeError"
    assert "explode" in subagent_events[0]["task"]


# --- Coverage-lift tests (M7) ---------------------------------------------


def test_load_user_specialists_returns_empty_when_not_a_list(monkeypatch, tmp_path):
    """If the [specialists] key is not a list, return empty (not error)."""
    monkeypatch.setattr("smolcode.agents.specialists.USER_SPECIALISTS_PATH", tmp_path / "specialists.toml")
    (tmp_path / "specialists.toml").write_text('specialists = "not-a-list"', encoding="utf-8")
    assert load_user_specialists() == []


def test_load_user_specialists_skips_non_dict_entries(monkeypatch, tmp_path):
    """Non-dict entries in [specialists] are silently skipped."""
    monkeypatch.setattr("smolcode.agents.specialists.USER_SPECIALISTS_PATH", tmp_path / "specialists.toml")
    (tmp_path / "specialists.toml").write_text('specialists = ["string", 42, true]', encoding="utf-8")
    out = load_user_specialists()
    assert out == []


def test_load_user_specialists_invalid_entry_raises(monkeypatch, tmp_path):
    """A dict entry that fails Specialist validation raises SpecialistError."""
    monkeypatch.setattr("smolcode.agents.specialists.USER_SPECIALISTS_PATH", tmp_path / "specialists.toml")
    # tier "bogus" is not in {restricted, elevated, full_access} -> SpecialistError
    (tmp_path / "specialists.toml").write_text(
        'specialists = [{name = "x", tier = "bogus"}]\n',
        encoding="utf-8",
    )
    with pytest.raises(SpecialistError):
        load_user_specialists()


def test_load_user_specialists_unreadable_returns_empty(monkeypatch, tmp_path):
    """An OSError on file read produces empty list (logged at DEBUG), not an exception."""
    p = tmp_path / "specialists.toml"
    p.write_text("", encoding="utf-8")  # ensure file exists for the is_file() check
    monkeypatch.setattr("smolcode.agents.specialists.USER_SPECIALISTS_PATH", p)
    # Make open raise OSError to simulate permission denied.
    import builtins as _b

    real_open = _b.open

    def _bad_open(*args, **kwargs):
        if str(args[0] if args else kwargs.get("file", "")).endswith("specialists.toml"):
            raise OSError("permission denied")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(_b, "open", _bad_open)
    assert load_user_specialists() == []


def test_load_user_specialists_parse_error_raises(monkeypatch, tmp_path):
    """A malformed TOML file raises SpecialistError, not a silent empty list."""
    monkeypatch.setattr("smolcode.agents.specialists.USER_SPECIALISTS_PATH", tmp_path / "specialists.toml")
    (tmp_path / "specialists.toml").write_text("specialists = [", encoding="utf-8")  # unterminated
    with pytest.raises(SpecialistError):
        load_user_specialists()


def test_resolve_specialist_uses_load_user_when_settings_provided(monkeypatch, tmp_path):
    """When settings is non-None, load_user_specialists is consulted."""
    monkeypatch.setattr("smolcode.agents.specialists.USER_SPECIALISTS_PATH", tmp_path / "missing.toml")
    settings = object()  # any non-None sentinel
    # No user specialists file; bundled only.
    out = resolve_specialist("deploy_staging", settings=settings)
    assert out is not None
    assert out.name == "deploy_staging"


# --- Coverage-lift tests for shell.py (M7) ---------------------------------


def test_run_rejects_empty_cmd_string():
    """Real shell._RunTool.forward() raises PermissionError on empty cmd."""
    from smolcode.tools import policy, shell

    tools = shell.build_shell_tools(policy.CommandPolicy(allowlist=("python",)))
    run = tools[0]
    with pytest.raises(PermissionError, match="cmd is required"):
        run("", ["-c", "print(1)"], timeout=5)


# --- Coverage-lift tests for fs.py (M7) ------------------------------------


def test_write_file_with_parents_creates_dirs(tmp_path):
    """write_file creates parent directories if they do not exist."""
    from smolcode.tools import fs

    tools = fs.build_fs_tools(tmp_path)
    write = [t for t in tools if getattr(t, "name", "") == "write_file"][0]
    target = tmp_path / "subdir1" / "subdir2" / "x.txt"
    write(str(target), "hi")
    assert target.read_text(encoding="utf-8") == "hi"


def test_load_user_specialists_generic_exception_raises(monkeypatch, tmp_path):
    """A specialist entry that fails Specialist validation with a non-SpecialistError
    exception gets wrapped in SpecialistError."""
    monkeypatch.setattr("smolcode.agents.specialists.USER_SPECIALISTS_PATH", tmp_path / "specialists.toml")
    from smolcode.agents.specialists import _models as _specialist_models

    real_specialist = _specialist_models.Specialist

    def _bad_specialist(*args, **kwargs):
        raise ValueError("synthetic failure for coverage")

    # The __init__.py imports Specialist at module load time, so the
    # in-module name is what load_user_specialists() calls. Patch both:
    # the module attribute and the name in _models (in case the import
    # re-resolves).
    monkeypatch.setattr("smolcode.agents.specialists.Specialist", _bad_specialist)
    monkeypatch.setattr(_specialist_models, "Specialist", _bad_specialist)
    (tmp_path / "specialists.toml").write_text(
        'specialists = [{name = "x", tier = "restricted"}]\n',
        encoding="utf-8",
    )
    with pytest.raises(SpecialistError, match="invalid specialist entry"):
        load_user_specialists()
    # Restore for later tests.
    monkeypatch.setattr(_specialist_models, "Specialist", real_specialist)
