---
title: "Task Board"
type: planning
status: current
updated: 2026-10-22
tags:
  - openttd
  - planning
  - tasks
---

# Task Board

Derived from [[99-Source-Documents/TASKS]] (2026-10-17 list + 2026-10-18/22 updates).
This board **grants no runtime authority**; statuses reflect what the source documents
record, nothing more. Priorities below are the source documents' own ordering
("current product priority is the stable demo plus bounded Random World") — no invented
deadlines.

## Completed (per source records — offline work)

- [x] 1. Offline transfer verification — branch/HEAD, dirty paths, source hashes vs `docs/handoff/2026-10-17/`; ignored artifacts exist; hashes verified; **Done:** reviewed source/evidence inventory, no secret transfer, no historical edits. (2026-10-17 era; E6)
- [x] 2. Offline fresh random readiness — 512-tile profile, legacy 256 compatibility, staged bridge, budgets, qualified-month window, 47-tile filter, P05 timeout, diagnostics/replay/cleanup reviewed; focused tests run; frozen-input identity + independent preflight with staleness/runtime blockers explicit; zero launches. (E5, E7)
- [x] 4. Offline P07 continuation after accepted delivery — replay to fresh sibling output; verified totals/charts/history/attributions; **Done:** reproducible reports, native vs derived distinguished, no invented OPEX/profit/ROI.
- [x] 5. Later product work — offline bounded extensions so far: terrain-aware reachability oracle (E9); bounded terrain-modification planning (E10); native classification + generalized feasibility + three-tier diagnosis (E11); V2 preparation (E12); execution path + capture runner (E13); native V2 capture consumed → fusion REJECTED (E14/E15/E16).
- [x] 6. Separate engineering backlog items staged offline — fourth-vehicle controlled preparation + telemetry groundwork; canonical inputs still missing (blocked flag below). (README §capacity; `docs/capacity-experiment.md`)
- [x] 7. Tile Classification V2 executable path — execution blockers implemented offline and validated; authorization consumed 2026-10-18 (first launch FAILED → diagnosed/repaired offline → **capture completed natively**, fusion REJECTED). (E14, E15, E16)
- [x] 8. Milestone D3 complete; D4 preparation — D3 closed 2026-10-22 (E19); D4 candidate staged same day, `PRELAUNCH PASS` + `PREFLIGHT PASS` (E20).

## Consumed authorization (closed with immutable outcome)

- [x] 3. Separate authorization: one new Seed 17 native smoke — **authorization consumed 2026-10-17** under its reviewed frozen identity; outcome `NO_BOUNDED_CORRIDOR` → `NO_FEASIBLE_SERVICES`; P05 NOT_RUN; diagnostics retained (E8). Task is closed; the *failed outcome* is retained, not "undone". Also completed offline follow-ups: readiness record (E8-linked), bounded routing record (E9), terrain-modification record (E10), classification record (E11), and preparation records (E12, E13).
- [x] **D4 native execution — one shot on candidate `D4-CORRIDOR-1`** — authorization
  consumed 2026-10-22; the ceremony halted `PHASE_HALTED_PREFIX_PRESERVED` at `op-01`:
  `op-00` verified (£785; funds £496,543 → £495,758), `op-01` refused at admission
  (£2,549 > £2,000 ceiling), `op-02`–`op-05` and the route read never executed;
  `verified: false`, Milestone D4 INCOMPLETE (E21). Closed with the immutable halted
  outcome — never retried, never relabeled.

## Open / pending

- [ ] **D4 restage decision** — for the refused `op-01` (native quote £2,549 > £2,000
  per-op ceiling): raise the ceiling or rescope/split the 17-tile run as a staging-time
  decision; then prepare a FRESH reviewed candidate; a fresh explicit operator
  authorization is still required before any launch. The consumed `D4-CORRIDOR-1` is
  never retried or reused (E21).
  → [[05-Planning/Blockers]] §8, [[05-Planning/Next Actions]].
- [ ] **Random World facts** — recorded follow-up options: same-instant re-observation of
  tiles [43951, 47286, 47288, 48042, 48309, 51378], and/or operator policy decision on the
  save-instant census; both under a new reviewed candidate + fresh authorization
  ([[05-Planning/Blockers]]). A new random native run additionally needs fresh frozen
  inputs; never retry consumed identities.
- [ ] **Protected-authority pin resolution** — explicit decision needed: pin-repair or
  re-capture for repo-root CONTEXT.md vs 2026-10-08 authority manifests
  ([[04-Evidence/Evidence Preservation]]).
- [ ] **Third-party/application backlog (separately scoped, later)** — obstructed terrain,
  long corridors, >32 industries, larger maps; fourth-vehicle matched A/B native work;
  continuous dispatch; five-year experiment expansion. All gated behind reviewed contracts
  + authorizations; fourth-vehicle native readiness currently BLOCKED (no canonical
  pre-intervention save).

## Board hygiene rules

- Never check a box without a source-recorded completion (E-ID or dated record).
- Never mark a task complete because tests pass, code exists, or a candidate is prepared.
- `DONE` offline items must not imply native authority was granted or consumed. In case
  of ambiguity, write the ambiguity and link the source ([[05-Planning/Next Actions]]).
