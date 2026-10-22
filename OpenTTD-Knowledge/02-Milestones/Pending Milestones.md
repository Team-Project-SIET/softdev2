---
title: "Pending Milestones"
type: milestone
status: current
updated: 2026-10-22
tags:
  - openttd
  - milestone
  - planning
---

# Pending Milestones

Nothing here is authorized. Pending ≠ prepared ≠ verified:
[[07-Reference/Status Definitions]]. Confirm live state per
[[05-Planning/Task Board]] before acting.

## D4 — Native road & station construction → ATTEMPT CONSUMED, `INCOMPLETE` (E21, 2026-10-22)

The staged candidate `D4-CORRIDOR-1` was consumed by its ONE operator-authorized launch
2026-10-22; the ceremony ended `PHASE_HALTED_PREFIX_PRESERVED` with `verified: false`:

- Verified prefix `op-00` only: 5-tile road run 45747→45743 built at £785 (within the
  £2,000 per-op ceiling), independently re-read, `NATIVE_STATE_CHANGED`; funds
  £496,543 → £495,758.
- `op-01` (the 17-tile run 45999→50095) was refused at admission: native quote £2,549
  exceeded the authorized £2,000 per-operation ceiling (`inspect-01 COST_LIMIT`); no
  native command was issued for it.
- `op-02`–`op-05` (corner, both truck stops, depot) and the route read were never
  executed; no `receipt.json` and no `after.sav` exist; `after-diagnostic.sav` is not
  a receipt-bound save. Milestone D4 remains INCOMPLETE. The E20 staging facts (schedule,
  budgets, `PRELAUNCH PASS`/`PREFLIGHT PASS`, seal `0b000d68…1a18f`) stay historical.
- The consumed candidate's frozen closure must never be edited or reused; a future
  attempt requires a fresh staged candidate and fresh explicit operator authorization,
  gated on the staging-time decision in [[05-Planning/Blockers]] §8. None staged or
  authorized. Full record: `docs/handoff/2026-10-22/d4-corridor-native-candidate-1-outcome.md`.

## D5+ — Vehicle purchase, orders, delivery on the corridor — NOT DESIGNED

After D4, separately scoped milestones would put a vehicle on the built corridor. No
candidate exists; nothing here is prepared. Road/station admission does not imply
purchase/run/verify capability.

## Random World native service execution — BLOCKED (infeasibility + open facts)

- Seed 17: only the coal pair was capturable (450 tiles); the other five relationships
  exceeded capture budgets even with `random-rectangle-512-v1` (Wood 1122, Livestock/Grain
  17947, Oil 8436, Iron ore 2457 tile rectangles); the coal pair proved completely
  disconnected in the supported corridor graph → `NO_BOUNDED_CORRIDOR` (E8, E9),
  structurally unrecoverable even with classified levelling
  (`NO_CONNECTED_LEVELED_CORRIDOR`, E10).
- Classification: 19 UNKNOWN tiles + 83 `PROJECTED_FLAGS_DIFFER` disagreements keep
  `INCOMPLETE_TILE_CLASSIFICATION` (E16). Uncommitted 2026-10-18 offline reconciliation
  returned `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED` (77 definitional, 6 temporal
  tiles 43951/47286/47288/48042/48309/51378, 0 contradictions) — the recorded minimum
  additional evidence is a bounded same-instant re-observation of exactly those six tiles
  and/or an explicit operator policy decision sealed in a new reviewed candidate
  ([[05-Planning/Blockers]]).
- A new native random run requires fresh reviewed frozen inputs + separate authorization;
  never retry a consumed identity (E8's `playable-demo-698799a2d…` is consumed).

## Fourth-vehicle intervention / matched A/B — PREPARED, native BLOCKED

- Controlled A/B/C preparation (Service 2 extra vehicle hypothesis; queue 651.42 vs
  557.10 sampled mean) exists via `analyze-continuous-freight --prepare-capacity-experiment`.
- Native readiness **BLOCKED**: no retained canonical pre-intervention save contains the
  original constructed fleet; no verified reload preserves GameScript bindings + native
  state. A future loader must verify a paused purchase boundary and common dispatch state
  (`docs/capacity-experiment.md`). Historical Attempt 19 is a contextual baseline, not a
  matched arm ([[99-Source-Documents/AI_HANDOFF]] shared language).

## Two-rollover qualification Attempt 3 — NOT STARTED

Attempt 3 readiness derivation exists (`docs/two-rollover-qualification-attempt3-readiness.md`)
and requires fresh authorization. Attempt 2 remains FAILED overall (post-run offline
verification failed) — its native SUCCESS does not carry to an overall pass
([[04-Evidence/Failed Attempts]]).

## Later product work — SEPARATELY SCOPED (TASKS item 5)

Support for obstructed terrain, long corridors, > 32 industries or larger maps only with
explicit contracts and bounded observation/search/execution. Current implementation does
not support arbitrary slopes, clearing, bridges/tunnels or arbitrary-world road feasibility.

## Historical/unknown inputs — MISSING (do not reconstruct)

Missing original terrain audit and canonical inputs remain missing
(`docs/specs/openttd-offline-evidence-freeze.md`); absent retained artifacts are UNKNOWN,
not regeneration prompts ([[04-Evidence/Evidence Preservation]]).
