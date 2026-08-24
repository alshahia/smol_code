"""The orchestrator tier (M5, decision 0008).

The orchestrator is a CodeAgent whose only tools are
do_restricted_task, do_elevated_task, and do_full_task -- three thin
wrappers around the existing tier factories (restricted, elevated,
full_access). The orchestrator receives the user's task and decides
which tier to delegate to.

Per decision 0008 (D1, option B), the orchestrator is OPT-IN via the
--orchestrator CLI flag. 'smolcode "task"' (no flag) still defaults to
the restricted tier -- there is no silent behavior change for users who
do not pass the flag.

Per decision 0008 (D2, D3), the orchestrator's tools create a fresh
sub-agent for every delegation. Each sub-agent has its own tools,
imports, and destructive-op gate (M4.x). The orchestrator surfaces the
sub-agent's final answer back to itself.

Per decision 0008 (D4), every delegation emits a 'subagent' event in
the audit log so the delegation chain is recoverable after the fact.

Per decision 0008 (D5, D6), the orchestrator can also delegate to
specialists via do_specialist(name, task). v1 ships ONE bundled
specialist (deploy_staging, full_access tier with a narrowed toolset
of run + git_push). User-installed specialists are loaded from
~/.smolcode/specialists.toml.

Per decision 0008 (D9), the orchestrator's system prompt is fixed in
code: it tells the orchestrator what sub-agents and specialists are
available and to prefer restricted when uncertain.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from smolagents import CodeAgent, Tool

from ..config import Settings
from .base import make_agent
from .specialists import (
    SpecialistError,
    bundled_specialists,
    load_user_specialists,
    resolve_specialist,
)


_log = logging.getLogger(__name__)


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# System prompt (D9). Kept short so it fits comfortably in the model's
# context window even on small models. The exact list of specialists
# is interpolated at build time so the orchestrator knows what it can
# route to.
ORCHESTRATOR_PROMPT_TEMPLATE = """You are the smolcode orchestrator. Your job is to pick the right sub-agent for the user's task.

You have three sub-agents and {specialist_count} specialist(s) available:

- do_restricted_task(task) -- workspace-bound, read-mostly tools, no network. Use this for everyday coding tasks (write code, run tests, fix bugs, refactor).
- do_elevated_task(task) -- adds pip/npm/curl/jq/make, more stdlib imports. Use this when the task needs to install a package, run a build, or talk to a known local host.
- do_full_task(task) -- opt-in powerful tier with full command allowlist (ssh, docker, kubectl, terraform, aws, gcloud, az) and open network. Use this only when the task explicitly needs infra/cloud operations. The user has already been prompted once for full_access at run start, but per-tool destructive ops (git push, aws destroy, rm -rf, etc.) will still prompt again.
{specialist_block}
Rules:
1. If unsure which tier to pick, default to restricted. It is always safe.
2. Each sub-agent has its own confirmation gate for destructive ops. Do not try to "pre-approve" anything.
3. Sub-agents return their final answer as a string. Summarise that string back to the user.
4. Call exactly one sub-agent unless the task explicitly requires two distinct steps at different tiers (e.g., "build the project (elevated) then deploy to staging (full_access)").
5. Do NOT do the work yourself -- you have no tools for that. Delegate.
"""

ORCHESTRATOR_IMPORTS_NOTE = (
    "You may import these stdlib modules in your own reasoning: "
    "json, pathlib, ast, textwrap, re, typing, dataclasses.\n\n"
)


def _render_specialist_block(specialists):
    """Render the specialist roster for the orchestrator prompt."""
    if not specialists:
        return "There are no specialists available right now.\n"
    lines = []
    for s in specialists:
        lines.append(
            '- do_specialist(name="'
            + s.name
            + '", task=...) -- '
            + s.description
            + " (runs at the '"
            + s.tier
            + "' tier, tools="
            + repr(list(s.tools))
            + ")."
        )
    return "\n".join(lines) + "\n"


def _build_delegation_tool(tier_name, settings, model, audit_sink=None, outer_run=None):
    """Build one do_<tier>_task Tool instance with settings + model bound.

    Returns a NEW smolagents Tool subclass instance. The forward() method
    instantiates a fresh sub-agent (so each delegation is independent and
    sees the live M4.x session/audit state) and runs the task.

    Phase 0 (decision 0025): when ``outer_run`` is supplied, the tool
    publishes subagent.started / subagent.ended events on the outer
    run around its inner agent.run() so the SPA can render a nested
    <SubAgentBlock> in the event stream and the Inspector can show
    a "delegated to X tier" hint. The events fire even when the
    inner agent raises (started always fires; ended fires with
    status="error" inside the except block).
    """
    tier_obj = settings.tiers[tier_name]

    class _Delegate(Tool):
        name = "do_" + tier_name + "_task"
        description = (
            "Delegate a task to a fresh " + tier_name + "-tier sub-agent. "
            "Returns the sub-agent's final answer as a string. "
            "The sub-agent has access to: imports="
            + repr(list(tier_obj.imports))
            + ", commands="
            + repr(list(tier_obj.commands))
            + ", network="
            + repr(tier_obj.network)
            + ", max_steps="
            + str(tier_obj.max_steps)
            + ". Destructive ops (git push, destructive cloud CLIs, rm -rf, etc.) "
            "will prompt for confirmation at run time unless auto-approve is on."
        )
        inputs = {
            "task": {
                "type": "string",
                "description": (
                    "The task description to pass to the sub-agent. Be specific: "
                    "include the goal, any constraints, and what 'done' looks like."
                ),
            }
        }
        output_type = "string"

        def __init__(self):
            super().__init__()
            # Bind live references (not class attrs) so the tool sees fresh
            # settings + model + audit sink without re-instantiation.
            self._settings = settings
            self._model = model
            self._tier_name = tier_name
            self._tier = tier_obj
            self._audit_sink = audit_sink
            # Phase 0 (decision 0025): outer Run for sub-agent events.
            self._outer_run = outer_run
            from ..web.runs import EVT_SUBAGENT_ENDED, EVT_SUBAGENT_STARTED

            self._EVT_SUBAGENT_STARTED = EVT_SUBAGENT_STARTED
            self._EVT_SUBAGENT_ENDED = EVT_SUBAGENT_ENDED
            import uuid as _uuid

            self._uuid = _uuid

        def forward(self, task: str) -> str:
            if not isinstance(task, str) or not task.strip():
                raise ValueError("task must be a non-empty string")
            started = time.monotonic()
            sub_id = self._uuid.uuid4().hex
            # Phase 0 (decision 0025) + Phase 2 §6.4 fold-in: publish
            # subagent.started on the outer run so the SPA can render a
            # nested <SubAgentBlock>. The history list (``subagent_history``)
            # accumulates every delegation; ``append_subagent`` handles
            # the pending_lock + duplicate-id guard.
            if self._outer_run is not None:
                self._outer_run.append_subagent(
                    sub_id,
                    tier=self._tier_name,
                    started_at=started,
                )
                try:
                    self._outer_run.publish(
                        self._EVT_SUBAGENT_STARTED,
                        {
                            "parent_run_id": self._outer_run.id,
                            "subagent_id": sub_id,
                            "tier": self._tier_name,
                            "task_preview": task[:200],
                            "ts": _now_iso(),
                        },
                    )
                except Exception as _e:
                    _log.warning("subagent.started publish failed: %s", _e)
            _log.info(
                "orchestrator delegating to %s tier (task=%d chars)",
                self._tier_name,
                len(task),
            )
            agent = make_agent(self._tier, self._settings, self._model)
            status = "ok"
            err_kind = ""
            err_msg = ""
            try:
                answer = agent.run(task)
            except Exception as e:
                status = "error"
                err_kind = type(e).__name__
                err_msg = str(e)
                _log.error(
                    "subagent %s raised %s: %s",
                    self._tier_name,
                    err_kind,
                    e,
                )
                if self._audit_sink is not None:
                    try:
                        self._audit_sink.record(
                            "subagent",
                            tier=self._tier_name,
                            specialist="",
                            task=task,
                            answer="",
                            status="error",
                            error=err_kind,
                            message=err_msg,
                            duration_s=time.monotonic() - started,
                        )
                    except Exception:
                        pass
                raise
            finally:
                # Phase 0: ALWAYS publish ended (even on error) so the
                # SPA can render a closed SubAgentBlock + the run.error
                # field can reference the active sub-agent id.
                ended = time.monotonic()
                if self._outer_run is not None:
                    self._outer_run.close_subagent(sub_id, ended_at=ended)
                    try:
                        self._outer_run.publish(
                            self._EVT_SUBAGENT_ENDED,
                            {
                                "parent_run_id": self._outer_run.id,
                                "subagent_id": sub_id,
                                "tier": self._tier_name,
                                "status": status,
                                "duration_s": ended - started,
                                "error_kind": err_kind,
                                "error": err_msg,
                                "ts": _now_iso(),
                            },
                        )
                    except Exception as _e:
                        _log.warning("subagent.ended publish failed: %s", _e)
            duration = time.monotonic() - started
            if self._audit_sink is not None:
                try:
                    self._audit_sink.record(
                        "subagent",
                        tier=self._tier_name,
                        specialist="",
                        task=task,
                        answer=str(answer),
                        status="ok",
                        duration_s=duration,
                    )
                except Exception:
                    pass
            return str(answer)

    return _Delegate()


def _build_specialist_tool(settings, model, specialists, audit_sink=None, outer_run=None):
    """Build the do_specialist(name, task) tool.

    Resolves the specialist by name (bundled + user-installed), then
    instantiates a fresh sub-agent with the specialist's tool set and
    runs the task. Raises a clear error if the name is unknown.

    Phase 0 (decision 0025): when ``outer_run`` is supplied, the tool
    publishes subagent.started / subagent.ended events around the
    inner agent.run() (mirroring _build_delegation_tool).
    """
    catalog = {s.name: s for s in specialists}

    class _Specialist(Tool):
        name = "do_specialist"
        description = (
            "Delegate a task to a named specialist (a pre-configured sub-agent "
            "with a narrowed toolset). Use this when the task fits a specialist's "
            "purpose exactly. Specialists run inside a tier (most often full_access) "
            "but expose a smaller, intent-focused toolset. Available specialists: "
            + ", ".join(sorted(catalog.keys()))
            + "."
        )
        inputs = {
            "name": {
                "type": "string",
                "description": ("The specialist name. One of: " + ", ".join(sorted(catalog.keys())) + "."),
            },
            "task": {
                "type": "string",
                "description": ("The task description to pass to the specialist. Be specific."),
            },
        }
        output_type = "string"

        def __init__(self):
            super().__init__()
            self._catalog = catalog
            self._settings = settings
            self._model = model
            self._audit_sink = audit_sink
            # Phase 0 (decision 0025): outer Run for sub-agent events.
            self._outer_run = outer_run
            from ..web.runs import EVT_SUBAGENT_ENDED, EVT_SUBAGENT_STARTED

            self._EVT_SUBAGENT_STARTED = EVT_SUBAGENT_STARTED
            self._EVT_SUBAGENT_ENDED = EVT_SUBAGENT_ENDED
            import uuid as _uuid

            self._uuid = _uuid

        def forward(self, name: str, task: str) -> str:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("name must be a non-empty string")
            if not isinstance(task, str) or not task.strip():
                raise ValueError("task must be a non-empty string")
            spec = self._catalog.get(name.strip())
            if spec is None:
                raise SpecialistError(
                    "unknown specialist " + repr(name) + "; available: " + ", ".join(sorted(self._catalog.keys()))
                )
            _log.info(
                "orchestrator delegating to specialist %s (tier=%s, tools=%s, task=%d chars)",
                spec.tier,
                list(spec.tools),
                len(task),
            )
            tier_obj = self._settings.tiers[spec.tier]
            agent = _build_specialist_agent(
                spec,
                tier_obj,
                self._settings,
                self._model,
            )
            started = time.monotonic()
            sub_id = self._uuid.uuid4().hex
            # Phase 0 (decision 0025) + Phase 2 §6.4 fold-in: publish
            # subagent.started on the outer run (mirrors
            # _build_delegation_tool.forward).
            if self._outer_run is not None:
                self._outer_run.append_subagent(
                    sub_id,
                    tier=spec.tier,
                    specialist=spec.name,
                    started_at=started,
                )
                try:
                    self._outer_run.publish(
                        self._EVT_SUBAGENT_STARTED,
                        {
                            "parent_run_id": self._outer_run.id,
                            "subagent_id": sub_id,
                            "tier": spec.tier,
                            "specialist": spec.name,
                            "task_preview": task[:200],
                            "ts": _now_iso(),
                        },
                    )
                except Exception as _e:
                    _log.warning("subagent.started publish failed: %s", _e)
            status = "ok"
            err_kind = ""
            err_msg = ""
            try:
                answer = agent.run(task)
            except Exception as e:
                status = "error"
                err_kind = type(e).__name__
                err_msg = str(e)
                _log.error(
                    "specialist %s raised %s: %s",
                    spec.name,
                    err_kind,
                    e,
                )
                if self._audit_sink is not None:
                    try:
                        self._audit_sink.record(
                            "subagent",
                            tier=spec.tier,
                            specialist=spec.name,
                            task=task,
                            answer="",
                            status="error",
                            error=err_kind,
                            message=err_msg,
                            duration_s=time.monotonic() - started,
                        )
                    except Exception:
                        pass
                raise
            finally:
                # Phase 0: ALWAYS publish ended (even on error).
                ended = time.monotonic()
                if self._outer_run is not None:
                    self._outer_run.close_subagent(sub_id, ended_at=ended)
                    try:
                        self._outer_run.publish(
                            self._EVT_SUBAGENT_ENDED,
                            {
                                "parent_run_id": self._outer_run.id,
                                "subagent_id": sub_id,
                                "tier": spec.tier,
                                "specialist": spec.name,
                                "status": status,
                                "duration_s": ended - started,
                                "error_kind": err_kind,
                                "error": err_msg,
                                "ts": _now_iso(),
                            },
                        )
                    except Exception as _e:
                        _log.warning("subagent.ended publish failed: %s", _e)
            duration = time.monotonic() - started
            if self._audit_sink is not None:
                try:
                    self._audit_sink.record(
                        "subagent",
                        tier=spec.tier,
                        specialist=spec.name,
                        task=task,
                        answer=str(answer),
                        status="ok",
                        duration_s=duration,
                    )
                except Exception:
                    pass
            return str(answer)

    return _Specialist()


def _build_specialist_agent(spec, tier_obj, settings, model):
    """Instantiate a specialist sub-agent with a narrowed tool set.

    v1 narrows by NAME: keep only the tools whose Tool.name appears
    in spec.tools. Everything else (fs tools, git_status, etc.) is
    dropped. The sub-agent still uses the named tier's imports and
    commands -- so run is still filtered by the tier command policy,
    not by the specialist.
    """
    from ..tools import build_tools

    workspace_path = "/workspace" if settings.executor == "docker" else str(settings.workspace)
    full_tools = build_tools(tier_obj, settings, workspace_path=workspace_path, mcp_configs=[])
    keep = set(spec.tools)
    narrowed = [t for t in full_tools if t.name in keep]
    present = {t.name for t in full_tools}
    missing = sorted(keep - present)
    if missing:
        raise SpecialistError(
            "specialist "
            + repr(spec.name)
            + " requested tools "
            + repr(missing)
            + " which are not present at tier "
            + repr(tier_obj.name)
            + " (available: "
            + repr(sorted(present))
            + ")"
        )
    return make_agent(
        tier_obj,
        settings,
        model,
        tools_override=narrowed,
    )


def _list_specialists(settings):
    """Return bundled + user-installed specialists."""
    out = list(bundled_specialists())
    out.extend(load_user_specialists(settings))
    return out


def build_orchestrator_agent(
    settings,
    model,
    *,
    max_steps=None,
    audit_sink=None,
    specialists=None,
    outer_run=None,
):
    """Build the orchestrator CodeAgent.

    The orchestrator has 4 tools (D3, D5):
        - do_restricted_task
        - do_elevated_task
        - do_full_task
        - do_specialist (only if at least one specialist is available)

    Specialists are loaded from ~/.smolcode/specialists.toml (D10) +
    the bundled deploy_staging. Pass specialists=... to override
    (used by tests).

    The orchestrator uses the RESTRICTED tier's max_steps as a ceiling
    for its own reasoning. Override with max_steps if needed.
    """
    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")
    if specialists is None:
        specialists = _list_specialists(settings)
    # Validate every specialist's toolset against its tier's available tools.
    # Surfaces 'unknown tool' errors at orchestrator-build time (cheap)
    # rather than at first delegation (confusing).
    from ..tools import build_tools

    for _spec in specialists:
        _tier_obj = settings.tiers[_spec.tier]
        _workspace_path = "/workspace" if settings.executor == "docker" else str(settings.workspace)
        _present = {t.name for t in build_tools(_tier_obj, settings, workspace_path=_workspace_path, mcp_configs=[])}
        _missing = sorted(set(_spec.tools) - _present)
        if _missing:
            raise SpecialistError(
                "specialist "
                + repr(_spec.name)
                + " requested tools "
                + repr(_missing)
                + " which are not present at tier "
                + repr(_tier_obj.name)
                + " (available: "
                + repr(sorted(_present))
                + ")"
            )
    tools = [
        _build_delegation_tool("restricted", settings, model, audit_sink=audit_sink, outer_run=outer_run),
        _build_delegation_tool("elevated", settings, model, audit_sink=audit_sink, outer_run=outer_run),
        _build_delegation_tool("full_access", settings, model, audit_sink=audit_sink, outer_run=outer_run),
    ]
    if specialists:
        tools.append(_build_specialist_tool(settings, model, specialists, audit_sink=audit_sink, outer_run=outer_run))
    prompt = ORCHESTRATOR_PROMPT_TEMPLATE.format(
        specialist_count=len(specialists),
        specialist_block=_render_specialist_block(specialists),
    )
    steps = max_steps if max_steps is not None else settings.tiers["restricted"].max_steps
    # Orchestrator runs at the restricted tier's surface area for its own
    # reasoning (it does not execute user code itself -- it delegates). It
    # gets the same import allowlist as restricted (minimal stdlib) and
    # the local executor (the orchestrator's own code does not need a
    # Docker sandbox because it does not run user-written code).
    orchestrator_tier = settings.tiers["restricted"]
    agent = CodeAgent(
        tools=tools,
        model=model,
        max_steps=steps,
        additional_authorized_imports=list(orchestrator_tier.imports),
        executor_type="local",
    )
    # CodeAgent stores its prompt in agent.prompt_templates['system_prompt'].
    system_prompt = ORCHESTRATOR_IMPORTS_NOTE + prompt
    if hasattr(agent, "prompt_templates") and isinstance(agent.prompt_templates, dict):
        agent.prompt_templates["system_prompt"] = system_prompt
    return agent


__all__ = [
    "build_orchestrator_agent",
    "resolve_specialist",
    "SpecialistError",
]
