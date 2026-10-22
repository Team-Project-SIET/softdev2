---
title: "Blockers"
type: planning
status: current
updated: 2026-10-22
tags:
  - openttd
  - planning
  - blockers
---

# Blockers

Live blockers with their sources. A blocker stays listed until a dated record resolves it
([[07-Reference/Status Definitions]]; preserve contradictions until properly investigated).

## 1. Authorization is always required before native work

**Type: process, standing.** The project's one-shot model means the *only* way anything
native happens is a fresh, explicit operator authorization per attempt (E17/E19 launch
records: "the record-writing session did NOT initiate the launch" — authorizations were
consumed by separate operator actions). That now includes D4: the one-shot
authorization for `D4-CORRIDOR-1` was consumed 2026-10-22 (E21 — the attempt halted
`PHASE_HALTED_PREFIX_PRESERVED`, Milestone D4 INCOMPLETE; the frozen closure must
never be edited or reused). Nothing further in the D-chain is staged or authorized,
and D4 restaging waits on the §8 decision.

## 2. Random World infeasibility chain (Seed 17)

**Type: technical — evidence-driven, immutable so far.**

- 5 of 6 compatible relationships exceed capture budgets even under `random-rectangle-512-v1`
  (Wood 1122, Livestock/Grain 17947, Oil 8436, Iron ore 2457 tiles vs 512-tile cap) — only
  coal (450 tiles) was capturable; Wood is also the nearest at 185 Manhattan tiles (E4/E5,
  `docs/random-world-distance-support.md`).
- The coal pair itself is **completely disconnected** in the supported corridor graph
  (17 water, 50 trees, 13 rough, 12 industry, 19 steep non-buildable tiles) —
  `NO_BOUNDED_CORRIDOR` is a complete-search proof (E9).
- With classified levelling admitted, **no connected corridor exists even in principle**
  via supported modifications: all 23 height-step adjacencies are fenced by
  forbidden-class tiles; 19 of 450 tiles' house/station class cannot be recovered offline
  → `NO_CONNECTED_LEVELED_CORRIDOR` (E10).
- Fresh V2 census disagrees with the retained projection on 83 tiles
  (`PROJECTED_FLAGS_DIFFER`) → fusion stays **REJECTED** (E16); the 19 historically
  UNKNOWN tiles stay UNKNOWN; P08 diagnosis stays `INCOMPLETE_TILE_CLASSIFICATION`
  (339 / 63 / 19 / 29).
- Uncommitted 2026-10-18 reconciliation found 0 contradictions but 6 **temporal**
  second-instant tiles (43951, 47286, 47288, 48042, 48309, 51378 — tree growth/death
  mechanics vs retained V1 window economy days 712285–712291; fresh census at 712224–712226)
  → `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`, P08 binding not allowed. **Recorded
  minimum additional evidence:** a bounded, separately-authorized same-instant native
  re-observation of exactly those six tiles, and/or an explicit operator policy decision
  declaring the save-instant census authoritative; sealed in a NEW reviewed candidate.
  Status caveat: this reconciliation is uncommitted working-tree work, not an indexed
  evidence record (no E-ID). *(Contradiction preserved, not resolved.)*
- **Consequence:** any new random native run is currently expected to hit
  `NO_FEASIBLE_SERVICES` again unless those facts change; TASKS explicitly says "Do not
  promise the coal pair will yield a feasible road".

## 3. CONTEXT.md authority-pin conflict

**Type: integrity/process (preserved contradiction).** See
[[04-Evidence/Evidence Preservation]] for the full mechanism: 2026-10-08 byte pins
(sha256 `b94b966…`) vs live file; two protected-authority tests + one architecture test
fail at baseline; the prepend-only 2026-10-18 addendum is deliberately uncommitted.
Resolution requires an explicit pin-repair or re-capture decision.

## 4. Fourth-vehicle / matched A/B native readiness

**Type: missing artifact.** No retained canonical pre-intervention save contains the
original constructed fleet; no verified reload preserves its GameScript bindings and
native state. Historical REAL_PASS evidence does not fill this gap
([[99-Source-Documents/TASKS]] item 6; `docs/capacity-experiment.md`).

## 5. Missing historical inputs

**Type: documentation/artifact gap, permanent until artifacts appear.** The original
terrain audit and canonical inputs remain missing; retained-evidence absence on a machine
→ UNKNOWN (`docs/specs/openttd-offline-evidence-freeze.md`).

## 6. Tooling unavailability (recorded, honest)

**Type: environment.** Typecheck (`mypy`/`ty`/`pyright`) repeatedly recorded unavailable
offline; `ty` is configured in the project but not installed. Full-tree test/lint health
UNKNOWN beyond recorded checks. Fixing this is straightforward but must be done honestly:
install, re-run, and record new results as fresh checks — do not reuse historical "PASS"
claims afterwards ([[03-Engineering/Testing Strategy]]).

## 7. Remote documentation completeness unverified

**Type: knowledge risk.** The project-local OpenTTD docs repository contents/version
availability is unverified (CONTEXT §4) — OpenTTD-specific behavior must be verified
against official 15.3 docs and/or 15.3 sources when project-local docs are incomplete
([[01-Architecture/OpenTTD Integration]]).

## 8. D4 restaging decision (op-01 price ceiling vs scope)

**Type: decision, staging-time (no live override).** The consumed attempt's 17-tile run
`op-01` was refused at admission: native quote **£2,549** vs the authorized **£2,000**
per-operation ceiling (E21). Before any fresh candidate: either raise the per-operation
ceiling (re-signed authorization payload, same fail-closed admission) or rescope/split
the 17-tile run into bounded pieces inside the current ceiling; every unexecuted op then
gets a fresh native quote at admission. A fresh reviewed candidate plus ONE fresh
explicit operator authorization are required; none exist. Source:
`docs/handoff/2026-10-22/d4-corridor-native-candidate-1-outcome.md` §9 and
[[99-Source-Documents/EVIDENCE_INDEX]] E21.

## Consequence summary for the next agent

The engineered path forward (D4) is decision-gated (§8), then requires a fresh
re-staged candidate and fresh explicit authorization (E21). The Random World path is
evidence-gated: it needs new authorized native facts (same-instant tiles) or an operator
decision before any feasibility verdict changes. Do not soften either gate.
