# OpenTTD transport planning and playable freight demo

Python selects freight services, builds them through OpenTTD 15.3's GameScript
bridge, and verifies deliveries from native readbacks. P08 generates bounded road
candidates; P05 uses OR-Tools CP-SAT to select services; P07 compares the plan with
retained observations. Python communicates over one encrypted Admin connection.
The graphical client joins a dedicated local server as a spectator.

## Quick start

Use Linux amd64, a graphical desktop, Python 3.14 or newer, and uv. Install the
project dependencies with `uv sync --locked`. PostgreSQL and Docker are not needed
for this demo. Install the pinned OpenTTD 15.3 distribution and OpenGFX 8.0 archive,
then set the two runtime paths as described in the [demo guide](examples/openttd-demo/README.md).
From the repository root:

```bash
.venv/bin/python -m app.openttd_demo check
.venv/bin/python -m app.openttd_demo --view-seconds 300
```

**VERIFIED native MVP:** one server, one graphical spectator, one encrypted Admin
connection; services 4→5, 2→3, 0→1; vehicles 4/5/6; 20 coal delivered per service,
60 total and £1,022 revenue. Graphical joining and inspection, fresh P07 reporting,
cleanup, and artifact integrity passed in the retained demo. These are short,
serial delivery batches. Revenue can vary with timing; it is not profit.

**Controlled/offline:** `python -m app.openttd_demo plan` selects services from the
bundled deterministic scenario without launching OpenTTD. P07 replays retained
native observations. Controlled tests do not establish additional native behavior.

See the [demo guide](examples/openttd-demo/README.md) for installation, spectator
controls, results, troubleshooting, and limits. Full OPEX and ROI remain UNKNOWN.
Arbitrary-world planning and larger networks are not verified MVP capabilities.

## Random World & Scalable Logistics

An opt-in bounded 256×256 native random generator and dynamic P08/P05 planning,
terminal monitoring and P07 charts/history/comparisons are implemented locally.
Seed 17 verified native generation, discovery and spectator inspection, but its
smoke remains FAILED: no services constructed/delivered and P05 did not run.
The new 512-tile rectangular capture correction is controlled/offline only;
actual Seed 17 route feasibility awaits fresh native facts and authorization.
Its Tile Classification V2 census completed natively on 2026-10-18 (90/90
pages, 450/450 tiles, schema-2 AdminPort, staged AI + GameScript startup,
cleanup PASS), but the SOURCE_SAVE_FUSION correspondence verdict is REJECTED:
83 projected-flag disagreements, nothing fused, the 19 historically UNKNOWN
tiles stay UNKNOWN and the P08 diagnosis stays `INCOMPLETE_TILE_CLASSIFICATION`.
Fixed Scenario remains the stable default. See [random-world documentation](docs/random-world-demo.md),
[distance support](docs/random-world-distance-support.md),
[the V2 completion record](docs/p08-classification-v2-native-capture-completion.md) and the
[vendor-neutral AI handoff](AI_HANDOFF.md) for current dirty-worktree scope.

## Research reference and historical milestones

The sections below retain research workflows and historical evidence. Their dated
limitations describe those milestones; the current public demo scope is above.

Python plans transport services and verifies their execution in **OpenTTD 15.3**.
The native multi-service MVP selected and delivered two coal services in one world
in Attempt 12: **20 + 20 coal, £682 revenue and £19,101 CAPEX**. Independent
retained receipt replay verifies both services and their aggregate. Services ran
serially; concurrency, paid shared-asset reuse and full OPEX remain unproven.

On 2026-10-11, freight Attempt 4 delivered **20 units of coal**. Offline replay
verified £341 delivery income, £304 vehicle-profit increase and £9,358 construction
and purchase spending. The plan-bound receipt is in
`artifacts/runtime/openttd-15.3-first-freight-delivery-attempt4/receipt.json`.
These historical launches were consumed. Another execution requires
its own authorization; inspecting the existing receipt does not launch OpenTTD.

On 2026-10-13, planner-driven Attempt 9 delivered **20 coal units** to the selected
power station after an economy-quarter rollover. Fresh same-session qualification,
P08/P05 selection, native construction, loaded arrival, industry-attributed delivery
and payment passed. Offline replay reproduced the complete plan-bound
[Attempt 9 receipt](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt9/receipt.json).
Delivery income was £325, vehicle profit increased £289, and construction plus
purchase cost £9,586. One launch and one encrypted session were consumed, without
retry or reconnection. The process was reaped, listeners closed, credentials removed
and the disposable workspace deleted. Attempts 1–8 remain unchanged.

The standalone freight MVP is checkpointed in commit `92388cb`. Planner-driven freight,
Attempt 9 monitoring and offline replay are checkpointed in `93986e0`. Native multi-service freight is checkpointed in `16345fa`. P07 offline
planned-vs-actual reporting, charts and deterministic feedback are available.
Runtime artifacts are ignored by Git and have not been pushed.
Historical runtime evidence is optional for a **new `--demo` run**.

## What works, and what remains incomplete

| Capability | Current evidence |
| --- | --- |
| Secure AdminPort, industry/cargo observation and native qualification | Native milestones; qualification Attempt 2's overall post-run acceptance remains FAILED |
| Road, stops, depot, purchase, orders and movement | Native readbacks |
| Freight loading, final industry delivery and payment | Attempt 4, 20 units, verified receipt and cleanup |
| WorldPlanningObservation → P08 → P05 → ExecutionPlan | Controlled verification and native Attempt 9 |
| P05 output → checked single-vehicle freight intent | Controlled compiler and native Attempt 9 |
| Qualified observation → P08 → native delivery | Attempt 9, 20 coal units, attributed payment, plan-bound offline replay and cleanup |
| P07 post-play evaluation, run history and charts | Offline replay of Attempts 4 and 9; native plan comparison for Attempt 9; failed Attempt 8 excluded from delivery averages |
| Multiple candidate services, shared-constrained P05 selection and network P07 estimates | Attempt 12: two native P05-selected services delivered in one world; paid shared-asset reuse remains unproven |
| Evidence-aware P07 performance analytics (bottlenecks, advisories, comparisons) | Offline implementation verified 2026-10-18 on retained Attempt 19/fixed-demo evidence; see [the analytics record](docs/p07-performance-analytics-extension.md); no native relabeling of FAILED terminals |
| Tile classification census capture (schema-2 AdminPort) | Native 2026-10-18: 90/90 pages, 450/450 tiles with AI/GameScript startup and cleanup PASS; correspondence verdict REJECTED (83 disagreements), nothing fused — see [the completion record](docs/p08-classification-v2-native-capture-completion.md) |
| Arbitrary maps, rail delivery, concurrent native vehicles, closed-loop optimization | Outside the demonstrated native MVP |

The standalone `--demo` result uses native OD selection. `--demo --planner` instead
qualifies that generated world, captures the missing planning facts, runs P08/P05,
and admits the selected service. Controlled planning inputs cannot authorize native
execution. Attempt 4 proves standalone delivery; Attempt 9 proves planner-driven delivery.

## Architecture

```text
Planning path, verified in native Attempt 9
WorldPlanningObservation + supplemental facts + prepared-source correspondence
  → P08 bounded road candidates → P05 CP-SAT → ExecutionPlan
  → checked freight intent → same-session native-source correspondence gate

Working native demonstration
Python CLI → isolated OpenTTD 15.3 + company + bridge GameScript
  → encrypted authorized-key AdminPort → bounded native admission
  → native construction / vehicle / orders → loading / arrival / unloading
  → industry cargo monitors + company income + vehicle profit
  → Python receipt replay + saved states + complete cleanup
  → P07 offline comparison → SQLAlchemy history → CSV / JSON / HTML charts
```

Python owns planning, immutable identities, deadlines and verification. GameScript
performs native queries and synchronous commands in company mode. P05 optimizes
supplied candidates; OpenTTD's vehicle pathfinder navigates the built road.
See [CONTEXT.md](CONTEXT.md) and [freight proof details](docs/first-freight-delivery-proof.md).

## Requirements and Fedora/Linux setup

The supported demo platform is Linux x86-64 with the pinned generic-amd64 OpenTTD
15.3 distribution and OpenGFX 8.0. Python **3.14+** is required; this work used 3.14.6.
Python dependencies include Pydantic, pymonocypher, OR-Tools, SQLAlchemy, Alembic,
psycopg and OpenTTDLab. Development checks use pytest, Ruff and squirrel-lang.
The standalone freight demo needs **neither PostgreSQL nor Docker**.

Install basic tools on Fedora and install [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
sudo dnf install git curl tar xz
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
```

From the project root:

```bash
uv python install 3.14
uv sync --locked --group dev
```

The lockfile and dev group are required for the controlled GameScript tests.

## Install the pinned OpenTTD assets

Keep the **whole extracted distribution**, including `lib`, `lang` and other
asset directories. Installing a different system OpenTTD package does not satisfy
the executable checksum gate.

```bash
mkdir -p artifacts/tools artifacts/runtime/verified-assets
curl --fail --location \
  https://cdn.openttd.org/openttd-releases/15.3/openttd-15.3-linux-generic-amd64.tar.xz \
  -o artifacts/tools/openttd-15.3-linux-generic-amd64.tar.xz
printf '%s  %s\n' \
  f49eb25d61b00f8f4d332fee02b530ad75552d1efb8f2bb01e7ca5e6540fe059 \
  artifacts/tools/openttd-15.3-linux-generic-amd64.tar.xz | sha256sum --check
tar -xJf artifacts/tools/openttd-15.3-linux-generic-amd64.tar.xz -C artifacts/tools
curl --fail --location \
  https://cdn.openttd.org/opengfx-releases/8.0/opengfx-8.0-all.zip \
  -o artifacts/runtime/verified-assets/opengfx-8.0-all.zip
export OPENTTD_BINARY="$PWD/artifacts/tools/openttd-15.3-linux-generic-amd64/openttd"
export OPENTTD_OPENGFX_ARCHIVE="$PWD/artifacts/runtime/verified-assets/opengfx-8.0-all.zip"
printf '%s  %s\n' \
  276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c \
  "$OPENTTD_BINARY" | sha256sum --check
printf '%s  %s\n' \
  43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be \
  "$OPENTTD_OPENGFX_ARCHIVE" | sha256sum --check
```

These checksums identify the locally verified official distributions. Preparation
also validates the graphics descriptor and native GRF checksums.

## Configuration

| Variable | Use |
| --- | --- |
| `OPENTTD_BINARY` | Freight demo executable path; bytes must match the pinned 15.3 binary |
| `OPENTTD_OPENGFX_ARCHIVE` | OpenGFX 8.0 ZIP path; defaults to `artifacts/runtime/verified-assets/opengfx-8.0-all.zip` |
| `UV_CACHE_DIR`, `UV_TOOL_DIR` | Optional writable uv cache/tool directories |
| `DATABASE_URL`, `APP_ENV`, `SQL_ECHO` | Optional database-backed experiment configuration; not needed by the freight demo |

Without `OPENTTD_BINARY`, the historical local default is
`/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd`; set the variable on
another machine. Export the two asset variables in the shell; the proof CLI does
not load them from `.env`.

The CLI generates isolated OpenTTD configuration, loopback game/Admin ports,
OpenGFX staging, the GameScript and company AI, and an ephemeral authorized key
with mode 0600. Insecure Admin login is disabled. It does not use your normal
OpenTTD profile. No manual game setup or permanent Admin password is needed.

## Complete freight usage example

Run controlled checks first:

```bash
uv run --no-sync pytest -q tests/test_freight_delivery.py tests/test_freight_planning.py
```

Choose a new attempt, generate its immutable preparation, and validate it:

```bash
FREIGHT_ATTEMPT="$(uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery next)"
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery \
  prepare "$FREIGHT_ATTEMPT" --demo
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery \
  preflight "$FREIGHT_ATTEMPT"
```

Expected output is `PRELAUNCH PASS`, then `PREFLIGHT PASS`. These commands create
no OpenTTD process or Admin connection. Preparation stages a 64×64 flat heightmap;
**the next command** creates the native world and its industries.

When authorized for one native launch:

```bash
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery \
  run "$FREIGHT_ATTEMPT" --authorize-one-launch
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery \
  verify "$FREIGHT_ATTEMPT"
```

The native demo uses seed 42, default temperate content, a real coal mine and power
station, and native clearing of its bounded construction footprint. It leaves
production, cargo allocation and payment to OpenTTD. The company buys one compatible
truck and receives source full-load and destination no-load orders.

A successful run prints:

```json
{"connections":1,"launches":1,"mutations":10,"preflight":"PASS","requests":26,"status":"NATIVE_DELIVERY_VERIFIED"}
```

`verify` returns the replayed receipt as JSON and exits zero only when frame
correlation, construction accounting, loading, arrival, unloading, both industry
monitors, payment, saves and cleanup all agree. Attempt 4's verified values were
`loaded=20`, `delivered=20`, `pickup_monitor=20`, `payment_income=341` and
`vehicle_profit_delta=304`. Dates and costs are observations, not hard-coded success
values. A future invocation is a fresh attempt, not a replay of Attempt 4.

Do not edit source files or configuration between preparation and run. A consumed
attempt cannot be run again. Diagnose a failure before preparing another attempt;
`next` does not authorize execution or implement an automatic retry loop.

## Inspect results and receipts

To verify the existing successful local evidence without launching the game:

```bash
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery \
  verify artifacts/runtime/openttd-15.3-first-freight-delivery-attempt4
```

For a new run, inspect these files under `$FREIGHT_ATTEMPT`:

| File | Meaning |
| --- | --- |
| `PRELAUNCH.json`, `PRELAUNCH.sha256`, `frozen-source.zip` | Immutable runtime/input/policy/source provenance |
| `CLAIM.json` | One-launch attempt consumed before starting |
| `inspect-1-response.json`, `plan.json` | Native admission and plan identity |
| `build-*-response.json`, `read-*-response.json` | Command results and independent state reads |
| `observe-*-response.json`, `finish-1-response.json` | Physical cargo and native monitor/payment evidence |
| `receipt.json` | Verified delivery, attribution, costs and digests; success only |
| `result.json`, `cleanup.json` | Overall result and process/socket/credential/workspace cleanup |
| `before.sav`, `after.sav`, `failure.sav` | Native saves, according to outcome |
| `frames.json`, `stdout.log`, `stderr.log`, `artifact-manifest.sha256` | Retained exchanges, logs and file integrity |

The disposable runtime is removed after cleanup; the evidence stays. These artifacts
are ignored by Git. Back them up before removing an attempt directory.

### Read-only evidence TUI

An optional Textual console renders retained runs and P07 reports without launching
OpenTTD or opening an Admin connection:

```bash
uv sync --group tui
uv run --group tui python -m app.tui --root artifacts/demos
```

It shows summary/finance readback, service rows, planned-versus-actual metrics,
retained charts and the evidence file list. Missing values remain `UNKNOWN`; the UI
never substitutes zero, estimates OPEX/ROI, or writes into evidence. See
[docs/tui.md](docs/tui.md) for screens, keys and limits.

## Planning integration boundary

`app/planning/p08_adapter.py` and `p08_road.py` consume admitted observation,
supplemental facts and source correspondence. P05's `optimize_candidate_network`
produces the existing `ExecutionPlan`; it does not choose terrain outside supplied
candidates. `app/simulation/openttd/freight_planning.py` compiles its selected
single-vehicle road service into a checked freight intent, retaining industry,
cargo, engine and plan identities. It never drops additional vehicles to fit the demo.

`--planner` reuses the existing two-rollover qualification coordinator on the freight
runner's one encrypted connection. It captures at most 256 tiles, both cargo coverage
scopes, compatible engines, road costs and native settings. These facts are bound to
the same qualified `WorldPlanningObservation`. An owned native save after qualification
becomes the prepared source. Process, connection, configuration, save-completion and
final-month checks establish correspondence. This workflow captures a generated
world; it does not claim to load an arbitrary prepared save.

P08 generates candidates and P05 produces `ExecutionPlan`. The compiler passes the
selected identities, corridor and depot front to native admission, which validates
that selection before the existing construction, vehicle, order and delivery stages.
No second OD search substitutes another service.

`--batch-limit 20` is an explicit planning policy that caps the demonstration at 20
qualified supply units without changing observed production. The one-load assumption,
planning calendar and cost estimates remain planning assumptions. Native capacity,
command quotes, funds, loading, delivery and payment are checked separately. Execution
supports one vehicle starting immediately, a planned batch equal to its native
full-load capacity, 2..47 flat corridor road tiles, two stops and one depot.
Partial loads and larger fleets are rejected. Attempt 9 verified this planner workflow
natively with fresh production observations. Historical observations never supply
fresh planning inputs.

Pre-planning collection retains its coherent economy-month and same-run qualification
checks. Post-execution monitoring permits one economy-quarter transition within the
same year. Each readback retains raw current-quarter counters; a separate period
record stores the first observed transition tick, economy date, closed quarter,
completed-quarter cargo and income. Receipt replay sums these explicit periods against
the original financial baseline, without treating them as one atomic snapshot.

The finite per-phase budget is `min(4440, 2048 + 128 * route_tiles)` script ticks,
where `route_tiles` includes the station approaches. Attempt 8 traversed 18 tiles in
1,064 transit ticks and retained all 20 coal units at speed 45 when its quarter guard
stopped observation. The new allowance includes departure and loading slack and
more than twice that observed travel time per tile. The entire observation lifecycle
must finish within 60 economy days. Each response has a 135-second deadline; the
planner run has a 600-second ceiling. Pause, clock failure, invalid vehicle or orders,
cargo loss in transit, destination loss, 2,048 ticks without movement and timeout fail
closed. Loaded arrival, actual unloading, industry monitors and payment remain required.
Year rollover remains excluded because vehicle profit resets annually.

Prepare and validate the next planner proof without launching OpenTTD:

```bash
PLANNER_ATTEMPT="$(uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery next)"
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery prepare "$PLANNER_ATTEMPT" --demo --planner --batch-limit 20
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery preflight "$PLANNER_ATTEMPT"
```

Expected output is `PRELAUNCH PASS`, then `PREFLIGHT PASS`. No `CLAIM.json` is created.
Once a separate launch is authorized, execute once and verify the retained result:

```bash
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery run "$PLANNER_ATTEMPT" --authorize-one-launch
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery verify "$PLANNER_ATTEMPT"
```

Run uses the sealed planner mode and batch cap. Inspect `world-planning-observation.json`,
`supplemental-planning-facts.json`, `planning-policy.json`, `planning-scenario.json`,
`execution-plan.json`, `planning-binding.json` and `qualified.sav`. A successful
`receipt.json` contains the execution-plan digest and native selection binding.
Offline verification replays qualification receipts with their exact log prefixes,
reconstructs supplemental facts, reruns P08/P05 and checks the delivery receipt.
Verification never launches or connects to OpenTTD and preserves retained evidence.

Native fact calls use the tagged OpenTTD 15.3
[engine API](https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/script/api/script_engine.hpp)
and [road API](https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/script/api/script_road.hpp).

Verify the existing controlled pipeline and the new boundary:

```bash
uv run --no-sync pytest -q tests/test_p08_controlled_e2e.py tests/test_freight_planning.py
```

## Troubleshooting

- **Pinned executable/assets mismatch:** check the exported paths and SHA-256 values.
  Keep the distribution's bundled files together; do not substitute a system binary.
- **`NO_NATIVE_FEASIBLE_OD`:** inspect `result.json` and the inspection response.
  Versioned failure counters distinguish absent pairs from rejected pairs and report
  the first rejecting gate. Attempt 2 rejected all layouts on topology/footprint;
  `--demo` supplies genuine flat terrain without weakening those checks.
- **`quote` rejection or failed purchase:** read the native response. Vehicle purchase
  is tested only after the owned depot exists; initial admission reserves the native
  engine price. Funds and native command cost checks still apply.
- **Frozen source changed:** the prepared attempt is stale. Do not rewrite its seal.
  Restore the exact prepared source or discard only that unconsumed preparation and
  create a fresh attempt under the applicable authorization policy.
- **Window exhaustion or readback mismatch:** this is a failed/inconclusive attempt,
  not proof of delivery or path blockage. Inspect the retained phase response and save.
- **Script died:** read `stderr.log`. Runtime script errors are reported separately
  from actual cleanup failures. For the historical Attempt 3, disposal recovery was
  recorded separately; its original failure record remains unchanged.
- **Port/process ownership failure:** another matching runtime or live endpoint blocks
  preflight. Stop only a process you own; never bypass the ownership gate.
- **uv cannot write its cache:** export writable paths such as
  `UV_CACHE_DIR=/tmp/softdev2-uv-cache` and `UV_TOOL_DIR=/tmp/softdev2-uv-tools`.

## Development checks and repository layout

```bash
uv run --no-sync pytest -q tests/test_freight_delivery.py tests/test_freight_planning.py
uv run --no-sync ruff check app/simulation/openttd/freight_delivery.py \
  app/simulation/openttd/freight_planning.py app/simulation/openttd/proof/freight_delivery.py \
  tests/test_freight_delivery.py tests/test_freight_planning.py
uv run --no-sync ruff format --check app/simulation/openttd/freight_delivery.py \
  app/simulation/openttd/freight_planning.py app/simulation/openttd/proof/freight_delivery.py \
  tests/test_freight_delivery.py tests/test_freight_planning.py
uvx ty check app/simulation/openttd/freight_delivery.py \
  app/simulation/openttd/freight_planning.py app/simulation/openttd/proof/freight_delivery.py \
  tests/test_freight_delivery.py tests/test_freight_planning.py
```

Default tests do not launch OpenTTD. Real integration tests are opt-in; they are
separate from running this explicitly authorized proof CLI.

```text
app/planning/                         typed contracts, P08 candidates, P05 optimizer
app/simulation/openttd/                transport, observation and delivery verification
app/simulation/openttd/freight_delivery_package/ native freight GameScript
app/simulation/openttd/proof/           isolated preparation, launch and receipt replay
app/experiments/                       historical batch/live experiment CLI and persistence
tests/                                controlled verification and opt-in native tests
artifacts/runtime/                    ignored native evidence and verified assets
docs/                                 contracts, proof reports and limitations
```

## Optional historical experiments and PostgreSQL

The separate `transport-experiment` CLI retains the historical OpenTTDLab/OpenTTD
13.4 external-AI experiment path. It is not the native 15.3 freight demonstration.
For that database-backed path, configure `.env` with `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_PORT`, `DATABASE_URL`, `APP_ENV=development` and
`SQL_ECHO=false`. Match the PostgreSQL URL to the Compose credentials.

```bash
docker compose up -d postgres
docker compose ps
uv run alembic upgrade head
uv run transport-experiment --help
```

Wait for PostgreSQL to be healthy before migrating. Migration history is retained;
no database schema retirement is part of this MVP. See [the proof CLI guide](docs/openttd-15.3-proof-cli.md)
for other 15.3 observation modes and their separate authorization rules.

## P07 post-play analytics

Analyze retained results without an OpenTTD launch, Admin connection, PostgreSQL
server or additional plotting dependency:

```bash
uv run --no-sync python -m app.experiments.cli analyze-freight \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt4 \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt8 \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt9 \
  --history artifacts/experiments/freight-history.sqlite \
  --output artifacts/experiments/p07-freight
```

The evidence-aware insights extension (2026-10-18) adds the offline subcommand
`analyze-performance-insights SOURCE --output DIR [--compare DIR ...]`: declared
metrics carrying OBSERVED/DERIVED/HYPOTHESIS/UNKNOWN status per metric,
deterministic bottleneck hypotheses, advisory recommendation rows (advisory
only — they never plan, purchase or execute), matched-world run comparisons and
bounded SVG charts; see [the analytics record](docs/p07-performance-analytics-extension.md).
It reads retained evidence read-only and keeps FAILED native terminals visible.

The installed `transport-experiment analyze-freight` command accepts the same
arguments. Open `artifacts/experiments/p07-freight/charts.html` in a browser. The
self-contained report has planned-versus-actual charts, revenue and spending,
delivered cargo, measured load fill, and descriptive history within comparable cohorts.
`summary.json` includes provenance, metric scopes, findings and per-cohort descriptive
statistics. `metrics.csv` has one row per metric; empty numeric fields mean unknown.
Example output reports `successful_deliveries: 2`, `failed_attempts: 1`, `cohorts: 2`.

| Attempt | Service mode | Delivered | Revenue | Infrastructure CAPEX | Purchase | Vehicle profit delta |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | Standalone | 20 coal units | £341 | £4,929 | £4,429 | £304 |
| 8 | Planner-driven, failed | Unknown | Unknown | Unknown | Unknown | Unknown |
| 9 | Planner-driven | 20 coal units | £325 | £5,157 | £4,429 | £289 |

Attempt 9 planned and delivered the same 20-unit batch, two stations, one depot,
one vehicle and a connected 24-tile corridor. Planned total CAPEX was £8,583;
actual service construction and purchase spending was £9,586. Infrastructure alone
was estimated at £4,154 versus £5,157 actual. Its £1,003 forecast error consists of
£588 for roads including entrance bits, £385 for stations and £30 for the depot.
Reconcile these estimates with retained native command quotes before another plan.
P08/P05 are unchanged by this evaluation.

Measured load fill was 100%, with 48 cargo units still waiting at source after
Attempt 9's delivery. Measure repeat-trip frequency and queue growth before buying
more vehicles. Retained timestamps include source dwell and travel, and do not
prove a detour or inefficient routing. Planned cargo is an explicit batch policy,
not a production forecast or a measured cargo-per-day forecast.

Delivery revenue and vehicle profit are separate, overlapping measures. The £36
difference in Attempt 9 is a revenue-minus-displayed-profit residual, **not** an
itemized operating-cost ledger. Full operating costs and net return are unknown.
The native API exposes [displayed vehicle profit](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_vehicle.cpp#L339-L344),
while [delivery accounting](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/economy.cpp#L1091-L1129)
distinguishes company revenue and vehicle shares. Sparse phase snapshots measure
load fill but cannot measure the fraction of time a vehicle moved or idled. No
full planning-horizon performance, recurring profitability, asset residual value
or capital payback forecast is claimed. CAPEX excludes preparation of the demo world.

Each successful import must pass the existing offline receipt verifier, including
plan binding, native cargo/payment evidence and cleanup. Attempt 4 uses its sealed
historical receipt format. Failed attempts retain their failure reason and unknown
delivery metrics. Modified or unverified packages are rejected before storage.
No historical artifacts are rewritten. Source receipt, manifest and result digests,
native/P05 plan digests, source paths and comparison definitions remain in history.

The local SQLite history uses the project's SQLAlchemy models and portable JSON
storage conventions. Migration `0009` adds the equivalent table to a managed
project database; the offline command creates only its own SQLite table. Reimporting
the same evaluation does not duplicate it. Conflicting provenance or changed stored
content is rejected. Downgrade refuses to discard retained history.

Comparisons require matching service mode, simulator/content, bridge semantics,
world/geometry, native supply and engine facts, planning policy and observed window.
Attempts 4 and 9 differ and have separate cohorts. Failed attempts never enter
successful-delivery averages. History charts show separate points and never infer
a trend from the retained attempts. More comparable measurements and a justified
sampling design are needed before drawing performance conclusions.

Focused offline checks:

```bash
uv run --no-sync pytest -q tests/test_freight_analytics.py tests/test_plan_evaluation.py
```

## Controlled multi-service optimization

Run the saved three-candidate scenario without starting OpenTTD:

```bash
uv run --no-sync python -m app.planning.network_cli \
  tests/fixtures/multi_service/scenario.json \
  --output artifacts/experiments/multi-service
```

The scenario comes from a qualified controlled observation and three bounded P08
OD fact packages. P05 selects two 40-unit services using four vehicles. Estimated
CAPEX is £2,580: £580 infrastructure and £2,000 vehicle purchases. Reducing shared
producer supply, vehicle availability, depot capacity or budget changes the selection.
An unavailable optional service is excluded while feasible services remain selectable.

`generate_freight_network(inputs, max_vehicles=..., resource_limits=...)` combines
up to 16 adapter-issued packages from one source, qualified month and policy. Each
package uses the existing bounded road generator. Conflicting shared facts and
duplicate OD packages are rejected. The `NetworkSelection` contract binds shared
supply and resource limits into the scenario digest; legacy single-service digests
and default minimum-CAPEX behavior remain unchanged.

The existing CP-SAT solver maximizes historical batch cargo, then minimizes CAPEX.
It builds a standard multi-route `ExecutionPlan`. Exact infrastructure candidates
are charged once across services. Partially overlapping corridors and incompatible
facility orientations remain conflicts; incremental road-bit reuse is unsupported.
Per-service resource declarations prevent borrowing an unqualified depot or corridor.
The historical supply limit is not a production forecast or measured acceptor capacity.

The output contains `execution-plan.json`, `estimates.json` and `evaluation.json`.
P07 reports selected services, unique network construction CAPEX and fleet purchases.
`evaluate_freight_network(plan, scenario, service_directories)` verifies retained
receipts before accepting service actuals and requires exact plan/scenario attribution.
Verified service-batch subtotals exclude failed and unattributed evidence. Independent
windows cannot establish concurrent network performance, and company income cannot
be assigned to concurrent services. Revenue, vehicle profit, CAPEX and unknown OPEX
remain separate; unknown expenses never become zero or a claimed net return.

The checkpointed native proof establishes two serial services. The multi-service path
reuses the service executor with serial execution in one session, independent vehicles and
orders, and stops each vehicle empty after delivery. A controlled multi-route plan
is **not native execution ready**. Existing single-service commands still work.

Focused verification:

```bash
uv run --no-sync pytest -q tests/test_freight_network.py tests/test_planning_optimizer.py
uv run --no-sync pytest -q tests/test_freight_history_postgres.py --run-postgres
```

PostgreSQL history persistence was verified using migrated isolated test schemas,
including readback, idempotency and conflicting-provenance rejection. SQLite remains
the default offline history backend. `FreightHistory.from_engine(engine)` supports an
already migrated SQLAlchemy/PostgreSQL database without changing its public schema.

## Native multi-service preparation

Attempt 10 used fresh-world preparation for two producer/acceptor pairs. The intended
pipeline qualifies that world, captures bounded native facts, runs P08/P05, preserves
both selected identities, admits aggregate native quotes against observed funds, and
sequences the existing freight construction/loading/delivery/payment checks. Unique
construction actions form the CAPEX ledger; repeated shared actions must spend zero.
Only the active service vehicle runs during its payment window. This establishes
serial service attribution, not concurrent network throughput. OPEX and net profit
remain unknown unless measured.

Preparation and preflight passed. The **single consumed launch failed** with
`NETWORK_INDUSTRY_BUILD_FAILED` during the second layout (`y=44`), before readiness,
Admin connection, qualification or P05 selection. No native services were selected;
no service construction, delivery, revenue or CAPEX was verified. The first native
industry pair was built before failure. Offline retained-save inspection found
exactly those two industries, one town, and `economy.multiple_industry_per_town=0`.
The third call, coal mine type 0 at tile 2836 `(20,44)`, violates the same-type,
same-town rule in [OpenTTD 15.3](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/industry_cmd.cpp).
That rule rejects the call before footprint and terrain checks. Total world
preparation mutations remain unmeasured.
Do not rerun this attempt or treat zero service requests as zero world mutations.

The immutable attempt directory retains `PRELAUNCH.json`, `CLAIM.json`, frozen
sources, logs, `failure.sav`, result, cleanup and artifact hashes. Independent retained
readback verified the manifest, one launch/zero connections, process reaping, closed
endpoints, credential removal and workspace disposal. Historical evidence was
preserved. No success receipts or native network P07 results exist for Attempt 10.

`verify_network_receipt(directory)` replays qualified observations, native facts,
P08/P05 selection, per-command spending, logged ownership/topology, each service's
cargo/payment and stopped-vehicle readback, and unique aggregate accounting for a
completed package. P07 accepts such a package through
`evaluate_freight_network(..., native_network_directory=directory)`; independent
historical runs cannot satisfy that input. These additions are checkpointed in `16345fa`. Attempt 12 proved native receipt replay and P07 network
actuals for two serial services, as recorded below.

### Attempt 12: verified native two-service execution

On 2026-10-14, one OpenTTD 15.3 launch and one continuous secure Admin connection
constructed and independently read back two coal mines and two power stations
(industry IDs 0–3). The sealed launch config contained exactly one `[economy]`
section; the running GameScript checked `economy.multiple_industry_per_town=1`
before construction. Same-world qualification and P08/P05 selected exactly two
services; native selection bindings, vehicles, orders, loading, final delivery and
payment were replayed from retained evidence.

| Service (native industry IDs) | Delivered coal | Actual revenue (GBP) | Construction and vehicle CAPEX (GBP) |
| --- | ---: | ---: | ---: |
| 2 → 3 | 20 | 356 | 9,515 |
| 0 → 1 | 20 | 326 | 9,586 |
| Aggregate | 40 | 682 | 19,101 |

The unique infrastructure ledger totals £10,243; vehicle purchases total £8,858.
P05 selected no shared construction actions, so shared CAPEX is £0. This attempt
proves aggregate accounting without duplication; paid shared-asset reuse remains
unproven. Services ran serially, with each vehicle stopped empty after delivery;
concurrent throughput, OPEX and net return remain unmeasured.

[Attempt 12 receipts](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt12/receipt.json)
passed independent offline replay. The
[P07 evaluation](artifacts/experiments/attempt12-native-network/evaluation.json)
records two verified services and their attributed actuals. Cleanup verified process
reaping, closed connection/listeners, credential removal and workspace disposal.
Attempts 1–11 remain preserved. The multi-service implementation is checkpointed in `16345fa`;
ignored native evidence stays local.

Focused verification passed (96 tests), plus Ruff, format and scoped typecheck:

```bash
uv run --no-sync pytest -q tests/test_native_freight_network.py \
  tests/test_freight_network.py tests/test_freight_planning.py \
  tests/test_freight_delivery.py tests/test_freight_analytics.py
```

Network preparation now explicitly sets `economy.multiple_industry_per_town=true`
and checks the setting before construction. The anchors and seed remain unchanged.
Each build checks the native outcome, industry count, type, and location. A failed
build stops preparation; the one-shot runner retains evidence and disposes the
workspace. Network preflight rejects retained saves in the disposable workspace
and checks both heightmap copies against the sealed source identity.

Attempts 10 and 11 are consumed failures. Use the fresh-attempt preparation
workflow below; never reuse their mutated saves.

## Known limits

Attempt 12 demonstrates one company and two independent coal producer/acceptor
pairs with two trucks, serial payment windows, bay stops, depots and bounded flat
road corridors using default content. One process and one continuous secure
connection were consumed without retries or reconnections. Its sealed budgets
permit 58 requests, 768-byte service responses and a 900-second total deadline;
world preparation is bounded separately in `PRELAUNCH.json`.

The proof covers each service's first paid batch. Long-run profitability, recurring
reliability, arbitrary-world route search, concurrent throughput and paid shared
asset reuse remain unproven. Full operating expenses and net return are unknown.
Amounts are OpenTTD GBP accounting units. Receipts fail closed; neither a command
ACK nor an empty vehicle alone can establish freight delivery.

## Reproducible multi-service replay and feedback

After `uv sync --locked --group dev`, the following commands run offline. They do
not need PostgreSQL, Docker, OpenTTD installation or Admin credentials. Native
replay requires the retained Attempt 12 package, which is ignored by Git; a fresh
clone can use the checked-in controlled scenario shown above, but cannot claim
native proof without the retained package.

```bash
ATTEMPT=artifacts/runtime/openttd-15.3-first-freight-delivery-attempt12
uv run --no-sync python -m app.planning.network_cli \
  "$ATTEMPT/planning-scenario.json" --native-network-directory "$ATTEMPT" \
  --output artifacts/experiments/attempt12-replay
uv run --no-sync python -m app.experiments.cli analyze-freight \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt4 \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt8 \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt9 \
  "$ATTEMPT" --history artifacts/experiments/multi-service-history.sqlite \
  --output artifacts/experiments/multi-service-feedback
```

Network replay uses the retained selected plan rather than re-running selection.
Inspect `attempt12-replay/evaluation.json` for each service and the unique network
ledger. Open `multi-service-feedback/charts.html` for planned/actual batches,
CAPEX components, attributed service revenue and measured capacity. The same folder
contains `summary.json`, `metrics.csv`, `network-reports.json` and `feedback.json`.
Feedback references retained evidence and its hashes. Repeating the commands
preserves content-addressed history without adding duplicate runs. Keep generated
output and history outside every retained evidence directory.

Estimated infrastructure CAPEX is compared with native command spending; vehicle
purchases are separate. Company revenue and displayed vehicle profit overlap and
must not be added. Full OPEX, net return, moving/idle utilization and capital
recovery remain unknown. Batch/capacity ratios describe observed batches, not
recurring throughput. Failure packages retain unknown metrics; standalone,
planner-driven and serial-network runs use separate cohorts. History provides
descriptive comparisons and never infers trends from one or two runs.

Recommendations identify cost quote discrepancies and which further measurements
P08/P05 need. They do not retrain anything or change optimizer parameters. Attempt
12 selected no shared construction actions; a zero shared ledger does not prove
paid reuse. Future native execution requires fresh authorization and a new attempt.

### Compare optional feedback-informed planning scenarios

P05 can use one verified P07 network history entry to compare controlled cost
assumptions. Without feedback flags, the existing optimizer behavior is unchanged.
Use the history generated above and the receipt hash as the selected history key:

```bash
FEEDBACK_RUN="$(sha256sum "$ATTEMPT/receipt.json" | cut -d ' ' -f 1)"
uv run --no-sync python -m app.planning.network_cli \
  tests/fixtures/multi_service/scenario.json \
  --feedback-history artifacts/experiments/multi-service-history.sqlite \
  --feedback-run "$FEEDBACK_RUN" \
  --output artifacts/experiments/feedback-replanning
```

Open `feedback-replanning/charts.html` for the P07 history with its planning
comparison. `planning-comparison.json` retains each full scenario and plan, their
digests, the selected history key, and native receipt references with hashes.
The ordinary `execution-plan.json`, `estimates.json`, and `evaluation.json` still
describe the baseline. If the baseline is infeasible, the CLI writes the comparison
and charts without these three baseline files; use a fresh output directory.

Verified example with the checked-in scenario and retained Attempt 12 feedback:

| Cost assumption | Selected services | Expected CAPEX (GBP) | Fleet capacity | Planned batch | Controlled feasible |
| --- | --- | ---: | ---: | ---: | --- |
| Baseline | `benchmark-2-1-17`, `benchmark-2-1-30` | 2,580.00 | 120 | 80 | Yes |
| Observed error | Same two services | 2,715.14 | 120 | 80 | Yes |
| Double error | Same two services | 2,850.24 | 120 | 80 | Yes |

All three remain within the identical £4,000 budget. JSON also reports whether
the baseline selection remains within budget under each alternative assumption.

The comparison replays retained evidence before using the selected history entry.
Baseline and alternatives use the same supplied P08 candidates, budget, fleet
capacity, and qualified supply. Only candidate infrastructure estimates change.
P05 still maximizes the selected historical cargo batch, then minimizes estimated
CAPEX. Vehicle purchases and revenue assumptions remain unchanged.

The alternatives apply the observed positive aggregate infrastructure error ratio
uniformly, then twice that ratio. Attempt 12 underestimated infrastructure by
£1,935 against an £8,308 estimate. Applying that ratio to another scenario is an
explicit transfer assumption. One observation provides no statistically calibrated
prediction or candidate-specific correction. Each adjusted candidate cost rounds
upward to pennies.

Waiting cargo of 54 and 42 units remains observed station backlog. It does not
increase planned supply, measured demand, or guaranteed future revenue. Comparisons
do not establish native feasibility or demonstrated optimization improvement.
Full OPEX, ROI, and profitability remain unknown. No parameters change automatically,
and no retraining or native execution occurs.

To prepare a fresh multi-service attempt without launching it:

```bash
NEXT_ATTEMPT="$(uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery next)"
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery \
  prepare "$NEXT_ATTEMPT" --demo --planner --network
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery \
  preflight "$NEXT_ATTEMPT"
```

Preparation and preflight grant no launch permission. Never reuse consumed Attempt
10, 11 or 12 run commands. Focused offline checks:

```bash
uv run --no-sync pytest -q tests/test_planning_feedback.py \
  tests/test_freight_analytics.py tests/test_freight_network.py
```

### Matched Baseline versus Feedback-aware experiment

Replay the same verified Attempt 12 initial world, observation, P08 candidates,
budget and constraints under both policies. The feedback policy applies the
explicit observed aggregate infrastructure-cost error assumption. Use the retained verified history
and a fresh output directory:

```bash
ATTEMPT=artifacts/runtime/openttd-15.3-first-freight-delivery-attempt12
FEEDBACK_RUN="$(sha256sum "$ATTEMPT/receipt.json" | cut -d ' ' -f 1)"
uv run --no-sync python -m app.experiments.feedback_experiment "$ATTEMPT" \
  --feedback-history artifacts/experiments/multi-service-mvp-feedback-2026-10-14/history.sqlite \
  --feedback-run "$FEEDBACK_RUN" \
  --output artifacts/experiments/matched-feedback-replay
uv run --no-sync pytest -q tests/test_feedback_experiment.py \
  tests/test_feedback_comparison.py
```

`planning-manifest.json` records matched input hashes, source-save provenance,
assumptions, both policy results and the launch decision. Separate scenario and
plan files permit reproducible replay. `comparison.json` and `charts.html` provide
P07 planned metrics, estimation errors and unknown actuals; historical verified
receipts and actual metrics appear only as a separate reference.

The verified replay selects identical execution decisions, so it launches neither
variant. Different cost estimates and plan digests do not imply different services,
fleet or construction. No paired delivery, revenue or economic improvement is
measured. The historical reference is not an outcome of either fresh variant.
OPEX, net return, ROI and unmeasured time utilization remain unknown.

If execution decisions differ, the command reports a blocker: the existing native
network policy does not permit cloned retained saves. It does not launch or reuse
a mutated world. A future native comparison requires both independently validated
preflights and supported separate clones of the verified initial source.

For exhaustive **controlled** budget sensitivity over the same supplied P08/P05
candidates and baseline, observed-error and double-error policies:

```bash
uv run --no-sync python -m app.experiments.feedback_experiment "$ATTEMPT" \
  --feedback-history artifacts/experiments/multi-service-mvp-feedback-2026-10-14/history.sqlite \
  --feedback-run "$FEEDBACK_RUN" \
  --output artifacts/experiments/feedback-budget-sensitivity --sensitivity
uv run --no-sync pytest -q tests/test_feedback_sensitivity.py
```

This verified offline command adds `sensitivity` to `planning-manifest.json` and
P07 `comparison.json`, plus budget charts and exact breakpoints in `charts.html`.
It tests all eligible alternative combinations, including omitted services, under
unchanged nonbudget constraints; enumeration above 100,000 combinations per
policy fails explicitly. Exact Decimal affordability thresholds and intervening
intervals are tested, including the original £100,000 budget. Shared candidate
infrastructure is charged once. Each selected plan passes independent validation.
Interval metrics describe the inclusive lower bound; budget slack rises inside
each interval. Rows compare services, candidates, CAPEX, per-load fleet capacity, horizon demand,
lexicographic objective values and budget/supply/resource/vehicle/capacity slack.

On retained Attempt 12 inputs, both policies are feasible but choose different
service sets at budgets **£17,166 ≤ budget < £19,101.04** (observed-error), and
**£17,166 ≤ budget < £21,036.06** (double-error). Baseline serves two demands
(40 units); feedback serves one (20 units). One-policy-only feasibility occurs
separately below £9,550.52 and £10,518.03 respectively, starting at baseline's
£8,583 threshold. Above the final threshold every eligible combination is
already affordable, so further budget increases cannot change these decisions.
At the original £100,000 budget selections remain identical.

These are retrospective cost-feedback sensitivity results. Attempt 12 actual
costs informed the uplift; the £19,101.04 revised estimate matching historical
£19,101 is **not independent validation**. No launches or Admin connections occur;
no profitability, native A/B improvement or automatic tuning is established.

The bounded **matched native A/B preparation** workflow clones the verified
`qualified.sav` initial planning state into separate baseline and feedback
workspaces. It copies the archived settings and bridge bytes and verifies source,
seed, content, settings and observation-policy identities offline. It launches no
native process and opens no Admin connection:

```bash
uv run --no-sync python -m app.experiments.paired_native prepare "$ATTEMPT" \
  --feedback-history artifacts/experiments/multi-service-mvp-feedback-2026-10-14/history.sqlite \
  --feedback-run "$FEEDBACK_RUN" --budget 18000 \
  --output artifacts/experiments/paired-native-prepared
uv run --no-sync python -m app.experiments.paired_native validate \
  artifacts/experiments/paired-native-prepared
uv run --no-sync python -m app.experiments.paired_native compare \
  artifacts/experiments/paired-native-prepared \
  --output artifacts/experiments/paired-native-comparison
uv run --no-sync pytest -q tests/test_paired_native.py
```

These commands retain their outputs and return exit code **1** for the verified
`BLOCKED` readiness result. At the interior integer budget **£18,000**, unchanged
P05 optimization selects two baseline services (estimated £17,166) and one
feedback service (estimated £9,550.52). Both plans independently pass existing
finance, infrastructure, supply, fleet and capacity checks and compile against
retained P08 service provenance. Historical baseline CAPEX **£19,101** exceeds the
cap by **£1,101**: that retrospective exposure rejects native readiness, without
claiming a fresh cost measurement or relaxing the cap. Fresh native cost bounds,
company-funds readback and feasibility admission remain unavailable. The existing
launch policy also requires fresh heightmap preparation and cannot execute these
save clones. Offline byte identity does not prove effective runtime reload identity.

`paired-manifest.json` records clone provenance, independent plan validation and
executor bindings. `validate` replays protected inputs and optimizer decisions;
`compare` produces P07 planned metrics with unknown fresh actuals. Attempt 12
remains separate historical feedback. Native receipt ingestion is rejected until
supported cloned-save execution and independent admission exist; no real outcome
improvement is established.

The finite `high-budget-500k` scenario preset initializes company 0 once to
**£500,000 cash**, retains its loan unchanged and keeps infinite money disabled.
The planning spending cap defaults separately to £500,000; `--planning-budget
18000` retains a low planning cap while starting cash stays £500,000. Seed 42 is
unchanged. Funding is an explicit scenario endowment, excluded from delivery
revenue, operating profit and feedback performance metrics. Repeated or resumed
funding is rejected; existing per-service execution safety limits remain in force.

Finance-only native Attempt 13 verified seed 42, cash **£100,000 → £500,000**
with a £400,000 scenario endowment, and loan **£100,000 → £100,000**. Its
retained before/after save hashes and funding provenance passed offline readback
verification. One launch and one connection were used; no freight run occurred.

For the bounded finance-only lifecycle, use a fresh attempt directory:

```bash
FINANCE_ATTEMPT="$(uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery next)"
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery prepare "$FINANCE_ATTEMPT" \
  --demo --planner --network --scenario high-budget-500k --finance-only
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery preflight "$FINANCE_ATTEMPT"
# One separately authorized launch only after independent effective-config review:
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery run "$FINANCE_ATTEMPT" \
  --authorize-one-launch
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery verify "$FINANCE_ATTEMPT"
```

Preparation seals the exact runtime config, preset, planning cap, seed, content,
bridge and source bytes. Finance-only execution performs initialization plus an
independent cash/loan/income/expenses read, saves the funded initial state and
stops before freight planning or construction. `scenario-capital.json` records the
endowment separately; `receipt.json` leaves freight outcomes unknown. The retained
verifier checks secure frames, runtime identity, save hashes and complete cleanup.
A finance-only result does not establish delivery or improved A/B outcomes.

Inspect starting cash, unchanged loan and saved-world provenance with the existing
`verify "$FINANCE_ATTEMPT"` command above. Its finance receipt includes the native
before/after balances and loan; preparation alone does not establish those values.

For P08/P05 planning and native multi-service freight, prepare a separate fresh
attempt without `--finance-only`. Native Attempt 14 executed the full workflow
below after preflight passed, using one launch and one secure connection:

```bash
HIGH_BUDGET_ATTEMPT="$(uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery next)"
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery prepare "$HIGH_BUDGET_ATTEMPT" \
  --demo --planner --network --scenario high-budget-500k --planning-budget 500000
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery preflight "$HIGH_BUDGET_ATTEMPT"
# Run only once with explicit authorization after preflight PASS:
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery run "$HIGH_BUDGET_ATTEMPT" \
  --authorize-one-launch
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery verify "$HIGH_BUDGET_ATTEMPT"
```

`--planner --network` qualifies observations, prepares P08 candidates, solves P05
and executes selected services in the existing workflow. Omitting
`--planning-budget` gives this preset the same £500,000 cap; an explicit positive
integer cap changes planner spending permission independently of company cash.
The seed controls world generation, starting cash controls available company
funds, and the planning budget limits selected plan cost. This financial preset
retains seed 42 and creates separate artifacts; it does not alter verified saves.


Native **Attempt 14** established **HIGH-BUDGET NATIVE FREIGHT EXECUTION PROVEN**.
Implementation checkpoint: `ceaf6ee` (no push). Preparation sealed starting cash
and the planning cap at **£500,000**, with infinite money disabled. Independent
native funding readback verified cash **£100,000 → £500,000**, loan unchanged at
**£100,000**, and exactly one £400,000 endowment. Funding changed neither income
nor expenses and is excluded from freight revenue. Admission cash after the
production qualification window was **£499,616**.

P08/P05 naturally selected two coal services, within the current one-or-two-service
executor limit. No benchmark identities or service count were forced. Native
admission checked industry compatibility, route feasibility and available funds;
the two £9,702 construction/purchase quotes totaled £19,404. Independent command,
route and delivery readbacks established:

| Native service | Delivered coal | Freight revenue | Actual CAPEX |
| --- | ---: | ---: | ---: |
| Industry 2 → 3 | 20 units | £356 | £9,515 |
| Industry 0 → 1 | 20 units | £326 | £9,586 |
| Total | 40 units | £682 | £19,101 |

Actual CAPEX comprises **£10,243 infrastructure** and **£8,858 vehicle purchases**.
Final retained cash readback was **£480,748**. Cash movement also includes the
qualification and running periods; it is not a net-profit calculation. OPEX and
net return remain unknown. Both vehicles stopped empty after delivery. Cleanup
verified process reaping, socket closure, workspace disposal and credential removal.

[Attempt 14 receipts](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt14/receipt.json),
[funding readback](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt14/scenario-capital.json)
and [P07 evaluation](artifacts/experiments/attempt14-high-budget/p07/evaluation.json)
passed independent offline replay. P07 verified both selected services and recorded
planned CAPEX £17,166 versus actual £19,101, a **£1,935** shortfall in the estimate.
Replay and analytics commands executed successfully:

```bash
ATTEMPT=artifacts/runtime/openttd-15.3-first-freight-delivery-attempt14
uv run --no-sync python -m app.planning.network_cli \
  "$ATTEMPT/planning-scenario.json" --native-network-directory "$ATTEMPT" \
  --output artifacts/experiments/attempt14-high-budget/p07
uv run --no-sync python -m app.experiments.cli analyze-freight \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt12 "$ATTEMPT" \
  --history artifacts/experiments/attempt14-high-budget/history.sqlite \
  --output artifacts/experiments/attempt14-high-budget/analytics
```

[Historical comparison](artifacts/experiments/attempt14-high-budget/attempt12-comparison.json)
keeps Attempt 12 separate: its planning cap was £100,000, versus £500,000 for
Attempt 14. Admission funds were £99,616 versus £499,616. Both generated 64×64
seed-42 worlds and selected the same industry/cargo relationships, delivering the
same 40 units for £682 and £19,101 CAPEX. Fresh qualified save hashes and execution
windows differ; this is not a matched native A/B comparison or evidence that the
higher budget improved performance. Receipts prove serial service batches, not
concurrent throughput. Historical evidence was preserved; no optimizer tuning,
retry, reconnect or push occurred. Consumed Attempt 14 must never be launched again.


The larger controlled network uses explicit `--network-service-limit 3`; the
existing default remains **2**. Attempt 14 had only two admitted OD candidates:
`0 → 1` and `2 → 3`; both cross-pair candidates were rejected with
`CAPTURE_REGION_BOUND`. Its `max_vehicles=2`, compiler and bridge also capped
services at two. Cash was not the binding constraint. Larger preparation creates
three separate coal-mine/power-station pairs at rows **8, 26, 44** on the same
64×64 flat map. Each matching capture region is 240 tiles, within the unchanged
256-tile limit. Eligibility still requires fresh production qualification,
catchment, road and funds admission. Three-service construction and delivery
have controlled coverage. Attempt 17 below also proves native delivery.

Offline preparation command verified in this task (choose a fresh directory):

```bash
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery prepare "$FRESH_ATTEMPT" \
  --demo --planner --network --scenario high-budget-500k --planning-budget 500000 \
  --network-service-limit 3
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery preflight "$FRESH_ATTEMPT"
uv run --no-sync pytest -q tests/test_high_budget_network_scaling.py tests/test_game_time.py \
  tests/test_native_freight_network.py tests/test_network_world_preparation.py
```

The three-service seal permits at most 87 execution requests, 33 mutations,
162 preparation mutations and 192 construction commands. Supplemental reads
remain bounded at 1,168; qualification and same-month capture rules are unchanged.
P05 retains its objective and all constraints. The controlled regression selects
three full-capacity services for 90 required units with three vehicles; a
£500,000 budget with a two-vehicle constraint still selects only two. Services
execute serially with independent identities and vehicles. Shared infrastructure
is charged once through the existing unique-asset ledger.

Attempt 14 cash reconciliation is
**£500,000 − £19,101 CAPEX + £682 revenue − £480,748 final cash = £833**
unexplained net outflow. Native admission cash £499,616 establishes **£384**
before admission; the remaining **£449** occurred afterward. These balances
reconcile the arithmetic, but retained evidence lacks an attributable expense
ledger. Neither residual is classified as OPEX; OPEX and net return remain UNKNOWN.

P07 now reports separate service/network game-time fields and charts. Future
network receipts seal `game_time_metrics_version=1` and independently replay
available milestone dates from correlated readbacks and unique native log markers.
Future start dates use the explicit `bridge_start_before_world_preparation`
boundary; elapsed economy days run from that boundary to final delivery. This
does not timestamp process launch or world generation. Construction/purchase
completion is logged after the final successful purchase; planning completion
remains an observed-by bound from selection admission, and exact first pickup
remains UNKNOWN without an event timestamp. Historical receipts remain unchanged. `GSDate.GetCurrentDate()` uses the **economy** counter in the pinned
[OpenTTD 15.3 source](tests/reference/economy_clock_15_3/script_date.cpp).
Calendar days, script ticks and wall-clock seconds are separate nullable metrics;
no conversion from ticks or wall time supplies missing economy dates.

| Attempt 14 network milestone | Retained economy-date evidence |
| --- | --- |
| Simulation start | UNKNOWN |
| Planning completion | UNKNOWN |
| Construction completion | UNKNOWN; all construction observed complete by 712319 |
| First cargo pickup | UNKNOWN; first loaded observation by 712299 |
| Final cargo delivery | 712349, native industry last-accepted date |
| Total elapsed economy days | UNKNOWN; simulation start was not timestamped |

Construction and pickup observation dates are bounds, not event timestamps.
The serial services delivered on economy dates **712319** and **712349**;
service construction was observed complete by **712291** and **712319**, and
loaded cargo by **712299** and **712329**. Dates alone do not establish concurrent
throughput or total simulation duration. No native launch, Admin connection or
push occurred during this scaling work.

### Three-service native Attempt 15: failed, consumed

Scaling checkpoint **`219580c`** passed focused controlled tests and review.
Fresh [Attempt 15](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt15/result.json)
passed preflight and used **one launch, one continuous encrypted Admin connection,
zero retries and zero reconnects**. Native readbacks verified finite **£500,000**
cash, an unchanged £100,000 loan, and all six required industries. Same-world
qualification, P08 and P05 naturally selected **4→5, 2→3, 0→1**, each for 20 coal.

The first road command logged success and **£2,512** spending, then the timing
callback crashed: **`RecordConstruction: the index 'base' does not exist`**.
The runner reported `TimeoutError` while awaiting its response. No vehicle,
cargo loading, delivery or payment was verified. Aggregate CAPEX, infrastructure
reuse, final cash, revenue, OPEX and net return remain **UNKNOWN**. The last
independent pre-mutation cash readback was **£499,616**; it is not final cash.

The bridge start economy date was **712223**. Planning was complete by the
selection/readback economy date **712295** (script tick **5384**); its exact
completion date is UNKNOWN. Construction completion, first pickup, final delivery,
elapsed economy days and service quarter transitions are UNKNOWN. Calendar dates,
script ticks and wall-clock time remain separate; no duration is inferred from them.

Cleanup verified the process reaped, connection/listeners closed, credential
removed and disposable workspace removed. The native manifest, frozen source,
requests, readbacks, logs and failure save are retained. The failure-save helper
reported a script/asset error, so retained bytes do not establish accepted save
completion. **Do not launch consumed Attempt 15 again.**

P07 analytics records this failure and excludes it from successful delivery
statistics. Native network replay rejects the missing first-build response;
there are **no verified service/network receipts** for Attempt 15.
[Failure analysis](artifacts/experiments/attempt15-three-service/failure-analysis.json)
links evidence hashes; [charts](artifacts/experiments/attempt15-three-service/analytics/charts.html)
preserve the verified Attempt 14 results separately.

Commands used for this consumed attempt and its offline analysis:

```bash
ATTEMPT=artifacts/runtime/openttd-15.3-first-freight-delivery-attempt15
# Historical commands only: do not prepare or run this directory again.
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery prepare "$ATTEMPT" \
  --demo --planner --network --scenario high-budget-500k --planning-budget 500000 \
  --network-service-limit 3
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery preflight "$ATTEMPT"
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery run "$ATTEMPT" \
  --authorize-one-launch
# Offline analysis can be repeated into a fresh output directory.
uv run --no-sync python -m app.experiments.cli analyze-freight \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt14 "$ATTEMPT" \
  --history artifacts/experiments/attempt15-three-service/history.sqlite \
  --output artifacts/experiments/attempt15-three-service/analytics
```

The local correction replaces unsupported `base.RecordConstruction(...)` with
`PlannerFreightProof.RecordConstruction.call(this,...)`. Focused offline tests
reproduced the native error before the fix and verify both ancestor construction
logs and timing markers afterward. Independent Codex review passed. The correction
was uncommitted and had no native proof at that point. Attempt 17 below provides
the fresh native proof. No second launch or push occurred during Attempt 15.

### Native three-service freight proven in Attempt 17

[Attempt 17](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt17/result.json)
completed one native OpenTTD 15.3 launch and one secure connection. P08/P05
naturally selected `4 → 5`, `2 → 3`, and `0 → 1`. The existing executor used
87 execution requests and 33 mutations, within the sealed limits.
Independent offline replay verifies loading, delivery, payment, command costs,
owned infrastructure, separate vehicles, receipts, and the complete network ledger.

| Service | Coal delivered | Revenue | Command CAPEX | Construction economy date | Delivery economy date | Days from construction to delivery | Days from bridge start to delivery |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 → 5 | 20 | £340 | £9,358 | 712298 | 712328 | 30 | 105 |
| 2 → 3 | 20 | £352 | £9,515 | 712329 | 712360 | 31 | 137 |
| 0 → 1 | 20 | £326 | £9,586 | 712360 | 712393 | 33 | 170 |
| Network | 60 | £1,018 | £28,459 | 712360 | 712393 | — | 170 |

The bridge start date is 712223, before world preparation. Exact pickup dates,
calendar duration, script-tick duration, and wall-clock duration remain UNKNOWN.
These are serial batches. Paid shared-asset reuse and concurrent throughput remain unproven.

[Financial reconciliation](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt17/financial-reconciliation.json)
separates £15,172 infrastructure CAPEX, £13,287 vehicle purchases, and £1,018 freight revenue.
Funded cash reconciles as **£500,000 − £28,459 + £1,018 − £1,067 = £471,492**.
The £1,067 unallocated decrease includes £384 before admission and £683 afterward.
Expense categories, OPEX, and net return remain UNKNOWN. No construction interval
had an unallocated cash change in Attempt 17.

[Attempt 16 diagnosis](artifacts/experiments/attempt17-three-service/attempt16-diagnosis.json)
proves an accounting defect: aggregate cash movement across ticks was required
to equal command cost. Its second-service stage 4 spent exactly £307 on commands,
while enclosing snapshots showed a £308 cash decrease. The extra £1 remains
UNKNOWN. Command-local quote, accounting, and spending must still match exactly.
The correction records separate cash intervals with snapshot provenance and
requires advancing ticks. Fresh seals require the financial ledger during replay.

[Three service receipts and the network receipt](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt17/receipt.json)
pass independent replay. [P07 network evaluation](artifacts/experiments/attempt17-three-service/analytics/network-reports.json)
records all three verified services and economy-time metrics.
[P07 charts](artifacts/experiments/attempt17-three-service/analytics/charts.html)
preserve unknown OPEX and net return. Focused Codex review, 136 tests, Ruff,
formatting, type checking, and preflight passed.

[Cleanup](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt17/cleanup.json)
reaped the process, closed sockets, removed the credential, and disposed the workspace.
All 8,522 protected files from Attempts 1–16 and `CONTEXT.md` are unchanged.
Attempt 17 is consumed. No retry, second launch, commit, or push occurred.

### Five complete economy years of continuous freight operation

**Attempt 19: FIVE-YEAR EVIDENCE OFFLINE VERIFIED (2026-10-15).**
Full offline replay now verifies the original native evidence plus explicitly
identified derived finalization metadata. **The historical native terminal remains
FAILED.** Recovery performed zero OpenTTD launches or Admin connections and changed
none of Attempt 19's 14,611 original files. Source/staged archive hashes, qualified
world and planner selection, construction/service receipts, fixed vehicles/orders,
secure exchanges, five anniversaries, financial observations, saves, cleanup, and
original artifact integrity pass the existing replay checks.

[Derived finalization](artifacts/experiments/attempt19-offline-recovery/derived-finalization.json)
and [offline verification](artifacts/experiments/attempt19-offline-recovery/verification.json)
have SHA-256 sidecars and bind the original manifest, PRELAUNCH, source archive,
FAILED result, native policy readbacks, and existing before/qualified/after saves.
They reconstruct policy/save correspondence only; no native observations or reload
evidence were recreated. The independently verified observations remain 1,826
economy days, 1,605 snapshots, 60 monthly/20 quarterly/five annual reports, 2,980
cargo, and £50,935 freight revenue, with £28,459 construction/purchase CAPEX.

The apparent £385 cash gap belonged to setup before the operating baseline:
£335 measured aggregate expenses plus £50 unattributed decrease. Setup reconciles
as `500000 - 28459 - 335 - 50 = 471156`; the five-year operating window reconciles
as `471156 + 50935 - 16312 - 1500 = 504279`. The £1,500 operating decrease remains
unattributed. Loan principal stayed £100,000. CAPEX is counted once, outside the
operating window; expense categories, actual vehicle OPEX, net profit, ROI, and
net break-even remain UNKNOWN.

P07 [JSON](artifacts/experiments/p07-attempt19-five-year-offline/summary.json),
[CSV](artifacts/experiments/p07-attempt19-five-year-offline/metrics.csv), and
[HTML charts](artifacts/experiments/p07-attempt19-five-year-offline/charts.html)
retain the offline recovery label, original FAILED status, sampled periods,
financial coverage audit, and native evidence references. Eleven charts use short
service labels with a full route/vehicle legend. Derived metadata and P07 outputs
each have an artifact manifest. Independent review, 101 focused tests (including
write-once finalization, recovery/tampering, and finance-window regressions), Ruff,
format, and scoped typecheck pass. Reproduce analysis:

```bash
.venv/bin/python -m app.experiments.cli analyze-continuous-freight \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19 \
  --recovery-directory artifacts/experiments/attempt19-offline-recovery \
  --output artifacts/experiments/p07-attempt19-five-year-offline
```

#### Five-year performance findings

The [performance analysis](docs/five-year-freight-performance-analysis.md)
compares the services and separates observed constraints from hypotheses.
Service labels follow the existing P07 chart legend, with vehicles 4, 5, and 6.

| Economy year | Service 1 cargo | Service 2 cargo | Service 3 cargo | Network cargo | Network revenue |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 200 | 200 | 180 | 580 | £9,920 |
| 2 | 200 | 200 | 200 | 600 | £10,259 |
| 3 | 200 | 200 | 200 | 600 | £10,258 |
| 4 | 220 | 180 | 200 | 600 | £10,241 |
| 5 | 200 | 200 | 200 | 600 | £10,257 |

Revenue per service remains UNKNOWN in every year. The 60 sampled monthly
intervals cover 2,940 cargo and £50,267; the final 17-day tail adds 40 cargo
and £668. Monthly boundaries are approximate observations, not accrual accounts.

Closing waiting cargo is 305, 572, and 574 units, while each vehicle holds
20 units. This supports testing fleet capacity and dispatch cadence. It does
not establish road congestion, exact travel time, idle duration, or infrastructure
saturation. Speed-zero samples include loading and unloading. Existing eleven
P07 charts remain sufficient; use the offline command above to regenerate them.

Prioritize a controlled comparison of one extra vehicle on Service 2 or 3
against a capacity change, holding routes, orders, and funding constant.
Any later native experiment needs separate authorization and telemetry for
departure, arrival, load, waiting cargo, and incremental costs. No native gains,
profit, or ROI are established. The existing P05 objective and defaults remain
unchanged; one planning trip per vehicle does not model native service frequency.

Compare explicit planning assumptions with the same offline CLI:

```bash
.venv/bin/python -m app.experiments.cli analyze-continuous-freight \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19 \
  --recovery-directory artifacts/experiments/attempt19-offline-recovery \
  --compare-planning --output /tmp/attempt19-performance-comparison
```

`planning-alternatives.json` records validated P08/P05 comparisons alongside
the existing P07 outputs. Raising the fleet limit from three to six leaves the
60-unit planning selection unchanged. Supplying 40 units of demand per service
and allowing six vehicles selects 120 planning units. These are one-trip model
quantities, not forecasts of annual throughput. Hypothetical capacities and
infrastructure cost sensitivity remain explicit assumptions; physical upgrades
need new P08 candidates. See the [controlled comparison](docs/five-year-freight-controlled-alternatives.md).

A recovery-only Git checkpoint was deferred because recovery depends on the
uncommitted five-year foundation. No unrelated changes were staged and nothing
was pushed. Historical Attempt 19 remains FAILED; offline verification passed.
The combined CLI replay and ten validated planning comparisons passed. Independent
review, 51 focused tests, Ruff, formatting, and whitespace checks passed.

#### One additional vehicle: controlled experiment preparation

[A/B/C preparation](docs/capacity-experiment.md) keeps original demand and
services unchanged. Opt-in P05 `minimum_vehicles_by_demand` produces A: 1/1/1,
B: 1/2/1, and C: 1/1/2 vehicles on S1/S2/S3. Routes, infrastructure and original
fleet semantics remain fixed. Default planning behavior and canonical hashes
remain unchanged.

S2 is the first hypothesis to test: its mean monthly sampled queue is 651.42
units versus S3's 557.10, with both delivering 980 units. The extra vehicle's
historical purchase cost is £4,429. Its £421 annual running-cost rate is not
measured OPEX. No throughput gain, per-service revenue, profit or ROI is forecast.

```bash
.venv/bin/python -m app.experiments.cli analyze-continuous-freight \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19 \
  --recovery-directory artifacts/experiments/attempt19-offline-recovery \
  --prepare-capacity-experiment --output /tmp/attempt20-capacity-preparation
```

The existing P07 outputs are accompanied by `capacity-experiment.json`, containing
input hashes, exact A/B/C plans, acceptance criteria and readiness blockers, and
`capacity-comparison.html`, containing one queue comparison chart. Treatment
performance remains UNKNOWN. The command performs offline preparation only.

The opt-in telemetry producer and bounded decoder record point measurements and
bracket possible arrivals, departures and loading events. Candidate cycles remain
censored inferences. Zero speed does not establish idle time, and stopped-in-depot
does not establish servicing time.

Fourth-vehicle execution and independent receipt replay are now controlled-tested
for any selected service. The existing continuous session collects bounded
per-vehicle telemetry, preserving three logical service counters. Additional
purchase CAPEX is recorded once; raw secure exchanges bind the physical vehicle
to its logical service. Partial mutations fail closed.

Native readiness remains **BLOCKED**: no retained canonical pre-intervention save
contains the original constructed fleet, and no verified reload preserves its
GameScript bindings and native state. The future loader must verify a paused
purchase boundary and common dispatch state. See the [exact prerequisite and
tests](docs/capacity-experiment.md). No Attempt 20 native seal, claim, launch or
connection was created. Historical Attempt 19 remains FAILED. No commit or push.
Validation: 180 focused tests, packaged GameScript checks, independent correction
review, historical offline replay, Ruff, formatting and scoped typecheck pass.

**Attempt 19 FAILED (2026-10-15): final policy provenance `FileExistsError`.**
Auto-renew initialization succeeded in company 0: the native setter returned true
and independent readback returned false. Preflight, 193 focused tests, packaged
Squirrel/API checks, Ruff, formatting, typecheck, and historical Attempt 17 replay
passed. One OpenTTD 15.3 process and one encrypted Admin connection observed all
five anniversaries without retry, reconnect, or fleet expansion.

Independent raw-wire/period replay verifies 1,605 snapshots over **1,826 economy
days** (native dates 712299–714125; 3,648.43 monitoring seconds), 60 monthly,
20 quarterly, and five annual observations. Original vehicles 4/5/6 delivered
1,020/980/980 cargo units: **2,980 total**, with **£50,935 aggregate freight revenue**.
Concurrent per-service revenue remains UNKNOWN. Command-recorded CAPEX is £28,459;
measured aggregate expenses are £16,312, and a further £1,500 cash decrease remains
unattributed. Operating-window cash rose from £471,156 to £504,279; loan principal
remained £100,000. Actual vehicle OPEX, interest categories, net profitability,
ROI, and net break-even remain UNKNOWN. Annual sampled-interval revenue/cargo:
£9,920/580; £10,259/600; £10,258/600; £10,241/600; £10,257/600.
Snapshot gaps reach three economy days; period observations are sampled boundaries,
not exact monthly/quarterly accruals.

Finalization attempted to update the existing immutable `company-policy.json`
through the write-once JSON helper and failed after `after.sav` and `receipt.json`
were retained. Without explicit derived recovery, full receipt replay rejects the
incomplete policy/save provenance; initial P07 analysis likewise rejected it.
Raw five-year observations do not override this failed acceptance gate.
The corrected implementation writes a separate immutable `company-policy-final.json`
and verifies both records. Its lifecycle regression and 75 related tests pass;
this correction neither repairs nor changes Attempt 19's retained evidence/status.
[Attempt 19 evidence](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19/)
is retained with a matching artifact manifest. Cleanup independently passed:
process reaped, connection/listeners closed, credential removed, workspace disposed,
no remaining owned processes or runtime errors. Attempt 18's 1,687 files remain
unchanged. Both attempts are consumed; no relaunch is permitted.

**Attempt 18 FAILED (2026-10-15): `CONTINUOUS_AUTORENEW_ENABLED`.**
Independent prelaunch checks passed: unconsumed claim, PRELAUNCH digest, all 263
frozen file hashes, predecessor provenance, effective config, documented command,
and unchanged resource/lifecycle budgets. The single authorized launch used
OpenTTD 15.3 and one encrypted Admin connection; no retry or reconnect occurred.
Three planner-selected services were constructed with £28,459 command-recorded
CAPEX. The native GameScript rejected `continuous-begin` with
`CONTINUOUS_AUTORENEW_ENABLED` despite frozen `company.engine_renew=false`.
Python then reported `TimeoutError`; failure-save collection reported
`Native script/asset error`.

The operation-start baseline was never returned: zero snapshots and zero complete
economy years are verified; elapsed operating days, deliveries, revenue, OPEX,
interest, unknown cash movements, opening/closing operating cash and loan, annual
throughput, ROI, and break-even are unavailable. Construction receipts do not
establish continuous operations. Offline receipt verification and P07 analysis
reject the missing `continuous-begin-response.json`; no five-year charts exist.

[Attempt 18 retained evidence](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt18/)
includes the claim, construction receipts, raw exchanges, logs, partial status,
result, cleanup, and matching artifact manifest. Cleanup confirms process reaping,
closed connection/listeners, removed credential, and disposed workspace, with no
remaining owned processes. The attempt is consumed and must never be relaunched.

For fresh continuous attempts, scenario initialization disables auto-renew in
`GSCompanyMode(0)`, checks the setter result, and independently reads the effective
company setting before planning. The frozen company policy and native readbacks
are retained with save digests in `company-policy.json`. Packaged Save/Load tests
check policy consistency; this does not claim a native reload. The continuous
observer still rejects enabled auto-renew and changed vehicle/order identities.
Explicit continuous rejections return a correlated reason immediately, allowing
failure-save collection without terminating the GameScript.

The five-year mode reuses the three-service P05 plan, infrastructure, vehicles,
orders, receipts and secure session. All selected services start before the
observation baseline and remain active through repeated pickup/delivery cycles.
It adds no vehicles and changes no planner decisions. Attempt 17 has ended;
this experiment requires a fresh disposable world and separate launch authority.
No launch or connection is authorized by preparation, preflight or offline analysis.

Prepare and inspect a fresh attempt without starting OpenTTD:

```bash
FIVE_YEAR_ATTEMPT="$(.venv/bin/python -m app.simulation.openttd.proof.freight_delivery next)"
.venv/bin/python -m app.simulation.openttd.proof.freight_delivery prepare "$FIVE_YEAR_ATTEMPT" \
  --demo --planner --network --network-service-limit 3 --continuous-years 5 \
  --scenario high-budget-500k --planning-budget 500000
.venv/bin/python -m app.simulation.openttd.proof.freight_delivery preflight "$FIVE_YEAR_ATTEMPT"
```

Only after separate authorization, the existing one-launch command is:

```bash
.venv/bin/python -m app.simulation.openttd.proof.freight_delivery run "$FIVE_YEAR_ATTEMPT" \
  --authorize-one-launch
```

Expect approximately one hour of real time. Native economy-date anniversaries
set the five-year endpoint; leap years and wallclock economy years are handled
by OpenTTD rather than assuming 365 days per year. Economy dates, calendar dates,
script ticks and wall-clock seconds remain separate. The finite monitor permits
3,600 polls, paced at two seconds, with a two-hour monitoring ceiling and a
140-minute overall lifecycle ceiling. Request, secure-frame, artifact and log
budgets are explicit; artifacts are capped at 64 MiB and runtime logs at 8 MiB.
Paused or stalled simulation, changed vehicles/orders and stalled routes fail
the run. No reconnection or automatic resume is performed.

The durable journal `continuous-snapshots.jsonl` records bounded native observations.
`continuous-periods.json` selects approximately 60 monthly, 20 quarterly and
five annual reports without duplicate periods. Monthly and quarterly changes
are sampled intervals around boundaries, not exact calendar-month accruals.
`continuous-summary.json` records the final network summary;
`continuous-partial.json` preserves interruption status. Correlated native request
and response files, secure-frame evidence, existing service/network receipts,
cleanup records and the artifact manifest retain independent replay provenance.

Verify completed evidence and generate offline P07 charts outside the native package:

```bash
.venv/bin/python -m app.simulation.openttd.proof.freight_delivery verify "$FIVE_YEAR_ATTEMPT"
.venv/bin/python -m app.experiments.cli analyze-continuous-freight "$FIVE_YEAR_ATTEMPT" \
  --output artifacts/experiments/p07-five-year-freight
```

Open `artifacts/experiments/p07-five-year-freight/charts.html` in a browser; it is
self-contained and needs no chart service. `summary.json` and `metrics.csv` retain
metric provenance and sampled intervals. Charts compare all three services and
the aggregate: monthly revenue, annual cargo, service revenue, cash, measured
operating costs, station backlog, sampled load/capacity utilization, cumulative
revenue against construction/purchase CAPEX, and break-even when supported.
The network utilization ratio is total observed load divided by total capacity.

Native company quarter income, signed total expenses, delivered cargo, cash,
loan balance and vehicle annual profit are measured. Per-service delivered
cargo is retained when its native destination-industry/commodity delivery monitor
belongs exclusively to that service. Service revenue,
completed cycle counts, actual vehicle OPEX, loan interest and expense categories
remain UNKNOWN where the available APIs cannot establish them. Annual running-cost
rates and vehicle profit do not establish actual OPEX. Cash reconciliation keeps
unknown movements separate; the historical £1,067 discrepancy remains UNKNOWN
without corresponding native category evidence. Operating profit, ROI and
break-even stay UNKNOWN unless every necessary cost and movement is supported.
Cumulative revenue exceeding CAPEX alone does not prove profitability.
Partial evidence is reported as partial and cannot establish five-year completion.

### Random-world demo milestone

The fixed playable demo remains the default. Explicit `--random-world` adds native
256×256 generation settings and bounded observed-world P08/P05 planning. Terminal
status and P07 reports include operational history, expense/UNKNOWN labels and
revenue/throughput charts. Offline `report` and `compare` commands reuse retained
evidence. See [random mode, interfaces and limitations](docs/random-world-demo.md).
Native random-world validation requires separate authorization.
