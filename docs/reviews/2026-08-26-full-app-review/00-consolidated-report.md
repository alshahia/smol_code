# smolcode — Full Application Review (Consolidated)

**Date:** 2026-08-26 · **Repo:** `E:\python projects\smol_code` @ `b014e22` (branch `main`, clean tree)
**Method:** Six parallel deep-review passes (core, security layer, tools/agents, web backend, frontend, tests/docs) plus independent inspection of security-critical modules, cross-checked for agreement. Static review + targeted read-only runtime probes (venv Python 3.12.9, smolagents 1.26.0). No live model/container/browser execution. **No source files were modified during review.**
**Status:** active

Companion documents (same folder): `01-core.md`, `02-security-layer.md`, `03-tools-agents.md`, `04-web-backend.md`, `05-frontend.md`, `06-tests-docs.md`. Remediation: `REMEDIATION-PLAN.md`.

---

## Validation results

| Check | Result |
|---|---|
| `pytest --collect-only -q` | PASS — 1,232 tests collected, 0 import errors |
| `ruff check src` (declared lint target) | PASS |
| `ruff check .` (whole package incl. scripts/) | FAIL — W292 `scripts/rotate_audit_log.py:71` |
| `ruff format --check .` | FAIL — 2 of 109 files would be reformatted |
| Full pytest suite | SKIPPED (review-only; Docker/shellcheck markers; global cov gate) |
| Docker daemon probe | SKIPPED (docker CLI unavailable in shell) |
| vitest / Playwright suites | SKIPPED |

## Executive summary

smolcode is an ambitious, unusually well-documented local coding-agent platform (three trust tiers, Docker-sandboxed model code, host tools serialized into containers, MCP integration, FastAPI backend + React SPA, audit/redaction layer, 46 decision records). Engineering culture is strong: honest ADRs, fail-closed config parsing, disciplined key handling, real incident-derived regression tests.

**The dominant defect pattern: several headline security controls exist in code and docs but are not wired into the running system.** Three reviewers independently converged on the same critical failure from different angles. On default paths (web runs, orchestrator runs, unbuilt images), approvals, audit, network isolation and sandbox hardening are silently absent.

**Verdict:** strong foundation; not safe to trust as configured today. ~12 findings are "the feature does not work," not "the feature could be better."

## Finding index (IDs used by REMEDIATION-PLAN.md)

### Critical
- **C1 — Destructive-operation approval gate is dead; full_access reachable with zero confirmations.** Gates require `sess.tier == "full_access"` (`tools/shell.py:77`, `tools/git.py:370`); orchestrator/web install outer-tier sessions and never re-install per delegation (`cli.py:341-347`, `web/agent_runner.py:662-670`, `agents/orchestrator.py:544`); in-container tools see a fresh default SessionState; CLI skips its own full-access confirmation in orchestrator mode on the false premise the gate fires (`cli.py:212-214`); web auto-approve endpoint toggles an unread flag. Prompt injection ⇒ unattended escalation.
- **C2 — Tier Dockerfiles never reach the executor.** Only `image_name`+`container_run_kwargs` are passed (`agents/base.py:_executor_kwargs_for`); vendored smolagents builds its stock root-user image under `smolcode:* tags when absent ⇒ non-root user and iptables/ip6tables ENTRYPOINT (M16/decision 0034) inert unless operator pre-builds images manually (undocumented). Compounded: `docker/full_access.Dockerfile:52-67` cannot build as written (vendor CLIs without apt repos); no image ships pytest/ruff/node/npm that allowlists advertise.

### High
- **H1 — Network isolation declared but enforced nowhere** (restricted `network="none"`: no network_mode, no firewall; all tiers egress-open; `run` tool python has no import allowlist ⇒ pip works).
- **H2 — Git option injection**: no dash-guard/`--` separator (`--receive-pack=`, `--upload-pack=`, `--output=`, `--ext-diff` reach argv; `.git/config` writable via write_file ⇒ hook exec). `git_clone(directory=…)` has no path policy.
- **H3 — fs/git policy gates bypassable via allowlisted `run` composition** (python -c writes into uploads, git apply, pytest conftest exec). Local-executor mode = host RCE without runtime warning.
- **H4 — UploadsStore follows symlinks** planted via rw-mounted workspace ⇒ arbitrary host-file read/download.
- **H5 — Audit hash chain restarts at genesis per sink** while CLI appends all runs to one JSONL ⇒ legitimate multi-run logs always fail `verify_chain`.
- **H6 — Web audit layer entirely disabled** (`server.py:47` hardcodes `audit=None`; nothing outside tests sets `app.state.audit_sink`) ⇒ zero records for web runs; /api/audit permanently empty; contradicts docs/security.md §3.3/§9.
- **H7 — Retry/rerun/export endpoints broken at runtime**: unexpected kwargs ⇒ 500 (`api.py:957,988` vs `runs.py:756-768`); export `dict(dataclass)` ⇒ 500 with subagent history (`api.py:1024-1026`); empty-body retry downgrades tier to restricted (truthy default).
- **H8 — FIFO queue never drains**: `_drain_queue_after_run` calls request-scoped deps without Request ⇒ swallowed TypeError (`agent_runner.py:1016-1036`); queued tasks silently never start.
- **H9 — Cost caps hollow end-to-end**: per-step guard reads nonexistent `run.tokens`; tracker not passed to directly-started runs; enqueue basis $0 for unknown rates; Pydantic schema strips computed `cost_usd` ⇒ SPA cost columns dead; sub-agent spend escapes accounting.
- **H10 — Frontend provider/model selection clobbered to server defaults** whenever activeRunId changes (`App.tsx:174-193`) ⇒ wrong model/billing despite correct-looking UI.
- **H11 — MCP readonly "guarantee" is a name-prefix regex** on server-reported names + self-declared mode (`mcp_tools.py:74,152-167`); destructive classifier never gates MCP calls.
- **H12 — No CI pipeline exists** while README/TASKS/docs claim CI enforces lint/coverage and runs the Docker contract tests (the only end-to-end verification of the elevated firewall).

### Medium (grouped)
- **Web:** SessionState TOCTOU disarms gates on concurrent starts; DNS rebinding (no Host validation); SSE terminal race drops run.ended payload; `_runs` unbounded + api_key_value retained forever; snapshot tempfiles never deleted; project create/delete wipes env cost_rates/caps; stop doesn't resolve pending approvals.
- **Tools/MCP:** MCP tools structurally broken under docker executor; MCP servers inherit full host env incl. API keys; registry id collisions leak processes/cross-wire; `timeout_s` dead config + indefinite blocking readline under lock; run tool cwd unbound/unvalidated timeout/unbounded output; patch_file drops empty hunk lines + newline mismatch vs write_file; git_checkout ungated; elevated force-push ungated; dead destructive-classifier branch; orchestrator replaces system prompt dropping final_answer/{{tools}}; specialist TOML descriptions Jinja-interpolated.
- **Security/uploads:** upload buffered-before-cap; redaction gaps vs docs; audit record() hash race outside lock; UTF-8 scripts pass MIME filter; first-arg-only classifier misses `aws s3 rm`; ip6tables blocks ICMPv6 NDP/PMTUD; checkpoint stash mutates worktree and failure doesn't abort.
- **Core/CLI:** --workspace bypasses validation; invalid SMOLCODE_LOG_LEVEL crashes pre-validation; custom provider silently routes to api.openai.com; audit ls --json dumps unredacted JSONL.
- **Tests/hygiene:** conftest env allowlist drifted (~12 vars uncleared); unconditional cov-fail-under=80 fails partial runs; ~4,600 leaked .pytest_tmp dirs + mkdtemp fixtures without cleanup.
- **Frontend:** countdown drifts ~2× fast; transient fetch error = unrecoverable full-screen error; ApprovalModal leaks A's edited content into B; finished-run history renders empty (no replay); TS strict off; keyboard/a11y gaps; EventStream stale callbacks + unvirtualized re-renders.

Low/Info highlights: Tier.__eq__ raises vs non-Tier; httpx undeclared; NaN/negative rates parse; .env.example incomplete; unpinned base images/gosu; ip6tables ICMPv6 gaps; rotation mtime cutoff; checkpoint worktree mutation; plaintext localStorage keys (documented tradeoff); duplicate TokenSummary interfaces; 3 unencoded run-id URLs; dead test:a11y script; tautological redaction test; stale smol_clone_2 paths; overstated §12 claim; TASKS.md duplication.

## Cross-cutting root causes
1. Controls written but not wired to default paths (images, audit sink, network, caps, auto-approve).
2. Process-global SessionState used as a security boundary (wrong-plane reads, tier confusion, TOCTOU nulling).
3. Two execution planes with contradictory importability/state assumptions for `smolcode` in-container.
4. Serialization-driven duplication of policy logic (~30 hand-copied blocks) invites drift.
5. Endpoint↔manager contract drift with mocked-below-the-seam tests and no CI.

## Strengths
Serialization-contract engineering (`_bind.py` + round-trip tests); layered path checks (double-realpath+normcase+commonpath); fail-closed env parsing; key whitelist/memory-only lifecycle; uploads magic-byte sniffing; loopback bind enforced twice and tested; audit append-only matrix + tamper tests; sandbox-guard regression test from a real bypass; candid "not defended" docs; genuinely assertive security test suite where it covers.

## Limitations
Static + read-only runtime probes; no live Docker/LLM/browser execution; docker CLI unavailable in this shell; security-layer details condensed pending its full appendix; dependency behavior verified against installed smolagents 1.26.0 only.
