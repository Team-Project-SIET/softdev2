# Endpoint cleanup diagnosis and shared contract

Attempt 3 under V4 remains POST-LAUNCH FAILED and consumed. The native coordinator
completed M0 January → M1 February → M2 March, validated stability and ten fresh
production records, and reached QUALIFIED_OBSERVATION_ASSEMBLED. Public retention
withheld complete/qualified admission after cleanup failed. Its retained
qualified_for_planning=false, native report and evidence have not been rewritten.
Mandatory offline verification subsequently passed. Supplemental ownership-checked
workspace disposal and persistent/historical integrity verification passed.

## Historical timeline and limits

The frozen native path is execute_qualification_attempt → shared
raw_production_attempt.execute_raw_production_attempt(qualification=True). That owner invokes NativeBackend.cleanup:
AdminStream.close(quit=True) writes encrypted ADMIN_QUIT, drains with the existing
one-second bound, calls writer.close and awaits wait_closed with the existing
one-second bound. It then closes ProcessLifecycle: console quit request, bounded
wait, escalation only if needed, and reap. Logs/key cleanup occurs separately.

Retained process-lifecycle.json records quit_requested → reaped, returncode=0,
remaining_processes=[], cleanup_error=[]. The qualification lifecycle records
CLEANUP_STARTED → PROCESS_REAPED → FAILED. The error is EADDRINUSE. No monotonic
socket-close, process-exit or bind timestamps, exception traceback, failing bind
index, contemporaneous procfs table, or inode/owner snapshot were retained.
Admin wait_closed catches timeout/OSError internally; an empty cleanup_error list
alone cannot prove its exact TCP teardown instant. Do not invent FIN/ACK timing.

After reap the owner called EndpointReservation.allocate(game=47319, admin=39807).
It creates AF_INET/SOCK_STREAM game, AF_INET/SOCK_DGRAM game, then AF_INET/SOCK_STREAM
Admin, binding each to 127.0.0.1. No SO_REUSEADDR/SO_REUSEPORT is set; no wait/retry
exists. There is no IPv6 verification socket. The exact failing one of those three
bind calls is UNKNOWN from immutable Attempt 3 evidence. The retained postrun
report records a later read-only observation of Admin 39807 in TIME-WAIT, with no
listener/established connection. Later retained socket listings show neither port
in use. These observations are not an atomic snapshot at the failing syscall.

A surviving listener, unexpected owner or child at the exact failing instant is
UNKNOWN, not disproved solely by parent reap. The native executable scan returned
no matching process and the later endpoint observations support closure. The
reservation closes before native launch and again before cleanup; its close method
empties the socket list, and allocate closes every partially acquired socket on
failure. No retained evidence indicates a reservation leak. No trace indicates
IPv6 wildcard aliasing or another verifier/test reusing the port; those possibilities
at the exact instant remain UNKNOWN. The old verifier itself acquires fresh binds,
so conflicts with a concurrent binder were indistinguishable from TIME_WAIT.

## Proven controlled defect

Two runs of the original minimal plain-socket reproduction falsely rejected a
closed listener with EADDRINUSE while /proc/net/tcp contained only state 06.
The deterministic exchange actively closes the accepted server socket, consumes
FIN/EOF on both sides, and closes every descriptor. No sleep, OpenTTD, AdminPort
client, gameplay request or native retry is involved.

The controlled matrix varies active closer, wildcard/loopback, old/new REUSEADDR,
accepted-socket survival and IPv6 wildcard V6ONLY. Never-accepted listeners rebind
immediately. Server-first close leaves server-side TIME_WAIT and plain rebind fails;
client-first close leaves TIME_WAIT on the client tuple and server rebind succeeds.
Reuse requires appropriate prior and new socket options. A surviving established
connection may allow REUSEADDR rebind, showing that even successful rebind is not
sufficient connection-closure proof. IPv6 wildcard V6ONLY=0 conflicts with IPv4;
V6ONLY=1 can be independent. Controlled results and monotonic reproduction ordering
are retained in the V5 verification artifacts.

The proven root cause in the verifier is semantic: port immediately bindable was
used as a substitute for listener/connection closed. The TIME_WAIT mechanism is
proven and matches the later Attempt 3 observation. Exact historical syscall
attribution is not recoverable without evidence that was never recorded.

## Required cleanup property

Owned process reaped, reservation released, no proof listener, no active connection,
no game UDP socket, credential removed, owned workspace disposed, and persistent
source/protected history exact are required. Immediate port reusability is not a
semantic requirement. A kernel TCP TIME_WAIT record has no accepting listener and
is permitted as residual teardown state. Any other endpoint-associated TCP state
is rejected; UDP bindings are rejected. Ambiguous ownership/identity/family or
unavailable/malformed kernel evidence fails closed.

proof/endpoints.py is the shared verifier. It reads /proc/self/net/tcp, tcp6, udp,
udp6 in the verifier's network namespace and checks both local server tuples and
remote client tuples. Frozen IPv4 loopback endpoints must exactly match PRELAUNCH.
IPv6 mapped/wildcard rows are considered too: procfs does not expose V6ONLY, so a
live wildcard row is conservatively rejected rather than assumed independent.
Explicit ::1 is distinct from 127.0.0.1. This is a post-reap observation, not an
atomic guarantee that an unrelated process cannot acquire the endpoint afterward.

No socket creation, connection probe, sleep, timeout change or bind retry was added.
ECONNREFUSED can support no listener for an exact-family probe; successful connect
contradicts closure and timeout is ambiguous. Production uses structured kernel
inspection, not a connect probe: it performs no extra Admin connection/request.

All eleven proof owners use the shared checker: ACK, world-info, industry-page,
inventory, cargo, capability enrichment, cargo-page, catalog, structural-world,
industry-production and complete-raw/qualification. Prelaunch endpoint reservation
remains strict binding with unchanged exclusive options. Native qualification
and all polling/accounting/production/stability contracts are unchanged.

Sources: [Linux socket manual](https://man7.org/linux/man-pages/man7/socket.7.html),
[Linux kernel proc TCP interface](https://kernel.org/doc/html/v5.12/networking/proc_net_tcp.html).

## Next execution boundary

Attempt 3 cannot execute again. V5 targets native Attempt 4, fresh destination and
credential, exact consumed Attempt 1/2/3 history and V3's preserved PRELAUNCH 0/0/0.
Guarded public preflight may reserve endpoints but creates no process or connection.
Any native Attempt 4 execution requires fresh explicit authorization.
