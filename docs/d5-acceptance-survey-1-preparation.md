# D5-ACCEPT-SURVEY-1 — read-only native acceptance survey: preparation record

Status: **OFFLINE PREPARATION ONLY.** No OpenTTD process was launched, no
AdminPort session, no candidate staged, no claim, no authorization payload,
no signature and no Gate C artifact exists from this work. The repository's
consumed-identity history, the D4 authoritative after-save and the sealed
D3/D4 evidence are untouched; the working tree carries no commit.

Predecessors (all verified in-tree, this session):

- [D5 candidate-1 outcome](2026-10-27/d5-corridor-freight-native-candidate-1-outcome.md)
  (E36: `D5-FREIGHT-1` consumed exactly once; `site-00` reached `READY` with
  every corridor fact correct but `accept 0`; halted
  `PHASE_HALTED_PREFIX_PRESERVED` with zero world mutation).
- [D5 design](d5-corridor-freight-design.md) (§4 site facts: the
  acceptance-API pin `GSTile.GetCargoAcceptance(tile, cargo, 1, 1, radius)`
  with `radius = GSStation.GetCoverageRadius(STATION_TRUCK_STOP)`).
- The retained pre-construction census
  (`artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json`),
  re-parsed offline this session (§3 binding).

## 1. The finding of record being extended

Delivery stop `50351` (front `50095`) — the D4-built corridor's only delivery
location — reported zero cargo-1 acceptance in the live Seed-17 world on
OpenTTD 15.3, because the only coal-accepting tile of industry 1 is tile
`51373` (173,200), outside the stop's effective catchment. `D5-FREIGHT-1` is
consumed and closed forever. A future freight attempt needs a delivery stop
whose **native** acceptance fact is derived first. This survey derives those
facts, read-only, before any placement design exists.

## 2. Survey identity, runtime and pins

| Item | Binding |
|---|---|
| Survey identifier | `D5-ACCEPT-SURVEY-1` (one-shot, read-only, no mutation op exists) |
| Binary | OpenTTD 15.3, pinned sha-256 `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c` (REPRODUCE.md), OpenGFX 8.0 `43a0c1da…03be` |
| Source world | authoritative D4 candidate-5 after-save `a81ac836…ef261` (the world `D5-FREIGHT-1` ran on; unchanged by that attempt: zero-cost halt) |
| World identity at connect | `revision 15.3`, `seed 17`, `landscape 0`, `256×256`, `start_day 712223` (the E36 welcome identity) |
| Company / cargo | company 0, cargo 1 (coal), funds expected `£492,149` exactly |
| Corridor pins | pickup `45748`/front `45747`, delivery `50351`/front `50095`, depot `45487`/front `45743` |
| Protocol | protocol 6 (`app/simulation/openttd/corridor_accept_survey.py`), additive over protocol 5, sharing only the 32-unique-request budget cap |

## 3. The pinned exchange sequence (8 read-only exchanges)

Request bodies are canonical JSON under `MAX_SURVEY_REQUEST_BYTES = 512`
(the largest production body measures 211 bytes); responses under 512.
Every request echoes the corridor identity pins and a uniform seal digest;
`max_cost` is 0 on every exchange (the survey has no cost-bearing operation
and its Squirrel handler contains no GS accounting usage at all).

| # | exchange | op | send | returns |
|---|---|---|---|---|
| 1 | `radius-00` | `radius` | — | native truck-stop coverage `radius` (0..255) |
| 2 | `accept-00` | `accept` | tile `50351` (control) | `accept` (0..8) + `radius` echo |
| 3 | `accept-01` | `accept` | tile `50607` | `accept` + `radius` echo |
| 4 | `accept-02` | `accept` | tile `50863` | `accept` + `radius` echo |
| 5 | `accept-03` | `accept` | tile `51119` | `accept` + `radius` echo |
| 6 | `accept-04` | `accept` | tile `51375` | `accept` + `radius` echo |
| 7 | `accept-05` | `accept` | tile `50605` | `accept` + `radius` echo |
| 8 | `prod-00` | `prod` | — | pickup industry 0 last-month production of cargo 1 |

Acceptance is always queried as `GSTile.GetCargoAcceptance(tile, 1, 1, 1,
radius)` with the radius measured natively in the same world (the `radius-00`
exchange must be `READY` before any recordable acceptance exists — the
verifier refuses an acceptance observation whose radius was never measured).

## 4. Hypotheses (retained census) versus expected native outcomes

The candidate tiles come from the retained pre-construction census
(`coverage` entries, role `delivery`, cargo 1), re-parsed offline and guarded
by `test_pinned_hypotheses_match_the_retained_preconstruction_census`:

| Tile | Census hypothesis (pre-construction, offline) | Native expectation for the survey | Meaning if different |
|---|---|---|---|
| `50351` (control) | acceptance 0 | **0** (the finding of record re-measured) | a positive control value would falsify the E36 finding of record and must halt for review, never be relabeled |
| `50607` (175,197) | 8 | ≥ 1/8 | catchment depends on the native radius; a 0 is a real finding |
| `50863` (175,198) | 8 | ≥ 1/8 | as above |
| `51119` (175,199) | 8 | ≥ 1/8 | as above |
| `51375` (175,200) | 8 | ≥ 1/8 | as above |
| `50605` (173,197) | 8 | ≥ 1/8 | as above |

Stated plainly: **these are hypotheses, not valid stops.** No candidate tile
is claimed buildable, no stop exists at any candidate tile, no station is
created, and positive acceptance alone proves only catchment — not a road
connection, not a route, not a freight cycle. The control's measured zero is
a structured `MEASURED` observation only under its correlated `READY`
readback with the radius echo; a refusal, a missing, a malformed, an
out-of-range or a stale observation can never be recorded as any value.

## 5. Offline implementation status (this session, uncommitted)

The protocol-6 contract module, the additive handler and the contract
suite below are unchanged from the first preparation round. This section
adds the implemented native pipeline.

### 5.1 The native staging pipeline (implemented this round)

**`app/simulation/openttd/proof/corridor_accept_survey_native.py` (new)** —
the §6 gap is closed:

1. **Plan binding and cross-plan refusal.** The pipeline is typed to
   `AcceptSurveyPlan` (`_require_survey_plan`), and every staging, seal,
   execution and replay entry point refuses any other plan model. A
   `FreightPlan` cannot be staged or run as a survey, and an
   `AcceptSurveyPlan` cannot ride the freight pipeline (its freight
   `FreightSecureSession` refuses protocol-6 request frames; the survey
   `SurveySecureSession` refuses protocol-5 freight frames — both fail at
   the schema check before any handler).
2. **Survey-sourced staging (`prepare_survey_candidate`)** — binds the
   authoritative D4 candidate-5 after-save via the imported, re-verified
   prerequisite binding (`survey_prerequisite_binding`, which re-checks the
   D4 replay receipt and the compiled corridor pins), the pinned OpenTTD
   15.3 binary digest plus exclusive-runtime gate, the frozen source
   closure and dependency inventory over this module's own closure root,
   the staged save-load composition (same reviewed package bytes), and
   writes the sealed `d5-accept-survey-prelaunch-v1` prelaunch record with
   the survey schedule, zero-cost budget table, world pins, read-only op
   set and hypotheses.
3. **Hypotheses stay hypotheses.** Staging re-parses the retained
   pre-construction census into `HYPOTHESIS` rows (control 0, candidates
   8); an absent census is recorded `CENSUS_ABSENT` and nothing is
   invented. `compare_census_findings` records every measured value
   differing from its hypothesis as a real finding of record in the
   receipt; findings are never normalized and never treated as protocol
   errors.
4. **Execution (`execute_survey_attempt`)** — one launch, one encrypted
   connection, welcome identity matched, the eight read-only exchanges in
   the pinned order, every exchange verified incrementally by the
   production `survey_phase_outcome` (radius FIRST: no acceptance
   observation is recordable before the native radius verifies), funds
   read back per exchange, `max_cost = 0` everywhere, `state_changed`
   pinned false, prefix-preserving halt on the first defect, retained
   request/response pairs and frames, certified cleanup gating the
   completion verdict.
5. **Sealing and preflight** — `PRELAUNCH.sha256` seal discipline as the
   freight candidate; `survey_preflight` re-derives (rather than trusts)
   every binding: schema/lineage, claim-absent, freeze bytes, D2 closure
   and dependencies, schedule and plan digests, world pins, hypothesis
   rows, budget table, identity pins, prerequisite record, staged source
   save and composition bytes, workspace ownership, backend and endpoint
   rehearsal.
6. **Authorization payload** — the shared builder's payload structure
   (`authorization_payload` / `canonical_authorization_bytes`), digest
   rebuildable offline via `staged_survey_authorization_payload_digest`;
   no claim, payload file or signature is created by this task.
7. **Read-only replay verification (`verify_survey_attempt`)** — never
   trusts the candidate's declared status: exhaustive manifest
   verification, authorization re-verification under the production
   operator anchor, prelaunch lineage and every binding re-derived
   (`verify_survey_attempt_identity`), retained welcome re-checked, frames
   re-parsed under the 512-byte protocol-6 bounds, request files, response
   files and unique frame positions cross-checked, duplicates and
   out-of-schedule ids refused, and the full eight-exchange schedule
   re-verified through production `survey_phase_outcome`. A refused,
   missing, malformed, out-of-range, stale or inconclusive exchange makes
   `SURVEY_COMPLETION_VERIFIED` impossible; a forced success label with no
   operator authorization returns structured `AUTHORIZATION_UNVERIFIED`;
   uncertified cleanup denies every verified completion.

### 5.2 Native-pipeline tests

**`tests/test_corridor_accept_survey_native.py` (new, 22 tests)** — staged
candidate binding + `PRELAUNCH PASS` + authorization-payload rebuild,
preflight re-derivation and its refusal of seal/schedule tamper, the
cross-session freight/survey refusals in both directions, the schedule's
read-only op set and exchange budgets, hypothesis/finding semantics, the
exchange helper's request/response pair persistence under malformed,
stale, truncated and over-512 failures, the frame replay parser, replay
fail-closed verdicts (claim absent, claim/manifest/schema tamper, forced
`NATIVE_SURVEY_COMPLETE` labels without authorization) and the exit-status
discipline.

### 5.3 Verification runs (this tree, this round)

survey-native 22/22, survey 25/25, freight 42/42 + freight-native 55/55
(122/122), construction wire/native + route-optimizer 84/84
(`tests/test_corridor_construction.py`,
`tests/test_corridor_construction_native.py`,
`tests/test_corridor_route_optimizer.py`), transport/protocol
80/80 (`tests/test_gamescript_transport.py`,
`tests/test_gamescript_protocol.py`); `ruff check` and `ruff format
--check` clean on both touched files, `py_compile` clean, `git diff
--check` clean, TASKS mirror byte-identity re-verified. A fresh candidate
smoke-staged outside the repository (`PRELAUNCH PASS` ≈ 25 s) exercised
the real staging path end to end; no candidate is staged in the runtime
area and nothing was launched or consumed.

### 5.4 Prior round (bytes unchanged this session)

1. **`app/simulation/openttd/corridor_accept_survey.py` (new)** — protocol-6
   wire contract: `AcceptSurveyPlan` (pinned world + ordered observations),
   `SurveyRequest`/`SurveyReadback` (strict per-op field subsets, domain
   bounds, cross-tile echo refusal, malformed/duplicate/stale bodies fail
   closed), the request-vs-plan verifier, and the fail-closed
   `survey_phase_outcome` verifier over preserved evidence only
   (`SURVEY_COMPLETE` only when all eight exchanges verify; per-observation
   kinds `MEASURED`/`REFUSED`/`MISSING`/`MALFORMED`; measured zero is
   structurally distinct from refusal).
2. **`app/simulation/openttd/d5_freight_package/main.nut` (additive)** — a
   protocol-6 dispatch through a new guarded `SurveyHandle`: fixed
   `survey_planned` schedule with its own prefix-preserving stage
   accounting, shared dispatcher request budget, funds readback per
   exchange, pin/company/pause defences, handler-side acceptance-tile pin
   (`ACCEPT_CONTROL` + `ACCEPT_CANDIDATES`) so only the pinned observations
   are queryable, and zero observation fields on any refusal. The
   protocol-5 freight schedule, latches and handlers are byte-identical.
3. **`tests/test_corridor_accept_survey.py` (new, 25 tests)** — contract
   tests (canonical bounds, malformed/stale/duplicate/cross-tile fail-closed
   surfaces, verifier halts and pending accounting) and controlled-VM tests
   running the shipped package in the real Squirrel VM against the stub
   world: full ordered run, out-of-order and duplicate ids, non-pinned tile
   refusal, stale pin, foreign company, paused world, out-of-range
   native fact (`::accept = 9` → `UNSUPPORTED_NATIVE_FACT`, no values),
   shared budget, and the one-plan-per-session latch (a freight exchange is
   refused `OUT_OF_ORDER` once a survey has latched a plan).
4. **Verification runs (this tree)** — `tests/test_corridor_accept_survey.py`
   25/25 PASS; regressions `tests/test_corridor_freight.py` 42/42 and
   `tests/test_corridor_freight_native.py` 55/55 PASS;
   `ruff check` on the touched files, `py_compile` and `git diff --check`
   clean. No freight predicate was weakened and no D5 identity reused.

The protocol 5 own admission sentence ("the delivery
stop's native cargo-1 acceptance is ≥ 1/8") stays exactly as it was; the
survey adds observation only.

## 6. Native execution requirements when authorized (NOT executed here)

Execution reuses the adopted D4/D5 ceremony discipline from
`corridor_freight_native.py`, importing by the same pattern that module uses
for `corridor_construction_native` helpers: a survey candidate staged from
the reviewed bytes over a copy of the authoritative after-save (source-save
binding verified), sealed `PRELAUNCH` + fresh read-only `PREFLIGHT`, the
frozen closure, exchange-pair persistence (`survey-<id>-request.json` /
`-response.json`), certified cleanup, and read-only replay verification with
`survey_phase_outcome` at the contract module. Evidence required:

- welcome identity matched (§2 welcome identity list) and binary sha pinned;
- preserved request/response bytes for all eight exchanges, failure or
  success, each under the 512-byte bounds;
- `survey_phase_outcome(...)` fail-closed over the retained-safe frame pair;
- a replay verifier that cannot produce `SURVEY_COMPLETE` from a refused,
  missing, malformed, out-of-range or stale exchange;
- the measured values recorded verbatim, statuses copied verbatim, no
  success label invented.

**Current gap — closed this session (2026-10-27):** the pipeline above is
implemented as `corridor_accept_survey_native.py` and validated offline in
§5.3. The smallest-safe-fix sketch that remains here is kept as the design
rationale for that implementation: it reuses — by import, not copy — the
prerequisite-save binding, freeze, manifest, session transport, cleanup and
replay skeleton of `corridor_freight_native.py`, bound instead to
`AcceptSurveyPlan` and the eight-exchange survey schedule. No improvisation
on a live path is possible: the module, its offline tests and any future
candidate are the next increments, before any authorization request.

## 8. Execution outcome — 2026-10-27

Executed and verified: candidate
`artifacts/experiments/d5-accept-survey-native-candidate-1/` (seal
`38b7667e…e06b`), staged `PRELAUNCH PASS` + independent fresh `PREFLIGHT
PASS`, operator-authorized, one launch, one connection and the exact eight
read-only exchanges (radius 3; control 50351 = 0; candidates 50607/50863/
51119/51375/50605 = 8; production 104; funds £492,149 each exchange;
`max_cost 0` everywhere). Replay `SURVEY_COMPLETION_VERIFIED` exit 0,
certified cleanup, zero world mutation, census findings empty. §7 above
records that no authorization existed at writing time; the session of
record consumed exactly the authorized one. One fail-closed post-attempt
correction (replay receipt-arm shape comparison) is documented with its
regression tests in
`docs/handoff/2026-10-27/d5-accept-survey-native-candidate-1-outcome.md`.

## 7. Explicit authorization required to execute (not granted)

The previously granted authorization covered the first native freight
attempt only and is consumed. Executing `D5-ACCEPT-SURVEY-1` requires a
fresh, explicit operator authorization record covering exactly: staging the
one survey candidate from these reviewed bytes, sealing + preflight, and
exactly one bounded read-only native survey session (1 launch, 1 connection,
≤ 32 request budget, 8 planned exchanges, zero-mutation discipline — no
constructions, orders, purchases, saves from the survey side). Nothing in
TASKS.md, this document, the design records or any past authorization
grants it. The next action must be that explicit approval for this survey
alone; anything broader is refused.

## 9. Post-survey audit and independent review of the replay fix (2026-10-28)

The §8 correction's final shape was reviewed by a fresh-context
independent reviewer; the full report is retained at
`docs/handoff/2026-10-28/d5-survey-replay-fix-independent-review.md`.

**Verdict: `MATERIAL DEFECT: no`.** The compared key set and the written
`receipt.json` shape both derive from the same production
`survey_phase_outcome` (keys auto-sync in both directions), the retained
`census_findings` is re-derived — twice, redundantly — from re-derived
observations, never copied, and no fail-closed predicate is weakened.
Three minor findings were recorded as standing remediations for the next
byte review of this module (none blocking, none accepts a refused,
malformed, stale, missing or forced-labeled exchange):

1. `before_save_sha256` is written but never re-compared against a
   re-hash of `session-before.sav` in replay (the freight twin compares
   every written key).
2. The verified arm lacks an explicit "verified receipt record missing"
   guard (masked today by the exhaustive artifact-manifest check).
3. Replayed census hypotheses are not re-pinned against the retained
   census bytes the way preflight pins them.

No remediation was applied in this task. The corridor-extension design
recorded this same day
(`docs/handoff/2026-10-28/d5-corridor-extension-design.md`) consumes the
survey's measured facts under their own §1/§2 evidence classes.
