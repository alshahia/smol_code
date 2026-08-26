"""Phase 1 (C1): the destructive/diff gate keys on the EXECUTING tool's tier,
not on the process-global SessionState tier.

Pins three bypasses found in the 2026-08-26 review:

1. git_push / destructive run executed by an elevated or full_access
   sub-agent under an orchestrator (whose global session says another
   tier) fired WITHOUT any confirmation, because shell.py / git.py keyed
   the gate on current_session().tier == "full_access".
2. A plain restricted-tier run could push code silently: every tier gets
   the git_push tool and the classifier ignored run(git push ...).
3. The web/CLI auto-approve flag was meaningless for delegated tiers for
   the same reason.

Contract after the fix:

- Tools carry their EFFECTIVE tier as a bound attribute; the gate fires
  on is_destructive(...) regardless of the ambient session tier.
- Restricted-tier tools auto-DENY destructive ops (no prompt).
- Non-restricted tools consult confirm_callback unless
  auto_approve_destructive is set.
- Orchestrator delegations install a CHILD SessionState (correct tier +
  inherited callback/audit) for the duration of the sub-run and restore
  the parent afterwards.
- Delegating into full_access requires a per-run confirmation supplied
  by the host plane (CLI prompt / web approval modal); refusing without
  one is fail-closed.
"""

from __future__ import annotations

import pytest

from smolcode.agents.orchestrator import build_orchestrator_agent
from smolcode.destructive import is_destructive
from smolcode.models import _StubLiteLLMModel
from smolcode.session import SessionState, get_session, set_session
from smolcode.tools import CommandPolicy
from smolcode.tools.git import build_git_tools
from smolcode.tools.shell import build_shell_tools


@pytest.fixture(autouse=True)
def _clean_session():
    """No ambient session leaks between tests."""
    prev = get_session()
    set_session(None)
    yield
    set_session(prev)


class _RecordingCallback:
    def __init__(self, approved=True):
        self.calls = []
        self.approved = approved

    def __call__(self, tool_name, kwargs, summary):
        self.calls.append((tool_name, dict(kwargs)))
        from smolcode.session import DestructiveDecision

        return DestructiveDecision(approved=self.approved, reason="test")


# --- classifier tightening ---------------------------------------------------


def test_run_git_push_is_classified_destructive():
    """C1 #2: run(cmd="git", args=["push", ...]) must be flagged."""
    assert is_destructive("run", {"cmd": "git", "args": ["push", "origin", "main"]}) is True


def test_run_git_reset_is_classified_destructive():
    assert is_destructive("run", {"cmd": "git", "args": ["reset", "--hard", "HEAD~1"]}) is True


def test_run_git_status_stays_non_destructive():
    assert is_destructive("run", {"cmd": "git", "args": ["status"]}) is False


# --- shell tool gating by effective tier ------------------------------------


def _shell_tool(tier_name):
    policy = CommandPolicy(("python", "git", "ssh"))  # ssh => destructive surface
    return build_shell_tools(policy, tier_name=tier_name)[0]


def test_restricted_shell_auto_denies_destructive_run(monkeypatch):
    """Restricted tier denies destructive ops outright - no prompt, no exec."""
    called = []

    def _boom(*a, **k):
        called.append(a)
        raise AssertionError("executed")

    monkeypatch.setattr("subprocess.run", _boom)
    sess = SessionState(tier="restricted", confirm_callback=_RecordingCallback())
    set_session(sess)
    tool = _shell_tool("restricted")
    with pytest.raises(PermissionError, match="restricted"):
        tool.forward(cmd="ssh", args=["host"])
    assert called == []


def test_restricted_shell_denies_even_with_auto_approve_on():
    sess = SessionState(tier="restricted", auto_approve_destructive=True)
    set_session(sess)
    tool = _shell_tool("restricted")
    with pytest.raises(PermissionError, match="restricted"):
        tool.forward(cmd="ssh", args=["host"])


def test_full_access_tool_prompts_despite_ambient_session_tier(monkeypatch):
    """THE C1 bypass: ambient session says 'restricted' (orchestrator-like)
    while the executing tool is full_access - the prompt MUST still fire."""
    cb = _RecordingCallback(approved=False)
    set_session(SessionState(tier="restricted", confirm_callback=cb))  # orchestrator-like ambient
    tool = _shell_tool("full_access")
    with pytest.raises(PermissionError, match="denied"):
        tool.forward(cmd="ssh", args=["host"])
    assert len(cb.calls) == 1  # callback consulted => gate fired


def test_elevated_tool_prompts_for_ssh():
    cb = _RecordingCallback(approved=False)
    set_session(SessionState(tier="elevated", confirm_callback=cb))
    tool = _shell_tool("elevated")
    with pytest.raises(PermissionError, match="denied"):
        tool.forward(cmd="ssh", args=["host"])
    assert len(cb.calls) == 1


def test_auto_approve_flag_skips_prompt_but_not_on_restricted():
    cb = _RecordingCallback()
    set_session(SessionState(tier="restricted", auto_approve_destructive=True, confirm_callback=cb))
    result = _shell_tool("elevated").forward(cmd="python", args=["-c", "print('x')"])
    assert "returncode: 0" in result
    # restricted still denies even with auto-approve on
    with pytest.raises(PermissionError):
        _shell_tool("restricted").forward(cmd="ssh", args=["host"])


def test_non_destructive_call_never_prompts():
    cb = _RecordingCallback()
    set_session(SessionState(tier="restricted", confirm_callback=cb))
    result = _shell_tool("full_access").forward(cmd="python", args=["-c", "print('x')"])
    assert "returncode: 0" in result
    assert cb.calls == []


def test_no_session_and_non_restricted_denies_closed():
    """No ambient session at all => confirm_callback missing => deny closed."""
    tool = _shell_tool("full_access")
    with pytest.raises(PermissionError, match="no confirm"):
        tool.forward(cmd="ssh", args=["host"])


# --- git_push tool gating ----------------------------------------------------


def _push_tool(tier_name, workspace):
    policy = CommandPolicy(("python", "pytest", "git", "ruff", "pip", "npm", "node", "curl", "jq", "make"))
    tools = build_git_tools(policy, cwd=str(workspace), tier_name=tier_name)
    return [t for t in tools if t.name == "git_push"][0]


@pytest.fixture
def fake_push(monkeypatch):
    """Capture subprocess.run instead of touching any real repo."""
    calls = []

    class _P:
        stdout = ""
        stderr = ""
        returncode = 0

    def _fake_run(*args, **kwargs):
        calls.append(args)
        return _P()

    monkeypatch.setattr("subprocess.run", _fake_run)
    return calls


def test_restricted_git_push_denied_without_prompt(fake_push, tmp_path):
    """C1 #1 concrete case: restricted-tier git_push used to execute silently."""
    cb = _RecordingCallback()
    set_session(SessionState(tier="restricted", confirm_callback=cb))
    tool = _push_tool("restricted", tmp_path)
    with pytest.raises(PermissionError, match="restricted"):
        tool.forward(remote="origin")
    assert fake_push == []  # nothing executed
    assert cb.calls == []


def test_elevated_git_push_prompts(fake_push, tmp_path):
    cb = _RecordingCallback(approved=False)
    set_session(SessionState(tier="elevated", confirm_callback=cb))
    tool = _push_tool("elevated", tmp_path)
    with pytest.raises(PermissionError, match="denied"):
        tool.forward(remote="origin")
    assert fake_push == []
    assert len(cb.calls) == 1
    assert cb.calls[0][0] == "git_push"


def test_full_access_git_push_under_ambient_restricted_session_prompts(fake_push, tmp_path):
    set_session(SessionState(tier="restricted"))  # NO callback installed
    tool = _push_tool("full_access", tmp_path)
    with pytest.raises(PermissionError, match="no confirm"):
        tool.forward(remote="origin")
    assert fake_push == []


# --- orchestrator execution-context threading -------------------------------


class _FakeSubAgent:
    def __init__(self, recorder):
        self._recorder = recorder

    def run(self, task):
        from smolcode.session import current_session

        self._recorder.append(current_session())
        return "sub-ok"


def _orch_settings(monkeypatch):
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    from smolcode.config import load_settings

    return load_settings()


def test_delegation_installs_child_session_with_correct_tier(monkeypatch):
    settings = _orch_settings(monkeypatch)
    seen = []
    monkeypatch.setattr(
        "smolcode.agents.orchestrator.make_agent",
        lambda tier, settings, model, **kw: _FakeSubAgent(seen),
    )
    cb = _RecordingCallback()
    set_session(SessionState(tier="restricted", confirm_callback=cb))
    agent = build_orchestrator_agent(
        settings, _StubLiteLLMModel(), specialists=[], full_access_gate=lambda: None
    )
    answer = agent.tools["do_full_access_task"].forward(task="do infra")
    assert answer == "sub-ok"
    assert len(seen) == 1
    child = seen[0]
    assert child.tier == "full_access"
    assert child.confirm_callback is cb  # inherited
    assert get_session().tier == "restricted"  # parent restored afterwards


def test_child_seed_inherits_auto_approve(monkeypatch):
    settings = _orch_settings(monkeypatch)
    seen = []
    monkeypatch.setattr(
        "smolcode.agents.orchestrator.make_agent",
        lambda tier, settings, model, **kw: _FakeSubAgent(seen),
    )
    set_session(SessionState(tier="restricted", auto_approve_destructive=True))
    agent = build_orchestrator_agent(
        settings, _StubLiteLLMModel(), specialists=[], full_access_gate=lambda: None
    )
    agent.tools["do_elevated_task"].forward(task="build")
    assert seen[0].tier == "elevated"
    assert seen[0].auto_approve_destructive is True


# --- lazy full-access confirmation gate --------------------------------------


def test_do_full_task_without_gate_fails_closed(monkeypatch):
    settings = _orch_settings(monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("must not build")

    monkeypatch.setattr("smolcode.agents.orchestrator.make_agent", _boom)
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel(), specialists=[])
    with pytest.raises(PermissionError, match="confirmation gate"):
        agent.tools["do_full_access_task"].forward(task="deploy")


def test_do_full_task_gate_denies(monkeypatch):
    settings = _orch_settings(monkeypatch)

    def _deny():
        raise PermissionError("user said no")

    built = []
    monkeypatch.setattr(
        "smolcode.agents.orchestrator.make_agent",
        lambda tier, settings, model, **kw: built.append(tier.name) or _FakeSubAgent([]),
    )
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel(), specialists=[], full_access_gate=_deny)
    with pytest.raises(PermissionError, match="user said no"):
        agent.tools["do_full_access_task"].forward(task="deploy")
    assert built == []


def test_do_full_task_gate_confirms_once(monkeypatch):
    settings = _orch_settings(monkeypatch)
    gate_calls = []

    def _gate():
        gate_calls.append(1)

    seen = []
    monkeypatch.setattr(
        "smolcode.agents.orchestrator.make_agent",
        lambda tier, settings, model, **kw: _FakeSubAgent(seen),
    )
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel(), specialists=[], full_access_gate=_gate)
    agent.tools["do_full_access_task"].forward(task="a")
    agent.tools["do_full_access_task"].forward(task="b")
    assert len(gate_calls) == 1  # memoized per run
    assert len(seen) == 2


def test_specialist_to_full_access_triggers_gate(monkeypatch):
    from smolcode.agents.specialists import Specialist

    settings = _orch_settings(monkeypatch)
    gate_calls = []
    monkeypatch.setattr(
        "smolcode.agents.orchestrator.make_agent",
        lambda tier, settings, model, **kw: _FakeSubAgent([]),
    )

    def _gate():
        gate_calls.append(1)

    spec = Specialist(name="dep", tier="full_access", description="d", tools=("run", "git_push"))
    agent = build_orchestrator_agent(settings, _StubLiteLLMModel(), specialists=[spec], full_access_gate=_gate)
    agent.tools["do_specialist"].forward(name="dep", task="t")
    assert len(gate_calls) == 1


def test_specialist_to_restricted_skips_gate(monkeypatch):
    from smolcode.agents.specialists import Specialist

    settings = _orch_settings(monkeypatch)
    gate_calls = []
    monkeypatch.setattr(
        "smolcode.agents.orchestrator.make_agent",
        lambda tier, settings, model, **kw: _FakeSubAgent([]),
    )
    spec = Specialist(name="lint", tier="restricted", description="d", tools=("run",))
    agent = build_orchestrator_agent(
        settings, _StubLiteLLMModel(), specialists=[spec], full_access_gate=lambda: gate_calls.append(1)
    )
    agent.tools["do_specialist"].forward(name="lint", task="t")
    assert gate_calls == []
