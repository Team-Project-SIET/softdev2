# OpenTTD transport planning and freight demonstration

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
