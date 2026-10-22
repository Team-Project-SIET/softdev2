# Single-page terrain proof: sealing and authorization

This repair supersedes the conflated final-seal authorization instructions in
`p08-15-3-single-page-real-proof-preparation.md`. It changes preparation lifecycle
only. No OpenTTD launch, live connection, native request, or approval is issued.

## Contract and root cause

Previously `validate_final_prelaunch(native=True)` required an immutable record
with `AUTHORIZED_IMMUTABLE_PRELAUNCH` and `authorized_one_launch=True`. That was a
correct launch restriction but made unauthorized immutable preparation impossible.

`TerrainCandidate.preflight()` remains the candidate admission gate.
`terrain_seal.seal_candidate(candidate, seal_directory, attempt_directory)` now
publishes a `SEALED_UNAUTHORIZED` record with `authorized_one_launch=False` and
`attempt_state=RESERVED`. `terrain_attempt.validate_immutable_seal()` checks the
record, read-only modes, digest, complete source inventory, candidate identity,
assets, ownership, runtime materializations, historical protection, request,
argv/environment, and manifest without granting permission or consuming an attempt.

`validate_final_prelaunch(native=True)` still requires all of those checks PLUS
`validate_authorization()`. Neither the existing boolean operator argument nor a
well-shaped JSON approval can pass production authorization verification. The
backend independently calls that strict gate immediately before launching; it
also requires the existing one-shot owned launch claim. Candidate or seal-only
execution is rejected before attempt creation and before backend invocation.

## Authorization boundary

The inspected native proof mechanisms use explicit caller permission arguments;
there is no established trusted issuer of separately digest-bound approval
artifacts. This repair implements the interface and fail-closed validation only,
as permitted by the task. **No production issuer is configured.** Native execution
remains inaccessible even with a correctly shaped artifact until that issuer is
separately established and reviewed. No signing scheme is invented.

A future authorization must bind `seal_sha256`, `attempt_identity`,
`attempt_directory`, and integer `authorized_launch_count=1`, and carry operator
approval provenance accepted by the trusted issuer. It must not modify PRELAUNCH.
The injected `authority` callback is a controlled validation seam only; production
launch callers cannot inject it. A controlled approval is never a real approval.
Any future runtime-source change to wire a trusted issuer invalidates the current
source freeze and requires renewed preparation/review before launch.

## Reservation, consumption, and retention

The terrain namespace uses unique `terrain-single-page-<uuid>` reserved identities,
not qualification attempt numbers. The attempt destination is absent at sealing.
A reservation is not consumption. `consume_authorized_attempt()` demonstrates
controlled exact-binding validation followed by atomic exclusive directory claim
and retained `authorization-consumed.json`. Reuse is rejected even after a failed
controlled attempt. Existing real execution claims its destination before entering
the backend and writes `native-launch-claimed.json` immediately before Popen.
The real authorization-to-consumption integration remains closed pending the
trusted issuer; no controlled receipt enables it.

## Immutable persistence and limits

The seal is staged separately, file contents fsynced, files made 0444, directory
made 0555, and atomically published with Linux `renameat2(RENAME_NOREPLACE)`.
The parent directory is fsynced; the seal is reread and fully validated. Failure
retains staging or published evidence and does not substitute a second seal.
Read-only permission bits are supplementary: candidate, source, runtime-copy,
PRELAUNCH, and manifest digests are checked independently. A future approval must
bind the exact PRELAUNCH SHA256; every source identity is rechecked at launch.

Source remains a 64x64 seed-42 new-world recipe, not save-byte correspondence.
Rectangle `[1,1,5,1]` yields tiles 65–69 in row-major order. Request ID remains
`terrain-single-page-review`, cursor 0, terminal page of five records, request
111 bytes. Selected response maximum 420 bytes; command maximum 508; absolute
application ceiling 512. One application request, at most eight query operations,
226 getter calls (`5*44+6`), six lifecycle frames (`2+3+1`), maximum 14 post-auth
frames (`8+6`), nominal 10 (`4+6`). No polling requests, retry, reconnect or resume.
Native-read evidence, correlated receipt, post-yield liveness, exact coverage,
accounting, child reap, independent endpoint cleanup, and post-run integrity
remain mandatory. The existing capture and failure retention behavior is unchanged.

## Controlled verification

Lifecycle tests exercise unauthorized seal creation/validation, read-only modes,
source and seal mutation, candidate/package mutation, missing and fake approval,
wrong digest/identity/destination/count, simulated one-shot consumption/replay,
failure retention, no automatic authorization, no attempt consumption by sealing,
and zero process/connection activity. Existing fake-child, tagged 15.3 VM,
serializer, collector, transport/accounting, cleanup, historical, P08/P05 and
ordinary regressions remain required. Controlled simulation cannot issue native
permission or establish real terrain acquisition.
