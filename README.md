# Transport Planning Experimentation Platform

The core goal is transport route, network and infrastructure optimization evaluated
in OpenTTD: choose connections, construction corridors, stations, transport modes and
fleet capacity, then measure the resulting network's efficiency and economics.
OpenTTD supplies the simulated world, vehicle behavior, cargo and company economics.
Its lower-level vehicle pathfinding, including YAPF, navigates infrastructure that
already exists; it does not replace the repository's intended network-design optimizer.
See the pinned [OpenTTD 13.4 road YAPF source](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/pathfinder/yapf/yapf_road.cpp).

The implemented experiment platform uses Python, version-pinned
[OpenTTDLab](https://github.com/michalc/OpenTTDLab), headless OpenTTD and PostgreSQL
to compare external AI policies reproducibly. Those AIs currently design, construct
and operate the networks; Python selects their configuration and records outcomes.

## Current architecture and project status

```text
CURRENT EXPERIMENT PATH
Scenario + versioned AI policy -> ExperimentService
    -> batch: OpenTTDLabRunner -> OpenTTD + pinned external AI -> public save parser
    -> live:  LiveSimulationRunner -> owned OpenTTD + pinned external AI
                 -> P04 AdminObserver -> typed telemetry -> PostgreSQL
                 -> explicit final save -> public save parser
    -> typed final metrics + PostgreSQL experiment history + retained artifacts

SEPARATE PLANNING BOUNDARY
PlanningScenario + PreparedWorldManifest
    -> repository-owned Python network optimizer                     [missing]
    -> P02 ExecutionPlan contracts -> validate/hash -> P03 staging
    -> P03ThinExecutor: decode/validate world/acknowledge              [implemented]
    -> infrastructure construction, fleet purchase and service orders [missing]
    -> plan-attributed simulation evaluation loop                     [missing]

RETAINED OPERATIONAL CAPABILITIES
Textual TUI -> routing/packing services -> CVRP/packing solvers + PostgreSQL
```

- **P01** defines the [planning/executor boundary](docs/specs/planning-executor-boundary.md).
- **P02** implements pure typed planning contracts, canonical serialization/hashing
  and prelaunch semantic validation (`app/planning/`); it does not generate plans.
- **P03** implements deterministic plan transport and a thin Squirrel executor.
  Python validates and stages the plan; `P03ThinExecutor` consumes/decodes it,
  validates runtime-world facts and acknowledges its IDs. The accepted receipt
  does not establish construction, vehicle purchase or service-order execution.
  [Runtime identity and Attempt #6 coverage](docs/planning-runtime-world-identity.md)
  describe the completed proof and its limits.
- **P04** completes the read-only Admin observation boundary used by the live
  runner: protocol framing/validation, owned session cleanup, authentication,
  identity checks, subscriptions, polling and heartbeat observations. Process
  launch, reconnect policy and persistence belong to surrounding components.

The repository-owned network optimizer, construction executor and evaluation loop
that attributes realized results to an executed plan are still missing. P03 staging
is separate from the production `ExperimentService` input path; P04 observations
support evaluation but do not complete that loop. Final-save period metrics and
company-level Admin observations are not a complete route-level profit measure.
These are current implementation gaps, not new task definitions.

### Documented history

Commit `6b612fa` cleaned up older pre-T-series documents and scaffolding; retained
operational modules remain available. **T01–T18 are the current project's production
telemetry/runtime foundation**, documented in the
[ticket definitions and completion context](docs/specs/realtime-openttd-telemetry-ticket-plan.md).
T17's accepted production proof is retained in [the smoke report](docs/live-production-smoke.md)
and commit `eca5a44`. T18 (`5a7e5ee`) retired the executable prototype, preserving
reference evidence; it did not retire the production T-series implementation.

P01–P04 are later planning/integration work: P01's specification, P02 (`76e176c`),
P03 (`7260f8c`) and P04 (`84ccb61`). The repository defines no one-to-one T-to-P
mapping and no P05. Historical proof reports retain their original attempt status;
current status comes from the accepted evidence and implementation history.

## Run the baseline experiment

Start PostgreSQL and configure `DATABASE_URL` as described below. Then run:

```bash
uv sync --group dev
uv run alembic upgrade head
uv run transport-experiment run --seed 17 --days 730
```

The command runs without a GUI and prints its run ID, final simulation date, metrics, and
artifact path. Repeating it creates a separate history row with the same configuration. The
scenario pins a generated 256-by-256 map configuration; the seed fixes world generation.
The baseline uses OpenTTD **13.4**, OpenGFX **7.1**, OpenTTDLab **0.0.75**, and trAIns AI
**2.1** from BaNaNaS with MD5 `c4c069dc797674e545411b59867ad0c2`.
Python **3.14.6** has been exercised with this combination on Linux. OpenTTDLab downloads
and caches the pinned game, graphics, and AI archives under `artifacts/experiments/cache/`.
Its final parsed savegame chunks and run configuration are saved as
`experiment-<run ID>.json.gz` beside that cache.

The first metrics are company money, current loan, income and expenses for the savegame's
current economy period, and cargo delivered in that period. These are values parsed from
the company record; the period metrics are not lifetime totals. Experiment rows preserve
the scenario/version, strategy/version and configuration, AI ID and MD5, game/graphics
versions, seed, duration, timestamps, completion status, and artifact reference. Failed
simulations remain recorded as failures. The OpenTTDLab adapter owns all savegame dictionary
access; strategies and persistence use application models.

## Compare transport policies

The comparison uses the same pinned SimpleAI 14 archive (MD5
`b3137bbd0c73641cf510ead06e36dab6`) for both policies. Python owns the versioned
strategy definitions and serializes their exact AI settings. `multimodal` sets
`use_trains=1`, `use_roadvehs=1`, and `use_aircraft=1`; `road-only` sets them to `0`, `1`,
and `0`. SimpleAI then constructs and operates routes inside OpenTTD. This is a transport
mode policy comparison, not a claim that one mode is universally better. This experiment
path uses pinned external AIs rather than a repository-owned Squirrel optimizer.
The repository does contain the P03 thin Squirrel executor and generated plan-data
transport; that executor validates and acknowledges supplied decisions without
optimizing the network or executing construction.

```bash
uv run transport-experiment compare \
  --scenario generated-256-square \
  --strategies multimodal,road-only \
  --seeds 0:10 \
  --days 730
```

The seed range is start-inclusive and stop-exclusive, so `0:10` runs seeds 0 through 9
for each policy. Every attempt has its own PostgreSQL experiment row and parsed-result
artifact. The command prints per-run metrics and per-policy mean, median, min, max, and
sample standard deviation for each metric, then saves the full comparison as a JSON report
under `artifacts/experiments/`. Failed runs remain visible and do not contribute to
summaries. The descriptive statistics make no significance claim.

`app/routing/` retains operational shipment CVRP over a geographic distance matrix;
it is not an OpenTTD tile/network optimizer. Packing, driver, shipment, LINE and
operational TUI modules remain available as retained operational capabilities,
separate from the OpenTTD research core; none is required by the experiment command.
Physical package placement is not a simulation feasibility constraint.

## Retained operational modules

### Logistics Optimizer

A Python logistics system with a Textual interface and Capacitated Vehicle Routing Problem
(CVRP) optimization and delivery-aware 3D package loading. The application manages customers,
shipments, packages, vehicles, drivers, persisted route plans, and loading plans.

## Stack and operational architecture

- Python 3.14+
- Textual
- SQLAlchemy 2.x and Alembic
- Pydantic 2
- Google OR-Tools
- PostgreSQL 16 and pgAdmin 4 (Docker Compose)
- pytest

The operational read path remains direct:

```text
Textual TUI -> service -> repository -> SQLAlchemy -> PostgreSQL
```

Routing keeps the solver isolated from both the TUI and database:

```text
Textual TUI -> RoutingService -> CVRPOptimizer -> OR-Tools
                    |
                    +-> RoutingRepository -> SQLAlchemy -> PostgreSQL
```

`RoutingService` loads selected entities, calculates shipment demand, prepares typed optimizer
input, and persists accepted plans. `CVRPOptimizer` only receives a `RoutingProblem`; it never
queries SQLAlchemy. The distance provider is replaceable independently of the optimizer.

LINE delivery is an independent integration:

```text
Saved Route -> assigned Driver -> LineService -> LINE Messaging API
```

The routing and packing components do not call LINE. `LineService` loads a saved route and its
assigned driver, builds a plain-text route message, and delegates the HTTPS push request to
`LineClient`.

Loading follows the saved route for one vehicle at a time:

```text
Saved Route -> ordered RouteStops -> packages for that vehicle
            -> PackingService -> PackingOptimizer -> LoadingPlan
                    |
                    +-> PackingRepository -> SQLAlchemy -> PostgreSQL
```

`PackingOptimizer.solve(vehicle, packages, delivery_sequence)` accepts only typed Pydantic data.
`PackingService` prepares that data and persists the accepted result, including partial plans.

## Project layout

```text
app/
├── config.py
├── customer/          # Customer ORM model and Pydantic schemas
├── database/          # Base, session factory, model registry, seed command
├── driver/            # Driver ORM model and Pydantic schemas
├── experiments/       # Scenario/policy selection, batch/live service, history and CLI
├── simulation/openttd/# Batch adapter, live lifecycle, Admin observation and final parsing
├── planning/          # P02 contracts/validation and P03 transport/thin executor
├── integrations/line/ # Saved-route read service and LINE Messaging API client
├── packing/           # Delivery-aware packing heuristic, schemas, models, repository, service
├── routing/           # CVRP solver, distance provider, models, repository, service
├── shipment/          # Shipment/Package models, schemas, repository, service
├── tui/               # Textual dashboard
└── vehicle/           # Vehicle model, schemas, repository, service
alembic/
└── versions/          # Versioned database migrations
tests/                 # Pure contracts, controlled runtime/peer tests and opt-in real proofs
docker-compose.yml
```

## Setup

Install Python 3.14 or newer and [uv](https://docs.astral.sh/uv/), then create the local environment:

```bash
cp .env.example .env
uv sync --group dev
```

Edit `.env` and replace both example passwords. Keep the PostgreSQL credentials in
`DATABASE_URL` aligned with `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`, and
`POSTGRES_DB`. `DEPOT_LATITUDE` and `DEPOT_LONGITUDE` define the one depot used by every route.
Set `LINE_CHANNEL_ACCESS_TOKEN` to the channel access token from the LINE Developers Console when
you want to send route plans. The real `.env` is ignored by Git.

## Start PostgreSQL and pgAdmin

```bash
docker compose up -d
docker compose ps
```

With the example values, the local database connection is:

```text
Host: localhost
Port: 5432
Database: logistics
User: logistics
Password: change-me (replace this)
SQLAlchemy URL: postgresql+psycopg://logistics:change-me@localhost:5432/logistics
```

pgAdmin is available at <http://localhost:5050>. Sign in with `PGADMIN_DEFAULT_EMAIL` and
`PGADMIN_DEFAULT_PASSWORD` from `.env`. To register the Compose database in pgAdmin, choose
**Add New Server** and use:

- Name: `Logistics Local` (or any name)
- Host name/address: `postgres` (the Docker Compose service name, not `localhost`)
- Port: `5432`
- Maintenance database: the value of `POSTGRES_DB`
- Username: the value of `POSTGRES_USER`
- Password: the value of `POSTGRES_PASSWORD`

PostgreSQL and pgAdmin data are retained in the named volumes `postgres_data` and
`pgadmin_data`. `docker compose down` stops the containers without deleting those volumes.

## Create and seed the database

Wait for PostgreSQL to report healthy, then run migrations and insert the mock dataset:

```bash
uv run alembic upgrade head
uv run logistics-seed
```

The seed command is safe to run again: if customer data already exists, it makes no changes.
Useful migration commands include:

```bash
uv run alembic current
uv run alembic history
```

## Run the TUI

```bash
uv run logistics-tui
```

The dashboard reads shipments and vehicles from PostgreSQL. Press `r` to refresh and `q` to quit.
If PostgreSQL is unavailable or migrations have not run, the dashboard remains open and displays
the connection error in its status line.

To optimize routes:

1. Open the **Route Optimization** tab.
2. Select one or more pending shipments.
3. Select one to three available vehicles.
4. Choose **Optimize routes**.
5. Review each vehicle's depot-to-depot route, ordered stops, distance, and payload.
6. Choose **Save route plan** to write `routes` and `route_stops` and mark its shipments planned.
   When the selected vehicle has exactly one assigned driver, that driver is attached to the route.

To send a saved route through LINE:

1. Configure `LINE_CHANNEL_ACCESS_TOKEN` in `.env` and store the driver's Messaging API user ID
   (a `U` followed by 32 lowercase hexadecimal characters) in `drivers.line_user_id`.
   Drivers without LINE enrollment leave this nullable field empty.
2. Make sure the driver has added or contacted the LINE Official Account for the channel.
3. Open the **Route Optimization** tab and find **Send saved route**.
4. Choose a route. The selector and status line show its assigned driver.
5. Choose **Send to LINE**. The status line reports success or a configuration, receiver, API, or
   network error without closing the TUI.

The first version sends one plain-text push message with the route ID, driver, vehicle, distance,
ordered delivery stops, customer addresses, package IDs, coordinates, and Google Maps navigation
links. It deliberately does not use LINE Flex Messages.

To optimize loading (run `uv run alembic upgrade head` first):

1. Open the **Loading Optimization** tab.
2. Select a saved route. Each route identifies one vehicle and its delivery sequence.
3. Choose **Optimize loading**.
4. Review packages grouped by stop, their coordinates and orientations, and the separate loading
   and unloading order tables. Order numbers start at 1.
5. Check volume/payload utilization and the **Unplaced packages** table. A partial or infeasible
   result means some deliveries are not loaded; saving it does not mark them loaded or delivered.
6. Choose **Save loading plan** to persist the preview, metrics and unplaced-package reasons.
   Use **Refresh routes** after route changes; routes saved in the TUI appear automatically.

Coordinates and dimensions are centimeters; weights are kilograms and volumes are cubic
centimeters. `x` runs across cargo width, `y` runs from the rear door (`y=0`) toward the cab, and
`z` runs upward from the floor. Orientation letters assign the original package dimensions to
`x/y/z`: for example `LHW` means length along x, height along y and width along z.

The packing heuristic is deterministic:

- Process stops in CVRP order, reserving a separate depth band for each stop, earliest nearest
  the rear door. Packages within a stop are considered by decreasing volume, then package ID.
- Try all six 90-degree axis orientations, placing boxes in floor rows or on supported stacks.
  Each upper box must fit entirely on the box beneath it; `stackable=False` prevents putting
  another package on that box. Choose the placement that uses the least additional depth,
  with stable height, position and orientation tie-breaks.
- Respect vehicle dimensions and remaining payload; report rejected packages and continue with
  the rest. Unload near-door rows first and stacks top-down. Load in the reverse order, putting
  later deliveries deeper inside and stack bases in first.

This prioritizes avoiding re-handling of later deliveries over dense packing. It assumes a
full-width/full-height rear opening and straight rearward extraction. It can leave unused space
or reject boxes that a more advanced solver could fit. Axle balance, crushing limits, door
clearances, securement and arbitrary rotation angles are outside this simplified model.

Total package volume includes all requested boxes; used cargo volume is the sum of placed box
volumes, excluding gaps. Volume utilization is used volume divided by the vehicle's cuboid volume.
Payload utilization is loaded weight divided by maximum payload. Saved statuses are `complete`,
`partial` and `infeasible`. Loading plans keep a source snapshot and their unplaced-package list;
the service rejects a preview if its route order, packages or vehicle changed before saving.

The current distance provider uses Haversine great-circle distance. Optimizer arc costs are integer
meters and capacity constraints are integer 0.0001 kg units; routing weights accept at most
four decimal places. Displayed and persisted results use kilometers and kilograms. Shipment demand is the sum of every package's `weight`. Routes always start and end
at the configured depot, deliveries are not split, and the primary cost is total fleet distance.

The equivalent module commands are:

```bash
uv run python -m app.database.seed
uv run python -m app.tui.app
```

## Run tests and lint

```bash
uv run pytest
uv run pytest tests/test_routing_optimizer.py tests/test_routing_service.py
uv run pytest --run-postgres tests/test_postgres_integration.py
uv run ruff check .
uv run ruff format --check .
```

The default tests use an in-memory SQLite database and fake TUI services, so they do not require
Docker, a running PostgreSQL instance, or a real LINE request. The optional
--run-postgres test uses a temporary schema in the configured PostgreSQL database to check
migrations and competing route and loading saves. Routing tests use deterministic matrix/grid
distance providers and cover assignment uniqueness, capacity limits, depot boundaries, multiple
vehicles, persistence, and infeasible fleets. LINE tests mock the HTTP request and cover message
formatting and error handling. PostgreSQL-specific schema behavior is versioned in Alembic
migrations.
Packing tests cover boundaries, overlap, weight, rotation, supported stacks, accessibility,
determinism, partial results, saved CVRP route integration and TUI actions. Migration `0003` has
SQLite upgrade/downgrade and metadata parity checks plus PostgreSQL SQL-generation coverage.

## Operational CVRP scope

The solver supports one depot, one to three vehicles, package-weight capacity, and one delivery
node per shipment. It does not include time windows, live traffic, pickups, multiple depots, split
delivery or dynamic rerouting. Package loading runs separately after route
planning; packing failures do not automatically reroute shipments.

## Stop local infrastructure

```bash
docker compose down
```

To deliberately remove all database and pgAdmin state as well, use
`docker compose down --volumes`. This is destructive and is not needed for ordinary shutdown.
