# Workbench — round three direction

**Status:** proposed, awaiting approval  
**Prototype:** [`prototypes/workbench/index.html`](prototypes/workbench/index.html)  
**Screens:** [trace](prototypes/shots/workbench-trace-1440.png) · [changes](prototypes/shots/workbench-changes-1440.png) · [approved](prototypes/shots/workbench-approved-1440.png) · [runs](prototypes/shots/workbench-sessions-1440.png) · [launch](prototypes/shots/workbench-launch-1440.png) · [audit](prototypes/shots/workbench-audit-1440.png) · [mobile](prototypes/shots/workbench-trace-390.png)

## The honest diagnosis

Cuebook, Custody, and Bonded were three different visual worlds applied to the same app.

All three used the same skeleton:

- a top bar with product navigation,
- a left navigation or plan pane,
- a summary band / hero stat strip,
- a wide table or card list as the home screen,
- a right-hand card stack or inspector,
- approvals in a modal.

Changing the palette, type, and metaphor did not change the product model. The most important object in smolcode — **one run and its evidence** — never became the page. That is why round two read as a reskin even when the worlds were distinct.

This direction starts from the run, not from a dashboard layout.

## What the product actually is

From `PRODUCT.md`:

- The **run** is the unit of work. Everything hangs off one run’s evidence.
- The **tier ladder** is the product. The boundary must stay visible.
- The **approval gate** is bound to one diff or action, not to a generic modal.
- The **audit log** is hash-chained and verifiable.
- The server is **loopback-only**, and the app is a working console, not a marketing site.
- The operator is impatient and risk-aware: they want to see what happened, what changed, what it cost, and what needs them.

A dashboard organises *many things*. This product is mostly *one thing at a time, with many things recoverable*. The shell should reflect that.

## Research: what current agent tools get right

I reread `frontend-design` and `impeccable` for this surface, then looked at current agent UIs rather than inventing a layout in isolation.

- [Claude Code desktop redesign](https://claude.com/resources/articles/claude-code-desktop-redesign) and [desktop docs](https://code.claude.com/docs/en/desktop): parallel sessions, drag/drop panes, integrated diff, “many things in flight, one orchestrator seat.”
- [OpenAI Codex app](https://openai.com/index/introducing-the-codex-app/): a “command center for agents,” project threads, parallel worktrees, review queue, comments on a diff.
- [Cursor Agents Window](https://cursor.com/docs/agent/agents-window): agent-first workspace, parallel agents, a dedicated diffs view, multi-workspace.
- [Beamline Run trace](https://beamline.io/components/run-trace): one run as a nested waterfall on a shared time axis, live-growing bars, retries, tokens and cost per step, keyboard tree grid.
- [Mandatum](https://github.com/caseyrtalbot/Mandatum): terminal panes, execution timeline, command palette, approval before shell commands.
- [Viden](https://github.com/wikieden/viden): local-first cockpit with transcript, approvals, workspace, providers, lanes, and evidence.
- [Agent progress trace pattern](https://uxpatternsguide.com/patterns/agent-progress-trace/) and [agent UI best practices](https://limecloud.github.io/agentui/en/authoring/best-practices): separate final answer, reasoning, and tool events; compress process by default; make states explicit — `loading`, `unknown`, `unavailable`, `stale`, `blocked`, `needs-input`, `failed`, `disputed`; approvals are controlled writes with audit.

What I take from that:

1. **The run is the workspace.** Sessions and runs are navigation, not permanent chrome.
2. **The trace is the primary canvas.** It is the evidence, not a log tab.
3. **The gate belongs inside the run.** The approval should be visible where the diff is, bound to that diff.
4. **Alternate views are modes of the same stage.** Changes, console, files — not three competing panes.
5. **States must be explicit and quiet.** Waiting, running, done, returned, no diff, stale, blocked.
6. **Keyboard is the fast path, not a feature page.**

## Direction: Workbench / Revision sheet

**Assigned direction:** index 3, seed ref `seed:0b7d2a780ca78f59`, build path code-led.  
This is recorded here for design provenance; it is not user-facing copy.

The world may contribute only **type, palette, density, and one signature move**. It must not supply layout, navigation, or controls. The controls stay standard web controls.

### The idea

A **revision sheet**: the run is a sheet of paper on a workbench. The left edge is the binding; the trace is the ruled spine; the gate is a cut across the sheet where a human signature is required. The audit trail is the same spine continued into the chain.

This gives the product one visual idea instead of a costume:

- **The run spine** runs continuously through trace rows, time notches, the approval cut, and the audit entries.
- **A gate is a break in the spine**, not a floating modal.
- **The revision mark** (run id, diff sha, audit seq) is always recoverable.

### Palette

| Token | Value | Role |
| --- | --- | --- |
| Ink rail | `#0f1719` | rail and composer; the bench edge |
| Vellum | `#e8eae2` | stage; the sheet |
| Paper | `#f4f4ee` | docks, sheets, drawer |
| Ultramarine | `#2d4bcc` | action, focus, selected |
| Amber | `#b97812` / `#7a4408` | waiting, live, gate attention |
| Signal red | `#a93831` | blocked / rejected / destructive |
| Verified green | `#23674d` | done / verified |

Six named colours plus tints. No neon, no gradient text.

### Type

- **Archivo** — UI, labels, buttons, tables.
- **Source Serif 4** — the run objective and sheet titles; the human document voice.
- **Courier Prime** — ids, timestamps, hashes, diff, console; the evidence voice.

Three roles, each doing a job. The serif is not decoration; it marks the thing the human is signing off.

### Signature move

The run spine:

- a hairline through the trace with small time notches,
- a filled node at the current event,
- a horizontal cut where the gate interrupts the run,
- the same chain rhythm in the audit drawer.

It is the one thing a screenshot should be recognisable by. The rest stays quiet.

## Structure

```
┌──────────────────────────────────────────────────────────────┐
│ top bar: product · project · daemon · needs you · budget     │
├──────┬───────────────────────────────────────────────────────┤
│ run  │ stage head: crumb · objective · meta · modes           │
│ rail │                                                       │
│      │ trace / changes / console / files                     │
│ 7f3a │                                                       │
│ 2b9c │                                                       │
│ ...  │                                                       │
│      │ gate dock (only when the run needs a human)           │
├──────┴───────────────────────────────────────────────────────┤
│ composer: new directive · attachments · tier · model · run    │
└──────────────────────────────────────────────────────────────┘
```

- **46 px top bar.** Product, project + workspace, loopback daemon, “needs you,” budget. No tab navigation.
- **72 px run rail.** Vertical run ids, each a chip with tier/status. A menu, queue count, audit, help. It is navigation, not a sidebar document.
- **Full-bleed stage.** One run owns the screen. No permanent left composer; no permanent right inspector.
- **Stage modes.** `Trace`, `Changes`, `Console`, `Files`. Only the active mode is mounted. The count of pending changes is a tab badge.
- **Inline gate dock.** The approval lives at the bottom of the run, bound to the current diff. It states what will be released, the file, the sha, the tier, and the image. Approving moves the run forward and writes the audit entry.
- **Composer.** A persistent console-like input at the bottom, with tier/model/attachments; `⌘Enter` runs. It collapses off mobile into a two-row bar.
- **Overlays.** Runs sheet, New run sheet, Audit drawer, Context drawer, command palette. All temporary; `Esc` closes; scrim click closes; focus returns.
- **URLs.** `#trace`, `#changes`, `#console`, `#files`, plus `#sessions`, `#launch`, `#audit`, `#palette` for prototype review. In the app these become real routes or search params.

## States that must exist

The prototype includes, or has a slot for:

- `Queued` — no events yet; shows the queue position, requested time, estimate.
- `Running` — live spine, elapsed, current step.
- `Awaiting approval` — gate dock, diff tab badge, needs-you count.
- `Done` — green verified; audit entry; changes tab disabled when no diff.
- `Returned` — agent stopped without a diff; explicit “no captured diff,” not an empty screen.
- `Blocked` / `Needs input` — explain what would unblock it, in the run, not a toast.
- `Stale` — image or preview older than the run; show the stale marker from the product model.
- `Empty queue` — says “Queue drain is off. Runs wait for a human; nothing starts silently.”
- `No changes` — says why, not just an empty list.

## Interaction model

- **Trace rows** expand details in place; no drawer for every event.
- **Review** moves the gate into Changes; the gate dock changes label from “Review change” to “Approve change.” One diff, one approval, one audit entry.
- **Approve** resumes the run, clears needs-you, updates spend/audit, and confirms with a toast that names the run and audit number.
- **Reject** returns the run with a typed reason; the rejection is audited.
- **Hold** parks the run without releasing the diff.
- **Runs (S)** opens the drawer over the stage; selecting a run closes it and loads that run.
- **New run (N)** opens the tier sheet; restricted is selected and explained; elevated and full_access are opt-in and explicitly labelled.
- **Audit (G)** opens the chain drawer; sequence, event kind, sha, and linked diff.
- **Command palette (⌘K / Ctrl-K)** is the keyboard index; `?` shows shortcuts.
- **Escape** closes the top overlay; **Enter** on a session selects it.

## What this is not

- Not a dashboard of cards. The queue is a secondary table, not the home screen.
- Not a terminal costume. No fake prompt chrome, no ASCII decoration, no invented glyphs.
- Not three permanent panes. The old `320px / 1fr / 360px` shell is removed.
- Not a modal approval. The gate is in the run.
- Not a statistics hero. Spend and audit live in the top bar and audit drawer.
- Not a palette change on the old layout. The IA and the skeleton are different.

## Craft floor compliance

- Text is 12 px minimum; body copy is 13–15 px; measure on prose is 60–70 ch.
- Key contrast pairs pass AA: muted `#59645c` on vellum 5.08:1; muted-2 `#5f6a61` 4.65:1; amber ink 6.44:1 on amber tint; red 4.88:1; green 5.41:1; white on ink rail 16.88:1.
- No gradient text, glass, grain, emoji, decorative left borders, repeating stripe overlays, or hard offset shadows.
- Depth is one system: sheets and drawers lift with a soft shadow; the stage is flat.
- Radius: 10–12 px on controls and sheets; no pill-everything.
- Focus: 2 px ultramarine ring, offset 2 px; keyboard paths documented.
- Motion: one entrance, gate state changes, toast; all disabled under `prefers-reduced-motion`.
- Responsive: 1440 / 1024 / 768 / 390 checked; rail becomes horizontal under 900 px; sheets go full width; launch becomes a full-height sheet; diff scrolls inside the stage; no horizontal page overflow.
- Browser surfaces: `color-scheme: light`, `theme-color` ink, selection ink on vellum.

## Implementation plan for the real app

No React source has been changed yet. The prototype is a direction, not a claim of completion.

1. **Shell and tokens.** Replace the three-pane `App.tsx` layout with the top bar + run rail + stage + composer. Move the palette/type scale into a `workbench.css` token layer.
2. **Run state and routing.** Use the existing run/session state; add a view mode and run selection without duplicating server state. Keep deep-linkable run/view URLs.
3. **Trace.** Port the real event model to a virtualised trace spine. Preserve event type, time, tool call, file, cost, and expandable detail. Do not invent event names.
4. **Changes and gate.** Port `DiffViewer` into stage mode. Wire `ApprovalModal` semantics into the gate dock; keep the approval bound to the diff hash and run. Keep reject/hold.
5. **Sessions, queue, launch, audit, context.** Move existing `SessionsPane`, `QueuePane`, `AuditPanel`, `SubAgentList`, `WorkspaceTree`, `FilePreview`, provider/tier controls into sheets and drawers. Keep all capabilities; remove persistent chrome.
6. **Composer.** Reuse the existing composer fields: directive, uploads, tier, provider, model, workspace, auto-approve. Preserve validation and provider key handling.
7. **Accessibility and tests.** Add focus return/trap for sheets, `aria-live` for run state, skip link, keyboard coverage, reduced-motion checks, 390/768/1024/1440 visual checks, and Playwright smoke tests for approve/reject/queue/audit.
8. **Cleanup.** Delete the old shell only after parity is verified; do not leave two home screens.

## Open question

Is this the structural direction to take into the React app? If yes, the next step is the shell + trace + gate, then sessions/queue/audit as drawers, with the old shell removed once parity passes.
