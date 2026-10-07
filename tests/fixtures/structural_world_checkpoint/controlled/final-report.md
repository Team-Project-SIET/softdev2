# Same-run structural world — controlled implementation

## Checkpoint baseline

HEAD: `ee2c4c6f01f6cd0dc6e4f74fe61df233728dc8b5` (unchanged).
Working tree before task: three unrelated modified documentation files (README.md,
planning-executor-boundary.md, srs.md), untracked P08 implementation/tests/documentation,
CONTEXT.md and .env.example. All preserved; index remains empty. No commit or push.

## Structural session

Session ID: `openttd15-structural-world-001`.
Phase order: complete inventory and finalized digest → complete per-industry capability
→ complete catalog → referential validation/structural assembly.
Continuous connection: required, with matching opaque process/connection owner identities.
Retries: 0. Reconnects: 0. Resume: prohibited; single-use after success or failure.

## Combined bounds

| Phase | Requests/pages | Records | Response bytes | Admin query operations |
|---|---:|---:|---:|---:|
| Inventory | 32 | 32 industries | 16384 | 256 |
| Capability | 32 | 32 industries | 16384 | 256 |
| Catalog | 32 | 64 cargoes | 16384 | 512 |
| Combined | **96** | Separate ceilings | **49152** | **1024** |

Derivation: 32+32+32 requests; 96×512 response bytes; 256+256+512 existing phase
operation ceilings. Inventory/catalog page size: 2. Existing generic maxima unchanged.
Attempts counted before send; returned exchange bytes/frames counted immediately, including
later validation failures. Existing phase limits apply independently. The session uses
exchange query-operation accounting; future native proof must also count owner-side
post-auth setup/control frames with its native recorder. No unobserved frame count is claimed.

## Models

Inventory: existing IndustryInventoryObservation. Capability: existing
IndustryCapabilityObservation. Catalog: existing CargoCatalogObservation.
Structural world: new frozen StructuralWorldObservation referencing immutable scoped sources,
with runtime/map identity, ordered industry/cargo IDs, counts, complete flag and component digests.
StructuralWorldContext adds explicit owned-process/connection provenance and stable
configuration identity without inventing native epochs or a competing world fingerprint.
P08 coupling: NONE; no planning-domain imports, PreparedWorldManifest adaptation or native runner.

## Referential integrity

Every produced and accepted cargo must exist exactly once in the validated complete catalog.
Missing cargo: explicit failure. Extra catalog cargo: valid. Shared cargo: valid.
Empty industry inventory: valid; zero capability requests; catalog still collected.
No source records or digests are mutated or silently dropped; no metadata is fabricated.

## Provenance

Runtime identity: exact across contexts and internal observations. Process/connection ownership:
object identity equality, checked before/after queries, evidence readers and phase transitions.
World/map identity: existing IndustryInventoryWorld and SERVER_WELCOME coordinate context,
matching runtime, dimensions, world ID, stable configuration digest and bridge identity.
Capability nested source inventory is complete and revalidated. Its digest matches inventory.
Structural inventory/capability/catalog digests are computed from revalidated component
observations. Exact source industry coverage and catalog references are checked.
Cross-run rejection: individually valid historical V4 enrichment and real catalog fixtures
remain distinct owned runs and cannot form a complete structural observation.

## Structural digest

Canonical schema identifier, runtime version/SHA-256/backend, map width/height,
stable configuration digest, bridge digest, inventory digest, capability digest and
catalog digest. Existing normalized cargo classes remain inside the catalog's established digest.
Pagination independence: PASS. Request-ID independence: PASS. Transient-path independence: PASS.
No timestamps, request/page/packet IDs, logs, paths, process IDs or ownership tokens included.
Caller world/session IDs are provenance, not semantic snapshot versions.

## Evidence

Industry: existing request/industry-page-read/send/post-response-liveness GameScript chain
and Python request/response/receipt/page validation.
Capability: existing request/industry-cargo-read/send/post-response-liveness GameScript chain
and Python request/response/receipt/capability validation.
Catalog: existing request/cargo-page-read/send/post-response-liveness GameScript chain
and Python request/response/receipt/cargo-page validation.

Structural Python session chain:
STRUCTURAL_WORLD_SESSION_STARTED → INDUSTRY_INVENTORY_COMPLETED →
INDUSTRY_CAPABILITY_COMPLETED → CARGO_CATALOG_COMPLETED →
REFERENTIAL_INTEGRITY_VALIDATED → STRUCTURAL_WORLD_ASSEMBLED →
STRUCTURAL_WORLD_VERIFIED → STRUCTURAL_WORLD_SESSION_COMPLETED.
Failures: STRUCTURAL_WORLD_SESSION_FAILED, complete=false, no structural digest;
completed components and received exchanges remain available.
Partial-order rule: process-local sequences plus correlations; no global cross-process timestamps.

## Semantics

Structural state only: industries, structural produces/accepts and active cargo metadata.
Dynamic state: excluded; no production/transport quantities, stockpiles, income or finance.
Stable-world assumption: one unchanged runtime/configuration throughout sequential phases.
Snapshot limitation: external/autonomous industry changes can violate strict consistency;
no atomic snapshot, epoch or version clock is claimed. Caller provenance is not a native attestation.

## Mutation safety

Construction, vehicles, orders, terraform, finance, industry mutation and gameplay RCON: NONE.
P05/P06 execution, P07 evaluation and P08 extraction: NONE. GameScript bridge unchanged.

## Verification claim

Same-run structural observation: CONTROLLED ONLY.
Real combined execution: NOT YET PROVEN.
Independent inventory verification: NONE.
Independent capability verification: NONE.
Independent catalog verification: NONE.
Production history: NOT INCLUDED.
P08 completion: NO.

## Historical integrity

V4 enrichment: unchanged. Cargo catalog: unchanged. Earlier proofs, freezes,
preparation/failure/lineage and archived credentials: unchanged. CONTEXT.md: unchanged.
All 898 pre-task historical snapshot file hashes exact; checkpoint HEAD unchanged.
New catalog regression fixture is a byte-identical public subset, with its own SHA-256 manifest.
No old report, proof or freeze was edited.

## Tests

Structural world: **65 passed**.
Catalog: existing 79 tests covered.
Cargo-page/complete-catalog proofs, capability/enrichment, inventory, industry-page,
world-info, bridge/protocol/transport, secure Admin, attempt lineage, evidence/causality,
production CLI, external runtime and P04: PASS in final ordinary suite.
P03/P05/P06/P07/P08 controlled suites: PASS in final ordinary suite.
Ordinary: **2065 passed, 38 skipped in 147.98s (0:02:27)**.

Earlier full results retained: one existing controlled save-parser finalization failure
(2062 passed, 38 skipped), then a different noisy-stdio runner finalization failure
(2063 passed, 38 skipped). The first failed test passed in isolation. A runner-module
recheck had three strict startup-timing failures (102 passed); all four isolated startup
cases then passed without changes. The final full run passes all tests on the final source.
The earlier intermittent failures are not claimed fixed; no unrelated runner code or
timeout was changed. Request budget evidence uses request_attempts, distinguishing a
pre-send transport failure from an actual wire request. Final full suite is authoritative.
No native opt-in tests were enabled and no native smoke test was performed.

## Review

Standards: PASS, no findings. Spec: PASS, no findings. Both independently re-reviewed
the nested capability-source inventory completeness/revalidation hardening.

## Quality

Ruff: PASS. Format: PASS (260 files already formatted). Applicable OpenTTD and cargo/structural test
typecheck: PASS. Git diff --check: PASS. Source whitespace audit: PASS. Import-boundary
and dynamic/mutation API audits: PASS. Unrelated local planning work remains untouched.

## Runtime activity

Gameplay launches: **0**. Live Admin connections: **0**. Real application requests: **0**.
No commit. No push.

## Status

READY FOR SAME-RUN STRUCTURAL-WORLD REAL-PROOF PREPARATION
