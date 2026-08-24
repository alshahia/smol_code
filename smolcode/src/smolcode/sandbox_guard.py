"""Runtime sandbox-boundary guard (decision 0023).

Layer A: check_sandbox_boundary() AST-scans a code block for any
reference to the host-only smolcode package and any cell that
tries to !pip install smolcode. The function returns a string
error message when the block is unsafe, or None when it is safe.
For sandbox tiers (restricted / elevated / full_access) every cell
model code is run through this check before it reaches the Jupyter
kernel; for orchestrator / non-sandbox tiers it is a no-op.

GuardedExecutor wraps a sandbox-tier python_executor:

* Layer A intercepts __call__(code_action) and raises
  SandboxBoundaryViolation when the model emits bad code, so
  smolagents catches it and feeds it back to the model as an
  observation.
* Layer B intercepts install_packages and run_code_raise_errors
  because smolagents calls those *directly* on the inner executor
  during send_tools, which side-steps __call__. Those two methods
  strip host-only references from infrastructure code (tool defs,
  package installs) so the Jupyter kernel never sees
  import smolcode or !pip install smolcode.

Invariants:
  0023-A: every sandbox-tier CodeAgent python_executor MUST be
    wrapped via wrap_executor(executor, tier) in make_agent()
    (no-op for orchestrator / local executor).
  0023-B: Layer A __call__ rejects bad code with
    SandboxBoundaryViolation so the message is fed back to model.
  0023-C: Layer B run_code_raise_errors sanitises infrastructure
    code and install_packages filters host-only packages;
    send_tools routes inner calls through layer B.
  0023-D: __getattr__ is plain delegation; do NOT rebind bound
    methods to the proxy (breaks __slots__-protected attribute
    assignments inside smolagents send_tools).
"""

from __future__ import annotations

import ast
import logging
import re


logger = logging.getLogger(__name__)

# -- tier semantics ----------------------------------------------------

SANDBOX_TIERS = frozenset({"restricted", "elevated", "full_access"})
"""Tiers where model-emitted code runs in a sandboxed Jupyter kernel."""

# -- helper: pip-magic patterns ---------------------------------------

_PIP_MAGIC_RES = [
    re.compile(r"^\s*[!%]\s*pip3?\s+install\b.*$"),
    re.compile(r"^\s*[!%]\s*python3?\s+-m\s+pip\s+install\b.*$"),
]
_ANY_PIP_MAGIC_RES = [
    re.compile(r"^\s*[!%]\s*pip3?\s+install\b"),
    re.compile(r"^\s*[!%]\s*python3?\s+-m\s+pip\s+install\b"),
]

_HOST_MODULES = frozenset({"smolcode"})
"""Module names that exist on the host but never in a sandbox kernel."""
_HOST_ONLY_PIP_PACKAGES = ("smolcode",)

# -- AST helpers -------------------------------------------------------


def _strip_magic_lines(code):
    """Return (python_only, magic_lines).

    Removes lines that are Jupyter line/cell magics so the rest can be
    parsed with ast.parse. The stripped lines are returned separately
    for downstream shell-magic detection.
    """
    py = []
    magic = []
    for line in code.splitlines():
        if line.lstrip().startswith(("!", "%")):
            magic.append(line)
        else:
            py.append(line)
    return "\n".join(py), magic


def _find_host_only_imports(code):
    """Return [(module_name, lineno), ...] for host-only imports."""
    py_only, _magic = _strip_magic_lines(code)
    if not py_only.strip():
        return []
    try:
        tree = ast.parse(py_only)
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _HOST_MODULES:
                    found.append((root, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            if node.module is None:
                continue
            root = node.module.split(".")[0]
            if root in _HOST_MODULES:
                found.append((root, node.lineno))
    return found


def _is_pip_magic(line):
    return any(pat.search(line) for pat in _ANY_PIP_MAGIC_RES)


def _find_host_only_pip_installs(code):
    """Return each pip-install shell magic that targets a host-only package."""
    hits = []
    for line in code.splitlines():
        if not _is_pip_magic(line):
            continue
        tokens = line.split()
        try:
            idx = tokens.index("install")
        except ValueError:
            continue
        pkgs = [t for t in tokens[idx + 1 :] if not t.startswith("-")]
        if any(p in _HOST_MODULES for p in pkgs):
            hits.append(line)
    return hits


def _resolve_tier_name(tier):
    """Return the tier .name; raise TypeError if not Tier-like."""
    name = getattr(tier, "name", None)
    if not isinstance(name, str):
        raise TypeError("tier must be a Tier-like object with a .name attribute, got " + repr(type(tier)))
    return name


# -- public API --------------------------------------------------------


def check_sandbox_boundary(code, tier):
    """Return a violation message if code crosses the sandbox boundary.

    code is the full cell body the model wants to execute. tier must
    be a Tier instance (or any object with a string .name attribute);
    orchestrator and other non-sandbox tiers always return None (the
    guard is a no-op there).

    Return value: None when the cell is safe; otherwise an error string
    the model can read and act on. The string starts with
    "SandboxBoundaryViolation" so downstream logging can spot it, and
    contains actionable hints telling the model to re-emit the cell
    without the bad import / install and to use workspace tools.
    """
    tier_name = _resolve_tier_name(tier)
    if tier_name not in SANDBOX_TIERS:
        return None
    if not code or not code.strip():
        return None

    imports = _find_host_only_imports(code)
    pip_hits = _find_host_only_pip_installs(code)
    if not imports and not pip_hits:
        return None

    parts = []
    parts.append("SandboxBoundaryViolation: blocked by runtime sandbox-boundary guard (tier=" + repr(tier_name) + ").")
    if imports:
        mods = sorted({m for m, _lineno in imports})
        parts.append(
            "Detected import of host-only module" + ("s" if len(mods) > 1 else "") + ": " + ", ".join(mods) + "."
        )
    if pip_hits:
        parts.append("Detected shell-magic pip install of host-only package: smolcode.")
    parts.append(
        "`smolcode` lives on the HOST-side orchestrator and is NOT installed inside the sandbox Jupyter kernel."
    )
    parts.append(
        "Re-emit the cell WITHOUT the host-only import / pip install, and use the workspace tools (write_file, patch_file, run, git_push) instead."
    )
    return " ".join(parts)


# -- layer-B line stripper -------------------------------------------

_HOST_ONLY_LINE_RE = re.compile(r"^\s*(?:from\s+smolcode(?:\.|\s).*|import\s+smolcode(?:\.|\s|$))")


def strip_host_only_lines(code):
    """Return code with host-only lines removed, preserving line numbers.

    When no host-only lines exist, return the original code unchanged so
    callers that pass through unmodified code do not lose trailing newlines
    or any other formatting the caller relied on.
    """
    if not code:
        return code
    out = []
    any_change = False
    for line in code.splitlines():
        bad = bool(_HOST_ONLY_LINE_RE.match(line))
        if not bad:
            for pat in _PIP_MAGIC_RES:
                if pat.search(line):
                    tokens = line.split()
                    try:
                        idx = tokens.index("install")
                    except ValueError:
                        break
                    pkgs = [t for t in tokens[idx + 1 :] if not t.startswith("-")]
                    if any(p in _HOST_MODULES for p in pkgs):
                        bad = True
                        any_change = True
                    break
        else:
            any_change = True
        out.append("" if bad else line)
    if not any_change:
        return code
    return "\n".join(out).rstrip("\n")


def _filter_packages(pkgs):
    return [p for p in pkgs if p not in _HOST_ONLY_PIP_PACKAGES]


# -- proxy -----------------------------------------------------------


class SandboxBoundaryViolation(RuntimeError):
    """Raised by GuardedExecutor.__call__ when model code crosses the boundary."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class _TierStub:
    """Minimal Tier stand-in used to round-trip a name back through check_sandbox_boundary."""

    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class GuardedExecutor:
    """Proxy around a sandbox-tier PythonExecutor enforcing the guard."""

    __slots__ = ("_inner", "_tier_name", "_orig_install", "_orig_run")

    def __init__(self, inner, tier):
        tier_name = _resolve_tier_name(tier)
        if tier_name not in SANDBOX_TIERS:
            raise ValueError("GuardedExecutor is only valid for sandbox tiers; got tier=" + repr(tier_name))
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_tier_name", tier_name)
        object.__setattr__(self, "_orig_install", getattr(inner, "install_packages", None))
        object.__setattr__(self, "_orig_run", getattr(inner, "run_code_raise_errors", None))

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __repr__(self):  # pragma: no cover
        return "GuardedExecutor(inner=" + repr(self._inner) + ", tier=" + repr(self._tier_name) + ")"

    # ---- Layer A: reject bad model code -----------------------------
    def __call__(self, code_action):
        code = getattr(code_action, "code", code_action)
        msg = check_sandbox_boundary(code or "", _TierStub(self._tier_name))
        if msg is not None:
            raise SandboxBoundaryViolation(msg)
        return self._inner(code_action)

    # ---- Layer B: sanitize infrastructure code ----------------------
    def install_packages(self, additional_imports):
        sanitized = _filter_packages(additional_imports)
        if not sanitized:
            return []
        if self._orig_install is None:
            return sanitized
        return self._orig_install(sanitized)

    def run_code_raise_errors(self, code):
        sanitized = strip_host_only_lines(code)
        if not sanitized or not sanitized.strip():
            try:
                from smolagents.local_python_executor import CodeOutput
            except Exception:
                return None
            return CodeOutput(output=None, logs="", is_final_answer=False)
        if self._orig_run is None:
            return None
        return self._orig_run(sanitized)

    # ---- smolagents paths that bypass __call__ ----------------------
    def send_tools(self, tools):
        inner = self._inner
        had_install = hasattr(inner, "install_packages")
        had_run = hasattr(inner, "run_code_raise_errors")
        if self._orig_install is not None:
            inner.install_packages = lambda pkgs, _real=self._orig_install: self._call_orig_install(_real, pkgs)
        else:
            inner.install_packages = lambda pkgs, _real=None: []
        if self._orig_run is not None:
            inner.run_code_raise_errors = lambda code, _real=self._orig_run: self._call_orig_run(_real, code)
        else:
            inner.run_code_raise_errors = lambda code, _real=None: None
        try:
            inner.send_tools(tools)
        finally:
            if had_install:
                inner.install_packages = self._orig_install
            else:
                try:
                    del inner.install_packages
                except AttributeError:
                    pass
            if had_run:
                inner.run_code_raise_errors = self._orig_run
            else:
                try:
                    del inner.run_code_raise_errors
                except AttributeError:
                    pass

    def send_variables(self, variables):
        self._inner.send_variables(variables)

    def _call_orig_install(self, real_callable, pkgs):
        sanitized = _filter_packages(pkgs)
        if not sanitized:
            return []
        return real_callable(sanitized)

    def _call_orig_run(self, real_callable, code):
        sanitized = strip_host_only_lines(code)
        if not sanitized or not sanitized.strip():
            try:
                from smolagents.local_python_executor import CodeOutput
            except Exception:
                return None
            return CodeOutput(output=None, logs="", is_final_answer=False)
        return real_callable(sanitized)


def wrap_executor(executor, tier):
    """Return a guarded executor for sandbox tiers; pass-through otherwise."""
    tier_name = _resolve_tier_name(tier)
    if tier_name not in SANDBOX_TIERS:
        return executor
    if isinstance(executor, GuardedExecutor):
        return executor
    return GuardedExecutor(executor, tier)


__all__ = [
    "SANDBOX_TIERS",
    "SandboxBoundaryViolation",
    "GuardedExecutor",
    "check_sandbox_boundary",
    "strip_host_only_lines",
    "wrap_executor",
]
