# D5-CORRIDOR-EXTENSION-3 — Phase A record

Status: **IN PROGRESS — A0 staged, waiting on the operator's Gate C signature.**
The consumed attempt `D5-CORRIDOR-EXTENSION-2` and its evidence remain
immutable; nothing here re-verifies the corridor, performs any construction,
or stages a construction candidate. Phase B is not authorized by this
document.

## 1. Baseline and evidence references

- Verified consumed baseline (immutable of record):
  `artifacts/experiments/d5-corridor-extension-native-candidate-2/` —
  `ROAD_FULL 50096→50864` £1,144, `ROAD_CONNECT 50095–50096` £142, bay truck
  stop at `50863` front `50864` £307 (SID 2), total £1,593, funds
  £492,149 → £490,556, route 28/29 pairs, first failure pair 28
  (`50864 → 50863`), verdict `ATTEMPT_FAILED_EVIDENCE_PRESERVED`.
- Root cause of record (Explanation A, physical connectivity defect; the
  verifier was not weakened):
  `docs/d5-corridor-extension-2-connectivity-postmortem.md` (independently
  reviewed, final PASS recorded in its §5).
- Consumed prerequisite world: the pinned D4 candidate-5 after-save
  (`a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261`), the
  same authoritative source world every D5 ceremony binds.
- Consumed survey evidence of record for the branch tiles:
  `artifacts/experiments/d5-terrain-survey-native-candidate-1/`
  (`D5-TERRAIN-SURVEY-1`); it never observed tile `50862` and predates the
  spur decision, so no old observation is recycled as fresh evidence here.

## 2. Corrected target design (pinned, offline)

From the postmortem §3: the existing `ROAD_FULL` and `ROAD_CONNECT` ops stay;
a **dedicated spur operation kind** (fresh eligibility predicate; the
existing `full` and `road` predicates both refuse this corner state and were
not broadened) performs `GSRoad.BuildRoadFull(50864, 50863)`; the bay truck
stop moves to `GSRoad.BuildRoadStation(50862, 50863, ROADVEHTYPE_TRUCK,
STATION_NEW)`; the route witness grows to 31 tiles / 30 pairs ending
`… 50095, 50096, 50352, 50608, 50864, 50863, 50862`. The spur's native
receipt is validated against the natively observable facts
`pairs_ok == 1` and `covered == 2`; the 50862-facing road bit of 50863 is
proven systemically by the fail-closed terminal witness pair 29 (the
GameScript surface exposes no road-bits getter — limitation of record).

## 3. Fresh survey candidate — A0

- Identity: **`D5-CORRIDOR-EXTENSION-3-SURVEY-1`** (unique; no consumed
  identity or seal reused).
- Candidate directory:
  `artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-1/`
- Staging: `PRELAUNCH PASS` (prepare re-ran the full preflight). No process
  launched, no claim, no authorization artifact; one EndpointReservation
  granted for the prelaunch record.
- Seal: `sha256(PRELAUNCH.json) =
  5d57ee5c5dc87783a4935a09bdb3b0c3a506bd3182d507f4963f5abf2626bd35`.
- Plan digest:
  `82246eb67f0fa6dfc0631a1fe7b84e84f963f9b7d8c8919fe4a064e8c98ef8d9`
- Instrument: the protocol-7 terrain survey (read-only), extended exactly for
  this attempt: schedule is now **ten exchanges** — `radius-00`, then tile
  facts for `50095, 50096, 50352, 50608, 50864, 50863, 50862`
  (`tile-00`…`tile-06`; `50862` is the added observation), then the
  acceptance pair `accept-00` (control `50351`) and `accept-01` (stop
  `50862`). Budgets unchanged and verified: 0 max cost, 32-request cap,
  512/512 byte bounds, 1 launch, 0 reconnects, 300 s total. Funds expectation
  pinned at the D4 close-out level exactly.
- The GameScript handler (`d5_freight_package/main.nut`, protocol-7
  `TerrainHandle`) carries the matching pinned tables and refuses any tile
  outside its pins before any observation.

Facts the survey observes per tile (`GSTile`): slope, min/max height,
buildable, owner, tree/water/coast/farm/rock/rough obstruction predicates,
and the four `HasTransportType` road/rail/water/air presences; the acceptance
op additionally reports the cargo-1 acceptance in eighths under the
measured native radius. Facts protocol 7 cannot observe and that no receipt
will claim: vehicle reachability, road-bit direction presence (no road-bits
getter exists), station buildability before the front road exists, and any
pathfinding. These remain UNKNOWN until the native construction attempt
itself.

## 4. Survey authorization status

**REFUSED BEFORE LAUNCH — AUTHORIZATION ABSENT (2026-10-30 survey-execution session).**
The staged candidate's canonical authorization payload digest, to be verified against the recomputed payload over the staged bytes before signing, is:

`38d31d6f490ca33399840434a66d633ecd8b1bf63ab95558da2f33376e524208`

That digest **re-verifies exactly** against the staged bytes (recomputed via
`staged_terrain_authorization_payload_digest`), and the PRELAUNCH seal
`5d57ee5c…26bd35` re-verifies byte-for-byte. But the candidate directory
carries no `AUTHORIZATION.json`, no `CLAIM.json` and no
`LAUNCH-CONSUMED.json`, and the repository's own replay verifier
(`corridor_terrain_survey_native.py verify`) returns
`AUTHORIZATION_UNVERIFIED` / `CLAIM_ABSENT`. OpenTTD was therefore never
launched. Nothing was repaired, rewritten, re-signed or replaced; the exact
failure is the missing operator signature artifact.

## 5. Survey results and unavailable observations

**REFUSED — EXECUTION FAILED AFTER AUTHORIZED LAUNCH (2026-10-31 survey-execution session).**

### 5.1 Authorization verified — gate passed

With the operator's Gate C Option 1 signing complete, the staged
`AUTHORIZATION.json` verified independently, in this order:

1. `AUTHORIZATION.json` present (3186 bytes); `CLAIM.json` and
   `LAUNCH-CONSUMED.json` absent pre-launch.
2. PRELAUNCH seal recomputed:
   `5d57ee5c5dc87783a4935a09bdb3b0c3a506bd3182d507f4963f5abf2626bd35` — match.
3. `plan_policy.plan_model_digest` recomputed against a freshly built
   protocol-7 plan model — match:
   `82246eb67f0fa6dfc0631a1fe7b84e84f963f9b7d8c8919fe4a064e8c98ef8d9`.
4. `plan_policy.plan_digest` recomputed independently from the staged
   schedule (`plan_digest_of`) — match:
   `f091754de6d364d226b77555766ed5d2f3f3dfb38e23f42f5d3757fd62246c3a`.
5. Canonical authorization payload digest recomputed from the staged
   `PRELAUNCH.json` metadata + seal — match:
   `38d31d6f490ca33399840434a66d633ecd8b1bf63ab95558da2f33376e524208`; the
   record's `payload` equals the rebuilt payload by dict equality.
6. RFC 8032 Ed25519 signature verified against the pinned operator anchor
   (identity `sha256-ed25519-public-key:cbb63ff58f17f13df3e1be0735fad18497e3a0c6ad6b5dd55491d708ae40c614`);
   authorization record digest
   `ad89f81baab84a233ab919f2130223c31fdca4cf0b00cb46cb328b41812244c7`.
7. Repository procedure `operator_authorization.verify_authorization` — PASS.
8. Full native preflight — `PREFLIGHT PASS`.

### 5.2 Execution — failed at Admin authentication, exchange 0 of 10

The authorized one-launch ran the pinned OpenTTD 15.3 binary
(`binary_sha256 276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`)
in the staged isolated workspace. The server booted, all GameScripts
reported ready, and the Admin TCP connection was accepted
(`Client connected from 127.0.0.1 on frame 7`) — then the client-side
`encode_join_secure` raised exactly:

```
AuthProtocolError: invalid secure client identification
```

Recorded status: `FAILED`, 0 requests, `last_status NOT_DISPATCHED`,
`state_changed: false`. Root cause (derived, read-only code analysis after
execution): the JOIN_SECURE client name is the attempt identity
`D5-CORRIDOR-EXTENSION-3-SURVEY-1` (32 bytes), which exceeds the OpenTTD
15.3 protocol-7 join-string capacity of 25 bytes including the terminating
NUL (`secure_admin.py encode_join_secure` refuses ≥25). The length check
fires before any frame is written, so the server sees an accepted socket
close with no client name (`'' () has disconnected`). No survey op was ever
encoded or sent; no tile or acceptance measurement exists.

### 5.3 Candidate consumed

The one-shot lifecycle completed even though authentication failed: the
grant was minted, `CLAIM.json` (consumed) and `LAUNCH-CONSUMED.json` were
written. `result.json` records
`error: "AuthProtocolError: invalid secure client identification"`,
`native_launches: 1`, `connections: 1`, `exchanges: []`,
`verified: false`. Cleanup completed: process reaped (pid 26416,
returncode 0), listener closed, credential removed, endpoint reservation
released, workspace disposed. Evidence preserved
(`result.json`, `cleanup.json`, `CLAIM.json`, `LAUNCH-CONSUMED.json`,
`frames.json`, `stderr.log`, `stdout.log`). The repository replay verifier
cannot run for this candidate (`verify_terrain_attempt` requires
`runtime-identity.json`, never written because execution halted before
identity pinning). **This candidate is permanently consumed and must never
be retried.**

SHA-256 of the preserved evidence: `result.json`
`faa17d5176efb3eba9952c002f3b56c13b488c5fd47b16323a4237c4690a2e3c`;
`cleanup.json`
`fee6aa63e44a9bd2106510ff61daa64318ff73c7ab4719a2bf2689a68038c959`.

Every tile and acceptance measurement in §3's schedule remains UNKNOWN, in
addition to the structurally unobservable facts listed there.

## 6. Phase A status

- `A0_SURVEY`: **FAILED** (authorization verified and launch executed, but
  the secure Admin join refused the 32-byte attempt identity against the
  25-byte JOIN_SECURE name capacity; 0 of 10 exchanges ran; no world
  mutation; one-shot consumed; evidence preserved)
- `A1_IMPLEMENTATION`: NOT STARTED (gated on the verified survey)
- `A2_INDEPENDENT_REVIEW`: NOT STARTED
- `PHASE_A`: NOT READY (A1's spur operation, station move, 31-tile witness,
  receipt validation and test coverage are implemented only after A0 verifies)

Note: the candidate was never consumed (no `CLAIM.json`, no
`LAUNCH-CONSUMED.json`), so this refusal does not burn the one-shot attempt;
once the operator's documented Gate C signing step (Option 1, repository
tooling only) produces a valid `AUTHORIZATION.json` over the verified
payload digest above, the still-staged candidate may be re-presented for
execution. No private key material may ever be pasted into chat or logs.

## 7. Exact next action required from the operator

Complete the documented trusted local Gate C signing step (Option 1,
repository tooling only), then report back; the survey may then execute
exactly once. No private key material may ever be pasted into chat or logs.

## 8. Remediation and fresh-candidate staging (appended)

Full detail: `docs/d5-corridor-extension-3-handshake-remediation.md`. Summary
of the record, preserving all prior history above unchanged:

- The `D5-CORRIDOR-EXTENSION-3-SURVEY-1` candidate (§3, and the earlier
  roadmap in §7 when this appendix is read after the 2026-10-31 update) was
  **permanently consumed** by the `JOIN_SECURE` handshake failure
  (`AuthProtocolError: invalid secure client identification`) and its
  failure evidence is preserved; it is never retried and never rewritten.
- Root cause: the 32-byte attempt identity exceeded the 15.3 JOIN_SECURE
  client-name capacity (25 bytes including NUL → 24-byte payload), and no
  stage before the encoder validated the identity. OpenTTD unmodified.
- Remediation: shared fail-closed `validate_join_secure_string` in
  `secure_admin.py` (UTF-8 byte length, empty, NUL, 24-byte payload),
  wired into `encode_join_secure` (defensive, before any frame write) and
  into terrain-survey preparation (before any candidate artifact) and
  PREFLIGHT (independent re-derivation on the sealed bytes). Fresh compact
  identity `D5CE3-SURVEY-2` (14 bytes); milestone unchanged.
- Tests: 166 passed, 1 skipped, 0 failed across `test_secure_admin.py`,
  `test_corridor_terrain_survey_native.py`,
  `test_corridor_freight_native.py`,
  `test_corridor_accept_survey_native.py`,
  `test_corridor_terrain_survey.py`. Exact commands in the remediation doc.
- Independent fresh-context review: **PASS** (capacity pinned in-repo from
  `ottd/src/network/core/config.h`; no semantic changes to authorization,
  claims or protocol-7; no consumed evidence touched). One cosmetic
  error-message note was fixed narrowly afterwards; affected tests re-ran
  green.
- Fresh staged candidate: `D5CE3-SURVEY-2` at
  `artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-2/`;
  `PRELAUNCH PASS` and independent `PREFLIGHT PASS`; PRELAUNCH seal
  `c76992187b0ace7b317e9f992f678bac675f9f89711cd87730fa8d0456aaa2b6`; plan
  model digest `82246eb67f0fa6dfc0631a1fe7b84e84f963f9b7d8c8919fe4a064e8c98ef8d9`;
  schedule digest `f091754de6d364d226b77555766ed5d2f3f3dfb38e23f42f5d3757fd62246c3a`;
  authorization payload digest
  `38dd8ecc86f5d86edc3474bdd88e0aff4f7022be56d8891b15b06c547f3abbf9`; no
  claim, no authorization artifact; no launch.
- Phase A remains: `A0_SURVEY` NOT EXECUTED for the fresh candidate
  (waiting on the operator Gate C signature, exact steps in the
  remediation doc §8); `A1_IMPLEMENTATION` NOT STARTED; `PHASE_A` NOT
  READY.

## 9. Evidence-reliability remediation (appended 2026-10-31, before any launch)

D5-CORRIDOR-EXTENSION-3 Pre-Launch Safety Audit remediation for candidate
`D5CE3-SURVEY-2` (`artifacts/experiments/
d5-corridor-extension-3-survey-native-candidate-2/`). This is a source/code
remediation record only: **no candidate lifecycle ran, nothing was staged,
signed, claimed or launched, and operator launch approval remains explicitly
ungranted.** The §3–§8 history above is unchanged and stands as written.

### 9.1 Verdict of record

`PARTIAL` at audit time → remediated source, offline-verified; the audit's
other findings stand: Gate C authorization verified, 3,491 frozen entries
match live bytes, `AUTHORIZATION.json` signature verifies against the pinned
anchor, no `CLAIM.json`, no `LAUNCH-CONSUMED.json`, A0 NOT executed,
Protocol-7 survey interface verified observational, absolute engine-level
zero-mutation NOT established (Console stdin remains an unrestricted local
authority channel: an accepted limitation of record, not a defect this
remediation could remove by code).

### 9.2 R1 root cause — premature one-shot consumption

Audit-time lifecycle wrote `CLAIM.json` before `backend.preflight`; a
preparation failure after the claim permanently consumed the candidate with
little usable evidence. The audit also classified "consumed" two different
ways; the corrected semantics of record:

| State | Marker | Meaning | Irreversible |
|---|---|---|---|
| AUTHORIZED | `AUTHORIZATION.json` | operator-issued, anchor-verified authorization exists | no (a fresh candidate reissues it) |
| CLAIMED | `CLAIM.json` | candidate-level one-shot claim exists; no second authorization mint is possible | **yes** |
| LAUNCH_CONSUMED | `LAUNCH-CONSUMED.json` | process-boundary consumption marker; written atomically immediately before `Popen` | **yes** |
| PROCESS_STARTED…COMPLETED | stage journal | execution progress of record | see §9.4 |

"Consumed" means CLAIMED for candidate reuse; "launch-consumed" means
LAUNCH_CONSUMED for the process boundary. Launch-boundary validation
failures before `Popen` leave the candidate CLAIMED-but-unlaunched: the
claim is spent, the process was never created, no snapshot confusion results.

### 9.3 R1 remediation — implemented lifecycle

```text
terrain_survey_preflight (pure re-derivation; runs nothing)
    |
    v
stage journal opens (PRE-CLAIM facts: RUN_PREFLIGHT, BACKEND_PREFLIGHT)
    |
    v
backend.preflight  (read-only: credentials, pins, ownership;
    |                creates no external state, repeatable, verified here
    v                against the real TerrainNativeBackend preflight)
AUTHORIZATION_VERIFIED (verify_authorization against the pinned anchor)
    |
    v
CLAIM_CREATED (atomic O_CREAT|O_EXCL, fsynced — the last reversible-free gate)
    |
    v
backend.launch (mandatory trust chain: grant, claim, re-verify, freeze,
    |            launch-critical stat identity, argv, owned environment)
    v
LAUNCH-CONSUMED.json at the Popen seam  ->  PROCESS_STARTED ...
```

`backend.preflight` was verified read-only before the reordering was
implemented (it opened nothing and reserved nothing; the endpoint re-check
uses allocate-then-close of the already-pinned endpoints). The claim is
atomic and race-safe (`O_CREAT | O_EXCL`); duplicate claims are refused;
two concurrent attempts cannot both claim; no process can be spawned without
the full authorization + one-shot boundary verification chain. Fail-closed
ordering: every safely reversible preparation now precedes the claim. A
future candidate must restage through the established process (§9.8); the
reordering does NOT retroactively un-consume any historical candidate.

### 9.4 R2 root cause and remediation — replay fail-closed

Audit-time `verify_terrain_attempt` read `runtime-identity.json` unguarded
(a `FileNotFoundError` could crash replay; candidate-1's retained state
reproduced it). Remediated replay loads every retained artifact through the
structured `_load_evidence_json` / `_versioned_evidence` states
(`PRESENT`, `ABSENT`, `MALFORMED`, `UNSUPPORTED_SCHEMA_VERSION`,
`INVALID`) and returns structured verdicts (`SURVEY_COMPLETION_VERIFIED`,
`ATTEMPT_FAILED_EVIDENCE_PRESERVED`, `PHASE_HALTED_EVIDENCE_PRESERVED`,
`EVIDENCE_INCOMPLETE`, `EVIDENCE_INVALID`,
`AUTHORIZATION_UNVERIFIED`, `UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED`).
Missing evidence NEVER becomes success; the verdict preserves
not-reached vs reached-and-failed vs undetermined, names the
`reached_stage` and per-artifact `evidence_states` when a journal or load
survives, and refuses verdict-vs-artifact contradictions outright.

### 9.5 New evidence schemas

- `d5-terrain-survey-attempt-progress-v1` (`attempt-progress.json`,
  `TerrainAttemptJournal`): ordered stage entries
  (`RUN_PREFLIGHT`, `AUTHORIZATION_VERIFIED`, `CLAIM_CREATED`,
  `BACKEND_PREFLIGHT`, `LAUNCH_BOUNDARY`, `PROCESS_STARTED`,
  `PROCESS_READY`, `ADMINPORT_CONNECTED`, `JOIN_SECURE_STARTED`,
  `AUTHENTICATED`, `WELCOME_RECEIVED`, `WELCOME_VERIFIED`,
  `RUNTIME_IDENTITY_WRITTEN`, `SUBSCRIPTION_ESTABLISHED`,
  `SURVEY_EXCHANGE_STARTED`, `SURVEY_EXCHANGE_COMPLETED`,
  `CLEANUP_STARTED`, `CLEANUP_COMPLETED`, `TERMINAL_SUCCESS`,
  `TERMINAL_FAILURE`), each `COMPLETED` or `FAILED` with a public detail
  (`label`, `error_type`) never an error message that could carry
  authentication material. Rewritten atomically (temp-file + `os.replace`)
  at every transition, so an abrupt death preserves the last confirmed
  stage; a stage is never recorded before its boundary completes. A
  post-crash attempt proves only stages whose journal write completed;
  an in-flight stage transition is by construction unprovable.
- `d5-terrain-survey-handshake-evidence-v1` (`handshake-evidence.json`):
  `join_secure` ∈ {`NOT_ATTEMPTED`, `STARTED`, `REJECTED`, `TIMED_OUT`,
  `IO_FAILED`, `INTERRUPTED`, `AUTHENTICATED`}; `welcome` ∈
  {`NOT_RECEIVED`, `RECEIVED`, `MISMATCH`, `VERIFIED`}; plus `encrypted`
  and `protocol_version` metadata. Contains no keys, seeds, admin secrets,
  passwords, session credentials or raw payloads. Replay re-derives the
  welcome identity from `runtime-identity.json` and never trusts the
  artifact's own success labels for a completion verdict.
- `runtime-identity.json` remains the authoritative post-welcome
  identity-verification artifact.

### 9.6 Failure-injection coverage and test results

Scripted backend doubles inside isolated temporary candidates (never a
process, port, secret or retained artifact; authorization always via the
synthetic RFC 8032 §7.1 TEST keys). Covered: backend-preflight failure
before the claim (fully reversible), claim refuses duplicates and
concurrent claimants (exactly one winner), launch-boundary refusal,
process-creation failure, readiness failure, exit before readiness,
JOIN_SECURE rejected/timed-out/dropped with durable handshake evidence,
welcome mismatch after an authenticated join, cleanup crash preserving
partial stages, uncertified cleanup refusing the attempt, missing/malformed
`runtime-identity.json`, missing/malformed `result.json`, malformed/missing
frames, missing handshake, missing stage journal, unsupported journal
schema, handshake-contradicted completion, journal-vs-result contradiction,
foreign-key signature refusal, unseeded anchor refusal, binary identity
refusal, launch-critical identity mismatch at the seam, and the core
invariant that forced success labels verify nothing.

Mixed run (before this record's final run): 122 passed,
1 skipped (`test_secure_admin.py`, `test_corridor_terrain_survey.py`,
`test_corridor_terrain_survey_native.py`) plus 8 new R2 replay scenarios;
final suite run below. Offline command of record (the `--run-openttd`
option is `store_true`; live paths stay disabled by omission):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_secure_admin.py \
  tests/test_corridor_terrain_survey.py \
  tests/test_corridor_terrain_survey_native.py \
  -q -p no:cacheprovider -rs
```

Test-embedded note of record: the synthetic-anchor scenarios re-verify the
pinned D4 candidate-5 prerequisite lineage under the production anchor
(captured at collection) and this candidate's own synthetic record under
the TEST anchor — the production anchor can never verify the TEST record
and vice versa; both refusals are enforced by every test.

### 9.7 Accepted limitations (unchanged in this remediation)

- Protocol-7 survey is observational only.
- Console stdin has no runtime ACL (unrestricted local authority channel).
- Console commands remain constrained by the frozen source and reviewed
  command construction.
- `start_ai` engine behavior is not independently proven without execution.
- Absolute engine-level zero-mutation is not established.
- No freight execution or delivery proof is implied by any of this.

### 9.8 Candidate-1/2 preservation and next-candidate requirements

Candidate-2 (`...-candidate-2/`) was not modified in any way during this
remediation: no PRELAUNCH regeneration, no `AUTHORIZATION.json` change, no
`CLAIM.json`, no `LAUNCH-CONSUMED.json`, no result artifact, no lifecycle
run. Candidate-1's retained state also stands untouched. A future candidate
requires, in order: fresh candidate staging; freeze generation and seal;
preflight; independent review; ONE fresh operator Gate C signature; and
separate explicit operator launch approval. Nothing in this record grants
any of them.
