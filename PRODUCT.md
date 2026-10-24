# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One primary user: a developer-operator running an AI coding agent on their own machine
(Windows/macOS/Linux) and, sometimes, a small trusted team sharing a self-hosted instance.
Their scene: a workstation with a repository open, Docker running, a hosted model key in hand,
and a task that needs real code execution without handing the machine to a model. They are
technical, impatient, and risk-aware: they expect to see exactly what the agent did, what it
touched, and what it cost. A secondary user is the same person returning after hours to check
what ran, what is queued, and what needs approval.

## Product Purpose

smolcode is a local, self-hosted multi-agent coding assistant: a browser UI plus CLI over
Hugging Face smolagents CodeAgent, with all model-written code executed in Docker sandboxes.
It exists so a developer can delegate real coding work to strong hosted models without granting
them the host. Success is a completed task with an intact audit trail, a reviewable diff, a
known tier, and a cost the user agreed to.

## Positioning

The tier ladder is the product: three distinct sandbox images and permission profiles
(restricted / elevated / full_access) with fail-closed gates, a hash-chained audit log, and an
approval gate on every destructive operation. Neighbouring tools either run agent code on the
host or hide the execution boundary; smolcode makes the boundary visible and reviewable, and
lets the user move up a tier deliberately rather than by default.

## Operating Context

- The web server binds loopback only and is run on the host; tier sandboxes run in Docker.
- Models come through LiteLLM (direct providers or a proxy), configured with API keys in the
  web UI or environment.
- MCP servers add tools; under the Docker executor they need explicit opt-in.
- Every run produces: steps/events, tool calls, file diffs, cost, and audit entries.
- The audit log is verifiable (`smolcode audit verify`) and hash-chained.
- Work is workspace-scoped; uploads and attachments are part of a run.
- The user often leaves runs unattended (queue) and returns to approve or inspect.

## Capabilities and Constraints

Confirmed in the codebase: run composer (tier, provider, model, workspace, attachments), live
event stream with code/tool output, approval modal for destructive diffs, workspace tree and file
preview, diff viewer, run history, queue with drain, sessions, sub-agent list, cost/usage limits,
audit panel, project switcher, auto-approve banner, stop/pause. Constraints: loopback-only web
server, Docker required for sandboxed execution, no host-side execution of model code, terminal
and tables must stay legible at density, the UI is a working console rather than a marketing site.

## Brand Commitments

Name: smolcode (lowercase in prose). Voice: precise, calm, technical, never hype. The tier names
are product terms and keep their spelling. No mascots, no gamification, no neon glow for its own sake.

## Evidence on Hand

The repository itself: 1,568 passing Python tests, 139 vitest, a Playwright suite, 41 ADRs,
docs/security.md, docs/operations.md, docs/environment.md. Screens and behaviours are verifiable
in smolcode/web/src (App.tsx and components). No marketing claims, customers, or benchmarks exist
and none may be invented.

## Product Principles

1. Show the boundary: tier, sandbox, approval, and audit are first-class visible state.
2. The run is the unit of work: everything hangs off one run's evidence, not a chat log.
3. Density with legibility: the operator scans many facts per second; hierarchy earns density.
4. Fail closed, explain openly: when something is blocked, the UI says why and what would unblock it.
5. Calm under load: live streams and queues must stay readable during motion.

## Accessibility & Inclusion

Keyboard-first operation (the existing app has keyboard shortcuts and a command palette mindset);
visible focus states; AA contrast for text and controls; colour never the only carrier of run
state (icons/labels accompany status colours); reduced-motion support for live indicators.
