# Structural-world production proof preparation

The public `python -m app.simulation.openttd.proof` CLI supports dedicated
`prepare --mode structural-world`, `preflight --mode structural-world`, and a
separately authorized future `run --mode structural-world`. Preparation and guarded
preflight create no native process, live connection, or application request.

`StructuralProductionRunner` owns one process and continuous secure connection.
It collects complete inventory, capability for precisely that inventory, then the
complete cargo catalog. Each complete semantic digest is a barrier before the next
phase. Referential validation and immutable structural assembly follow catalog
completion. Missing referenced cargo fails; shared or unreferenced catalog cargo
is valid. Historical separate-run observations cannot provide same-run inputs.

The secure session's single frame observer accounts outgoing admitted plaintext
frames and every decrypted incoming frame, including buffered surplus packets.
Authentication through ENABLE_ENCRYPTION is excluded. Encrypted PROTOCOL and
WELCOME consume two establishment frames, explicit subscription UPDATE_FREQUENCY,
PING and PONG consume three setup frames, and graceful QUIT consumes one cleanup
frame. Query traffic, including unexpected decoded packets, consumes the active
phase budget. Duplicates are neither free nor valid proof substitutes. Liveness
comes from canonical GameScript log evidence and needs no additional query.

Inventory and capability each permit 256 query operations; catalog permits 512.
The query ceiling is 1024 and total post-auth frame ceiling is 1030, exactly
1024 + 2 + 3 + 1. The overhead allowance cannot admit extra query work. Counters
persist through phases and cleanup; over-budget admission fails before another
application request. A send is recorded as SENT only after secure send succeeds;
rejected admission is NOT_SENT, and ambiguous transport failure is terminal.

The session also permits at most 96 application requests and 49152 response bytes,
derived from three phase ceilings of 32 requests and 16384 bytes. Inventory and
catalog proof page sizes are two. No retry, reconnect or resume is allowed.

Public preflight constructs the production runner, validates the exact frozen
configuration and lineage, reserves loopback endpoints, and reaches the shared
read-only launch gate. An audit guard blocks subprocess creation and socket
connection. The exact future destination is
`artifacts/runtime/openttd-15.3-structural-world-real-attempt1/`.

The semantic digest remains the controlled composition of stable world identity
and component digests, independent of requests, pagination and evidence paths.
This is a non-atomic stable-world observation: external or autonomous changes can
violate snapshot consistency. No epoch or lock is invented. Independent inventory,
capability and catalog sources remain NONE; SERVER_WELCOME supports map bounds
only. Production history is excluded and P08 adaptation remains deferred.

Failure retains transactions and truthfully completed components. Failed final
retention cannot leave a complete structural session or a premature structural
digest. Historical evidence remains immutable. Structural-world attempt lineage
is distinct from the other proof kinds; unknown relevant failures reject the gate.
