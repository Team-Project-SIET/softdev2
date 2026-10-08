# Complete raw industry-production real-proof preparation

## Baseline

HEAD: 278a3792b34fdb58085aff4e999dabac482cf21a.
Working tree: existing controlled changes and unrelated local P08/documentation files retained; no staging, commit or push. The task adds combined proof integration, tagged economy authority, tests and current preparation documentation.

## Previous blockers

- Combined CLI/lifecycle: CLOSED.
- Native economy authority: CLOSED.
- Freeze/preflight integration: CLOSED.

## Native economy authority

C++ API: ScriptDate::GetCurrentDate, returning ScriptDate::Date from TimerGameEconomy::date.base().
Generated binding: GSDate.GetCurrentDate.
Fields: economy_date_before and economy_date_after; Squirrel integers, native signed int32 economy day ordinals from year zero. V1 range 0..2147483647.
Meaning: current-state capture brackets around native last-month metrics, not historical month boundaries. before <= after; equal brackets are legal.
Fresh-world authority: new generated world, explicit TKU_CALENDAR=0 and starting_year=1950; native WELCOME.start_day is the configured calendar start date, not a current date. Source-equivalent Gregorian/native leap-year-zero conversion identifies the initial economy month. All collected brackets must remain inside it; a crossing fails immediately without waiting. No historical production value or bracket is an expected constant. Save loading/wallclock profiles are excluded.
Source and binding authority: 18 exact tagged 15.3 files plus source manifest, retained in tests/reference/economy_clock_15_3 and frozen economy-authority.json. See docs/complete-raw-production-economy-window-authority.md.

## Combined CLI

Mode: complete-raw-production.
Entry point: python -m app.simulation.openttd.proof.
Runner: RawProductionRunner / RawProductionNativeBackend / CompleteRawProductionSession.
Public preparation: python -m app.simulation.openttd.proof prepare --mode complete-raw-production.
Guarded public preflight: python -m app.simulation.openttd.proof preflight --mode complete-raw-production.
Phase order: A complete industry inventory → B complete capability → C complete cargo catalog → D complete StructuralWorldObservation → E complete raw production. Every preceding phase must finalize its complete observation and digest. D validates same-run provenance before target derivation or production requests.

## Lifecycle

States: PREPARED → LAUNCHED → ADMIN_ACTIVE → COMBINED_SESSION_STARTED → STRUCTURAL_COLLECTION_STARTED → STRUCTURAL_WORLD_COMPLETED → PRODUCTION_TARGETS_FINALIZED → RAW_PRODUCTION_STARTED → RAW_PRODUCTION_COMPLETED → COMBINED_OBSERVATION_VERIFIED → CLEANUP_STARTED → PROCESS_REAPED → ENDPOINTS_CLOSED → CREDENTIAL_REMOVED → WORKSPACE_DISPOSED → POSTRUN_INTEGRITY_VERIFIED → COMPLETED. FAILED is explicit.
Final success: only after all mandatory cleanup and integrity barriers, followed by COMPLETED and retained terminal evidence. Runtime semantic completion is intermediate. A cleanup, source/history integrity or terminal evidence-retention failure prevents final PASS.
Cleanup order: close Admin; stop/reap owned OpenTTD; confirm endpoints closed; remove credential; retain logs; dispose ephemeral workspace; validate persistent source/history; accept final completion. No retry, reconnect, resume or relaunch after failure. Partial production is retained as incomplete.

## Accounting

Structural request ceiling: 96 (industry_page 32, industry_cargo 32, cargo_page 32).
Production request ceiling: 512.
Combined request ceiling: 608.
Structural response-byte ceiling: 49152. Production: 171520. Combined: 220672.
Structural query ceiling: 1024. Production controlled query ceiling: 4096 (512 × 8 conservative allowance; normal observed subscribed queries can use four).
Combined query ceiling: 5120.
Lifecycle frames: 6, paid ONCE for the continuous session: encrypted PROTOCOL/WELCOME 2 + subscription UPDATE/PING/PONG 3 + graceful QUIT 1.
Total post-auth frame ceiling: 5126 = 5120 + 6.
Phase barriers, target finalization, model assembly and owned-stderr liveness add zero Admin frames. One shared secure frame observer/counter persists across all phases; query receipts validate it without adding another counter. Independent per-phase limits cannot borrow unused budget. Exact/overflow query and frame boundaries are tested.

## Same-run provenance

Process, continuous secure Admin connection, runtime, world, configuration and bridge identities must match across all components.
production.source_structural_world_digest must equal the finalized structural-world digest.
The owner constructs all observations inside the new runtime. Historical structural observations cannot supply production's source. StructuralWorldObservation remains unchanged; dynamic production remains separate.

## Targets

Source: same-run complete capability.records[*].produces.
Ordering: industry_id ascending, then cargo_id ascending.
Maximum: 512. Zero targets: valid; zero production requests and zero records can complete.
Immutable target tuple is finalized before the first production request. Industry/catalog membership, produced membership, uniqueness and exact response coverage are required. Accepted-only and catalog-only cargoes are excluded. No hard-coded historical target or synthetic native target exists.

## Production semantics and qualification

industry_production V1 is unchanged: audited worst-case response 335 bytes, application limit 512, native ceiling 1450; response headrooms 177 and 1115 bytes.
Raw last-month production, station-allocation transported quantity, native transported percentage and economy capture brackets keep the audited meanings. Station allocation does not mean vehicle pickup or delivered throughput. Zero and non-zero values are both legal. production_level: DEFERRED / NOT INCLUDED.
Complete means exact validated coverage, including evidence, liveness, same-run provenance and budgets; it does not require qualification. Complete=true with qualified_for_planning=false is expected.
Rollovers: 0. qualified_for_planning: false.
Fresh-world seeded-history ambiguity remains; later planning qualification requires a separate two-rollover phase. Collection is NON-ATOMIC and PRE-DECISION with autonomous/external snapshot-drift risk. No P08 adaptation, optimizer, evaluation telemetry or gameplay mutation.

## Evidence

Structural evidence reuses its established contracts without rewriting historical events.
GameScript per production record: BRIDGE_REQUEST_RECEIVED → INDUSTRY_PRODUCTION_READ → BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE.
Python per record: INDUSTRY_PRODUCTION_REQUEST_SENT → INDUSTRY_PRODUCTION_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → PRODUCTION_RECORD_VALIDATED. Receipt alone cannot pass semantics.
Combined semantic layer: COMBINED_SESSION_STARTED → STRUCTURAL_WORLD_VERIFIED → PRODUCTION_TARGET_SET_FINALIZED → COMPLETE_PRODUCTION_COVERAGE_VALIDATED → RAW_PRODUCTION_OBSERVATION_ASSEMBLED / INDUSTRY_PRODUCTION_OBSERVATION_ASSEMBLED → PRODUCTION_QUALIFICATION_EVALUATED(false) → COMBINED_OBSERVATION_VERIFIED → COMBINED_SESSION_COMPLETED. Runtime semantic session completion is separately classified from final lifecycle acceptance. Partial-order correlation is used, without a cross-process global timestamp requirement.
Canonical request/response bytes, digests, receipts, metrics and per-request GameScript/Python evidence are retained in transaction records.

## Cleanup ownership

Shared repaired ownership implementation reused; no combined-specific ownership model.
IMMUTABLE_SOURCE and PROTECTED_HISTORICAL survive cleanup and are rehashed after disposal.
RUNTIME_EPHEMERAL copies may be deleted while canonical origins/content identities remain frozen.
RUNTIME_CREDENTIAL must be removed at execution cleanup; private bytes are excluded from public evidence.
GENERATED_EVIDENCE is retained outside cleanup roots.
No persistent/protected/evidence path may overlap or alias into an owned cleanup root. Ownership and materialization checks passed at guarded preflight.

## Proof identity and freeze

Proof kind: complete-raw-production.
Attempt ID: complete-raw-production-v1-native-attempt1.
Predecessors: NONE for this distinct proof kind; industry-production Attempt 1/2 are supporting history only. Hardened lineage validates native-launch-based attempt numbering and newer-freeze rules for any future post-launch failure. No prelaunch continuation exception was used.
Fresh explicit runtime authorization required: YES.
Freeze directory: artifacts/runtime/openttd-15.3-complete-raw-production-real-prelaunch/.
Revision: 1.
Baseline HEAD: 278a3792b34fdb58085aff4e999dabac482cf21a.
Persistent source/input count: 215.
Protected public count: 1258.
Archived credential identities: 7.
Protected manifest digest: e59a2dd815c22ba33de33c9386a2e0cb145703b14c9e05a1f306c7e6880be3d5.
Lineage digest: 89ce3e7ed931d73983704180ec04377f0e515b05e13dccb313e8f04f83eb0395.
Bridge digest: cee002001d0a7a69c899e94c5c2cf77893a507e69686f4ac2e6d71effe94c58a.
Proof-config digest: 1fe8a3c438a6028c3797ac689f01007cb38fd69971f20c1184d54461ef80821b.
Accounting digest: b5d1e393de31069002940a662e42364c44861aa68898affd179b03d8e813422c.
Economy-authority digest: ef04ff341ee6a87fcbdc8f703a88fd3273f1f00017af484f44468a10b54159dc.
Initial inventory-request digest: 21d755070577fbd11f46a57f799800d40d9ff540cb2c109024fd7dfa68bb7644.
Future destination: artifacts/runtime/openttd-15.3-complete-raw-production-real-attempt1/.
Actual target set is deliberately generated/frozen in memory after future same-run structural assembly; it is not derived from retained historical structural data.
One fresh credential prepared after non-credential inputs were validated; mode 0600; not reused from earlier proofs. Its private path is ephemeral and excluded from persistent identities/public evidence. All 215 frozen input hashes and the freeze manifest were rechecked after guarded preflight.

## Guarded preflight

Public CLI: PASS.
Freeze, economy authority, combined lifecycle, accounting, ownership, phase barriers, target derivation and all independent/combined bounds: loaded and validated.
OpenTTD binary, OpenGFX, GameScript package, secure X25519/loopback configuration, fresh credential metadata, historical identities, lineage, exact destination and EndpointReservation.allocate(): validated.
READY_TO_LAUNCH: YES.
Final subprocess boundary: reached.
Subprocess created: NO.
Admin connected: NO.
Request sent: NO.
Future attempt destination exists: NO.
No native execution was authorized or performed.

## Claim boundaries

Complete raw production: PREPARED ONLY.
Real combined execution: NOT YET PROVEN.
Qualified history: NOT PROVEN.
Same-run structural/production: NOT YET PROVEN REAL.
Independent source: NONE.
P08 completion: NO.

## Historical integrity

Pre-existing identities recorded: 1724. Exact unchanged identities: 1715; the other nine are the intended current source/current preparation-document edits. Missing files: 0. Unexpected changes: 0.
All 1364 recorded historical artifact/fixture identities are exact. The freeze separately protects 1258 public historical identities, validates seven archived credential identities and retains the controlled verification record created before freezing.
Attempt 1: immutable FAILED post-launch history; no relabeling, restoration or retry.
Attempt 2: immutable PASS single-native query history.
Production V2/V3 freezes, structural/cargo/catalog/enrichment/inventory proofs, cleanup verification, controlled recovery and earlier incomplete preparation verification: unchanged.
CONTEXT.md: unchanged (SHA-256 b94b96649b466e73e25c9df9409bd745e311b84273bedfd9a111792869e3b7b3).
Unrelated local files, including tests/test_preparation_lifecycle.py, tests/test_preparation_probe.py, ther.md, .env.example and unrelated P08/docs changes: preserved.

## Tests

Combined preparation: 46 passed.
Frame accounting: 18 passed.
Coverage: 62 passed.
Controlled production: 81 passed, including qualification regressions.
Production proof: 59 passed.
Cleanup ownership: 33 passed; combined final-success/cleanup regressions included in preparation tests.
Structural: 117 passed.
Catalog: 162 passed.
Capability/enrichment: 159 passed.
Inventory/page: 218 passed.
Bridge/protocol/transport: 383 passed.
Secure Admin: 62 passed.
Lineage: 41 existing regressions plus new combined lineage tests passed.
Causality: 28 passed. Public CLI: 5 existing plus combined CLI tests passed. External runtime controlled: 28 passed.
Focused total: 1532 passed, 0 failed, 145.10 seconds.
Isolated live runner: 105 passed, 0 failed, 26.23 seconds.
P03/P04/P05/P06/P07/P08 ordinary controlled regressions: PASS; no native P05-P08 execution.
Final serial ordinary suite: 2416 passed, 38 skipped, 0 failed, 209.62 seconds. No concurrent verification activity.
Previous timeout-sensitive runner contention did not recur; no unrelated timeout constants changed.

## Quality

Ruff: PASS (all checks).
Format: PASS (310 files).
Applicable typecheck: PASS (proof package, production/combined sessions and new controlled tests).
Git diff --check: PASS.
Whitespace audit: PASS for task files and exact tagged reference files.
Import-boundary audit: PASS; no planning/evaluation/optimizer/telemetry dependency in the combined query/proof layer.
Test adequacy and code review gates: PASS; see the immutable final-controlled-verification/review.md.

## Runtime activity and Git

OpenTTD launches: 0.
Live Admin connections: 0.
Real application requests: 0.
Gameplay mutations: 0.
HEAD: 278a3792b34fdb58085aff4e999dabac482cf21a. Staged: NONE. Commit: NO. Push: NO.
No native attempt was created; no month rollover was waited for.

## Remaining blockers

None for preparation. The future real combined run requires fresh explicit authorization against this exact immutable freeze.

## Status

READY TO REQUEST AUTHORIZATION FOR ONE OPENTTD 15.3 REAL SAME-RUN COMPLETE RAW PRODUCTION PROOF
