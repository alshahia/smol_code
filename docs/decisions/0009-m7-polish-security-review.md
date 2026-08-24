# M7 — Polish + security review

**Date:** 2026-08-19
**Status:** active
**Trigger:** Milestone 7 of `docs/roadmap.md` (final pre-v1 milestone).
**Related:** `docs/security.md`, `docs/roadmap.md` sec 6 (M7), `docs/architecture.md`, `docs/environment.md`.

## Question

What does M7 ship? M7 is the **final milestone before v1**. It is the
milestone where the project stops adding new features and instead
*hardens* what M0-M6 shipped: security tests, log redaction, log
rotation, coverage gate, and a documented security review sign-off.

M7 is also the milestone where the user explicitly answers Q9 (the
security review sign-off question, `docs/roadmap.md` sec 7.6.3).

## Findings

### F1. Coverage at start of M7 was 78.7% (with `__main__.py` + demo MCP server)

A pre-M7 audit (`pytest --cov=smolcode`) showed total coverage at
**78.7%**. Two modules dragged the total:

* `src/smolcode/__main__.py` (4 stmts, 0 covered) — the CLI shim
  that simply calls `cli.main()`. Tested end-to-end by
  `test_cli.py::test_print_config_prints_yaml` and friends, but never
  *directly* invoked because pytest always goes through the module
  function path.
* `src/smolcode/tools/_mcp_demo_server.py` (24 stmts, 0 covered) —
  the docs demo MCP server. Its tool list is exercised by
  `test_mcp_tools.py::TestBuildMCPTools`; the server itself runs only
  when a user points `mcp_config.json` at it.

`tools/git.py` had 54% coverage because the git wrappers
(`git_push`, `git_clone`, `git_checkout`) require a real git remote,
and the existing test suite only exercises the local-repo paths.

### F2. `RedactSecretsFilter` did not exist as a module

`docs/security.md` sec 8 calls for a `RedactSecretsFilter` to redact
`sk-`, `sk-ant-`, `hf_`, `ghp_` from log output. The filter was never
implemented — `docs/roadmap.md` sec 6.5 lists it as M4 (decision 0006)
deferred, but it was never picked up. M7 ships it as a new module.

### F3. `AuditSink` had no rotation policy

`docs/security.md` sec 9 states the audit log is rotated by an
external tool, but no reference config (logrotate, launchd plist,
Windows scheduled task) existed. M7 ships `docs/audit-log-retention.md`
+ `scripts/rotate_audit_log.py`.

### F4. Coverage gate not enforced

`pyproject.toml` had no `pytest-cov` configuration. M7 adds it and
sets `--cov-fail-under=80` in `addopts` so `make test` (or just
`pytest`) enforces the gate by default.

### F5. Q9 sign-off

`docs/roadmap.md` sec 7.6.3 posed Q9: who signs off the security
review? The four options were:

  a. Self-review (the user)
  b. Trusted peer/colleague
  c. Formal third-party audit (out of scope for v1)
  d. No formal sign-off

The user picked **option (a)** at the start of M7 implementation.

## Decision

M7 ships the following:

### D1. `smolcode/redact.py` — new `RedactSecretsFilter`

A `logging.Filter` that mutates `record.msg`, `record.args`, and
`record.exc_text` to replace matched secrets with `[REDACTED:<class>]`
markers. Installed via `setLogRecordFactory` so the redaction runs at
record *creation* time, regardless of which logger or handler
eventually processes the record.

**Sub-decisions:**

  * Patterns: `sk-ant-[A-Za-z0-9_-]+`, `sk-[A-Za-z0-9_-]+`,
    `hf_[A-Za-z0-9]+`, `ghp_[A-Za-z0-9]+`. Listed longest-first so
    `sk-ant-` is consumed before `sk-`.
  * Markers: `[REDACTED:openai]`, `[REDACTED:anthropic]`,
    `[REDACTED:huggingface]`, `[REDACTED:github]`. The marker uses a
    *colon-separated* name that does NOT contain the trigger prefix, so
    the redaction marker cannot be re-matched by a later pass (this is
    critical for `sk-ant-`, whose naive marker `[REDACTED-sk-ant]`
    would itself match the `sk-` pattern).
  * Min token length: 10 characters. Tokens shorter than 10 chars
    after the prefix are left alone (e.g. `sk-short` is NOT redacted).
  * Custom patterns: the constructor accepts additional compiled
    regexes for use-cases like a self-hosted LiteLLM proxy key.

### D2. CLI wires the redact filter at startup

`smolcode/cli.py:main()` calls `redact.install_redact_filter()`
immediately after `logging.basicConfig`. The filter is idempotent:
re-installation is a no-op.

### D3. `tests/test_security.py` — top-level security suite

A new test file that mirrors `docs/security.md` sec 12 (Security
testing plan). Each numbered item in sec 12 is covered by at least one
test. Where a behaviour is already covered by a module-level test file
(`test_audit.py`, `test_redact.py`), the security test still includes
a re-assertion so a regression in the module is caught by the security
gate.

### D4. `docs/audit-log-retention.md` + `scripts/rotate_audit_log.py`

Reference rotation policy:

  * Retention: 365 days for `full_access` audit log; 90 days for
    `elevated`; 30 days for `restricted` (none of the latter two are
    actually written by default; the policy applies if the user opts
    in).
  * Compression: gzip; date-suffixed filename `audit-YYYYMMDD.jsonl.gz`.
  * Cross-platform: `logrotate` (Linux), PowerShell scheduled task
    (Windows), `launchd` (macOS).
  * Reference implementation: `scripts/rotate_audit_log.py` (used by
    launchd; on Linux call this from `/etc/cron.daily/` if
    `logrotate` is not desired).

### D5. Coverage gate at 80%

`pyproject.toml` now includes `--cov=smolcode --cov-report=term
--cov-fail-under=80` in `addopts`. The `.coveragerc` excludes:

  * `__main__.py` (CLI shim)
  * `_mcp_demo_server.py` (docs demo)
  * `pragma: no cover` lines (developer escape hatch)
  * `if TYPE_CHECKING:` blocks (typing-only imports).

Result: **80.28%** at end of M7. The gate is enforced by default; a
regression below 80% will fail `pytest` in CI.

### D6. Q9 answer — self-review (option a)

The user signed off on the threat model in `docs/security.md`
themselves. The README will state this explicitly (D7). A future
`M7.5` milestone can re-do the sign-off as option (b) if the project
is adopted by a team.

### D7. README documents the M7 sign-off

`smolcode/README.md` adds a note in the security section: "Threat
model self-reviewed by the user on 2026-08-19. No external security
audit. Recommended for personal use and small teams; for production
deployment consider a third-party review (decision 0009 sec D6).

## Code Impact

### New files (5)

  * `smolcode/src/smolcode/redact.py` (~270 lines) — `RedactSecretsFilter`
    + `install_redact_filter()` + `reset_for_tests()`.
  * `smolcode/src/smolcode/tests/test_redact.py` (~290 lines, 31 tests).
  * `smolcode/src/smolcode/tests/test_security.py` (~430 lines, 26 tests).
  * `smolcode/docs/audit-log-retention.md` (~250 lines) — logrotate
    + Windows + macOS examples.
  * `smolcode/scripts/rotate_audit_log.py` (~75 lines) — cross-platform
    rotation helper.
  * `smolcode/.coveragerc` (~20 lines).

### Updated files (5)

  * `smolcode/src/smolcode/cli.py` — install redact filter after
    `basicConfig` (D2).
  * `smolcode/pyproject.toml` — add `pytest-cov` to dev deps; add
    coverage args to `addopts` (D5).
  * `smolcode/README.md` — M7 section + security sign-off note (D7).
  * `smolcode/src/smolcode/tests/test_orchestrator.py` — 8 new tests
    (specialist edge cases + `_RunTool.forward` empty cmd).
  * `smolcode/src/smolcode/tests/test_tools_shell.py` — 2 new tests
    (empty cmd + Windows `.exe` suffix strip).

### Files NOT changed (intentional)

  * `smolcode/src/smolcode/audit.py` — `AuditSink` already enforces
    append-only; the rotation policy lives in the new doc + script.
  * `smolcode/src/smolcode/security.md` — same threat model, no
    changes needed for the self-review sign-off.
  * `docs/security.md` sec 11 already lists "what we do not defend
    against"; M7 does not add or remove items in that list.

## Validation

| Gate | Result |
|---|---|
| `ruff check src` | PASS |
| `ruff format --check src` | PASS |
| `pytest` (with coverage) | PASS — **449 tests** |
| Coverage gate (`--cov-fail-under=80`) | PASS — **80.28%** |
| `smolcode --print-config` | PASS |
| `smolcode --smoke --tier restricted "echo hi"` | PASS |
| `docker compose -f smolcode/docker-compose.litellm.yml config` | valid (from M6) |
| `scripts/rotate_audit_log.py` smoke test | rotates + compresses + deletes old files |
| `RedactSecretsFilter` end-to-end via CLI | `sk-abc...` -> `[REDACTED:openai]` |

## Followups (deferred to v1.1)

  * `iptables` enforcement for `elevated.network_allowlist` (per
    M4 decision 0006). **Planned for M16** — see decision 0017.
  * Hash-chained audit log for tamper evidence. **DONE in M13.1** — see decision 0016.
  * Cold-storage sync (S3 Object Lock) in the `postrotate` block. **STILL OPEN** — requires external S3 credentials; deferred to v1.6+.
  * Per-`/models` HTTP endpoint (per M6 decision 0002). **ALREADY DONE in M11.1** — `GET /api/providers/{id}/models` ships in `smolcode/src/smolcode/web/api.py:592`. Remove from followups list.
  * Audit log `audit ls` / `audit grep` reader tool. **DONE in M13.2** — see decision 0016.
  * Additional redact patterns: Anthropic bearer tokens, Google API
    keys (`AIza...`), AWS access keys (`AKIA...`). **DONE in M13.3** — see decision 0016. (`sk-ant-` was already shipped in M7; M13 added Google, AWS, and the GitHub OAuth/User/Server family.)

## References

  * `docs/roadmap.md` sec 6 (M7) — original scope.
  * `docs/roadmap.md` sec 7.6.3 (Q9) — security review sign-off question.
  * `docs/security.md` sec 8 (secrets policy), sec 9 (audit log),
    sec 12 (security testing plan).
  * `docs/decisions/0006-m4-elevated-full-access-tiers.md` — `AuditSink` design.
  * `docs/decisions/0002-litellm-proxy.md` — M6 (referenced from M7
    because M7 touches the LiteLLM proxy config for redaction).
  * `smolagents-ui/AGENTS.md` PB-11.1 — original 80% coverage target.