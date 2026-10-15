# Structural-world proof frame accounting

This is a controlled accounting design, not a prelaunch freeze. The structural-world
production CLI, native owner and prepared launch contract still need integration.
No native execution is authorized by this document.

The query-operation ceiling remains 1024: inventory 256 + capability 256 + catalog
512. The response-byte ceiling remains 49152 and the application-request ceiling
remains 96. These ceilings do not imply a particular industry or cargo count.

The total post-auth frame ceiling is **1030**, with this boundary defined explicitly:

| Category | Maximum frames | Production authority |
| --- | ---: | --- |
| Encrypted session establishment | 2 | `SecureAdminSession.authenticate`: encrypted SERVER_PROTOCOL and SERVER_WELCOME after ENABLE_ENCRYPTION |
| Explicit subscription setup | 3 | `GameScriptTransport.subscribe`: UPDATE_FREQUENCY, ADMIN_PING, SERVER_PONG |
| Inventory query operations | 256 | Existing inventory session budget |
| Capability query operations | 256 | Existing capability session budget |
| Catalog query operations | 512 | Existing catalog session budget |
| Graceful Admin close | 1 | `AdminStream.close(quit=True)`: ADMIN_QUIT |
| Total | 1030 | 2 + 3 + 256 + 256 + 512 + 1 |

Authentication JOIN_SECURE, AUTH_REQUEST, AUTH_RESPONSE and ENABLE_ENCRYPTION
belong to authentication, preceding this boundary. TCP EOF, socket closure and
process signals are not Admin frames. There is no native application `ping` or
`world_info` request in this derivation. Protocol ADMIN_PING is a barrier packet.

For this derivation, the future owner must perform subscription explicitly before
Phase A. Otherwise the first query receipt includes subscription operations and
those frames must not be counted a second time. The guarded dry run must verify
this wiring; merely importing the accounting class is insufficient.

Each query receipt counts outgoing GameScript request and completion ADMIN_PING,
incoming GameScript response and SERVER_PONG, and any other decoded frames consumed
while waiting. GameScript post-response liveness comes from stderr evidence and
requires no extra application request or Admin frame. Unexpected traffic consumes
the applicable budget; it is not unbounded lifecycle overhead.

Two gaps in the existing catalog template matter when preparing the combined owner:
its recorder is installed after encrypted PROTOCOL/WELCOME have been consumed, and
its `close` delegates to the secure session, so graceful QUIT bypasses the recorder.
The structural owner must account for these paths explicitly, retaining evidence
rather than assuming successful establishment or closure. Every actual outbound
and decoded inbound frame must be admitted once. On a budget failure, cleanup must
still close the stream and reap the process without sending another application
request. A QUIT that would exceed its reserved category is prohibited; socket and
process cleanup remain required.

`StructuralFrameBudget` supplies the controlled category ceilings and rejects
unknown categories, invalid counts and overruns without changing admitted counts.
It does not implement native recording or prove an executed frame count.
