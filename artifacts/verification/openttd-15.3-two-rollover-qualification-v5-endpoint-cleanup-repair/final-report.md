# Attempt 3 classification

native qualification: SUCCESS; coordinator COMPLETED  
qualified observation: internally assembled, YES; formal retained qualified_for_planning=false  
cleanup: FAILED, endpoint rebind EADDRINUSE after process reap  
offline verification: PASS  
overall: FAILED, POST-LAUNCH consumed native Attempt 3  
supplemental credential/workspace disposal and persistent/historical integrity: PASS  
historical result rewriting: NONE

# Endpoint failure

endpoint candidates: frozen game 127.0.0.1:47319 TCP then UDP; Admin 127.0.0.1:39807 TCP  
exact historical failing bind index/port: UNKNOWN, not retained in exception/evidence  
address family: AF_INET  
rebind method: raw_production_attempt cleanup → EndpointReservation.allocate → socket.bind  
socket options: defaults, no SO_REUSEADDR, no SO_REUSEPORT  
dual-stack verification socket: NONE (IPv4 only)  
retry/wait behavior: none  
EADDRINUSE cause in controlled reproduction: closed listener + server-side TCP TIME_WAIT  
exact historical syscall kernel state/owner: UNKNOWN; later TIME_WAIT observation is consistent

# Root cause

actual listener remained at historical failing instant: UNKNOWN; none indicated by later observations  
TIME_WAIT involved: later Attempt 3 report observed Admin TIME_WAIT; mechanism proven in controlled tests  
reservation leak: no retained indication; code releases before launch and cleanup; controlled release/stale tests PASS  
address-family issue: none indicated historically; IPv6 aliasing handled conservatively by repaired verifier  
verifier semantic error: immediate rebindability falsely used as listener/connection closure  
proven cause: shared verifier rejects closed endpoints in TCP TIME_WAIT; adding reuse to a rebind check can also wrongly accept an established connection  
historical certainty limit: no atomic procfs snapshot/owner/bind traceback was retained; no invented timing or owner

# Cleanup timeline

1. According to frozen source: AdminStream.close(quit=True) writes ADMIN_QUIT, drains,
   closes the client writer and awaits wait_closed under the existing one-second bounds.
   Exact client shutdown syscall/FIN ordering and successful wait versus swallowed timeout
   are not individually retained.
2. According to retained process evidence: console quit_requested → reaped,
   returncode=0, no remaining matching OpenTTD processes, cleanup_error=[].
3. According to retained qualification lifecycle: CLEANUP_STARTED → PROCESS_REAPED
   → endpoint rebind raises EADDRINUSE → FAILED before ENDPOINTS_CLOSED.
4. According to code: game TCP bind, game UDP bind, Admin TCP bind, each loopback,
   without reuse options. Which bind failed is not retained.
5. Later report records Admin TIME_WAIT and no listener/ESTABLISHED; later retained
   socket listings are empty. These do not establish the exact earlier syscall state.
6. Supplemental ownership-validated cleanup removed the workspace; key already removed
   by the public finally path. Independent source/history integrity passed.

No historical monotonic timestamps were available. The plain-socket reproduction retains
its own monotonic ordering: server FIN observed → descriptors closed → naive EADDRINUSE
→ repaired verifier PASS, without a sleep.

# Endpoint contract

process reaped: REQUIRED  
listener closed: REQUIRED  
connection closed: REQUIRED, no endpoint-associated active TCP state accepted  
game UDP binding closed: REQUIRED  
owned reservation released: REQUIRED  
credential removed / workspace disposed / persistent+historical integrity: REQUIRED  
port immediately rebindable after cleanup: NOT REQUIRED  
prelaunch exclusive reservation: unchanged, still REQUIRED  
allowed residual kernel state: TCP TIME_WAIT only; recorded explicitly  
unknown state/family/ownership/kernel inspection: FAILED closed

# Repair

modules: new proof/endpoints.py; eleven shared proof owners; qualification preparation,
preflight and revision/destination configuration; controlled endpoint/preparation tests  
old behavior: attempt fresh game/Admin binds after reap; infer endpoint closure from rebindability  
new behavior: structured /proc/self/net/tcp, tcp6, udp, udp6 inspection in the verifier namespace;
exact frozen IPv4 loopback tuple, local and remote connection checks, reaped process and released reservation prerequisites  
shared impact: ACK, world_info, industry page, inventory, industry cargo, enrichment,
cargo page/catalog, structural-world, industry-production, complete-raw and qualification  
sleep added: NO  
timeout changed: NO  
connection probe added: NO  
native retry/resume added: NO  
force/ignore switch: NONE  
Linux portability: explicit Linux proof contract; unavailable tables fail closed  
IPv6 wildcard: rejected conservatively because procfs cannot prove V6ONLY coverage  
atomic closure promise: NO; this is an observed post-reap state, not protection against future external port acquisition

# Controlled reproduction

naive verifier: deterministic EADDRINUSE despite closed listener and TIME_WAIT only  
repaired verifier: PASS, recorded TIME_WAIT and no live listener/connection  
real listener negative case: rejected  
other Python process listener negative case: rejected  
listener closed but accepted connection survives: rejected, even where REUSEADDR rebind succeeds  
closed never-accepted listener: passes immediate rebind and semantic closure  
server-first/client-first active close: independently tested  
SO_REUSEADDR old/new and wildcard/loopback: 16 controlled matrix rows retained  
IPv4/IPv6 V6ONLY aliasing: two additional matrix rows retained  
successful connect vs ECONNREFUSED: demonstrated using a plain test peer, not production verification  
timeout/ambiguous inspection: rejected, no closure inferred  
wrong family / endpoint identity / stale reservation / unreaped ownership: rejected

# Contracts unchanged

polling: 1 second, 300-second qualification deadline, clock ceiling 304  
requests: 1072  
bytes: 368080  
query operations: 9088  
frames: lifecycle 6 once; post-auth 9094  
qualification: M0→M1→M2, T1==T2, lifetime/fingerprint stability, fresh M2 production,
exact source digest and final M2 guard unchanged  
production_level: DEFERRED / NOT INCLUDED  
P08 integration: NO  
Squirrel dispatch: RawObservationBridge.Handle.call(this, request), byte-identical  
qualification-contract differences: revision 4→5 and future destination Attempt 3→4 only

# Attempt numbering

Attempt 3 consumed: YES  
next native attempt: 4  
Attempt 1/2/3 reuse: rejected  
V3 PRELAUNCH 0/0/0: preserved; never counted as native consumption

# V5

freeze: /home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v5/PRELAUNCH.json  
attempt ID: two-rollover-qualification-v5-native-attempt4  
future destination: /home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-two-rollover-qualification-real-attempt4  
checkpoint HEAD: cc7f7479e3fbfa8c036901ba041dee1b97dc6b42  
predecessors: two-rollover-qualification-v1-runtime-b045142a46c304ba, two-rollover-qualification-v2-runtime-c2f8823bfa845c97, two-rollover-qualification-v3-prelaunch-b6c114daf6106fc7, two-rollover-qualification-v4-runtime-d46ba285fa8f08d8  
Attempt 1: POST-LAUNCH FAILED, dispatch compatibility failure  
Attempt 2: POST-LAUNCH FAILED overall, native success, offline lineage failure  
V3: PRELAUNCH FAILED 0/0/0, controlled-consumption regression  
Attempt 3 under V4: POST-LAUNCH FAILED, native qualification success, offline PASS, cleanup endpoint FAILED  
fresh credential: YES, mode 0600, distinct public identity, private bytes excluded  
fresh authorization required: YES; no native Attempt 4 execution authorized/performed  
protected manifest digest: e72aa1e82743e424201ba36451be73d52953cfef320eff1329637185c8138d2d  
lineage digest: 3a57324bd73cb46d849be22cd33f9728da1024cbdde7b965e8dfdceb10806e77  
bridge digest: d8b263ec580fe4f0f4bd96007da168ddc4d96a2b1b5d502b912f335026d711b3  
proof-config digest: 85e64b62614277e2d6fdbc5f97457b42b699069b93d4947a2bc0df4b3c551114  
accounting digest: 9f44510c24194a214dbf2b3d412c90669ef56d810c255c7ef494df8dcac8fd74  
polling digest: a56c1d383a90fe8827d68c15b830041a6111c385b81d93f0b10326a4e6b1faab  
cleanup contract: endpoint-cleanup-contract.json, linux-kernel-endpoint-closure-v1

# Guarded preflight

historical Attempt 1: PASS  
historical Attempt 2: PASS  
historical V3: PASS  
historical Attempt 3: PASS  
Attempt 4 consumed: NO  
next attempt: 4  
new shared cleanup verifier: loaded, Linux evidence authority resolves, controlled tests PASS  
READY_TO_LAUNCH: YES  
subprocess: NO, blocked  
Admin: NO, blocked  
request: NO  
public path: python -m app.simulation.openttd.proof prepare/preflight --mode two-rollover-qualification

# Historical integrity

V1: byte-identical  
Attempt 1: byte-identical  
V2: byte-identical  
Attempt 2: byte-identical  
V3 and its prelaunch failure report: byte-identical  
V4: byte-identical persistent freeze  
Attempt 3 native evidence and postrun report: byte-identical; FAILED result preserved  
complete raw proof / production Attempt 1/2 / earlier history: byte-identical  
CONTEXT.md: byte-identical  
previously captured public files audited: 1742  
V5 protected files: 1708; archived credential identities: 8  
V5 public freeze/source inventory: validated after guarded preflight

# Tests

endpoint: 30 passed, 0 skipped, 0 failures/errors  
cleanup/lifecycle: PASS  
lineage and historical-vs-next: PASS  
qualification preparation/coordinator/clock/lifetime: PASS  
polling/accounting: PASS  
structural/catalog/capability/inventory: PASS  
transport/protocol/secure Admin: PASS  
complete raw and production / Attempt 1/2/3 regressions: PASS  
P03-P08 controlled regressions: PASS  
focused final: 2015 passed, 3 skipped, 0 failures/errors  
ordinary: 2704 passed, 39 skipped, 0 failures/errors, final serial run without native/Postgres opt-in flags  
post-freeze endpoint/lineage: 66 passed, 0 skipped, 0 failures/errors

The first focused run caught an edit made to a controlled proof's frozen source while the
suite was in flight. Its identity guard correctly rejected it. Source was then fixed,
and the complete focused and serial ordinary suites passed. Earlier diagnostic failures
and final green logs are retained. No guard was relaxed to satisfy that failure.

# Quality

Ruff: PASS  
format: PASS  
applicable typecheck: PASS, all changed proof owners, shared checker and preparation/tests  
git diff --check: PASS  
whitespace: PASS on changed/new sources  
import boundary: PASS, no planning/evaluation dependencies introduced  
source commits/pushes: NONE

# Runtime activity

launches: 0  
connections: 0  
real requests: 0

Plain controlled sockets (and one Python listener stand-in) are not OpenTTD native
execution or real Admin activity. Public preparation/preflight had subprocess/connect
audit guards; no real endpoint was probed. Attempt 3 was not retried.

# Status

READY TO REQUEST FRESH AUTHORIZATION FOR OPENTTD 15.3 TWO-ROLLOVER QUALIFICATION ATTEMPT 4 UNDER V5
