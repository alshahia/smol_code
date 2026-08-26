# Area Review — Web Backend (FastAPI: server / api / runs / agent_runner / schemas / keys / cost_caps / dashboard / diffs)

**Date:** 2026-08-26 · **Reviewer:** parallel review agent (all 11 in-scope files fully read; root causes traced across the package; three findings runtime-verified with project venv) · **Status:** active

## Summary
Local FastAPI backend: loopback-only viewer/upload API plus live-execution layer (RunManager + SSE, thread-based runner, approval/diff gates, FIFO queue, cost caps, dashboard). Boundary security mostly sound (hard loopback bind enforced twice, path sandboxing, key whitelisting), but several Phase-2/3 features are wired incorrectly and fail at runtime — retry/rerun, queue draining, per-step cost caps, run export — and two core controls are effectively inert in web mode: the destructive-op approval/auto-approve flow and the audit sink.

## Architecture notes
- create_app builds shared singletons into app.state via lifespan; deps resolve lazily. Bind host validated in both _cli_subcommands._web_main() and run_server() (defense in depth).
- Runs execute on daemon threads publishing SSE frames into an unbounded Queue + capped events_log; approval/diff gates block the worker on threading.Event.
- Tool gating flows through process-global SessionState consumed host-side by shell.run/git push (tier=="full_access" check) and by write_file/patch_file via tier-agnostic diff callback.
- Cost caps: enqueue-time estimate via compute_dashboard + per-step callback. API keys memory-only on Run.
- A module-bottom monkey-patch re-wraps RunManager.__init__ to add queue state instead of editing the class (smell).

## Findings

1. **[HIGH] POST /api/runs/{id}/retry and /rerun always fail with 500** — api.py:957,988 pass parent_retry_of/parent_rerun_of; start_or_enqueue_run accepts only (task,tier,settings,audit,provider_override,model_override,api_key_value,session_id,project). Runtime-verified TypeError. Tests only exercise the dataclass. Fix: add params and persist on Run, or drop kwargs; endpoint-level test with real manager.

2. **[HIGH] Queued runs never start: _drain_queue_after_run calls request-scoped deps without a Request** — agent_runner.py:1016-1036 vs deps.py:19-23,47-58 ⇒ TypeError swallowed by finally-warning (903-906); dead double assignment of settings too. Entire FIFO queue non-functional. Fix: thread settings/tracker through QueueEntry or store on manager at construction.

3. **[HIGH] Per-step cost-cap enforcement is dead code; active runs unbounded** — agent_runner.py:358 guard getattr(run,"tokens",None) but Run has tokens_in/tokens_out (runtime-verified MISSING); start_run's Thread passes no tracker (only dequeued runs would get one, agent_runner.py:1044-1052); resume path passes neither (:988). "Stop at $1" doesn't bound a running job until the 15-min wall clock. Fix: use real fields; pass tracker into every run_in_thread/resume.

4. **[HIGH] Destructive-op approval gate unreachable for every web-startable tier; auto-approve mutates a flag nothing reads** — gates at tools/shell.py:77, git.py:370 require sess.tier=="full_access"; web rejects full_access ("requires the CLI"); orchestrator delegating to full_access sub-agents keeps session tier "orchestrator" (orchestrator.py:544) so host-side shell/git skip the gate; POST /runs/{id}/auto-approve (runs.py:970-985 → session.py:136-171) toggles where its only consumer is behind the full_access check. Elevated/orchestrator runs execute destructive ops (git push --force, rm -rf, docker, ssh…) with no prompt/events, contradicting config.py:335. Only the write_file/patch_file diff gate fires on web. Fix: gate on is_destructive regardless of tier (tier decides allowlists, not whether confirmation exists); set effective inner-agent tier during delegation.

5. **[HIGH] Web audit layer entirely disabled** — server.py:47-54,70 hardcode audit=None; `smolcode web` has no wiring either (_cli_subcommands.py:130-192). /api/audit always returns "no audit sink attached" (api.py:452-460); audit.start/end/error + destructive_decision/diff_decision records never written (agent_runner.py:452-463,575-588,672-683,847-885); dashboard errors_today pinned at 0. Fix: construct AuditSink in create_app honoring a flag, exactly as CLI does; thread into RunManager.start_run.

6. **[MEDIUM] Start/enqueue TOCTOU race clobbers global SessionState and disarms the diff gate** — runs.py:784-785,843-855 is_busy()/start not atomic under FastAPI threadpool; overlapping POSTs both start; first finisher set_session(None) (agent_runner.py:880) leaves survivor sessionless ⇒ fs.py:143-165 cb=None writes directly, un-gated. Fix: atomic check+claim under one lock or per-run scoped sessions instead of a global singleton.

7. **[MEDIUM] SSE subscriber can terminate before delivering run.ended** — runs.py:874-892 breaks on terminal status + empty queue; runner sets status BEFORE publishing EVT_RUN_ENDED (agent_runner.py:877-888) ⇒ client intermittently gets bare end frame without result/error payload. Fix: publish ended first or drain-with-timeout.

8. **[MEDIUM] Run history never purged; event payloads embed full file contents** — _runs insertion only (runs.py:743-744; no eviction anywhere); ≤5000 events_log frames/run; diff.proposed carries complete before/after uncapped; live events.Queue unbounded without subscribers; retains api_key_value string indefinitely. Fix: TTL/cap eviction; truncate diff bodies; zero api_key_value after consumption.

9. **[MEDIUM] GET /api/runs/{id}/export 500s whenever the run delegated** — api.py:1024-1026 dict(s) on SubAgentSummary dataclasses (runtime-reproduced TypeError). Fix: dataclasses.asdict.

10. **[MEDIUM] Project create/delete silently resets cost_rates/cost_caps** — api.py:378-392,413-426 rebuild Settings omitting those fields ⇒ env-configured overrides dropped for the process; cap tracker keeps its own copy but cost math loses overrides. Fix: with_overrides-style copying that threads all fields.

11. **[MEDIUM] Retry with explicit empty body downgrades tier to restricted** — api.py:950 req.tier defaults truthy "restricted" (schemas.py:211) so {} retries elevated/orchestrator as restricted. Fix: Optional[None]/sentinel.

12. **[MEDIUM] Loopback binding is the only access control; no Host/Origin validation ⇒ DNS rebinding reads the whole API** — server.py:30,100-107; a webpage resolving a domain to 127.0.0.1:7860 can read GET /api/files contents, sessions timelines, start/stop runs (SOP permits reading same-"origin"). Fix: middleware rejecting non-loopback Host; optional per-boot URL token (Jupyter-style).

13. **[LOW] Cost-cap enforcement basis is an estimate often $0** — runs.py:596-653 + model_catalog.py:288-309 cost_for returns 0.0 for unknown provider/model pairs ⇒ capped providers without rates never trip. Fix: surface rate_source_for in GET /cost-caps + warn; token-based fallback.

14. **[LOW] Stop during an open approval doesn't resolve the pending decision** — runs.py:957-962 sets stop_flag only; confirm/diff wait bounded by 30s timeout (confirm.py:169) ⇒ zombie "stopping"/awaiting_approval up to ~30s; denied-by-timeout audit reason instead of stopped. Fix: stop() resolves open decisions reason="stopped".

15. **[LOW] Unlocked bookkeeping mutations** — _next_event_id read-modify-write outside pending_lock (duplicate ids possible); cancel_queue writes status lockless (runs.py:418-421,1139-1144). Fix: fold under existing locks.

16. **[LOW] Snapshot temp files never cleaned** — NamedTemporaryFile(prefix="smolcode-snap-", delete=False) per snapshot (runs.py:550-569), never deleted. Fix: delete on terminal transition / managed dir with rotation.

17. **[LOW] Misleading advisory endpoint & style debt** — api.py:490-504 fs.write_file branch answers allowed-without-checking-any-path; __import__ gymnastics at api.py:1101-1111; module-level RunManager.__init__ patch at runs.py:1204-1219. Fix: implement containment claimed; normal imports; fold patch back.

18. **[INFO] Tracebacks flow raw into SSE/export payloads** — redaction covers logger output only; EVT_ERROR publishes traceback/message unfiltered (agent_runner.py:824-846). Loopback+single-user keeps risk low; route error strings through the redactor.

## Strengths
1. Boundary discipline done right: loopback-only enforced twice; uploads names rejected on any separator/dot (+api double-check); /api/files uses resolve()+commonpath correctly incl. symlinks and Windows case.
2. API-key hygiene: whitelist (*_API_KEY/*_APIKEY/HF_TOKEN), first-line trim, size/count caps; catalog endpoints accept env keys only; build_model never touches os.environ.
3. Robust run lifecycle mechanics: wall-clock-bounded agent.run via ThreadPoolExecutor with forced container cleanup in finally; atomic snapshot writes (tmp+os.replace); lock-guarded token/step aggregation; idempotent decision resolution.
4. Thread-safe, defensively-validated CostCapTracker with clear semantics and PUT validation against known providers (400 + alias hints).

## Coverage
Fully read: all 11 in-scope files (api.py 1337 lines; runs.py 1250 incl. truncated middle; agent_runner.py 1067). Trails: session.py (~320 lines), confirm.py, models.py, model_catalog.py (cost_for/rate_source_for/is_api_key_env), config.py, uploads.py, tools/shell.py gate region, tools/git.py gate via grep, orchestrator delegation tiers via grep, cli.py audit/session wiring, _cli_subcommands web launch, test_retry_rerun_export.py full. Runtime verifications (venv, read-only): pydantic import of schemas/create_app OK; retry TypeError reproduced; Run.tokens missing confirmed; dict(SubAgentSummary) TypeError reproduced. No servers started; no tests executed; no files modified.
