# 0008 — M5: orchestrator + specialists (proposed)

**Date:** 2026-08-19
**Status:** active
**User sign-off (Q-M5.1):** B — opt-in via `--orchestrator` flag only (env var deferred; see D8).
**Supersedes:** — (none; first orchestrator decision)
**Related:** `0001-initial-setup.md` (orchestrator scope = always present), `0006-m4-elevated-full-access-tiers.md`, `0007-m4x-per-tool-confirmation-checkpoint.md`, `docs/roadmap.md` §6

> Decision 0008 was PENDING until the user gave the green light ("proceed to M5").
> Per the recommendation in this doc, Q-M5.1 was resolved to **option B** (opt-in
> via `--orchestrator` flag only; no env var in v1; smallest change; preserves
> the existing restricted-default behavior for CI scripts).

## Question

M5 introduces the orchestrator agent — a `CodeAgent` whose only tools are
`do_restricted_task`, `do_elevated_task`, and `do_full_task`. The orchestrator
receives the user's task and decides which tier (and which specialist) to
delegate to.

Decision 0001 said "Orchestrator scope → always present", but that was decided
before the M4.x per-tool destructive gate existed. Adding the orchestrator
changes *which agent* the user is talking to when they type
`smolcode "task"` without `--tier` — that's a meaningful behavioral change
worth re-confirming.

**Q-M5.1:** Should the orchestrator be the v1 default, or only when
`--orchestrator` is passed?

## Findings

### Current default behavior (M4.x)

- `smolcode "task"` → builds the `restricted` agent and runs the task directly.
- `smolcode --tier elevated "task"` → builds the `elevated` agent and runs directly.
- `smolcode --tier full_access "task"` → builds the `full_access` agent (with confirmation prompt) and runs directly.
- `smolcode --print-config` → no agent built; just dumps config.

The CLI has no orchestrator today; the user always picks a tier (explicitly or
implicitly via the default).

### Why the orchestrator is a behavioral change

With the orchestrator on by default, `smolcode "task"` no longer means
"restricted agent runs the task". It means "orchestrator agent decides which
tier (or specialist) handles the task". The same input can produce a
different agent — and a different tool set, different confirmation prompt,
different audit trail — depending on the orchestrator's reasoning.

For an interactive user, this is the Claude-Code-like behavior they expect.
For a CI script that already works against the restricted tier, it's a
silent semantic break.

### What "always present" means in 0001's terms

Decision 0001's "always present" was about *availability*, not *default-on*.
The text reads: "Orchestrator scope → always present." It was answering
"is there an orchestrator in the design?", not "does `smolcode "task"` route
through it by default?". So switching to opt-in is not a contradiction of
0001; it's a refinement.

## Options

### A. Orchestrator by default (Claude Code-like)

- `smolcode "task"` → orchestrator picks a tier / specialist.
- `smolcode --tier X "task"` → tier-direct (bypasses orchestrator).
- Existing users + CI scripts get a different agent silently.
- Audit log records the delegation chain (orchestrator + sub-agent).
- Confirmation prompt fires at the orchestrator level (NOT at each sub-agent
  — see D2 below).

**Risk:** anyone with a CI script that does
`smolcode "run the test suite"` and expects restricted behavior will
suddenly get orchestrator behavior, which may pick `elevated` or `full_access`
if the orchestrator reasons that the task requires it.

### B. Opt-in via `--orchestrator` flag (recommended)

- `smolcode "task"` → unchanged from M4.x (restricted).
- `smolcode --orchestrator "task"` → orchestrator picks.
- `smolcode --tier X "task"` → unchanged (tier-direct).
- No behavior change for users who don't pass the flag.
- CI scripts that don't know about the flag continue to work.

**Trade-off:** the orchestrator is shipped and usable, just not on by
default. Users have to discover `--orchestrator` to use it. Documented in
README and `--help`.

### C. Opt-in via flag AND env var

- Same as B, plus `SMOLCODE_ORCHESTRATOR=1` env var activates it.
- Useful for CI/automation that wants to flip the default once.
- Same trade-off as B, but with one more surface.

## Recommendation: B

**Why:**

- **Smallest change.** M4.x ships with the implicit-restricted default.
  Adding the orchestrator as opt-in preserves that contract.
- **No CI break.** Existing scripts that work today keep working tomorrow.
- **The orchestrator is still shipped.** Users who want Claude-Code-like
  routing have an explicit, documented knob to turn it on.
- **Matches `CLAUDE.md` §2:** "Use the smallest change that completely solves
  the task."
- **Env var can be added later** for ~1 line of code if users ask for it.

If the user later decides they want C, it's a one-line addition (`_env_flag`
already exists in `cli.py` from M4.x). If they want A, the change is small
but the risk surface is bigger.

## Decisions (to be filled in once user picks)

| ID | Decision |
|---|---|
| **D1** | **RESOLVED (option B)** — orchestrator is opt-in via `--orchestrator` flag only. `smolcode "task"` (no flag) still defaults to restricted. Env var deferred (would be a one-line addition to `cli.py:_env_flag` if requested). |
| **D2** | Confirmation prompt fires at the orchestrator level only. Sub-agents do NOT re-prompt. (Reasoning: double-prompting the user is confusing; the orchestrator's confirmation already covers the run. Sub-agents still hit the M4.x per-tool destructive gate for `git_push` etc.) |
| **D3** | `do_restricted_task` / `do_elevated_task` / `do_full_task` are tools the orchestrator can call. Each one instantiates the named tier's agent and runs the task in that context. Returns the sub-agent's final answer to the orchestrator. |
| **D4** | Audit log records the delegation chain as nested `subagent` events: orchestrator event → sub-agent event(s) → final-answer event. (Audit schema extension; see D7.) |
| **D5** | Specialists are first-class agents (their own `make_agent` factory), but are NOT a separate tier — they run inside a tier (e.g. `deploy_staging` runs at `full_access`). The orchestrator routes to them via `do_specialist(name, task)`. |
| **D6** | v1 ships ONE sample specialist: `deploy_staging`. Full-access tier; narrowed toolset (`run` + `git_push` only — no fs tools). Declared extra paths in `config.py` (e.g. `~/.docker/`, `./infra/`). |
| **D7** | Audit log new event type: `subagent`. Schema: `{event: "subagent", ts, parent_event: "<orchestrator-event-id>", tier: "restricted" | "elevated" | "full_access", specialist: "" | "deploy_staging", task: "...", answer: "...", duration_s: N}`. |
| **D8** | `--orchestrator` flag is opt-in (per D1, option B). Env var `SMOLCODE_ORCHESTRATOR` is NOT wired in v1; adding it later is a one-line change to `cli.py:_env_flag` if asked. |
| **D9** | Orchestrator's system prompt tells it: "you have three sub-agents (restricted / elevated / full_access) and N specialists; pick the right one based on the task. If you're not sure, pick restricted." |
| **D10** | Specialists are loaded from `~/.smolcode/specialists.toml` (user-installed) + the bundled `deploy_staging` (always available). Specialists file schema: `{name: str, tier: "full_access" (only option in v1), description: str, extra_paths: list[str], tools: list[str]}`. |
| **D11** | Tier-direct runs (`--tier X`) do NOT go through the orchestrator even if `--orchestrator` is set. The two flags are orthogonal: `--tier` = "which tier"; `--orchestrator` = "let the orchestrator decide". |
| **D12** | Exit codes unchanged from M4.x. Orchestrator-level denial = exit 4 (same as M4 per-run confirmation denial). |

## Files to add / change (once approved)

| Path | Purpose |
|---|---|
| `smolcode/src/smolcode/agents/orchestrator.py` | NEW. `build_orchestrator_agent` + the 3 delegation tools. |
| `smolcode/src/smolcode/agents/specialists/__init__.py` | NEW. Specialist registry. |
| `smolcode/src/smolcode/agents/specialists/deploy_staging.py` | NEW. Sample specialist. |
| `smolcode/src/smolcode/agents/__init__.py` | EXTENDED. Export `build_orchestrator_agent`. |
| `smolcode/src/smolcode/cli.py` | EXTENDED. `--orchestrator` flag + `SMOLCODE_ORCHESTRATOR` env var; route to orchestrator factory if set. |
| `smolcode/src/smolcode/config.py` | EXTENDED. Optional `specialists` section in `Settings` (loaded from `~/.smolcode/specialists.toml`). |
| `smolcode/src/smolcode/tests/test_orchestrator.py` | NEW. 10+ tests. |
| `docs/decisions/0008-m5-orchestrator.md` | THIS FILE — change Status from PENDING to active once Q-M5.1 is resolved. |
| `smolcode/README.md` | EXTENDED. New `## M5: Orchestrator + specialists` section + usage example + specialist list. |
| `docs/roadmap.md` | EXTENDED. M5 SHIPPED status + Q-M5.1 resolved. |
| `docs/architecture.md` | EXTENDED. Remove "M5 work" placeholder; describe the orchestrator shape. |

## Acceptance gates (per roadmap §6 M5)

| Gate | Expected |
|---|---|
| `ruff check src` | PASS |
| `ruff format --check src` | PASS |
| `pytest src/` | PASS (~336 tests: 326 prior + ~10 orchestrator) |
| `smolcode --smoke --orchestrator "echo hi"` | orchestrator runs, picks restricted (per its system prompt) |
| `smolcode --smoke "echo hi"` (no `--orchestrator`) | unchanged from M4.x (restricted, no extra behavior) |
| `smolcode --smoke --orchestrator --deploy-staging "echo hi"` | deploy-staging specialist runs (narrow toolset; full_access tier) |
| Audit log records orchestrator + sub-agent events | PASS |
| Decision 0008 status = active | PASS |

## Open questions deferred to v1.1 / M5.x

- Multiple specialists beyond `deploy_staging` (M5 ships one; users can install more).
- Orchestrator auto-routing based on task content (v1's orchestrator picks a tier from the task description; v1.1 may add explicit routing rules or an embedding-based router).
- Specialist hot-reload (re-read `specialists.toml` without restart).
- Orchestrator's own audit-event schema (`subagent` events are flat; v1.1 may nest).
