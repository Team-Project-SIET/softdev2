---
title: "Current Status"
type: project
status: current
updated: 2026-10-24
tags:
  - openttd
  - status
---

# Current Status

Snapshot taken **2026-10-22** from the `devmodule2` working tree (commit `5872689`,
dirty tree per [[99-Source-Documents/AI_HANDOFF]]) plus the newest handoff records
(`docs/handoff/2026-10-21/`, `docs/handoff/2026-10-22/`). The fixed demo remains the
stable default. Datestamp discipline: statements below carry the date of their
authoritative record; older statuses are historical and preserved, not reconciled.

## Evidence-backed state by area

Condensed from [[99-Source-Documents/AI_HANDOFF]] (2026-10-17 + 2026-10-18 addendum) and
the 2026-10-21/22 addenda of [[99-Source-Documents/EVIDENCE_INDEX]]. Full per-attempt
detail: [[04-Evidence/Native Verification]], [[04-Evidence/Failed Attempts]],
[[04-Evidence/Evidence Index]].

| Area | State and boundary | Evidence |
|---|---|---|
| Stable fixed demo | **VERIFIED** native 15.3 gameplay at checkpoint `a348016`: P08/P05 selected 3 freight services, vehicles 4/5/6, 60 coal delivered, £1,022 revenue, £28,459 CAPEX; spectator joined/inspected; fresh P07, cleanup and evidence checks PASS. No direct company control; no full OPEX/ROI. | E1 |
| Canonical creation Q3 | **PROVEN** in retained native engineering evidence; `CANONICAL_CREATED_PENDING_FRESH_PROCESS_RELOAD`, 1 launch/connection, 27 mutations. | E2 |
| Fresh-process reload Q3 | **PROVEN** reload-only: `CANONICAL_RELOAD_ONLY_VERIFIED`, exact semantic correspondence, 0 mutations. Purchase/dispatch/unpause disabled — not proven by this. | E2 |
| Attempt 19 (five economy years) | Original native terminal **FAILED** at finalization (`company-policy.json` already existed). Separate offline recovery valid within derived scope; never relabel the original terminal. | E3 |
| Random World implementation | **CONTROLLED/OFFLINE** implementation present in dirty tree; native generation/discovery/GUI verified in Seed 17; native service execution unverified. | E4, E5 |
| Seed 17 smoke | **FAILED** — preflight 12/12 PASS, one launch, facts complete, but P08 found `NO_BOUNDED_CORRIDOR` on the only capturable pair (coal) → 0 candidates → P05 NOT_RUN → `NO_FEASIBLE_SERVICES`. Later proven a complete-search infeasibility by a bounded terrain-aware oracle (E9). | E8, E9 |
| Tile Classification V2 | Capture **completed natively** 2026-10-18 (`TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT`): 90/90 pages, 450/450 tiles, schema-2, staged AI + GameScript startup, 0 mutations, cleanup PASS. **SOURCE_SAVE_FUSION verdict REJECTED** — 83 `PROJECTED_FLAGS_DIFFER` disagreements; nothing fused; the 19 remain UNKNOWN in the base ledger, while ADR-013 (accepted 2026-10-25) resolves them in the derived layer to `TERRAIN_MODIFICATION`. P08 planning binding is allowed (`p08_complete: false`); fusion gate still **CLOSED**. | E14–E16 |
| Milestone D2 native clearing | **PROVED** — tile 46769 cleared by one `GSTile.DemolishTile`, cost £15, result `NATIVE_STATE_VERIFIED`, immutable claim consumed, cleanup complete. | E17 |
| Milestone D3 native clearing + terraforming | **PROVEN**, closed 2026-10-22 — two bounded clears (45999 £30, 49326 £45) + 16 compiled S-corner raises (£3,382) all `RECEIPT_VERIFIED`; finances reconcile to £496,543; post-D3 world `fbebef54…d59e` is verified native evidence. | E18, E19 |
| Milestone D4 road + station construction | **ATTEMPT CONSUMED — INCOMPLETE** — the one candidate `D4-CORRIDOR-1` was consumed by its operator-authorized launch 2026-10-22 and the ceremony ended `PHASE_HALTED_PREFIX_PRESERVED`, `verified: false`: `op-00` verified (5 tiles, £785, funds £496,543 → £495,758); `op-01` refused at admission (£2,549 > £2,000 ceiling, no command issued); `op-02`–`op-05` and the route read not executed; no receipt/`after.sav`. The approved Option C restage decision (8-op split-run-B schedule inside the unchanged £2,000 per-op ceiling) is implemented **offline only** 2026-10-22 (E22, ADR-011): 55 controlled tests PASS, no native quote/command/authorization for the new schedule. Staging facts (E20) remain historical; the independent offline review is complete (`PASS WITH CONCERNS`, E23) and the original fresh candidate `D4-CORRIDOR-2` is now **stale/superseded** (E24; its frozen closure predates the accepted ADR-012/ADR-013 source edits, so a read-only preflight on 2026-10-25 fails `verify_freeze`; it was never consumed and was not edited). A fresh candidate **`D4-CORRIDOR-3`** was staged 2026-10-25 (E27) and then **consumed exactly once** by its operator-authorized native run (E28): `op-00`–`op-02` built and read back (£785 + £1,398 + £1,151; funds £496,543 → £493,209); `op-03` (interior join `48047↔48303`) was refused at admission as `NOT_BUILDABLE` with cost 0; `op-04`–`op-07` and the route read never executed. Result `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `status: FAILED_CLEANUP`; no receipt-bound `after.sav`/`receipt.json`, and replay refuses `halted attempt cleanup incomplete`. No retry or reuse; D4 needs a fresh, separately authorized candidate with the `op-03` admission defect corrected. | E21, E22, E23, E24, E27, E28 |
| Offline V1/V2 semantic reconciliation | Uncommitted work: 83 disagreements accounted (77 definitional `buildable`, 6 temporal, 0 contradictions, 0 unresolved) → `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`. ADR-012 (6 temporal) and ADR-013 (19 definitional, accepted 2026-10-25) are active in the derived layer. Combined P08 **planning** binding allowed; `p08_complete: false`; fusion gate **CLOSED**; no native evidence. | [[05-Planning/Blockers]] |
| Fourth vehicle / matched experiments | **PREPARED/BLOCKED** — controlled A/B/C preparation exists; native readiness blocked because no retained canonical pre-intervention save exists. | [[02-Milestones/Pending Milestones]] |
| OpenTTD 13.4 proofs (P03/P06) | **Historical regression evidence only** — cannot establish 15.3 compatibility. | [[99-Source-Documents/CONTEXT]] §19 |

Statuses are scoped by their records: VERIFIED means supported by inspected retained
reports within the stated scope, not a fresh re-run. CONTROLLED means offline/controlled
validation that does not prove native runtime behavior. FAILED is an immutable consumed
outcome. UNKNOWN means missing facts. [[07-Reference/Status Definitions]].

## Worktree and vault sync facts

- Branch `devmodule2`; HEAD `5872689` ("docs(openttd): synchronize verified milestones
  and open blockers", 2026-10-18); **218 uncommitted status entries** as seen on 2026-10-22
  (`git status --short`). HEAD alone is incomplete — substantial engineering is
  modified/untracked locally, and it is not thereby published or accepted natively.
- CONTEXT.md/EVIDENCE_INDEX.md/TASKS.md carry uncommitted 2026-10-21/22 updates in the
  working tree (vault copies in `99-Source-Documents/` were taken from that working tree).
- **2026-10-24 operator-extraction documentation correction (documentation only):**
  `docs/handoff/2026-10-17/operator-key-provisioning.md` §1 and
  `docs/handoff/2026-10-21/d2-native-clearing-candidate-3-preflight.md` §6(b) now
  document the tested `od`/`tr` pipeline (no `-noout` on DER seed extraction) with
  `pipefail` state captured and restored. Validated with synthetic keys only; no
  production key was accessed and nothing was signed. No candidate, seal, evidence
  file or authorization record was touched, so this note's evidence statuses are
  unchanged.
- **Authority-pin conflict resolved 2026-10-25 (E26, ADR-014):** the historical
  2026-10-08 `CONTEXT.md` pin and every retained manifest stay frozen and unmodified;
  one explicit, fail-closed supersession record scopes only the exact path/digest
  transition, and the base validator is unchanged. The three former baseline failures
  now pass.
- Typecheck tooling (`mypy`/`ty`/`pyright`) recorded unavailable in recent offline
  validation runs — honest gap, not a pass. [[03-Engineering/Testing Strategy]].

## Dated caution against stale statuses

The dated statuses in [[99-Source-Documents/CONTEXT]] §20 (reviewed 2026-10-11) and the
older handoff versions remain historical. E.g. "qualification Attempt 2 reached native
SUCCESS/COMPLETED" refers to native qualification only; its mandatory post-run offline
verification failed, so **overall Attempt 2 remains FAILED**. Never transplant an old
status into a newer area; always re-derive from the newest record ([[04-Evidence/Failed Attempts]]).
