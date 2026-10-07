# Same-run structural world observation — controlled V1

Checkpoint baseline: `ee2c4c6f01f6cd0dc6e4f74fe61df233728dc8b5`.

`StructuralWorldSession` collects a complete industry inventory, one structural
capability result for each observed industry, and the complete active cargo catalog.
`StructuralWorldObservation` references the three immutable observations rather than
copying their records. It is a Python query-layer model, not a prepared planning world.
This combined session has controlled coverage only; its real execution is not yet proven.

## Same-run provenance

Existing `RuntimeIdentity` identifies the executable/version/backend. Identical binary
hashes do not identify a process or connection. `StructuralWorldContext` therefore
also requires opaque owned process and connection handles, the existing
`IndustryInventoryWorld` context, bridge identity, and a SHA-256 digest of stable
runtime configuration/content. Handle identity is checked with `is`; the transport
owner must expose the same context and continuous secure session throughout collection.
None of these handles is a new native epoch or snapshot/version clock.

A future runtime owner must derive configuration identity from stable settings/content,
excluding private credentials, ephemeral endpoints, workspace paths and logs. This slice
requires that identity but does not implement a native owner, credential generator,
production proof mode or freeze. The context is caller-supplied provenance, not an
independent runtime attestation. Controlled streams supply equivalent synthetic context.

`ScopedObservation` retains the context captured by the collecting owner. Assembly
requires identical process and connection ownership, complete typed observations,
matching runtime and world/map contexts, configuration and bridge hashes, and matching
internal catalog runtime/world provenance. Capability source inventory identity must
match the supplied inventory, with exact industry coverage. Merely sharing a runtime
binary, world ID or deterministic configuration cannot join separate runs.

`IndustryInventoryWorld.from_welcome` remains the map-context construction interface:
SERVER_WELCOME supplies coordinate bounds from the authenticated connection. No additional
world_info request is sent by this coordinator. Its world ID is caller provenance, not a
native snapshot version. `PreparedWorldManifest.world_fingerprint` belongs to planning
preparation and is not imported or repurposed here. No second competing world fingerprint
is introduced; the structural digest identifies semantic observation content.

## Ordered collection and completion

The public collection interface accepts the existing typed query transport plus the
three per-command GameScript evidence readers. Python alone owns these phases:

1. A: bounded inventory pagination until its validated terminal page and inventory digest.
2. B: capability queries in ascending same-run industry ID order; exactly once per industry.
3. C: complete cargo pagination after the capability observation has completed.
4. D: referential validation, structural assembly and verification.

No pipelining is allowed. The coordinator checks ownership before and after every query,
at each evidence reader, and at phase transitions. Missing liveness, timeout, disconnect,
replacement or transport ambiguity fails the entire session. There is no reconnect,
retry or resume; sessions are single-use after either success or failure. Phase readers
retain their existing receipts and per-command validation chains unchanged.

The default deterministic session identity is `openttd15-structural-world-001`.
Child IDs use existing derivation functions:

- Inventory: `openttd15-structural-world-001-inv-p001`, `...-p002`, etc.
- Capability: `openttd15-structural-world-001-cap-i00002`, etc., from observed industry IDs.
- Catalog: `openttd15-structural-world-001-cat-p001`, `...-p002`, etc.

Both paginated phases use page size 2. The generic protocol maxima are unchanged.
No historical industry or cargo set is hard-coded.

Invalid or partial assembly raises a validation failure. A complete structural model
can only be constructed from validated terminal component observations. Failed sessions
retain received exchanges and any completed components; their evidence has complete=false,
no structural digest and an explicit failure. This avoids claiming that completed
individual components constitute a completed world when the join fails.

An empty inventory is valid, leading to zero capability requests and an empty complete
capability observation. Catalog collection still runs. Generic empty catalogs are
permitted when no capability references require cargoes.

## Cargo referential integrity

Every produces and accepts cargo ID must exist exactly once in the complete catalog.
Catalog uniqueness is validated by the existing typed record/page/catalog contracts.
Missing referenced cargo fails assembly; metadata is never fabricated and relationships
are never discarded. Multiple industries may share cargoes and the same cargo may occur
in both produces and accepts. Active catalog cargoes need not be referenced by any
industry: passengers, mail or other unreferenced cargoes are still valid catalog entries.

This validates existence and supplies structural metadata. It does not independently
validate an industry-to-cargo relationship. Cargo labels remain identity metadata;
generic cargo properties should guide future planning when applicable. No localized
name or dynamic production/economic data is introduced. The existing V1 normalized
cargo-class mask remains part of the catalog schema and digest unchanged.

## Finite bounds and accounting

| Phase | Requests/pages | Records | Response bytes | Query Admin operations |
|---|---:|---:|---:|---:|
| Inventory | 32 | 32 industries | 32 × 512 = 16384 | 32 × 8 = 256 |
| Capability | 32 | 32 industries | 32 × 512 = 16384 | 32 × 8 = 256 |
| Catalog | 32 | 64 cargoes | 32 × 512 = 16384 | 32 × 16 = 512 |
| Combined | **96** | Separate phase bounds | **49152** | **1024** |

These are ceilings, not targets. The inventory retains its proven 32-page ceiling;
minimum page occupancy is not assumed to tighten it. Catalog page size 2 spans at most
32 pages in the 64-ID cargo space. The application payload maximum remains 512 bytes,
and the native GSAdmin.Send ceiling remains 1450 bytes.

The combined wrapper records request_attempts before send; this conservative budget
counter does not claim an application packet was sent when transport fails before writing. It clamps each query's operation budget
to remaining allowance (at most 16), and accounts every returned exchange immediately,
even if later semantic or GameScript validation fails. Each existing phase independently
enforces its own limits. Exactly-at-budget completion is allowed; exhaustion prevents
further sends. Authentication and unobserved owner-side setup/control frames are outside
the existing exchange accounting. A future real proof must additionally apply the owned
post-auth frame recorder to all setup/query/control traffic; this controlled coordinator
does not claim native post-auth telemetry that it cannot observe.

## Canonical structural digest

Canonical ASCII JSON composes:

- schema `structural-world-v1`;
- runtime version, executable SHA-256 and backend, excluding executable path;
- map width and height;
- stable configuration digest and bridge digest;
- inventory semantic digest;
- capability semantic digest;
- cargo catalog semantic digest (including its already-established class mask).

The component contracts are revalidated before their digests are composed. Exact
provenance relationships are exposed as `inventory_digest`, `source_inventory_digest`,
`capability_digest` and `cargo_catalog_digest`. No blindly supplied digest string can
substitute for a component observation. The structural SHA-256 excludes request IDs,
page/packet boundaries, timestamps, logs, evidence paths, process IDs, memory addresses,
opaque ownership tokens and caller world/session IDs. Identical semantic content hashes
identically with different pagination, request IDs or transient paths.

## Evidence and claim boundary

Per-command GameScript and Python evidence remains unchanged. The Python structural chain is:

```text
STRUCTURAL_WORLD_SESSION_STARTED
INDUSTRY_INVENTORY_COMPLETED
INDUSTRY_CAPABILITY_COMPLETED
CARGO_CATALOG_COMPLETED
REFERENTIAL_INTEGRITY_VALIDATED
STRUCTURAL_WORLD_ASSEMBLED
STRUCTURAL_WORLD_VERIFIED
STRUCTURAL_WORLD_SESSION_COMPLETED
```

Failures terminate with STRUCTURAL_WORLD_SESSION_FAILED. Child observations retain ordered
request/response/receipt/evidence information. Correlation uses deterministic child IDs,
cursors, digests and receipts. Evidence uses process-local ordering and correlations;
it never imposes total timestamp order across Python and GameScript.

V1 assumes one stable world throughout collection. This project performs no gameplay
mutation, but autonomous or external industry changes during sequential collection can
violate strict snapshot consistency. These APIs do not provide an atomic snapshot, epoch
or version clock; no such guarantee is invented here.

The successful historical enrichment and cargo-catalog runs prove their individual native
query paths. They are separate processes and cannot be merged into a same-run proof.
The cargo-catalog checkpoint fixture reproduces its exact six-page/11-record digest;
regressions reject assembly with the independently valid V4 enrichment fixture.

- Same-run structural observation: CONTROLLED ONLY.
- Real combined execution: NOT YET PROVEN.
- Independent inventory/capability/catalog verification: NONE.
- Production history: NOT INCLUDED.
- P08 completion: NO.

No construction, vehicles, orders, terraform, finance, industry mutation or gameplay RCON
is performed. This slice introduces no native APIs, GameScript changes, dynamic queries,
CLI proof execution mode, or planning-domain imports. A future adapter may consume the
validated structural observation; PreparedWorldManifest/P08 adaptation is a later task.
