"""Tests for the runtime sandbox-boundary guard (decision 0023).

Decision 0021 added a tier-aware system-prompt note telling the LLM
``smolcode`` is host-only. In practice the model often ignores the
note and writes ``import smolcode`` or ``!pip install smolcode`` --
the kernel then raises ``ModuleNotFoundError`` and the model has no
hint about what to do next.

Decision 0023 adds **defense-in-depth** at the executor layer: a
``GuardedExecutor`` proxy around ``agent.python_executor`` that
pre-scans every code block and raises ``SandboxBoundaryViolation``
(``RuntimeError`` subclass) before the bad code reaches the kernel.
smolagents catches the exception in ``CodeAgent._step_stream`` and
feeds the message back to the model as an observation, so the next
step retries correctly.

These tests pin the behavior:

  1. ``check_sandbox_boundary``
     - detects ``import smolcode`` / ``from smolcode import X`` /
       ``from smolcode.X import Y`` via AST
     - does NOT flag ``import smolagents`` (smolagents IS installed
       in the sandbox)
     - does NOT flag ``from .sibling import X`` (relative imports)
     - does NOT flag strings / comments / docstrings mentioning
       smolcode (AST walk ignores them)
     - tolerates SyntaxError (returns None, lets the executor report)
     - detects Jupyter shell-magic ``!pip install smolcode`` /
       ``!pip3 install smolcode`` /
       ``!python -m pip install smolcode`` /
       ``%pip install smolcode`` etc.
     - does NOT flag ``!pip install numpy`` or
       ``!pip install pillow numpy smolagents``
     - returns None for non-sandbox tiers (orchestrator)
     - raises TypeError on non-Tier

  2. ``GuardedExecutor`` / ``wrap_executor``
     - proxy pre-checks code on __call__
     - bad code raises ``SandboxBoundaryViolation``
     - good code delegates to inner executor (verified via mock)
     - ``send_tools`` / ``send_variables`` / ``cleanup`` / arbitrary
       attribute access delegates to inner via __getattr__
     - non-sandbox tiers return the original executor unchanged
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from smolcode.config import Settings, Tier, _default_tiers
from smolcode.sandbox_guard import (
    SANDBOX_TIERS,
    GuardedExecutor,
    SandboxBoundaryViolation,
    check_sandbox_boundary,
    wrap_executor,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _restricted_tier() -> Tier:
    """Return the restricted tier from the default settings."""
    return _default_tiers()["restricted"]


def _elevated_tier() -> Tier:
    return _default_tiers()["elevated"]


def _full_access_tier() -> Tier:
    return _default_tiers()["full_access"]


def _orchestrator_tier() -> Tier:
    """Build a Tier named 'orchestrator' to assert guard is bypassed.

    The orchestrator does not appear in ``_default_tiers()`` -- it is
    constructed on-the-fly in ``agents/orchestrator.py`` -- so we build
    a stand-in Tier instance with the same shape here. The exact
    imports / commands / docker_image don't matter; the guard checks
    only ``tier.name``.
    """
    return Tier(
        name="orchestrator",
        imports=("json",),
        commands=("python",),
        paths=(".",),
        network="loopback",
        network_allowlist=(),
        mcp_servers=(),
        max_steps=10,
        timeout_s=60,
        docker_image="",
    )


# ---------------------------------------------------------------------------
# SANDBOX_TIERS constant
# ---------------------------------------------------------------------------


def test_sandbox_tiers_constant_matches_documented_set():
    assert SANDBOX_TIERS == frozenset({"restricted", "elevated", "full_access"})


# ---------------------------------------------------------------------------
# Tier gating
# ---------------------------------------------------------------------------


def test_check_returns_none_for_orchestrator_tier():
    """Orchestrator runs on the host -- the guard MUST be a no-op."""
    tier = _orchestrator_tier()
    bad = "import smolcode\n!pip install smolcode"
    assert check_sandbox_boundary(bad, tier) is None


def test_check_raises_typeerror_for_non_tier():
    with pytest.raises(TypeError):
        check_sandbox_boundary("import smolcode", "restricted")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "tier_fn",
    [_restricted_tier, _elevated_tier, _full_access_tier],
    ids=["restricted", "elevated", "full_access"],
)
def test_check_returns_message_for_every_sandbox_tier(tier_fn):
    """Every sandbox tier must flag the same host-only import."""
    msg = check_sandbox_boundary("import smolcode", tier_fn())
    assert msg is not None
    assert "SandboxBoundaryViolation" in msg
    assert "smolcode" in msg


# ---------------------------------------------------------------------------
# Python import detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "import smolcode",
        "import smolcode\nprint('hi')",
        "import smolcode as sc",
        "from smolcode import agents",
        "from smolcode.agents import base",
        "from smolcode.agents.base import make_agent",
        "if True:\n    import smolcode\n",
        "try:\n    import smolcode\nexcept ImportError:\n    pass",
    ],
)
def test_check_flags_smoldcode_imports(code):
    msg = check_sandbox_boundary(code, _restricted_tier())
    assert msg is not None, f"should have flagged: {code!r}"
    assert "SandboxBoundaryViolation" in msg


def test_check_flags_smoldcode_import_with_other_imports():
    """Mixed import line -- the smolcode import must still be flagged."""
    code = "import json, smolcode, os"
    msg = check_sandbox_boundary(code, _restricted_tier())
    assert msg is not None
    assert "smolcode" in msg


@pytest.mark.parametrize(
    "code",
    [
        "import smolagents",
        "from smolagents import CodeAgent",
        "from smolagents.tools import Tool",
        "import json, os, pathlib",
        "from pathlib import Path",
        "import numpy",
    ],
)
def test_check_does_not_flag_safe_imports(code):
    assert check_sandbox_boundary(code, _restricted_tier()) is None


def test_check_does_not_flag_smolagents_with_smoldcode_in_string():
    """A string mentioning smolcode does NOT count as an import."""
    code = '# A note: smolcode is host-only.\nmsg = "smolcode is not available here"\nimport smolagents\n'
    assert check_sandbox_boundary(code, _restricted_tier()) is None


def test_check_does_not_flag_comment_with_import_smoldcode():
    """Comments are ignored by the AST walk."""
    code = "# import smolcode -- this is just a comment\nimport json\n"
    assert check_sandbox_boundary(code, _restricted_tier()) is None


def test_check_does_not_flag_docstring_with_import_smoldcode():
    """Docstrings are ignored by the AST walk."""
    code = 'def f():\n    """This function avoids `import smolcode` because it is not available."""\n    return 42\n'
    assert check_sandbox_boundary(code, _restricted_tier()) is None


def test_check_does_not_flag_relative_import():
    """Relative imports are always sandbox-safe."""
    code = "from .sibling import foo\nfrom ..package import bar"
    assert check_sandbox_boundary(code, _restricted_tier()) is None


def test_check_tolerates_syntax_error():
    """A SyntaxError is NOT a sandbox violation -- let the executor
    surface the real error to the model with proper line context."""
    code = "def broken(:\n    return import smolcode"  # malformed
    # Should not raise, and should not flag (because we can't AST-parse it).
    assert check_sandbox_boundary(code, _restricted_tier()) is None


def test_check_detects_import_alongside_unrelated_shell_magic():
    """A cell that mixes `import smolcode` with an UNRELATED shell
    magic (`!ls`) must still flag the import. This is the regression
    that prompted the shell-magic stripping in _find_host_only_imports:
    `ast.parse` would otherwise reject the whole cell on the `!` line
    and miss the import on the preceding line."""
    code = "import smolcode\n!ls /workspace"
    msg = check_sandbox_boundary(code, _restricted_tier())
    assert msg is not None
    assert "import of host-only module" in msg


def test_check_detects_import_alongside_unrelated_pct_magic():
    """Same as above but with the `%` form of shell magic."""
    code = "from smolcode import x\n%pwd"
    msg = check_sandbox_boundary(code, _restricted_tier())
    assert msg is not None
    assert "import of host-only module" in msg


def test_check_empty_code_returns_none():
    assert check_sandbox_boundary("", _restricted_tier()) is None
    assert check_sandbox_boundary("\n\n# just comments\n", _restricted_tier()) is None


# ---------------------------------------------------------------------------
# pip-install shell-magic detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "!pip install smolcode",
        "!pip install smolcode numpy",
        "!pip install -q pillow smolcode numpy",
        "!pip3 install smolcode",
        "%pip install smolcode",
        "!python -m pip install smolcode",
        "!python3 -m pip install --quiet smolcode",
        "%python -m pip install smolcode",
        # Multi-line with a leading cell magic line
        "print('setup')\n!pip install smolcode\n",
    ],
)
def test_check_flags_pip_install_smoldcode(code):
    msg = check_sandbox_boundary(code, _restricted_tier())
    assert msg is not None, f"should have flagged: {code!r}"
    assert "SandboxBoundaryViolation" in msg
    assert "smolcode" in msg


@pytest.mark.parametrize(
    "code",
    [
        "!pip install numpy",
        "!pip install pillow numpy requests",
        "%pip install -q numpy",
        "!python -m pip install numpy",
        "!pip install smolagents",  # smolagents IS allowed in sandbox
    ],
)
def test_check_does_not_flag_safe_pip_install(code):
    assert check_sandbox_boundary(code, _restricted_tier()) is None


def test_check_detects_combined_import_and_pip_install():
    """Both violation types should appear in the error message."""
    code = "import smolcode\n!pip install smolcode numpy"
    msg = check_sandbox_boundary(code, _restricted_tier())
    assert msg is not None
    # Both violations should be listed.
    assert "import of host-only module" in msg
    assert "shell-magic pip install of host-only package" in msg


# ---------------------------------------------------------------------------
# Error message shape (pinned so a future refactor can't lose the
# actionable hint)
# ---------------------------------------------------------------------------


def test_error_message_mentions_host_only_and_recovery():
    """The model recovers in one step iff the message tells it:
    (a) smolcode is host-only, (b) re-emit without the import, and
    (c) use workspace tools."""
    msg = check_sandbox_boundary("import smolcode", _restricted_tier())
    assert msg is not None
    assert "HOST-side orchestrator" in msg
    assert "NOT installed" in msg
    assert "Re-emit" in msg or "re-emit" in msg
    assert "workspace tools" in msg.lower() or "write_file" in msg


# ---------------------------------------------------------------------------
# GuardedExecutor / wrap_executor
# ---------------------------------------------------------------------------


def test_wrap_executor_returns_guarded_for_sandbox_tier():
    """wrap_executor must swap the executor for a GuardedExecutor when
    the tier is in SANDBOX_TIERS."""
    inner = MagicMock()
    out = wrap_executor(inner, _restricted_tier())
    assert isinstance(out, GuardedExecutor)
    assert out is not inner


def test_wrap_executor_returns_inner_unchanged_for_orchestrator():
    """Orchestrator runs on host -- wrap is a no-op."""
    inner = MagicMock()
    out = wrap_executor(inner, _orchestrator_tier())
    assert out is inner


def test_wrap_executor_raises_typeerror_for_non_tier():
    with pytest.raises(TypeError):
        wrap_executor(MagicMock(), "restricted")  # type: ignore[arg-type]


def test_guarded_executor_blocks_bad_code():
    inner = MagicMock()
    gx = GuardedExecutor(inner, _restricted_tier())
    with pytest.raises(SandboxBoundaryViolation) as exc:
        gx("import smolcode")
    assert "SandboxBoundaryViolation" in str(exc.value)
    # Inner must NOT have been called.
    inner.assert_not_called()


def test_guarded_executor_passes_through_good_code():
    """Good code is delegated to the inner executor verbatim."""
    inner = MagicMock(return_value="ok-output")
    gx = GuardedExecutor(inner, _restricted_tier())
    out = gx("x = 1 + 1\nprint(x)")
    assert out == "ok-output"
    inner.assert_called_once_with("x = 1 + 1\nprint(x)")


def test_guarded_executor_passes_through_when_inner_raises():
    """An exception from the inner executor is propagated unchanged --
    the guard must not wrap or swallow downstream errors."""
    inner = MagicMock(side_effect=RuntimeError("kernel timeout"))
    gx = GuardedExecutor(inner, _restricted_tier())
    with pytest.raises(RuntimeError, match="kernel timeout"):
        gx("x = 1")


def test_guarded_executor_delegates_send_tools():
    """send_tools must reach the inner executor (smolagents calls it
    during setup)."""
    inner = MagicMock()
    gx = GuardedExecutor(inner, _restricted_tier())
    gx.send_tools({"foo": "bar"})
    inner.send_tools.assert_called_once_with({"foo": "bar"})


def test_guarded_executor_delegates_send_variables():
    inner = MagicMock()
    gx = GuardedExecutor(inner, _restricted_tier())
    gx.send_variables({"x": 1})
    inner.send_variables.assert_called_once_with({"x": 1})


def test_guarded_executor_delegates_cleanup():
    inner = MagicMock()
    gx = GuardedExecutor(inner, _restricted_tier())
    gx.cleanup()
    inner.cleanup.assert_called_once_with()


def test_guarded_executor_delegates_arbitrary_attribute():
    """Smolagents may grow new methods on PythonExecutor in future
    versions; __getattr__ must forward anything that isn't already on
    the proxy."""
    inner = MagicMock()
    inner.future_method.return_value = "delegated"
    gx = GuardedExecutor(inner, _restricted_tier())
    assert gx.future_method() == "delegated"
    inner.future_method.assert_called_once_with()


def test_guarded_executor_has_no_attribute_not_on_inner():
    """If the inner doesn't have an attribute, AttributeError bubbles
    up cleanly (rather than returning None)."""
    inner = MagicMock(spec=[])  # spec=[] -> no attributes
    gx = GuardedExecutor(inner, _restricted_tier())
    with pytest.raises(AttributeError):
        _ = gx.no_such_method


def test_guarded_executor_blocks_pip_install_smoldcode():
    """The actual failure mode the user hit: the Jupyter cell starts
    with ``!pip install smolcode`` and the kernel never returns."""
    inner = MagicMock()
    gx = GuardedExecutor(inner, _restricted_tier())
    with pytest.raises(SandboxBoundaryViolation):
        gx("!pip install smolcode numpy pillow")
    inner.assert_not_called()


def test_sandbox_boundary_violation_is_runtime_error():
    """smolagents' CodeAgent._step_stream catches ``except Exception``
    around ``self.python_executor(...)`` -- our exception must subclass
    ``RuntimeError`` (which is an ``Exception``) so it is caught and
    the message is fed back to the model as an observation."""
    assert issubclass(SandboxBoundaryViolation, RuntimeError)
    err = SandboxBoundaryViolation("test")
    assert isinstance(err, RuntimeError)
    # And it's catchable as Exception (smolagents' handler).
    try:
        raise err
    except Exception as e:
        assert str(e) == "test"


# ---------------------------------------------------------------------------
# Smoke test: end-to-end through make_agent()
# ---------------------------------------------------------------------------


def _settings_with_local_executor() -> Settings:
    """Minimal Settings (local executor, no I/O) for unit tests."""
    return Settings(
        workspace=".",
        executor="local",
        provider="opencode-go",
        model="stub-model",
        litellm_proxy=None,
        log_level="INFO",
        tiers=_default_tiers(),
    )


def test_make_agent_wraps_executor_for_sandbox_tier():
    """End-to-end: make_agent() returns an agent whose
    python_executor is a GuardedExecutor, and bad code raises
    SandboxBoundaryViolation at __call__ time."""
    from smolcode.agents.base import make_agent

    class DummyModel:
        model_id = "dummy"

        def generate(self, *args, **kwargs):  # pragma: no cover - never reached
            raise NotImplementedError

    agent = make_agent(tier=_restricted_tier(), settings=_settings_with_local_executor(), model=DummyModel())
    assert isinstance(agent.python_executor, GuardedExecutor)
    with pytest.raises(SandboxBoundaryViolation):
        agent.python_executor("import smolcode")
    # Cleanup the docker executor we accidentally started.
    try:
        agent.python_executor.cleanup()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Regex coverage of pip-magic patterns (sanity check on the pattern
# compilation itself, so a future refactor doesn't silently drop a
# variant).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "!pip install smolcode",
        "!pip3 install smolcode",
        "%pip install smolcode",
        "!python -m pip install smolcode",
        "!python3 -m pip install smolcode",
        "%python -m pip install smolcode",
    ],
)
def test_pip_magic_patterns_each_match(code):
    """Every documented pip-magic variant is caught by the regex set."""
    from smolcode.sandbox_guard import _PIP_MAGIC_RES

    assert any(pat.search(code) for pat in _PIP_MAGIC_RES), f"no pattern matched {code!r}"


# ---------------------------------------------------------------------------
# strip_host_only_lines (layer B sanitizer) tests
# ---------------------------------------------------------------------------


def test_strip_host_only_lines_strips_import_smoldcode():
    from smolcode.sandbox_guard import strip_host_only_lines

    out = strip_host_only_lines("import smolcode\nprint('hi')")
    assert "import smolcode" not in out
    assert "print('hi')" in out


def test_strip_host_only_lines_strips_from_smoldcode():
    from smolcode.sandbox_guard import strip_host_only_lines

    out = strip_host_only_lines("from smolcode.session import current_session")
    assert "smolcode" not in out


def test_strip_host_only_lines_strips_pip_install_smoldcode():
    from smolcode.sandbox_guard import strip_host_only_lines

    out = strip_host_only_lines("!pip install pillow smolcode numpy")
    assert "smolcode" not in out


def test_strip_host_only_lines_strips_from_smoldcode_dotted():
    from smolcode.sandbox_guard import strip_host_only_lines

    out = strip_host_only_lines("from smolcode.agents.base import make_agent\n")
    assert "smolcode" not in out


def test_strip_host_only_lines_keeps_smolagents():
    from smolcode.sandbox_guard import strip_host_only_lines

    out = strip_host_only_lines("import smolagents\nprint('hi')")
    assert "import smolagents" in out
    assert "print('hi')" in out


def test_strip_host_only_lines_keeps_pip_install_numpy():
    from smolcode.sandbox_guard import strip_host_only_lines

    out = strip_host_only_lines("!pip install numpy pandas")
    assert "numpy" in out
    assert "pandas" in out


def test_strip_host_only_lines_keeps_safe_imports():
    from smolcode.sandbox_guard import strip_host_only_lines

    code = "import json\nimport os\nimport pathlib\nfrom collections import OrderedDict"
    out = strip_host_only_lines(code)
    assert "import json" in out
    assert "import os" in out
    assert "import pathlib" in out
    assert "from collections import OrderedDict" in out


def test_strip_host_only_lines_handles_all_pip_magic_variants():
    from smolcode.sandbox_guard import strip_host_only_lines

    for code in (
        "!pip install smolcode",
        "!pip3 install smolcode",
        "%pip install smolcode",
        "%pip3 install smolcode",
        "!python -m pip install smolcode",
        "!python3 -m pip install smolcode",
        "%python -m pip install smolcode",
        "%python3 -m pip install smolcode",
    ):
        out = strip_host_only_lines(code)
        assert "smolcode" not in out, f"failed for {code!r}"


def test_strip_host_only_lines_handles_mixed_cell():
    """Mixed cell: import + pip + good code. Strip bad lines, keep good."""
    from smolcode.sandbox_guard import strip_host_only_lines

    code = "import json\n!pip install smolcode\nimport smolcode\nprint('hello')\n"
    out = strip_host_only_lines(code)
    assert "import json" in out
    assert "print('hello')" in out
    assert "import smolcode" not in out
    assert "!pip install smolcode" not in out


def test_strip_host_only_lines_preserves_line_numbers():
    """Stripped lines are replaced with a blank line so Jupyter error
    messages still reference the original line numbers."""
    from smolcode.sandbox_guard import strip_host_only_lines

    code = "x = 1\nimport smolcode\ny = 2\n"
    out = strip_host_only_lines(code)
    # Should have 3 logical lines (with blanks for stripped ones)
    # Verify "y = 2" is still present
    assert "y = 2" in out
    # Verify blank line replaces the import
    assert "import smolcode" not in out
    # Verify x = 1 still present
    assert "x = 1" in out


def test_strip_host_only_lines_empty_input():
    from smolcode.sandbox_guard import strip_host_only_lines

    assert strip_host_only_lines("") == ""


def test_strip_host_only_lines_only_bad_lines_returns_blank_lines():
    """When every line is host-only, the result is just blank lines."""
    from smolcode.sandbox_guard import strip_host_only_lines

    code = "import smolcode\nfrom smolcode.x import Y\n!pip install smolcode"
    out = strip_host_only_lines(code)
    assert "smolcode" not in out
    assert out.strip() == ""


# ---------------------------------------------------------------------------
# GuardedExecutor.run_code_raise_errors (layer B) tests
# ---------------------------------------------------------------------------


class _FakeInner:
    """Minimal stand-in for smolagents' DockerExecutor."""

    def __init__(self):
        self.calls = []
        self.cleanup_called = False
        self._should_raise = False

    def __call__(self, code):
        self.calls.append(("call", code))
        if self._should_raise:
            raise RuntimeError("inner failed: " + code[:50])
        return {"output": "ok:" + code[:20], "is_final_answer": False}

    def send_tools(self, tools):
        self.calls.append(("send_tools", tools))

    def send_variables(self, variables):
        self.calls.append(("send_variables", variables))

    def run_code_raise_errors(self, code):
        self.calls.append(("run_code_raise_errors", code))
        if self._should_raise:
            raise RuntimeError("inner failed: " + code[:50])
        return {"output": "ok:" + code[:50], "is_final_answer": False, "logs": ""}

    def install_packages(self, additional_imports):
        self.calls.append(("install_packages", list(additional_imports)))
        return list(additional_imports)

    def cleanup(self):
        self.cleanup_called = True


@pytest.fixture
def sandbox_tier():
    from smolcode.config import _default_tiers

    return _default_tiers()["restricted"]


@pytest.fixture
def orch_tier():
    # Orchestrator is NOT in _default_tiers. Use a synthetic Tier for the test.
    from smolcode.config import Tier

    return Tier(
        name="orchestrator",
        imports=("json",),
        commands=("python",),
        paths=(),
        network="none",
        network_allowlist=(),
        mcp_servers=(),
        max_steps=12,
        timeout_s=120.0,
        docker_image="smolcode:restricted",
        uploads="read",
    )


def test_run_code_raise_errors_strips_host_only_lines(sandbox_tier):
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    proxy = wrap_executor(inner, sandbox_tier)
    # Code with import smolcode at the top + safe code below (mimics
    # the auto-generated tool definition code)
    code = "from typing import Any\nimport smolcode\nimport os\nclass _Foo:\n    name = 'foo'\n"
    result = proxy.run_code_raise_errors(code)
    # Inner was called
    assert any(call[0] == "run_code_raise_errors" for call in inner.calls)
    called_code = inner.calls[-1][1]
    # import smolcode was stripped from what reached inner
    assert "import smolcode" not in called_code
    assert "from typing import Any" in called_code
    assert "import os" in called_code
    assert "class _Foo" in called_code
    # And the result is what inner returned
    assert result["output"].startswith("ok:")


def test_run_code_raise_errors_unchanged_when_no_host_only(sandbox_tier):
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    proxy = wrap_executor(inner, sandbox_tier)
    code = "print('hi')\nx = 1\n"
    result = proxy.run_code_raise_errors(code)
    assert inner.calls[-1][1] == code
    assert result["output"].startswith("ok:")


def test_run_code_raise_errors_returns_empty_when_all_lines_stripped(sandbox_tier):
    """When ALL lines are host-only, return a benign empty CodeOutput
    without calling inner (so smolagents doesn't get a confusing
    ModuleNotFoundError from an empty cell)."""
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    proxy = wrap_executor(inner, sandbox_tier)
    code = "import smolcode\nfrom smolcode.x import Y\n"
    result = proxy.run_code_raise_errors(code)
    # Inner was NOT called
    assert inner.calls == []
    # Result is a benign empty CodeOutput
    assert result is not None
    if hasattr(result, "logs"):
        # CodeOutput dataclass
        assert result.logs == ""
        assert result.is_final_answer is False
    else:
        # dict fallback
        assert result.get("output") in (None, "")
        assert result.get("logs") == ""


def test_run_code_raise_errors_passes_through_inner_exception(sandbox_tier):
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    inner._should_raise = True
    proxy = wrap_executor(inner, sandbox_tier)
    with pytest.raises(RuntimeError, match="inner failed"):
        proxy.run_code_raise_errors("print('hi')")


def test_run_code_raise_errors_noop_for_orchestrator(orch_tier):
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    proxy = wrap_executor(inner, orch_tier)
    # Orchestrator tier: no wrap (returns inner unchanged)
    assert proxy is inner


# ---------------------------------------------------------------------------
# GuardedExecutor.install_packages (layer B) tests
# ---------------------------------------------------------------------------


def test_install_packages_filters_smoldcode(sandbox_tier):
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    proxy = wrap_executor(inner, sandbox_tier)
    out = proxy.install_packages(["smolcode", "numpy", "smolcode"])
    # smolcode filtered out
    assert out == ["numpy"]
    # Inner was called with the filtered list
    last_call = inner.calls[-1]
    assert last_call[0] == "install_packages"
    assert last_call[1] == ["numpy"]


def test_install_packages_empty_after_filter(sandbox_tier):
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    proxy = wrap_executor(inner, sandbox_tier)
    out = proxy.install_packages(["smolcode"])
    # All filtered out: inner should NOT be called (mirror inner no-op)
    assert out == []
    assert inner.calls == []


def test_install_packages_passes_through_when_safe(sandbox_tier):
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    proxy = wrap_executor(inner, sandbox_tier)
    out = proxy.install_packages(["numpy", "pandas"])
    assert out == ["numpy", "pandas"]
    assert inner.calls[-1] == ("install_packages", ["numpy", "pandas"])


def test_install_packages_noop_for_orchestrator(orch_tier):
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    proxy = wrap_executor(inner, orch_tier)
    assert proxy is inner


# ---------------------------------------------------------------------------
# Tool-requirements integration (the actual user bug)
# ---------------------------------------------------------------------------


def test_guarded_executor_blocks_send_tools_bypass_path(sandbox_tier):
    """Regression test for the 0023 followup bug: smolagents' send_tools
    called install_packages + run_code_raise_errors DIRECTLY on the
    inner executor, bypassing __call__ and letting !pip install smolcode
    run in Jupyter. Now GuardedExecutor.install_packages filters and
    run_code_raise_errors strips."""
    from smolcode.sandbox_guard import wrap_executor

    inner = _FakeInner()
    proxy = wrap_executor(inner, sandbox_tier)

    # Simulate smolagents' send_tools flow exactly as remote_executors.py does:
    # 1. install_packages(['smolcode'])
    out = proxy.install_packages(["smolcode"])
    assert out == []
    assert inner.calls == []

    # 2. run_code_raise_errors(<tool definition code with import smolcode>)
    tool_def_code = (
        "from typing import Any\n"
        "import smolcode\n"
        "import os\n\n"
        "class _WriteFileTool(Tool):\n"
        "    name = 'write_file'\n"
        "    def forward(self, path, content):\n"
        "        return 'wrote'\n"
    )
    proxy.run_code_raise_errors(tool_def_code)
    # Inner was called once (for run_code_raise_errors) with the sanitized code
    assert len(inner.calls) == 1
    assert inner.calls[0][0] == "run_code_raise_errors"
    sent_code = inner.calls[0][1]
    assert "import smolcode" not in sent_code
    assert "import os" in sent_code
    assert "class _WriteFileTool" in sent_code
    assert "from typing import Any" in sent_code
