# 0039 - Phase 4: backend feature repair (retry, rerun, export, queue, cost caps)

**Date:** 2026-09-24
**Status:** active
**Phase:** `docs/reviews/2026-09-24-full-app-review/REMEDIATION-PLAN.md` Phase 4 (R3, R4 + web-medium)
**Depends on:** decision 0038 (Phase 3 - buildable/installable/testable)

## Context

Phase 3 made the tree build, install, and test. Phase 4 repairs the four web
features that the SPA already exposes and the review proved are broken at
runtime. All four shipped with green tests because the tests mocked below the
seam (`**kwargs` catch-alls, `SimpleNamespace` fakes carrying a nonexistent
`.tokens` attribute, API mocks) rather than exercising the real
`RunManager` on `app.state`.

| Finding | Defect | Evidence |
|---|---|---|
| R3a / H7 | `POST /api/runs/{id}/retry` and `/rerun` pass `parent_retry_of` / `parent_rerun_of` to `start_or_enqueue_run`, which does not accept them -> `TypeError` -> **HTTP 500** | `api.py:1077,1108` vs `runs.py:867-880` |
| R3b / H8 | `GET /api/runs/{id}/export` calls `dict(s)` on a `SubagentEntry` dataclass -> `TypeError` -> **HTTP 500** for any run with sub-agent history | `api.py:1144-1146` |
| R3c / H8 | `_drain_queue_after_run` calls `_api_module.get_run_manager()` and `_deps.get_settings()` - **request-scoped** FastAPI dependencies - from the runner thread after the request is gone. The resulting failure is swallowed by a bare `except` + `log.warning`, so the queue silently never drains | `agent_runner.py:1321-1341`, `1208-1211` |
| R4 / H9 | Cost caps never fire and the dashboard always reports `$0`: `_check_cost_cap_or_raise` and `dashboard.py` read `run.tokens`, but `Run` only has `tokens_in` / `tokens_out`. `TokenSummary` has no `cost_usd`, so Pydantic strips the computed cost out of every response. `cost_cap_tracker` is passed only on the drain path, never from `start_run` | `runs.py:679-736`, `dashboard.py:74-140`, `schemas.py:305-339`, `agent_runner.py:392` |

Plus the web-medium items: project create/delete rebuild `Settings` without
`cost_rates` / `cost_caps` (`api.py:383-395,418-430`), `resume_active_agent`
passes `cost_cap_tracker=None` (`agent_runner.py:1293`), and
`start_or_enqueue_run` never forwards `anchor_to_project_root` to
`enqueue()` (`runs.py:965-974`).

## Decision

1. **Run identity: `parent_retry_of` / `parent_rerun_of` become real `Run`
   fields.** Both `start_run` and `start_or_enqueue_run` accept them, persist
   them on the `Run`, and surface them in `summary_dict` and the
   `run.started` event. `retry_count` becomes a real field on `Run` instead of
   a `getattr(parent, 'retry_count', 0)` incremented on the parent only.
2. **`RunStartRequest.tier` becomes `str | None = None`.** The *endpoint*
   applies `'restricted'` for a fresh `POST /api/runs`; retry/rerun inherit
   the parent tier when the body omits it. Rationale: a non-optional default
   in the schema made it impossible to distinguish "caller said restricted"
   from "caller said nothing", which is exactly the distinction the retry
   path needs. Comments at both sites record this.
3. **Export reuses `Run.summary_dict()`.** It is the existing, working
   serialisation of a run and already handles sub-agent cost; no new
   serialiser is introduced.
4. **`RunManager` owns its own settings.** The monkey-patched `__init__`
   (`runs.py:1340-1353`) is folded into the real class, which also stores the
   `Settings` instance. `_drain_queue_after_run` then reads `run`'s manager
   directly. `run_in_thread` receives the manager as a parameter, so the
   drain no longer reaches through request-scoped FastAPI dependencies.
5. **A failed drain is visible.** `_drain_queue_after_run` records the error
   on the manager as `queue_drain_error`, which `GET /api/health` reports.
   The log line stays; the silent `except` does not.
6. **`Run.tokens` becomes a property** returning a `TokenSummary`-shaped
   object built from `tokens_in` / `tokens_out`. Preferred over rewriting
   every read site: it gives one definition of "this run's tokens" and keeps
   the existing `getattr(run, 'tokens', None)` call sites working. Explicit
   `tokens_in` / `tokens_out` reads are used where the property would be
   ambiguous.
7. **`TokenSummary` gains `cost_usd: float | None = None`** so the computed
   cost survives serialisation. Optional, not defaulted to `0.0`: an explicit
   `None` distinguishes "not priced" from "priced at zero" for a run whose
   provider has no rate.
8. **`cost_cap_tracker` is threaded through both entry points** -
   `start_run` and `resume_active_agent` - not just the drain path.
9. **Project create/delete preserve cost settings** using the existing
   `with_overrides` copy helper (`config.py:249-250,267-268`).
10. **`enqueue()` receives `anchor_to_project_root`** so `QueueEntry` reflects
    reality.
11. **Tests run against the real `RunManager`** obtained from
    `app.state.run_manager`, with only `_build_agent_for_run` stubbed. No
    `**kwargs` fakes, no `SimpleNamespace` runs. The RED test for each item is
    written and observed failing before the fix.

**Not in this phase:** frontend retry/rerun URL encoding + body changes
(Phase 5), `GET /api/health` implementation of `queue_drain_error` (Phase 8
adds the field to the response schema; the manager-side capture lands here so
the value is not lost), auth/CSRF (deferred).

## Validation

```
uv run ruff check src scripts
uv run ruff format --check src scripts
uv run pytest src/smolcode/tests -m "not docker" -q      # 0 failed, 0 errors

# each of these must have been observed RED before its fix:
uv run pytest src/smolcode/tests/test_retry_rerun_export.py -q
uv run pytest src/smolcode/tests/test_queue.py -q
uv run pytest src/smolcode/tests/test_cost_caps.py -q
```

## Exit criteria

1. `POST /api/runs/{id}/retry`, `POST /api/runs/{id}/rerun` and
   `GET /api/runs/{id}/export` all return 2xx against the real `RunManager`
   for the cases the review exercised; unknown ids return 404, not 500.
2. An empty-body retry of an `elevated` run yields an `elevated` child (the
   regression that the old non-optional `tier` default made impossible).
3. Three runs enqueued behind one active run all execute, in order, after it
   ends - verified through the real `RunManager`, not a fake.
4. A run with real `tokens_in` / `tokens_out` produces a non-zero
   `cost_estimate_usd_today` on `GET /api/dashboard` and
   `cost_usd` survives serialisation; spending past a configured cap returns
   **429** with `cost_cap_reached:`.
5. Project create/delete leaves `cost_rates` / `cost_caps` intact.
6. A drain failure sets `queue_drain_error` instead of vanishing.

## File-by-file spec

| File | Change |
|---|---|
| `web/runs.py` | `Run.parent_retry_of` / `parent_rerun_of` / `retry_count` fields; `Run.tokens` property; `RunManager.__init__` stores settings; both start methods accept + persist the parent ids; `cost_cap_tracker` passed to `run_in_thread`; `enqueue(anchor_to_project_root=...)`; `queue_drain_error` attribute; monkey-patch removed |
| `web/agent_runner.py` | `run_in_thread` takes the manager; `_drain_queue_after_run` uses it instead of request-scoped deps; drain error recorded; `resume_active_agent` passes the tracker |
| `web/api.py` | retry/rerun calls now match; export via `summary_dict`; project create/delete preserve cost settings |
| `web/schemas.py` | `RunStartRequest.tier: str \| None = None`; `TokenSummary.cost_usd` |
| `web/dashboard.py` | explicit token reads where the property is ambiguous |
| `tests/test_retry_rerun_export.py` | extended to endpoint level |
| `tests/test_queue.py` | real `RunManager` drain test |
| `tests/test_cost_caps.py` | real `Run` objects, cap -> 429, `cost_usd` survives |
| `tests/test_web_runs_api.py` | concurrent-start + project caps preservation |
| `TASKS.md` | §0b Phase 4 row updated at ship |

## Supersedes / relates

- ADR 0038 (Phase 3) - this phase relies on the green build/install/test gate.
- Decisions 0025, 0026, 0030, 0032, 0036 - the behaviours being repaired were
  specified there; this ADR makes them actually work.
