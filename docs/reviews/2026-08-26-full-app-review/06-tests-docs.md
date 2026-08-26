# Area Review — Tests, Docs & Repo Hygiene

**Date:** 2026-08-26 · **Reviewer:** parallel review agent · **Status:** active

## Summary
The test suite is unusually strong for a personal-project security-sensitive codebase: 1,232 tests collect cleanly (0 import errors), ruff clean on src, and the security-critical behaviors — tier immutability, path traversal/symlink escape, shell injection, MCP tool-name classification, secret redaction, audit append-only + hash-chain tamper evidence, sandbox boundary guarding — are genuinely asserted, not just happy-path smoke. Main weaknesses are process-level: no CI pipeline exists anywhere even though multiple docs claim CI enforcement; the conftest env-isolation allowlist has drifted from the env surface the code actually reads; the global coverage gate makes any subset run exit non-zero; temp-dir hygiene is poor (thousands of leaked .pytest_tmp dirs plus mkdtemp workspaces never removed). Docs are largely accurate and refreshingly candid, with a handful of concrete drift points.

## Architecture notes
- Tests in smolcode/src/smolcode/tests/ (55 files + conftest; 1,148 test functions → 1,232 items). pyproject addopts: "-sv --durations=0 --basetemp=.pytest_tmp --cov=smolcode --cov-report=term --cov-fail-under=80"; docker/shellcheck markers declared; .coveragerc omits __main__.py and _mcp_demo_server.py.
- Isolation: autouse fixture clears a hardcoded list of SMOLCODE_*/provider-key vars, repoints SMOLCODE_WORKSPACE at tmp_path, stubs load_dotenv_into_environ.
- External-dependence discipline: Docker/shellcheck/internet confined to 5 marked tests in test_elevated_iptables.py with runtime guards (_docker_available → skip; _host_can_reach_public_internet probe). MCP tests spawn local demo-server subprocess. Everything else offline.
- Docs form three layers (README usage / docs design+threat model / 46 ADR decisions / TASKS.md state); web API's no-auth stance explicitly documented with loopback-only bind enforced AND tested.

## Findings

1. **[HIGH] No CI pipeline exists while docs claim CI enforces gates** — no .github anywhere, no .gitlab-ci/Jenkinsfile/.circleci/tox/pre-commit at either root. README.md:513 "fail pytest in CI"; TASKS.md:498-500 iptables "lint-checked by standalone CI" + "pytest -m docker … runs in CI, not here"; docs/environment.md:131. Impact: nothing automated ever runs the only end-to-end verification of the elevated-tier iptables firewall; coverage/lint gates are honor-system. Fix: GitHub Actions job 1 = ruff + pytest -m "not docker" on windows/ubuntu; job 2 (ubuntu) = -m docker + shellcheck; publish coverage.

2. **[MEDIUM] Conftest env isolation allowlist drifted from real env surface** — conftest.py:18-34 clears exactly 14 vars, but code also reads SMOLCODE_UPLOAD_DIR/MAX_BYTES/ALLOWED_MIME, PROJECTS/COST_RATES/COST_CAPS, MCP_CONFIG, AUDIT_LOG (+hash-chain flag), FULL_ACCESS/DESTRUCTIVE confirm timeouts, five SMOLCODE_WEB_* knobs, provider host overrides ⇒ exported dev vars silently change test behavior (incl. make_agent attempting MCP loads). Fix: prefix-based clearing (SMOLCODE_* loop) + explicit provider-key list — pattern newer test files already use locally.

3. **[MEDIUM] Coverage gate in global addopts makes every partial run fail spuriously** — pyproject.toml:58 unconditional --cov-fail-under=80: even --collect-only exits FAIL (23.59% measured on collection). README-documented single-file runs report all-passed yet exit non-zero — trains users to ignore red exits. Fix: move cov flags to make test / CI command.

4. **[MEDIUM] Temp-dir leakage: thousands of stale .pytest_tmp entries at two roots + %TEMP% mkdtemp dirs never deleted** — root .pytest_tmp 2,294 dirs; smolcode\ 2,331; sessions repeatedly died without basetemp cleanup (root-level copy proves parent-dir launches too). test_cost_caps.py:208,303 / test_web_runs_api.py:391 / test_checkpoint.py:81 build workspaces via tempfile.mkdtemp with NO rmtree cleanup (finally only client.__exit__). Impact: unbounded disk growth; commit-junk risk if git initialized at parent (scenario anticipated by root .gitignore:1-8). Fix: prefer tmp_path/tmp_path_factory; wrap required mkdtemp in TemporaryDirectory/try-finally rmtree; always run pytest from smolcode\.

5. **[LOW] test_create_app_default_settings mutates os.environ directly bypassing monkeypatch** — test_web_server.py:37-41; failure between mutation and teardown leaks env into subsequent tests. Fix: monkeypatch.delenv/setenv.

6. **[LOW] "CLI installs redaction filter" test effectively tautological** — test_security.py:370-388 installs the filter itself when missing before asserting installed; cannot fail on the property it names (contradicts README.md:496); web path has no equivalent assertion at all. Fix: assert before any fallback install; add create_app() asserts redact.is_installed().

7. **[LOW] Documentation drift (verified against code)** — README.md:41,75 + docs/environment.md:32 point quick-start at repo root smol_clone_2 (actual: smol_code); docs/security.md:422 §12 claims shell.run rejects `..` `;` `&&` etc. while implementation/tests enforce something different and more precise (string args rejected outright; metacharacters inert via shell=False; `..` NOT special-cased per test_security.py:136-144); docs/security.md:735 says 19 always-run tests in test_elevated_iptables.py but post-0034 it carries ~28; TASKS.md:36-61 vs 63-81 duplicated paragraphs verbatim; TASKS.md/pyproject marker comment describe runtime pytest.skip guards as "deselected". Fix: path sweep; reword §12; refresh counts; dedupe TASKS.md.

8. **[INFO] Flakiness posture good; residual risks small and identifiable** — all time.sleep uses deliberate+bounded (60s hang simulation cut off by wall-clock fixture asserting <3s; 5s sleeps prove timeouts don't wait with elapsed<1.0 assertions). Residual: wall-clock ceilings can trip on loaded CI; MCP tests spawn ~10 subprocesses/session (slow, stable). No unplanned network I/O; symlinks skip gracefully where unsupported.

9. **[INFO] Missing coverage areas (within this lens)** — real Docker execution (container create/mount/auto-remove; container_run_kwargs wiring agents/base.py:94-112) exercised only by the 4-5 never-run-here contract tests; orchestrator/runner tested at fakes seams (honest mocking) so real CodeAgent construction has thin direct coverage; frontend suites outside Python coverage gate entirely.

## Strengths
1. Security behaviors truly asserted, not narrated: tier policy non-mutable via env; shell=False enforced by SOURCE INSPECTION; symlink/traversal rejections; MCP readonly/shadowed-name classification; audit append-only mode matrix; SHA-256 chain with tamper/broken-link/pre-M13 verification incl. refuse-to-rotate on broken chain.
2. Sandbox-guard suite pins defense-in-depth incl. a REAL historical bypass (send_tools→install_packages/run_code_raise_errors flow reproduced; error-message contracts pinned).
3. Honest external-dependence gating: docker/shellcheck self-skip with reasons + container-internet reachability probe to avoid false-passing firewall tests; zero accidental network/Docker use elsewhere in 55 files.
4. Docs candid about limits — security.md §11 explicit non-goals; architecture.md §13.5 plainly states no CSRF/bearer token and why — making the drift that does exist easy to catch.

## Coverage
Read fully: conftest.py, pyproject.toml, .coveragerc, smolcode/.gitignore, Makefile, web/server.py, agents/base.py; test_security/test_tiers/test_sandbox_guard/test_elevated_iptables/test_redact/test_web_keys/test_web_server/test_mcp_runtime. Inventories/excerpts of ~15 more test files; remaining ~40 skimmed via grep inventories. README all headings + close reads of Quick start/Security/M7/M13; architecture.md §13.4-13.7 close; security.md §12/§9.8 close; roadmap headings; environment §2-3; TASKS head/tail; both .gitignores; docs inventory. Commands (read-only): pytest --collect-only -q → 1,232 collected/0 errors (5.71s); ruff check src → All checks passed; directory/CI/temp-artifact inspections. Full suite intentionally not run per task rules.
