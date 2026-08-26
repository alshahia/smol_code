# smolcode Remediation Plan — Phased

**Date:** 2026-08-26
**Source:** Full application review of 2026-08-26 (`docs/reviews/2026-08-26-full-app-review/`).
**Finding IDs** refer to `00-consolidated-report.md` (C = critical, H = high).
**Status:** active · **Mode:** plan only — nothing in this document has been implemented.

---

## Guiding principles

1. **Make truth verifiable before making code better.** Every phase ends with a gate that a machine can run; Phase 0 builds that machinery first so later phases cannot regress silently.
2. **Wire controls before adding new ones.** The dominant failure is "documented control not actually connected" (C1, C2, H5, H6, H8, H9). Fixing wiring is cheaper and safer than inventing new mechanisms.
3. **One execution-plane truth.** Wherever container vs host behavior diverges (C1, H3), first pin the real behavior in a test, then unify.
4. **Follow repo conventions:** ruff line-length 119; `make quality` then `make test` before any commit; each shipped phase gets an ADR under `docs/decisions/` continuing the numbering (next free ≈ 0035); update TASKS.md as cross-session state.
5. **No security-control change ships without a test that fails when the control is disabled.**

Dependency note: Phases are ordered so each depends only on earlier ones. Phase 0 unblocks everything; C1/C2 fixes (Phase 1) should land before tool hardening (Phase 4) re-tests gates; frontend work (Phase 6) consumes backend schema changes from Phase 3/5.

---

## Phase 0 — Verification infrastructure ("make lies impossible")

**Objective:** CI exists, quality gates run where docs claim they run, test env isolation is total, hygiene debt stops growing.
**Findings addressed:** H12, plus M-items from `06-tests-docs.md` (conftest drift, cov gate, temp leakage) and the two ruff FAILs from validation.

Tasks:
1. Add CI pipeline (GitHub Actions or equivalent):
   - Job A (windows + ubuntu): `ruff format --check`, `ruff check src`, `pytest -m "not docker"`.
   - Job B (ubuntu, Docker available): build the three tier images (see Phase 1 task 4), run `pytest -m docker` + shellcheck-marked tests, publish coverage.
2. Fix lint/format debt: add trailing newline to `scripts/rotate_audit_log.py`; apply ruff format to the 2 flagged files. Decide whether `scripts/` joins the ruff target set.
3. Move `--cov=smolcode --cov-report --cov-fail-under=80` out of pyproject `addopts` into the Makefile `test` target and CI command; keep plain `pytest` honest and fast.
4. Replace conftest's hardcoded 14-var allowlist with prefix clearing (`for k in list(os.environ): k.startswith("SMOLCODE_") → delenv`) + explicit provider-key list; convert `test_web_server.py:37-41` direct `os.environ` mutation to monkeypatch.
5. Temp hygiene: replace raw `tempfile.mkdtemp()` in `test_cost_caps.py`, `test_web_runs_api.py`, `test_checkpoint.py` with `tmp_path_factory` or try-finally `rmtree`; purge both `.pytest_tmp` roots; ensure pytest always launched from `smolcode/`.
6. Fix tautological redaction test (`test_security.py:370-388`): assert installation BEFORE any fallback install; add `create_app() → redact.is_installed()` assertion.

Validation: CI green on empty change; `make quality && make test` PASS locally on windows; collection exits 0 without coverage noise.
Exit criteria: a deliberately broken control (e.g., remove one iptables ACCEPT rule in a scratch branch) turns CI red.
Size: M.

---

## Phase 1 — Critical security wiring (C1 + C2 + H1)

**Objective:** the destructive-approval gate fires on every plane; tier images are actually built and used; network posture matches declarations.
**Findings addressed:** C1, C2, H1 (+ parts of H3 honesty).

Tasks:
1. **Redesign the destructive/diff gate trigger (C1).** Stop keying on the global session tier:
   - Gate at the point of execution on `is_destructive(tool, kwargs)` regardless of tier; tier decides *allowlists*, not *whether confirmation exists* (restricted may auto-deny instead of prompt).
   - Thread an execution-context object (effective tier, confirm callback, audit sink) through orchestrator `_build_delegation_tool`/`_build_specialist_tool` into sub-agent runs, replacing the process-global `SessionState` read inside forwards (full session-model refactor lands in Phase 5; this phase removes the *security-critical* dependency on it).
   - Remove the false premise in `cli.py:212-214` (orchestrator mode skipping full-access confirmation); restore the CLI confirmation whenever a delegation will (or may) use full_access; fix the orchestrator system-prompt claim (`orchestrator.py:68`).
   - Make web auto-approve meaningful again: `POST /runs/{id}/auto-approve` toggles the flag the gate actually reads.
2. **Make tier images real (C2).**
   - Pass the Dockerfiles to the executor explicitly (smolagents supports dockerfile content via executor kwargs) OR pre-build at startup: `smolcode` boot checks for local images `smolcode:{tier}`; if absent/stale (label hash ≠ source hash of Dockerfile + iptables-init.sh), build them once and cache; refuse to start sandboxed tiers otherwise with actionable message.
   - Fix `docker/full_access.Dockerfile`: add vendor apt repos/keys for gcloud/kubectl/terraform/azure-cli or drop those CLIs from the allowlist; install `pytest`, `ruff` everywhere advertised; nodejs+npm for elevated/full_access. Add image↔allowlist consistency test (each tier command resolves inside its image).
   - Pin base images + checksum gosu.
3. **Enforce network posture (H1/C2).** Restricted/elevated containers launch with no egress by default (custom internal network or the existing iptables ENTRYPOINT now that images are real); elevated allowlist CIDRs applied per family as today; fix ip6tables ICMPv6 NDP/PMTUD allowances while there.
4. **Pin the plane-truth test:** integration test proving (a) tools executing in-container see the correct effective tier + callback, (b) restricted container has no route to external DNS, (c) full_access destructive op prompts unless approved. These are the Phase-0 "broken control ⇒ red" tests, inverted.

Validation: new integration tests green in CI Job B; manual smoke: orchestrator run delegating to full_access requires exactly one approval for `git push`; restricted container cannot reach the internet.
Exit criteria: C1/C2/H1 findings have failing-test-then-fix commits; ADR documenting the gate-context redesign.
Size: L.

---

## Phase 2 — Audit & evidence integrity (H5 + H6 + related M)

**Objective:** every run leaves a tamper-evident trail; verification works on multi-run logs; secrets never appear in any dump.
**Findings addressed:** H5, H6; M: audit hash race, `audit ls --json` unredacted, redaction-vs-docs gaps, snapshot/temp cleanup (runs-side part).

Tasks:
1. Construct an `AuditSink` in `create_app(`no_audit flag)`) exactly as cli.py does; thread it into `RunManager.start_run`; update deps docstring; SPA audit panel then works unchanged.
2. Fix chain genesis across sinks: chain continuation reads last line of the existing log (per-path) so appended runs extend the same chain; multi-run logs pass `verify_chain`; add regression test (two sinks, one file, verify OK; tamper still detected).
3. Move hash computation under the sink lock (race M-item).
4. Route `audit ls --json` output through RedactSecretsFilter like table/grep paths.
5. Reconcile redaction coverage with docs/security.md claims (extend patterns or amend text).
6. Snapshot/temp cleanup: delete `smolcode-snap-*` NamedTemporaryFiles on terminal transition (runs.py:550-569).

Validation: unit tests for 2-4; integration: web-started run produces start/end/destructive_decision records readable via GET /api/audit with verify=true ok.
Exit criteria: `docs/security.md` §9 claims demonstrably true end-to-end on CLI and web.
Size: M.

---

## Phase 3 — Repair broken features (H7 + H8 + H9 backend/schema side)

**Objective:** retry/rerun/export/queue/caps do what their endpoints promise.
**Findings addressed:** H7, H8, H9 (backend half); FE cost columns unblock (FE half in Phase 6).

Tasks:
1. Add `parent_retry_of`/`parent_rerun_of` params to `start_or_enqueue_run`/`start_run`, persist on Run, expose in summaries; endpoint-level tests using the REAL manager (no mocks below the seam).
2. Fix queue drain: carry settings/tracker/manager refs through QueueEntry (or store on RunManager at construction); delete request-scoped dep calls from agent_runner; drain test: enqueue 3 while busy → all execute sequentially after completion.
3. Cost caps: delete `run.tokens` guard (use tokens_in/out); thread tracker into every run_in_thread/resume invocation; warn (GET /cost-caps `rate_source`) when a capped provider lacks rates; optional token-based fallback cap.
4. Add `cost_usd` to `schemas.TokenSummary` (unblocks FE Dashboard).
5. Retry tier default: make RunStartRequest.tier Optional[None]; explicit body wins; else inherit parent.
6. Project create/delete must preserve cost_rates/cost_caps (with_overrides-style copy helper).

Validation: endpoint tests green incl. 500-repro cases from review; cap test: force spend past cap mid-run → next step aborts.
Exit criteria: all four previously-dead paths demo'd via TestClient script committed under scripts/.
Size: M.

---

## Phase 4 — Tool & MCP hardening (H2 + H3 + H4 + MCP set)

**Objective:** host-side tools enforce what their names promise even against hostile arguments; MCP becomes usable-or-absent, never silently leaky.
**Findings addressed:** H2, H3, H4, H11; M-items: MCP broken-under-docker, env inheritance, registry collisions, timeout_s, run cwd/timeout/output, patch_file bugs, checkout gating, classifier shapes.

Tasks:
1. Git dash-guards: reject leading '-' in every string arg (or insert `--` where supported) across push/clone/fetch/diff/checkout/log/status/add/commit; validate remotes against `git remote -v`; scheme-allowlist clone URLs; clamp clone/diff-output paths under workspace; export GIT_CONFIG_GLOBAL=/dev/null and empty core.hooksPath; block writes under `.git/` in fs tools. Generate the repetitive blocks from one template or add equivalence tests across all nine git tools (review INFO item) so fixes can't drift.
2. Composition boundary (H3): decide + document the trust model per executor mode; minimum viable enforcement: uploads immutability and `.git/` protection enforced in-image/mount flags rather than only in forward(); runtime warning banner when SMOLCODE_EXECUTOR=local.
3. Uploads (H4): reject symlinks in store operations (lstat before read/delete/list); stream size-cap enforcement during save instead of buffering whole bodies; align "50 MB" hint with config.
4. MCP:
   - If kept under docker executor: host-side proxy design (tools stay local; only calls cross the boundary) — else refuse mcp_configs+docker loudly at build time.
   - Default-deny server env (PATH/HOME/temps + explicit per-server passthrough added to mcp_config.json schema).
   - Globally unique registry ids (monotonic factory), close superseded servers, resolve configs once per run and reuse instances across delegations.
   - Implement timeout_s (selector/kill-on-deadline); document single-flight locking.
   - Replace name-prefix readonly heuristic with operator-curated per-tool allowlists (keep prefix regex as advisory lint); route MCP calls through destructive classifier for elevated/full_access.
5. patch_file/write_file correctness: treat empty hunk-body lines as context; newline="" parity between writers (diff-gate preview == persisted bytes); catch UnicodeDecodeError on binary 'before' reads.
6. Destructive classifier: wire git_checkout gating above restricted (or minimal elevated always-confirm set: push --force/reset --hard/clean); delete dead extra_args branch; handle multi-word shapes (aws s3 rm…).
7. run tool: bind cwd like the git builder; validate int 0<timeout<=tier cap; cap captured output (tail N KB).

Validation: adversarial unit suite (option-injection strings from review as fixtures); MCP integration test against _mcp_demo_server under BOTH executors; patch_file golden diffs incl. empty-line hunks and CRLF files.
Exit criteria: every H2/H3/H4/MCP M-item has a red-then-green test; ADR for MCP deployment decision.
Size: L.

---

## Phase 5 — Web robustness & session model (M-set + H3 residue)

**Objective:** concurrent starts can't disarm gates; localhost surface tightened; memory bounded.
**Findings addressed:** TOCTOU SessionState race, Host-header/DNS-rebinding, SSE terminal race, _runs/api_key retention, stop-resolves-pending, unlocked bookkeeping, misleading advisory endpoint, style debts (monkey-patched __init__, __import__ tricks).

Tasks:
1. Session lifecycle: atomic single-active-run claim in RunManager (check+start under one lock) AND/OR replace global SessionState with per-run context object (completes Phase 1 refactor; deletes set_session(None)-clobbers-by-design).
2. Host middleware: reject requests whose Host ∉ {127.0.0.1[:port], localhost[:port], [::1]}; document residual rebinding stance in architecture.md §13.5.
3. Publish EVT_RUN_ENDED before setting terminal status (or drain-with-timeout in subscribe()); regression test with forced scheduling jitter.
4. Evict terminal runs after TTL/cap; truncate diff before/after to a budget in events_log; zero api_key_value once consumed (retry/rerun get it from a short-lived side map).
5. RunManager.stop() resolves open pending decisions reason="stopped"; fold _evt_seq and cancel_queue mutations under locks.
6. Implement the path containment /api/allowlist/check claims for fs.write_file; normal imports; fold module-bottom RunManager.__init__ patch back into the class.

Validation: concurrency stress test (parallel POSTs; survivor keeps diff gate); rebinding probe test (wrong Host → 421/400); long-session soak showing bounded memory.
Exit criteria: review M-items 6,7,8,12,14,15,16,17 closed with tests.
Size: M-L.

---

## Phase 6 — Frontend correctness & UX (H10 + FE M-set)

**Objective:** UI state reflects reality; approvals can't cross-contaminate; history readable.
**Findings addressed:** H10; FE mediums 3-9 from `05-frontend.md`; LOW cleanups opportunistically.

Tasks:
1. Selection clobber: bootstrap config once (ref guard); restore selection from loadLast(); decouple initial-load effect from polling callbacks. Regression test: submit → selection persists.
2. ApprovalModal: key card by pending.decisionId (or reset editedAfter effect); Escape + focus trap.
3. EventStream: hydrate finished/past runs from events snapshot before subscribing; handler refs updated via separate effect; functional status updates; stable keys; consider windowed rendering.
4. Inspector countdown: reset tick on remaining_s change; use matched tier timeout_s instead of hardcoded 900.
5. Scope error screens to panels; global screen only for initial getConfig failure + retry button.
6. Enable TS strict + noUncheckedIndexedAccess; resolve fallout; merge duplicate TokenSummary declarations (cost_usd optional, dashboard variant only); encodeURIComponent for retry/rerun/export; remove dead test:a11y or add the folder; dynamic upload-limit hint from config.
7. A11y pass: reuse NodeRow Enter/Space pattern on ActiveRow/RunHistory rows/upload zone/directory toggles; combobox wiring for mention input; axe run gated in vitest.

Validation: vitest suites + Playwright specs green; new tests for tasks 1-3; strict compile clean.
Exit criteria: H10 + FE findings 2-9 closed; no console errors on a scripted happy-path e2e.
Size: M.

---

## Phase 7 — Docs alignment & structural refactors (close the gap between paper and reality)

**Objective:** docs describe the system that exists; the two structural risk hotspots get designed fixes.
**Findings addressed:** doc-drift LOWs; root causes 2-4 residue.

Tasks:
1. Docs sweep: README quick-start paths (smol_clone_2→actual), security.md §12 shell.run semantics, §9.8 counts, TASKS.md dedupe + "deselected vs skip" wording; architecture.md trust-boundary section rewritten around per-executor realities (post-Phase 4).
2. ADR: session/context model (replacing global singleton) — required before any future multi-run concurrency ambitions.
3. ADR/POC: serialization-safe policy generation (single-source template emitting the per-forward blocks) to end hand-copy drift.
4. Reconcile .env.example with actual env surface; deduplicate provider/env lists behind one module; packaging metadata (license/readme/authors); declare httpx if kept.

Validation: docs link/grep sweep in CI (stale path detector); ADRs numbered and linked from roadmap.
Exit criteria: a fresh reviewer can follow README/docs to a working, honestly-described deployment.
Size: M.

---

## Suggested sequencing & effort

| Phase | Theme | Depends on | Size |
|---|---|---|---|
| 0 | CI + gates + hygiene | — | M |
| 1 | C1 gate redesign + C2 images/network | 0 | L |
| 2 | Audit integrity + web sink | 0 | M |
| 3 | Broken endpoints/queue/caps | 0 | M |
| 4 | Tools/MCP hardening | 0 (re-tests after 1) | L |
| 5 | Web robustness + session model | 1 (context object) | M-L |
| 6 | Frontend correctness | 3 (schema) | M |
| 7 | Docs + structural ADRs | 1-5 | M |

Phases 2 and 3 can proceed in parallel with Phase 1 once Phase 0 merges.

## Definition of done (all phases)

- Each finding closed by a commit whose test fails without the fix (red→green evidence in PR description).
- `make quality && make test` PASS; CI Job B green including docker-marked tests.
- Security-behavior changes ship an ADR; TASKS.md updated; no secrets introduced; public API changes documented.
