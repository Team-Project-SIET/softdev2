# Operator-attended local terrain proof

Model A is explicitly approved for this local development proof. It preserves
source integrity, exact operation binding, durable one-shot safety, bounded
evidence, and independent cleanup verification. Malicious same-OS-user execution
is outside its scope. A TTY does not authenticate an independent operator or
cryptographically establish human presence. No native execution is authorized by
this implementation or its tests.

## Preparation and attended execution

Preparation remains separate. A future `seal_candidate(...,
authorization_policy="OPERATOR_ATTENDED_LOCAL_PROOF")` creates only a
`SEALED_UNAUTHORIZED`, `RESERVED` record. Existing records are not rewritten.
The default policy remains `INDEPENDENTLY_AUTHENTICATED_PROOF`; its issuer gate
continues to reject production approval when no trusted issuer is configured.

The separate module entry point is:

```text
python -m app.simulation.openttd.proof.terrain_operator preflight --seal-directory PATH
python -m app.simulation.openttd.proof.terrain_operator run-attended --seal-directory PATH
```

The second command is for a future separately authorized operator action only.
Help, import, construction and preflight do not launch, connect, create credentials,
authorize or consume an attempt. No preparation API calls this entry point.

After immutable seal and current source validation, attended execution requires
interactive stdin/stdout and opens `/dev/tty` directly. It displays the executable,
version, seal digest, attempt identity, destination, command, rectangle, tile IDs,
launch/request limits, no-retry rule and source result. Confirmation must be exactly:

```text
CONFIRM FULL_SEAL_SHA256 EXACT_ATTEMPT_ID EXACT_ABSOLUTE_DESTINATION
```

There is no default approval, environment approval, force/yes flag or approval
copied from a candidate. Declining or an invalid source does not consume an attempt.

## Authorization and launch path

`LocalOperatorAuthorization` binds the exact seal, attempt, destination, operation
and allowance of one launch. It records `LOCAL_OPERATOR_ATTESTED`, current PID,
Linux process start identity and an action nonce. An internal in-memory issuance
marker distinguishes the attended action from a fabricated dataclass or persisted
record. This is a cooperative interface safeguard, not protection against malicious
same-user Python code. Controlled confirmations use a separate marker and
`CONTROLLED_OPERATOR_ATTESTED`; the production backend rejects them.

The typed context flows through `authorized_native_run` → `execute_single_page`
→ `SinglePageNativeBackend.bind_authorization` → `validate_final_prelaunch`.
Missing context is never approval. Seal policy must explicitly select Model A.
Model B artifacts and controlled authority callbacks remain distinguishable and
cannot create a local production context.

## Durable claim and ownership

The existing attempt-directory claim is the sole replay ledger. Atomic exclusive
`mkdir` acquires the destination. Parent directory, claim file and destination are
fsynced. `authorization-consumed.json` records `STARTED` and exact source/action
bindings. STARTED means the launch allowance has been irrevocably acquired; it does
not assert successful Popen. The directory itself remains consumed if writing or
fsync fails. Concurrent claimants have at most one winner.

Before acquisition the destination must be absent. Afterwards continuation requires
the exact claim-file digest, matching PID/start identity/nonce, exact seal and
operation bindings, current ownership, mode 0700, and only the prescribed in-flight
files. Another process or arbitrary occupied directory cannot continue. Completed
results or retained failure files prevent continuation.

`launch-claim.json` is an executor witness, not a second replay ledger.
`native-launch-claimed.json` is exclusively created and fsynced before Popen to burn
the backend invocation even across replacement backend instances. Source, seal,
authorization and claim ownership are revalidated immediately before Popen. There
is no retry, reconnect or resume. Popen failure retains the consumed claim and
failure evidence, while the process-launch count remains zero. A crash never
releases an acquired attempt.

## Evidence, cleanup and fixed bounds

The existing query receipt, native-read evidence, response/yield liveness, exact
row-major coverage, accounting, bounded capture, source postcheck and structured
Linux endpoint cleanup remain mandatory. Future seals also include explicit
`game_port` and `admin_port` matching their existing endpoint tuple, as required by
the existing cleanup verifier. The native backend reuses `TerrainCandidate.preflight()` for exact pinned asset
validation and reads the existing owned Admin key. It does not require the generic
backend's absent `graphics-identity.json`, generate a key, or create an artifact.
No transport operation was added.

The fixed proof remains OpenTTD 15.3, 64×64 seed 42, rectangle `[1,1,5,1]`, tiles
65–69, request ID `terrain-single-page-review`, cursor zero. Request size is 111
bytes; selected response ceiling 420, command ceiling 508, absolute ceiling 512.
There is one application request; query operations ≤8; native getters ≤226
(5×44+6); lifecycle frames 6; post-auth frames ≤14 (8+6).

Failures retain bounded result and cleanup evidence. Typed local failures
separate seal invalidity, missing authorization, declined confirmation, source
integrity, claim acquisition, already consumed attempts and launch failure.
Existing proof acceptance and cleanup failures still fail the overall result.

## Stale seal and next tasks

The old seal `0d98f819f085b66a098ccb8c787de174cc0625bc6caea689885ff42ec142a663`
and reserved attempt `terrain-single-page-809378528d2d4b36a4e1c5ef9cb68b57`
remain unchanged, stale and unconsumed. They cannot select Model A implicitly.
No retirement or fabricated consumption is performed. Any future supersession
should be an additive lineage record referencing both identities.

A separate preparation task must regenerate assets and source inventory from
settled code, preflight them, use a fresh attempt/destination, and seal the explicit
local policy and cleanup port fields. It must not launch. Only a subsequent,
explicitly authorized attended execution may confirm that new seal and acquire
its one-shot claim. This task creates no real approval and no replacement seal.

Controlled tests exercise exact confirmations, local/independent trust separation,
context propagation, source revalidation, owned continuation, concurrent claims,
failed fake Popen, retained failures and fake-child query/cleanup acceptance.
No controlled approval can authorize production Popen. Real terrain acquisition,
full-region repeatability, qualified-production correspondence and construction
legality remain unproven.
