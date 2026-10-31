# D5 corridor extension — offline design and implementation record

Status: **OFFLINE DESIGN AND IMPLEMENTATION ONLY.** No OpenTTD process was
launched, no AdminPort connection, no candidate staged in the runtime
experiment area, no claim, no authorization payload file, no signature and
no Gate C artifact exist from this work. The authoritative D4 candidate-5
after-save, every sealed candidate, every consumed identity and the
pre-existing `OpenTTD-Knowledge/.obsidian/workspace.json` modification are
untouched. Nothing committed or pushed.

Predecessors:

- [D5-ACCEPT-SURVEY-1 outcome](2026-10-27/d5-accept-survey-native-candidate-1-outcome.md)
  (the measured acceptance facts this design consumes)
- [D5 freight candidate-1 outcome](2026-10-27/d5-corridor-freight-native-candidate-1-outcome.md)
  (the accept-0 finding of record, retained forever; `D5-FREIGHT-1` and
  `D5-ACCEPT-SURVEY-1` identities and authorization artifacts are consumed
  permanently and never reused)
- [D5 freight design](../../../docs/d5-corridor-freight-design.md)
  (the acceptance-API pin `GSTile.GetCargoAcceptance(tile, cargo, 1, 1,
  radius)` with the measured radius)

## 1. Survey audit and independent review of the replay fix

The outcome record's §1.5 post-attempt correction (replay receipt-arm
shape comparison) was given a fresh-context independent review; the full
report is retained verbatim at
[d5-survey-replay-fix-independent-review.md](2026-10-28/d5-survey-replay-fix-independent-review.md).

Verdict: **MATERIAL DEFECT: no.** The compared key set and the written
receipt shape both derive from the same production `survey_phase_outcome`
(auto-sync in both directions), `census_findings` is genuinely re-derived
twice from re-derived observations (never copied), the JSON round-trip
handles the tuple/list equality, and no fail-closed predicate is weakened
(refused/missing/malformed/stale exchanges and forced labels stay
unverifiable; the receipt arm only adds strictness).

Minor findings (retained with narrow remediations, none blocking):

1. `before_save_sha256` is written into the receipt but never compared in
   replay — the one key outside the sync mechanism (the freight twin
   compares every written key against a re-hashed `session-before.sav`).
   Narrowest remediation: one comparison against
   `sha256(directory / "session-before.sav")` in the verified arm.
2. No explicit "verified receipt record missing" guard (masked today by
   the exhaustive artifact-manifest check). Narrowest remediation: an
   explicit `else: raise ValueError(...)` on the verified arm.
3. Replayed census hypotheses are not re-pinned against the retained
   census bytes preflight-style. Narrowest remediation: reuse the
   preflight pin loop inside `verify_survey_attempt_identity`.

No remediation was applied in this task: the review found no material
defect, the survey identity is consumed, and its module bytes bind the
consumed candidate only through the retained manifest. The findings are
recorded as the standing remediation list for the next byte review of
that module (any future survey candidate, e.g. the post-construction
acceptance recheck below, must carry them).

## 2. Verified candidate geometry (evidence-classed)

Source evidence: the authoritative D4 candidate-5 after-save bindings
(`artifacts/experiments/d4-corridor-native-candidate-5/corridor-route-read.json`,
`corridor-0X-*.json`, receipt-bound by `after.sav`
`a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261`), the
retained pre-construction census
(`artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json`),
and the survey's measured facts. Tile arithmetic: `tile = y*256 + x`
(256×256 map), confirmed against every cited tile.

**Measured facts (native, retained):** truck-stop coverage radius 3;
acceptance 0 at 50351 (control, live-world); acceptance 8 at 50607,
50863, 51119, 51375, 50605; production 104; funds `£492,149`.

**Measured facts (native, D4 construction readbacks):** closed corridor
route `ROUTE_VERIFIED`, 24-tile witness, 23/23 connected pairs; pickup
stop 45748 front 45747 (sid 0, non-drive-through truck stop, linked,
cost £307); delivery stop 50351 front 50095 (sid 1, £292); depot 45487
front 45743 (orientation south, £390); company road runs: run A y=178,
x=175..180; run B x=175, y=179..195 (witness tail 50095=(175,195) is the
front, 50351=(175,196) the dead-end stop tile). Every D4 op carried a
positive tested native quote and matching funds debit.

**Source-derived conclusions:** acceptance catchment is Chebyshev-
consistent with the measured radius: the accepting industry tile
51373=(173,200) is at Chebyshev distance 4 from the control stop
50351 (outside radius 3 → measured 0) and distance ≤3 from every
candidate (inside → measured 8). The census-classed tile rows for all
branch tiles are flat (`slope 0`), buildable, treeless, waterless and
(census-era) roadless: 50096 (176,195), 50352 (176,196), 50608 (176,197),
50094..50606 (west branch row and column), 50607. Industry 1 occupies
(173,199), (173,200), (174,200); (176,200) is tree-covered (irrelevant:
no op touches it).

**Hypotheses (fail-closed at native admission time):**
- The census-era vacancy of the branch tiles persists into the D4-after
  world (D4's retained build evidence covers only the 24-tile witness,
  `D5-FREIGHT-1` mutated nothing, and every admission re-observes the
  pins natively — the plan must never trust the census for a build).
- Quoted build costs are priced by native test mode at runtime, never
  guessed offline; D4's neighboring quotes (road piece £71, stop
  £292–£307, roughly £115–£140/plain road tile) bound expectations only.
- A stop tile whose native acceptance reads ≥1/8 sits inside the radius-3
  catchment of an industry tile that natively accepts cargo 1 — the
  survey's `accept 8` values satisfy this, NOT the `industry_covered`
  flag alone.

## 3. Recommended placement (primary and fallback)

1. `50607` — immediately south-east reachable from the road terminus, on
   x=175+1: **primary.**
2. `50863`, `51119`, `51375` — farther south on x=175 (longer, dead-end
   column, same measured acceptance; no benefit, more tiles, more
   quote/cost surface; all blockable by the same frontier analysis).
3. `50605` (173,197) and other west-branch alternatives — **fallback**
   (needs the mirrored west branch; equal measured evidence, one extra
   tile of quote surface if fronted from 50606).

Recommended construction sequence (primary), all pre-states validated
natively at inspect time by the production admission rules —
fail-closed on any unexpected existing road, station merge, cost
overrun, partial construction or readback mismatch:

| # | op | pins | pre-state required | post-state verified |
|---|---|---|---|---|
| 0 | inspect/command/read `full` | start 50096 → end 50608 (3 tiles) | both endpoints and the span unowned, roadless, flat, vacant | run_len 3, covered 3, pairs 2/2, both endpoints company road |
| 1 | inspect/command/read `road` | 50095 ↔ 50096 (1-tile join) | both endpoints company road, pair NOT yet connected | joined both directions, cost re-quote equal |
| 2 | inspect/command/read `station` | tile 50607, front 50608 | stop tile unplanned unowned ground; front IS company road (handler samples `front_road`; the wire-level front gate the D4 copy lacked is now mirrored into the handler) | non-drive-through truck stop, `linked` true, front-adjacency, geometry fields equal across built/read arms |
| 3 | `route` read (pure observation, cost 0) | 29-tile witness `45748, 45747, 45746, 45745, 45744, 45743, 45999, 46255, 46511, 46767, 47023, 47279, 47535, 47791, 48047, 48303, 48559, 48815, 49071, 49327, 49583, 49839, 50095, 50351, 50095, 50096, 50352, 50608, 50607` | — | 28/28 pairs company-connected, first_fail −1, head/tail truck stops (45748, 50607), depot pin intact |

Design invariants:

- **No terrain modification anywhere.** Every op is road/stop on flat
  vacant ground; the plan refuses any raise/clear op.
- **No station merge.** The package pins `GSStation.STATION_NEW`
  (the D4 handler's own build call, byte-preserved): a station join into
  the existing sids 0/1 is a defect, and a replay-time check refuses a
  built `sid` equal to either existing station id, fail-closed. The
  handler-side `front_road` eligibility gate is the one additive logic
  change over the D4 copy (mirrors the production Python admission rule
  the D4 package enforced only Python-side; no reply-shape or validation
  logic changed).
- **New stop catchment:** 50607 reaches 51373 at Chebyshev distance 3 =
  the measured radius → native tile acceptance 8 (measured live-world).
  The stop must never be ordered to serve cargo by `industry_covered`
  alone: the acceptance recheck below re-derives the fact natively
  post-construction, before any freight attempt.
- **Preservation:** the witness path includes the full existing corridor;
  28/28 pairs re-verified after construction keeps the D4 corridor and
  its evidence intact (the two additions touch only 50095's road bit
  toward 50096 and the new branch/nothing else of the witness).
- **Funds precondition (exactly pinned):** the at-session baseline funds
  MUST read `£492,149` (the D4 close-out pin) before op 0's admission;
  every later exchange verifies `funds = 492149 − Σ verified op cost`
  with each per-op cost ≤ `£2,000` and equal to its admission quote.

Fallback placement (west branch), same op shapes mirrored: `full`
50094 → 50606 (3 tiles) , `road` 50095 ↔ 50094, `station` tile 50605
front 50606, identical funds/ceiling/pairs discipline (stop
50605=(173,197) fronted by 50606=(174,197); stop-to-industry Chebyshev
distance 3, measured acceptance 8). It is the designed fallback because
the branch fronts the same road terminus and needs no extra geometry.

## 4. Implementation prepared offline

Files added this task (uncommitted):

- `app/simulation/openttd/d5_extension_package/main.nut` — the extension
  GameScript package (D4 copy with the pinned schedule above; ready
  marker `D5_EXT_READY`; 3 staged ops + route read; request budget 16;
  `STATION_NEW` build call byte-preserved).
- `tests/test_corridor_extension.py` — controlled real-Squirrel-VM suite:
  23/23 PASS (happy path + budget + ordering + eligibility + cost +
  stale + route witnesses + no-auto-join probe).
- `app/simulation/openttd/proof/corridor_extension_native.py` — the
  candidate pipeline: D4-candidate-5 prerequisite binding, evidence-
  derived `extension_schedule()` (witness from `corridor_facts()`, branch
  pins derived + cross-checked against the retained census and the D4
  route read; refusal on any drift), plan policy (company 0, per-op
  `£2,000`, budget 16, funds `£492,149` pin, STATION_NEW discipline,
  acceptance-recheck statement staging), prepare/preflight
  (`PRELAUNCH` seal + fresh independent re-derivation), execution
  bindings (inspect→command→read per op, `D5_EXT_READY`, per-exchange
  persisted request/response pairs, funds arithmetic, prefix-preserving
  halt, `sid ∉ {0,1}` station-merge refusal, 29-tile route receipt), and
  the replay-only fail-closed `verify_extension_attempt` (manifest/seal,
  authorization re-verification under the production anchor with
  structured `AUTHORIZATION_UNVERIFIED` for forced labels, frame
  schedules, duplicates/orphans refused, phase outcome re-derivation
  through the production corridor verifiers; verified status
  `EXTENSION_COMPLETION_VERIFIED` requires all 10 exchanges, certified
  cleanup, exact funds and cost ceilings).
- `tests/test_corridor_extension_native.py` — 43/43 PASS (derivation
  failure modes, plan/budgets, staged seal+preflight+refusals, digest
  rebuild without any claim/payload/signature, the replay fail-closed
  family, the synthetic consumed 10-exchange replay, exit statuses).

The prelaunch/policy and the verified receipt carry, verbatim: the
acceptance recheck happens in a **separate read-only survey session on
this attempt's after-save, with fresh derived candidate and its own
authorization, before any freight order or vehicle purchase**. The
construction operations are strictly protocol 4 + this package; nothing
of the read-only acceptance-survey protocol rides inside this pipeline.

Test suites run this task (all PASS):
survey 25, survey-native 25, extension 23, extension-native 43,
construction 41, construction-native 43, freight 42, freight-native 55,
gamescript transport + protocol, corridor route optimizer (regressions).
`ruff check` and `ruff format --check` clean on all touched files,
`py_compile` clean, `git diff --check` clean, TASKS mirror
byte-identical.

## 5. Remaining unknowns and safety limitations

- The live-world pre-state of the branch tiles is a census-era hypothesis
  validated only at native admission time; the plan is fail-closed there
  (roadless unowned flat required, quoted positive cost required), but
  the offline evidence cannot settle it.
- Exact quoted costs are runtime native facts; offline expectations are
  bounded, never asserted.
- `STATION_NEW` never-join semantics are asserted by readback
  (`sid ∉ {0,1}`, separate station) rather than proven from source; the
  replay check converts a join into a halted, uncertain-world failure.
- The survey package (`d5_freight_package/main.nut`) still hardcodes its
  acceptance pins; the future post-construction acceptance-recheck
  candidate requires an additive review binding the new stop tile pins
  (control: the retired 50351 fact stays historical; new control and
  candidates must be re-pinned and NEVER reuse `D5-ACCEPT-SURVEY-1`).
- Route connectivity is verified pairwise (the native `AreRoadTilesConnected`
  discipline); it is not a pathfinding proof, and no vehicle, order or
  delivery exists in this design.

## 6. Authorization required for the construction session (not granted)

Executing `D5-CORRIDOR-EXTENSION-1` requires a fresh, explicit operator
authorization record scoped to EXACTLY: staging one candidate from these
reviewed bytes over a copy of the authoritative D4 candidate-5
after-save, sealing + independent preflight, and one bounded construction
session — 1 launch, 1 connection, ≤16-request budget, 10 planned
exchanges, per-op `max_cost £2,000`, funds baseline `£492,149`,
prefix-preserving halt, certified cleanup, zero freight/order/vehicle
operations, acceptance logic absent. The freight attempt remains a
separate, later authorization with its own fresh candidate. The consumed
`D5-FREIGHT-1`, `D5-ACCEPT-SURVEY-1` identities and artifacts are never
reused. Nothing in this record grants any of it.

## 7. Remediation record — 2026-10-28 (construction review F1/F2)

The independent construction review returned `BLOCKED PENDING REMEDIATION`
with two findings. Both are remediated in the uncommitted working tree; no
candidate was staged, no launch occurred, and sections 1-6 above are
unchanged historical record.

### F1 (CRITICAL) — funds-gate arithmetic at the command/read gates

Defect: in `execute_extension_attempt`
(`proof/corridor_extension_native.py`), the post-command gates called
`_funds_gate(built, spent, ...)` and `_funds_gate(independent, spent, ...)`.
The native handler (`d5_extension_package/main.nut`) reports `r.funds =
post.funds` — the POST-debit balance — and enforces
`funds - r.funds == r.cost`, while the host's `spent` accumulator only
advances after `verify_corridor`. The gates therefore compared the
post-debit balance against `492149 − previous_spent` (the pre-debit
expectation), so a correct native construction was rejected at `op-00
command` and the attempt halted before it could finish.

Fix (smallest correct change, two call sites):

```python
_funds_gate(built, spent + int(built.cost), label + " command")
_funds_gate(independent, spent + int(built.cost), label + " read")
```

Why this is mathematically correct: for a post-command observation the
expected balance is
`expected_funds = initial_funds − (previous_spent + current_operation_cost)`
`= FUNDS_PIN − (spent + built.cost)`, exactly `_expected_funds(spent +
int(built.cost))`. No double-count is possible: `spent` is incremented only
after `verify_corridor` succeeds (line `spent += int(built.cost)`), so at
both gates `spent` provably excludes the current op's cost, and
`built.cost` is that op's actual native cost — `verify_corridor` pins
`built.cost == intent.native_test_cost` and `before.funds − built.funds ==
built.cost`, and the independent read is gated on the identical balance
(`verify_corridor` also pins `independent.funds == built.funds`). The
inspect gate (`_funds_gate(before, spent, ...)`) is unchanged and correct:
the inspect observes the pre-debit balance. The route-read gate
(`_funds_gate(route, spent, "route-00")`) is unchanged and correct: by then
`spent` includes every verified op cost and the route read is pure
observation with `cost == 0`. The replay funds arithmetic
(`_expected_funds(sum(completed costs))`) is unchanged. Cost ceiling,
funds pin, station gates, operation order and prefix-preserving halt
semantics are untouched.

### F2 — execution arm had no test coverage

`tests/test_corridor_extension_native.py` gained a scripted-backend
execution arm (18 tests) driving the REAL `execute_extension_attempt`
production path: real preflight, real `exchange`/`CorridorReadback` wire
parsing, real `admit_corridor`/`verify_corridor`/`corridor_phase_outcome`/
`verify_corridor_route`, real funds/station gates, real diagnostic-save/
cleanup/log-health tail, and (on the success path) the real replay verifier
reaching `EXTENSION_COMPLETION_VERIFIED` over the retained evidence. The
scripted backend implements the production backend interface
(preflight/launch/health/connect/cleanup, console saves with real files and
acks, frame observation over real Admin wire frames). The only
monkeypatched seam is the operator-authorization gate (`grant_launch`),
exactly as in the pre-existing consumed-frame replay section: no operator
private key exists under the tests. No OpenTTD launch, no AdminPort. (On
the replay-tail assertion inside the success-path test, the synthetic
grant's fabric signature also requires nulling `replay_authorization_state`,
exactly as in the consumed-frame replay section; one test additionally
patches the `FakeStdin` test double to simulate a native save failure.
Neither touches a production verifier.)

Coverage: (1) successful complete attempt — all three inspect-command-read
groups, the 29-tile route read, cumulative cost/funds accounting, verified
receipt plus replay verification (proves the arm reaches route-read and
final-verification logic, not just a first refusal); (2) post-debit
accounting at every gate; (3) the exact F1 regression — £492,149 pin,
£454 op-00 cost within the £2,000 ceiling, correct post-debit £491,695
accepted — plus the negative case where the handler reports the pre-debit
balance and the gate still fails closed; (4) funds drift halts and blocks
later ops; (5) cost violations (over-limit, negative, zero, inconsistent
command cost) fail closed before mutation; (6) unanswered command frame
halts at `DISPATCHED_UNKNOWN` without fabricating success and retains the
diagnostic save; (7) diagnostic-save failure recorded, never verified;
(8) receipt-save failure refuses verified success; (9) log-health findings
and abnormal return code demote a nominally successful protocol sequence;
(10) failed independent readback preserves attempted-operation evidence,
halts later ops, refuses success; (11) station merge and drive-through
identity halt before later ops; (12) route-read mismatch yields no receipt
and no completion verdict.

### Validation (2026-10-28)

- Focused execution-arm tests: 18/18 PASS.
- `tests/test_corridor_extension.py` + `tests/test_corridor_extension_native.py`
  (61 tests), survey + survey-native, freight + freight-native, D4
  construction + construction-native, route-optimizer: see the remediation
  run results recorded in TASKS.md.
- Ruff lint, Ruff format check, `py_compile`, `git diff --check`: clean.
- TASKS mirror byte-identity: verified.
- Independent fresh-context re-review of the remediation diff: the report
  follows below.

### Independent re-review — 2026-10-29

A fresh-context reviewer who did not implement the remediation examined the
fix, the execution-arm tests, the native handler and the record above;
read-only inspection plus a re-run of the focused execution-arm tests
(18/18 PASS). Verdict: **MATERIAL DEFECT: no.**

- Funds arithmetic verified at every phase by independent algebra:
  inspect gate `492149 − spent` (pre-debit); command/read gates
  `492149 − (spent + built.cost)` (post-debit; `built.cost` is the
  handler's actual cost, pinned equal to `intent.native_test_cost` and to
  `before.funds − built.funds`; `independent.funds == built.funds`);
  route gate `492149 − spent_full` (cost 0); replay
  `route.funds == 492149 − Σ(completed receipt costs)`. All reduce to the
  same pinned rule `expected = 492149 − verified prefix total` with the
  correct inclusion boundary per phase (492149 − 454 − 71 − 307 = 491317).
- No double-count: `spent += int(built.cost)` occurs exactly once, after
  `verify_corridor` succeeds; both post-command gates pass the sum as an
  argument and never mutate `spent`.
- Execution-arm tests drive the real `execute_extension_attempt` over the
  real verifiers and gates with real Admin wire frames; the only
  monkeypatched seams are the operator-authorization gate, the
  authorization-replay state on the replay-tail assertion, and one
  test-double console patch — no production verifier is mocked.
- All 18 failure tests refuse success through production code
  (`_funds_gate`, `admit_corridor`, `verify_corridor`,
  `corridor_phase_outcome`, `_station_gate`, `verify_corridor_route`, the
  diagnostic-save/log-health/returncode demotion branches); no test
  fabricates a pass; negative outcomes are retained on disk.
- No safety predicate weakened: the fix is exactly the two call sites;
  station gate, cost ceiling, halt semantics, phase outcome, replay
  manifests/order/frame checks, funds pin and cleanup certification are
  untouched; the D4/corridor-construction verifier module has no edits.

Residual notes (recorded, none blocking): the replay does not individually
pin every retained per-op `before.funds` to `pin − prefix` (only the
opening balance), a pre-existing design property whose fabrication risk is
anchored by the operator-authorization replay and artifact manifest; and
the §7 wording above was amended to name the two additional
monkeypatched/test-double seams the reviewer identified.

Nothing was committed, staged, launched or authorized. The consumed
`D5-FREIGHT-1` and `D5-ACCEPT-SURVEY-1` evidence and all pre-existing
dirty/untracked files are preserved. `D5-CORRIDOR-EXTENSION-1` remains
unstaged; construction still requires the explicit operator authorization
described in section 6.
