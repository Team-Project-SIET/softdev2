# OPENTTD 15.3 REAL SAME-RUN STRUCTURAL-WORLD PROOF PASSED — READY FOR CHECKPOINT COMMIT

Authorized public invocation: `python -m app.simulation.openttd.proof run --mode structural-world --authorize-one-launch`.
Frozen preparation: `artifacts/runtime/openttd-15.3-structural-world-real-prelaunch/PRELAUNCH.json`.
Baseline HEAD: `ee2c4c6f01f6cd0dc6e4f74fe61df233728dc8b5` (unchanged).
Attempt: `structural-world-v1-native-attempt1`. Runtime destination: `/home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-structural-world-real-attempt1`.
No source/freeze repair, retry, alternate runner, destination override, commit or push performed.

## Real execution
Exactly one owned OpenTTD 15.3 launch and one continuous X25519 secure Admin connection.
Exactly 21 application requests: 5 industry_page, 10 industry_cargo, 6 cargo_page.
Inventory: 10 industries, complete. Capability: 10 validated results, complete.
Catalog: 11 cargo records across 6 pages, complete. Proof page sizes: 2.
Request targets and cursor continuations came from same-run results; historical counts were not inputs.
Both pagination chains terminate with has_more=false and next_after_id=null.
No missing, extra or duplicated capability industry; no missing referenced cargo.
Same process, connection, runtime, configuration, map and bridge provenance validated.
Inventory/capability/catalog digest provenance exact. StructuralWorldObservation complete=true.
Structural-world digest: `060fb6368d2f73deaf3081ec14c9081b4cad4c70541981fe9199131afbc7ac11`.

## Evidence and limits
All 21 transactions replay-validated through frozen typed response and GameScript evidence validators.
Every request/response digest matches its receipt. Per-page cursor metadata, ordering, correlation, response-send and post-response liveness passed.
Python lifecycle and child evidence retained; partial-order semantics used without cross-process total timestamp ordering.
Cumulative response bytes: 4611 / 49152. Every response satisfies 512-byte application and 1450-byte native limits.
Shared native accounting: inventory20 + capability40 + catalog24 = 84 / 1024 query operations.
Total post-auth frames: establishment2 + setup3 + query84 + cleanup1 = 90 / 1030.
Counters remain continuous; phase ceilings remain unchanged. Six overhead frames were not query capacity.
Retries=0, reconnects=0, replacements=0, ambiguous requests=0.

## Cleanup and integrity
Graceful Admin close and process shutdown/reap passed; return code0.
Remaining OpenTTD processes=0. Loopback endpoints closed. Runtime private credential removed.
All 158 frozen source/input hashes exact; protected unique path set and all914 public hashes exact.
All6 archived credential identities exact. Frozen manifests/digests and prior proof evidence unchanged.
CONTEXT.md unchanged. Runtime artifact manifest validates. Original retained proof evidence was not rewritten by post-run verification.

## Verification
Ordinary suite: 2117 passed, 38 skipped, including structural production, frame-budget, structural-world, catalog, cargo-page, enrichment/capability, inventory, industry-page, world-info, bridge/protocol/transport, secure Admin, lineage/evidence, CLI/external runtime and P03/P04/P05/P06/P07/P08 regressions.
Ruff, format, scoped applicable OpenTTD typecheck, git diff --check, changed-file whitespace and structural-layer planning-import audit passed.
No second native smoke test performed.

## Claim boundaries
Read-only structural state only. Gameplay mutations=0; no script crash or protocol error observed.
Independent inventory source=NONE. Independent capability source=NONE. Independent catalog source=NONE.
SERVER_WELCOME supports map bounds only. Referential validation establishes referenced cargo membership, not independent industry relationship truth.
Non-atomic stable-world assumption remains; no snapshot epoch, version clock or external/autonomous change lock.
Production history=NOT INCLUDED. P08 completion=NO. No world-preparation adapter executed.

## Status
OPENTTD 15.3 REAL SAME-RUN STRUCTURAL-WORLD PROOF PASSED — READY FOR CHECKPOINT COMMIT
