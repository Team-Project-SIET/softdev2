# Single-page OpenTTD 15.3 terrain proof preparation

Local CONTEXT.md remains architecture authority. This is preparation only: no
native process, connection, application request, qualification, authorization,
immutable native freeze or native attempt is issued here. The existing controlled
terrain implementation and historical qualified production are separate evidence.

## Objective and owned seams

Observe exactly one five-tile `tile_facts_page` page using one owned 15.3 process,
one secure connection and one application request. No retry, reconnect, resume,
replacement process, clock query or optimizer is allowed. The proof does not use
the two-sweep collector or attach a fresh runtime to historical Attempt 4.

`proof/terrain_preparation.py` provides `prepare_candidate(directory)` and
`TerrainCandidate.preflight()`. `load_terrain_prepared(candidate_directory, sealed_directory)`
loads the shared PreparedProof/LaunchSpecification without launching. Its request
union now admits TileFactsRequest; no existing preparation or objectives change.
Preparation is CACHE_ONLY: it uses existing
RuntimeWorkspace, AdminSettings, OpenGFX validation/staging, launch_argv,
source_freeze, public materialization identities, ownership and historical protection.
The root must be fresh and nonaliasing. Its restricted credential is outside public
hash inventories; only its public key and permissions enter the record. Package
staging uses `info.nut` and the exact composed `terrain_bridge_source()` bytes.
Existing registration selects NoMutationBridge; the terrain extension inherits the
raw event loop and uses `RawObservationBridge.Handle.call(this, request)`.

`proof/terrain_attempt.py` supplies `execute_single_page(prepared, backend,
destination)` at the existing backend seam, `verify_page(...)`, read-only
`verify_retained_attempt(directory)` and dormant `authorized_native_run(...)`.
Controlled fake children use the same execution and acceptance functions, with
CONTROLLED results. They do not start a subprocess or open Admin connections.

`proof/terrain_native.py` specializes the existing StructuralNativeBackend. Its
owned-listener readiness inspection does not probe TCP: one secure connection
attempt follows verified child listener ownership. Shared authentication verifies
15.3, protocol 3, encryption and SERVER_WELCOME identity. Setup uses only the
existing GameScript subscription and PING barrier. Exact environment overrides are
passed as the complete child environment; inherited variables are not merged.
The guarded session rejects a second/different application request before send.

## Exact pins and disposable source

Executable: `/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd`.
SHA-256: `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`.
Version authority is prior inspected/verified 15.3 evidence plus matching current
executable bytes; no `--version` process is launched during preparation.

Graphics: `artifacts/runtime/verified-assets/opengfx-8.0-all.zip`, SHA-256
`43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be`.
The extracted OpenGFX-8.0 descriptor and GRFs are independently validated and
pinned. The future runtime receives a verified owned copy, not a normal profile.

Terrain package digest:
`a2f64d409b661943b276d5dc63115432ef5e3f516fdce7520def8b0e285eb263`.
Package hashing follows the existing sorted filename/NUL/8-byte-length/content
rule. Isolated compiler success does not substitute for final package equality.

The source is the existing new-world preparation recipe: seed 42, map_x=6,
map_y=6 (64×64), temperate, year 1950, land_generator=1, no competitors, OpenGFX,
economy timekeeping. Its canonical recipe digest is
`6641b582e20df3e3790ba65393e3387ee4be694771a38fa9437e6f9b74d9350f`.
There are **no source save bytes**: this is a declared new-world recipe, not a
save-byte identity. Reproducibility is limited to the pinned recipe/assets/settings;
SERVER_WELCOME must independently confirm dimensions/seed/context after launch.
No post-qualification save correspondence or historical same-run claim is made.

## Region, bytes and accounting

Rectangle [x,y,width,height]=[1,1,5,1], cursor=0. Expected row-major tile IDs on
64×64 are 65,66,67,68,69. Request ID: `terrain-single-page-review` (descriptive,
not an allocated native attempt). All actual terrain values remain unknown.

Exact compact request is 111 bytes:

```json
{"cursor":0,"protocol":1,"region":[1,1,5,1],"request_id":"terrain-single-page-review","type":"tile_facts_page"}
```

The existing wire schemas and scalar domains are unchanged. For this shorter ID,
64×64 map, exact rectangle and terminal continuation, the maximal-width response
is **420 bytes**, tested against the actual tagged ScriptAdminMakeJSON/nlohmann
serializer. The vector uses maximal allowed scalars and masks [2,10,10,10,8];
it is an encoding bound, not a prediction that these native facts coexist.
Protocol request ceiling remains 159, command response ceiling 508, application
ceiling 512 and native Send ceiling 1450. This proof enforces its stricter 420-byte
response budget and canonical serializer equality. No truncation is admitted.
Exactly five records, no pagination/continuation request.

| Resource | Single-page bound and derivation |
| --- | --- |
| Application requests | 1 |
| Request bytes | 111 |
| Response bytes | 1×420=420 |
| Native getter calls | 5×44+6=226 upper bound, not measured CPU work |
| Query operations | 1×8=8 ceiling; nominal application/response/PING/PONG=4 |
| Lifecycle frames | PROTOCOL+WELCOME 2; subscription/PING/PONG 3; QUIT 1: 6 |
| Post-auth frames | 2+3+8+1=14 ceiling, nominal 10 |
| Application plaintext frames | request 111+NUL+3=115; response 420+NUL+3=424 |
| Application encrypted frames | 115+16=131; 424+16=440 |
| Retained output | stdout ≤262144; stderr ≤262144 bytes |

SinglePageFrames configures the existing observer, enforces independent phases,
counts every decrypted/encrypted-boundary packet once and rejects undeclared
packet kinds or order. The actual native query must follow application send, response,
completion PING, completion PONG; the allowance cannot hide unsolicited traffic. Receipts reconcile counters; they never increment them a second
time. No reset and no hidden transition query. Authentication handshake before
post-auth encryption is shared protocol machinery, not part of these 14 frames.
No Admin console subscription is used for liveness; GS markers come from captured
script logs. Shutdown uses one Admin QUIT plus owned console stdin `quit`, followed
by existing bounded SIGTERM/kill/reap escalation if necessary. Console stdin is not
an Admin frame. The old 838 and 9094 ceilings have no authority for this proof.

## Candidate, preflight and authorization

Candidate location for this preparation:
`/tmp/terrain-single-page-preparation/candidate-v2/CANDIDATE.json`.
It retains exact executable/graphics/package identities, source recipe, owned
configuration digest, actual argv and environment, endpoints/public credential
identity, region/request bytes and digest, budgets, historical protection and
source/materialization identities. The private key is never included in the record.
`attempt_identity=null`, `authorized=false`, state=REVIEW_CANDIDATE. The record is
reviewable; it is neither an authoritative immutable freeze nor authorization.

Preflight checks exact input bytes, complete runtime cache inventory, no aliases
or substituted files, mandatory assets, protected history, command reachability,
registration, secure credential ownership, region, serializer identity, config,
argv, environment and budget. It does not connect or inspect runtime terrain.
Ports are reserved offline during preparation and released; future final preflight
must reserve the **same** endpoints, fail if unavailable, and release immediately
before the one launch. A changed port/key/package/source requires fresh review.

Explicit next-step checklist, none authorized here:

1. Review the actual candidate record, argv, public key and isolated cache.
2. Authorize a named, fresh final preparation root and a distinct native attempt
   destination, with exactly one launch/connection/tile request and no retry.
3. Materialize and independently review the final immutable launch seal using
   existing ownership/materialization/historical machinery. No candidate issuer
   silently promotes this record. Include candidate digest, request, exact budget,
   source inventory, secure config, historical integrity and package identities.
4. Supply state=AUTHORIZED_IMMUTABLE_PRELAUNCH, mode=terrain-single-page,
   authorized_one_launch=true, candidate_path/candidate_sha256 and explicit
   attempt_directory in the final PRELAUNCH record. Freeze that record itself.
   Final preparation belongs under the repository's owned runtime evidence root,
   so shared historical protection/disposal uses the correct authority base.
5. Only a separate operator action may invoke `authorized_native_run` with the
   explicit authorization argument. It checks the immutable seal before importing
   the native backend. Normal controlled tests cannot use a candidate as that seal.

No real-run CLI is automatically invoked. Preparation does not choose/consume a
numbered attempt. Preflight failures precede atomic runtime claim and remain zero
launch; a claimed postlaunch failure retains its evidence and cannot be resumed.

## Evidence and mandatory acceptance

GameScript: BRIDGE_REQUEST_RECEIVED → TILE_FACTS_READ (canonical response_json)
→ BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE after yield. Existing parser
checks correlation/order/completeness and equality to typed response bytes.
Python: TILE_FACTS_REQUEST_SENT → TILE_FACTS_RESPONSE_RECEIVED →
TRANSPORT_RECEIPT_CREATED → TILE_FACTS_VALIDATED, through existing transport exchange.
Receipt hashes bind exact bytes; independent logs establish native reads/liveness.

Acceptance requires all source/prelaunch integrity, one process/connection/query,
byte bounds, correlation, independent welcome dimensions, exact covered tile IDs,
row order, native-read evidence, post-yield liveness, receipt/semantic validation,
frame reconciliation, independent endpoint cleanup/reap and post-run source/artifact
integrity. No one gate substitutes for another. Offline verifier re-reads hashes,
receipt, typed page, raw GS markers, accounting and structured cleanup evidence;
it does not trust a result.json success field alone.

## Failure retention and cleanup

Missing/mismatched assets, package omissions, invalid source/region/request, cursor
or ID mismatch, incomplete/duplicate/out-of-order page, excessive response, missing
read/liveness evidence, handler exception, disconnect, crash, extra request,
accounting exhaustion, capture overflow, un-reaped child, active endpoint or source
mutation fail overall acceptance. Evidence filenames and error types are bounded;
unbounded native exception strings are not exposed as protocol data.

Native capture drains stdout/stderr through bounded pipes, writes at most 256 KiB
each, and fails on overflow; it does not truncate an accepted response. Cleanup
remains independent of query success, closes Admin, reaps the owned process, drains
bounded capture and closes file/pipe handles. Existing Linux verifier checks kernel
TCP/UDP state, reservation release and reap; TIME_WAIT alone is allowed, active or
ambiguous sockets fail, without connect/bind probes, sleeps or retries. Canonical
input copies survive disposable cache cleanup; shared final cleanup verifies source
and historical identities after workspace/credential removal. Failed evidence is
retained, never rewritten into PASS. Offline acceptance is not a real fact issuer.

## Controlled verification and claim limitations

Focused tests cover public candidate pins/integrity, final authorization rejection,
package inclusion, selected maximum-width tagged serialization, fake one-shot
success and failure, independent accounting ceilings, negative page/evidence cases,
endpoint failure, child reap, source mutation, bounded capture and offline replay.
Existing terrain VM/collector/protocol, transport, cleanup, supplemental, WPO,
P08/P05, qualified-production and lineage regressions remain unchanged and required.
Native OpenTTD-marked tests stay deselected.

Settled-source verification: **61 new tests**, **954 targeted regressions**, and
**3079 passed, 35 skipped, 3 native deselected** in the final serial ordinary suite.
Both exact-tagged VM/serializer probes were explicitly configured. Ruff, full format
check, scoped typecheck (including the shared request union), diff, whitespace,
import and historical-integrity checks passed. The deselected native cases are
`test_one_real_production_live_run`, `test_real_fixed_seed_simulation` and
`test_one_real_p03_setup_proof`; they are not counted as success.

Five new-code issues were reproduced and repaired: an invalid test fixture omitted
in-region assessment masks; a candidate metadata gate omitted the configuration
hash comparison; the initial frame gate admitted an unsolicited PONG inside the
query allowance and now enforces packet order; shared authentication gate tests
exposed the missing PROCESS transition, now advanced before authentication.
A final backend launch-boundary test also exposed the absence of a seal backstop;
it now independently revalidates the final immutable seal before Popen.
Existing terrain validators were retained without relaxation.

A future PASS could establish only REAL NATIVE SINGLE-PAGE TILE FACT ACQUISITION
for the exact authorized runtime/source/region/package. It cannot establish a full
sweep, two-sweep repeatability, qualified same-run integration, whole-world coverage,
catchment/engine/cost acquisition, executable save correspondence, construction
legality, a real P08 scenario or real execution. The next real step requires the
separate review, immutable freeze and operator authorization above.
