# Frontend directions — round two decision brief

**Status:** awaiting the operator's choice
**Date:** 2026-10-25
**Scope:** visual direction and interaction prototype for the smolcode web app
**Files:** `design/prototypes/` (open `index.html` by double-click)

This document records the design process, the three worlds now on the table, and
the evidence gathered. It is development-only: it must never be copied into the
browser-delivered app or any user-facing artifact. `DESIGN.md` and
`.impeccable/design.json` are written only after a direction is chosen.

---

## 1. What changed after round one

Round one produced **Cuebook**, **Wayfinding**, and **Lexicon**. The operator's
verdict was specific:

- **Cuebook is the best direction so far.** It is kept as the incumbent and was
  not rebuilt, recoloured, or simplified in this round.
- **Wayfinding and Lexicon never fit the project.** They are retired from the
  comparison page. Their prototypes remain on disk as an archive, not as
  candidates, and nothing from either world is reused below.

Round two therefore re-rolled the direction and built **two new worlds from
scratch**: Custody (the pick card) and Bonded (the assigned direction). The
comparison page now shows Cuebook, Custody, and Bonded only.

## 2. Product truth that does not move

smolcode is a loopback-only, host-run, Docker-sandboxed multi-agent coding
assistant. The frontend has to make five truths legible without turning them
into decoration:

- a visible **tier ladder** (restricted / elevated / full access) that can be
  read at a glance and changed deliberately;
- a **human release gate** for destructive steps, bound to one diff and one run;
- an **append-only hash-chained audit** that answers who did what, with which
  image, at what cost;
- an **inspector** that keeps policy, workspace, file, and diff evidence in view
  while the run is still live;
- a **composer** that behaves like a console, not a chat box: project, tier,
  provider, model, uploads, task, auto-approve, caps.

Posture per `PRODUCT.md`: developer-operator on their own machine; precise,
calm, evidence-first; lowercase `smolcode`; keyboard-first; WCAG AA; reduced
motion respected. All prototype data is synthetic and labelled as such.

## 3. Method

The work followed the impeccable skill in Operate mode:

1. `impeccable context` had already established `PRODUCT.md` in round one, so
   the second round started from the documented product truth.
2. `impeccable concept-seed --scope direction --mode operate` re-rolled the
   direction with key `1242e029365962828883a59dc0f9d47a` and seed reference
   `seed:00c825fea9917299`, **assigned index 6** of the grounded list.
3. The roll's challengers were a boarding-pass gate board, a character-goods
   catalog, a botanical folio, a warm consumer app, a Crouwel grid specimen,
   and a darkroom exposure record. **The assigned role was the bonded customs
   yard; the pick card was the evidence-intake bench.** Those two were built.
   The remaining challengers were dropped: each either borrowed a visual
   costume or pulled the product toward retail/editorial territory.
4. Direction contract held throughout: a world may lend **type, palette,
   density, and one signature move** — never the destination set, action
   semantics, or control behaviour. Navigation is themed but resolves to the
   same screens and actions; all controls stay standard; no invented glyphs, no
   decorative chrome, no image comps. The build was code-led.
5. Craft floor held across all three documents: no kickers over headings, no
   gradient text, no glass, no hard offset shadows, one depth system, 12–16px
   card radii, body contrast ≥ 4.5:1, measure 65–75ch, 12px minimum UI text, one
   authored motion moment, all states, 390px responsive, reduced motion.

The assigned direction's role metadata is development-only. It does not appear
in any user-facing label, navigation item, or product copy.

## 4. The three worlds

### I — Cuebook (incumbent · round one)

- **Thesis:** a run is a performance; every step is a cue, and the gate is a
  held cue waiting for GO.
- **World:** warm near-black desk, ivory ink, cue red, standby amber; typewriter
  labels against a grotesque UI; hairlines rather than boxes.
- **Signature move:** the cue rail — numbered rows (Q01…), state words
  STANDING BY / GO / HOLD, one held diff rendered as a cue sheet.
- **Navigation:** left rail (Call sheet, Cue sheet, Queue, Sessions, Audit trail,
  Settings), tonight's call table, three-pane console.
- **Built:** overview, run console with live cue stream and evidence rail, audit
  with chain/policy/workspace, settings (“House rules”), approval sheets for
  `run_2b9c` and `run_7f3a`, mobile, keyboard focus, Escape, Cmd/Ctrl+K.
- **Pick it if:** identity and atmosphere matter as much as throughput; you
  want the release moment to feel like a deliberate cue, not a dialog.
- **Watch:** the dark, dense rail is the most designed of the three; it needs
  discipline to keep long sessions calm rather than theatrical.

### II — Custody (new · pick card · evidence intake)

- **Thesis:** every agent action is taken into custody. A diff is sealed to one
  case; a person signs it out; the register is the product, not a log viewer
  bolted on afterwards.
- **World:** pale bench grey, sheet white, panel green-grey, steel rules,
  oxblood seal, verify teal. Instrument Sans for the bench voice, IBM Plex Mono
  for seals, chain values, and evidence tags; numbered clauses and thin rules.
- **Signature move:** the **tamper-evident seal** — one case, one diff, one
  seal ID (9D07AA / 4B21C9), with a release sheet that breaks the seal only
  after an explicit acknowledgement. A CSS barcode anchors the seal register.
- **Navigation:** Intake / Case / Queue / Register / Protocol. The intake table
  is the night's bench; the dark release-pending card interrupts it; the case
  file carries a custody rail; the register is a dark header over a chained
  ledger.
- **Built:** intake with stat strip, table, gate card, seal register; case file
  with numbered sequence, entries, diff/terminal blocks, custody rail and hold
  block; queue with capacity and rule cards; register with chain verification
  and barcode; protocol with policy matrix, providers, caps, and store; both
  release sheets (`#release`, `#release7`) with consent gating; toast;
  mobile, keyboard, Escape, Cmd+K, reduced motion.
- **Pick it if:** you want approval and audit to feel like the product's central
  promise rather than a compliance screen; clinical calm suits your long
  sessions.
- **Watch:** the density is real — more mono, more rules, more small evidence
  than a typical dashboard. It must stay scannable, not become paperwork.

### III — Bonded (new · assigned · customs yard)

- **Thesis:** every run is cargo. It enters through a gate, sits under seal
  while it works, and leaves only on a signed gate pass. The queue has a
  physical place.
- **World:** tarpaulin cream, sheet cream, navy gate, container orange, customs
  green, stencil amber. Barlow Condensed for plates and manifest headers,
  Barlow for prose, JetBrains Mono for seals, slots, gates, and costs.
- **Signature move:** the **container plate and gate pass** — a stencilled
  7F3A/2B9C plate marks the cargo, and the orange-banded release sheet is a
  gate pass at gate 01. The yard ticker keeps gate state visible across views.
- **Navigation:** Yard / Container / Queue / Manifest / Store. The yard overview
  is a manifest table with a dark release-pending gate card; the container view
  has a dark manifest index edge; the manifest view is a custody ledger; the
  store is providers, gates, image tiers, and paths.
- **Built:** yard overview with tally, table, gate card, seal register; container
  file with plate, actions, meta strip, index, entries, diff/terminal, hold band,
  sticky composer; queue with slots, capacity, and rule; manifest with verified
  stamp and ledger; store with provider table, levers, caps, bonded store, paths;
  both gate passes with cargo/signature columns, consent gating, and toast;
  mobile, keyboard, Escape, Cmd+K, reduced motion.
- **Pick it if:** you want queue and gate state to read at a distance and the
  interface to feel operational rather than literary; the visible tier ladder
  maps naturally to slots and gates.
- **Watch:** the header and condensed display type are the heaviest of the
  three. The yard metaphor has to stay operational; never let it become costume.

## 5. Shared product truth (all three)

Same screens, same data, same interactions; only the world changes.

- `run_7f3a` — restricted, `anthropic/claude-sonnet-4`, 04:12 elapsed, $0.38,
  running; gate on `src/billing/webhook.py` (+24 −3, sha 9d07aa).
- `run_2b9c` — elevated, `anthropic/claude-opus-4`, 06:48, $0.91, hold:
  “Drop 12 legacy snapshot files”, `src/session/store.py` (+42 −11, sha 4b21c9).
- `run_6d1e` done/cleared, `run_04aa` full-access queued #1, `run_9c31`
  returned/refused after the stale elevated image.
- Spend $3.84 of $12.00; audit entries 1198–1204, chain 1,204, unbroken;
  images: restricted current, elevated stale, full access current;
  daemon `127.0.0.1:8765`, workspace `~/work/orbit-api`, project `orbit-api`.
- Every screen is clickable: nav, table rows, inspector tabs, queue, sessions,
  register/manifest, protocol/store, both release sheets, mobile nav, focus
  rings, Escape, Cmd/Ctrl+K, disabled and empty states, reduced motion.

## 6. Evidence

- **Screenshots:** `design/prototypes/shots/` — overview, live run/case/container,
  register/manifest, protocol/store, queue, both release sheets, 390px mobile for
  each world, plus the comparison page. Captured with Playwright + Chromium at
  1440×1000 and 390×844.
- **Detector:** `impeccable detect --json --no-advisory` returns no errors:
  - Custody: 23 advisories — 22 `cramped-padding` on intentionally dense diff
    and register rows, plus 1 `overused-font` for Instrument Sans.
  - Bonded: 18 advisories — all `cramped-padding` on density-driven manifest
    and diff rows.
  - Comparison page: 3 advisories — one `cramped-padding` on the hero side rule,
    `overused-font` for Instrument Sans, and `cream-palette` for the review
    shell itself.
  All remaining findings are accepted as deliberate: the dense rows are the
  product's diff and ledger surfaces, and the review shell is intentionally a
  neutral paper stage. Low contrast, heading order, dark glow, gradient text,
  glass, and tracking findings are cleared.
- **Verification:** each document parses to `</html>`, contains its script, was
  rendered for every captured screen and state, and exposes the hash deep links
  used above. No console exceptions observed; no backend calls.
- **Scope honesty:** static prototypes, synthetic data, no shipped assets yet.

## 7. Decision

No direction is picked here. The comparison page states the trade-off plainly:

| | Cuebook | Custody | Bonded |
|---|---|---|---|
| Primary read | atmosphere + cue discipline | custody + evidence | queue + gate state |
| Signature | cue rail and held cue | tamper-evident seal and release sheet | container plate and gate pass |
| Best for | identity-led solo operator | audit-and-approval-first operator | operational, glanceable work |
| Cost | density can feel theatrical | clinical density can feel like paperwork | heaviest header and display type |

**My read:** Cuebook remains the strongest single identity and still gives the
release decision the cleanest emotional weight. Custody is the most honest to
this product: it makes the seal, the release, and the register into the
interface rather than decoration. Bonded is the most legible at a distance and
the only one that gives the queue a physical place. If the choice is close,
choose on the question you want the product to answer fastest at 1am: “what is
this run doing?” (Cuebook), “who has this diff?” (Custody), or “what is at the
gate?” (Bonded).

## 8. After the choice

Write `DESIGN.md` + `.impeccable/design.json` with the winning tokens, then
rebuild the chosen direction inside `smolcode/web` on the existing React 19 /
Vite / TypeScript app, reusing the current component inventory and state model:
the tier ladder, release sheets, register, inspector, composer, focus order,
reduced motion, and 390px layout all survive the translation. The other two
prototypes remain in `design/` as reference; they are not merged or shipped.
Wayfinding and Lexicon remain archived on disk but are no longer candidates.
