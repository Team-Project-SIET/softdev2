# D4 Native Road & Station Construction — staging handoff

Status: **D4 STAGED — one candidate `D4-CORRIDOR-1`, `PENDING_AUTHORIZATION`;
`PRELAUNCH PASS` + read-only `PREFLIGHT PASS`; no claim written, nothing
launched, no tile changed**

Predecessor record:
[d3-terraform-native-candidate-1-outcome.md](d3-terraform-native-candidate-1-outcome.md)
("receipt-bound after.sav `fbebef54…d59e` — the authoritative verified post-D3
world"). This document closes the D4 **preparation** step for Milestone D4:
the reviewed Seed 17 corridor is staged as one fresh save-load candidate whose
source world is that receipt-verified D3 output, reusing the proven D2/D3
one-launch machinery exactly (operator authorization, runtime freeze,
dependency identity, immutable launch environment, one-shot claim, signed
replay, cleanup boundaries) parameterized at call time. No second security
framework exists.

Nothing in staging launches OpenTTD, connects to any port, mutates any tile,
or writes a claim. The staged pre-launch claim is never written; nothing can
launch until a separate operator authorization creates it, and no Git
stage/commit/push/reset/clean/stash was performed for this work. The D3
evidence directories are untouched (their `after.sav` digest re-checked below,
§7).

## 1. The staged candidate at a glance

| Fact | Value |
| --- | --- |
| Candidate directory | `artifacts/experiments/d4-corridor-native-candidate-1/` |
| Attempt | `D4-CORRIDOR-1` (one attempt, milestone `D4-CONSTRUCTION`, kind `corridor`) |
| Prelaunch schema | `d4-corridor-native-prelaunch-v1` |
| Prelaunch seal (PRELAUNCH.json sha-256) | `0b000d68852aac75504a0c16fb65807051d6f52dfccb6ea99de29a230781a18f` |
| Source world mode | `PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD` |
| Source save | `after.sav` from the consumed D3-TERRAFORMING-1 attempt, sha-256 **`fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e`** |
| Prerequisite record | `d4-native-prerequisite-attempt-v1`: attempt `D3-TERRAFORMING-1`, prelaunch sha `edb6b34c6597d146be766ca42728da816d27eaaf40dcb51eb779dd13e30cff9e`, consumed claim, replay-verified receipt, chain `… → D3-CLEARING-2 → D3-CLEARING-1` (cleared chain tiles `[45999, 49326]` = the compiled clears) |
| Welcome (must match at execution) | revision `15.3`, seed `17`, landscape `0`, 256×256, `start_day 712223`, dedicated |
| GameScript identity | save's retained identity `RoadFreightProof` v1 announced by the staged `info.nut`; the corridor handler runs as bridge class `NetworkFreightProof extends D4CorridorProof` (no retained identity byte modified) |
| Company | 0 (authorized company for every op) |
| Plan digest | `3bf3eddffa807cca2bde279425332d5079a025dec3b1dabe7114164822d8a912` |
| Budgets | 1 launch, 1 connection, **25 requests**, 6 road ops, 0 retries/reconnects, readiness 45 s, request 10 s, total 900 s, responses ≤ **640 B** |
| Authorization | `PENDING — requires ONE fresh operator authorization after all preflight gates; offline staging consumed no claim and no authorization file exists` |
| Execution command (after authorization) | `.venv/bin/python -m app.simulation.openttd.proof.corridor_construction_native run artifacts/experiments/d4-corridor-native-candidate-1` |
| Exit semantics | 0 only for the verified native receipt; every failed/halted/pre-verified state exits 1 |

## 2. The staged corridor schedule (compiled, deterministic)

Derived offline from the pinned compiled levelling specification (digest
`9e70b3609a2339299d0fb501ba1c8ba2c6808a8d0ec6c3966124367a075a0d1d`) plus the
deterministic depot entry over the compiled post-D3 facts; the authorization
payload carries the schedule + plan digest as additive keys of the shared
scalar builder. Road pieces built by separate commands do not auto-merge: the
corner between the two runs is its own scheduled op, never a free by-product.

| Op | Kind | Command | Pins (tile → (x,y)) | Run length |
| --- | --- | --- | --- | --- |
| 0 | `full` | `GSRoad.BuildRoadFull` | start 45747 (179,178) → end 45743 (175,178) | 5 |
| 1 | `full` | `GSRoad.BuildRoadFull` | start 45999 (175,179) → end 50095 (175,195) | 17 |
| 2 | `road` | `GSRoad.BuildRoad` | 45743 (175,178) ↔ 45999 (175,179) | 2 |
| 3 | `station` | `GSRoad.BuildRoadStation` | tile 45748 (180,178), front 45747 (179,178), pickup | 1×1 |
| 4 | `station` | `GSRoad.BuildRoadStation` | tile 50351 (175,196), front 50095 (175,195), delivery | 1×1 |
| 5 | `depot` | `GSRoad.BuildRoadDepot` | tile 45487 (175,177), front 45743 (175,178), orientation `south` | 1×1 |

Both straight spans are inside the wire contract's `MAX_FULL_SPAN` bound (36
delta steps; actual spans 4 and 16). The route read is **not** an op.

Order in execution: run A, run B, corner, pickup stop, delivery stop, depot —
six ops in execution order, each halting exactly as in D3: the first
verification failure halts the phase, earlier verified receipts stand, later
operations never execute, nothing is retried, and the world state after a
failed command is explicitly uncertain (a failed native road command may
still have built pieces; no compensating mutation exists).

## 3. Wire contract v4 — 19 planned exchanges

Protocol 4 lives in `app/simulation/openttd/corridor_construction.py`; the
handler is `app/simulation/openttd/d4_corridor_package/main.nut`.

- Planned inventory: **6 ops × 3 exchanges + 1 route read = 19** (inspect →
  command → independent read per op; dispatcher budget 25 = 19 + 6 slack, the
  same cap the handler itself enforces — request 26 is refused).
- Wire identity style (identical to the proven D2/D3 ceremonies): the
  inspection request and the command request present the **prelaunch seal**
  the inspect latched; the independent verification read presents the
  **admitted intent digest**; the final route read carries the prelaunch seal
  as **pure observation**.
- Request bound: every request serializes ≤ 512 B. Worst planned request in
  the staged schedule is 304 B (min 177 B); all 19 were built offline through
  the production builder and validated.
- Response bound: **640 B**, a D4-contract-only delta from the historical 512.
  The final route read echoes the ordered 24-tile witness (24 five-digit tile
  ids) plus its full observation set (pair accounting, both stop
  classifications and station ids, the depot join), which cannot honestly fit
  512 B. Every other response stays far below it; the handler's `Guard()`
  numeric bounds still make any oversized or spoofed readback a refused frame,
  and changing any required observation field would weaken the fail-closed
  verifiers, so nothing was dropped to keep 512.
- The route read's verification is observation only: 23/23 adjacent pairs
  joined by company road along the witness path, both stops classified
  non-drive-through truck stops with valid station ids, the depot joined to
  its pinned front — **it never issues a build assertion**.

## 4. Per-admission pre-state rules (the fail-closed latches)

Every op's inspect response is judged by `admit_corridor` before any command
may run; all of these are native facts re-observed at admission time, never
planning derivations, and a mismatch is terminal for that op:

- `full` ops: scale fresh — both endpoints unowned (`owner −1`), roadless
  (`road false`), run coverage 0, report the staged run length exactly; any
  drift vs the staged schedule (e.g. the 2 vs 5 or 17 tile count) refuses.
- corner `road` op: both endpoints **company-owned road** with the pair not
  yet connected (`pairs_ok 0`), covered = staged 2.
- `station` ops: unplanned footprint (`stop/drive_through/truck false`, no
  station id) fronting a company-owned road tile.
- `depot` op: unplanned ground (`depot false`, `depot_linked false`) with the
  front on company road.
- Cost gates: `READY` with a positive tested native quote within the per-op
  ceiling and funds for it; **a zero-cost native refusal is terminal** — it
  must never trigger a build command.
- The command stage re-observes the whole admission, re-quotes equal, and
  executes the single native build command exactly once; the independent read
  must agree (post-state + summaries + geometry), else the phase halts with
  the verified prefix preserved.

## 5. Budgets, costs and coverage anchors (planning evidence only)

- Per-op native ceiling: **£2,000** (`MAX_CORRIDOR_COST`); the historical
  reference costs (road piece £71, truck stop £150, depot £375) stay
  controlled references, never authorization.
- Stop anchors from the sealed census: pickup 45748 — industry 0, cargo 1,
  `producer_count 1`, `industry_covered`; delivery 50351 — industry 1, cargo
  1, `industry_covered`; measured at unplanned ground with
  `acceptance_eighths 0`. Catchment/acceptance re-checks and every structural
  admission happen **natively at construction admission**; a zero-cost native
  refusal there is terminal, and acceptance is never inferred from planning.
- Post-D3 floor facts (compiled projection, certified offline in the tests):
  all 24 corridor tiles read flat (`min_height 2`, `slope 0`), tree-free,
  roadless, unowned, buildable, industry-free.

## 6. Preflight verdict and read-only rehearsal

The candidate passed the offline launch-boundary rehearsal twice (once inside
`prepare`, once as the standalone read-only command) with these gates:

prelaunch seal intact; claim absent (nothing consumed); prelaunch schema the
D4 corridor lineage; frozen sources byte-intact; the D2 runtime source closure
and installed dependency inventory frozen under the candidate's contract; the
staged schedule and plan digest equal their compiled derivation; every site
front adjacent to its pin; the route scope equal to `route_policy()`; the
prerequisite binding equal to a live re-verification of the retained D3
attempt (claim consumed, receipt replay-verified against the production
operator anchor, after-save digest == `fbebef54…d59e`); the expected welcome
equal to the retained facts; the staged `source.sav` byte-identical to the
pinned after-save; the staged `info.nut`/`main.nut` byte-equal to the
retained frozen-source composition; workspace ownership correct; the backend
preflight gates (binary digest, exclusive runtime) and the endpoint
reservation reallocated-and-released. Verdict: **`PREFLIGHT PASS`**.

## 7. Offline validation performed

- **New staging test suite** `tests/test_corridor_construction_native.py` —
  26 tests, exit 0: the pinned witness/runs/depot facts (exact tiles above),
  the compiled 24-tile post-D3 flat-ground projection, the compiled-six-op
  schedule, the coverage anchors, the full budget table, the plan policy with
  the shared schedule/plan-digest keys, the authorization payload rebuild
  (setting `operation_schedule` + `plan_digest`, digest equal to
  `staged_authorization_payload_digest`), the 19 planned exchange inventory
  and all request wire sizes, staged-artifact identity, the staged
  source-save ≡ the pinned D3 after-save (and ≠ the diagnostic save),
  preflight pass + the drift-refusal gates (config tamper, source-save tamper,
  frozen-source drift probe, removed closure entry, drifted seal, planted
  claim), launch-marker lineage, exit-status semantics and the
  never-consumed fail-closed verdict.
- The wire/handler suites stay green alongside the D4 staging work: in one
  combined run, the shipped-corridor Squirrel-VM suite (21 tests) + this
  staging suite (26) + the D3 native integration suite (23) all pass and exit
  0 (70 progress dots; the in-process Squirrel driver suppresses pytest's
  terminal summary); the plan-level terrain suite (31 tests) also passes
  exit 0.
- **Restage honesty.** Two earlier stages of this same candidate were deleted,
  never preserved or relabeled, and the third stays: the first (seal
  `7ee744d6a710b20d7760603ec21a8c82b386ff883b626957c7556f8532b2a1a7`) was
  created before the final handler/test fixes of this session, the second
  (`736a9fd3…4c4ef2cf`) before the module's final lint hygiene (ruff I001/F841/
  E501 cleanups, zero semantic deltas — the plan digest and every schedule or
  route pin are identical). Each stage's frozen freeze entries recorded
  superseded source bytes, and a candidate whose freeze no longer matches the
  reviewed sources may never be authorized — so each was removed and staged
  fresh from the current bytes. The restaged candidate's freeze re-verifies
  the final module and package bytes; D3 artifacts untouched: `after.sav`
  re-reads `fbebef54…d59e`, and the distinct `after-diagnostic.sav`
  (`2942b778…25b07`) remains **never a substitute** for the
  authoritative after-save. Hygiene at close: `compileall` and `ruff check`
  clean on the staging module and the test module.
- **Fail-closed verify decision.** `verify_corridor_attempt` returns the
  structured verdict `AUTHORIZATION_UNVERIFIED` / `CLAIM_ABSENT` for a
  candidate whose claim never existed (never a crash and never a receipt),
  matching the function's graceful schema/authorization paths. It is
  exercised against the never-consumed staged candidate above.

## 8. Authorization posture — what remains for the operator

1. The candidate is `PENDING_AUTHORIZATION` only; no `AUTHORIZATION.json`
   exists and no `CLAIM.json` may be created by anything but the runner after
   an operator record verifies.
2. The authorization payload is rebuildable offline exactly from the staged
   prelaunch record (`staged_authorization_payload_digest`): milestone
   `D4-CONSTRUCTION`, attempt `D4-CORRIDOR-1`, one launch / zero retries, the
   entire budget table, the execution command, the full ordered schedule and
   its plan digest, the sealed source world (after.sav `fbebef54…d59e`) and
   the expected welcome — all bound by equality and an RFC 8032 Ed25519
   signature under the seeded operator anchor.
3. After authorization, the `run` command executes the one ceremony: claim
   consumption, one launch, one encrypted connection, the six scheduled ops
   (phase halts prefix-preserving on any failure) then the route read, the
   retained receipt, cleanup (process reaped, sockets closed, workspace
   disposed, credential removed) and replay verification — zero only if
   everything verifies.
4. Any staging-time drift between now and authorization is refused by the
   reinstallable gates above; the schedule, route witness, budget table and
   world identity of the authorized record are not negotiable after staging.

## 9. Honesty and limits

- **Nothing ran.** No OpenTTD process, no AdminPort connection, no save
  mutation; the only filesystem writes are the candidate's own staging
  directory and the test suites' own temporary candidates.
- **Strictly the staged schedule.** The staged evidence covers exactly the
  six bounded ops and the route read above; no other tile, command class,
  vehicle or expansion is claimed, and demolition/terraforming commands are
  absent from the handler by construction.
- **Native-only admission.** Road buildability, catchment/acceptance, costs
  and structural facts are verified natively per op at admission; zero-cost
  refusals are terminal; nothing about the phase outcome beyond the staged
  pre-state expectations is claimed here.
- **One attempt.** `D4-CORRIDOR-1` carries its own prelaunch seal, one-shot
  claim and fresh authorization; consumed D3 evidence is never retried,
  relabeled or re-run. If this candidate is consumed or refused, a new
  candidate regenerates from the same compiled derivation — never an edit of
  this one.
- **The one report button is the operator's.** This handoff records staged
  facts and offline verification only; it does not attribute, promise or
  simulate any future launch.
