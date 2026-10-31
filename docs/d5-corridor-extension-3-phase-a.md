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

## 10. Journal-ordering correction (appended 2026-10-31, source-backed audit)

Corrects the R1 remediation wording in §9.3 (and any summary derived from it).
The §3–§9 history stands as written; this addendum changes only the described
lifecycle sequence, verified directly against
`app/simulation/openttd/proof/corridor_terrain_survey_native.py`
(`execute_terrain_attempt`) as committed at this date. Production behavior is
NOT changed by this correction and must not be.

### 10.1 Corrected lifecycle contract (the actual production sequence)

1. `terrain_survey_preflight(prepared)` runs first (pure offline
   re-derivation; writes no attempt evidence).
2. The `TerrainAttemptJournal` object is constructed **before**
   `backend.preflight`, but construction is **in-memory only**: its
   `__init__` builds the document and binds the target path
   `attempt-progress.json`; it writes nothing. No journal file exists yet.
3. `backend.preflight(prepared)` runs next (read-only: credential
   permissions, graphics identity, pinned binary/ownership; creates no
   external state and reserves nothing). **No journal stage is recorded
   before or during it.** If `backend.preflight` fails, the candidate is left
   with **no `attempt-progress.json`, no `CLAIM.json` and no
   `LAUNCH-CONSUMED.json`**; the failure is fully reversible.
4. On `backend.preflight` success, the first `journal.stage("RUN_PREFLIGHT")`
   call **creates the journal file**; `BACKEND_PREFLIGHT` is then recorded.
   Both stages are recorded at their boundary completion and before
   `write_terrain_claim` (the last reversible-free gate).
5. Authorization verification (`grant_launch` + launch-critical identity),
   the atomic exclusive-creation claim, the `LAUNCH-CONSUMED.json` seam and
   the process stages follow in the order §9.3 already shows.

§9.3's diagram line "stage journal opens (PRE-CLAIM facts: RUN_PREFLIGHT,
BACKEND_PREFLIGHT)" placed above the `backend.preflight` box overstated this:
the *file* and its first two stage entries do not exist until
`backend.preflight` has succeeded. The corrected semantics above are the
contract of record.

### 10.2 Replay consequences (unchanged, restated for precision)

A backend-preflight failure leaves no retained claim, so the repository's
replay verifier returns `AUTHORIZATION_UNVERIFIED` with authorization state
`CLAIM_ABSENT` because no retained claim exists. That refusal is **not**
evidence of consumption or success, and never becomes one.

### 10.3 Schema-hygiene observation: `LAUNCH_BOUNDARY`

`LAUNCH_BOUNDARY` is declared in `TERRAIN_ATTEMPT_STAGES` but is not actually
recorded through `journal.stage()` anywhere in the executed path. This is a
schema-hygiene inconsistency only: the replay verifier's required-stage set
for a verified completion (reviewed at this date) does not require it, and no
replay verdict or required-stage validation reads it. The wildcard-stage
validation (unknown stage refusal) is unaffected. Per the audit decision, the
schema and lifecycle are left unchanged for the fresh candidate; this is a
recorded known limitation to clean up in a future schema revision (folding
the boundary fact into `PROCESS_STARTED` or recording it at the seam), not a
defect affecting any verdict.

## 11. Continuation record (appended 2026-10-31, offline; no launch, no claim, no signing)

### 11.1 Independent six-workstream remediation review — all PASS

Read-only review of the remediated terrain-survey pipeline, verified directly
against production sources and the executed suites (not the report's own
claims). Files: `app/simulation/openttd/proof/corridor_terrain_survey_native.py`
(terra pipeline), `app/simulation/openttd/proof/terrain_clearing.py`
(`ClearingNativeBackend.launch` trust chain, `record_boundary_consumption`),
`app/simulation/openttd/proof/native.py` (`NativeBackend.preflight`, read-only),
`app/simulation/openttd/proof/operator_authorization.py` (anchor, grant, claim
evidence), `app/simulation/openttd/secure_admin.py` (JOIN_SECURE capacity
validation, encoder-side defense), tests
`tests/test_corridor_terrain_survey_native.py`, `tests/test_corridor_terrain_survey.py`,
`tests/test_secure_admin.py`.

| # | Workstream | Production evidence | Test evidence | Verdict |
|---|---|---|---|---|
| 1 | Preflight-before-claim ordering; reversible failure | `execute_terrain_attempt` order: offline preflight → in-memory journal → `backend.preflight` (read-only) → first `journal.stage("RUN_PREFLIGHT")` creates the file → both preflight stages recorded at boundary completion before `write_terrain_claim`; every reversible gate precedes the claim | `test_backend_preflight_failure_stays_fully_reversible`, `test_claim_arrives_only_after_every_reversible_gate`, `test_missing_authorization_record_refuses_before_the_claim`, `test_unseeded_anchor_refuses_every_launch_gate`, `test_foreign_authorization_signature_refuses_the_claim` | **PASS** |
| 2 | Exclusive atomic claim; duplicate/concurrent protection | `write_terrain_claim` `O_CREAT\|O_EXCL\|O_WRONLY` + fsync; `FileExistsError` → staged refusal; preflight refuses any candidate that already carries a claim | `test_exclusive_claim_refuses_a_second_claim`, `test_concurrent_claims_produce_exactly_one_winner` | **PASS** |
| 3 | Launch trust chain, authorization binding, binary identity, launch-critical identity | `ClearingNativeBackend.launch`: grant binds candidate directory + seal + claim authorization story + complete one-shot state; `reverify_launch_grant` re-checks exact record bytes and the current anchor; `validate_launch` argv; `verify_freeze` + `launch_critical_identity` stat equality at the seam; sealed exact environment, forbidden keys refused; `sha256(BINARY) != BINARY_SHA256` / `matching_processes` enforced at staging, preflight and boundary | `test_binary_identity_mismatch_refuses_read_only_preflight`, `test_launch_critical_identity_mismatch_refuses_before_the_process_seam`, `test_boundary_marker_opens_exactly_once`, `test_foreign_authorization_signature_refuses_the_claim` | **PASS** |
| 4 | `LAUNCH-CONSUMED.json` at the actual Popen boundary | `record_boundary_consumption` runs inside `backend.launch` immediately before `Popen`; exclusive creation; a second grant/instance refuses at the marker; a boundary validation failure before it leaves the candidate CLAIMED-but-unlaunched (documented state) | `test_process_boundary_is_the_launch_consumption_point` (marker consumed with zero processes created), `test_claim_arrives_only_after_every_reversible_gate` (refusal keeps claim, no marker) | **PASS** |
| 5 | Attempt progress journal and handshake-evidence lifecycle | `TerrainAttemptJournal` atomic whole-document rewrites, boundary-completed stages, fail entries carry error types only; `handshake-evidence.json` merges fail-closed states; replay re-derives the welcome from `runtime-identity.json` and never trusts success labels | `test_join_refusals_are_preserved_as_handshake_evidence`, `test_welcome_mismatch_after_an_authenticated_join`, `test_cleanup_crash_after_the_claim_preserves_partial_stages`, `test_replay_refuses_a_completed_attempt_without_handshake_evidence`, `test_replay_refuses_a_completed_attempt_without_its_stage_journal` | **PASS** |
| 6 | Replay verification, evidence-state classification, cleanup, fail-closed | `verify_terrain_attempt`: per-artifact `_load_evidence_json`/`_versioned_evidence` states, manifest exhaustiveness, authorization replay, schedule/plan re-derivation, frame/file exchange correspondence, duplicate/stale/malformed refusals, receipt byte-equality, census-findings equality, cleanup certification gate (all four fields, no errors), structured verdict taxonomy incl. `EVIDENCE_INCOMPLETE`/`EVIDENCE_INVALID`/`AUTHORIZATION_UNVERIFIED`/`CLAIM_ABSENT` | `test_replay_fails_incomplete_when_the_terminal_evidence_never_survived`, `test_replay_fails_incomplete_without_runtime_identity_and_records_the_stage`, `test_replay_names_malformed_*_evidence_invalid`, `test_replay_refuses_a_failed_result_its_journal_calls_terminal_success`, `test_replay_never_verifies_a_forced_label_without_authorization`, `test_uncertified_cleanup_fails_the_attempt_closed`, `test_replay_fails_closed_on_tampered_retained_phase_in_receipt` | **PASS** |

Checks named by the audit's critical-failure list, verified, not merely asserted:
a stage is recorded only at its boundary completion (no stage claims work that
did not happen); `NATIVE_TERRAIN_COMPLETE`/`SURVEY_COMPLETION_VERIFIED` is
impossible without the journal, the handshake, `runtime-identity.json`, the
frames, every retained exchange, a re-derived `SURVEY_COMPLETE` and certified
cleanup; cleanup failure denies verification (`apply_terrain_cleanup_outcome`,
`FAILED_CLEANUP`); authorization verification (`grant_launch`,
`verify_authorization`) is bound into the claim and never confused with
candidate consumption; no replay path accepts incomplete evidence as success.

Non-blocking observations recorded (no behavior change made):

- `LAUNCH_BOUNDARY` is declared in `TERRAIN_ATTEMPT_STAGES` but never recorded
  through `journal.stage()`; replay's required-stage set does not include it
  and no verdict reads it — schema-hygiene limitation for a future revision
  (§10.3).
- A FAILED attempt can carry two `TERMINAL_FAILURE` entries (the `except`
  journal.fail and the `finally` journal.fail both append); replay treats
  stages set-like and `_reached_stage` reads the last entry, so the
  duplication is harmless; a future journal revision may deduplicate.
- `STARTED` is a legal `join_secure` evidence state but the executed path
  transitions from `NOT_ATTEMPTED` directly to a resolved state; harmless and
  covered by the same future revision.

### 11.2 Offline validation of record (actual result)

Command (the documented one):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_secure_admin.py \
  tests/test_corridor_terrain_survey.py \
  tests/test_corridor_terrain_survey_native.py \
  -q -p no:cacheprovider -rs
```

Actual: **130 passed, 1 skipped, 0 failed, 0 errors** (273.57 s). The skip is
exactly `tests/test_corridor_terrain_survey.py:346` — shipped terrain source
already corrects the `typeof` spelling. This equals the historical baseline.
No OpenTTD process, AdminPort session, candidate lifecycle or retained
artifact was touched.

### 11.3 Candidate-2 status after this record (read-only re-checked)

- `artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-2/`
  remains byte-untouched by this session: no staging, no edit, no claim, no
  marker, no launch. Read-only replay returns `AUTHORIZATION_UNVERIFIED` /
  `CLAIM_ABSENT` (authorized-but-never-consumed, retained `AUTHORIZATION.json`
  verified at audit time).
- This session's §2.3 production-comment correction changed the working-tree
  bytes of `corridor_terrain_survey_native.py` (comment only; behavior
  unchanged). Because the fresh candidate's frozen closure pins those bytes
  (`c204e107…dfb94` → now `ad409539…c424`), the preflight gate correctly
  fails closed: `ValueError: Frozen source/input changed; no launch permitted`.
  Candidate-2 therefore becomes **stale-by-source-drift** (signed, never
  consumed, never launchable without restaging) — the same documented pattern
  as the D4 candidate-2 case. Its retained evidence stands unchanged as
  history; it is never edited, re-signed, re-claimed or launched.

### 11.4 Prepared checklist: fresh D5-CORRIDOR-EXTENSION-3 survey candidate (approval-gated)

Nothing below has been executed; staging, signing and launch each need the
exact explicit approvals already defined in §9.8 / the remediation doc §8.
The fresh candidate (candidate-3) must use, in order:

1. **Explicit staging approval** and (per precedent) the one-constant
   identity bump `TERRAIN_SURVEY_ATTEMPT` `D5CE3-SURVEY-2` → a fresh ≤24-byte
   identity (e.g. `D5CE3-SURVEY-3`); milestone unchanged
   `D5-CORRIDOR-EXTENSION-3`; no other source/test/package byte changed for
   the bump; focused suites re-run after it.
2. Fresh staging: `corridor_terrain_survey_native prepare` into a brand-new
   directory `artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-3/`
   (`exist_ok=False`; the consumed candidate-1 and stale candidate-2 stay
   untouched); fresh prerequisite re-binding to the pinned D4 candidate-5
   after-save `a81ac836…ef261`, fresh workspace/freeze closure from current
   reviewed bytes (now including the §2.3-corrected comment), new
   EndpointReservation, fresh credential.
3. Fresh seal + authorization payload digest recomputed from the staged
   bytes; recorded in the phase-a doc / evidence index.
4. Independent review of the staged bytes and digest chain (fresh context).
5. `PREFLIGHT` re-derivation PASS (read-only).
6. Operator Gate C Option-1 signing over the recomputed payload digest
   (local handoff; seed never displayed; signature verified under the pinned
   anchor before any write; nothing is signed by this record).
7. Separate explicit operator launch approval; launch exactly once through
   the remediated lifecycle; replay against retained evidence; certified
   cleanup; never retried on any failure.

None of that is granted by this record. Candidate creation, signing and
launch remain separate approval gates.

### 11.5 Status after this record

- `A0_SURVEY`: NOT EXECUTED (fresh candidate-3 not staged; operator gates
  pending).
- `A1_IMPLEMENTATION`: NOT STARTED (gated on a verified A0).
- `PHASE_A`: NOT READY.
- D5 as a whole: freight delivery NOT proven (`D5-FREIGHT-1` consumed
  FAILED-of-record); M8 optimizer route-select proof NOT demonstrated (no
  competing executable route); D4 corridor construction remains the only
  native-verified D5-adjacent milestone (E35, scoped to the v3 schedule).

## 12. Fresh candidate-3 staging record (appended 2026-10-31, operator-approved)

Executed exactly per the §11.4 checklist after one explicit operator approval
("stage candidate-3"). **No signing, no claim, no launch, no AdminPort session;
candidate-2 remains byte-untouched (seal re-verified
`c76992…aaa2b6`).** This record is staged-evidence only; D5 remains
PARTIALLY CLOSED with the native A0 survey NOT EXECUTED.

### 12.1 Identity bump (one-constant, per §11.4 step 1)

- `corridor_terrain_survey_native.py`: `TERRAIN_SURVEY_ATTEMPT`
  `"D5CE3-SURVEY-2"` → `"D5CE3-SURVEY-3"` (14 UTF-8 bytes, never-consumed;
  milestone unchanged `D5-CORRIDOR-EXTENSION-3`). One review-facing test
  constant and one validator call in
  `tests/test_corridor_terrain_survey_native.py` were updated with the bump
  (same precedent as the SURVEY-1→SURVEY-2 bump); no other source/test/package
  byte changed. Focused suites re-run after the bump: the documented
  3-file command returned **130 passed, 1 skipped, 0 failed** (exit 0),
  identical to the E37 baseline.
- New source bytes sha:
  `1b92d191994d26f55c6c75028dacb9f886719ea39aeae730636f351c156c7d5e`.

### 12.2 Fresh staging (§11.4 step 2–3)

- Command:
  `.venv/bin/python -m app.simulation.openttd.proof.corridor_terrain_survey_native
  prepare artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-3`
  → `PRELAUNCH PASS` (prepare re-ran the full preflight; fresh
  EndpointReservation, admin 44109 / game 60181; fresh credential created and
  never displayed).
- Seal: `sha256(PRELAUNCH.json) =
  6743fc3c8400723854cde6f2f1d643188a9c2c5583d02a7acff7e241d6898df8`
  (= `PRELAUNCH.sha256`, byte-re-verified).
- Authorization payload digest
  (`staged_terrain_authorization_payload_digest`):
  `75a5d226ea598056c5b32240d1c984f3f1a8578058d062213cb88548ba0ae991`.
- Frozen closure: **3,491 entries**, including the bumped source
  (`…7d5e` above), the byte-identical staged GameScript
  (`game/RoadFreightProof/main.nut` `500d3f02…c5a3e4`, matching
  `d5_freight_package/main.nut`) and the staged workspace/config.
- Prerequisite re-binding: fresh bind to the pinned D4 candidate-5 after-save
  `a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261`
  (staged `source.sav` re-hashes to exactly that digest); schedule digest
  unchanged `f091754de6d364d226b77555766ed5d2f3f3dfb38e23f42f5d3757fd62246c3a`
  (same ten-exchange protocol-7 plan); budgets unchanged (1 launch,
  32-request cap, 512/512 bytes, 0 reconnects/retries, 300 s, funds
  `492149`).
- Standalone read-only `preflight` re-derivation: **PREFLIGHT PASS**.

### 12.3 Independent fresh-context review (§11.4 step 4)

Verdict **PASS** (read-only, no writes): seal ↔ `PRELAUNCH.sha256` match;
survey module, gate Nut and five spot-checks re-hashed against live bytes;
**full frozen sweep re-hashed 3,491 OK / 0 mismatch / 0 missing**; budgets,
ports, prerequisite binding and payload digest independently recomputed to
the exact values above; lifecycle confirmed `AUTHORIZATION_UNVERIFIED` /
`CLAIM_ABSENT` with no `AUTHORIZATION.json` / `CLAIM.json` /
`LAUNCH-CONSUMED.json` / attempt journal; identity 14 UTF-8 bytes accepted by
the untouched shared `validate_join_secure_string`; secret-adjacent files
confirmed by name/digest only, never opened.

### 12.4 Gates remaining (unchanged from §11.4 steps 6–7)

Status as written when §12 was recorded: 1. Gate C Option-1 signing (executed
below, §12.5); 2. separate explicit operator launch approval (still pending).

### 12.5 Gate C Option-1 signing record (appended 2026-10-31, operator-approved)

Following one explicit operator approval ("sign candidate-3 via Gate C
Option-1"), the documented repository-tooling signing checklist
([key provisioning §1/§2/§4](docs/handoff/2026-10-17/operator-key-provisioning.md),
same pipeline validated for the D5 freight candidate, E36) was executed
exactly once:

- Refusal gates checked first and re-checked immediately before signing:
  `AUTHORIZATION.json`, `CLAIM.json`, `LAUNCH-CONSUMED.json` all absent;
  payload digest re-verified `75a5d226…e991` over the exact canonical bytes.
- Seed extracted from the operator-held PEM
  (`~/.local/share/openttd-operator/operator-private.pem`, outside the git
  repository) into a shell variable via the corrected exit-status/shape
  -checked pipeline (bash, `pipefail`); never printed, written to a file or
  passed as a command-line argument.
- Derived public key checked equal to the pinned production anchor
  `5063982b…4880f` **before** signing.
- 64-byte RFC 8032 Ed25519 signature verified under the pinned anchor over
  the exact canonical payload bytes **before** any write; then
  `AUTHORIZATION.json` written by `write_authorization_record`.
- Record sha-256: `a481dfb51d80766e8f75ae5e9ae19dc1b9758098682ee72540e9aca4abac8261`;
  seed cleared immediately after final use (`unset`, verified empty). A
  first script invocation failed at a verifier-API name check (`is_valid`
  vs `verify`) after the refusal gates and digest checks and **before any
  signature verification or write**; the seed was cleared at that exit and
  the second invocation re-ran the complete checklist from the refusal
  gates. No signature was produced twice; `sign_authorization_record` ran
  once.
- Read-only post-write verification: `verify_authorization` → PASS;
  `authorization_sha256` = the record sha above; `operator_key_identity` =
  `sha256-ed25519-public-key:cbb63ff5…40c614` (unchanged production anchor);
  payload binds `attempt D5CE3-SURVEY-3` / milestone
  `D5-CORRIDOR-EXTENSION-3` to seal `6743fc3c…898df8`. `CLAIM.json`,
  `LAUNCH-CONSUMED.json` and the attempt journal remain absent; read-only
  `verify` still returns `AUTHORIZATION_UNVERIFIED`/`CLAIM_ABSENT`
  (authorized, never consumed); standalone `preflight` → **PREFLIGHT
  PASS**. Candidate-2 seal re-checked unchanged `c76992…aaa2b6`.
- The authorization signature is NOT launch approval. Per §11.4 step 7 the
  next and final gate is a separate explicit operator launch approval for
  exactly one native survey attempt through the remediated lifecycle (no
  retry on any failure), then replay + certified cleanup.

## 13. A0 Native Survey completion record (appended 2026-10-31, operator-approved launch)

After one separate explicit operator launch approval, the released
`D5CE3-SURVEY-3` candidate was executed **exactly once** through the
remediated lifecycle:

```
.venv/bin/python -m app.simulation.openttd.proof.corridor_terrain_survey_native run
  artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-3
```

Exit 0. The one-shot claim and `LAUNCH-CONSUMED.json`
(`d5-native-launch-consumed`) were consumed exactly once (1 native launch,
pid 54600, 1 fully encrypted X25519 connection, 10/10 planned exchanges,
0 retries, 0 mutations — `state_changed: false`).

### 13.1 Native success conditions — all met

- **Runtime identity** (`runtime-identity.json`): revision `15.3`, seed `17`,
  256×256, landscape `0`, `start_day 712223`, dedicated, encrypted `true` —
  the pinned prerequisite world, matched exactly.
- **Handshake evidence** (`handshake-evidence.json`,
  `d5-terrain-survey-handshake-evidence-v1`): `join_secure AUTHENTICATED`
  (protocol version 3, encrypted), `welcome VERIFIED`; the 14-byte identity
  passed the encoder that failed the 32-byte `SURVEY-1` identity at §5.2.
- **Result/frame evidence**: `result.json` `verified: true`, `status
  NATIVE_TERRAIN_COMPLETE`, `returncode 0`, requests 10, `halt: null`;
  per-exchange `request/response` pairs for all ten exchanges
  (`radius-00`, `tile-00`…`tile-06`, `accept-00`, `accept-01`) + `frames.json`;
  `receipt.json` re-derives `SURVEY_COMPLETE`. Funds pinned exactly
  £492,149 in every receipt (the expected D4 close-out level).
- **Replay verification**: read-only `corridor_terrain_survey_native verify`
  → **`SURVEY_COMPLETION_VERIFIED`** (exit 0) — the documented successful
  survey verdict, over the retained evidence, not inferred from exit status.
- **Certified cleanup** (`cleanup.json`): process reaped (`returncode 0`,
  no remaining processes), sockets closed, credential removed, reservation
  released, workspace disposed (`isolated/` empty); endpoint verification
  policy `linux-kernel-endpoint-closure-v1` with kernel `TIME_WAIT`
  observation — `cleanup_complete: true`; 38-file
  `artifact-manifest.sha256` re-hash-verifies 0 mismatches (write-side
  artifacts retained, never modified).

### 13.2 Journal stage lifecycle (remediated contract, as executed)

`attempt-progress.json` stages in exact order: `RUN_PREFLIGHT`,
`BACKEND_PREFLIGHT` (both recorded after the read-only backend preflight,
before the claim), `AUTHORIZATION_VERIFIED`, `CLAIM_CREATED`,
`PROCESS_STARTED`, `PROCESS_READY`, `ADMINPORT_CONNECTED`,
`JOIN_SECURE_STARTED`, `AUTHENTICATED`, `WELCOME_RECEIVED`,
`WELCOME_VERIFIED`, `RUNTIME_IDENTITY_WRITTEN`,
`SUBSCRIPTION_ESTABLISHED`, ten × (`SURVEY_EXCHANGE_STARTED`,
`SURVEY_EXCHANGE_COMPLETED`), `CLEANUP_STARTED`, `CLEANUP_COMPLETED`,
`TERMINAL_SUCCESS` — no stage claims work that did not happen; cleanup is
recorded complete before the terminal stage.

### 13.3 Survey observations (native, as received)

- `radius-00` → measured radius 3 around the stop site under the planned
  acceptance metric.
- Station tiles `50095` (company 0, road present, buildable false — the
  existing pickup stop), `50096`, `50352`, `50608` (slopes 12/12/8,
  buildable, unowned), `50864`, `50863`, `50862` (flat height 1, slope 0,
  buildable, unowned, roadless) — all `SURVEY_OBSERVED` with per-tile facts
  (slope, heights, buildable, owner, clearance/road/rail/water/air
  presences).
- The acceptance pair: control `50351` (pickup-side) → acceptance value
  **0/8**; the planned delivery-stop tile `50862` → acceptance value
  **8/8** — i.e. under the measured native radius-3 footprint, `50862`
  reports full cargo-1 acceptance while the control tile reports none.
  The replay's `census_findings` additionally record six census-vs-native
  deviations (`buildable`/`min_height`/`road` on `50095`; `slope` on
  `50096`, `50352`, `50608`) — captured as findings, never fused over.
- Protocol-7 remains observational: vehicle reachability, road-bit
  direction presence, station buildability before the front road exists
  and pathfinding stay UNKNOWN (as staged); the native construction
  attempt itself will decide those.
- **The D5 scope of record is unchanged**: this A0 survey is the remediation
  milestone for the delivery-stop viability question. Freight delivery
  (`D5-FREIGHT-1` FAILED-of-record) and M8 optimizer route selection remain
  unproven; the corridor extension (`A1`) and any construction remain
  separate native attempts.

### 13.4 Phase-A status after this record

- `A0_SURVEY`: **COMPLETE — VERIFIED NATIVE** (candidate-3, `D5CE3-SURVEY-3`;
  consumed; never retried; historical candidates-1/2 and the freight and
  accept-survey records stand unchanged).
- `A1_IMPLEMENTATION` (corridor spur + bay-stop construction): UNBLOCKED,
  needs its own scoped design, fresh candidate staging, review, Gate C
  signature and a separate launch approval.
- Candidate-3 is permanently consumed (`CLAIM.json` + `LAUNCH-CONSUMED.json`
  retained); any replay against it is read-only and returns
  `SURVEY_COMPLETION_VERIFIED` without rerunning anything.
