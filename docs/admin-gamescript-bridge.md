# OpenTTD 15.3 AdminPort ↔ GameScript ping/ACK

`CONTEXT.md` remains the architecture authority. This slice implements only
communication completion, not plan execution or evidence of world mutation.
Real OpenTTD 15.3 Attempt #2 established the secure encrypted ping/ACK and explicit
GameScript liveness baseline; its PASSED evidence remains immutable in
`artifacts/runtime/openttd-15.3-real-ack-attempt2/`. Existing P03/P06/P07 13.4 proofs
remain historical. The additive [world_info slice](openttd-15.3-world-info.md)
is controlled-only and has not had a real world-state proof.

## Application protocol

Canonical UTF-8 JSON request:

```json
{"protocol":1,"request_id":"ack-000001","type":"ping"}
```

ACK:

```json
{"protocol":1,"request_id":"ack-000001","status":"ok","type":"ack"}
```

The root must be an object with exactly the documented fields. Protocol must be
integer 1 (booleans/floats are rejected). This section specifies unchanged ping/ACK;
world_info/world_info_result has its separate strict schema in the linked slice.
IDs are 1–64 ASCII characters matching
`[A-Za-z0-9][A-Za-z0-9_-]{0,63}`. Python rejects invalid UTF-8, malformed JSON,
duplicate keys, missing/extra fields, unsupported versions/types/statuses, and
oversized payloads. Canonical serialization sorts keys without extra whitespace.

The application byte limit is **512**, inclusive, in each direction before the
Admin string's NUL terminator. The bridge returns only a fixed ACK envelope and
the validated ID. Its maximum compact output is **121 bytes**, safely below the
documented `GSAdmin.Send` 1450-byte constraint. The 15.3 API header documents
rejection above 1450; the inspected `script_admin.cpp` does not contain that
size check. This application does not depend on native enforcement.

GameScript receives a converted table through `GetObject()`, not raw JSON.
It validates field count, types, protocol, command, and ID. Native JSON conversion
has already occurred; it cannot independently inspect original whitespace or
duplicate raw JSON keys. The Python outbound session validates the strict JSON
request before any write. Invalid bridge objects produce no ACK and the event
loop stays alive. Repeated valid ping objects produce identical ACKs without a
persistence store or gameplay operations.

`CommunicationReceipt` is immutable and records protocol version, exact request
ID, SHA-256 of the actual request/response JSON bytes (excluding NUL/framing),
response type, and status. It is returned only after strict parsing and exact
ID correlation. It does not certify a world-state change.

## Admin framing and transport

Verified OpenTTD 15.3 wire constants:

| Purpose | ID / value |
| --- | --- |
| `ADMIN_PACKET_ADMIN_GAMESCRIPT` | 6 |
| `ADMIN_PACKET_SERVER_GAMESCRIPT` | 124 |
| `ADMIN_UPDATE_GAMESCRIPT` | 9 |
| `AUTOMATIC` frequency mask | 64 |
| Admin protocol version | 3 |

A plaintext/decrypted Admin frame uses a little-endian uint16 total length,
one-byte packet ID, and body. GameScript body is one UTF-8 JSON string terminated
by NUL. The shared frame bound remains 32767, verified in 15.3 `config.h`.
The engine's incoming GameScript JSON string bound is 9000 including NUL;
this is separate from the much stricter application bound.

`AdminFrameDecoder.feed_frames()` exposes raw packets beneath P04's existing
`feed()` decoder. `encode_admin_frame()` is a framing primitive, not an outbound
permission. `AdminStream` centralizes the existing socket read/write/cleanup
lifecycle. `AdminSession` retains P04's read-only allowlist; packet 6 remains
forbidden there. P04 server decoding still treats unsupported packets, including
GameScript replies, as bounded unknown metadata.

`GameScriptSession` has a separate narrow policy: valid ping/world_info packets,
the GameScript AUTOMATIC subscription, read-only AdminPing barriers, and AdminQuit. It permits no RCON, gameplay,
or general-purpose command writes. `GameScriptTransport` takes this exclusively
owned, authenticated stream after Welcome plus the parsed `ServerProtocol`.
It does not connect or authenticate. The caller must have consumed all handshake
frames and must not leave another reader operating on that connection.

The transport requires protocol 3 and an advertised AUTOMATIC GameScript capability,
registers update 9 with mask 64 before sending the first ping, and waits under one
bounded deadline covering writes and reads. It ignores unrelated packet types;
GameScript ACKs must match the pending ID. Unexpected lifecycle packets fail the
protocol; shutdown/EOF/I/O failure are disconnects. Malformed frames/JSON and
unsupported or mismatched envelopes have distinct exception categories:
`TransportTimeout`, `TransportDisconnected`, `MalformedResponse`, and
`TransportProtocolError`.

One request may be pending at a time. IDs cannot be reused on the same stream;
up to 256 IDs are retained, then a new session is required. This avoids a delayed
ACK completing a later same-ID request and keeps correlation memory bounded.
GameScript duplicate behavior remains deterministic. Timeout, cancellation,
disconnect, or protocol failure invalidates and closes the owned session.
No background reader or wall-clock polling sleep is used as completion proof.

## Package and controlled verification

`gamescript_bridge_package/info.nut` registers `NoMutationBridge`, version 1,
API major **"15"**. `main.nut` implements only:

- persistent `Start()` with bounded event batches and script-tick yielding;
- `GSEvent.ET_ADMIN_PORT` detection;
- `GSEventAdminPort.Convert(event).GetObject()`;
- validated ping handling and `GSAdmin.Send(ack)`.

There are no construction, vehicle, order, terrain, industry, finance,
GSCompanyMode, RCON, or save/load commands. `stage_bridge(workspace)` copies the
package into the prepared isolated `game/NoMutationBridge/` directory, computes
its content digest, and selects it in `[game_scripts]`. It refuses an existing
selection or escaping symlink. Selection applies to a future new world;
loading an existing save may restore that save's script state instead.

Tests execute the actual handler and `Start()` in Squirrel using API-shaped
15.3 fakes. The complete controlled path runs typed Python → packet → decoded
input → actual Squirrel event handler → ACK table → native-JSON-shaped server
packet → correlated receipt. Separate tests exercise the pure handler model,
framing fragmentation, message limits, error categories, request correlation,
script survival, mutation prohibition, and P04/runtime preservation.
The fake VM does not prove native engine binding or network interoperability.

## Concrete prerequisites for a real ACK proof

- The [secure Admin transport](secure-admin-transport.md) now implements
  authorized-key authentication and persistent encrypted framing in controlled
  tests. A native server handshake and ACK remain unproved; no insecure fallback
  is enabled.
- Official OpenGFX 8.0 is now staged and statically verified by the
  [one-launch harness preparation](openttd-15.3-real-ack-proof.md). Native load
  and the real ACK remain unproved.
- The controlled real-proof harness must own/reserve local endpoints, launch the
  staged new world, consume the protocol-3 handshake/Welcome, retain evidence,
  and reap the process. This task intentionally contains no world launcher.
- Real launch/live connection requires a separate authorization.

No planner or P02/P05/P06/P07/P08 caller is migrated to this bridge.
The historical P07 source-freeze audit now checks the proof-era implementation
commit `6eacdb0b4c39b2dd886a4a749bbeb588f690d22f`, rather than today's editable
workspace. Frozen artifacts are unchanged; this check makes no claim about
current-source real-game compatibility.

## OpenTTD 15.3 authority

- [Packet IDs, update type, frequency and string layouts](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/core/tcp_admin.h)
- [Version 3 and wire/string size bounds](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/core/config.h)
- [Subscription filtering and JSON event dispatch](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network_admin.cpp)
- [Framing and string encoding](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/core/packet.cpp)
- [Event controller and ET_ADMIN_PORT](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_event.hpp)
- [AdminPort event conversion and GetObject](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_event_types.hpp)
- [Native JSON-to-Squirrel conversion](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_event_types.cpp)
- [GSAdmin.Send documented constraint](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_admin.hpp)
- [GSAdmin.Send implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_admin.cpp)
- [GameScript configuration selection](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/settings.cpp)
