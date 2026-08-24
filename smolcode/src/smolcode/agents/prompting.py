"""Sandbox-boundary instructions injected into tier agents' system prompts.

The default smolagents ``CodeAgent`` system prompt explains how to write
code blobs but does NOT mention that the code runs inside a Docker
container with a curated Python image. When the LLM writes
``import smolcode`` (or other host-only modules) inside the sandbox, the
import fails with ``ModuleNotFoundError`` -- which is exactly the
failure mode a user hit when asking the Web UI to "create a simple
todo app": the model wrote ``import smolcode`` because it mistakenly
thought the orchestrator framework was installed in the sandbox.

This module provides a tier-aware ``custom_instructions`` string that
is injected into the ``{{custom_instructions}}`` slot of the smolagents
default prompt template (via the ``instructions=`` kwarg of
``CodeAgent.__init__`` / ``MultiStepAgent.__init__``). It explicitly
tells the LLM:

1. ``smolcode`` is the host-side orchestrator and is NOT installed in
   this sandbox. Do NOT ``import smolcode``.
2. The sandbox image is minimal (smolagents + jupyter kernel gateway +
   a curated set of imports/commands per tier). Use only the listed
   imports + the provided tools.
3. If a task legitimately needs host-side state (audit log, redact
   filter preview, config dump, etc.), that state must be exposed as a
   Tool -- the model should never try to reach it through ``import``.

The orchestrator tier is exempt: it runs on the host
(``executor_type='local'``) where ``smolcode`` IS installed, so the
boundary note would be misleading (and the orchestrator already has a
fixed prompt of its own; see ``agents/orchestrator.py``).

Design notes
------------
- The note is plain text. We deliberately do NOT use
  ``prompt_templates=`` because (a) smolagents' default system prompt
  is ~10 KB of carefully-tuned instruction we do not want to rewrite,
  and (b) the ``{{custom_instructions}}`` slot is exactly the right
  place to append tier-specific guidance.
- The note is regenerated every time ``make_agent`` is called, so
  changes to the tier's imports/commands are picked up automatically.
- The text is small (~25 lines) to keep token cost negligible.
"""

from __future__ import annotations

from ..config import Tier


# Tier names that run their code inside the elevated/restricted/full_access
# Docker sandbox. The orchestrator runs locally and is intentionally excluded.
_SANDBOX_TIERS = frozenset({"restricted", "elevated", "full_access"})


def sandbox_boundary_instructions(tier: Tier) -> str:
    """Return the sandbox-boundary note for ``tier``.

    Args:
        tier: The active tier. Must be a Tier instance.

    Returns:
        A multi-line string suitable for passing as the ``instructions=``
        kwarg of ``CodeAgent`` (or any ``MultiStepAgent`` subclass). For
        sandbox tiers, the note warns the model that ``smolcode`` is
        host-only and lists the tier's allowed imports + commands. For
        non-sandbox tiers (orchestrator), returns ``""`` so the model's
        view is unchanged.
    """
    if not isinstance(tier, Tier):
        raise TypeError("tier must be a Tier instance")
    if tier.name not in _SANDBOX_TIERS:
        return ""
    imports = sorted(tier.imports)
    commands = sorted(tier.commands)
    return (
        "Sandbox boundary (read carefully):\n"
        "\n"
        "The Python interpreter that runs your code blocks is INSIDE a Docker\n"
        "container. The image is minimal -- it has `smolagents`,\n"
        "`jupyter_client`, and `ipykernel` plus a curated set of stdlib\n"
        "modules. `smolcode` is the HOST-side orchestrator and is NOT\n"
        "installed inside this container. NEVER write `import smolcode`\n"
        "(or any other host-only module) in your code blocks -- it will\n"
        "raise ModuleNotFoundError and waste a step. Use the tools\n"
        "listed above (write_file, read_file, run, etc.) to interact\n"
        "with the host.\n"
        "\n"
        f"You may only import these modules: {', '.join(imports)}.\n"
        f"The shell `run` tool only accepts these commands: {', '.join(commands)}.\n"
        "\n"
        "The workspace at `/workspace` inside this container is bind-mounted\n"
        "to the host workspace; files you write there are visible to the\n"
        "host immediately. Network egress is restricted to the CIDR allowlist\n"
        "configured for this tier (see docs/security.md section 9 for M16).\n"
    )


__all__ = ["sandbox_boundary_instructions"]
