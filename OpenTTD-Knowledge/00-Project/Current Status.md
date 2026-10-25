---
title: "Current Status"
type: project
status: current
updated: 2026-10-26
tags:
  - openttd
  - status
---

# Current Status

Snapshot taken **2026-10-22** from the `devmodule2` working tree (commit `5872689`,
dirty tree per [[99-Source-Documents/AI_HANDOFF]]) plus the newest handoff records
(`docs/handoff/2026-10-21/`, `docs/handoff/2026-10-22/`, `docs/handoff/2026-10-25/`,
`docs/handoff/2026-10-26/`);
evidence notes are updated through **2026-10-26**. The fixed demo remains the
stable default. Datestamp discipline: statements below carry the date of their
authoritative record; older statuses are historical and preserved, not reconciled.

## Evidence-backed state by area

Condensed from [[99-Source-Documents/AI_HANDOFF]] (2026-10-17 + 2026-10-18 addendum) and
the 2026-10-21/22/25/26 addenda of [[99-Source-Documents/EVIDENCE_INDEX]]. Full per-attempt
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
| Milestone D4 road + station construction | **FOUR ATTEMPTS CONSUMED — PROVEN (2026-10-26) for exactly the reviewed v3 scope** — the first candidate `D4-CORRIDOR-1` was consumed by its operator-authorized launch 2026-10-22 and the ceremony ended `PHASE_HALTED_PREFIX_PRESERVED`, `verified: false`: `op-00` verified (5 tiles, £785, funds £496,543 → £495,758); `op-01` refused at admission (£2,549 > £2,000 ceiling, no command issued); `op-02`–`op-05` and the route read not executed; no receipt/`after.sav`. The approved Option C restage decision (8-op split-run-B schedule inside the unchanged £2,000 per-op ceiling) is implemented **offline only** 2026-10-22 (E22, ADR-011): 55 controlled tests PASS, no native quote/command/authorization for the new schedule. Staging facts (E20) remain historical; the independent offline review is complete (`PASS WITH CONCERNS`, E23) and the original fresh candidate `D4-CORRIDOR-2` is now **stale/superseded** (E24; its frozen closure predates the accepted ADR-012/ADR-013 source edits, so a read-only preflight on 2026-10-25 fails `verify_freeze`; it was never consumed and was not edited). A fresh candidate **`D4-CORRIDOR-3`** was staged 2026-10-25 (E27) and then **consumed exactly once** by its operator-authorized native run (E28): `op-00`–`op-02` built and read back (£785 + £1,398 + £1,151; funds £496,543 → £493,209); `op-03` (interior join `48047↔48303`) was refused at admission as `NOT_BUILDABLE` with cost 0; `op-04`–`op-07` and the route read never executed. Result `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `status: FAILED_CLEANUP`; no receipt-bound `after.sav`/`receipt.json`, and replay refuses `halted attempt cleanup incomplete`. The later reported credential removal and workspace disposal were verified read-only (E30): `credential_removed: true`, `workspace_disposed: true`, workspace absent, no candidate-3 secret/config file, but the historical TCP state-5 `verification_error` and missing `sockets_closed` remain, so the cleanup outcome and replay refusal are unchanged. Fresh candidate **`D4-CORRIDOR-4`** was then staged from the reviewed v3 schedule (E31): `PRELAUNCH PASS` + `PREFLIGHT PASS`, seal `88cd1ecc…fd22c3`, plan digest `b5b472ff…2283a78`, payload `4037c5d8…487c7f`, 7 ops / 22 planned / cap 28 / £2,000 per-op, no interior join, corner retained; it was signed (authorization `b069b484…5db6d`) and **consumed exactly once** (E32). `op-00`–`op-05` built and read back (£4,004; funds £496,543 → £492,539), including the perpendicular corner and both stops. `op-06` (depot) was dispatched; the native log reports `D4_RESPONSE depot-06 BUILT` and the retained frame reports `BUILT`/£390/£492,149, but its 513-byte response exceeded the 512-byte application limit and was rejected before parsing. Phase `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `status: PHASE_HALTED_PREFIX_PRESERVED`; no `confirm-06`, receipt or authoritative `after.sav`; cleanup PASS (all four fields true); manifest 80/80. Offline E33 corrects the protocol-4 decode bound to 640 while preserving the version-one 512 default; the retained 513-byte depot payload now parses, but replay still refuses at the missing durable response and D4 remains INCOMPLETE (native). No retry or reuse of consumed identities; finally, fresh identity **`D4-CORRIDOR-5`** was staged from the same reviewed v3 schedule (staging + independent fresh-context review **PASS 20/20**, 2026-10-25) and, under the explicit 2026-10-26 operator authorization covering signing plus exactly one native attempt, was **signed and consumed exactly once** (E35): every pre-signing gate re-verified fresh (including the 3,448-entry frozen closure via `PREFLIGHT PASS` and protocol 640/512/32763 statics/dynamics), signing by the approved checklist (record `55486971…dec03` under the pinned production anchor; seed never displayed/logged), then 1 launch / 1 connection / 22 of 28 requests. All seven v3 ops dispatched with positive tested quotes equal to native costs within the £2,000 per-op ceiling (£785 + £1,398 + £1,151 + £71 + £307 + £292 + £390 = £4,394) and each independently read back, including `confirm-06` (durable 513-byte depot response under the E33 640-byte bound). `PHASE_COMPLETE`, `verified: true`, `NATIVE_CORRIDOR_VERIFIED`; funds £496,543 → £492,149 confirmed by the route read `ROUTE_VERIFIED` 23/23; authoritative receipt-bound `after.sav` `a81ac836…ef261`; cleanup certified (all four fields true); manifest 90/90; read-only replay `RECEIPT_VERIFIED`; historical evidence re-verified unchanged. **Milestone D4 native road and station construction is COMPLETE (native) for exactly the reviewed v3 scope; the claim is consumed.** | E21, E22, E23, E24, E27, E28, E30, E31, E32, E33, E35 |
| Offline V1/V2 semantic reconciliation | Uncommitted work: 83 disagreements accounted (77 definitional `buildable`, 6 temporal, 0 contradictions, 0 unresolved) → `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`. ADR-012 (6 temporal) and ADR-013 (19 definitional, accepted 2026-10-25) are active in the derived layer. Combined P08 **planning** binding allowed; `p08_complete: false`; fusion gate **CLOSED**; no native evidence. | [[05-Planning/Blockers]] |
| Native execution attempt analytics | **CONTROLLED/OFFLINE, integrated 2026-10-25:** read-only run-level analytics over the seven retained native attempt directories (`analyze-native-attempts` CLI); statuses/verified flags verbatim, unverified attempts never counted as verified successes, missing fields UNKNOWN, cleanup fail-closed, lineage comparison descriptive only. Retained evidence hash-unchanged; no native evidence created. | [[04-Evidence/Controlled Tests]], `docs/native-attempt-analytics.md` |
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
- **D4 candidate-3 cleanup remediation + candidate-4 staging (2026-10-25, E30/E31):**
  read-only non-secret checks confirmed the reported credential removal and workspace
  disposal for `D4-CORRIDOR-3` (`credential_removed: true`, `workspace_disposed: true`,
  absent workspace, empty `isolated/`, no candidate-3 secret/config file or
  process/listener). The historical `verification_error`, missing `sockets_closed`,
  `result.json` `FAILED_CLEANUP`/`verified: false`, missing authoritative after-save and
  replay refusal are unchanged. Separately, `D4-CORRIDOR-4` was staged from v3
  (7 ops, 22 planned, cap 28, £2,000 per-op, no interior join, corner retained) with
  `PRELAUNCH PASS` + `PREFLIGHT PASS`.
- **D4 candidate-4 native run (2026-10-25, E32):** the cleanup-certification
  question is attempt-scoped: candidate-3's historical `FAILED_CLEANUP`/missing
  `sockets_closed` is preserved and is not a hard prerequisite for a fresh
  candidate, while current isolation was verified independently (no process,
  listener, workspace or secret; candidate-3/candidate-4 ports free).
  `D4-CORRIDOR-4` was signed and consumed once; `op-00`–`op-05` verified
  (£4,004; £496,543 → £492,539), `op-06` depot response exceeded the then-hard-
  coded 512-byte application limit after the native log reported `BUILT`; no
  readback/receipt; cleanup PASS; manifest 80/80. Offline E33 corrects protocol
  4's decode bound to 640 (version-one default unchanged); the retained frame
  now parses, but replay still refuses for missing durable confirmation and D4
  remains INCOMPLETE (native). Records:
  `docs/handoff/2026-10-25/d4-corridor-native-candidate-4-outcome.md`,
  `docs/handoff/2026-10-25/d4-corridor-response-limit-fix.md`.
- **D4 completed natively (2026-10-26, E35):** under the explicit operator
  authorization covering signature plus exactly one attempt,
  `D4-CORRIDOR-5` was signed by the documented approved checklist
  (record `55486971…dec03` verified under the pinned production anchor;
  seed captured, never displayed or logged, cleared after signing) after all
  pre-signing gates were re-verified fresh — seal `505b5d49…4a7c`, payload
  `77a965f0…0e4` (2,307 canonical bytes), plan digest `b5b472ff…2283a78`,
  source world `fbebef54…d59e`, 3,448-entry frozen closure via `PREFLIGHT PASS`,
  review PASS 20/20, protocol 640/512/32763 statics + dynamics, runtime
  isolation, focused suites 129/129. The single attempt: 1 launch / 1 X25519
  connection / 22 of 28 requests; all seven v3 ops verified with quotes equal
  to native costs (£4,394; £496,543 → £492,149), route `ROUTE_VERIFIED` 23/23
  (incl. the E33-fixed `confirm-06` depot readback on the 513-byte durable
  response), authoritative `after.sav` `a81ac836…ef261`, cleanup certified,
  manifest 90/90, replay `RECEIPT_VERIFIED`. Candidate-1/2/3/4 and D2/D3
  evidence re-verified byte-unchanged (candidate-4 manifest 80/80). The claim
  is consumed: the next milestone (D5 vehicle purchase/orders/delivery) needs
  a fresh reviewed candidate and fresh explicit operator authorization.
  Record: `docs/handoff/2026-10-26/d4-corridor-native-candidate-5-outcome.md`.
- Typecheck tooling (`mypy`/`ty`/`pyright`) recorded unavailable in recent offline
  validation runs — honest gap, not a pass. [[03-Engineering/Testing Strategy]].

## Dated caution against stale statuses

The dated statuses in [[99-Source-Documents/CONTEXT]] §20 (reviewed 2026-10-11) and the
older handoff versions remain historical. E.g. "qualification Attempt 2 reached native
SUCCESS/COMPLETED" refers to native qualification only; its mandatory post-run offline
verification failed, so **overall Attempt 2 remains FAILED**. Never transplant an old
status into a newer area; always re-derive from the newest record ([[04-Evidence/Failed Attempts]]).
