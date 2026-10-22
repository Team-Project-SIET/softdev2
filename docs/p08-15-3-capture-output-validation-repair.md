# Terrain capture-output validation repair

`CONTEXT.md` is the architecture authority. This is a controlled lifecycle repair;
no native execution, operator authorization, native attempt allocation or resealing
is part of this task.

## Historical failure and ownership boundary

Attempt `terrain-single-page-9ee0357adb064852a2f98d1d0a1d6b54`, bound to seal SHA256
`1dcb8c6bdb1660d7d9bfe3b36f85cb4362e0b5dadd58bf7579d6cfaafc5440b8`, is permanently
consumed. Its retained result is `REAL_FAILED` / `SOURCE_INTEGRITY_FAILED`, with zero
process launches, connections and application requests. The authorization claim
and invocation marker survive; neither permits reuse. The old seal, claim,
result, cleanup and manifests are preserved byte-for-byte.

The backend created two empty capture files before its last pre-Popen validation.
Candidate preflight compared every runtime file with 17 declared input paths.
The two generated outputs made that set contain 19 files, causing
`Unexpected runtime cache input`. All 962 persistent frozen hashes matched.
The original traceback was not retained. The diagnosis relies on retained
markers, source execution order and controlled differential reproduction.

Persistent canonical configuration templates, source, executable and graphics
identities are frozen inputs. Their runtime copies and the credential live in a
disposable owned workspace. The separate attempt destination contains durable
claims and persistent generated evidence. Before this repair, captures were
inside the workspace but absent from its ownership graph; directory containment
incorrectly made their creation an input-set mutation.

## Implemented correction

The existing launch specification and cleanup contract place captures under the
workspace's `logs` directory and copy bounded bytes into the attempt afterwards.
Moving them would change that shared contract and the exact claim file allowlist.
The smaller correction therefore keeps the paths and declares exactly:

- `<owned workspace>/logs/stdout.log`
- `<owned workspace>/logs/stderr.log`

Both paths are explicit `RUNTIME_EPHEMERAL` outputs in candidate and seal ownership
graphs. The candidate binds their exact paths. Their hashes are never frozen input
identities. The parent is an owned, nonaliasing directory with mode 0700.

Preflight defaults to the `absent` phase: neither output may exist. The `prepared`
phase requires both outputs to be regular, singly linked, owned mode-0600 files
of zero length. The `running` validation phase permits changing capture content
within the existing 262144-byte bound. It does not authorize execution.

Capture creation uses exclusive creation, `O_NOFOLLOW`, an opened directory
file descriptor and post-open descriptor inspection. Final validation compares
file descriptors with the current path inodes. Symlinks, directories, devices,
wrong output paths, input/output collisions and unapproved additional files fail.
There is no `logs/*` exclusion or general allowance for unknown workspace files.
Immutable runtime inputs retain exact paths, regular file types and content hashes.

## Validation ordering and Model A

Read-only candidate and backend preflight check capture declarations and launch
specification paths before durable claim acquisition. Exact direct TTY confirmation,
process-bound Model A authorization and exclusive durable claim rules remain.

The production backend validates the launch before creating its durable invocation
marker, then opens the approved captures. Immediately before Popen it repeats the
immutable seal/source/runtime-input validation, validates generated outputs
separately, checks their descriptors, and preserves claim/operation/budget checks.
No validator is skipped. Model B remains separately fail-closed. No environment,
automatic confirmation, retry, reconnect or resume option is added.

## Controlled reproduction and diagnostics

The regression first failed against the original real candidate validator after
capture creation. It now accepts exactly the two declared outputs and rejects
extra files, changed/missing inputs and capture substitutions. Controlled tests
exercise the production backend's setup and final validator, use test-only
controlled grants, substitute the process-creation boundary, and verify one fake
Popen invocation, invocation-marker binding, cleanup and no second launch. No
production authorization or live Admin session is created.

Future post-claim failures retain stage, stable failure code, failing function,
exception cause frames, expected/actual input counts, unexpected/missing paths,
identity mismatches, claim consumption, Popen invocation state, launch count and
cleanup outcome. Cause chains, frame lists, messages and path lists are bounded.
Tracebacks omit source lines and locals; credential bytes, sensitive environment
values and labelled password/secret/token/private-key values are redacted. No
traceback is added to the historical attempt.

## Required next work

This repair changes frozen source and adds capture/diagnostic modules. Existing
seals are source-stale and remain immutable. A separate task must regenerate the
complete source/dependency inventory and owned runtime assets, verify settled
source, and prepare one fresh unauthorized Model A seal with a fresh destination.
Only a subsequently authorized attended one-shot execution can provide real terrain
proof. The historical consumed attempt must never be reused.

The frozen source changes requiring future resealing are
`proof/terrain_preparation.py` (phase-aware input/output admission),
`proof/terrain_seal.py` and `proof/ownership.py` (explicit output ownership),
`proof/terrain_attempt.py` (validation phase and failure retention), and
`proof/terrain_native.py` (capture creation and final descriptor checks).
The inventory must additionally include `proof/terrain_capture.py` and
`proof/terrain_failure.py`. The TTY implementation, authorization policy,
GameScript bridge and application budgets are unchanged.
