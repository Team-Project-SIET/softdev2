---
title: "Failed Attempts"
type: evidence
status: current
updated: 2026-10-26
tags:
  - openttd
  - evidence
  - failed
  - immutable
---

# Failed Attempts (immutable history)

> These records are FINAL. Never delete, rewrite, relabel, regenerate, or retry a
> consumed attempt. Learning from failure requires the failure record to stay exactly as
> recorded. Status later improvements never retroactively change a terminal.

## Native attempt failures

| Attempt | Date | Failure | What survived | Evidence |
|---|---|---|---|---|
| Seed 17 smoke (`playable-demo-698799a2d…`) | 2026-10-17 | Planning failed before execution: native facts complete but P08 found `NO_BOUNDED_CORRIDOR` on the only capturable pair (coal) → 0 candidates → P05 NOT_RUN → `NO_FEASIBLE_SERVICES`; no construction/delivery | Interface/spec verified; 10 industries, 11 cargos, 6 pairs; spectator + screenshots; fail-closed cleanup; diagnostics retained | E8 |
| Seed 17 smoke (original, old capture gate) | 2026-10-17 | Terminal FAILED under the old 256-rect gate; funding mutation separate from service construction | Native generation/discovery/GUI verified | E4 |
| V2 classification capture attempt 1 (`classification-exec-seed17-e71c95a3`, attempt `750167949a4f46af…`) | 2026-10-18 | Instance died in readiness window (stored AI unresolved→dummy AI; no `Load()` hook); 0 requests/0 pages; `FAILED_CLEANUP`; world correspondence NOT established | Auth consumed; fail-closed chain (process reaped rc 0, credential removed, ports freed); `capture-failure.json`, logs, `failure.sav` retained; SAME_SESSION fallback untouched | E14 |
| Attempt 10 | pre-2026-10-14 | `NETWORK_INDUSTRY_BUILD_FAILED` at second layout (same-town rule, `multiple_industry_per_town=0`); zero service requests ≠ zero world mutations | Immutable directory incl. `failure.sav`; later fixed by explicit setting check | README |
| Attempt 15 | scaling checkpoint | First road command logged £2,512 then bridge crash (`RecordConstruction: the index 'base' does not exist`) → runner Timeout; no delivery/CAPEX/revenue verified; last pre-mutation cash readback £499,616 is NOT final cash | Failure analysis + charts; fix verified offline by the fresh Attempt 17 | README |
| Attempt 19 | 2026-10-15 | Auto-renew init succeeded but policy finalization collided with an existing `company-policy.json` (`FileExistsError`); native terminal **FAILED**; one readback disagreement (setter true, readback false) | 1,826 economy days, 1,605 snapshots retained; separate offline recovery (derived finalization) verified **within derived scope** — original terminal never relabeled | E3 |
| Qualification Attempt 2 | 2026-10-11 era | Native SUCCESS/COMPLETED but mandatory post-run offline verification failed → overall FAILED | Historical validation + next-attempt derivation separated; Attempt 3 needs fresh authorization, doesn't change Attempt 2 | CONTEXT §20 |
| D4 corridor `D4-CORRIDOR-3` | 2026-10-25 | Consumed once; `op-00`–`op-02` built, `op-03` redundant interior join correctly `NOT_BUILDABLE` at admission, runner halted before dispatch; `op-04`–`op-07` and route read never ran; no receipt-bound after-save; historical cleanup `FAILED_CLEANUP` (TCP state 5) | Three verified prefix receipts; funds £496,543 → £493,209; all request/response pairs, diagnostic save and 48/48 manifest retained; later read-only verification confirmed credential removal/workspace disposal while preserving the failed outcome (E30); identity must not be retried or reused | E28, E30 |
| D4 corridor `D4-CORRIDOR-4` | 2026-10-25 | Consumed once; `op-00`–`op-05` built and read back, then `op-06` depot response was rejected before parsing — its 513-byte GameScript payload exceeded the then-hard-coded 512-byte application limit (`MalformedMessage`); no `confirm-06`, receipt or authoritative after-save; route read never ran | Six verified prefix receipts (£4,004; £496,543 → £492,539), including perpendicular corner and both stops; retained 517-byte frame (native log reports `BUILT`), 19 exchanges, diagnostic save and 80/80 manifest; cleanup PASS (all four fields true); replay raised the same error at the time. Offline E33 corrects protocol 4's decode bound to 640; replay now stops at missing durable confirmation. Identity must not be retried or reused | E32, E33 |

The failure chain for this milestone ends here: the next staged identity
`D4-CORRIDOR-5` consumed its explicit-operator-authorized one-shot run
successfully on 2026-10-26 — all seven v3 operations verified, route verified,
authoritative after-save retained (E35, [[04-Evidence/Native Verification]]).
That success does not relabel any record above: identities 1/3/4 remain
failed/partial, identity 2 remains stale, and none of them may be retried,
reused or re-signed.

Repeat-consumer blocklist (kept prominent):
`playable-demo-698799a2d…`, `random-smoke-correction-b84b9bd…`, `classification-exec-seed17-e71c95a3`,
Attempts 10/11/15/19, and every other consumed package in
[[04-Evidence/Evidence Index]].

## Offline/controlled "failures" that are results, not defects

- `NO_BOUNDED_CORRIDOR` (E8/E9) and `NO_CONNECTED_LEVELED_CORRIDOR` (E10) are **correct
  feasibility verdicts** — proofs of infeasibility with the evidence at hand, not bugs.
- SOURCE_SAVE_FUSION `REJECTED` (E16) is a correct negative gate result.
- `V2 → SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED` (reconciliation record) is a partial
  result with the next-step evidence explicitly named ([[05-Planning/Blockers]]).

## Rules carried from CONTEXT/AI_HANDOFF

- Deterministic tests, explicit proof criteria, controlled real-game attempts, retained
  logs/evidence, cleanup after execution, no success claims without execution evidence.
- Do not preserve the old transport mechanism merely because code exists.
- Never weaken correspondence checks to make reconciliation or replay succeed.
- Fresh same-instant evidence or an explicit operator policy decision is required before
  any unknown-tile assessment change.
