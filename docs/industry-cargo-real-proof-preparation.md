# Single-industry cargo capability real-proof preparation

Baseline HEAD: `d7ee72f47149482841fcf45cd92b222664bfb3bd`. `CONTEXT.md` is the
architecture authority. Preparation performs zero gameplay launches, live Admin
connections or real application requests. Historical evidence stays immutable.

## Public production path

`python -m app.simulation.openttd.proof prepare --mode industry-cargo` prepares a
new isolated profile. `preflight --mode industry-cargo` installs audit guards for
process creation and socket connections, validates frozen inputs, loads the
validator and reserves distinct loopback endpoints via `EndpointReservation.allocate()`.
It reports READY_TO_LAUNCH and releases reservations without launching.

Only a separately authorized `run --mode industry-cargo --authorize-one-launch`
may execute the future attempt. No private object construction or external wrapper
is required. The dedicated backend owns one process and one continuous secure
Admin connection; it uses the existing isolated runtime harness and bounded cleanup.

Lifecycle: PREPARED → LAUNCHED → ADMIN_ACTIVE → INDUSTRY_CARGO_REQUEST_SENT →
INDUSTRY_CARGO_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → CAPABILITY_VALIDATED →
POST_RESPONSE_LIVENESS_VERIFIED → COMPLETED. FAILED is explicit. Native receipt
recording binds the envelope and raw bytes before capability semantic validation.
A transport receipt does not imply capability verification.

## Frozen request and response

Production canonical request, 98 bytes:

```json
{"industry_id":0,"protocol":1,"request_id":"openttd15-industry-cargo-001","type":"industry_cargo"}
```

SHA-256: `64e228cdf2a3a9b696de1d959ae34b46721518192ca3f5af67e051ecded43e63`.

Response is `industry_cargo_result`, protocol 1, exact request ID, status `ok`,
industry ID 0, and strictly ascending unique `produces`/`accepts` cargo ID arrays.
Each array permits zero to 16 entries, IDs 0–63. Cargo overlap across the two
arrays is allowed. Empty arrays do not weaken native-read evidence requirements.
No specific cargo ID or non-empty list is expected.

Each payload remains at most 512 bytes and below the native 1450-byte ceiling.
The conservative global response maximum remains 280 bytes: 232 bytes of
application headroom and 1170 bytes below the native ceiling. No schema, cargo
metadata or production-history expansion is introduced.

## Source authority and provenance

Exact OpenTTD 15.3 source copies and manifests freeze:
GSCargoList_IndustryProducing, GSCargoList_IndustryAccepting, GSList.Sort,
SORT_BY_ITEM, SORT_ASCENDING, GSIndustry.IsValidIndustry and GSCargo.IsValidCargo.
The export generator preserves underscores when replacing Script with GS.
CargoType has 64 valid IDs; industry input/output arrays each have 16 slots,
including NewGRF industries. References are in `tests/reference/industry_cargo_15_3/`
and the verified industry binding/evidence reference trees.

The producing and accepting lists describe structural capability. Accepting lists
may include cargoes temporarily not currently accepted. Transient IsCargoAccepted,
last-month production/transported values, stockpile state and cargo names/labels/classes
are excluded. Future cargo_catalog remains separate.

The successful historical complete inventory observed industry ID 0 and digest
`dce9b4d257af150776e679b09c74880b918163b86ae5e5f9f6e30e35d26c865a`.
Preparation validates its successful status, complete records, canonical digest and
matching deterministic world configuration. This supports the selected industry ID;
it does not independently specify cargo capability in a newly generated world.
The inventory proof is not rerun and no industry_page application request is sent.

## Evidence and claim

Native local chain: BRIDGE_STARTED → BRIDGE_REQUEST_RECEIVED → INDUSTRY_CARGO_READ
→ BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE. Canonical read metadata includes
industry ID, produced/accepted counts and optional first/last IDs. Null is literal
`null`; integers are canonical decimal. Native object/debug rendering is invalid.

Python local chain: INDUSTRY_CARGO_REQUEST_SENT → INDUSTRY_CARGO_RESPONSE_RECEIVED
→ TRANSPORT_RECEIPT_CREATED → CAPABILITY_VALIDATED. The immutable
IndustryCargoVerification retains identities, request/response digests, industry ID,
ID sets/counts, ordering/uniqueness/bounds/payload flags and verified status.

Correlate protocol, request ID/types, status, industry ID, counts/endpoints and the
Python retained raw response digest. No native SHA API is invented. Validate each
local chain independently, without total cross-process timestamp ordering.

Independent second-source capability: **NONE**. SERVER_WELCOME supports runtime
identity and map dimensions, not industry cargo sets. A future pass establishes real
native bindings executed and returned correlated valid structural capability; it
cannot claim independent equivalence, complete enrichment or P08 completion.
Current preparation only runs production logic with controlled fake transport/API
sources in native SQVM; native OpenTTD cargo bindings remain unproven until authorized.

## Safety and authorization

Future maxima: one gameplay launch, one live Admin connection, one industry_cargo
request. Retries, reconnects, additional requests/command types and launches: zero.
No ping, world_info, inventory continuation or enrichment request is permitted.
Admin subscription/control Ping/Pong framing is transport lifecycle, not a GameScript
application query. Fresh mode-0600 X25519 credentials are isolated; only public-key
identity enters evidence. Insecure Admin authentication and password fallback remain
disabled. Both endpoints are loopback-only, owned and checked before/after execution.

No construction, vehicles, orders, terraform, finance, industry mutation, gameplay
RCON, operational planning or P08 extraction is authorized. GameScript validates one
industry and reads/sorts at most 16 slots per capability set. No map scan or industry
inventory assembly is performed in GameScript.

Prelaunch failures retain zero-activity evidence and stop without retry. Post-launch
failures retain partial evidence, never resend/reconnect/relaunch/repair sources,
then close Admin, bounded shutdown/terminate/kill if necessary, reap, verify endpoint
closure and remove credentials. Final artifact failures also classify the proof failed.
Any later native execution requires fresh explicit authorization.

New freeze: `artifacts/runtime/openttd-15.3-industry-cargo-real-prelaunch/`.
Future evidence destination: `artifacts/runtime/openttd-15.3-industry-cargo-real-attempt1/`;
it remains absent during preparation. Expected filenames are listed in PRELAUNCH.json.
Old freezes cannot authorize this changed production source.

## Prepared freeze identity

Public CLI preparation and guarded preflight completed with READY_TO_LAUNCH,
process creation blocked and activity counters 0/0/0. The freeze contains **132**
source/input hashes. Corrected capability bridge package digest:
`63285895cf80be2b1f9b675c586525148117b3aa05c7ea1bea67a94bbfcecb2b`.
Proof configuration digest:
`2709bc9f5177b95886753fcac63baaa1447646ac73e58ac103d8604a24f12959`.
The request digest is unchanged from the canonical request above. All 425
protected historical files and checkpoint HEAD remain unchanged. The isolated
private credential is fresh and mode 0600; its bytes are absent from public evidence.
Fresh explicit execution authorization is required against this freeze.
