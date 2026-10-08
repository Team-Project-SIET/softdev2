# Real same-run complete raw industry-production proof

## Runtime

HEAD: 278a3792b34fdb58085aff4e999dabac482cf21a. Public entry point: python -m app.simulation.openttd.proof run --mode complete-raw-production --authorize-one-launch.
Freeze revision 1; attempt ID complete-raw-production-v1-native-attempt1.
Runtime destination: artifacts/runtime/openttd-15.3-complete-raw-production-real-attempt1/.
Launches: 1. Secure Admin connections: 1. Retries: 0. Reconnects: 0. Resume: NO.
Owned process PID: 4; same owned process across all phases. Connection continuity: YES, one encrypted X25519 AuthorizedKey / Protocol 3 session throughout A–E. No alternate CLI mode, wrapper or manual Admin client.

## Structural

Industries: 10 (IDs 0–9). Inventory pages: 5. Capability records: 10. Cargo catalog records: 11 (IDs 0–10), in 6 pages.
Inventory, capability and cargo catalog: complete, with finalized digests before subsequent phases. StructuralWorldObservation.complete: true.
Structural digest: 74e7e10c28c1fcc1461d57a15eddc88cced96ea7c9a11e7a778b9ea1c54d2ce5.
Phase order: inventory → capability → catalog → structural assembly → immutable produced targets → production.

## Production

Targets: 10. Records: 10. Requests: 10. Response bytes: 2957. Every same-run produced pair queried exactly once; no accepted-only/catalog-only, missing, duplicate or extra pair.
Production digest: f6486ab4c282e407cbe1f729baafa230308d975b140e761b03ce1f017ba17c30.
Complete: true. qualified_for_planning: false. production_level: DEFERRED / NOT INCLUDED.

| Industry | Cargo | Raw production | Station allocation | Transported % | Economy before | Economy after |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1 | 168 | 0 | 0 | 712223 | 712223 |
| 2 | 5 | 0 | 0 | 0 | 712223 | 712223 |
| 3 | 7 | 80 | 0 | 0 | 712223 | 712223 |
| 4 | 5 | 0 | 0 | 0 | 712223 | 712223 |
| 5 | 5 | 0 | 0 | 0 | 712223 | 712223 |
| 6 | 9 | 0 | 0 | 0 | 712223 | 712223 |
| 7 | 4 | 56 | 0 | 0 | 712223 | 712223 |
| 7 | 6 | 88 | 0 | 0 | 712223 | 712223 |
| 8 | 3 | 96 | 0 | 0 | 712223 | 712223 |
| 9 | 8 | 88 | 0 | 0 | 712223 | 712223 |


These are observed native raw values, including valid zero production. Station allocation is not vehicle pickup, delivery completion, destination receipt or post-decision throughput. Transported percentage is retained separately with its native meaning.

## Economy

Native API: ScriptDate::GetCurrentDate. Binding: GSDate.GetCurrentDate.
Initial economy month: January 1950, native ordinal interval [712223,712254).
Final observed economy month: January 1950; every production bracket is 712223 → 712223.
Month crossing: NO. Equal brackets observed: 10/10, valid current-state captures. Rollovers observed: 0.
The brackets are current economy-day metadata around metric reads, not start/end boundaries of a historical production period. No waits for days, months, wall-clock time or value changes were performed.

## Accounting

Application requests: 31 / 608 (structural 21 / 96, production 10 / 512).
Response bytes: 7715 / 220672 (structural 4758 / 49152, production 2957 / 171520).
Query operations: 124 / 5120 (structural 84 / 1024, production 40 / 4096).
Post-auth frames: 130 / 5126 = 124 query operations + 6 deterministic lifecycle frames ONCE.
Categories: establishment 2, setup 3, inventory 20, capability 40, catalog 24, production 40, cleanup 1. All frames admitted; counter failed=false. No reset/replacement or budget borrowing between phases. Phase transitions and target finalization sent no Admin frames.
All production payloads pass the audited 335-byte worst-case bound and application/native limits (512 / 1450). All structural payloads pass their 512-byte bound. Actual production payload range: 295–297 bytes.

## Provenance

Same process: YES. Same continuous Admin connection: YES. Same runtime: YES. Same world/config: YES. Same bridge: YES.
production.source_structural_world_digest equals structural digest exactly: 74e7e10c28c1fcc1461d57a15eddc88cced96ea7c9a11e7a778b9ea1c54d2ce5.
Structural source was collected within this new runtime, not attached from historical evidence. Models remain unchanged.

## Evidence

Structural evidence: PASS. Per-production Python and GameScript evidence: PASS. Combined semantic evidence: PASS. Post-response liveness: PASS for every request.
All 31 canonical responses and typed transport receipts were revalidated offline; all 31 GameScript request/read/send/alive chains passed their command-specific validators. Every production Python chain is request sent → response received → receipt created → production record validated. Transport receipt alone did not establish semantics.
Combined target finalization follows structural verification, then exact coverage, observation assembly, qualification evaluated as false, combined verification and semantic session completion. Final acceptance follows the separate cleanup lifecycle. Existing partial-order conventions are preserved.
Evidence is immutable in the exact runtime destination; this separate verification directory does not replace or rewrite it.

## Cleanup

Process reaped: YES, graceful return code 0. Remaining OpenTTD processes: 0.
Endpoints closed: YES. Credential removed: YES. Workspace disposed: YES.
Post-run source integrity: PASS. Protected historical integrity: PASS.
Final lifecycle: COMPLETED, following POSTRUN_INTEGRITY_VERIFIED. No early final PASS.
Persistent sources/history survive; only classified ephemeral runtime material and credential were removed. Generated evidence is retained. No gameplay mutation, script crash or protocol error was observed.

## Qualification

Complete raw production: PROVEN. Qualified historical production: NOT PROVEN.
qualified_for_planning=false, rollovers=0. Fresh-world seeded-history ambiguity remains, regardless of zero/non-zero returned metrics. Later two-rollover qualification requires separate design/authorization.

## Claim boundary

Same-run structural/production: PROVEN. Independent production source: NONE. P08 completion: NO. Atomic snapshot: NO.
This is NON-ATOMIC PRE-DECISION observation; autonomous/external world changes can cause snapshot drift even inside one economy month. No optimizer, P05 action, P06 execution, P07 evaluation or P08 extraction occurred.

## Historical integrity

All 215 frozen persistent source/input identities exact after execution and after regressions. All 1258 protected public identities and seven archived credential identities exact.
Protected manifest, lineage, bridge, proof configuration, accounting and economy authority identities remain exactly frozen; binary/OpenGFX/GameScript identities are included in the validated source/configuration set.
Industry-production Attempt 1 remains immutable FAILED history. Attempt 2 remains immutable PASS history. Production V2/V3 freezes, structural proof, cargo/catalog/capability/inventory proofs, cleanup verification and controlled/recovery/preparation evidence remain unchanged.
The consumed revision-1 freeze is unchanged. CONTEXT.md unchanged. No source repair, file restoration, new freeze, new credential, retry or second native attempt.

## Tests

Real-proof offline validation: PASS for all 31 retained transactions and exact target coverage.
Combined preparation/lifecycle/economy/real-runner controlled regressions: 46 passed.
Frame accounting: 18 passed. Complete coverage: 62 passed. Controlled production and qualification: 81 passed.
Production proof: 59 passed. Cleanup ownership: 33 passed, with final-success/cleanup regressions also included in the combined module.
Structural: 117 passed. Catalog: 162 passed. Capability/enrichment: 159 passed. Inventory/page: 218 passed.
Bridge/protocol/transport: 383 passed. Secure Admin: 62 passed. Existing lineage: 41 passed plus new combined lineage regressions. Public CLI, evidence/causality and external-runtime controlled regressions passed.
Focused total: 1532 passed, 0 failed, 139.75 seconds.
P03/P04/P05/P06/P07/P08 controlled regressions: PASS in ordinary suite; no additional native execution.
Final serial ordinary suite: 2416 passed, 38 skipped, 0 failed, 225.84 seconds. No concurrent final-suite verification.

## Quality

Ruff: PASS. Format: PASS (310 files). Applicable typecheck: PASS.
git diff --check: PASS. Task/reference whitespace audit: PASS. Import-boundary audit: PASS; no planning/evaluation/optimizer/telemetry leakage into query/session/proof owners.
HEAD unchanged. Staged: NONE. Commit: NO. Push: NO. Unrelated local worktree state preserved.

## Status

OPENTTD 15.3 REAL SAME-RUN COMPLETE RAW PRODUCTION PROOF PASSED — READY FOR TWO-ROLLOVER QUALIFICATION DESIGN
