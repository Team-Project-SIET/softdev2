# Real two-rollover qualification attempt 1 — FAILED

## Runtime
Checkpoint HEAD: cc7f7479e3fbfa8c036901ba041dee1b97dc6b42.
Public command: `.venv/bin/python -m app.simulation.openttd.proof run --mode two-rollover-qualification --authorize-one-launch`.
Launches: 1. Secure connections: 1. Retries: 0. Reconnects: 0. Resume: NO.
Native log interval: 08:24:43–08:25:51 local, approximately 68 seconds through shutdown.
Process/connection continuity held through failure; M0→M2 continuity was not established.

## Economy timeline
M0: January 1950, native date 712223, day 1.
First rollover: February 1, 1950, native date 712254; adjacent transition observed.
M1: February 1950. Second rollover / M2 / final guard: NOT REACHED.
Qualified month: NOT ADMITTED. Third rollover: not observed.
Native clock: GSDate.GetCurrentDate/GetYear/GetMonth/GetDayOfMonth/GetDate.

## Polling
Clock requests: 61 = baseline 1 + paced polls 59 + pre-anchor guard 1.
Deadline: 300 seconds, not exhausted. Maximum clock requests: 304.
Clock observations, semantic receipts and native evidence/liveness chains: 61 validated.
Wall-clock pacing was operational only.

## M1 anchor
First industry_page request sent; no validated response retained.
Inventory/capability/catalog/structural anchor: incomplete.
Industries, structural digest, T1, L1: not finalized.
Anchor completion/month coherence: NOT PROVEN.

## M2 final structure and stability
Not reached. T2/L2/digest unavailable. Target/lifetime/fingerprint stability not evaluated.
No target additions/removals or lifetime changes can be inferred from this failed slice.

## Final production
Targets finalized: NO. Records: 0. Requests: 0. Response bytes: 0.
Production digest: absent. Complete: false. qualified_for_planning: false.
production_level: DEFERRED / NOT INCLUDED.
No production table exists for this attempt.

## Qualification evidence
Boundary 1 validated; boundary 2 absent. No fresh final production, final guard or admission.
Lifecycle: PREPARED → LAUNCHED → ADMIN_ACTIVE → QUALIFICATION_SESSION_STARTED → BASELINE_MONTH_OBSERVED → FIRST_ROLLOVER_OBSERVED → ANCHOR_COLLECTION_STARTED → CLEANUP_STARTED → PROCESS_REAPED → ENDPOINTS_CLOSED → CREDENTIAL_REMOVED → WORKSPACE_DISPOSED → POSTRUN_INTEGRITY_VERIFIED → FAILED.

## Accounting
| Phase | Requests | Response bytes | Native query operations |
|---|---:|---:|---:|
| Clock | 61 | 13819 | 244 |
| Anchor structural | 1 | 0 | 1 |
| Anchor lifetime | 0 | 0 | 0 |
| Final structural | 0 | 0 | 0 |
| Final lifetime | 0 | 0 | 0 |
| Final production | 0 | 0 | 0 |
| Total | 62 | 13819 | 245 |

Lifecycle frames actually counted: 5 (establishment 2 + setup 3), within allowance 6.
Post-auth frames: 250. Ceilings: 1072 requests / 368080 bytes / 9088 query operations / 9094 frames.
The incomplete anchor has one outbound query frame and no completed semantic exchange; its accounting must not be rounded to four operations.

## Provenance
One owned process, one encrypted X25519 AuthorizedKey connection and unchanged runtime/config/bridge through failure.
Final structural digest relation: unavailable; no final observation assembled.

## Cleanup
Admin closed; OpenTTD gracefully quit and reaped, return code 0.
Remaining owned processes: 0. Endpoints closed: YES. Credential removed: YES.
Workspace disposed: YES. Post-run integrity: PASS. Final state: FAILED.

## Failure boundary
Exact terminal error: `TransportTimeout: structural-world phase deadline expired`.
The first anchor industry_page request has an outbound native frame but no corresponding retained GameScript request/read/response chain or successful response.
This is an anchor collection timeout, not bounded qualification polling exhaustion. The underlying reason for the missing anchor response is not established by this report.
No source repair, resend, retry, reconnect or relaunch occurred.

## Claim boundary
Controlled qualification remains PROVEN by existing controlled tests.
Real two-rollover execution and qualified historical production: NOT PROVEN.
Complete qualified production and M0→M2 same-run provenance: NOT PROVEN BY THIS ATTEMPT.
Earlier real complete-raw-production proof remains unchanged and valid for its original scope.
P08 integration: NO. Atomic snapshot: NO. Independent source: NONE. Gameplay mutations: 0.

## Historical integrity
247 frozen source identities, 1360 protected public identities and 7 archived credential identities exact.
Freeze artifact manifest exact; CONTEXT.md unchanged.
Complete-raw proof, production Attempt 1 FAILED and Attempt 2 PASS, prior freezes and historical proofs preserved.
No historical evidence rewritten. No commit or push.

## Verification
Focused: 2070 passed, 4 skipped, 214.64 seconds.
Final serial ordinary: 2606 passed, 38 skipped, 275.66 seconds.
Includes qualification/preparation, clock/lifetime/accounting, coverage/production/proof, cleanup/lifecycle, structural/catalog/capability/inventory, transport/secure Admin/lineage, external runtime controlled and P03–P08 regressions.
Ruff PASS; format PASS (331 files); scoped typecheck PASS; diff check PASS; qualification-source whitespace/import-boundary audits PASS.
Offline native clock exchange validation: 61 PASS. Frozen source/history/manifest audit PASS.
No additional native execution occurred during verification.

## Status
OPENTTD 15.3 REAL TWO-ROLLOVER QUALIFICATION PROOF FAILED — NO RETRY PERFORMED — M1 anchor structural collection timed out
