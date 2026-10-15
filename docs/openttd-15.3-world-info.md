# Read-only world_info, protocol 1

`world_info` returns only map width and height. Python requests these from the actual GameScript, then compares the response with the separately captured SERVER_WELCOME from its authenticated Admin session in the same runtime. The caller must retain that independent welcome and invalidate the observation on NEWGAME/disconnect; the transport rejects lifecycle changes during the query. No date, landscape, terrain, infrastructure, companies, industries or cargo is queried.

## API authority

No verified release-specific generated GS map docs were available in the project. The online generated API identified itself as master, so the implementation uses the official OpenTTD **15.3 release-tag source** instead:

- [script_map.hpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_map.hpp) marks ScriptMap `@api ai game` and declares GetMapSizeX/GetMapSizeY.
- [script_map.cpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_map.cpp) implements them by returning Map::SizeX/SizeY; no command or mutation executes.
- [API CMakeLists.txt](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/CMakeLists.txt) generates the **game;GS** binding, establishing GSMap rather than copying an AI name.
- [network_admin.cpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network_admin.cpp) independently sends Map::SizeX/SizeY as uint16 in SERVER_WELCOME.
- [map.cpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/map.cpp) requires power-of-two map axes.

Pinned copies, URLs and SHA-256 identities are in tests/reference/world_info_15_3/manifest.json. Controlled tests check the game API annotation, GS binding, exact getter bodies and independent Admin serialization. Protocol validation requires positive uint16 powers of two; it does not invent unverified engine minimum/maximum settings. A valid native welcome provides the independent runtime dimensions.

## Protocol

Request, exactly three fields:

```json
{"protocol":1,"request_id":"world-001","type":"world_info"}
```

Canonical response, exactly six fields:

```json
{"map_height":128,"map_width":64,"protocol":1,"request_id":"world-001","status":"ok","type":"world_info_result"}
```

Request IDs remain 1–64 safe ASCII characters. Protocol must be integer1; dimensions must be integers, not booleans/floats. Unknown fields/types, duplicate JSON keys, malformed JSON, wrong IDs and non-ok statuses fail closed. Existing application limit512 bytes remains below GSAdmin.Send's verified1450-byte ceiling. Maximum canonical response is172 bytes with64-character ID and five-digit dimensions. Native Send receives a fixed six-field table of bounded values; Send failure emits no response-sent/liveness marker.

No protocol-version bump: this is an additive command with a distinct response. Ping/ACK envelope bytes, receipt semantics and markers are unchanged. Neither response type can satisfy the other command.

The current bridge is NoMutationBridge package **v2**, API15. Its digest is b7392d59e44f0b973a1a8bbd6de4ab395df5eb58df79c45cbde33bef7427a783. Attempt #2 retains its historical v1 package/digest and PASSED communication baseline. The new package has controlled validation only.

## Two evidence channels

```text
Python WorldInfoRequest → ADMIN_GAMESCRIPT
                          → ET_ADMIN_PORT / validated dispatcher
                          → GSMap.GetMapSizeX/Y
                          → GSAdmin.Send(world_info_result)
Python typed response ← SERVER_GAMESCRIPT
    ↓
WorldInfoReceipt (transport correlation)
    + independent SERVER_WELCOME
    + retained internal GameScript records
    ↓
WorldInfoVerification
```

GameScript local chain:

```text
BRIDGE_STARTED protocol=1 api=15
BRIDGE_REQUEST_RECEIVED request_id=... type=world_info protocol=1
WORLD_INFO_READ request_id=... map_width=... map_height=...
BRIDGE_RESPONSE_SENT request_id=... type=world_info_result status=ok protocol=1
BRIDGE_POST_RESPONSE_ALIVE request_id=...
```

Read marker follows the actual getter calls and dimension validation. Response marker follows successful GSAdmin.Send. Liveness marker follows the existing script-tick yield and event-loop continuation. Parser requires native GameScript root18 prefix, exact marker semantics, request identity and ordered supporting records. It retains original raw log bytes, record line numbers, source locator and SHA-256; completion replays that raw evidence and compares its read dimensions with the network response.

Python local chain: REQUEST_SENT < NETWORK_RESPONSE_RECEIVED < RECEIPT_CREATED. Exactly one application send, one matching response and zero retries are required. The transport uses the existing production secure session, registers GAMESCRIPT AUTOMATIC through the production encoder, ignores unrelated non-lifecycle Admin packets, and rejects malformed/wrong/duplicate responses. A read-only protocol AdminPing/Pong completion barrier catches a second response queued in a later read; this is not another application request, ping command or heartbeat. Timeout and disconnect remain distinct failures.

There is **no temporal ordering** between GameScript post-response liveness and Python response/receipt. Correlation is protocol1, same request_id, world_info/world_info_result/ok, and matching internally read/network-reported dimensions.

## Transport versus semantic proof

WorldInfoReceipt establishes only request/response correlation and binds exact raw payload digests. It is separate from the unchanged ACK CommunicationReceipt.

WorldInfoVerification requires both complete evidence chains, then compares reported dimensions with a separately supplied typed ServerWelcome. It retains both dimension pairs, comparison result, runtime and bridge identities, response digest and raw internal-log digest. Any width or height mismatch yields dimension_mismatch; require_match raises. Neither source is preferred and no value from the GameScript response is manufactured into the independent observation.

Controlled tests execute the actual Squirrel Start/dispatcher against read-only GSMap fakes, send production Admin packets through in-memory streams, and independently decode a separate WELCOME fixture. These are controlled tests, not a real world-state proof.

## Mutation scope and next real proof

Only GSMap.GetMapSizeX/Y was added. The exact GS symbol whitelist excludes company/test construction modes, roads/rail/stations/depots/vehicles/orders/terraform/finances/save-load and RCON. No P05 optimization, P06 execution, P07 evaluation or P08 extraction occurs.

This slice provides no terrain/infrastructure extraction, industry discovery, routing candidate generation, optimization or gameplay mutation.

The existing proof CLI is intentionally still the **frozen ping Attempt #2 runner**, not a world_info runner. Do not execute old prelaunch freezes after these source changes, reinterpret old ACK receipts as world-state evidence, or use an ad-hoc launcher. A separate production one-launch world-info proof lifecycle/prelaunch freeze (raw record retention, independent welcome, semantic verification and immutable artifacts) must be prepared and controlled-tested before requesting authorization for a real world-info proof. Historical evidence remains unchanged. No real process or live Admin connection is authorized by this implementation task.

## Production proof preparation

The production proof CLI now supports a separate `--mode world-info` profile:

```sh
.venv/bin/python -m app.simulation.openttd.proof prepare --mode world-info
.venv/bin/python -m app.simulation.openttd.proof preflight --mode world-info
```

Preparation creates `artifacts/runtime/openttd-15.3-world-info-real-prelaunch/`.
Preflight uses the same frozen-input validation, secure native backend and
`EndpointReservation.allocate()` ownership checks as execution. Its audit guard
blocks process creation and socket connection. Neither command executes a proof.
No shell wrapper, object reconstruction or private helper import is required.
The future `run --mode world-info --authorize-one-launch` command requires a
separate explicit authorization for this new frozen profile.

`WorldProofState` records PREPARED, LAUNCHED, ADMIN_ACTIVE,
WORLD_INFO_REQUEST_SENT, WORLD_INFO_RESPONSE_RECEIVED, SEMANTICALLY_VERIFIED,
POST_RESPONSE_LIVENESS_VERIFIED and COMPLETED. Any failure terminates the attempt.
Receiving a response does not imply semantic verification or proof completion.
A transport receipt remains valid communication evidence when dimension
comparison fails; the overall attempt fails and retains both dimension pairs.

The request is protocol 1, type `world_info`, ID `openttd15-world-info-001`.
The strict six-field `world_info_result` response uses positive uint16 powers of
two for map dimensions. Both application payloads retain the 512-byte ceiling.
The current bridge is NoMutationBridge v2, API 15; it still supports `ping`.
Its verified read-only APIs remain `GSMap.GetMapSizeX()` and `GSMap.GetMapSizeY()`.

The GameScript chain is STARTED < REQUEST_RECEIVED < WORLD_INFO_READ <
RESPONSE_SENT < POST_RESPONSE_ALIVE. The Python/Admin chain is
WORLD_INFO_REQUEST_SENT < WORLD_INFO_RESPONSE_RECEIVED < TRANSPORT_RECEIPT_CREATED
< SEMANTIC_VERIFICATION_CREATED. They correlate by protocol, request ID, command,
response type/status and the reported dimensions. There is no total timestamp
ordering between the GameScript liveness marker and Python-side records.

The independent authority is the **SERVER_WELCOME from the same authenticated,
encrypted Admin session**. Launch settings only support runtime identity checks.
`WorldInfoVerification` retains GameScript dimensions, observed Admin dimensions,
individual width/height comparisons, immutable runtime/package identities and
source references/digests. Equality of both dimensions is required; a mismatch
fails rather than selecting one source as correct.

The future evidence destination is
`artifacts/runtime/openttd-15.3-world-info-real-attempt1/`, distinct from ACK history.
The frozen PRELAUNCH contract lists all expected evidence and success/failure
criteria. Native GameScript records are copied to `gamescript-supporting.log`
and parsed with exact record identifiers and a raw digest **before shutdown**.
The runner retains logs and semantic failures, removes the ephemeral private key,
verifies source/history integrity and endpoint closure, and deletes the workspace
only after reaping is established. No application resend or process relaunch is
provided. A second run requires fresh explicit authorization.

This slice verifies communication and read-only map dimensions. It does not
provide terrain/infrastructure extraction, industry discovery, routing candidates,
optimization, simulation evaluation or gameplay mutation. ACK Attempt #2 remains
the historical transport baseline; no ACK evidence is regenerated.
