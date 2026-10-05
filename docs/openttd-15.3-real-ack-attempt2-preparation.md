# PRELAUNCH — Attempt #2 evidence hardening

Controlled preparation only. No gameplay launch or live Admin connection is
allowed in this task. `CONTEXT.md` remains architecture authority. Attempt #1 is
FAILED and its evidence is immutable; its valid network receipt does not change
that verdict. No commit or push.

## Attempt #1 forensic review

Every file in `artifacts/runtime/openttd-15.3-real-ack-attempt1/` was read before
editing. The full artifact SHA-256 snapshot is retained in the new PRELAUNCH
forensic record. The old manifest validates; source-freeze-post exactly matches
source-freeze. Its stdout contains the game console banner. Its stderr contains
world generation, graphics loading, one authenticated Admin session and shutdown,
but no script-origin lifecycle markers.

| Fact | Classification | Reason |
| --- | --- | --- |
| Startup | B: never explicitly emitted | Old bridge Start had no logging call. |
| Event receipt | B: never explicitly emitted | Old event/Handle path had no logging call. |
| ACK send | B: never explicitly emitted | Real response/receipt proves network result; old Send path did not log success. |
| Post-ACK liveness | B: never explicitly emitted | Old loop continued without an explicit observable marker. |

No trustworthy missing marker was found in either raw stream, protocol evidence,
response, receipt, lifecycle, sanitized config, or other retained artifact. The
network ACK and immutable receipt are valid communication facts. Formal Attempt
#1 remains `REAL ACK PROOF FAILED — NO RETRY PERFORMED — required explicit
GameScript startup/event-processing and post-ACK liveness evidence not retained`.

## Minimal instrumentation and capture

The bridge uses `GSLog.Info` for four deterministic records. Start initializes a
local pending-ID list, then logs `BRIDGE_STARTED protocol=1 api=15`. A validated
Admin event logs `BRIDGE_REQUEST_RECEIVED request_id=<id>`. Only a successful
`GSAdmin.Send` logs `BRIDGE_ACK_SENT request_id=<id>`. Start queues that ID and
logs `BRIDGE_POST_ACK_ALIVE request_id=<id>` when the existing event loop resumes
after its existing `Sleep(1)` script-tick yield. No extra sleep, request,
heartbeat, world query or gameplay API is added. A failed Send produces no
ACK-sent or alive marker.

OpenTTD 15.3 [ScriptLog](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_log.cpp)
prints script messages through Debug. Its
[log level enum](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_log_types.hpp)
assigns Info level **4**. Attempt #1 selected script=3; preparation now selects
`-dscript=4,grf=1,net=3`. The
[debug sink](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/debug.cpp)
prints those records to stderr, independently of console subscriptions. The
[GameInstance root](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/game/game_instance.cpp)
is OWNER_DEITY, value 18 in
[company_type.h](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/company_type.h).
The parser requires the native script:4 / root 18 / Info prefix; Python or other
script-root messages cannot substitute.

The native adapter captures stdout/stderr directly into isolated files. The
proof waits boundedly for newline-terminated records visible in stderr while
the process remains healthy. Polling delays only pace file observation; elapsed
time never proves liveness. No assumption about shutdown flushing is used: the
complete supporting bytes are copied into `gamescript-observed.log`, with
`gamescript-evidence.json`, before shutdown is requested. A deadline fails
closed if logging does not become visible. The final stderr is also parsed after
shutdown to reject a late duplicate startup/sequence. Native behavior of the
new instrumentation remains for a separately authorized real attempt.

The typed frozen evidence retains exact records, line numbers, origin log,
ordered markers, identity and SHA-256 of the observed raw log. Success requires
startup < request received < ACK sent < continued-loop alive, plus an
independently correlated encrypted network ACK and one application request.
A receipt is constructed before waiting for complete internal evidence; an
overall successful receipt artifact is published only when every gate passes.

## New frozen input and invocation boundary

Default preparation and execution target Attempt #2 only. Preparation refuses
Attempt #1 paths, existing directories and ordinary profile paths. Loading an
old Attempt #1 preparation is rejected before reopening its workspace; an old
request passed to execution is rejected before writes or cleanup. Ordinary tests
use synthetic history; the actual historical manifest is checked externally
before and after this task without rewriting it.

Canonical request is
`{"protocol":1,"request_id":"openttd15-real-ack-002","type":"ping"}`.
The preparation records its digest and the new instrumented package digest;
Attempt #1's package digest stays a historical identity only.

Preparation command (does not launch or connect):

```sh
.venv/bin/python -m app.simulation.openttd.proof prepare
```

Future directory:
`artifacts/runtime/openttd-15.3-real-ack-attempt2-prelaunch/`.
There must be no `openttd-15.3-real-ack-attempt2/` runtime directory until separate
explicit real-run authorization. A new 0600 ephemeral X25519 key stays only in
the isolated workspace, outside public evidence and manifests. Source freeze
includes the parser, lifecycle harness, bridge instrumentation, runtime sources,
dependencies, binary, and staged public assets/configuration. Ports remain exact
frozen loopback endpoints; busy ports fail with zero launches. The established
secure Admin, framing, ping/ACK semantics, external runtime and P05–P08 logic are
unchanged.
