# Area Review — Tools & Agents / Tier Enforcement

**Date:** 2026-08-26 · **Reviewer:** parallel review agent (all 19 in-scope files fully read; supporting trails verified incl. installed smolagents 1.26.0 internals) · **Status:** active

## Summary
smolcode implements three trust tiers over smolagents 1.26 CodeAgents, with host-defined tools (fs/shell/git) deliberately structured to survive Docker serialization, a hand-rolled sync JSON-RPC MCP stdio client, an opt-in orchestrator delegating to per-tier sub-agents, and per-tier Docker images (elevated: iptables default-deny egress). The serialization engineering is genuinely good and defense-in-depth intent is real — but several controls are weaker than they look: the destructive gate never fires during orchestrator runs; git args are not dash-guarded; restricted's network="none" is unenforced; MCP tools are broken under the default executor while the readonly filter is only a naming convention.

## Architecture notes
- Two execution planes: model code in containerized Jupyter kernels (docker default); tools serialized INTO the container via send_tools → instance_to_source (why _bind.py bakes state into class attributes and policy is re-inlined per forward()). local executor runs everything host-side.
- Tier surface from config._default_tiers(); every tier gets the same fs/run/git toolset, differing only in allowlists.
- Human-in-the-loop via process-global SessionState singleton read synchronously by forward(): destructive gate (full_access only) + M10 diff gate for write_file/patch_file.
- Orchestrator = local-executor CodeAgent whose only tools are do_<tier>_task/do_specialist; each forward builds a fresh sub-agent.
- MCP: config → MCPServerConfig; servers filtered per-tier by declared tools_mode; exposed as <server>__<tool> backed by module-global registry of stdio clients.

## Findings

1. **[CRITICAL] Destructive-op confirmation gate never fires during orchestrator runs — full_access reachable with zero human approvals** — cli.py:341-347, web/agent_runner.py:662-670; gates at tools/shell.py:77, tools/git.py:370. Sessions installed with OUTER run tier ("restricted"/"orchestrator"); delegation tools never reinstall full_access sessions; CLI skips confirm_full_access + git checkpoint in orchestrator mode on the false premise sub-agents hit the gate (cli.py:212-214); orchestrator prompt repeats the promise (orchestrator.py:68). Untrusted repo/task content that prompt-injects the orchestrator gains unauthenticated escalation. Fix direction: tier-aware gating at execution point / per-delegation session context + explicit opt-in when orchestrator first selects full_access.

2. **[HIGH] Git tool arguments are not dash-guarded — option injection** — git.py:356-388 (push), 442-454 (clone), 501-511 (fetch), 119-127 (diff), 561-570 (checkout): --receive-pack/--upload-pack/--exec/--output/--ext-diff/--pathspec-from-file reach git's parser; agent can write .git/config itself enabling hook/driver exec; git_clone(directory=…) has NO path policy. In-container blast radius = container + rw workspace; local executor = host RCE primitives. Fix: reject leading '-' or insert '--'; validate remotes against `git remote -v`; scheme-allowlist clone URLs; clamp outputs under workspace; GIT_CONFIG_GLOBAL=/dev/null, empty core.hooksPath, block .git/ writes.

3. **[HIGH] Restricted tier's network="none" declared but enforced nowhere** — config.py:326 vs agents/base.py:94-112 and docker/restricted.Dockerfile (no ENTRYPOINT/iptables); demo corpus even asserts network_mode=none that doesn't exist. Default bridge networking + unrestricted python via run tool (incl. pip install). Fix: network isolation at launch or iptables ENTRYPOINT; else downgrade declared posture everywhere.

4. **[HIGH] All fs/git gates bypassable through composition with allowlisted run tool; host-side under local executor this is full RCE** — shell.py:91-100 vs fs.py:104-167, tools/__init__.py:74. run("python", ["-c", …]) writes uploads, git apply, pytest conftest exec, npm/make lifecycle scripts. Fix: honest per-mode trust-boundary docs; move integrity-critical checks into image/entrypoint/mount-ro; flag local mode as non-security at runtime.

5. **[HIGH] MCP readonly tier filter is a name-prefix heuristic, not capability check** — mcp_tools.py:74,152-167: ^(get|search|read|list)_ on server-reported names + server self-declared tools_mode. "list_then_wipe" passes. destructive.py:25-26 explicitly never gates MCP. Fix: operator-curated per-tool allowlists beyond readonly; readOnlyHint advisory only; route MCP calls through destructive classifier for elevated/full_access.

6. **[MEDIUM] MCP tools structurally broken under the default Docker executor** — mcp_tools.py:197-208 resolves runtime via sys.modules; serialized source lands in a container where smolcode isn't installed ⇒ every call raises RuntimeError. M3 feature cannot work as deployed. Fix: host-side proxy tools or refuse loudly at build time.

7. **[MEDIUM] MCP stdio servers inherit the entire host environment including provider API keys** — _mcp_runtime.py:98-99 env=dict(os.environ); schema has no env field to restrict. Fix: default-deny env with explicit per-server passthrough list.

8. **[MEDIUM] MCP registry id collisions leak server processes and cross-wire sessions** — mcp_tools.py:242-243,259-292 counter restarts per build; CLI builds twice with --mcp-config; each orchestrator delegation respawns/overwrites; old processes accumulate; stale instances route to last claimant. Fix: uuid/monotonic ids; close superseded; resolve once per run and reuse.

9. **[MEDIUM] timeout_s is dead config; MCP client can hang forever holding its lock** — _mcp_runtime.py:84,149-199 blocking readline inside lock until matching id. One misbehaving server stalls the run. Fix: read timeouts/selectors/kill-on-deadline; enforce timeout_s; document single-flight.

10. **[MEDIUM] run tool: cwd never bound (docstring says otherwise), unvalidated model-controlled timeout, unbounded output capture** — shell.py:9-14,38-39,92-100; build_shell_tools binds only allowlist while git builder pins cwd (tools/__init__.py:75). Fix: bind cwd; validate int 0<timeout<=cap; cap captured output.

11. **[MEDIUM] patch_file drops empty lines inside hunk bodies; write_file/patch_file disagree on Windows newlines** — fs.py:300-305,316-327 vs 167,434-437. Real git diffs fail with misleading count errors; byte-level divergence between edit paths. Fix: treat empty body lines as context; newline="" parity.

12. **[MEDIUM] Destructive-gate coverage holes: git_checkout never gated; git_reset classification dead code; elevated force-push unprompted** — git.py:561-607; destructive.py:131-134,217-226 (branch keyed on kwargs shape no tool produces); shell.py:77 full_access-only ⇒ elevated run(git push --force) ungated by design comment destructive.py:53-55. Fix: gate checkout (+guarded reset) above restricted or minimal always-confirm set for elevated; delete/wire dead branch.

13. **[MEDIUM] Orchestrator replaces smolagents' entire system prompt and omits response protocol; specialist descriptions Jinja-interpolated** — orchestrator.py:548-569 vs smolagents agents.py template machinery: no {{tools}}, no final_answer contract; StrictUndefined crash/prompt-injection via ~/.smolcode/specialists.toml description fields. Fix: append scaffolding instead of replace; escape/validate specialist metadata.

14. **[MEDIUM] Sub-agent LLM spend escapes per-run cost accounting and caps** — orchestrator.py:201,206 bare make_agent without step callback; audit records durations not tokens. Fix: thread step callback/child-cost accumulator through delegation tools.

15. **[LOW] Tier Dockerfiles don't ship (or can't build) parts of their own command allowlists** — full_access.Dockerfile:52-67 vendor CLIs without repos (build fails); no image installs pytest/ruff; elevated lacks node/npm despite allowlist. Fix: repo setup; install advertised tools; consistency test.

16. **[LOW] Misc robustness/quality** — fs.py:135-139 UnicodeDecodeError before diff gate on binary 'before'; policy.py near-dead duplicate of inlined logic; git.py test-only helper; load_mcp_config accepts streamable-http but build silently drops non-stdio; SpecialistError(KeyError) repr noise; extra_paths knob documented-but-unenforced yet advertised in bundled description.

17. **[INFO] Serialization-driven duplication is a maintained-risk hotspot** — ~30 identical basename/subprocess blocks across git.py × 9 tools + shell.py; no equivalence enforcement. Fix: generate classes from one template or behavioral-equivalence unit test.

## Strengths
1. First-class handling of smolagents' serialization contract (_bind.py; pipe-encoded allowlists; MethodChecker quirks; round-trip tests).
2. Genuinely layered containment where it exists: double-realpath+normcase+commonpath; uploads immutability for restricted; diff gate semantics; GuardedExecutor dual-layer; elevated kernel-level egress denial with fail-closed CIDR validation mirrored both sides + audited kill switch.
3. Honest engineering record-keeping (decision IDs; candid comments like "v1.7 docs incorrectly claimed IPv6 was enforced").
4. Clean failure isolation choices (MCP partial-failure build; shadowed-name guard; per-server prefixing; dependency-free JSON-RPC client with idempotent close_all+atexit; sub-agent events published in finally).

## Coverage
Fully read (19 files): tools/{fs,git,shell,policy,_bind,mcp_tools,_mcp_runtime,_mcp_demo_server,__init__}; agents/{base,restricted,elevated,full_access,orchestrator,prompting,__init__}; specialists/{_models,deploy_staging,__init__}. Trails: config, destructive, sandbox_guard, models, container(1-150), session(40-150), cli(180-410), agent_runner(600-730), all three Dockerfiles, iptables-init.sh, venv smolagents 1.26 internals. Read-only checks: greps + scoped pytest --collect-only (25 items clean).
