# Decision 0032: Per-provider usage caps

Date: 2026-08-26
Status: accepted
Decision owner: agent-runtime

## Problem

Operators running unattended batches hit runaway-cost surprises --
agents looping on retries against expensive hosted models accumulate
$10, $50, $100 before anyone notices. We need an enforceable per-provider
USD ceiling that gates both new-run admission and per-step continuation.

Today the dashboard surfaces cost_estimate_usd_today (decision 0028)
but there is no enforcement path. Operators want to set a $1 / $5 / $20
cap per provider and trust that no single runaway run can blow past it.

## Goals

- Reject new runs whose provider has already reached today's cap.
- Stop an in-flight run whose per-step cost pushes that provider past
  the cap. The run ends with status stopped, not error.
- Surface live + default caps in the Dashboard so the SPA can render
  a spend/cap progress gauge per provider without a second request.
- Make the cap user-editable at runtime (PUT) without a server restart.
- Seed defaults from SMOLCODE_COST_CAPS env so a fresh container
  inherits the operator's policy.

## Non-goals

- Per-model or per-task caps (we group by provider, not model or
  session). Can be added in a follow-up decision by extending the
  tracker key.
- Hard daily limits across all providers (would need a separate
  CostBudget concept; out of scope here).
- Alerting / webhook on threshold crossings. The Dashboard's
  over-cap row is the only consumer.
- Cost-rate override at runtime (decision 0025 Q5 still owns that; the
  tracker uses whatever cost_for() returns given the active
  Settings.cost_rates).

## Design

### 1. Settings.cost_caps

Loaded once at process startup from SMOLCODE_COST_CAPS (JSON object,
same shape as the existing SMOLCODE_COST_RATES). Validation:

- Must be a JSON object (list / scalar rejected).
- Values must coerce to positive floats.
- Bools and non-numeric strings rejected (ConfigError).
- String-coercible numerics like 1.5 accepted.
- Negative numbers rejected.
- bool is rejected even when truthy (True would otherwise coerce to 1.0).

Threaded through __init__, with_executor, with_overrides, and
as_dict (always present, may be empty).

### 2. CostCapTracker (web/cost_caps.py)

Thread-safe mutable per-provider registry with two dicts:

- defaults: the boot-time baseline (captured from
  Settings.cost_caps). NEVER mutated by update.
- caps: the LIVE state (replaced wholesale by update).

API surface:

- __init__(defaults=None): clean via _clean (drops <=0, non-numeric,
  bools).
- get_state() returns {caps, defaults} under the lock; both are
  independent copies so a caller cannot corrupt the registry.
- get_cap(provider) -> float: 0.0 when not set.
- update(new_caps) -> dict: replace caps with the cleaned version
  of new_caps. Returns the cleaned dict so the API layer can echo it.
- reset() -> dict: restore caps = defaults.
- check_reached(provider, current_spend_usd) -> (reached, reason).

Reason string format (decision 0032 spec): uses percent-formatting NOT
f-strings, so tests can grep for the literal prefix.

    cost cap reached for provider %s: $%.4f >= cap $%.

check_reached returns (True, reason) only when cap > 0 AND
current_spend_usd >= cap. We use >= so exactly-at-the-cap trips
the gate -- the operator's intent is no more than $1, not
strictly less than $1.

### 3. Two-layer enforcement

Layer A -- run-start (web/runs.py start_or_enqueue_run)

Before constructing the Run, the manager queries
CostCapTracker.check_reached(provider, today_usd). If reached is
True, raises ValueError with the same reason string prefixed
cost_cap_reached:. The api.py:start_run catch translates that
to HTTPException(429, ...) with detail = the reason.

today_usd is computed by compute_dashboard(mgr, audit, settings)
and pulled from the per-provider bucket. This is the same aggregator
the Dashboard uses (decision 0028), so the SPA and BE agree.

Layer B -- per-step (web/agent_runner.py _make_step_callback)

The step callback, when given cost_cap_tracker and settings,
computes the accumulated run-cost after each step and raises
_StopRequested(cost_cap_exceeded:provider:cost:cap) once
the per-run ceiling is reached. run_in_thread catches this and the
run ends with status = stopped (not error).

resume_active_agent does NOT receive the tracker; pause+resume
bypasses the per-step check on the resumed path. Documented
limitation; the per-day check at original run-start still applies.

### 4. API endpoints (web/api.py)

Two new endpoints, no auth (operator-local web app):

- GET /api/cost-caps returns { caps: [{provider, cap_usd}],
  defaults: [...], providers: [string], current_spend_usd: {provider: float} }.
  The dashboard uses current_spend_usd to render the spend/cap gauge
  without a second request.
- PUT /api/cost-caps body {caps: {provider: float}} returns
  same shape plus updated_at: float. Empty caps clears all overrides
  (defaults stay). Unknown provider ids rejected with 400 BEFORE
  touching the tracker. The canonical id is MiniMax (capital X);
  minimax (any case) is rejected so the SPA can surface a clear
  use-MiniMax hint.

Reason prefix mapping (api.py catch block):

- cost_cap_reached: -> 429.
- Everything else (ValueError) -> 400 (existing behavior).

### 5. SPA

- Dashboard.tsx gains a Cost today stat card plus a per-provider
  Today / Cap column with <progress> and an over-cap row class
  when the row's today >= cap. Data flows from getCostCaps()
  (joined with getDashboard() in the existing 30s poll).
- New <UsageLimitsPanel> mounted under <Dashboard> inside the
  dashboard overlay. Edits a draft cap per provider, Save caps
  fires PUT /api/cost-caps, Reset to defaults fires PUT with
  empty body. Renders Saved. flash chip on success.
- api.ts adds CostCapEntry, CostCapsState,
  CostCapsUpdateResponse types plus getCostCaps / putCostCaps.
- index.css adds .usage-limits* plus .dashboard-provider-row.over-cap.
- _helpers.ts (e2e) adds cost_caps_response /
  cost_caps_put_response slots plus GET / PUT handlers.

## Failure modes + UX

| Scenario | UX |
|---|---|
| Operator sets cap=$1, today spend=$1.0 | New run rejected with 429 + clear reason; user can edit cap or wait for tomorrow. |
| Operator sets cap=$5, in-flight run crosses $5 at step 12 | Run ends with status=stopped, reason = cost_cap_exceeded:<provider>:<cost>:<cap>; Inspector shows stopped. |
| Operator puts empty body ({caps:{}}) | All overrides cleared, defaults stay as-is. |
| Operator types minimax (lowercase) | 400 unknown provider with the canonical MiniMax hint. |
| Cost-capped per-day check uses today's dashboard aggregate | Dashboard + enforcement see the same number. No drift. |
| Multiple parallel runs against the same provider, each < cap | Per-run ceiling still triggers at the run level; day check only fires at start so N concurrent runs of same provider could collectively exceed day cap by up to N * per_run_cap. Documented. |
| resume_active_agent (pause+resume path) | Per-step check is skipped on the resumed step; per-day check at original start still holds. Documented. |

## Tests

BE (35 tests in test_cost_caps.py):

- TestParseCostCaps (8): env-var JSON parser (empty, valid,
  invalid, non-object, non-numeric, negative, bool, string-coercible).
- TestSettingsCostCaps (4): default, with_overrides,
  with_executor, as_dict.
- TestCostCapTracker (6): init clean, get_cap, get_state copies,
  update drops bad values, reset, check_reached (including
  thread-safety and percent-format reason).
- TestRunStartCapEnforcement (4): no caps allows; below cap allows;
  at cap rejects; cap on other provider does not block.
- TestCostCapsAPI (8): GET empty / shape; PUT round_trips /
  empty clears / canonical MiniMax / minimax alias 400 /
  unknown 400.

FE (vitest, in __tests__/):

- Dashboard.test.tsx: 9 cases incl. renders the cost + cap columns
  when caps are configured + marks over-cap rows.
- UsageLimitsPanel.test.tsx (NEW, 7 cases): renders, over-cap row
  class, PUT-only-positive filter, saved-flash chip, reset clears
  drafts, empty-state, GET-error state.

FE (playwright, in e2e/):

- dashboard.spec.ts: existing tests updated for the new
  cost-cap columns.
- usage-limits.spec.ts (NEW, 4 cases): panel mounts, save fires
  PUT + flash, over-cap row class, reset clears cap.

## Migration / compatibility

- No DB migrations. The cap state is in-memory only; restarts
  re-seed from SMOLCODE_COST_CAPS env. (Persistent caps can be a
  follow-up if operators ask.)
- Older SPA clients (no cost_caps request) still work: the new
  getDashboard() response is additive (cost_estimate_usd_today is
  already present per decision 0028; we only added cost_usd to the
  TokenSummary shape).
- Older BE clients (pre-0032) ignore the new cost_caps env. Caps
  default to empty.

## Known limitations

1. No persistence. Caps live in process memory; a restart drops
   overrides unless SMOLCODE_COST_CAPS is set. Acceptable for v1.9
   because the operator's intent is stop right now, and defaults
   survive restarts.
2. Per-run ceiling not user-configurable. Layer B uses a flat
   cap * 2 per-run ceiling (decision 0025 10.5). Operators who
   want a tighter ceiling can set the day cap low.
3. Multi-run day-cap drift. N concurrent runs each have their own
   per-run ceiling but the day check only fires at start, so N *
   per-run-cap can leak past the day cap. Operators who care should
   set day cap = N * per-run-cap.
4. Pause/resume skips per-step check. Documented above.
5. minimax (any case) alias rejected with 400. Lowercase alias
   is convenient but rejected so the SPA can prompt the user to use
   the canonical MiniMax id.

## Followups

1. Persistent caps (per-project config file or DB row).
2. Per-model caps (extend tracker key to provider/model).
3. Webhook / Slack notification on cap hit.
4. CLI: smolcode caps --set openai=$5.