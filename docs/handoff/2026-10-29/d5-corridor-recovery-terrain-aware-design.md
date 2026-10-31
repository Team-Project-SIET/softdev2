# D5 corridor extension — terrain-aware recovery design and offline implementation record

Status: **OFFLINE DESIGN AND IMPLEMENTATION ONLY.** No OpenTTD process was
launched, no AdminPort connection was opened, no candidate was staged in the
runtime experiment area, and no claim, authorization payload, signature or
Gate C artifact exists from this work. The corridor extension remains
**NOT VERIFIED** end to end until a future separately authorized native
attempt runs. The authoritative D4 candidate-5 after-save, the consumed
identities, and the pre-existing `OpenTTD-Knowledge/.obsidian/workspace.json`
modification are untouched. Nothing was committed or pushed. All changed
files are dirty in the working tree, added alongside the pre-existing dirty
and untracked baseline state.

Predecessors (read-only, unmodified):

- The halted D5-CORRIDOR-EXTENSION-1 attempt evidence:
  `artifacts/experiments/d5-corridor-extension-native-candidate-1/`
  (older generation; its identity is consumed permanently and is never
  reused). This candidate generation differs from the one described in the
  2026-10-28 design below; the geometry redesign is the subject of this
  record.
- [2026-10-28 D5 extension design](../2026-10-28/d5-corridor-extension-design.md)
  (survey audit, placement analysis, F1/F2 remediation — geometry pins now
  superseded by this record; its acceptance instrumentation is unchanged).
- [2026-10-27 freight outcome](../2026-10-27/d5-corridor-freight-native-candidate-1-outcome.md)
  and [2026-10-27 accept-survey outcome](../2026-10-27/d5-accept-survey-native-candidate-1-outcome.md)
  (`D5-FREIGHT-1` and `D5-ACCEPT-SURVEY-1` consumed; the measured facts of
  record).
- D3 terraforming receipts (`artifacts/experiments/d3-terraform-native-candidate-1/receipt.json`)
  and the census slices in `artifacts/demos/classification-exec-seed17-3a8f9e46/`.

## 1. Root cause of the halted attempt (evidence-backed)

The halted attempt mutated the world twice and then halted fail-closed at
the station op, never verifying anything:

1. `inspect-00`/`full-00` and `road-01` **actually mutated** the non-authoritative
   diagnostic save: two road ops, £987 + £142 = £1,129, funds £492,149 →
   £491,020 (`ext-00-*.json`, `ext-01-*.json`; `result.json`).
2. `inspect-02` (the station op's first and only native pre-state sample) came
   back `NOT_BUILDABLE` with `stop_slope=9` and `front_slope=8`
   (`inspect-02-response.json` — the halted attempt's retained evidence is at
   `frames.json` and the halt label `ValueError: native READY admission with
   positive tested cost required` in `result.json`).
3. The plan's "flat" pre-state had **never been verified for the road ops**:
   the handler's road-op replies (`run_len/covered/pairs/owners`) carry no
   slope fields at all, so the mutation prefix was built blind with respect
   to the very fact that refused the stop.

Why the stop was sloped while the census said flat: the D3 terraforming
receipt (`artifacts/experiments/d3-terraform-native-candidate-1/receipt.json`)
records 16 tile raises with corner S at tiles 48558..50351, touching corner
points `shared_point_x` 175/176 and `shared_point_y` 190..197. On this map
(tile = y*256 + x) the raised corner columns feed the corner model of the
delivery terrace's edge: the live native slope at the planned stop 50607 was
9 (its N/W corner points raised: 175,196 and 176,196 plus shared points), and
after the branch road built, 50608 read 8. The retained census
(`d4._retained_network_facts()`, verified against the accept-survey's own
measurement-session census slices this session: rows for 50863, 50864 and
51119 all slope 0) predates those raises on the terrace rows y=195..196..197:
the grade was stale for the terrace edge, honestly labeled census-grade
evidence in the 2026-10-28 design, but no live slope check ever ran before
the first mutation.

The halt itself was correct: prefix-preserving, funds-consistent, cleanup
certified, `result.json` world state `UNCERTAIN_AFTER_FAILED_COMMAND`. The
defect was the plan: it sampled terrain in the mutation order rather than
before any mutation.

## 2. Redesigned geometry (the terrain-aware branch)

Within the raised corner columns (x 175/176, y 190..197), the tile 50351 sits
outside the shared-corner influence (all four of its corner points were
raised by the D3 receipts, so it stays flat), while 50607/50608 lie inside.
The branch therefore moves south onto ground the D3 receipts prove untouched
by any raise: the receipt's y range tops out at 197 as shared points, and the
new pins use rows y=195..198 at x=176 for the run plus y=198 at x=175 for the
stop. Pins (all subsequently re-checked against the census and the D4
corridor facts offline):

- Branch full run 50096 → 50864, straight, x=176, y 195..198, **run_len 4**
  (tiles 50096=(176,195), 50352=(176,196), 50608=(176,197), 50864=(176,198)).
- Road join 50095 ↔ 50096 (unchanged; the run cannot start on the delivery
  front, which is company road and roadless-eligibility false).
- Branch truck stop **50863** fronting **50864** (`GSStation.STATION_NEW`).
- Extended witness: 30 tiles — the 24-tile D4 corridor, the retraced
  delivery front 50095, the four branch run tiles, and the stop tile last
  (29 expected connected pairs; the retrace of the 50095/50351 dead end is
  by design).
- Fallback west (`50605` fronting `50606`, mirrored west branch) is recorded
  in the predecessor design as measured-equal; it is **not implemented**
  here and needs its own authorized candidate if the east stop proves
  natively unbuildable.

Predicted flat vs live fact: the D3 receipts prove the corner points of
50863/50864 were never raised, so the predicted live slope is 0 — but the
**live slope of 50863 and 50864 is an UNKNOWN until a native verify** (the
acceptance survey measured acceptance, not slopes, at those tiles; the
census is hypothesis-grade). The gate below treats this exactly as an
UNKNOWN: the pre-admission refuses anything while the live facts fail.

## 3. Zero-surprise pre-admission (engine-honest gate)

Design fork this work settled explicitly (recorded verbatim): the shipped
wire contract and its Python side cannot gain a new "pre-admission" wire op
(`corridor_construction.py` STATUS/op literals are frozen; and the D4
`d4._parse_phase_frames` would raise on any non-CorridorRequest outbound
frame), so the gate rides inside the stage-0 `full` inspect of the existing
package `d5_extension_package/main.nut`.

Native semantics constraint (the evidence that forced the redesign of
yesterday's whole-schedule test chain): **native test mode validates and
prices a command but never persists its effects and never creates the
infrastructure a dependent command would need.** The repo's own records
prove it: a vehicle test-mode purchase cannot succeed on an unbuilt depot
(`docs/first-freight-delivery-proof.md`, §16.1 "vehicle test-mode purchase
cannot succeed on an unbuilt depot"), and the road fair-use record refuses
to assume test mode simulates a preceding construction
(`docs/road-freight-infrastructure-proof.md`, "Independent nonoverlapping
test sites avoid assuming that test mode simulates a preceding construction";
also `docs/minimum-freight-vertical-slice.md`: "Test mode does not create
infrastructure or vehicle IDs for subsequent commands"). A one-GSTestMode
chain that builds full → road → station inside the scope and observes each
dependent op's pre-state inside the same scope therefore **always fails
closed in the real engine** (the road op would read 50096 roadless, the
station op roadless at its front). It was replaced with the engine-honest
gate; the offline implementation of the gate is:

- **Whole-branch live terrain survey (pure observation, zero mutation):**
  at stage-0's inspect the handler reads each full-run tile, the join's new
  end, the stop tile and its front — validity, live slope (must be 0),
  live vacancy (`GSTile.IsBuildable`, ownership, water/coast/tree/farm/
  rock/rough, no transport of any kind) — plus the stop/front's own
  `GSTile.GetSlope`/`GetMinHeight`, and the delivery front's live road
  fact. This is exactly the evidence that refused the halted attempt
  (native slope 9 at the predecessor's stop), sampled **before any
  mutation**. Any sloped tile refuses `NOT_BUILDABLE` (with the stop/front
  slope facts in the reply's `stop_slope`/`front_slope` fields); any
  occupied tile refuses `NOT_BUILDABLE`; a native-fact breakage refuses
  `UNSUPPORTED_NATIVE_FACT`.
- **Independent native test-mode validation of the join command** (the one
  command whose eligibility is order-independent): quote `GSRoad.BuildRoad(
  50095, 50096)` inside a test-mode scope against the live unbuilt join
  ground, requiring positive cost, cost ≤ per-op ceiling and live funds
  covering it. Failures map: quote refusal / zero cost → `REJECTED`, over
  ceiling → `COST_LIMIT`, funds → `INSUFFICIENT_FUNDS`, native-fact →
  `UNSUPPORTED_NATIVE_FACT`.
- The gate refuses the stage-0 admission itself: no staged op is ever
  admitted, dispatched or debited while any branch fact is live-sloped or
  occupied. The stub-level positive case (whole schedule buildable and
  priced) is covered by the existing VM tests: the first op only reaches
  READY after the gate passes.

**Honest limitation (not a claim of a fully pre-verified schedule):** the
stop op's native buildability cannot be pre-verified before its front road
exists natively (a road station's entrance needs the real built front — the
same engine constraint as the vehicle/depot precedent). The gate is
necessary, not sufficient. The residual post-gate exposure is bounded to
the schedule's road prefix: if the native world refuses after the gate
passed, the halt stays prefix-preserving and the exchanged evidence remains
`PARTIAL_EXECUTION_EVIDENCE`/uncertain per the frozen wire contract
(`corridor_construction.py` `corridor_phase_outcome`), never a success
label. No test, comment or receipt claims that "partial mutation is
eliminated"; the claim is precisely: no mutation occurs before the branch
terrain is live-proven flat/vacant and the independent command is
test-price-provable.

## 4. Surveyed alternates (no viability assumed)

Every alternate was classified only against the measured acceptance survey
and census evidence; none was assumed viable; none consumes this
candidate's identity.

| Tile (front) | measured acceptance | census | D3-raise corner evidence | status for this design |
|---|---|---|---|---|
| 50863 (50864) | 8 | slope 0 rows, x=175/176 | shared points y up to 197; row y=198 outside | **primary, implemented** (live slopes UNKNOWN until native verify) |
| 51119 (51120) | 8 | slope 0 (51119 census row verified live this session) | same style, farther south (y=199, x=175) | not implemented; farther run (5 tiles), same gate class |
| 51375 (51376) | 8 | slope 0 | beyond 51119 y=200 | not implemented; no acceptance benefit, longer run |
| 50605 (50606) | 8 | 50602..50606 flat | west branch row x=173 | recorded fallback only (mirrored west branch), out of scope |
| 50607 (50608) | 8 | slope 0 in census, **live slope 9/8** | inside raised terrace corner columns | refused by design — the halted attempt's stop |

UNKNOWNs carried forward (all fail-closed at native admission; none is
assumed by any test):

- live slope/height/terrain of 50863 and 50864 in the D4-after world
  (predicted flat from the D3 receipts; census only);
- live vacancy and ownership of every branch tile at the D4-after world;
- live acceptance at 50863 in the D4-after world (the survey ran against
  its own session world);
- the station op's native buildability/price (only natively provable after
  the road prefix exists);
- the live re-quote equality of the join command across the two ops.

## 5. Tests (all offline; results at implementation completion)

Squirrel VM suite `tests/test_corridor_extension.py` (**32 tests, all
green**):
happy path (each op READY only after the whole gate passes, then built and
read), the pre-mutation gate refusals (sloped stop with its native slope
fact in the reply, sloped run tile, occupied stop tile, occupied run tile —
each asserting status NOT_BUILDABLE, `real_calls == 0`, funds unchanged,
no stop creation), chain-preview zero-cost → REJECTED, quote refusal →
REJECTED, ceiling → COST_LIMIT, funds → INSUFFICIENT_FUNDS, pin-migration
assertions (witness 30 tiles/29 pairs, run_len 4, station 50863/50864),
STATION_NEW arguments, merge-probe discipline, route-read witnesses and the
package's op-surface prohibition (no vehicle/order/cargo/terraform/
demolition/rail/dock/airport op surface in the shipped package text).

Replay/execution suite `tests/test_corridor_extension_native.py` (61 tests,
all green): pin equality against the retained census and built corridor
evidence (with fail-closed refusal on slope drift, obstruction, evidence
drift, corridor overlap and pinned-witness drift), staging/preflight
discipline, synthetic attempt replay fail-closed on every defect class
(funds drift, cost overrun, per-op ceiling, station merge to sid 1, drive
through, pair accounting, route funds, duplicate frame, out-of-schedule,
malformed frame, orphan response, cleanup, manifest, truncation, claim
mismatch, consumed-state checks), the halted-attempt prefix-immanent
replay, and the execution arm: full schedule completion with the
independent route read, funds accounting at every gate, halt-on-drift,
failure-mode demotions, diagnostic-save uncertainty, station-merge/identity
halts and the route-read mismatch refusal (no vehicle/order/cargo op exists
in the plan by construction).

Regression suites accepted: survey (`accept_survey` ×2), construction
(×2), freight (×2), route optimizer, planning optimizer — **259 passed**
(6m29s).

Static gate: `ruff check` (all green), `ruff format --check` (green after
formatting the three Python files), `py_compile` (green), `git diff
--check` (clean).

## 6. Changed paths (exact working-tree diff of this task)

- `app/simulation/openttd/d5_extension_package/main.nut` — pins moved to the
  terrain-aware geometry (50863/50864), StageIndex keys, the stage-0
  engine-honest zero-mutation gate (`Chain`: whole-branch live terrain
  survey + independent join test-mode validation), docstring/root-cause
  statement.
- `app/simulation/openttd/proof/corridor_extension_native.py` — 30-tile
  `PINNED_WITNESS`, branch-pin arithmetic, schedule/policy/preflight index
  and literal updates (run 50096..50864 run_len 4; station 50863/50864).
- `tests/test_corridor_extension.py` — SCHEDULE/WITNESS/EXT_STOP/
  EXT_FRONT pins, VM stubs (sloped corner model coverage), pre-mutation
  gate tests, op-surface prohibition test.
- `tests/test_corridor_extension_native.py` — PINNED_SCHEDULE,
  `build_attempt`/site/route fixture updates to the new pins, route-tile
  count, budget pin drift tests re-anchored on `branch_stop`.
- This design record (new file). Nothing else; the frozen wire contract
  (`corridor_construction.py`) is untouched; the consumed/frozen modules
  (`corridor_freight_native.py`, `corridor_accept_survey_native.py`) are
  untouched by this task.

## 7. Report and next authorized step

The work is complete at the implementation/review level described above;
the full transcript step summary (final test counts, regression summary and
the independent fresh-context review verdict) is recorded in the chat reply
pairing this document; the corridor extension itself stays **NOT VERIFIED**.

**Next step (exactly one): stage a fresh native D5 corridor-extension
candidate — and nothing else — against the D4 candidate-5 after-save, so
that a later, separately authorized launch can never reuse any consumed
identity (D5-FREIGHT-1, D5-ACCEPT-SURVEY-1, D5-CORRIDOR-EXTENSION-1).**

Fresh authorization requirements for any subsequent Launch attempt (this
record authorizes none of them):

1. a new explicit operator authorization for a new candidate identity
   (never D5-CORRIDOR-EXTENSION-1 or any other consumed attempt id);
2. prelaunch staging that re-verifies the prerequisite (D4 candidate-5
   after-save digest and its freight/acceptance prerequisite bindings), the
   train of this workflow's F1/F2 remediations and the 30-tile/29-pair
   witness pins natively;
3. read-only acceptance confirmation that the live D4-after world's
   acceptance at the pinned stop tile meets the survey's own instrument
   (the prereq acceptance is its own separate survey session record);
4. the launch Gate/claim chain run exactly as landed in the working tree.
