"""smolcode CLI.

Flags (see docs/architecture.md 8):
    --tier           "restricted" | "elevated" | "full_access"
    --provider       "opencode-go" | "MiniMax" | "openai" | "anthropic" | "custom"
    --model          model id string
    --litellm-proxy  URL (overrides api_base)
    --workspace      path
    --print-config   print resolved settings as YAML and exit
    --smoke          use a stub model (no network, no key required)
    --max-steps      override tier max_steps

Non-interactive run:  smolcode "task description"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml

from . import __version__
from .agents.elevated import build_elevated_agent
from .agents.full_access import build_full_access_agent
from .agents.orchestrator import build_orchestrator_agent
from .agents.restricted import build_restricted_agent
from .audit import AuditSink
from .checkpoint import create_checkpoint, format_checkpoint_message
from .config import ConfigError, load_settings
from .config import as_dict as settings_to_dict
from .confirm import (
    ConfirmationDenied,
    confirm_full_access,
    prompt_destructive,
    resolve_destructive_timeout_s,
    resolve_timeout_s,
)
from .models import MissingAPIKey, _StubLiteLLMModel, build_model
from .session import DestructiveDecision, SessionState, set_session


def _build_parser():
    p = argparse.ArgumentParser(
        prog="smolcode",
        description="Local/Docker multi-agent coding assistant built on smolagents.",
    )
    p.add_argument("task", nargs="?", default=None, help="Task description for the agent.")
    p.add_argument("--tier", choices=("restricted", "elevated", "full_access"), default="restricted")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--litellm-proxy", default=None)
    p.add_argument("--workspace", type=Path, default=None)
    p.add_argument("--print-config", action="store_true", help="Print resolved config as YAML and exit.")
    p.add_argument("--smoke", action="store_true", help="Run with a stub model (offline).")
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument(
        "--mcp-config",
        type=Path,
        default=None,
        help="Path to mcp_config.json (M3). Default: no MCP servers.",
    )
    p.add_argument(
        "--confirm-timeout",
        type=float,
        default=None,
        help=(
            "Timeout in seconds for the full_access confirmation prompt (M4). "
            "Default 30; <=0 means require y even on instant-decline. "
            "Env: SMOLCODE_FULL_ACCESS_CONFIRM_TIMEOUT_S."
        ),
    )
    p.add_argument(
        "--audit-log",
        type=Path,
        default=None,
        help=(
            "Override audit log path (M4). Default: <cwd>/logs/audit.jsonl. "
            "Env: SMOLCODE_AUDIT_LOG. The log is always opened append-only."
        ),
    )
    p.add_argument(
        "--no-audit",
        action="store_true",
        help="Skip audit logging for this run (M4; not recommended for full_access).",
    )
    p.add_argument(
        "--auto-approve-destructive",
        action="store_true",
        help=(
            "Skip per-tool destructive-op confirmation for this run (M4.x). "
            "Env: SMOLCODE_AUTO_APPROVE_DESTRUCTIVE=1. Can also be enabled "
            "mid-run by typing `a` (all) at any destructive prompt."
        ),
    )
    p.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Skip the git checkpoint before a full_access run (M4.x).",
    )
    p.add_argument(
        "--destructive-confirm-timeout",
        type=float,
        default=None,
        help=(
            "Timeout in seconds for per-tool destructive-op confirmation "
            "(M4.x). Default 30. Env: SMOLCODE_DESTRUCTIVE_CONFIRM_TIMEOUT_S."
        ),
    )
    p.add_argument(
        "--orchestrator",
        action="store_true",
        help=(
            "Build the orchestrator agent (M5, decision 0008). The orchestrator "
            "delegates the user's task to one of do_restricted_task / "
            "do_elevated_task / do_full_task (or do_specialist). Default (no flag) "
            "keeps the existing --tier behavior. The two flags are orthogonal: "
            "--tier selects a tier directly; --orchestrator lets the orchestrator "
            "decide. If both are set, --orchestrator wins (D11)."
        ),
    )
    p.add_argument("--version", action="version", version=f"smolcode {__version__}")
    return p


def main(argv=None):
    # If argv was not passed (i.e. we were invoked as an entry-point
    # script that called main() with no args), read it from sys.argv.
    # The setuptools entry-point wrapper does this for us, but the
    # python -m smolcode path does NOT, and the [uploads] / [web]
    # pre-dispatch needs the actual argv to fire.
    if argv is None:
        argv = sys.argv[1:]
    # M8: uploads subcommand pre-dispatch. If the very first argv
    # element is "uploads", handle it without ever building the
    # main parser (so `uploads list` / `uploads clean --yes` etc.
    # don't trip argparse's "unrecognized arguments" error).
    # M12 (decision 0015): `models` is the third subcommand, mirrors
    # the SPA's /api/providers + /api/providers/{id}/models catalog.
    if isinstance(argv, (list, tuple)) and len(argv) >= 1:
        if argv[0] == "uploads":
            return _uploads_main(list(argv))
        if argv[0] == "web":
            return _web_main(list(argv))
        if argv[0] == "models":
            return _models_main(list(argv))
        if argv[0] == "audit":
            return _audit_main(list(argv))

    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("SMOLCODE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # M7: scrub known secret prefixes (sk-, sk-ant-, hf_, ghp_) from
    # every log record before the formatter reads it. Decision 0009.
    from smolcode import redact as _redact

    _redact.install_redact_filter()

    # --print-config is allowed without a task and without a key
    if args.print_config:
        try:
            settings = load_settings(cli_overrides=_cli_overrides(args))
        except ConfigError as e:
            print(f"config error: {e}", file=sys.stderr)
            return 2
        print(yaml.safe_dump(settings_to_dict(settings), sort_keys=False))
        return 0

    if not args.task:
        parser.error("task is required unless --print-config is set")

    try:
        settings = load_settings(cli_overrides=_cli_overrides(args))
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    if args.smoke:
        settings = settings.with_executor("local")
        model = _StubLiteLLMModel()
    else:
        try:
            model = build_model(settings, model_override=args.model, preset_name=args.provider)
        except MissingAPIKey as e:
            print(f"missing api key: {e}", file=sys.stderr)
            return 3

    # M4 + M5: per-tier agent factory dispatch.
    # Per decision 0008 (D8, D11): --orchestrator overrides --tier.
    if args.orchestrator:
        factory = build_orchestrator_agent
        orchestrator_mode = True
    else:
        factory = {
            "restricted": build_restricted_agent,
            "elevated": build_elevated_agent,
            "full_access": build_full_access_agent,
        }[args.tier]
        orchestrator_mode = False

    # M4: full_access confirmation prompt (30s hard y/N, configurable).
    # Fires BEFORE the agent is built so a denial never spends tokens.
    # M5 (D11): when --orchestrator is set, the orchestrator decides the
    # tier; the user has already opted in by passing --orchestrator. Skip
    # the full_access prompt in that case. Sub-agents still hit the M4.x
    # per-tool destructive gate when they call git_push / etc.
    if args.tier == "full_access" and not orchestrator_mode:
        try:
            timeout_s = resolve_timeout_s(args.confirm_timeout)
            confirm_full_access(timeout_s=timeout_s)
        except ConfirmationDenied as e:
            print(f"aborted: {e}", file=sys.stderr)
            return 4

    # M4.x: git checkpoint before any full_access run. Skipped if
    # workspace is not a git repo OR is clean OR --no-checkpoint is
    # passed. Result is always recorded in the audit log + printed to
    # stderr so the user has the stash ref for `git stash pop`.
    checkpoint_result = None
    # M5: orchestrator_mode defers the tier decision, so the checkpoint
    # only runs if the orchestrator later routes to full_access. v1 keeps
    # it simple: skip the checkpoint entirely when --orchestrator is set.
    if args.tier == "full_access" and not args.no_checkpoint and not orchestrator_mode:
        # Defer audit-sink wiring until after we know whether the
        # audit sink was requested (below). For now we create the
        # checkpoint without an audit sink and re-record it after.
        checkpoint_result = create_checkpoint(settings.workspace)
        print(format_checkpoint_message(checkpoint_result), file=sys.stderr)

    # M5: the orchestrator factory needs the audit sink so it can record
    # 'subagent' events for each delegation. We therefore build the audit
    # sink BEFORE constructing the agent in orchestrator mode.
    audit = None
    if orchestrator_mode and not args.no_audit:
        audit_path = str(args.audit_log) if args.audit_log else None
        if audit_path is None:
            audit_path = os.environ.get("SMOLCODE_AUDIT_LOG") or _default_audit_path()
        try:
            audit = AuditSink(audit_path)
        except Exception as e:
            print(f"audit sink init failed: {e}", file=sys.stderr)
            return 5

    if orchestrator_mode:
        agent = factory(settings, model, max_steps=args.max_steps, audit_sink=audit)
    else:
        agent = factory(settings, model, max_steps=args.max_steps)

    # M3: propagate --mcp-config to the agent factory (via env var).
    # Per decision 0005 the MCP runtime opens servers during tool
    # build and the registry is closed by close_mcp_servers() in the
    # finally block. An atexit handler is also armed as a safety net.
    if args.mcp_config is not None:
        os.environ["SMOLCODE_MCP_CONFIG"] = str(args.mcp_config)
        # Rebuild the agent so build_tools picks up the env var.
        # M5: pass audit_sink for orchestrator mode (sub-agent events).
        if orchestrator_mode:
            agent = factory(settings, model, max_steps=args.max_steps, audit_sink=audit)
        else:
            agent = factory(settings, model, max_steps=args.max_steps)

    from .tools import close_mcp_servers

    # M4: AuditSink around every run (elevated + full_access mandatory;
    # restricted also audited unless --no-audit is passed).
    # M5: the orchestrator mode created the audit sink earlier (so the
    # orchestrator factory can record subagent events). Skip this block
    # if audit is already set.
    if audit is None and not args.no_audit:
        audit_path = str(args.audit_log) if args.audit_log else None
        if audit_path is None:
            audit_path = os.environ.get("SMOLCODE_AUDIT_LOG") or _default_audit_path()
        try:
            audit = AuditSink(audit_path)
        except Exception as e:
            print(f"audit sink init failed: {e}", file=sys.stderr)
            return 5
    if audit is not None:
        # M5: when running the orchestrator, log the orchestrator's tier
        # as "orchestrator" so the audit trail is unambiguous.
        effective_tier = "orchestrator" if orchestrator_mode else args.tier
        audit.start(
            tier=effective_tier,
            task=args.task,
            model=settings.model,
            provider=settings.provider,
            executor=settings.executor,
            workspace=settings.workspace,
        )
        # M4.x: if a checkpoint ran, record it now that we have the sink.
        if checkpoint_result is not None:
            try:
                audit.record("checkpoint", **checkpoint_result.to_audit_fields())
            except Exception:
                pass

    # M4.x: install the session (auto_approve + confirm callback).
    # The session is the bridge between host-side tools (git_push,
    # run) and the CLI's confirmation prompt. Tools read
    # `current_session()` to find their tier, auto_approve state,
    # and confirm callback.
    destructive_timeout = resolve_destructive_timeout_s(args.destructive_confirm_timeout)
    auto_approve_default = bool(args.auto_approve_destructive) or _env_flag("SMOLCODE_AUTO_APPROVE_DESTRUCTIVE")

    def _confirm_callback(tool_name, kwargs, summary):
        # Read live session to allow mid-run toggling.
        from .session import current_session

        sess = current_session()
        # If auto_approve was flipped on by a previous `a` reply,
        # don't prompt again.
        if sess.auto_approve_destructive:
            return DestructiveDecision(approved=True, reason="auto-approve")
        decision = prompt_destructive(
            tool_name=tool_name,
            summary=summary,
            timeout_s=destructive_timeout,
        )
        if audit is not None:
            try:
                audit.record(
                    "destructive_decision",
                    tool=tool_name,
                    summary=summary,
                    approved=decision.approved,
                    reason=decision.reason,
                    auto_approve_now=decision.auto_approve_now,
                    auto_approve_off=decision.auto_approve_off,
                )
            except Exception:
                pass
        return decision

    session = SessionState(
        tier=args.tier,
        auto_approve_destructive=auto_approve_default,
        confirm_callback=_confirm_callback,
        audit_sink=audit,
    )
    set_session(session)

    rc = 0
    started = _now_monotonic()
    try:
        answer = agent.run(args.task)
        print(answer)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        rc = 130
    except ConfirmationDenied as e:
        print(f"aborted: {e}", file=sys.stderr)
        rc = 4
    except Exception as e:
        if audit is not None:
            try:
                audit.error(e)
            except Exception:
                pass
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        rc = 1
    finally:
        # M4.x: clear session so a subsequent import-time tool
        # reference doesn't accidentally see stale state.
        try:
            set_session(None)
        except Exception:
            pass
        if audit is not None:
            try:
                audit.end(exit_code=rc, duration_s=_now_monotonic() - started)
                audit.close()
            except Exception:
                pass
        try:
            close_mcp_servers()
        except Exception:
            pass
    return rc


def _cli_overrides(args):
    out = {}
    if args.provider:
        out["provider"] = args.provider
    if args.model:
        out["model"] = args.model
    if args.litellm_proxy:
        out["litellm_proxy"] = args.litellm_proxy
    if args.workspace:
        out["workspace"] = args.workspace
    return out


def _env_flag(name):
    """True iff the named env var is set to a truthy value.

    Truthy values (case-insensitive, stripped): "1", "true", "yes", "on".
    Anything else (including unset and empty string) is False.

    Used by main() to read toggles like SMOLCODE_AUTO_APPROVE_DESTRUCTIVE
    without importing os everywhere. Lives in cli.py so test patches of
    os.environ land correctly via monkeypatch.
    """
    raw = os.environ.get(name, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _default_audit_path():
    """Default audit log path: <cwd>/logs/audit.jsonl.

    Used by main() when --audit-log is not provided and
    SMOLCODE_AUDIT_LOG is unset. We re-import audit.default_audit_path
    lazily so test patches land correctly.
    """
    from .audit import default_audit_path

    return default_audit_path()


def _now_monotonic():
    """Monotonic clock in seconds (for run duration measurement)."""
    import time

    return time.monotonic()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


# ---- M15: subcommand handlers live in _cli_subcommands.py (decision 0019) -----
# Re-exported here so existing test imports keep working, e.g.
#   from smolcode.cli import _audit_main   # tests/test_cli_audit.py:21
#   from smolcode.cli import _build_parser # tests/test_orchestrator.py:473
from . import _cli_subcommands  # noqa: E402, F401  (M15: late re-export, kept below __main__ guard for readability)
from ._cli_subcommands import (  # noqa: E402, F401  (M15 backwards-compat re-exports)
    _audit_main,
    # Module-private helpers (used by tests; see test_cli_models.py:189):
    _models_format_age,
    _models_main,
    # Public-ish top-level handlers (called by main() pre-dispatch):
    _uploads_main,
    _web_main,
)
