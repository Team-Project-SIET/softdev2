# Random-world distance support

The distance extension admits larger completely observed rectangles in random
mode without changing P05 or the fixed demo. It does not add arbitrary-terrain
routing or increase the native executor's 47-road-tile limit.

## Seed 17 admission failure

The consumed run `playable-demo-b84b9bd854a342f1a86e4ba669d8e450` remains FAILED.
Its independent qualified-world replay confirms ten industries and eleven cargo
types. Discovery examined 60 source/cargo/destination combinations without search
truncation and found these compatible positive-supply relationships:

| Source→destination | Cargo | Origin | Destination | Manhattan distance | Padded rectangle area | New 512-tile capture |
|---|---|---|---|---:|---:|---|
| 0→1 | COAL | (183,173) | (172,199) |37|450|Admitted for observation |
| 3→2 | WOOD | (219,23) | (221,206) |185|1122|CAPTURE_TILE_BUDGET |
| 7→5 | LVST | (166,21) | (33,148) |260|17947|CAPTURE_TILE_BUDGET |
| 7→5 | GRAI | (166,21) | (33,148) |260|17947|CAPTURE_TILE_BUDGET |
| 8→4 | OIL_ | (182,97) | (75,25) |179|8436|CAPTURE_TILE_BUDGET |
| 9→6 | IORE | (133,33) | (168,92) |94|2457|CAPTURE_TILE_BUDGET |

Every relationship originally failed `CAPTURE_REGION_BOUND`. The old check was
`(abs(origin.x-destination.x)+4) * (abs(origin.y-destination.y)+4) <= 256`, plus
interior-map bounds. Thus even the 37-tile pair failed: the limit was rectangle
area, not route length or Manhattan distance. These IDs and coordinates come from
retained evidence; application discovery and routing do not hardcode them.

## Bounded coverage and construction gates

`discover_relationships` now separates compatibility from capture admission.
`bounded_relationships` applies the same capture admission during live planning
and independent replay. New preparations seal `capture_tile_limit=512` and
`capture_seconds=45`; the explicit `random-rectangle-512-v1` fact profile requires
complete tile and declared cargo-coverage observations over that rectangle.
Padding clips to the map interior. Missing tiles/scopes, wrong identities,
invalid brackets, stale months and unsupported profiles fail explicitly.

Each relationship permits at most 546 reads: 512 tiles, settings, an engine list,
and at most 32 engine details. The global staged request guard remains finite:
`(capture_tile_limit+36)*max_relationships+1`, or 8769 reads for 16 relationships.
Individual replies remain bounded to 512 bytes; tile replies retain 19 integers.
There is no whole-map scan, packet batching or silent observation truncation.
The qualified-month and total native-runtime deadlines remain enforced. At most
512 tile records and 1024 coverage records are admitted per relationship; engine
records remain capped at 32 and P08's aggregate path-expansion cap remains 4096.

The fixed profile retains its 256-tile region serialization and package bytes.
Old sealed random budgets without the new limit field retain 256-tile admission
and their original staged request guard. New code cannot reuse consumed frozen
source hashes or transfer a consumed authorization.

P08 uses its existing vacant-flat-land station/depot/corridor search. Trees,
water, occupied terrain, slopes and disconnected captured corridors are rejected;
clearing, bridges, tunnels, slopes and feasibility outside the bounded slice are
unsupported. Random candidates outside the native 2..47-road-tile range are
excluded before P05. Native test/admission, owned construction, orders and
independent readback remain mandatory before execution can be called verified.

## Controlled results and native evidence gap

One of Seed 17's six pairs now passes capture admission. This establishes only
that its 450 required tile reads fit the new bound. The consumed run contains zero
planning tile, engine-list or engine-detail reads; it stopped before those reads.
Actual terrain, vacancy, catchment, engine compatibility and costs remain missing.
No actual Seed 17 P08 scenario, P05 selection, construction cost or delivery result
can be derived from its industry coordinates or failure save alone in this task.

A separate explicitly synthetic flat 450-tile rectangle, catchment and 30-unit
engine tests the existing P08/P05 pipeline using retained structure. It produces
one valid 31-road-tile candidate and one selected service. Estimated construction
is GBP 830 and vehicle purchase GBP 1000, totaling GBP 1830. These are controlled
fixture estimates, not measured Seed 17 costs. The controlled source cannot acquire
native authority. Exact scenario/plan identities and full inputs are retained in
[the offline analysis](../artifacts/demos/random-distance-seed17-offline-20261017/controlled-pipeline-result.json).

The 450-tile capture test exercises 453 bounded exchanges, exact tile/scope
completeness, retained replay, and tampered-request rejection. Other tests cover
260-tile-Manhattan discovery with explicit capture rejection, map edges, discovery
budgets, unsupported terrain, disconnected routes, native path rejection, timeout
accounting, sealed budgets and legacy staging correspondence.

## Planning diagnostics and P07

Every completed random planning attempt publishes `planning-diagnostic.json` and
`planning-diagnostic.html`, including failed attempts after qualification. The
terminal prints the same status/counts. Diagnostics retain world identity, seed,
industries/cargo types, compatible pairs, capture/candidate rejections, attempted
and complete capture reads, candidate/selection counts and limitations. Missing
results remain null. They do not create delivery metrics, revenue or profit.
Live operational monitoring and the existing P07 replay/charts/history path remain
unchanged; P07 still requires a completed native service receipt.

## Verification and next native run

Focused regression suite: 149 tests PASS. Additional compatibility suite: 135 tests
PASS, with overlap, covering existing P08 roads, freight compilation, fixed-world
preparation and prelaunch gates. Ruff, format checks and typecheck pass. Independent
Codex review passed 28 new tests and reviewed the corrected runtime/replay paths.
No native launches or Admin connections were made for this extension.

Code coverage is ready for a new reviewed smoke preparation. Actual Seed 17
P08/P05 validation remains blocked by missing native terrain/catchment/engine
facts. A future native smoke needs fresh frozen inputs, independent preflight and
separate one-shot authorization. The consumed smoke is never retried or relabeled.
