# P08 controlled native integration

This slice implements the simulated lifecycle in the
[native integration design](specs/p08-native-multi-page-integration-design.md).
It produces the unchanged [paired evidence v1](specs/terrain-paired-evidence-v1.md)
package. It implements no REAL outer contract, Model A grant, native process
factory, socket connection or genuine authentication/encryption.

## Interface and authority

`ControlledTerrainAcquisition(context, per_sweep_budget, combined_budget, limits,
monotonic)` owns a `TerrainTwoSweep`, which privately owns the two paginators.
`collect(simulated_backend, directory)` runs one explicitly declared
CONTROLLED_SIMULATED backend. The external seam supplies a simulated owned process,
one supplied GameScript session, establishment frames, context/health observations,
page log evidence and cleanup observations. Production `GameScriptTransport`,
page correlation, native marker parsing, pagination and equality validation are real.
Only the external process and session observations are simulated.

Collection follows PREPARED, CONNECTED, SWEEP_1, SWEEP_2, VERIFIED, CLEANED.
No package is written until exact coverage, ten-field equality and successful
cleanup. `collect` returns the writer's digest as a convenience, not trusted
authority. The caller must independently establish and supply
`accept(expected_descriptor_sha256=...)`; this runs the actual paired verifier,
compares replay with collected exchanges/accounting, and returns a frozen result
in CONTROLLED_ACCEPTED. Its authentication label is fixed to SIMULATED_ONLY.
It cannot be supplied as REAL authorization or native proof evidence.

Offline callers use `verify_paired_package` directly with their independently
retained descriptor pin after permitted originals disappear. The exact v1 artifact
inventory contains only the descriptor, summary, manifest and indexed request,
response and exchange files. It contains no runtime or credential attestations.
Lifecycle/frame diagnostics in the integration result are in-memory CONTROLLED
observations, not independently retained REAL evidence. No additional files are
inserted into the frozen paired inventory.

## Failure and cleanup

An atomic one-use guard is set before the first await, preventing concurrent calls
from allocating a second simulated process. Sweep 1 finishes before sweep 2 starts.
No method retries a request, reconnects or relaunches. Admission failures become
terminal REJECTED; bounded partial exchanges remain accessible through copied
diagnostics. Misuse after a completed accepted result does not mutate that result.
Premature acceptance rejects, and missing caller authority is a Python signature
error. Wrong authority or modified retained evidence cannot become acceptance.

Cleanup runs after any attempted launch, including startup, transport, liveness,
drift, budget and cancellation failures. Closing the supplied session cannot
suppress its exception; backend disposal is still attempted. Success requires all
four exact true observations: reaped, connection closed, listener closed and
credentials disposed, no errors and a non-live final process observation. These are
simulated attestations, not evidence that real credentials or sockets existed.
Cleanup failure prevents package writing and acceptance. Its failure remains in
diagnostics alongside the primary exception cause. Invalid non-simulated backends
are refused before launch or cleanup calls.

## Resource accounting

Existing pagination ceilings remain 52 pages/sweep, 104 combined, 16,536 total
request bytes, 52,832 response bytes and 832 query operations. Selected request
allowances are checked before writes; actual responses and page/sweep accounting
are validated by the production two-sweep logic.

Reuse `TerrainFrameBudget`: two establishment, three subscription, bounded sweep
frames and one graceful QUIT, at most 838 post-auth frames. Count every supplied
frame independently of receipts and reconcile every query's frame delta. The
initial profile allows only its exact subscription, one selected page request and
completion PING/PONG sequence; unknown or duplicate packets reject. A cleanup
frame and 19 projected stream bytes are reserved before further traffic admission.

Frame records retain lengths and SHA256. Projected encrypted lengths add 16 to
plaintext frame lengths and are explicitly labeled simulated; no encryption was
performed by this layer. The cap is at most `838*32767` projected stream bytes.
Actual received chunks and incomplete decoder bytes must fit the selected buffer
cap, at most the existing 65,536-byte feed ceiling. Health observations also bound
reported buffered bytes and require quiescence at completion barriers. Supplied
backend functions must cooperate with cancellation; arbitrary hostile Python code
is not sandboxed by this interface.

Selected startup/page/evidence/session/cleanup/finalization limits are positive
and capped by the design's 60/15/10/2660/20/15-second envelopes. A monotonic clock
and `asyncio.wait_for` bound acquisition waits. The combined acquisition allowance
also uses the selected number of pages; cleanup has a separate reserved deadline.
Synchronous bounded package writing is checked against the finalization deadline
before publishing its path. Caller-driven offline acceptance is separate from the
released process/session lifecycle. These settings are safety caps, not latency or
throughput measurements.

Paired storage is bounded by the existing 1 MiB/315-file contract. Simulated native
log evidence is at most 262,144 bytes per snapshot and is parsed against the exact
exchange. No cumulative logs are duplicated into the package. Actual native RSS,
instruction execution, kernel buffer behavior, capture draining and private-key
disposal remain unresolved native gates. This slice cannot establish them.

## Verification and remaining native work

Tests exercise public acquisition/acceptance and production replay. External
fixtures emit deterministic synthetic responses and frame streams; validators
are not replaced. Coverage includes 1/5/6/255/256 tiles, partial final pages,
missing/duplicate/stale responses, drift, context change, process/connection failure,
timeouts, frame/byte/query caps, cleanup failure, concurrent startup, evidence
mutation and cleanup-independent fresh-process replay. A 256-tile region remains
partial coverage of a 64x64 map.

Before native integration, specify and review the separate REAL outer evidence
contract, exact operation authorization, phase-dependent inventories, native log
scopes, endpoint/public-key/runtime commitments, memory/buffering/deadline admission
and independently pinned completed evidence. Complete controlled native transport
and adversarial implementation gates before separately requested seal preparation
and one exact attended authorization. This result grants none of those actions.

Baseline-1 and its 26 digests remain unchanged. Historical native REAL_PASS remains
supported; historical complete offline acceptance remains AUDIT_BLOCKED with 13
missing inputs. Historical bytes are neither regenerated nor reclassified.
