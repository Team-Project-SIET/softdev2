# Structural-world production preparation

## Production lifecycle
CLI mode: `structural-world`. Runner: `StructuralProductionRunner` with `StructuralNativeBackend`.
Endpoint ownership: `EndpointReservation.allocate()`; reservations released during guarded preflight.
States: PREPARED → LAUNCHED → ADMIN_ACTIVE → STRUCTURAL_SESSION_STARTED → INDUSTRY_INVENTORY_STARTED → INDUSTRY_INVENTORY_COMPLETED → INDUSTRY_CAPABILITY_STARTED → INDUSTRY_CAPABILITY_COMPLETED → CARGO_CATALOG_STARTED → CARGO_CATALOG_COMPLETED → REFERENTIAL_INTEGRITY_VALIDATED → STRUCTURAL_WORLD_ASSEMBLED → STRUCTURAL_WORLD_VERIFIED → COMPLETED. FAILED is terminal. Transactions retain repeated request evidence.

## Native frame accounting
Shared authority: `SecureAdminSession` frame observer → `StructuralFrameBudget`.
Post-auth boundary: after ENABLE_ENCRYPTION; encrypted SERVER_PROTOCOL and SERVER_WELCOME are counted.
Both outgoing admitted frames and decoded incoming frames count once. Buffered surplus and duplicate/unexpected frames count and fail validation; partial buffered traffic fails the completion barrier.
Query operations include request, response, ADMIN_PING, SERVER_PONG and other decoded traffic consumed in the active phase.
Non-query categories: establishment 2; explicit UPDATE_FREQUENCY/PING/PONG setup 3; graceful QUIT 1. Overhead: 6.
Query ceiling: 1024. Total post-auth ceiling: 1030 = 1024 + 2 + 3 + 1.
Either overrun immediately fails. Query work cannot borrow overhead. Counters never reset between phases; cleanup retains totals. Admission rejection is NOT_SENT; transport ambiguity is terminal.

## Combined bounds
Inventory: 32 requests/pages, 32 records, 16384 response bytes, 256 query operations.
Capability: 32 requests/records, 16384 response bytes, 256 query operations.
Catalog: 32 requests/pages, 64 records, 16384 response bytes, 512 query operations.
Combined: 96 application requests; 49152 response bytes; 1024 query operations; 1030 total post-auth frames. Proof page sizes: 2.

## Structural phase barriers
Session: `openttd15-structural-world-001`.
Inventory complete + finalized digest precedes capability; capability complete + finalized digest precedes catalog; catalog complete + finalized digest precedes assembly. No pipelining.

## Connection semantics
One owned process; one continuous secure connection. Process/runtime/connection/configuration/bridge identity must remain equal. Replacement fails the entire session.
Retry: 0. Reconnect: 0. Resume: prohibited. Counter continuity is preserved across all phases and cleanup.

## Structural assembly
Existing immutable `StructuralWorldObservation` and component models reused without digest redesign.
Exact inventory/capability/catalog digest provenance and capability industry coverage are required.
Every produced/accepted cargo must exist exactly once; missing cargo fails, shared and extra catalog cargo are valid.
Complete requires all phase observations, identities, provenance, evidence and budgets valid. Failed retention normalizes session/world completion to false and removes premature structural digest artifacts; completed components remain truthful.
Stable semantic component digests and world identity compose the structural digest, independent of requests and pagination.
No planning/P08 transport imports, production history or gameplay mutation. Non-atomic stable-world assumption remains: external/autonomous changes may violate strict snapshot consistency. No epoch or lock added.
Independent inventory/capability/catalog sources: NONE. SERVER_WELCOME supports map bounds only. P08 completion: NO. Real combined execution: NOT YET PROVEN.

## Proof identity
Proof kind: structural-world. Attempt ID: structural-world-v1-native-attempt1.
Predecessors: none. Unknown relevant structural-world failures reject preflight; unrelated proof-kind failures are not predecessors. Fresh authorization remains required.
Runtime destination: /home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-structural-world-real-attempt1 (absent).

## Freeze
Directory: artifacts/runtime/openttd-15.3-structural-world-real-prelaunch.
Baseline HEAD: ee2c4c6f01f6cd0dc6e4f74fe61df233728dc8b5.
Source/input count: 158.
Protected public files: 914.
Archived credential identities: 6.
Protected manifest digest: fb9fef3bac447d7d01746416286a9360ce15527cd7b0106170e8acc10de70633.
Lineage digest: 9330ff721b352e60a4a1154c44b7c3ce9cb164f99e1425c6476013662b2f7fe1.
Bridge digest: 7b45783b37ed93a481a58a2d768b4c490c8fad35a55db459a82cb0ddeaa84981 (unchanged).
Proof/session-config digest: ebec219ab46f0ffb564b58d3696c98a1cfa0d0c03df4c4060a82965f13b57e4d.
Frame-accounting identity: 83fa880662a2a0ceae0146a101b3d5cb7e6833e0696cf0e4a46aedf3f255b35f.
Fresh credential: mode 0600; private bytes excluded from public freeze evidence. Isolated future workspace is private preparation data.

## Guarded preflight
Public CLI: `python -m app.simulation.openttd.proof preflight --mode structural-world`.
Production runner, shared accounting, phase bounds, freeze, lineage, destination and endpoint reservation validated.
READY_TO_LAUNCH: YES. Subprocess created: NO. Admin connected: NO. Request sent: NO.

## Historical integrity
920 baseline hashes exact, including structural controlled report, frame audit, all previous proofs/freezes/failures and CONTEXT.md.
Historical files modified: NO. HEAD unchanged. No commit or push.

## Tests
Production preparation: 36 passed. Frame budget: 16 passed. Structural: 65 passed.
Catalog, capability/enrichment, inventory, industry, world-info, bridge/protocol/transport, secure Admin, lineage/evidence, production CLI, external runtime, P04 and P03/P05/P06/P07/P08 regressions included in ordinary suite.
Ordinary: 2117 passed, 38 skipped. Final focused rerun: 117 passed.
Spec and Standards reviews: no remaining blockers.

## Quality
Ruff: passed. Format: passed. Scoped OpenTTD/model/proof typecheck: passed.
Diff check, changed-file whitespace audit and structural query-layer planning-import audit: passed.
Known unrelated planning diagnostics were not changed.

## Runtime activity
Gameplay launches: 0. Live Admin connections: 0. Real requests: 0.

## Remaining blockers
None for requesting authorization. Fresh explicit authorization against this exact freeze is required before native execution.

## Status
READY TO REQUEST AUTHORIZATION FOR ONE OPENTTD 15.3 REAL SAME-RUN STRUCTURAL-WORLD PROOF
