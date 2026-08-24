# 0021 — Sandbox-Boundary Note for CodeAgent (bugfix)

**Date:** 2026-08-23
**Status:** SHIPPED — v1.7.1
**Type:** Bugfix (not a milestone; rolled into v1.7.1)
**Effort:** ~0.5 person-day, ~120 LOC Python + ~280 LOC tests

---

## 1. Context and motivation

A user opened the Web UI and asked the agent to **"create a simple todo
app to test the agent."** The agent failed with:

```
AgentError: ---------------------------------------------------------------------------
ModuleNotFoundError    Traceback (most recent call last)
Cell In[2], line 70
     66 read_file = _ReadFileTool()
     67
     68
     69 ---> 70 import smolcode
     71 import pathlib
     72 import os
ModuleNotFoundError: No module named 'smolcode'
```

The trace shows the LLM wrote `import smolcode` inside the elevated
container's Jupyter kernel gateway. That container's Python interpreter
is deliberately minimal: `smolagents` + `jupyter_client` + `ipykernel`
+ a curated stdlib per the tier's `imports` allowlist. **`smolcode` is
the host-side orchestrator and is NOT installed inside any sandbox
container** (by design — see `docs/architecture.md` 5.4 and `docs/
security.md` 9.1).

The same import worked fine from the **host** Python because
`smolcode` IS pip-installed there. But the user never opened a host
shell — they used the Web UI, which dispatches to the elevated
CodeAgent → Docker executor → kernel gateway inside the container.
That kernel gateway does NOT see the host's site-packages.

The error is also recoverable in principle: smolagents catches the
`ModuleNotFoundError` and feeds it back to the model as an Observation.
A clever model would notice the failure and retry without the import.
But in practice the LLM either looped or stalled; either way the user
saw a hard error.

---

## 2. Goals

G1. **Tell the model — explicitly — that `smolcode` is host-only.**
    The default smolagents `CodeAgent` system prompt template
    (`code_agent.yaml`) explains how to write code blobs but does not
    mention that the code runs inside a Docker container with a
    curated image. We need a tier-aware "sandbox boundary" instruction
    that lands in the model's first user-facing context.

G2. **No new dependencies, no prompt-template rewrite.** The fix
    must use the smolagents' existing `instructions=` kwarg (which
    substitutes into the `{{custom_instructions}}` slot of the default
    prompt template). Re-writing `prompt_templates` would mean
    maintaining ~10 KB of carefully-tuned prompt text and is
    out-of-scope for a bugfix.

G3. **Tier-aware.** The orchestrator runs on the host with
    `executor_type='local'`, where `smolcode` IS installed. It must NOT
    receive the boundary note (otherwise its model would be told
    `smolcode` is unavailable, which is false).

G4. **Pin the regression with tests.** A Web UI failure from a stale
    prompt would be silent; we need tests that fail loudly if the
    boundary note stops being injected.

G5. **Token-cheap.** The note is regenerated every `make_agent` call
    but only adds ~25 lines (~400 tokens) per sandbox-tier run. The
    orchestrator (which runs many delegations) adds zero.

---

## 3. Non-goals

- **Adding a `smolcode` shim inside the sandbox image.** Wrong
  direction: it would let the model call into host-only state from
  the sandbox, breaking the trust boundary. If the model legitimately
  needs a host capability (audit log, redact preview, etc.), the
  right fix is to expose it as a smolagents `Tool`, not as a Python
  import.
- **Replacing the entire `code_agent.yaml` template.** Out of scope
  for a bugfix; would require careful regression testing across all
  tiers.
- **Hard-blocking `import smolcode` at the executor level.** The
  executor is `smolagents.LocalPythonExecutor` (or its Docker variant),
  which already enforces `additional_authorized_imports`. Adding a
  second, parallel enforcement layer would not help: the model would
  still try the import and the executor would still raise — we'd
  only change which exception class the user sees. Better to fix the
  cause (the prompt) than the symptom (the exception).

---

## 4. Design

### 4.1 New module: `agents/prompting.py`

```python
def sandbox_boundary_instructions(tier: Tier) -> str:
    if tier.name not in {"restricted", "elevated", "full_access"}:
        return ""
    return (
        "Sandbox boundary (read carefully):\n"
        "\n"
        "The Python interpreter that runs your code blocks is INSIDE a Docker\n"
        "container. ... `smolcode` is the HOST-side orchestrator and is NOT\n"
        "installed inside this container. NEVER write `import smolcode` ...\n"
        f"You may only import these modules: {', '.join(tier.imports)}.\n"
        f"The shell `run` tool only accepts these commands: {', '.join(tier.commands)}.\n"
        "..."
    )
```

The note is plain text. It is regenerated per call so changes to the
tier's imports/commands are picked up automatically.

### 4.2 Wiring: `agents/base.py:make_agent`

```python
from .prompting import sandbox_boundary_instructions

def make_agent(tier, settings, model=None, ...):
    ...
    instructions = sandbox_boundary_instructions(tier)
    return CodeAgent(
        tools=tools,
        model=model,
        max_steps=steps,
        additional_authorized_imports=imports,
        executor_type=settings.executor,
        executor_kwargs=executor_kwargs,
        instructions=instructions,   # NEW
    )
```

`CodeAgent.__init__` accepts `**kwargs` which it forwards to
`MultiStepAgent.__init__`, where `instructions` is a documented
parameter. Confirmed in smolagents 1.27.0.dev0:

```
>>> MultiStepAgent.__init__ params: ..., 'instructions', ...
```

### 4.3 Tier behavior

| Tier | Executor | Boundary note? | Why |
|---|---|---|---|
| `restricted` | docker | Yes | Code runs inside minimal sandbox image. |
| `elevated` | docker | Yes | Same; iptables ENTRYPOINT (M16) but `smolcode` is still not in the image. |
| `full_access` | docker | Yes | Same. |
| `orchestrator` | local | **No** | Runs on host with `executor_type='local'`. `smolcode` IS importable there (the orchestrator doesn't actually use it, but the note would be misleading). |
| specialists (future) | varies | No (default) | Opt-in by tier name in `_SANDBOX_TIERS`. |

---

## 5. Validation

### 5.1 New tests: `tests/test_agent_prompting.py`

19 tests, organized in three groups:

- **Per-tier shape (10 tests):** the note mentions `smolcode` /
  `ModuleNotFoundError` / `Docker` / `/workspace` for every sandbox
  tier; lists every import and every command the tier allows.
- **Negative coverage (3 tests):** orchestrator returns `""`;
  unknown tier name returns `""`; non-Tier argument raises TypeError.
- **End-to-end wiring (5 tests):** `make_agent` passes `instructions=`
  to `CodeAgent`; rendered `agent.system_prompt` contains the note
  AND every tier import; orchestrator's rendered prompt does NOT
  contain the note.

### 5.2 Lint / format

- `ruff check src` → 0 errors
- `ruff format --check src` → clean

### 5.3 Full pytest

- `pytest src/smolcode/tests/ --basetemp=.pytest_tmp --no-cov` → all
  tests pass; +19 from the new file (M16 853 → 0021 **872** passed).

---

## 6. Risks and rollback

### 6.1 Risk: prompt bloat

Each sandbox tier run now sends ~25 extra lines (~400 tokens) to the
model. At 50 runs/day × 400 tokens × $0.00001/1K = ~$0.0002/day.
Negligible. **Status: ACCEPTED.**

### 6.2 Risk: orchestrator regression

If the orchestrator tier accidentally gets the boundary note (e.g. by
adding it to `_SANDBOX_TIERS`), the orchestrator model would be told
`smolcode` is unavailable — wrong, since the orchestrator runs on the
host. Mitigated by:
- The orchestrator tier has `name="orchestrator"`, which is not in
  `_SANDBOX_TIERS` by design.
- `test_make_agent_orchestrator_has_no_boundary_note` and
  `test_orchestrator_returns_empty_note` pin the behavior.

**Status: MITIGATED.**

### 6.3 Risk: prompt-template substitution breaks

If a future smolagents version changes the placeholder name (e.g. from
`{{custom_instructions}}` to `{{user_instructions}}`), the note stops
being injected and the bug regresses silently. Mitigated by:
- `test_make_agent_renders_boundary_note_in_system_prompt` asserts
  that `agent.system_prompt` contains "Sandbox boundary" — fails
  loudly if substitution breaks.

**Status: MITIGATED.**

### 6.4 Rollback

Revert commit `0021-bugfix-sandbox-import-error` (3 files: `agents/
prompting.py`, `agents/base.py`, `tests/test_agent_prompting.py`).
No data migration, no schema change, no breaking API. **Status:
REVERSIBLE.**

---

## 7. Files

| File | Change |
|---|---|
| `smolcode/src/smolcode/agents/prompting.py` | NEW — `sandbox_boundary_instructions(tier)` |
| `smolcode/src/smolcode/agents/base.py` | MOD — pass `instructions=` to `CodeAgent` |
| `smolcode/src/smolcode/tests/test_agent_prompting.py` | NEW — 19 tests |
| `smolcode/README.md` | MOD — sandbox-boundary note under "Trust tiers" |
| `docs/decisions/0021-bugfix-sandbox-import-error.md` | NEW — this doc |

---

## 8. Decision

**Ship.** The fix is small (~120 LOC), tier-aware, reversible, and
covered by 19 regression tests. It addresses the exact failure mode the
user reported and prevents the same class of bug (model importing
host-only modules) from recurring for any future host-side module.

---

## 9. Closeout

| Metric | Value |
|---|---|
| Shipped | 2026-08-23 (v1.7.1) |
| Test count delta | +19 (M16 853 → 0021 872) |
| Files | 2 NEW + 2 MOD + 1 NEW (decision doc) |
| Deviations | None |
| Risk register | R-0021-A prompt bloat ACCEPTED; R-0021-B orchestrator regression MITIGATED; R-0021-C template substitution MITIGATED |
