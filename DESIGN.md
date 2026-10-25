---
name: smolcode
description: A local, loopback-only workbench for auditable agent runs.
colors:
  ink: "#171c19"
  ink-deep: "#11181a"
  rail: "#0f1719"
  rail-raised: "#131f20"
  vellum-ground: "#e8eae2"
  vellum-paper: "#f4f4ee"
  hairline: "#c9cec4"
  hairline-strong: "#9ea79d"
  muted-ink: "#59645c"
  ultramarine: "#2d4bcc"
  ultramarine-deep: "#213ba8"
  ultramarine-wash: "#dfe5ff"
  amber-ink: "#7a4408"
  amber-live: "#d99a2a"
  amber-wash: "#f2e7d1"
  refusal-red: "#a93831"
  verified-green: "#23674d"
  white: "#f7f7f1"
  code-ground: "#11191b"
  code-ink: "#e3e7df"
typography:
  objective:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "29px"
    fontWeight: 600
    lineHeight: 1.08
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Archivo, Public Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "-0.035em"
  body:
    fontFamily: "Archivo, Public Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Courier Prime, JetBrains Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "0.01em"
  evidence:
    fontFamily: "Courier Prime, JetBrains Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: "4px"
  md: "5px"
  lg: "6px"
spacing:
  hair: "1px"
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "18px"
  xxl: "26px"
components:
  button-primary:
    backgroundColor: "{colors.ultramarine}"
    textColor: "{colors.white}"
    rounded: "{rounded.md}"
    padding: "0 11px"
    height: "30px"
  button-primary-hover:
    backgroundColor: "{colors.ultramarine-deep}"
  button-secondary:
    backgroundColor: "{colors.vellum-paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 11px"
    height: "30px"
  chip-tier:
    backgroundColor: "{colors.vellum-paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "2px 7px"
    height: "22px"
  gate-dock:
    backgroundColor: "{colors.amber-wash}"
    textColor: "{colors.ink}"
    padding: "11px 14px"
  composer:
    backgroundColor: "{colors.rail}"
    textColor: "{colors.white}"
    padding: "9px 16px"
  sheet:
    backgroundColor: "{colors.vellum-paper}"
    textColor: "{colors.ink}"
    rounded: "0"
---

# Design System: smolcode

## Overview

**Creative North Star: "The Revision Desk"**

smolcode is a desk for proofing agent work, not a dashboard for watching agents. A run arrives as a manuscript: an objective set in serif, evidence set in monospace, and a continuous spine running down the margin from start, through actions and diffs, to the moment a human signs a release. The change is held on the desk until that signature. The audit chain is the margin record that survives the session.

The world is built from two materials. Deep ink is the rail, topbar and composer — the desk's edge, where work is selected and started. Vellum is the stage — one run at a time, full-bleed, with generous air around the objective. The interface must feel like a working document that happens to be software, never like a terminal emulator, a control panel, or a metrics grid.

Every screen earns its place by helping a person decide. There is no table home, no permanent three-pane console, no right-hand inspector that stays open "for context". Runs, changes, console, files, audit, sessions and usage arrive as deliberate sheets over the stage. The empty stage is a real state: a blank sheet with a single invitation, not an empty dashboard.

**Key Characteristics:**
- One run is the unit of work; the stage shows one run at a time.
- A continuous run spine connects trace rows, time notches, the gate cut and the audit chain.
- The approval gate is inline at the foot of the stage, not a modal interruption.
- Three type registers: serif for human theses, sans for controls, mono for evidence.
- A deep-ink rail and composer keep instrument controls at the edge of the paper.
- Restraint is structural, not decorative: no gradients, glass, grain, emoji or costume.

## Colors

A vellum-and-ink palette with one working blue, one live amber and two outcome colours. Colour is information; it is never atmosphere.

### Primary
- **Ultramarine Action** (#2d4bcc): the only colour for actions the person can take and for the selected state. Primary buttons, active tabs, focused inputs, links, selected tier radio. Hover deepens to #213ba8. A pale wash (#dfe5ff) may mark a selected row or key, never body text.
- **Deep Ink Rail** (#0f1719): the topbar, run rail and composer. It is a single continuous edge, not a second content surface.

### Secondary
- **Revision Amber** (#a75f0b, ink) and **Live Amber** (#d99a2a): held, waiting and live states only — awaiting approval, the current trace node, the gate marker, the run's live dot. The wash (#f2e7d1) is the gate's paper. Amber never means "warning" in general.
- **Refusal Red** (#a93831): deny, stop, errors and the approval gate's refusal path.
- **Verified Green** (#23674d): approved, done, chain verified. It appears after the decision, never before it.

### Neutral
- **Ink** (#171c19): primary text on vellum; **Ink Deep** (#11181a): code and dark fields.
- **Vellum Ground** (#e8eae2): the stage; **Vellum Paper** (#f4f4ee): cards, sheets, inputs, diffs.
- **Hairline** (#c9cec4) and **Hairline Strong** (#9ea79d): 1px structural rules only. **Muted Ink** (#59645c) passes 5.08:1 on vellum.
- **White** (#f7f7f1): text on the rail; **Code Ground / Code Ink** (#11191b / #e3e7df): evidence surfaces only.

### Named Rules
**The Signature Line Rule.** Ultramarine marks what a person can do or has selected. It is never used for decoration, status or a section label. If a blue element cannot be clicked or is not selected, it is wrong.

**The Held Change Rule.** Amber means a decision is outstanding, red means it was refused or stopped, green means it was verified. These three colours never trade roles, and green never appears before a decision is recorded.

**The Paper Is the Stage Rule.** The dark rail is an instrument edge, not a content background. Never place a second dashboard or document surface inside the rail.

## Typography

**Display / UI Font:** Archivo (with Public Sans, ui-sans-serif, system-ui, sans-serif)
**Objective Font:** Source Serif 4 (with Georgia, serif)
**Evidence / Label Font:** Courier Prime (with JetBrains Mono, ui-monospace, monospace)

**Character:** A documentary pairing rather than a product-marketing pairing. Archivo is compact and civic; Source Serif 4 gives the objective the authority of a written brief; Courier Prime makes timestamps, paths, tool calls and audit hashes read as evidence rather than prose. The contrast between the three is the hierarchy.

### Hierarchy
- **Objective** (600, 29px / 1.08, -0.025em): the run's task statement at the top of the stage. Max 44ch, balanced, never uppercase.
- **Headline** (600, 26px / 1): sheet titles such as New run and Audit chain. One per sheet.
- **Title** (600, 23px / 1.1): the held-change heading and section headings inside the stage.
- **Body** (400, 13px / 1.45): UI copy, explanations, empty states. Keep prose to 62–72ch.
- **Label** (400–500, 12px / 1.4, 0.01em): metadata, tabs, chips, timestamps, paths. 12px is the hard floor for interface text.
- **Evidence** (400, 12px / 1.6): trace details, console frames, diffs, hashes.

### Named Rules
**The Three Voices Rule.** Serif is for what the human decided or asked; sans is for what the interface offers; mono is for what the machine recorded. Never set a code path, timestamp or diff in serif, and never set a paragraph in mono.

## Layout

The shell is a fixed instrument frame around a paper stage.

- **Topbar:** 46px, deep ink; brand, project selector, daemon state, live need-you count, and utility actions.
- **Run rail:** 72px at desktop, fixed at the left; 44px run chips with status dots, then queue, audit, help at the foot. Below 900px the rail becomes a 57px horizontal strip under the topbar, scrollable with a mask fade.
- **Stage:** fills the remaining width and height. It scrolls inside itself; the page never does. The objective block sits at the top with the run meta row; mode tabs (Trace, Changes, Console, Files) sit below it. The mode panel is the only scrolling region.
- **Gate dock:** anchored to the bottom of the stage, above the composer. It is part of the stage, not an overlay; it takes its own height and compresses the mode panel.
- **Composer:** 114px at desktop, 150px at mobile; deep ink, a task input, a primary Run action, and provider / tier / model chips.
- **Sheets:** side sheets (Runs) at 364px, drawers (Context, Audit, Sessions, Usage, Help) at 392px, launch sheet at min(840px, 100vw − 140px). All use a scrim and a focus trap. Nothing is permanently docked on the right.

Breakpoints: 1120px tightens metadata and stage padding; 900px collapses the rail to a horizontal strip, moves Changes to a single column with the diff first, and widens the composer; 560px hides secondary topbar icons and allows the gate actions to wrap. At every width, the composer stays at the bottom and the gate stays directly above it.

Spacing follows a 4 / 6 / 8 / 12 / 18 / 26 rhythm. Stage padding is 15–28px horizontally and 12–24px vertically. Sheets use 14–16px padding on the dark side and 16–20px on paper drawers.

## Elevation & Depth

Depth is tonal first. The rail is darker than the stage, the stage is darker than paper cards, and paper is darker than focused fields. This tonal stack carries most of the hierarchy; shadows only separate things that genuinely float.

There are exactly two shadow tokens. Shadow 1 is a quiet paper-card shadow: 0 1px 2px rgba(15,23,25,.05), 0 7px 18px rgba(15,23,25,.06). Shadow 2 lifts side sheets and drawers: 0 18px 50px rgba(8,13,13,.26), mirrored horizontally for right-side drawers. The launch sheet uses a single upward shadow, 0 -12px 42px rgba(8,13,13,.24), because it rises from the composer. No hard offset shadows, no glow, no glass, no neumorphism.

The scrim is a flat rgba(8,13,13,.38) over the whole viewport, including the composer; the open sheet is the only interactive layer. Modal sheets are genuinely modal.

### Named Rules
**The One Depth System Rule.** A surface either sits flat on its tonal ground or floats as a sheet with Shadow 2. Do not invent intermediate elevations, coloured glows or outlines that pretend to be depth.

## Shapes

The form language is paper and rule: 1px hairlines, 4px cards and diff frames, 5px buttons, 6px chips and tags, and one 10px rotated square for the gate. Corners are tight because the content is documentary; there are no pill-shaped buttons or oversized radii.

Borders do the structural work. A change is enclosed by a 1px hairline with a 2px amber top rule only at the gate. The run spine is a 1px vertical line through nodes and time notches; it terminates in the gate's diamond. Do not add a second decorative line beside it.

## Components

### Buttons
- **Shape:** 30px high, 5px radius, 12px Archivo 500.
- **Primary:** ultramarine ground, white text, 0 11px padding; hover deepens to #213ba8. Used for Run and Approve only.
- **Secondary:** vellum-paper ground, hairline-strong border, ink text; hover raises to white with an ink border. Deny uses red text and a red-tinted border but stays visually secondary to Approve.
- **Focus:** 2px ultramarine outline with 2px offset. Never remove it.

### Chips and Tags
- **Style:** tier tags and file counts use 6px radius, 22px height, mono 12px, a hairline border and paper ground. Status is carried by a 6px dot plus a word, never by fill alone.
- **State:** selected tier is marked by a radio and an ultramarine-wash row, not by a solid blue fill.

### Inputs and Fields
- **Composer input:** dark ink field on the rail, 1px #2b3733 border, white text, amber focus ring. It is the one place where amber focus is intentional: the composer is where a live task begins.
- **Paper fields:** vellum-paper ground, 1px hairline-strong border, 4px radius, 12–13px body text. Focus uses the ultramarine ring. Error text is red and sits below the field, never as a placeholder.

### Navigation
- **Run rail:** 44px square chips, 4px radius, status dot at the top-right; the active chip is lifted with a paper border and a 3px ultramarine bar. Hover reveals the run id and task in a small ink tooltip.
- **Tabs:** text-only, 12px mono, 1px bottom border on the active tab. No segmented control shells, no background pills.
- **Sheets:** the sheet header is the navigation: one serif title, one mono subtitle, a close button. Back and forward do not belong inside a sheet.

### Gate Dock (signature)
The gate is a single amber-washed strip at the foot of the stage, with a 2px amber rule on its top edge and a document icon at its left. It states the held file and the +/- counts, then offers exactly three decisions: Approve, Deny, and No more prompts this run, plus a Details disclosure. Approving turns the rule green and records the reason in the audit chain. The gate is bound to one diff and one run; it never batches decisions.

### Run Spine (signature)
Trace rows share a three-column grid: 63px time notch, 24px node, flexible content. A 1px vertical line runs through the node column; nodes are 9px circles, square for sub-steps, diamond for the gate, filled red for errors and green for approval. The gate row cuts the spine with a horizontal rule and a paper card. The spine continues in the audit drawer as the hash chain, so the same evidence line is legible before and after the decision.

### Cards and Containers
- **Corner style:** 4px.
- **Background:** vellum paper on vellum ground.
- **Border:** 1px hairline; only the gate uses an amber border.
- **Shadow:** cards sit flat; sheets use Shadow 2.

## Do's and Don'ts

### Do:
- **Do** keep one run on the stage and make the empty stage a deliberate blank sheet.
- **Do** keep the approval gate inline, visible, and bound to one diff and one run.
- **Do** use ultramarine only for actions and selection, amber only for held/live, red only for refusal/error, green only for verified outcomes.
- **Do** set objectives in Source Serif 4 and evidence in Courier Prime; keep every UI label at 12px or larger.
- **Do** keep the composer at the bottom and reachable at every breakpoint, with a 44px minimum touch target for icon controls.
- **Do** respect prefers-reduced-motion: transitions are short opacity/colour changes, never staged movement.
- **Do** keep the product truth visible: tier, provider, model, loopback host, and audit chain are readable without opening a settings maze.

### Don't:
- **Don't** build a dashboard home, a permanent three-pane layout, or a right-hand inspector that never closes.
- **Don't** dress the app as a terminal: no scanlines, blinking cursors as decoration, ASCII ornaments, or all-mono body copy.
- **Don't** use gradient text, glass panels, decorative grain, hard offset shadows, emoji icons, or invented glyphs.
- **Don't** use a coloured left border thicker than 1px as a status device; use a dot, a word, or a wash.
- **Don't** show design-direction names, seed metadata or internal vocabulary in the product UI.
- **Don't** allow a sheet to leave the composer visually live while the sheet is modal; the scrim covers the whole viewport.
- **Don't** trade WCAG AA contrast, keyboard reachability or reduced-motion support for atmosphere.
