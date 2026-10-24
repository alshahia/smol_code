# Frontend directions — decision brief

**Status:** awaiting the operator's choice
**Date:** 2026-10-24
**Scope:** visual direction and interaction prototype for the smolcode web app
**Files:** `design/prototypes/` (open `index.html` by double-click)

This document records the design process, the three committed worlds, and the
evidence gathered. It is development-only: it must never be copied into the
browser-delivered app or any user-facing artifact. `DESIGN.md` and
`.impeccable/design.json` are written only after a direction is chosen.

---

## 1. Brief

Re-design the frontend of smolcode — a loopback-only, host-run, Docker-sandboxed
multi-agent coding assistant — around the truths that actually differentiate it:

- a visible **tier ladder** (restricted / elevated / full access) that the
  operator can read at a glance and change deliberately;
- a **human approval gate** for destructive steps, bound to one diff and one run;
- an **append-only hash-chained audit** that answers "who did what, with what
  image, at what cost";
- an **inspector** that keeps policy, workspace, file, and diff evidence in
  view while the run is still live;
- a composer that is a *console*, not a chat box: project, tier, provider,
  model, uploads, task, auto-approve, caps.

Product posture per `PRODUCT.md`: developer-operator on their own machine;
precise, calm, evidence-first; lowercase `smolcode`; keyboard-first; WCAG AA;
reduced-motion respected. The prototype data is synthetic and labelled as such.

## 2. Method

The work followed the impeccable skill in Operate mode:

1. `impeccable context` → `NO_PRODUCT_MD`; `init` wrote `PRODUCT.md` with the
   platform, operator, purpose, loop and five principles.
2. `concept-seed --scope direction --mode operate` rolled key
   `71586e88925f66781a284129c6e44a28`, **assigned index 7** of my grounded list.
3. Direction contract applied throughout: a world may lend **type, palette,
   density, and one signature move** — never the destination set, action
   semantics, or control behaviour. Navigation is themed (rail, tabs, masthead)
   but resolves to the same screens and actions; all controls stay standard; no
   invented glyphs, no decorative chrome, no image comps. Build was code-led.
4. Craft floor then held across all four documents: no kickers over headings,
   no gradients/glass/hard shadows, one depth system, 12–16px card radii, body
   contrast ≥ 4.5:1, measure 65–75ch, 12px minimum UI text, one authored motion
   moment, all states, 390px responsive, reduced motion.

### Grounded list (resonance order)

1. Airport wayfinding — saturated yellow, grotesque numerals, huge tier bands
2. Composing-room galley proof — paper, rules, margin corrections
3. Nautical chart and ship's log — bearings, fixes, weather margins
4. Museum conservation condition report — object, condition, treatment
5. Land registry survey plan — parcels, seals, measured boundaries
6. Library card catalogue — drawers, cards, cross-references
7. **Stage manager's prompt book / cue sheet — assigned**

The concept-seed **pick card** was *airport yellow wayfinding*. The challenger
draw was *lexicon shoulder and plate*. Those became Wayfinding and Lexicon;
Cuebook is the assigned direction.

## 3. The three worlds

### I — Cuebook (assigned · theatrical prompt book read at 1am)

- **Thesis:** a run is a performance; every step is a cue, and the gate is a
  held cue waiting for GO.
- **World:** warm near-black desk, ivory ink, cue red, standby amber, olive
  status; typewriter labels against a grotesque UI; hairlines, not boxes.
- **Signature move:** the cue rail — numbered rows (Q01…), state words
  STANDING BY / GO / HOLD, one held diff rendered as a cue sheet.
- **Navigation:** left rail (Call sheet, Cue sheet, Queue, Sessions, Audit trail,
  Settings), tonight's call table, 3-pane console.
- **Built:** overview, run console with live cue stream and evidence rail,
  audit with chain/policy/workspace, settings ("House rules"), approval sheets
  for run_2b9c and run_7f3a, mobile, keyboard focus, Escape, Cmd/Ctrl+K.
- **Pick it if:** identity and atmosphere matter as much as throughput; you
  want the approval moment to feel like a deliberate cue, not a dialog.
- **Watch:** the dark, dense rail is the most "designed" of the three; it needs
  discipline to keep long sessions calm rather than theatrical.

### II — Wayfinding (pick card · airport signage)

- **Thesis:** a terminal that answers "where am I, what tier, what is happening,
  what do I do next" before you read a single paragraph.
- **World:** poster yellow bands on bone paper, black rail, grotesque display
  type, tier letters R/E/F, arrow as the only ornament.
- **Signature move:** the full-width **status band** — RUN 7F3A · RESTRICTED
  SANDBOX · RUNNING — and a one-line "Review the gate →" prompt.
- **Navigation:** top tabs (Overview, Console, Queue, Audit, Settings) and a
  departure board of runs.
- **Built:** overview with departures board, console with event stream and
  evidence/folders/policy tabs, audit with chain-verified plate and policy
  matrix, settings, gate sheets for both runs, mobile, keyboard, hash deep links.
- **Pick it if:** you want the clearest at-a-glance state machine and the most
  authoritative "tier gate" read; it scales best to a second monitor and a
  glance-from-across-the-room workflow.
- **Watch:** yellow is a commitment; it will dominate the product's identity and
  needs restraint in secondary surfaces.

### III — Lexicon (challenger · working reference book)

- **Thesis:** the whole product is a register — runs are entries, the transcript
  is an annotation, diffs are printer's corrections, audit is the register.
- **World:** cream paper, ink, vermilion, olive; Source Serif 4 argument, Karla
  apparatus, JetBrains Mono record; rules, hanging annotations, shoulder index.
- **Signature move:** the **entry** — a run read as a book entry with lettered
  annotations (a–h), margin notes, and a printer's-correction diff.
- **Navigation:** masthead, contents strip, shoulder thumb index, guide rules.
- **Built:** index, run entry with apparatus tabs (Evidence / Files / Policy),
  register audit with chain-ok stamp and policy-in-brief, colophon settings,
  proof-slip approval, mobile, tabs, hash deep links.
- **Pick it if:** trust and legibility are the brand; you want an app that feels
  like an instrument of record and reads well in daylight for long sessions.
- **Watch:** editorial whitespace costs density; the run console needs the
  tightest typographic tuning to keep long transcripts scannable.

## 4. Shared product truth (all three)

Same screens, same data, same interactions; only the world changes.

- Run `run_7f3a` — restricted, `anthropic/claude-sonnet-4`, 04:12 elapsed,
  $0.38, running; Q06 gate on `src/billing/webhook.py` (+24 −3, sha 9d07aa).
- Run `run_2b9c` — elevated, `anthropic/claude-opus-4`, 06:48, $0.91, HOLD:
  "Drop 12 legacy snapshot files", `src/session/store.py` (+42 −11, sha 4b21c9).
- `run_6d1e` struck, `run_04aa` full-access queued #1, `run_9c31` dropped
  (stale elevated image).
- Spend $3.84 of $12.00; audit entries 1198–1204, chain 1,204, unbroken;
  images: restricted current, elevated stale, full access current;
  daemon `127.0.0.1:8765`, workspace `~/work/orbit-api`, project `orbit-api`.
- Every screen is clickable: nav, table rows, inspector tabs, queue, sessions,
  audit, settings, both approval sheets, mobile nav, focus rings, Escape,
  Cmd/Ctrl+K, disabled/empty states, reduced motion.

## 5. Evidence

- **Screenshots:** `design/prototypes/shots/` — overview, run console, audit,
  settings, both approval sheets, 390px mobile for each world, plus the
  comparison page. Captured with Playwright + Chromium at 1440×1000 and 390×844.
- **Detector:** `impeccable detect --json --no-advisory` returns 54 advisories,
  0 errors: 52 `cramped-padding` on intentionally full-bleed dense surfaces
  (diff rows, matrix rows, hold bands) and 2 `cream-palette` for the two paper
  worlds. Accepted as deliberate; font floor, low contrast, wide tracking,
  heading order, and pulsing-dot findings are cleared.
- **Verification:** each document parses to `</html>`, contains its script,
  and was rendered for every captured screen; no console exceptions observed.
- **Scope honesty:** static prototypes, synthetic data, no backend calls, no
  shipped assets yet.

## 6. Decision

No direction is picked here. The comparison page states the trade-off plainly:

| | Cuebook | Wayfinding | Lexicon |
|---|---|---|---|
| Primary read | atmosphere + cue discipline | state at a glance | trust + record |
| Signature | cue rail and held cue | full-width tier band | entry with annotations |
| Best for | identity-led solo operator | glanceable multi-screen work | evidence-first long sessions |
| Cost | density can feel theatrical | yellow dominates | whitespace costs density |

**After the choice:** write `DESIGN.md` + `.impeccable/design.json` with the
winning tokens, then rebuild the chosen direction inside `smolcode/web` on the
existing React 19 / Vite / TypeScript app, reusing the current component
inventory and state model. The other two prototypes remain in `design/` as
reference; they are not shipped.
