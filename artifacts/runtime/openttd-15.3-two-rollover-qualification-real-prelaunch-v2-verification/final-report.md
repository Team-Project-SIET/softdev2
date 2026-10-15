# Qualification Attempt 1 diagnosis and V2 preparation

## Failure classification
Attempt: two-rollover-qualification-v1-native-attempt1.
Freeze: openttd-15.3-two-rollover-qualification-real-prelaunch/PRELAUNCH.json, revision1.
Classification: POST-LAUNCH FAILURE. Overall: FAILED.
Failure phase: first M1 anchor structural request.
Exception: TransportTimeout: structural-world phase deadline expired.

## Request-send classification
B — sent, no GS receive.
The transaction ledger marks SENT and retains the exact payload; native accounting admits an outbound application frame. No structural response, receipt or GS receive/read/response evidence exists.

## Timeline
Baseline January1950/date712223; clocks1–59 in January; clock60 February1/date712254; clock61 M1 guard; fresh anchor session constructed after guard; first industry_page sent; timeout after the fresh5-second response wait; cleanup and FAILED. Native log launch08:24:43 to shutdown08:25:51. Missing Python monotonic timestamps are not invented. Detailed partial order is retained in dispatch-repair-verification/timeline.json.

## Root cause
Proven: modern base.Handle delegation is incompatible with exact OpenTTD15.3 Squirrel, where parent is the supported keyword and base is an undefined identifier. The dispatcher throws before the raw handler receive marker; the event loop catches it; Python times out. Exact tagged compiler/VM red/green reproduction and actual composed adapter replay establish this.
Primary aged-deadline hypothesis REJECTED. No shared absolute structural deadline or pre-created session exists. All ten hypotheses and deadline objects are traced in docs/two-rollover-qualification-attempt1-diagnosis.md.
Scope: qualification bridge composition. Explicit RawObservationBridge.Handle.call(this,request) covers all delegated raw commands. Raw historical bridge package unchanged.

## Deadline model
Overall: fixed300seconds from collect entry, including all phases.
Polling: same overall bound, shared paced poll ceiling; no rollover renewal.
Phase: new structural/production sessions at phase entry; no separate absolute phase-wide deadline.
Request/evidence: fresh relative min(5,remaining overall).
Native evidence loop: fresh5second local loop within bounded callback.
Cleanup: shared process lifecycle5second graceful/terminate/kill waits; independent post-failure cleanup.
No timeout values changed. No polling values changed. No qualification semantics changed.

## Repair
qualification_bridge.nut: one receiver-preserving delegation line.
qualification_contract.py: explicit deadline/dispatch authority, revision2 and attempt2 destination.
qualification_lineage.py: retained canonical native predecessor ID/error/states; validate owner's top-level manifest plus its recursively bound payload. Nested mutation rejected.
qualification_preparation.py: freeze diagnosis/language-reference/test authority.
harness.py: V2 prelaunch-failure revision metadata.
Tests and focused diagnosis document added; exact tagged lexer/compiler digests retained.

## Accounting
Clock304; requests1072; bytes368080; query operations9088; lifecycle6; frames9094 remain exact. Per-phase budgets unchanged. Dispatch and Python-only contract metadata add0 requests/frames. No reset/retry/reconnect/resume.

## Attempt1
M0 PROVEN; first adjacent rollover PROVEN; anchor NOT PROVEN COMPLETE; second rollover NOT PROVEN; qualified history NOT PROVEN; overall FAILED. No historical evidence rewritten.

## V2
Freeze: artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v2/.
New attempt: two-rollover-qualification-v2-native-attempt2.
Destination: artifacts/runtime/openttd-15.3-two-rollover-qualification-real-attempt2/.
Predecessor classification: POST-LAUNCH FAILURE (typed lineage RUNTIME).
Prelaunch continuation exception: NO. Fresh authorization required: YES.
Fresh credential mode0600, private bytes excluded from public evidence.
Exact identities/digests are copied directly from PRELAUNCH into freeze-summary.json.

## Guarded public preflight
Public CLI: python -m app.simulation.openttd.proof preflight --mode two-rollover-qualification.
READY_TO_LAUNCH:YES. Subprocess created:NO. Admin connected:NO. Request sent:NO.
V2 source/history/native authority/polling/coordinator/accounting/ownership/lineage/destination validation passed. EndpointReservation.allocate and final subprocess boundary reached; creation blocked.

## Historical integrity
1446 pre-task artifact/CONTEXT snapshot hashes exact; original1360 protected entries exact.
V1 freeze and Attempt1 evidence byte-identical; complete raw proof and production Attempt1/2 unchanged; CONTEXT.md unchanged. V2 source freeze and manifest exact after guarded preflight.
V2 identities:252 source/input,1461 protected public,7 archived credentials.

## Tests
35 new repair tests +57 preparation tests PASS, including exact-tagged VM, delayed phase entry, expired overall deadline, continuous accounting and nested evidence tampering.
Focused2105 passed/4 skipped (239.85s).
Final serial ordinary2641 passed/38 skipped (276.51s), including qualification, clock/lifetime/polling, raw coverage, production/proof, cleanup/lifecycle, structural/catalog/capability/inventory, transport/secure Admin/lineage, external controlled runtime and P03–P08.
Ruff PASS; format PASS333files; scoped typecheck PASS; diff/whitespace/import audits PASS.

## Runtime activity
OpenTTD launches0; live Admin connections0; real requests0. Standalone controlled Squirrel execution is not an OpenTTD gameplay launch.
No commit or push. P08 integration:NO. Atomic snapshot:NO. Real two-rollover qualification remains NOT PROVEN.

## Status
READY TO REQUEST FRESH AUTHORIZATION FOR OPENTTD 15.3 TWO-ROLLOVER QUALIFICATION ATTEMPT 2
