# Random World native observation pipeline — Seed 17 readiness record

Recorded 2026-10-17 against the live `devmodule2` working tree. This record reports
**offline implementation and controlled validation only**: no OpenTTD launch, no
AdminPort connection and no consumption of any launch authorization occurred while
preparing it. It complements [random-world-distance-support.md](random-world-distance-support.md)
(the capture-area correction) and [random-world-demo.md](random-world-demo.md)
(CLI/interfaces). Anything below marked UNKNOWN cannot be determined offline.

## Status

`SEED17 OBSERVATION IMPLEMENTATION READY FOR NATIVE VALIDATION` (offline sense).

The terrain, catchment and engine observation pipeline exists, is complete and
passes focused controlled validation in this working tree. It has **never**
collected real Seed 17 planning facts: the consumed smoke
(`playable-demo-b84b9bd854a342f1a86e4ba669d8e450`, terminal FAILED, P05 NOT_RUN)
stopped before any planning tile, engine-list or engine-detail read. A native
validation is blocked solely by the separate reviewed frozen-inputs / one-shot
authorization requirement, not by missing implementation.

### Missing-observation root cause

The consumed run used the legacy `(dx+4)*(dy+4) <= 256` rectangular capture-area
gate, failed by all six Seed 17 relationships (`CAPTURE_REGION_BOUND`), so the
planning-read phase was never reached. The `random-rectangle-512-v1` correction
(512 completely observed tiles per rectangle) is implemented offline and was never
consumed natively; its coal pair admission (450 tiles ≤ 512) is therefore an
admission-for-observation only, not a feasibility result. IDs/coordinates come
from retained evidence; code does not hardcode them.

## Verified limits vs current code

| Limit | Where enforced |
|---|---|
| Random capture 512 completely observed tiles/profile `random-rectangle-512-v1` | `MAX_RANDOM_TILES=512` (`supplemental_planning_facts.py`); `RandomCaptureRegion` (≤512, exact-tile completeness validator); `DemoBudgets.capture_tile_limit: Literal[256,512]` (`demo_random.py`) |
| Fixed-demo capture 256 tiles; legacy identity preserved | `Region.tile_limit=MAX_TILES=256`; `DemoBudgets.from_sealed` re-pins 256 for old packets; fixed staging bytes unchanged |
| ≤546 reads/relationship (512 tiles + settings + engines list + ≤32 engine details), 45 s deadline | `capture_planning_facts` request budget `tile_limit+34` and `asyncio.timeout_at` deadline (`freight_runtime_planning.py`); `capture_seconds=45` |
| Global staged read guard 8769 = `(512+36)×16+1` | `DemoBudgets.supplemental_request_limit`; staged bridge `planner_requests>=…` seam (`demo_random_native.stage_random`) |
| Replies ≤512 bytes; 19 ints per tile reply | `PlanningReadback.parse_for` (512-byte + exact data shape; tile=19); GameScript `planner.nut` tile branch |
| Native corridor 2..47 road tiles, excluded before P05 | `freight_planning.ServicePath` (2..47), `network_from_facts` `NATIVE_CORRIDOR_BOUND`, bridge `PLANNER_TOPOLOGY_REJECTED (tiles.len()>47)` |
| ≤8 services/vehicles, ≤16 candidate relationships | `DemoBudgets` bounds; `MAX_SERVICE_PACKAGES=16` (`p08_network.py`); `compile_freight_network` 1..8 routes |
| Industry observation ceiling 32 | `MAX_INDUSTRY_RECORDS=32` (`industry_inventory.py`); structural phase ceilings (`structural_world.py`) |
| One full-capacity vehicle per service | `compile_freight_network` rejects `group.count != 1` / capacity mismatch (`freight_planning.py`) |

## Pipeline stages and ownership

1. **Native acquisition** — qualified structural/production observations (32-cap
   phases) plus per-relationship `settings/engines/engine/tile/generation` reads
   over the AdminPort↔GameScript bridge (`freight_runtime_planning.py`,
   `freight_delivery_package/planner.nut`, staged by `demo_random_native.py`).
   Retained requests/responses are replayable (`replay_network_capture`).
2. **Completeness/validation** — `SupplementalPlanningFacts` contract (exact
   region tile coverage, no duplicates, declared cargo-coverage completeness,
   source/world identity `require_world`, economy-month capture bracket),
   `NativeSaveCorrespondence`/`PreparedSourceCorrespondence`.
3. **Candidate generation** (`p08_adapter` → `p08_road`): flat-vacant-only BFS
   corridor, native-coverage station sites (`MISSING_CATCHMENT` /
   `NO_STATION_PLACEMENT` explicit), depot placement, engine compatibility
   (`INVALID_ENGINE_COMPATIBILITY`), 2..47 pre-P05 filter, bounded search
   (`SEARCH_LIMIT_EXCEEDED`, 4096-expansion cap). Industry-center Manhattan
   distance only ranks; native coverage membership decides.
4. **Optimization** — `p08_network.generate_freight_network` (≤16 packages, one
   qualified month/world) → bounded P05 via `optimize_bounded` (subprocess, hard
   wall-clock bound) → `validate_execution_plan`.
5. **Execution** — existing compiled service/network path (funding, staged orders,
   independent readback) unchanged; candidates from admitted native facts only.
6. **Operational reporting** — P07/replay/monitoring unchanged; failed planning
   writes `planning-diagnostic.json`/`.html` with world identity, industries, cargo,
   relationship counts, capture/candidate rejections, read accounting and limits;
   delivery/financial metrics stay `null`/UNKNOWN until native receipts.

## Seed 17 native observation inventory

Facts the next authorized run must observe in-session for the coal pair
(source industry 0 at (183,173), destination industry 1 at (172,199), cargo COAL;
IDs from retained evidence, not hardcoded). Every item has an explicit failure
mode if absent or inconsistent:

1. **World identity** — `revision=15.3`, seed 17, 256×256, generation readback
   (landscape, `terrain_type=0`, `number_towns=1`, `industry_density=2`);
   configuration/runtime/bridge digests; welcome identity.
2. **Qualified structure** — ≤32 industries (10 expected), cargo catalog
   (11 expected freight/temperate set), capabilities (produces/accepts) with
   industry/cargo identity; exact produced-pair production coverage plus the
   qualified economy month (calendar brackets, stability).
3. **Capture settings read** — truck-stop coverage radius (3 or 4, mutually
   bound to `station.modified_catchment`), `serve_neutral_industries`,
   `economy.timekeeping_units=0` (calendar economy), road speed and
   road/truck-stop/depot costs.
4. **Engine facts** — native road-engine list + per-engine details (engine id,
   default cargo == COAL, road type 0, capacity, purchase price, running cost,
   max speed). UNKNOWN: which engines exist in 1950/temperate Seed 17.
5. **450 tile reads** — for every tile of the clipped padded rectangle: tile id
   vs `y*map_width+x`, min height, slope, 11 vacancy/transport booleans, native
   industry sentinel, per-tile COAL production (`producer_count`) and acceptance
   (`acceptance_eighths`), and industry-specific pickup/delivery coverage.
6. **Funding/budget context** — company funds vs required construction/purchase
   CAPEX (amount UNKNOWN until reads), planning policy budget, batch limits.
7. **Provenance** — post-qualification native save digest, retained per-request
   request/response bytes (replay), capture economy-bracket dates within the
   final qualified month, facts digests binding all of the above.

Absence or contradiction of any item fails closed (explicit codes); none may be
reconstructed from industry coordinates, failure saves or synthetic fixtures.

## Native smoke readiness assessment

- Ready (offline-verifiable): recipes/preflight/staged bridge correspondence,
  capture admission, replay, diagnostics, cleanup path; focused suites green.
- Preconditions for any native attempt: fresh frozen inputs, independent
  preflight v1 PASS (`app/demo_smoke_preflight.py`), separately granted one-shot
  launch authority; the consumed identity is never retried or relabeled.
- Granular statuses for the run: qualification → capture per relationship →
  P08 candidate generation → P05 selection → construction/admission → delivery
  → P07 replay. Any earlier failure yields diagnostics, not delivery receipts.
- Explicit non-prediction: the coal pair may still be infeasible (terrain,
  catchment, engine, corridor >47 tiles, budget); a valid unsupported-world
  outcome is distinct from success.

## Fresh controlled validation in this record

- Focused suite (`test_demo_random`, `test_demo_random_native`,
  `test_random_distance`, `test_random_capture_schema`,
  `test_random_capture_budgets`, `test_demo_operations`,
  `test_demo_smoke_preflight`, `test_openttd_demo`): **90 passed** (includes two
  new guard tests: staging seam-drift refusal, failed-qualification diagnostic).
- Additional compatibility suite (`test_p08_controlled_road`,
  `test_p08_controlled_e2e`, `test_planning_preparation`,
  `test_supplemental_planning_contracts`, `test_paired_source`,
  `test_native_save_path`, `test_freight_offline_recovery`): **297 passed**.
- Terrain/facts acquisition suites (`test_terrain_*`, `test_tile_facts_protocol`):
  **216 passed, 11 skipped** (native-machine prerequisites).
- `ruff check` and `ruff format --check` PASS on the pipeline modules;
  `git diff --check` PASS. No configured typecheck command exists in this
  environment (no mypy/pyright installed); all touched Python compiles via
  `compileall`. RESULTS ARE SCOPED; whole-tree counts beyond these commands are
  not claimed.

## Independent review and resolution

An independent OpenCode subagent reviewed the pipeline (same scope as this
record) and concluded **"OBSERVATION PIPELINE DEFECT-FREE within reviewed
scope"** — no blocking defects; arithmetic/budget/pagination/anti-fabrication
checks (exact-fit 546-read budget, coverage completeness, tile-id identity,
frozen-bridge engine projection binding) were independently re-verified, and no
Seed-17 forcing or hardcoded IDs were found. Resolution of its non-blocking
findings:

- Fixed: staged-seam drift detection (`STAGING_SEAM_DRIFT` counts the anchorless
  64→256 seam replacements per file in `stage_random`, both legacy and explicit
  profile, with frozen legacy staging bytes unchanged) — review finding 2.
- Fixed: the fabricated `generation_seed=42` fallback in
  `capture_planning_facts` now requires the observed runtime identity file —
  finding 4.
- Fixed: capture-admission rejection reasons now use the stable code prefix
  (`CAPTURE_TILE_BUDGET`/`CAPTURE_MAP_BOUND`/…) instead of whole exception text
  in `bounded_relationships` — finding 6.
- Fixed: a qualification-phase failure on the random path now still writes a
  minimal FAILED `planning-diagnostic.json/.html` — finding 12.
- Fixed: offline receipt verification re-checks observed
  `supplemental_requests` against the sealed budget — finding 11.
- Clarified: `MAX_COVERAGE` comment now states both profile ceilings — finding 8.
- Accepted unchanged (latent/frozen-correspondence/contractual): dead legacy
  64-map bounds in the unreachable staged `infrastructure.nut` handler and dead
  legacy offset helpers (findings 1, 3); Python-authored engine booleans bound
  by `Compatible()` filtering and the digest-frozen bridge (finding 5);
  relationship-budget saturation labeled `CANDIDATE_SEARCH_LIMIT` (finding 7);
  informational `padded_capture_tiles` estimate (finding 10).

## Remaining limitations

- No native Seed 17 terrain/catchment/engine facts exist; the controlled flat
  450-tile fixture (31-road-tile candidate, £830 construction + £1,000 vehicle
  = £1,830 estimated) proves the pipeline contract only, never native feasibility.
- Flat vacant land only: no clearing, bridges, tunnels, slopes, or routes over
  occupied/unequal-height terrain; candidates outside the one admitted rectangle
  and 2..47-tile native range are rejected by design.
- One vehicle per service; serial delivery batches; single relationship capture
  context per rectangle; ≤32 industries; 256×256 worlds only.
- Full OPEX, net profit and ROI remain UNKNOWN; revenue is timing-dependent;
  cargo backlog is a point sample, not demand.
- A native smoke still requires the separately reviewed frozen-input identity and
  explicit one-shot authorization described above.
