"""Subcommand handlers extracted from cli.py (M15, decision 0019).

`smolcode/cli.py` historically grew to 1172 lines as the audit / models /
uploads / web subcommands accumulated their own argparse pre-dispatch
and helper functions. M15 splits the four ``_*_main`` handlers + their
private helpers into this module so `cli.py` is left with the argparse
parser, the pre-dispatch `main()`, and the small top-level helpers.

The handlers are re-exported from `smolcode.cli` at the bottom of that
file so existing imports (e.g. `from smolcode.cli import _audit_main`
in `tests/test_cli_audit.py:21`) keep working.

Imports inside the handlers stay LAZY (matching the original style) so
that the CLI still starts on minimal installs where some subcommand
deps (FastAPI for `web`, etc.) may be missing.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time


# ---- M8: uploads subcommand -------------------------------------------------


def _uploads_main(argv_list):
    """Handle `smolcode uploads [list|clean|path]` and return exit code.

    Accepted forms:
        smolcode uploads                  -> default: list
        smolcode uploads list
        smolcode uploads clean [--older-than N] [--yes]
        smolcode uploads path

    `argv_list` is the argv list passed to main() (with
    the leading 'uploads' element still present).
    """
    parts = list(argv_list)
    verb = parts[1] if len(parts) >= 2 else "list"
    verb_flags = parts[2:]

    from .config import ConfigError, load_settings

    try:
        settings = load_settings()
    except ConfigError as e:
        print("config error: " + str(e), file=sys.stderr)
        return 2

    from .uploads import UploadsStore

    store = UploadsStore(
        settings.uploads_dir,
        max_bytes=settings.upload_max_bytes or 50 * 1024 * 1024,
        allowed_mime=settings.upload_allowed_mime or ("text/",),
    )

    if verb == "path":
        print(str(settings.uploads_dir))
        return 0

    if verb == "list":
        metas = store.list_metadata()
        if not metas:
            print("(no uploads)")
            return 0
        print("stored_name\tsize\tmime\ttier\tts\toriginal_name\tsha256")
        for m in metas:
            print(
                "\t".join(
                    [
                        m.stored_name,
                        str(m.size),
                        m.mime,
                        m.tier,
                        m.ts,
                        m.original_name,
                        m.sha256[:12],
                    ]
                )
            )
        return 0

    if verb == "clean":
        older_than = None
        auto_yes = False
        i = 0
        while i < len(verb_flags):
            tok = verb_flags[i]
            if tok == "--older-than" and i + 1 < len(verb_flags):
                try:
                    older_than = int(verb_flags[i + 1])
                except ValueError:
                    print("--older-than requires an integer", file=sys.stderr)
                    return 2
                i += 2
                continue
            if tok == "--yes" or tok == "-y":
                auto_yes = True
                i += 1
                continue
            print("unknown uploads clean flag: " + repr(tok), file=sys.stderr)
            return 2
        metas = store.list_metadata()
        if not metas:
            print("(no uploads to clean)")
            return 0
        print("Will delete " + str(len(metas)) + " file(s):")
        for m in metas:
            print("  " + m.stored_name + "  " + str(m.size) + " B  " + m.mime)
        if not auto_yes:
            print("Pass --yes to confirm.", file=sys.stderr)
            return 6
        count = store.clean(older_than_days=older_than)
        print("deleted " + str(count) + " file(s)")
        return 0

    print("unknown uploads verb: " + repr(verb), file=sys.stderr)
    print("usage: smolcode uploads [list|clean [--older-than N] [--yes]|path]", file=sys.stderr)
    return 2


# ---- M8: web subcommand -----------------------------------------------------


def _web_main(argv_list):
    """Handle `smolcode web [--port N] [--host H] [--no-browser] [--no-audit]`.

    Starts the FastAPI server (decision 0010 D2). Host defaults to
    127.0.0.1 (loopback only); --host is rejected unless it is in
    ALLOWED_BIND_HOSTS (server.py enforces the same allowlist at
    start time). Phase 2 (H5): --no-audit is the explicit opt-out
    from the per-app audit sink; without it web runs are audited
    exactly like CLI runs.
    """
    port = 7860
    host = "127.0.0.1"
    no_browser = False
    no_audit = False
    log_level = "info"
    for i, tok in enumerate(argv_list[1:], start=1):
        if tok in ("--port", "-p") and i + 1 < len(argv_list):
            try:
                port = int(argv_list[i + 1])
            except ValueError:
                print("--port requires an integer", file=sys.stderr)
                return 2
        elif tok == "--no-browser":
            no_browser = True
        elif tok == "--no-audit":
            no_audit = True
        elif tok == "--host" and i + 1 < len(argv_list):
            host = argv_list[i + 1]
        elif tok in ("--log-level",) and i + 1 < len(argv_list):
            log_level = argv_list[i + 1]

    from .config import ConfigError, load_settings

    try:
        settings = load_settings()
    except ConfigError as e:
        print("config error: " + str(e), file=sys.stderr)
        return 2

    try:
        from .web import ALLOWED_BIND_HOSTS, run_server
    except ImportError:
        print("web dependencies missing. Install with: uv pip install -e .[web]", file=sys.stderr)
        return 7

    if host not in ALLOWED_BIND_HOSTS:
        print(
            "refusing to bind to host "
            + repr(host)
            + "; allowed hosts are "
            + repr(ALLOWED_BIND_HOSTS)
            + " (decision 0010 D1: loopback only)",
            file=sys.stderr,
        )
        return 8

    print("smolcode web starting on http://" + host + ":" + str(port) + "/", file=sys.stderr)
    if not no_browser:
        print("opening browser; pass --no-browser to suppress", file=sys.stderr)
    try:
        run_server(
            host=host, port=port, log_level=log_level, no_browser=no_browser, settings=settings, no_audit=no_audit
        )
        return 0
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print("server failed: " + str(e), file=sys.stderr)
        return 1


# ---- M12: models subcommand (decision 0015) --------------------------------


def _models_collect_env_keys():
    """Return the same env-var subset that web/api.py:_collect_env_keys does.

    Duplicated here so the ``models`` subcommand does not pull in the
    FastAPI deps. Keep the two in sync; if you add a new provider,
    update both lists.
    """
    names = (
        "OPENCODE_GO_APIKEY",
        "OPENCODE_HOST",
        "MINIMAX_API_KEY",
        "MINIMAX_HOST",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CUSTOM_API_KEY",
        "CUSTOM_BASE_URL",
        "HF_TOKEN",
    )
    return {n: os.environ.get(n, "") for n in names if os.environ.get(n, "")}


def _models_format_age(epoch_seconds):
    """Render a cache-age string for the CLI table.

    Returns ``"-"`` if no cache entry exists, otherwise a short
    human-friendly string. Matches the SPA's badge format so the two
    surfaces look consistent (``just now`` < 30s, ``Nm`` < 1h,
    ``Nh`` thereafter; ``stale (>1h)`` when older than the TTL).
    """
    if epoch_seconds is None or epoch_seconds <= 0:
        return "-"
    age = max(0.0, time.time() - epoch_seconds)
    if age < 30:
        return "just now"
    if age < 60:
        return f"{int(age)}s ago"
    if age < 3600:
        return f"{int(age // 60)}m ago"
    if age < 24 * 3600:
        return f"{int(age // 3600)}h ago"
    return f"{int(age // 86400)}d ago"


def _models_main(argv_list):
    """Handle `smolcode models [list|refresh|doctor] ...` and return exit code.

    Accepted forms:
        smolcode models                       -> default: list
        smolcode models list
        smolcode models refresh               -> clear in-memory cache for ALL providers
        smolcode models refresh <provider>    -> clear in-memory cache for ONE provider
        smolcode models doctor [--no-fetch]   -> connectivity diagnostic (M12.5)
        smolcode models help

    This subcommand mirrors the SPA's ``GET /api/providers`` (list view)
    and ``GET /api/providers/{id}/models?refresh=1`` (refresh). The
    in-memory cache is per-process and shared with any running
    ``smolcode web`` server (both import ``model_catalog``); clearing
    it here will affect the SPA's "just now" badge on the next fetch.

    No keys are read from disk; only env vars populated in THIS shell
    process are used to compute ``key_state`` + ``model_count``.
    """
    parts = list(argv_list)
    verb = parts[1] if len(parts) >= 2 else "list"
    verb_args = parts[2:]

    # Lazy imports so the CLI still starts on minimal installs.
    from .model_catalog import clear_cache, get_provider, get_providers

    if verb in ("help", "-h", "--help"):
        print("usage: smolcode models [list|refresh [<provider>]|doctor|help]")
        print()
        print("  list                  # default; print provider table")
        print("  refresh [<provider>]  # clear in-memory model cache (all, or one)")
        print("  doctor [--no-fetch]   # per-provider connectivity diagnostic (M12.5)")
        return 0

    if verb == "refresh":
        if not verb_args:
            clear_cache(None)
            print("cleared model cache for all providers")
            return 0
        provider_id = verb_args[0]
        if get_provider(provider_id) is None:
            from .model_catalog import PROVIDERS

            print(
                "unknown provider: " + repr(provider_id) + "; known: " + ", ".join(p.id for p in PROVIDERS),
                file=sys.stderr,
            )
            return 2
        clear_cache(provider_id)
        print("cleared model cache for " + provider_id)
        return 0

    if verb == "list":
        if verb_args:
            print("unknown models list argument: " + repr(verb_args[0]), file=sys.stderr)
            print("usage: smolcode models list", file=sys.stderr)
            return 2
        env_keys = _models_collect_env_keys()
        rows = get_providers(env_keys)
        # Header
        print("PROVIDER".ljust(20) + "KEY".ljust(10) + "MODELS".ljust(8) + "CACHE_AGE".ljust(14) + "DEFAULT_MODEL")
        print("-" * (20 + 10 + 8 + 14 + 32))
        for r in rows:
            err = r.get("cached_error")
            age_cell = _models_format_age(r.get("cached_at"))
            if err:
                # M12.4: tag the age cell with a warning glyph + truncated
                # error so the user sees the failure at a glance.
                short = err if len(err) <= 32 else err[:29] + "..."
                age_cell = "⚠ " + age_cell + " (" + short + ")"
            print(
                r["id"].ljust(20)
                + r["key_state"].ljust(10)
                + (str(r["model_count"]) if r["model_count"] is not None else "-").ljust(8)
                + age_cell.ljust(14)
                + (r["default_model"] or "-")
            )
        print()
        print("tip: 'smolcode models refresh <provider>' clears the cache")
        print("     'smolcode models refresh' clears all caches")
        print("     ⚠ in CACHE_AGE column = most recent fetch failed (M12.4)")
        return 0

    if verb == "doctor":
        # M12.5: per-provider connectivity diagnostic. Iterates every
        # PROVIDERS entry, reports whether the API key env is set,
        # and either performs one HTTP fetch (default) or reads the
        # in-process cache only (`--no-fetch`). Exits 1 if any
        # provider has a fresh `cached_error` so CI can use this
        # as a connectivity gate.
        no_fetch = bool(verb_args) and verb_args[0] == "--no-fetch"
        if verb_args and verb_args[0] not in ("--no-fetch",):
            print("unknown models doctor argument: " + repr(verb_args[0]), file=sys.stderr)
            print("usage: smolcode models doctor [--no-fetch]", file=sys.stderr)
            return 2
        env_keys = _models_collect_env_keys()
        from .model_catalog import _CACHE as _CACHE
        from .model_catalog import PROVIDERS as _PROVIDERS
        from .model_catalog import fetch_models
        from .model_catalog import is_api_key_env as _is_api_key_env

        header = "PROVIDER".ljust(14) + "KEY".ljust(8) + "STATUS".ljust(14) + "AGE".ljust(12) + "DETAIL"
        print(header)
        print("-" * len(header))
        any_failure = False
        for spec in _PROVIDERS:
            api_key_envs = [e for e in spec.env_vars if _is_api_key_env(e)]
            api_key_env = api_key_envs[0] if api_key_envs else None
            has_key = bool(api_key_env and env_keys.get(api_key_env))
            if not has_key:
                skip_detail = "(" + api_key_env + " not set)" if api_key_env else "(no key env)"
                print(spec.id.ljust(14) + "-".ljust(8) + "skipped".ljust(14) + "-".ljust(12) + skip_detail)
                continue
            # Have a key. Either fetch now or read cache only.
            if no_fetch:
                entry = _CACHE.get(spec.id)
                if entry is None:
                    print(
                        spec.id.ljust(14)
                        + "✓".ljust(8)
                        + "no-cache".ljust(14)
                        + "-".ljust(12)
                        + "(use without --no-fetch to fetch)"
                    )
                elif entry.error:
                    any_failure = True
                    print(
                        spec.id.ljust(14)
                        + "✓".ljust(8)
                        + "fail".ljust(14)
                        + _models_format_age(entry.fetched_at).ljust(12)
                        + entry.error
                    )
                else:
                    print(
                        spec.id.ljust(14)
                        + "✓".ljust(8)
                        + "ok-cached".ljust(14)
                        + _models_format_age(entry.fetched_at).ljust(12)
                        + "("
                        + str(len(entry.models))
                        + " models)"
                    )
                continue
            # Perform a fresh fetch. refresh=True bypasses TTL.
            result = fetch_models(spec.id, env_keys, refresh=True)
            cached_entry = _CACHE.get(spec.id)
            cached_age = _models_format_age(cached_entry.fetched_at) if cached_entry else "-"
            if result.get("error"):
                any_failure = True
                print(spec.id.ljust(14) + "✓".ljust(8) + "FAIL".ljust(14) + cached_age.ljust(12) + result["error"])
            else:
                print(
                    spec.id.ljust(14)
                    + "✓".ljust(8)
                    + "OK".ljust(14)
                    + "just now".ljust(12)
                    + "("
                    + str(len(result.get("models", [])))
                    + " models)"
                )
        print()
        print("tip: 'smolcode models doctor --no-fetch' skips the network round-trip")
        print("     exit 0 = all good; exit 1 = at least one provider failed (M12.5)")
        return 1 if any_failure else 0

    print("unknown models verb: " + repr(verb), file=sys.stderr)
    print("usage: smolcode models [list|refresh [<provider>]|doctor|help]", file=sys.stderr)
    return 2


# ---- M13.2: audit subcommand (decision 0016) --------------------------------


def _audit_resolve_path(explicit=None):
    """Return the audit log path, honouring --audit-log > SMOLCODE_AUDIT_LOG > default."""
    if explicit:
        return str(explicit)
    env = os.environ.get("SMOLCODE_AUDIT_LOG")
    if env:
        return env
    from .audit import default_audit_path

    return default_audit_path()


def _audit_redact(text):
    """Run a single string through the default RedactSecretsFilter."""
    if not text:
        return text
    # M15.2: use the public redact_string (decision 0019). The default
    # `patterns=None` makes it pick up `DEFAULT_PATTERNS` for us.
    from .redact import redact_string

    scrubbed, _ = redact_string(text)
    return scrubbed


def _audit_format_row(obj, redact=True):
    """Format one JSONL audit entry as a one-line summary.

    Columns (fixed widths):
        TS         event          tier           detail
    The `detail` column carries the most useful per-event payload:
    `task` for start, `action` for step, `exit_code + duration_s`
    for end, `kind + message` for error, `-` for everything else.
    """
    ts = obj.get("ts", "-")
    event = obj.get("event", "-")
    tier = obj.get("tier", "-")
    detail = "-"
    if event == "start":
        task = obj.get("task", "-")
        detail = "task=" + str(task)
    elif event == "step":
        detail = "step=" + str(obj.get("step", "-")) + " action=" + str(obj.get("action", "-"))
    elif event == "end":
        detail = "exit=" + str(obj.get("exit_code", "-")) + " dur=" + str(obj.get("duration_s", "-"))
    elif event == "error":
        detail = obj.get("kind", "-") + ": " + str(obj.get("message", "-"))
    if redact:
        detail = _audit_redact(detail)
    return ts.ljust(22) + event.ljust(10) + tier.ljust(14) + detail


def _audit_main(argv_list):
    """Handle `smolcode audit [ls|grep|verify|rotate] ...` and return exit code.

    Accepted forms:
        smolcode audit                              -> default: ls
        smolcode audit ls [-n N] [--json] [--no-redact] [--audit-log PATH]
        smolcode audit grep <pattern> [-n N] [--no-redact] [--audit-log PATH]
        smolcode audit grep --patterns <re1> <re2> ... [-n N] [--audit-log PATH]
        smolcode audit verify [--audit-log PATH]
        smolcode audit rotate [--dry-run] [--keep-days N] [--audit-log PATH]
        smolcode audit help

    Exit codes:
        0  = success (clean verify / non-empty listing / rotated)
        1  = verify detected tampering OR grep matched nothing
        2  = usage error
        3  = audit log file not found
        4  = audit chain broken (rotate refused; decision 0018 R-M14-C)

    All verbs read the log via `default_audit_path()` unless
    `--audit-log PATH` is passed (mirrors `SMOLCODE_AUDIT_LOG`).
    `grep` output is routed through `RedactSecretsFilter` so keys
    read back from the log cannot leak to the terminal.
    """
    from .audit import verify_chain

    parts = list(argv_list)
    verb = parts[1] if len(parts) >= 2 else "ls"
    verb_args = parts[2:]

    if verb in ("help", "-h", "--help"):
        print("usage: smolcode audit [ls|grep|verify|rotate|help] [options]")
        print()
        print("  ls [-n N] [--json] [--no-redact] [--audit-log PATH]")
        print("     # list recent audit entries (default: last 20).")
        print("     # Redacted like grep unless --no-redact is passed.")
        print("  grep <pattern> [-n N] [--no-redact] [--audit-log PATH]")
        print("     # filter entries whose task/action/message contains <pattern>.")
        print("     # Output is routed through RedactSecretsFilter (M7).")
        print("     # With --patterns, all positionals are treated as regexes.")
        print("  verify [--audit-log PATH]")
        print("     # replay the hash chain (M13.1). exit 0 = clean.")
        print("  rotate [--dry-run] [--keep-days N] [--audit-log PATH]")
        print("     # verify chain, then gzip the live log to audit-<stamp>.jsonl.gz")
        print("     # (M14.3, decision 0018). Refuses if chain is broken (exit 4).")
        print("")
        print("env: SMOLCODE_AUDIT_LOG overrides the default log path")
        return 0

    audit_path = None
    limit = None
    as_json = False
    no_redact = False
    dry_run = False
    keep_days = None
    patterns = False
    pos = []
    i = 0
    while i < len(verb_args):
        tok = verb_args[i]
        if tok == "--audit-log" and i + 1 < len(verb_args):
            audit_path = verb_args[i + 1]
            i += 2
            continue
        if tok == "-n" and i + 1 < len(verb_args):
            try:
                limit = int(verb_args[i + 1])
            except ValueError:
                print("-n requires an integer", file=sys.stderr)
                return 2
            if limit < 1:
                print("-n must be >= 1", file=sys.stderr)
                return 2
            i += 2
            continue
        if tok == "--json":
            as_json = True
            i += 1
            continue
        if tok == "--no-redact":
            no_redact = True
            i += 1
            continue
        if tok == "--dry-run":
            dry_run = True
            i += 1
            continue
        if tok == "--keep-days" and i + 1 < len(verb_args):
            try:
                keep_days = int(verb_args[i + 1])
            except ValueError:
                print("--keep-days requires an integer", file=sys.stderr)
                return 2
            if keep_days < 1:
                print("--keep-days must be >= 1", file=sys.stderr)
                return 2
            i += 2
            continue
        if tok == "--patterns":
            patterns = True
            i += 1
            continue
        pos.append(tok)
        i += 1

    log_path = _audit_resolve_path(audit_path)

    if verb == "ls":
        if pos:
            print("unknown audit ls argument: " + repr(pos[0]), file=sys.stderr)
            print(
                "usage: smolcode audit ls [-n N] [--json] [--no-redact] [--audit-log PATH]",
                file=sys.stderr,
            )
            return 2
        from pathlib import Path as _P

        if not _P(log_path).exists():
            print("audit log not found: " + log_path, file=sys.stderr)
            print("(set --audit-log or SMOLCODE_AUDIT_LOG; run a task to create one)", file=sys.stderr)
            return 3
        entries = []
        with open(log_path, "r", encoding="utf-8", errors="replace") as fp:
            for raw in fp:
                line = raw.rstrip("\r\n")
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if limit is not None:
            entries = entries[-limit:]
        if as_json:
            # Phase 2 (M-item): route JSON output through the SAME
            # redactor as the table/grep paths. The raw JSONL dump
            # previously leaked verbatim task text and exception
            # messages; docs/security.md section 9 promises all read
            # paths apply RedactSecretsFilter.
            from .redact import DEFAULT_PATTERNS as _AUDIT_PATTERNS
            from .redact import _redact_value as _audit_redact_value

            for obj in entries:
                out_obj = obj if no_redact else _audit_redact_value(obj, _AUDIT_PATTERNS)
                print(json.dumps(out_obj, ensure_ascii=False, separators=(",", ":")))
            return 0
        if not entries:
            print("(audit log empty)")
            return 0
        header = "TS".ljust(22) + "EVENT".ljust(10) + "TIER".ljust(14) + "DETAIL"
        print(header)
        print("-" * len(header))
        for obj in entries:
            print(_audit_format_row(obj, redact=True))
        return 0

    if verb == "grep":
        if not pos:
            print(
                "usage: smolcode audit grep <pattern> [-n N] [--no-redact]",
                file=sys.stderr,
            )
            print(
                "   or: smolcode audit grep --patterns <regex1> [<regex2> ...]",
                file=sys.stderr,
            )
            return 2
        from pathlib import Path as _P

        if patterns:
            # M14.4 (decision 0018): each positional is a Python regex;
            # an entry matches when ANY compiled regex hits the haystack.
            try:
                compiled = [re.compile(p) for p in pos]
            except re.error as e:
                print(
                    "invalid regex: " + repr(e.pattern) + ": " + str(e),
                    file=sys.stderr,
                )
                return 2
        else:
            pattern = " ".join(pos).lower()
        if not _P(log_path).exists():
            print("audit log not found: " + log_path, file=sys.stderr)
            return 3
        matches = []
        with open(log_path, "r", encoding="utf-8", errors="replace") as fp:
            for raw in fp:
                line = raw.rstrip("\r\n")
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                haystack_parts = []
                for key in ("event", "tier", "task", "action", "message", "kind"):
                    v = obj.get(key)
                    if v is not None:
                        haystack_parts.append(str(v))
                haystack = " ".join(haystack_parts)
                if patterns:
                    if any(rx.search(haystack) for rx in compiled):
                        matches.append(obj)
                else:
                    if pattern in haystack.lower():
                        matches.append(obj)
        if limit is not None:
            matches = matches[-limit:]
        if not matches:
            print("(no matches)")
            return 1
        header = "TS".ljust(22) + "EVENT".ljust(10) + "TIER".ljust(14) + "DETAIL"
        print(header)
        print("-" * len(header))
        for obj in matches:
            print(_audit_format_row(obj, redact=not no_redact))
        return 0

    if verb == "verify":
        from pathlib import Path as _P

        if not _P(log_path).exists():
            print("audit log not found: " + log_path, file=sys.stderr)
            return 3
        try:
            r = verify_chain(log_path)
        except Exception as e:  # pragma: no cover (defensive)
            print("verify failed: " + repr(e), file=sys.stderr)
            return 2
        if r.ok:
            print("OK: " + str(r.entries) + " entries verified, chain intact (M13.1).")
            return 0
        if r.bad_line is not None:
            print(
                "FAIL: line "
                + str(r.bad_line)
                + " did not match its recorded entry_hash; "
                + str(r.chained_entries)
                + "/"
                + str(r.entries)
                + " entries verified before the break."
            )
            if r.malformed_lines:
                print("  malformed JSONL lines: " + ", ".join(str(n) for n in r.malformed_lines))
            return 1
        if r.first_unverifiable_line is not None:
            print(
                "PARTIAL: chain verifiable through line "
                + str(r.first_unverifiable_line - 1)
                + "; line "
                + str(r.first_unverifiable_line)
                + " onward has no chain fields (likely pre-M13). "
                + str(r.chained_entries)
                + "/"
                + str(r.entries)
                + " entries verified."
            )
            return 1
        print("FAIL: chain verification produced an unexpected result: " + repr(r), file=sys.stderr)
        return 1

    if verb == "rotate":
        from .audit import rotate_audit_log as _rotate_audit_log

        if pos:
            print("unknown audit rotate argument: " + repr(pos[0]), file=sys.stderr)
            print(
                "usage: smolcode audit rotate [--dry-run] [--keep-days N]",
                file=sys.stderr,
            )
            return 2
        try:
            result = _rotate_audit_log(
                log_path,
                keep_days=(keep_days if keep_days is not None else 365),
                dry_run=dry_run,
            )
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            print("(set --audit-log or SMOLCODE_AUDIT_LOG; run a task to create one)", file=sys.stderr)
            return 3
        if not result.chain_ok:
            print("refusing to rotate: " + result.chain_message, file=sys.stderr)
            return 4
        if dry_run:
            if result.rotated_to is None:
                print("(dry-run) empty log; nothing to rotate")
            else:
                print("(dry-run) would rotate to: " + result.rotated_to)
            if result.deleted:
                print("(dry-run) would delete " + str(len(result.deleted)) + " old archive(s):")
                for d in result.deleted:
                    print("  " + d)
            return 0
        if result.rotated_to is None:
            print("(empty log; nothing to rotate)")
            return 0
        print("rotated: " + result.rotated_from + " -> " + result.rotated_to)
        if result.deleted:
            print("deleted " + str(len(result.deleted)) + " old archive(s)")
        return 0

    print("unknown audit verb: " + repr(verb), file=sys.stderr)
    print("usage: smolcode audit [ls|grep|verify|rotate|help] [options]", file=sys.stderr)
    return 2


__all__ = [
    "_uploads_main",
    "_web_main",
    "_models_main",
    "_models_collect_env_keys",
    "_models_format_age",
    "_audit_main",
    "_audit_resolve_path",
    "_audit_redact",
    "_audit_format_row",
]
