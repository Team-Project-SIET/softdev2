---
title: "Pending Milestones"
type: milestone
status: current
updated: 2026-10-25
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

**Restage decision (2026-10-22, offline, E22/ADR-011):** Option C was chosen and
implemented offline — the fresh schedule stages 8 ops (run A; run-B segments
45999→48047 and 48303→50095 with the separate interior join 48047↔48303 after
both; unchanged corner join, stops and depot) inside the **unchanged £2,000
per-operation ceiling**, with 25 planned exchanges (budget 31) and a
schedule-version selector keeping the consumed attempt's replay re-derivable.
This is controlled offline work: **no native quote, command, receipt or
authorization exists for the new schedule, so D4 remains INCOMPLETE (native)** —
the historical £2,549/£785 quotes are controlled references only, and the
worst-case theoretical exposure of 8 × £2,000 = £16,000 (if every op quoted the
ceiling) is an exposure bound, never a budget. Recorded in
`docs/handoff/2026-10-22/d4-corridor-option-c-implementation.md`. **Review outcome
(2026-10-22, offline, E23):** the independent offline review of that implementation
returned **`PASS WITH CONCERNS`** — the implementation and its 55 controlled tests are
review-cleared for fresh-candidate preparation via the existing authorization process;
two non-blocking code observations and one documentation defect (fixed during the
review) are recorded in
`docs/handoff/2026-10-22/d4-corridor-option-c-implementation-review.md`. **Staging
outcome (2026-10-22, offline, E24):** the fresh candidate **`D4-CORRIDOR-2`** is
staged at `artifacts/experiments/d4-corridor-native-candidate-2/` —
`PRELAUNCH PASS` + standalone read-only `PREFLIGHT PASS`, seal
`de0e16f7…04f00`, plan digest `2a30e950…cabb3a` (v2, eight ops), 25 planned
exchanges / budget 31, source world byte-bound to the D3 after-save
`fbebef54…d59e`; the attempt identity was operator-approved before staging
(module constant moved from the consumed `D4-CORRIDOR-1` to the never-consumed
`D4-CORRIDOR-2`), with the focused suites re-run 55/55 PASS afterward.
**Read-only payload verification (2026-10-22):** the staged authorization
payload was rebuilt offline and matched its staged digest
`e85ea64b…52ff17` (full
`e85ea64ba8ec15c383e913a72df7d1e4bd13569496a83d297bf7ee2c1952ff17`,
2,393 bytes), the frozen closure hash-verifying 3,447/3,447 (0 missing,
0 mismatches) — verification only: nothing signed, no claim, no launch.
Record:
`docs/handoff/2026-10-22/d4-corridor-native-candidate-2-payload-verification.md`.
At that stage the remaining requirement was ONE fresh explicit operator
authorization — later issued for candidate-3 (E28). D4 remains INCOMPLETE
(native), and no native quote for the eight-op schedule existed then. Staging
record:
`docs/handoff/2026-10-22/d4-corridor-native-candidate-2-preparation.md`.

**2026-10-25 restage (E27):** candidate-2's frozen closure was proved stale
against the accepted ADR-012/ADR-013 source edits (read-only preflight fails
`verify_freeze`; never consumed, not edited). Fresh candidate
**`D4-CORRIDOR-3`** is staged at
`artifacts/experiments/d4-corridor-native-candidate-3/`: `PRELAUNCH PASS` +
read-only `PREFLIGHT PASS`, seal `8cc8c1f7…7d24`, plan digest
`2a30e950…cabb3a`, payload `e1163d09…068d`, 3,448-entry frozen closure,
focused suites 55/55 PASS. At that stage ONE fresh explicit operator
authorization was required; it was then issued and the candidate was consumed
(E28). D4 remains INCOMPLETE (native). Record:
`docs/handoff/2026-10-25/d4-corridor-native-candidate-3-preparation.md`.

**2026-10-25 native outcome (E28):** the operator authorized signing, then the
one-shot native run. `D4-CORRIDOR-3` was consumed exactly once after all
pre-run gates passed. `op-00`–`op-02` built and read back (£785 + £1,398 +
£1,151; funds £496,543 → £493,209); `op-03` (interior join `48047↔48303`) was
refused at admission as `NOT_BUILDABLE` with cost 0 and `pairs_ok 1`, so the
runner halted with `ValueError: native READY admission with positive tested cost
required`. `op-04`–`op-07` and the route read never executed. The result is
`PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `status: FAILED_CLEANUP`;
`after-diagnostic.sav` (`b52d0ecf…970b`) is not an authoritative save, no
`after.sav`/`receipt.json` exists, and read-only replay refuses `halted attempt
cleanup incomplete` (a TCP state-5 observation prevented workspace/credential
disposal; no listener remains). Manifest 48/48 OK. No retry, re-sign or
replacement candidate. **D4 remains INCOMPLETE (native).** Record:
`docs/handoff/2026-10-25/d4-corridor-native-candidate-3-outcome.md`.

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
- Classification: 83 `PROJECTED_FLAGS_DIFFER` disagreements remain sealed. The offline
  reconciliation is `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED` (77 definitional, 6
  temporal tiles, 0 contradictions). ADR-012 (six temporal, planning evidence only) and
  ADR-013 (19 definitional, accepted 2026-10-25) are active in the derived layer; the
  combined P08 planning binding is allowed with `p08_complete: false`, while the fusion
  gate remains **CLOSED**. Native Random World execution and native classification
  evidence remain separate, authorization-gated work ([[05-Planning/Blockers]]).
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
