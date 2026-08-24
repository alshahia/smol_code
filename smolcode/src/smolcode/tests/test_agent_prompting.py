"""Tests for the sandbox-boundary note injected into CodeAgent prompts.

Background: when a user asked the Web UI to "create a simple todo app",
the LLM wrote `import smolcode` inside the elevated Docker sandbox.
That import raised ``ModuleNotFoundError`` because the sandbox image is
minimal (smolagents + jupyter kernel gateway + curated stdlib only;
``smolcode`` is the host-side orchestrator and is NOT installed inside
the container).

Decision 0021 injects a tier-aware sandbox-boundary note into every
sandbox-tier CodeAgent via the ``instructions=`` kwarg (which smolagents
substitutes into the ``{{custom_instructions}}`` slot of the default
system prompt template). These tests pin that behavior so the bug
cannot silently regress.

Coverage:
    1. ``sandbox_boundary_instructions`` returns the right shape per tier.
    2. The note mentions ``smolcode`` is host-only (every sandbox tier).
    3. The note lists the tier's allowed imports and commands.
    4. The orchestrator (non-sandbox) returns "" so its prompt is unchanged.
    5. ``make_agent`` wires ``instructions=`` into the CodeAgent.
    6. The rendered system prompt contains our note (smoke test that the
       substitution actually happens).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from smolcode.agents.base import make_agent
from smolcode.agents.prompting import (
    _SANDBOX_TIERS,
    sandbox_boundary_instructions,
)
from smolcode.config import Settings, Tier, _default_tiers


# ---------------------------------------------------------------------------
# sandbox_boundary_instructions: per-tier shape
# ---------------------------------------------------------------------------


def _settings_with_local_executor() -> Settings:
    """Build a minimal Settings for unit tests (local executor, no I/O)."""
    return Settings(
        workspace=".",
        executor="local",
        provider="opencode-go",
        model="stub-model",
        litellm_proxy=None,
        log_level="INFO",
        tiers=_default_tiers(),
    )


def test_sandbox_tiers_constant_matches_documented_set():
    """The set of sandbox tiers is the documented set; no silent drift."""
    assert _SANDBOX_TIERS == frozenset({"restricted", "elevated", "full_access"})


@pytest.mark.parametrize("tier_name", sorted(_SANDBOX_TIERS))
def test_sandbox_boundary_note_mentions_smolcode_host_only(tier_name):
    """Every sandbox tier's note must warn against `import smolcode`."""
    tiers = _default_tiers()
    note = sandbox_boundary_instructions(tiers[tier_name])
    assert "import smolcode" in note
    assert "HOST-side orchestrator" in note or "host-side orchestrator" in note
    assert "ModuleNotFoundError" in note  # tells the model what happens
    assert "Docker" in note
    assert "/workspace" in note  # tells the model where files live


@pytest.mark.parametrize("tier_name", sorted(_SANDBOX_TIERS))
def test_sandbox_boundary_note_lists_imports(tier_name):
    """Every import allowed by the tier appears in the note."""
    tiers = _default_tiers()
    tier = tiers[tier_name]
    note = sandbox_boundary_instructions(tier)
    # Each import the tier allows must be mentioned so the model knows
    # which `import X` lines won't be rejected.
    for module in tier.imports:
        assert module in note, f"{module!r} missing from {tier_name} note"


@pytest.mark.parametrize("tier_name", sorted(_SANDBOX_TIERS))
def test_sandbox_boundary_note_lists_commands(tier_name):
    """Every command allowed by the tier appears in the note."""
    tiers = _default_tiers()
    tier = tiers[tier_name]
    note = sandbox_boundary_instructions(tier)
    # The elevated tier allows 'curl', the full_access tier allows 'ssh',
    # etc. Each one must appear in the note so the model picks from the
    # allowlist, not from imagination.
    for cmd in tier.commands:
        assert cmd in note, f"{cmd!r} missing from {tier_name} note"


def test_sandbox_boundary_note_does_not_include_forbidden_import():
    """Negative check: the note must not advertise `smolcode` as usable."""
    tiers = _default_tiers()
    note = sandbox_boundary_instructions(tiers["elevated"])
    # The note must say `import smolcode` is forbidden, not that it's
    # allowed. We check the negation context (NEVER, NOT, raise, fail).
    lower = note.lower()
    assert ("never" in lower and "import smolcode" in lower) or (
        "not installed" in lower and "import smolcode" in lower
    )


def test_orchestrator_returns_empty_note():
    """The orchestrator runs on the host -- no boundary note needed.

    If we gave the orchestrator the same boundary note, the orchestrator
    model would be told `smolcode` is unavailable -- which is wrong,
    because the orchestrator runs with executor_type='local' on the
    host where smolcode IS installed.
    """
    orchestrator_tier = Tier(
        name="orchestrator",
        imports=("json",),
        commands=("python",),
        paths=(),
        network="none",
        network_allowlist=(),
        mcp_servers=(),
        max_steps=5,
        timeout_s=10.0,
        docker_image="n/a",
    )
    assert sandbox_boundary_instructions(orchestrator_tier) == ""


def test_unknown_tier_name_returns_empty_note():
    """A tier name not in the sandbox set (e.g. a future specialist) gets "".

    Specialists and other future tiers should be opt-in to the boundary
    note, not silently get it. Returning "" keeps the behavior explicit.
    """
    tier = Tier(
        name="future_specialist",
        imports=(),
        commands=(),
        paths=(),
        network="none",
        network_allowlist=(),
        mcp_servers=(),
        max_steps=5,
        timeout_s=10.0,
        docker_image="n/a",
    )
    assert sandbox_boundary_instructions(tier) == ""


def test_rejects_non_tier_argument():
    """Type contract: tier must be a Tier instance."""
    with pytest.raises(TypeError):
        sandbox_boundary_instructions("not a tier")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        sandbox_boundary_instructions(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# make_agent wires `instructions=` into CodeAgent
# ---------------------------------------------------------------------------


def _stub_model() -> MagicMock:
    """Build a MagicMock model -- make_agent never calls it."""
    m = MagicMock()
    m.generate = MagicMock(return_value="OK")
    return m


@pytest.mark.parametrize("tier_name", sorted(_SANDBOX_TIERS))
def test_make_agent_renders_boundary_note_in_system_prompt(tier_name):
    """The boundary note survives end-to-end through make_agent.

    We build a real CodeAgent (local executor, stub model) and inspect
    ``agent.system_prompt``. The default prompt template substitutes
    ``{{custom_instructions}}`` with whatever we passed via
    ``instructions=`` -- so the note MUST appear in the rendered string.

    This is the regression test for the user's reported failure: before
    decision 0021, the model received no warning about host-only modules,
    so it tried ``import smolcode`` and crashed. With the fix, the
    rendered prompt explicitly forbids the import.
    """
    tiers = _default_tiers()
    settings = _settings_with_local_executor()
    agent = make_agent(tiers[tier_name], settings, _stub_model())
    rendered = agent.system_prompt
    assert "Sandbox boundary" in rendered
    assert "import smolcode" in rendered
    # The default template slot must be substituted, not left raw.
    assert "{{custom_instructions}}" not in rendered
    # Tier-specific content must also survive.
    for module in tiers[tier_name].imports:
        assert module in rendered, f"{module!r} missing from rendered prompt for {tier_name}"


def test_make_agent_orchestrator_has_no_boundary_note():
    """Orchestrator's prompt must not contain the boundary note.

    Pins the orchestrator exemption: it runs on the host where smolcode
    IS installed, so the boundary note would be wrong.
    """
    orchestrator_tier = Tier(
        name="orchestrator",
        imports=("json",),
        commands=("python",),
        paths=(),
        network="none",
        network_allowlist=(),
        mcp_servers=(),
        max_steps=5,
        timeout_s=10.0,
        docker_image="n/a",
    )
    settings = _settings_with_local_executor()
    settings = Settings(
        workspace=settings.workspace,
        executor=settings.executor,
        provider=settings.provider,
        model=settings.model,
        litellm_proxy=settings.litellm_proxy,
        log_level=settings.log_level,
        tiers={**settings.tiers, "orchestrator": orchestrator_tier},
    )
    agent = make_agent(orchestrator_tier, settings, _stub_model())
    rendered = agent.system_prompt
    assert "Sandbox boundary" not in rendered
    assert "NEVER write" not in rendered


def test_make_agent_instructions_kwarg_is_actually_passed():
    """make_agent must pass `instructions=` to CodeAgent, not silently drop it.

    This test guards the wiring itself (without going through
    ``system_prompt`` rendering, which is smolagents' responsibility):
    we patch CodeAgent to capture kwargs and assert `instructions=` is
    in there for a sandbox tier and is "" for the orchestrator.
    """
    from smolagents import CodeAgent

    captured: dict = {}
    original_init = CodeAgent.__init__

    def spy_init(self, *args, **kwargs):
        captured.clear()
        captured.update(kwargs)
        return original_init(self, *args, **kwargs)

    CodeAgent.__init__ = spy_init  # type: ignore[method-assign]
    try:
        tiers = _default_tiers()
        settings = _settings_with_local_executor()
        # Elevated: boundary note expected
        make_agent(tiers["elevated"], settings, _stub_model())
        assert "instructions" in captured, "make_agent did not pass instructions= to CodeAgent"
        assert "Sandbox boundary" in captured["instructions"]
        # Orchestrator: empty string expected
        orchestrator_tier = Tier(
            name="orchestrator",
            imports=("json",),
            commands=("python",),
            paths=(),
            network="none",
            network_allowlist=(),
            mcp_servers=(),
            max_steps=5,
            timeout_s=10.0,
            docker_image="n/a",
        )
        settings2 = Settings(
            workspace=settings.workspace,
            executor=settings.executor,
            provider=settings.provider,
            model=settings.model,
            litellm_proxy=settings.litellm_proxy,
            log_level=settings.log_level,
            tiers={**settings.tiers, "orchestrator": orchestrator_tier},
        )
        make_agent(orchestrator_tier, settings2, _stub_model())
        assert "instructions" in captured
        assert captured["instructions"] == ""
    finally:
        CodeAgent.__init__ = original_init  # type: ignore[method-assign]
