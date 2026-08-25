# 0028 - Per-sub-agent cost aggregation

**Date:** 2026-08-25
**Status:** applied (uncommitted, user review pending)

## 1. Context

Decision 0025 Phase 3 shipped CostBadge for the per-run cost chip and SubAgentList (replacing the single-row SubAgentBlock) but two things were left undone:

1. SubAgentList was never imported by Inspector - the legacy single-row sub hint (showing tier + id + duration only) remained in the Inspector and the full history view was invisible to users.
2. The SubAgentList rows had no per-sub-agent cost. The BE Run.publish() aggregated all step.action tokens into the outer run totals (tokens_in / tokens_out); sub-agent attribution was a list of {id, tier, started_at, ended_at, specialist} only.

Additionally, SubAgentSummary Pydantic schema in schemas.py was missing the specialist field that the BE dataclass already carried - the BE-to-wire serialization was silently dropping it.

Dashboard-level cost (cost_estimate_usd_today on GET /api/dashboard) and the per-run CostBadge on the Inspector header continue to work off the OUTER run tokens; this decision does NOT change that. The new per-sub-agent view is additive.

## 2. Decision

### 2.1 BE - Run / SubAgentSummary (decision 0028 additions)

- SubAgentSummary (BE dataclass in web/runs.py) gains tokens_in: int = 0 and tokens_out: int = 0 defaults.
- Run (BE dataclass) gains active_subagent_id: str | None = None.
- Run.append_subagent(sub_id, ...) sets self.active_subagent_id = entry.id after appending (under the existing pending_lock).
- Run.close_subagent(sub_id, ...) clears self.active_subagent_id ONLY if it matches sub_id (preserves attribution when a nested sub-agent has already taken over).
- Run.publish(EVT_STEP_ACTION, ...) - when self.active_subagent_id is set, the inner loop finds that entry and increments its tokens_in / tokens_out UNDER THE SAME pending_lock that increments the outer totals. The outer tokens_in / tokens_out continue to receive every token (own + sub-agents) so run-level cost math is unchanged.
- Run.summary_dict() computes cost_usd per sub-agent entry at read time via cost_for(self.provider, self.model, s.tokens_in, s.tokens_out, cache_hit=0, settings=None), rounded to 6 decimals (matches the existing cost_for rounding). Returns 0.0 when tokens are 0 even if rates are known (defensive - keeps the wire shape stable).
- Run.summary_dict() also now includes specialist in the per-sub-agent wire dict (was already emitted via getattr defensively; the docstring + ordering make it explicit).

### 2.2 BE - schemas.py (Pydantic)

SubAgentSummary gains:
- specialist: str | None = None (gap fix - was on dataclass, missing from Pydantic)
- tokens_in: int = 0
- tokens_out: int = 0
- cost_usd: float = 0.0

All additive with defaults; older wire payloads remain valid.

### 2.3 FE - SubAgentList (web/src/components/SubAgentList.tsx)

- SubAgentSummaryWire interface gains tokens_in?, tokens_out?, cost_usd? (all optional for back-compat with older servers).
- Each row now renders CostBadge(costUsd=s.cost_usd, rateSource="default") next to the existing tier/specialist/duration. The badge is wrapped in a span data-testid="subagent-cost" so per-row tests can target it.
- A new "Sub-agents total" chip renders below the rows when the sum of cost_usd > 0 (hidden when all rows have cost_usd == 0, e.g. unknown provider/model).
- Token count column (X,XXX tokens with input/output in title) added between duration and cost.

### 2.4 FE - Inspector (web/src/components/Inspector.tsx)

- Imports SubAgentList.
- Replaces the legacy single-sub-agent hint block (which showed tier + id + duration only) with SubAgentList(history={activeRun.subagent_history ?? []}). The legacy const sub = activeRun?.subagent ?? null line is commented out (kept for git-blame continuity) - the live sub accessor still drives the nested SubAgentBlock inside EventStream so that surface is unchanged.

## 3. Rationale

### 3.1 Why per-sub-agent token attribution in publish() (vs. a separate listener)?

Run.publish() is the SINGLE chokepoint for step.action events from both the orchestrator thread and the inner sub-agent thread (sub-agents publish to the outer's queue). Doing attribution here means:
- One lock to reason about (pending_lock already covers outer + history + active_subagent_id).
- Zero new wiring between orchestrator tool (do_<tier>_task) and Run state.
- Free consistency under concurrency: the existing concurrent-stress test patterns in test_run_manager.py cover it.

A separate listener would need to either consume the same event queue (duplicate work, race with the runner thread) or hook into the SSE stream (leaks runner internals to the FE layer).

### 3.2 Why derive cost_usd at read time (vs. store on SubAgentSummary)?

cost_for() needs the provider/model + optional Settings for override rates. Storing cost_usd on the sub-agent entry would require:
- Threading Settings through Run.append_subagent -> _build_delegation_tool -> orchestrator state -> Run.close_subagent -> Run.summary_dict (or stashing cost_for calls at every step).
- Re-computing on every cost_for() config change (Settings can be reloaded).

Deriving at read time in summary_dict():
- One cost_for call per sub-agent per snapshot - cheap (12 entries in worst case = 12 multiplications).
- Re-reads Settings if we choose to pass it later (deferred; v1 uses default rates).
- Keeps SubAgentSummary lean (two int fields, no derived state).

Trade-off accepted: cost can shift slightly between snapshot reads if cost_rates change, but that is the same trade-off dashboard.py already makes for the day-level cost (always reads at request time).

### 3.3 Why default-rates-only for v1 (not Settings-aware)?

Plumbing Settings into Run.summary_dict() requires:
- Run to hold a reference to Settings (new dataclass field; survives RunManager rebuilds).
- summary_dict() signature change; all callers must pass settings.
- Test infrastructure updates to construct Settings stubs.

For v1, sub-agent cost uses the same default rate as the outer run CostBadge (which ALSO uses default rates unless the user has set SMOLCODE_COST_RATES). When the user has set SMOLCODE_COST_RATES, the per-sub-agent chip will diverge from the run-level chip by a small amount - documented in section 6 Limitations. The plumbing to make both consistent is a follow-up decision (tracked in TASKS.md section 9).

### 3.4 Why double-write (outer + sub-agent) instead of "sub-agent only when active"?

The Dashboard computes run-level cost from Run.tokens_in / Run.tokens_out (dashboard.py line 102-116). Changing the semantic of those fields to "own only" would BREAK the Dashboard cost_estimate_usd_today math.

Double-writing preserves:
- Outer tokens_in / tokens_out = TOTAL (own + all sub-agents) - Dashboard unchanged.
- Sub-agent tokens_in / tokens_out = ONLY that sub-agent tokens - new per-row view.

Both are updated under the same pending_lock, so no race.

## 4. File-by-file spec

| File | Change | Lines |
|---|---|---|
| smolcode/src/smolcode/web/runs.py | + cost_for import; SubAgentSummary gains tokens_in/out; Run gains active_subagent_id; Run.append_subagent sets active id; Run.close_subagent clears it conditionally; Run.publish attributes tokens; Run.summary_dict emits cost_usd per sub-agent + specialist field | ~+90 / -3 |
| smolcode/src/smolcode/web/schemas.py | SubAgentSummary Pydantic gains specialist, tokens_in/out, cost_usd | +27 / -5 |
| smolcode/src/smolcode/tests/test_subagent_cost.py | NEW: 6 classes / 15 tests covering token attribution, wire shape, concurrency, dataclass defaults, event regression | +187 |
| smolcode/web/src/components/SubAgentList.tsx | Import CostBadge; extend SubAgentSummaryWire; add CostBadge per row + token column + total chip | +76 / -16 |
| smolcode/web/src/components/Inspector.tsx | Import SubAgentList; replace legacy single-hint with SubAgentList; comment out unused sub var | +18 / -16 |
| smolcode/web/src/__tests__/SubAgentListCost.test.tsx | NEW: 9 tests covering per-row badge, -- placeholder, token formatting, total chip visibility, axe-core | +86 |
| .gitignore | Add **/.pytest_tmp/ to capture pytest tmp dirs | +1 |

## 5. Validation commands

```
# BE
./smolcode/.venv/Scripts/python.exe -m pytest smolcode/src/smolcode/tests/ -q --no-cov
# Result: 1159 passed, 5 skipped (was 1144 + 15 new TestSubAgent* tests)

./smolcode/.venv/Scripts/python.exe -m ruff check smolcode/src/smolcode/tests/test_subagent_cost.py smolcode/src/smolcode/web/runs.py smolcode/src/smolcode/web/schemas.py
# All checks passed!

./smolcode/.venv/Scripts/python.exe -m ruff format --check smolcode/src/smolcode/tests/test_subagent_cost.py smolcode/src/smolcode/web/runs.py smolcode/src/smolcode/web/schemas.py
# 3 files already formatted

# FE
cd smolcode/web && pnpm vitest run
# Test Files  9 passed (9)
#      Tests  64 passed (64) (was 55 + 9 new)

cd smolcode/web && pnpm exec tsc -b
# (no output = success)

cd smolcode/web && pnpm build
# dist/assets/index-*.js  258.01 kB / gzip: 77.72 kB
# (was 257.80 / 77.67; +0.21 KB / +0.05 KB)
```

## 6. Limitations + future work

1. Default-rates only: per-sub-agent cost_usd ignores Settings.cost_rates overrides. When the user sets SMOLCODE_COST_RATES, the per-sub-agent chip will show default-rate cost while the Dashboard shows override-rate cost. Follow-up: thread Settings into Run.summary_dict() (add settings=None parameter; callers pass it).
2. No cache-hit attribution: cost_for(cache_hit=...) is supported but step.action events do not carry per-event cache_hit counters. The BE uses cache_hit only in dashboard.py (which reads it from the run running token totals - also 0). Cost may be slightly UNDER-estimated when caching is in use. Follow-up: add cache_hit to the step.action event payload.
3. Provider/model inheritance: sub-agents inherit the OUTER run provider/model for cost_for(). If a future variant lets sub-agents override per-invocation, the SubAgentSummary would gain provider / model fields and summary_dict() would read them.
4. SubAgentList was orphaned: this decision finally wires it into the Inspector. The live nested SubAgentBlock inside EventStream is unchanged (the sub accessor still drives it).

## 7. References

- docs/decisions/0025-web-ui-ux-review-and-roadmap.md section 6.5 (Phase 3 Dashboard + a11y + power features) - established CostBadge + SubAgentList library components
- TASKS.md section 4 line 187 (v1.9.x followup #3: per-subagent cost aggregation)
- docs/roadmap.md line 1001 (v1.9.x followups inventory)
