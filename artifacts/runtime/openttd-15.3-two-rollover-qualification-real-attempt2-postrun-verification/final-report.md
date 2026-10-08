# Attempt 2 post-run acceptance report

Native execution recorded REAL_SUCCESS after cleanup and post-run integrity, with lifecycle COMPLETED. Final task acceptance is FAILED because the required offline regressions are not fully green. Native evidence remains unchanged; its truthful qualified observation is retained.

## Attempt

Attempt: two-rollover-qualification-v2-native-attempt2. Freeze: immutable V2. HEAD: cc7f7479e3fbfa8c036901ba041dee1b97dc6b42. Predecessor: two-rollover-qualification-v1-native-attempt1, immutable POST-LAUNCH FAILED. No retry or source change.

## Runtime

Launches: 1. Secure connections: 1. Retry: 0. Reconnect: 0. Resume: NO. Duration approximately 122 seconds (retained server log 09:13:40 through shutdown 09:15:42). Process/connection/runtime/world/config/bridge continuity: PASS throughout M0→M2. Gameplay mutations: 0. No commit or push.

## Dispatch repair

Old unsupported expression: base.Handle(request). New expression: RawObservationBridge.Handle.call(this, request).

First M1 structural request: openttd15-qualification-001-anchor-inv-p001. SENT; GameScript lines 318–321 record BRIDGE_REQUEST_RECEIVED → INDUSTRY_PAGE_READ → BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE. Python records INDUSTRY_PAGE_REQUEST_SENT → INDUSTRY_PAGE_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → PAGE_VALIDATED. Receipt and semantic validation PASS. Economy-clock handlers also execute successfully. This establishes progression beyond the old dispatch failure, rather than merely absence of timeout.

## Economy timeline

M0: January 1, 1950, economy date 712223. Rollover 1: February 1, date 712254. M1/qualified month: February 1950. Rollover 2: March 1, date 712282. M2: March 1950. Final guard: March 2, date 712283. Third rollover: NO. Adjacent observed rollovers: 2.

## Polling

Clock requests: 115 (baseline 1, paced polls 110, collection guards 4). Frozen deadline: 300 seconds; not exhausted. Poll interval: 1 second. Wall-clock pacing is operational liveness only. Native economy observations establish qualification.

## M1 anchor

Structural complete: YES. Industries: 10; complete capability and 11-cargo catalog. T1: 10 targets. L1: 9 relevant industry identities. Month coherence: M1 PASS.

Structural digest: cb3986f04767359b76d6cefd8181b4830335665a2560316e014b9204ee7e7207.

## M2 final

Fresh structural complete: YES. Industries: 10; complete capability and catalog. T2: 10 targets. L2: 9 relevant identities. Final structural/lifetime/production/guard month coherence: M2 PASS.

Structural digest: cb3986f04767359b76d6cefd8181b4830335665a2560316e014b9204ee7e7207.

## Stability

T1 == T2: YES. Target additions/removals: 0/0. Lifetime/fingerprint changes: 0. Lifetime construction dates are CALENDAR identities, separate from ECONOMY month evidence.

## Final production

Targets/records/requests: 10/10/10, exactly one request per target. Response bytes: 2857. Complete: true. Native-qualified_for_planning: true. Production digest: f873858c6aba09802d22b07898412731dc66d376609447576ac47fbce4fded72.

Source structural digest equals fresh final M2 digest. Production_level: DEFERRED / NOT INCLUDED. Station allocation is native allocation, not delivery or vehicle pickup. Per-query brackets are M2 current-state capture metadata, not M1 qualification boundaries. Equal brackets valid.

| industry_id | cargo_id | raw production | station allocation | transported % | economy_before | economy_after |
|---|---|---|---|---|---|---|
| 0 | 1 | 168 | 0 | 0 | 712283 | 712283 |
| 2 | 5 | 0 | 0 | 0 | 712283 | 712283 |
| 3 | 7 | 80 | 0 | 0 | 712283 | 712283 |
| 4 | 5 | 0 | 0 | 0 | 712283 | 712283 |
| 5 | 5 | 0 | 0 | 0 | 712283 | 712283 |
| 6 | 9 | 0 | 0 | 0 | 712283 | 712283 |
| 7 | 4 | 56 | 0 | 0 | 712283 | 712283 |
| 7 | 6 | 88 | 0 | 0 | 712283 | 712283 |
| 8 | 3 | 96 | 0 | 0 | 712283 | 712283 |
| 9 | 8 | 88 | 0 | 0 | 712283 | 712283 |

## Accounting

| Phase | Requests | Response bytes | Query operations |
|---|---:|---:|---:|
| clock | 115 | 26075 | 460 |
| anchor_structural | 21 | 4695 | 84 |
| anchor_lifetime | 9 | 1881 | 36 |
| final_structural | 21 | 4674 | 84 |
| final_lifetime | 9 | 1872 | 36 |
| production | 10 | 2857 | 40 |
| TOTAL | 185 | 42054 | 740 |

Deterministic lifecycle frames: 6, paid once. Total post-auth frames: 746. Frozen total ceilings: 1072 / 368080 / 9088 / 9094; all phase bounds independently PASS. One continuous accounting object, no reset/budget borrowing.

## Qualification evidence

Boundary 1 and boundary 2 retained in qualified-month.json: M0→M1 and M1→M2, respectively. Qualified month February 1950. Fresh final structure and production recorded after boundary 2. Final M2 guard is the last validated clock transaction, after production and before admission. All clock/lifetime/structural/production receipts, semantic chains and post-response liveness PASS. Qualification admission passed. No false total timestamp ordering is imposed between evidence producers.

## Cleanup

Admin closed; process stopped/reaped; endpoints closed; runtime credential removed; workspace disposed; persistent source and protected history integrity verified. Remaining owned OpenTTD processes: 0. Native lifecycle COMPLETED only after POSTRUN_INTEGRITY_VERIFIED. Generated evidence retained.

## Claim boundary

Controlled qualification: PROVEN. Native real two-rollover execution, qualified historical production, complete production and same-run provenance: supported by successful native semantic evidence. Overall task acceptance remains FAILED due to post-run verification. P08: NO. Atomic snapshot: NO. Independent source: NONE. Target/lifetime checks mitigate specific drift only; observation remains NON-ATOMIC and PRE-DECISION.

## Historical integrity

252 source identities, 1461 protected public files and 7 archived credential identities exact after cleanup and verification. V2 freeze manifest exact. Attempt 1 freeze/evidence unchanged and FAILED. Complete raw proof and production Attempts 1/2 unchanged. CONTEXT.md unchanged. No files restored or historical artifacts rewritten.

## Tests

Focused: 2104 passed, 4 skipped, 1 failed in 225.77 seconds. Includes repair, qualification, clock/lifetime, polling/accounting, 62 coverage, 81 production, proof, cleanup/lifecycle, structural/catalog/capability/inventory, bridge/transport/secure Admin, lineage, external-runtime and P03–P08 regressions.

Final serial ordinary suite: 2640 passed, 38 skipped, 1 failed in 241.95 seconds. No concurrent verification activity.

Both fail only tests/test_qualification_dispatch_repair.py::test_new_lineage_requires_revision_two_attempt_two_and_runtime_predecessor. Isolated rerun fails in 0.29 seconds. It calls capture_lineage for V2/Attempt 2 against live repository history after Attempt 2 has been consumed. Discovery includes the newly completed runtime attempt; capture derives attempt 3, so retaining destination attempt2 is rejected with ValueError: Post-launch failure requires exact new attempt destination. This is a prelaunch-state test incompatibility after execution, not evidence of native dispatch/qualification failure. Failure logs retained; suite is NOT reported PASS. No repair or freeze change performed.

## Quality

Ruff PASS. Format PASS (333 files). Applicable scoped typecheck PASS. git diff --check PASS. Qualification-module whitespace/import-boundary audit PASS. No private-key files or private-key PEM blocks in runtime evidence. Unrelated local work preserved.

## Status

OPENTTD 15.3 REAL TWO-ROLLOVER QUALIFICATION ATTEMPT 2 FAILED — NO RETRY PERFORMED — post-run lineage regression failed in focused and serial ordinary suites
