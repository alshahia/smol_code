# Area Review — Python Core (config / models / session / CLI / packaging)

**Date:** 2026-08-26 · **Reviewer:** parallel review agent (verified against venv runtime) · **Status:** active

## Summary
All 12 in-scope files fully read plus follow-the-trail reads into confirm/audit/checkpoint/uploads/redact/web/agents. Every reported issue verified against surrounding code or runtime-checked (read-only). No files modified.

Verified-correct highlights: LiteLLMModel usage matches installed smolagents 1.26 exactly (custom_llm_provider flows via self.kwargs into litellm.completion); stub ChatMessage signature compatible; keys never printed; fail-closed JSON env parsing; session-id traversal regex solid; atomic meta.json writes.

## Findings

1. **[MEDIUM] CLI --workspace bypasses existence/validation** — config.py (load_settings applies cli_overrides AFTER the workspace exists/mkdir check); also creates the default <repo>/workspace even when overridden.
2. **[MEDIUM] `smolcode audit ls --json` dumps raw JSONL with NO redaction** — while table/grep paths route through RedactSecretsFilter; log stores verbatim task text and exception messages (_cli_subcommands.py ~line 596).
3. **[MEDIUM] Invalid SMOLCODE_LOG_LEVEL raises uncaught ValueError from logging.basicConfig before load_settings' validation runs** (runtime-verified); validated settings.log_level is never applied on the CLI path.
4. **[MEDIUM] `custom` provider with CUSTOM_BASE_URL unset silently builds LiteLLMModel without api_base** ⇒ litellm routes to api.openai.com (can bill the user's OPENAI_API_KEY if present); build_model lacks the guard model_catalog has.
5. **[LOW/MED] Tier.__eq__ raises AttributeError vs non-Tier** (no NotImplemented guard; runtime-verified). Project gets this right.
6. **[LOW/MED] httpx imported directly by model_catalog.py but undeclared in pyproject** (only transitive via litellm→openai).
7. **[LOW]** _parse_projects mkdir-before-validation side effects (raw OSError on Windows for ':' in names); Project name under-validation (Windows reserved names, '.'); list_sessions stat race outside its own try/except; dead _ensure_default_session(); agent built twice just to set an env var one statement earlier; stderr prints bypass LogRecord redaction; _web_main silently ignores unknown/dangling flags.
8. **[INFO]** .env.example documents only a subset of supported env vars; provider/env-key lists duplicated across 3-4 modules; as_dict omits tier 'paths'; NaN/negative rates pass _parse_cost_rates; Makefile Windows-only with dead POSIX var; minor packaging metadata gaps (no license/readme/authors).

## Strengths
- LiteLLM/smolagents API compatibility verified against installed versions.
- Secrets never printed; fail-closed parsing of SMOLCODE_COST_RATES/CAPS/PROJECTS.
- Session id validation and atomic meta writes solid.

## Coverage
Fully read: __init__.py, __main__.py, config.py, models.py, model_catalog.py, session.py, cli.py, _cli_subcommands.py, _unicode_env.py, pyproject.toml, Makefile, .env.example. Trails followed into confirm/audit/checkpoint/uploads/redact/web/agents modules as needed.
