# D5-CORRIDOR-EXTENSION-1 — Terrain-Aware Construction Design, Implementation Record

Date: 2026-10-30. Status: implementation complete and independently reviewed (PASS);
**no OpenTTD launch, no construction, no claim, no authorization.** The consumed
`D5-TERRAIN-SURVEY-1` identity is never reused; any construction attempt needs a
fresh candidate directory and a fresh operator authorization.

## 1. Survey evidence of record (verified)

Source: `artifacts/experiments/d5-terrain-survey-native-candidate-1/result.json`
(read-only; `CLAIM.json` shows `consumed: true`, 1 launch, 0 retries).

- Plan digest `be3be5570181f16948cb60c090ca831861eb244856d191156eb14de6e48a5324`;
  seal `ee0f21af5c8360476fd004c32ac4a3841eb070a457280fc2c735100cc1a88751`;
  radius 3; funds 492149 at survey start; `SURVEY_OBSERVED` receipts per tile;
  world binding `a81ac836…ef261` (D4 candidate-5 after-save).
- Receipted live facts: 50095 road (owner 0, buildable false); 50096 and 50352
  live slope 12 (N|E raised, min 1/max 2); 50608 live slope 8; 50863 and 50864
  live flat height 1; acceptance 50351 = 0, 50863 = 8.
- All facts fail-closed-read by `terrain_survey_facts()` in
  `app/simulation/openttd/proof/corridor_extension_native.py` and bound into
  `extension_staging_pins()` as `terrain_survey`; preflight re-derives the pins,
  so any survey drift refuses staging before launch can be contemplated.

## 2. Road/slope semantics (OpenTTD 15.3, native facts)

- Slope encoding (W=1, S=2, E=4, N=8; steep = 0x10). `CheckRoadSlopeAnalysis` in
  `road_cmd.cpp` (tag 15.3) prices the natural straight road over escarpment
  ramps with `PR_BUILD_FOUNDATION` under the `build_on_slopes` game setting
  (default ON; not changeable from a GameScript).
- Therefore the surveyed run tiles 50096/50352 (slope 12) and 50608 (slope 8)
  are NOT admission refusals for a straight south road; their native verdict is
  the test-mode quote of the single `GSRoad.BuildRoadFull(50096, 50864)`
  command (one command covers the whole run, so its price covers all three
  ramps' foundation charges).
- The stop tile 50863 and its front 50864 must be live-flat: a nonzero stop or
  front slope refuses at stage 0 with the tile's own observation
  (`STOP_TILE_SLOPED` / `FRONT_TILE_SLOPED`), exactly the fact class that sank
  the halted predecessor attempt at stop tile 50607 (live slope 9).

## 3. Pre-admission (native test-mode) facts

- EVERY road op is quoted pre-mutation by native `GSTestMode` in
  `app/simulation/openttd/d5_extension_package/main.nut`:
  1. Stage-0 `Chain()` first previews the WHOLE run
     `BuildRoadFull(50096, 50864)` on the live unbuilt run ground (reasons
     `full_QUOTE_REFUSED` / `full_ZERO_COST` / `full_COST_LIMIT` /
     `full_INSUFFICIENT_FUNDS`), then previews the join
     `BuildRoad(50095, 50096)` (the deployment front must already be company
     road; nothing is simulated built first — no multi-command chains in test
     mode, per the engine-honest rule that test mode never simulates a
     preceding construction).
  2. The station op is NOT stage-0-provable: `STATION_NEW`'s entrance needs the
     real built front road, so its quote happens at its own staged exchange
     after both road ops — the gate is necessary, never sufficient.
- Quote-derived expected costs (stub-native per-op prices, VM-tested, not
  invented): full run 454, join 71, station 307; total 832 of the pinned path;
  per-op ceiling 2000; funds pin 492149.

## 4. Final corridor op sequence (pinned)

Witness (30 tiles) = built D4 corridor (45748…50351), retraced delivery front
50095, run 50096/50352/50608/50864, standing on new stop 50863.

| op | command | tiles | native quote |
|----|---------|-------|--------------|
| 0 | `GSRoad.BuildRoadFull` | 50096→50864 (run_len 4) | 454 |
| 1 | `GSRoad.BuildRoad` | 50095–50096 | 71 |
| 2 | `GSRoad.BuildRoadStation` (truck, `STATION_NEW`) | 50863 front 50864 | 307 |
| 3 | route read (pure observation, 29 pairs) | — | 0 |

Station-merge discipline: a readback `sid` of 0 or 1 is a FAIL-CLOSED station-
merge defect; the sid dataset is pinned from the built corridor's route-read
evidence. No vehicle, order, or cargo operation exists anywhere in the handler
(whitelist + shipped-text test pin this).

## 5. Can all known fatal road preconditions be checked pre-mutation?

Yes for the ROAD ops: geometry (straight bounded axis), occupancy (zero-mutation
observation — any road/ownership on a run tile refuses `BRANCH_NOT_VACANT`),
the delivery-front road premise, the native legality of every sloped run tile
(price includes foundation charges), zero-cost/over-ceiling/insufficient-funds
refusals — all before any mutation, and the station's slope/occupancy facts are
also surveyed at stage 0. NO for the station's actual buildability: the stop
needs the built front road, so the station op keeps a capacity for native
surprise bounded after two road ops (that residual, and the final acceptance
recheck on the attempt's own after-save, stay with the separate read-only
survey session instrument).

## 6. Test results

- `tests/test_corridor_extension.py` — 32 passed (VM: seeded survey slopes, run
  quote READY at cost 20, gate slope/occupancy/join/ceiling/funds refusals,
  station merge/orientation/occupied-endpoint, budget/request-cap, route
  read/replay, vehicle/order/cargo surface exclusion).
- `tests/test_corridor_extension_native.py` — 67 passed (staging pins incl.
  `terrain_survey`, preflight drift refusals incl. survey-pin drift, replay
  fail-closed paths, execution arm, funds/station-merge/route gates).
- Corridor suites: terrain survey 149 passed + 1 skipped, construction 104,
  freight native 55, accept-survey 50 — all green.
- `ruff check` clean, `ruff format` applied, `py_compile` OK, `git diff --check`
  clean.
- Fresh-context independent review (general subagent, no prior conversation):
  **PASS**, all seven constraints confirmed; 3 nit findings — the quoted-twice
  full-run at stage 0 (second quote re-latched by the command path's
  equal-re-quote gate, safe), raw `JSONDecodeError` (fixed: now refuses as
  `ExtensionStagingError`), and the road-tile flag bar (fixed: `tree` is now
  always checked). No blockers, no majors.

## 7. Next step (explicit, NOT auto-executed)

A FRESH candidate directory (never `d5-terrain-survey-native-candidate-1` nor
any other consumed identity), staged via
`prepare_extension_candidate()` + `extension_preflight()` from the pinned D4
candidate-5 prerequisite, then ONE fresh operator authorization, then a single
launch executing the pinned three-op schedule. Implementation readiness is
proven offline as above; construction verification remains an in-world verdict
pending that launch. Offline rule stands: nothing launched, nothing committed,
no evidence mutated.

Pre-existing unrelated full-suite flake: 3 order-dependent failures in
`tests/test_industry_inventory_proof.py` (module untouched by this task; passes
in isolation — baseline issue, out of scope).
