# Qualification lineage regression diagnosis and repair

Local CONTEXT.md is the architecture authority. This work is offline only. Native
Attempt 2 and its offline failure evidence remain immutable. No commit or push.

## Failure classification

Attempt: two-rollover-qualification-v2-native-attempt2.
Overall: FAILED. Failure phase: POST-RUN OFFLINE VERIFICATION.
Native runtime: SUCCESS, lifecycle COMPLETED.
Qualification observation: complete=true, qualified_for_planning=true.
Cleanup and post-run runtime integrity: PASS. Mandatory offline verification: FAIL.

REAL NATIVE TWO-ROLLOVER QUALIFICATION EXECUTION COMPLETED SUCCESSFULLY AND PRODUCED
A QUALIFIED OBSERVATION BEFORE FINAL OFFLINE ACCEPTANCE FAILED.
Project-level proof status remains FAILED.

## Exact regression and reproduction

Test: tests/test_qualification_dispatch_repair.py::test_new_lineage_requires_revision_two_attempt_two_and_runtime_predecessor.
Command: `.venv/bin/pytest -q tests/test_qualification_dispatch_repair.py::test_new_lineage_requires_revision_two_attempt_two_and_runtime_predecessor --tb=long`.
Initial result: one deterministic failure, before any edit.
Expected assertion: `value["attempt_id"] == "two-rollover-qualification-v2-native-attempt2"`.
Actual intermediate identity: two-rollover-qualification-v2-native-attempt3.
Actual exception: `ValueError: Post-launch failure requires exact new attempt destination`.
Stack: test → capture_lineage → relevant_failures → predecessor_row/read_attempt;
then capture_lineage → validate_lineage → destination check. No test assertion reached.

The test passed directory=retained V2, revision=2, destination=retained Attempt 2.
Historical inputs: V2 attempt-lineage.json has only consumed Attempt 1 as predecessor;
V2 PRELAUNCH.json and qualification-contract.json bind Attempt 2.
Current inputs: discovery scans artifacts/runtime, reads both native attempt payloads,
their manifests, proof-attempt.json, proof-evidence.json, creating PRELAUNCH authority,
and recursively bound transaction/semantic evidence. Two launches imply attempt 3.
No native process, connection, or request is needed to reproduce this failure.

## Root cause and classification

Classification C: BOTH — INVALID API DESIGN. The test intends historical validation
of retained V2/Attempt 2, but recaptures current next-execution lineage. The execution
validator also compares frozen predecessors against current discovery, so loading
frozen V2 alone fails with `Unknown, unacknowledged, or missing predecessor failure`.

Ranked hypotheses tested before editing:

1. Wrong test operation: recapture derives 3; frozen V2 still names 2. Confirmed.
2. Validator coupling: validating unchanged frozen V2 against current history fails.
   Confirmed independently of capture/destination derivation.
3. Missing offline acceptance layer: current V3 derivation initially fails with
   `Failed post-launch predecessor required for new attempt`, since native Attempt 2
   says REAL_SUCCESS while retained verification.json says FAILED_POSTRUN_VERIFICATION.
   Confirmed. Native success must not erase overall failure or consumption.

Minimal controlled reproduction captures identity before each consumption, consumes
Attempts 1 and 2, validates both frozen identities, rejects both for execution, and
then derives 3. Each historical validation uses its frozen predecessor set only.

## Lineage API and caller audit

| API | Inputs and reads | Historical identity | Next identity / consumed safety | Intended and actual callers |
| --- | --- | --- | --- | --- |
| read_attempt / AttemptIdentity | Native directory, recursive payload, manifest, creating PRELAUNCH | Kind, revision, counts, terminal result, evidence digest, parents | No discovery or authorization | Retained predecessor readers; historical attempt validator |
| native_predecessor_row | Native directory / read_attempt and proof-evidence | Native status, ID, error, states | No next derivation | Frozen historical rows without later offline verdict |
| predecessor_row | Native directory plus retained mandatory offline-verification manifest/XML/JSON when native succeeded | Native identity plus separate overall failure | Supplies consumed current history; no new execution itself | Current capture; historical rows only when that verdict was already frozen |
| lineage_rows | Frozen lineage predecessor lists only | Returns canonical frozen rows | No discovery or derivation | Historical and execution validation, preparation metadata |
| digest / file_digest / _files / _json | Supplied public data or named retained files | Canonical JSON hashes, recursive public payload hashes and duplicate-safe records | No authorization or current history discovery | Attempt readers and validators |
| relevant_failures | Current sibling directories and proof kind | None | Discovers consumed history, despite legacy name | Current capture and execution validation only |
| capture_lineage / derive_next_attempt | Freeze path, revision, destination, full current history | Does not rewrite historical identity | Derives launch-count+1, requires newer freeze, exact new destination | Preparation checks and freeze creation; legacy tests exercising current derivation |
| validate_historical_lineage | Frozen lineage, revision, destination; only named frozen predecessors | Exact digest, identity, parent rows and frozen destination | Never discovers current-next identity; authorizes nothing | Historical validator, execution gate as first validation step, regression fixtures |
| validate_lineage | Same inputs plus current discovery and destination existence | Delegates historical checks | Rejects consumed destinations and missing/unacknowledged current history | Guarded preflight; preparation; runtime acceptance through preflight |
| validate_historical_attempt | Creating freeze, consumed destination; manifests and frozen contract | Exact creating authority, lineage, native ID, counts, requests, terminal result, recursive evidence and parents | No discovery and no launch authorization | Retained post-run verification and repaired original regression |
| failed_offline_verification | Retained postrun directory, native record, manifests, both mandatory XML suites | Manifest-bound separate native lifecycle / failed final verdict | No derivation or execution | Current qualification predecessor consumption |
| retain_attempt_identity | Directory, frozen metadata, terminal native result | Writes recursive terminal payload identity once | No authorization | Native cleanup/terminal recording and prelaunch failure recording |

Preparation calls check_qualification_preparation then freeze_qualification_preparation;
both use derive_next_attempt. validate_qualification_preparation uses the execution
gate, called by validate_native_inputs. Public preflight and runtime launch acceptance
both reach validate_native_inputs. Historical verification has its own API and never
loads current executable configuration or credentials.

## Shared impact

Enrichment, cargo-page, catalog, structural-world, single industry-production,
complete raw production, and qualification each duplicated historical checks and
current-history set equality in validate_lineage. All seven now expose historical
validation separately; their execution gates retain current discovery and reject
already consumed destinations. Existing proof-kind-specific policy remains unchanged.
No two-rollover-only exception to consumed protection exists.

ACK, world-info, industry-page/inventory, and single capability observation use
fixed-contract/history/destination gates in preflight rather than these lineage
helpers. They have no shared capture/validate ambiguity to repair. Their existing
consumed-destination and historical-protection checks remain intact.

Historical Attempt 2 validation reads its exact V2 contract, never the current V3
contract. A later offline sidecar is not retroactively a native frozen predecessor
field; native_predecessor_row preserves that time boundary. When a new freeze includes
an offline verdict, that exact manifest-bound verdict becomes part of its lineage.

## Repair and safety

Modified lineage modules: enrichment_lineage, cargo_page_lineage, catalog_lineage,
structural_lineage, production_lineage, raw_production_lineage, qualification_lineage.
Added offline_verification; updated qualification_contract/preparation and regression
fixtures. Accounting and runtime qualification code are unchanged.

Historical API: validate_historical_lineage and validate_historical_attempt.
Next-attempt API: derive_next_attempt; capture_lineage remains the compatibility entry
for existing next-preparation callers. Execution API: validate_lineage.
There is no force/ignore mode. Historical validation cannot authorize execution.
Attempt 2 remains consumed. Attempt 3 requires a new V3 freeze and fresh authorization.

The V3 lifecycle description distinguishes native COMPLETED from overall ACCEPTED.
Final PASS requires native lifecycle success AND mandatory offline verification
success. No runtime state, historical report, or old authority is rewritten.

## Contracts unchanged

Poll interval: 1 second. Overall deadline: 300 seconds. Max clock requests: 304.
Application requests: 1072. Response bytes: 368080. Query operations: 9088.
Post-auth frames: 9094. M0/M1/M2, T1==T2, lifetime stability, fresh M2 production,
final M2 guard, production_level exclusion, and P08 boundary are unchanged.

## Verification and V3 readiness

See the final controlled repair report for test counts, immutable-file audit,
V3 digests, fresh credential public identity, guarded preflight and final readiness.

## Required regression coverage

| Required cases | Controlled checks |
| --- | --- |
| Historical Attempts 1/2; historical Attempt 2 destination | test_consumed_attempt_historical_identity; original repaired regression |
| Attempts 1/2 cannot execute | test_consumed_destination_rejected_for_execution; shared consumed guard cases |
| After 1 → 2; after 1+2 → 3 | test_controlled_consumption_separates_history_and_next |
| Historical validation never derives next | test_historical_validator_never_discovers_current_history; seven shared historical seam cases |
| Derivation preserves historical identity | test_current_next_attempt_preserves_frozen_identity; immutable byte comparison |
| Attempt 3 preparation destination; incorrect destinations | test_current_next_attempt_preserves_frozen_identity; test_next_attempt_wrong_destination_rejected; public preparation tests |
| V2 and Attempt 2 immutable | test_retained_public_evidence_manifest_exact; before/after protected-file audit |
| Overall FAILED, native success, offline failure | test_current_next_attempt_preserves_frozen_identity and manifest-bound verification checks |
| No prelaunch exception; post-launch rule | fresh authorization/continuation assertions; test_next_attempt_requires_new_freeze |
| No force/ignore switch | Distinct APIs have no bypass parameter; consumed execution rejection remains unconditional |

The repaired original test now reads V2's retained lineage and calls historical
validation. It no longer uses the current REVISION/ATTEMPT_DIRECTORY constants to
assert a historical identity. Current preparation tests use the new V3/Attempt 3
constants and two controlled consumed predecessors.
