---
title: "Planning and Execution Boundary"
type: architecture
status: current
updated: 2026-10-22
tags:
  - openttd
  - architecture
  - planning
---

# Planning and Execution Boundary

**Canonical spec:** `docs/specs/planning-executor-boundary.md` in the repository
(P01 design specification + P05/P06/P07/P08 implementation sections). Key handoff
statement: [[99-Source-Documents/AI_HANDOFF]]. Read the spec before changing planning or
executor code — this note only indexes its binding rules.

## The one-line rule

> Python owns optimization, identity, validation, deadlines and evidence binding.
> GameScript executes synchronous commands under `GSCompanyMode`, returns bounded
> correlated messages and exposes readback. Keep route optimization in Python.

## What P05 is and is not

- `optimize_candidate_network(PlanningScenario)` returns an immutable `OptimizationResult`
  with a P02-validated `ExecutionPlan` and separate `EstimatedPlanMetrics`.
- P05 **selects supplied candidates**; it does **not** perform YAPF, terrain search, or
  arbitrary-world route planning. OpenTTD's vehicle pathfinder navigates built roads.
- One route per demand: pickup station → delivery station → final compatible depot → one
  supplied corridor directly connecting them. No multi-edge paths, no `SERVICE` waypoints.
- OR-Tools CP-SAT picks exactly one alternative per demand; objective is construction +
  vehicle purchase capex; proven optima only; deterministic canonical output.
- Planned subsystem internals: rail wagon-composition search bounded (≤ 128 compatible
  wagon types, 100,000 states per alternative) and unsupported-scenario failure instead
  of approximate plans (spec §P05).

## What P08 is and is not

- P08 adapts admitted observations into **bounded road candidates**: flat-land routing,
  2..47 road tiles per candidate path, explicit budgets; bounded terrain-aware
  reachability oracle before selection; bounded terrain-modification *planning* contracts
  (E9, E10).
- P08 does not clear, mine, bridge, or improvise: unsupported geometry is reported via
  typed feasibility diagnoses (`NO_CONNECTED_CORRIDOR`, `TERRAIN_MODIFICATION_REQUIRED`,
  `UNSUPPORTED_CONSTRUCTION`, `INCOMPLETE_TILE_CLASSIFICATION`, `SEARCH_BUDGET_EXCEEDED`,
  `CONNECTED_WITHOUT_MODIFICATION`).
- Neither P05 nor P08 is an arbitrary-world planner or an OpenTTD-YAPF replacement.

## Contract discipline (P01/P02)

- Immutable strict typed records; canonical UTF-8 JSON, sorted keys, fixed decimal
  strings for money (`GBP`, exact integer units at `10**max(2,fractional_digits)`).
- `plan_hash` = SHA-256 over canonical envelope excluding the hash; equal IDs with
  different hashes are conflicts; generation timestamps stay out of the hash.
- Strict cross-reference validation **before** any OpenTTD launch: unknown versions,
  unknown nodes/modes, budget inconsistencies, unsupported construction → typed
  rejection (`UNSUPPORTED_PLAN_VERSION`, `UNBUILDABLE_INFRASTRUCTURE`,
  `PLAN_TRANSPORT_FAILURE`, …). Never launch on known-invalid input.
- Estimated vs realized metrics: separately typed artifacts; estimated profit is never
  stored as realized profit; current-period parser values are not full-horizon economics.

## Executor discipline (P06-style, freight lineage)

- Stages in declared dependency order; commands irreversible at this boundary — a
  mutation attempt converts failure to `PARTIAL_EXECUTION` **even if the command reports
  failure**; no rollback or cleanup claims; partial execution never scores as valid.
- Exactly-once terminal receipt (`P06_EXECUTION_V1` lineage) bound to plan hash, world
  fingerprint, runtime hash; independent evidence validator rejects forged/duplicate
  identity; parsing bounded (64 KiB/record, 1 MiB/stream).
- The freight compiler retains industry, cargo, engine and plan identities and never
  drops vehicles to fit the demo; native admission re-validates selection before
  construction/vehicle/order stages; no second OD search substitutes a service.

## Source trust / identity through compilation and replay

Prepared-save + world/scenario/plan identities stay mandatory through compilation and
replay (handoff). Controlled source bytes are **not an executable save**; accepted bytes
and schemas do not establish runtime correspondence. Execution supports one vehicle,
planned batch = native full-load capacity, 2..47 flat corridor tiles, two stops, one
depot; partial loads and larger fleets are rejected ([[99-Source-Documents/README]]).

## P07 meaning in this boundary

P07 compares plan with retained observations: native receipts replayed independently;
OBSERVED native measurements vs DERIVED aggregates vs CONTROLLED inputs kept separate;
failed planning retains JSON/HTML diagnostics, not delivery receipts; comparisons keep
distinct seed/config identities. Evidence-aware analytics extension (2026-10-18) adds
advisory-only recommendations — they never plan, purchase or execute.
