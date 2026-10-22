---
title: "Controlled Tests"
type: evidence
status: current
updated: 2026-10-22
tags:
  - openttd
  - evidence
  - controlled
---

# Controlled Tests

**CONTROLLED** = offline tests, synthetic fixtures, or controlled validation. It never
proves native runtime behavior — that boundary is the project's cardinal discipline.

## Why controlled work exists

Preparation, contracts, planners, and diagnostics are developed and validated offline so
that the rare, one-shot, operator-authorized native attempts arrive with sealed frozen
inputs and preflighted gates. A controlled pass is a *readiness* signal, not a *native*
claim ([[07-Reference/Status Definitions]]).

## Major controlled conclusions (scope-bound)

| Item | What it is | Where |
|---|---|---|
| 512-tile random capture correction | Controlled/offline; no new native run: 512 fully observed tiles per rectangle; fixed demo stays 256; road path 2..47 unchanged; profile `random-rectangle-512-v1` (45 s, ≤546 reads/relationship) | E5 |
| Observation pipeline readiness | Offline verification + independent review; suites 90+297+216 (11 skipped); no native observation collected | E7 |
| Bounded reachability oracle | `corridor_reachability` over eligible vacant stops; frozen corridor regression intact; Seed 17 coal disconnect = complete-search proof | E9 |
| Bounded terrain-modification planning | Typed budgets (32 corner ops, ±1 step, 8 clears, 128 region, 47 interior road), planning-only proposals; `NO_CONNECTED_LEVELED_CORRIDOR` (176 expansions) for retained Seed 17 | E10 |
| Tile classification + feasibility (additive) | Schema-2 wire; five segment classes; `assess_world_feasibility`; readiness registry; 13+24 focused tests | E11 |
| V2 capture preparation | Receipt/exchange/sweep; 90-page plan; refuse-on-missing-seam staging; 16+7+9(+1) tests | E12 |
| V2 execution path | Staging/dispatch/runner/correspondence policy; 10+10+10+8 tests, offline | E13 |
| V2 diagnosis/repair | 35 focused tests incl. consumed-log replay; AI staging sealed | E15 |
| Offline V1/V2 semantic reconciliation | 450-tile replay: 77 definitional / 6 temporal / 0 contradictions / 0 unresolved → `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`; P08 binding not allowed; 15 focused tests | [[05-Planning/Blockers]] (uncommitted record) |
| Controlled P08→P05 chain | Observation admission, supplemental facts, prepared-source correspondence, bounded generation, P05 optimization, execution-plan validation — controlled source bytes are not an executable save | CONTEXT §20 |
| Synthetic flat fixture | 31-road-tile route, 1 selected service, £1,830 estimated construction/purchase | E5 (never a Seed 17 native result) |
| P07 analytics extension | Offline implementation verified on retained Attempt 19/fixed-demo evidence; advisory-only; FAILED terminals stay visible | 2026-10-18 checkpoint; README §P07 |
| Capacity experiment prep | A/B/C controlled plans (`minimum_vehicles_by_demand`); queue stats sampled | `docs/capacity-experiment.md` |

## Suite counts are dated, not additive

Recorded counts belong to their own records and dates ("prior extension suite counts and
VM results are historical, not rerun claims" — REPRODUCE). Do not sum, do not re-cite as
fresh runs, and never present a controlled suite result as native verification.

## Controlled tooling gaps (honest)

- Typecheck repeatedly recorded unavailable offline (mypy not installed; `ty` configured,
  not installed) — recorded in E9/E10/E11/E15 and the AI_HANDOFF validation notes.
- Full-tree test/lint/type health remains UNKNOWN beyond recorded checks.
- Baseline authority-pin failures are known and preserved ([[03-Engineering/Testing Strategy]]).

## Controlled → native promotion rule

Only a consumed one-shot attempt with retained receipts can advance a status. The
promotion path is: preparation record → reviewed candidate (`PENDING_AUTHORIZATION`) →
preflight → operator authorization → one launch → readback/receipt → close-out record
(reference: E12→E13→E14/E15→E16 and E18→E19). All current prepared items:
[[02-Milestones/Pending Milestones]].
