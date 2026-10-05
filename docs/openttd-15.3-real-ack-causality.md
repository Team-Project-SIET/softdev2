# PRELAUNCH revision v2 — two correlated proof channels

`CONTEXT.md` remains the architecture authority. This correction is controlled
only. No OpenTTD process, live Admin connection or real application request is
authorized in this task. No commit or push.

## Historical state

Attempt #1 executed once and remains FAILED for missing explicit internal
GameScript evidence. Its valid historical encrypted ACK and immutable receipt
do not change that classification.

The previous Attempt #2 state is **ATTEMPT #2 NOT EXECUTED — PRELAUNCH GATE
FAILED**. It had zero gameplay launches, live Admin connections and application
requests. Its old report used a runtime-failure status line; that text is retained
unchanged as historical evidence, and this document records the correct state.
The original prelaunch directory and gate-failure directory are immutable.

The gate demanded receipt creation before GameScript post-ACK liveness emission.
That was an invalid total order over independently scheduled channels. The
controlled native fixture legitimately emits ALIVE before delivering the ACK.
The old production parser already validated only internal log order; this change
makes the complete partial-order proof contract explicit and independently
retains the Python/Admin chain.

## Proof model: two-correlated-chains-v2

GameScript log order:

```text
BRIDGE_STARTED
  < BRIDGE_REQUEST_RECEIVED
  < BRIDGE_ACK_SENT
  < BRIDGE_POST_ACK_ALIVE
```

Python/Admin operation order:

```text
REQUEST_SENT < NETWORK_ACK_RECEIVED < RECEIPT_CREATED
```

Both complete chains are required. Post-ACK liveness may precede the network ACK,
follow that ACK but precede the receipt, or follow the receipt. No shared clock,
wall-clock timestamp comparison, or global temporal ordering is used.

Semantic correlation requires protocol 1, request_id
`openttd15-real-ack-002`, request type ping, ACK type ack and status ok. The
unchanged frozen bridge validates these request semantics and creates fixed ACK
fields; its successful-Send marker is emitted only after GSAdmin.Send succeeds.
GameScript evidence explicitly identifies that source-based semantic identity
basis. The parser does not pretend type/status fields were emitted in raw marker
text. All request-specific records must have the exact ID, and the startup record
must have protocol=1/api=15. Native script:4/root 18/Info provenance, exact raw
records and strictly increasing log line numbers remain required.

NetworkProofEvidence retains canonical request/response bytes, the actual
immutable production receipt, local event order, request/ACK/retry counts and
sanitized post-authentication packet metadata. TransactionCorrelation joins the
channels by their canonical envelope fields. No successful result can be based
on network ACK alone or internal logs alone.

## Duplicate ACK and retry protection

A proof-only session observer delegates all I/O and security to the production
Admin session. It records successful sends and validated ACK receives; a second
application-send attempt, mismatched ACK or duplicate matching ACK fails.
After receipt creation it uses a read-only ordered AdminPing/Pong completion
barrier (token 0x154) to drain any duplicate ACK queued as a separate encrypted
packet. This is not a second application ping or a heartbeat. It changes no
crypto, framing, envelope, runtime or bridge behavior. The existing subscription
barrier retains token 0x153. There is no fictitious subscription ACK.

Supporting GameScript bytes and typed evidence, independent network evidence and
transaction correlation are retained before shutdown/workspace disposal.
Failure retains available partial evidence. Final log validation still rejects a
late duplicate startup and missing liveness. There are no gameplay APIs added.

## Revision and authorization boundary

New default preparation:
`artifacts/runtime/openttd-15.3-real-ack-attempt2-prelaunch-v2/`.
The old preparation and gate-failure paths are rejected before writes. Old
preparation metadata is rejected before workspace reopening, process creation,
connection or cleanup. The new manifest declares attempt 2, prelaunch revision 2
and proof model `two-correlated-chains-v2`.

The same binary/OpenGFX/bridge and canonical request 002 are retained. The new
source freeze includes the partial-order validator and proof-only network
observer. A fresh 0600 ephemeral X25519 key lives only in the new isolated
workspace, outside public evidence/manifests; config remains loopback-only and
secure-key-only. No Attempt #2 runtime directory exists in this controlled task.

The prior launch authorization was never consumed. It must not be used against
this changed freeze: **fresh explicit authorization for revision v2 is required**.
This task only prepares that reviewable state.
