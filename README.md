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

Commit `6b612fa` cleaned up older pre-T-series documents and scaffolding.
**T01–T18 are the current project's production telemetry/runtime foundation**, documented in the
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

## Research stack and project layout

The current platform uses Python 3.14+, OpenTTDLab, Pydantic, SQLAlchemy,
Alembic and PostgreSQL 16. OR-Tools remains an intentional dependency for future
optimization research; it is not an implemented network optimizer.

```text
app/
├── config.py          # Current application/database settings
├── database/          # Shared Base, session factory and current ORM registry
├── experiments/       # Scenarios, policies, batch/live service, history and CLI
├── simulation/openttd/# Runtime, Admin observation, telemetry and final parsing
└── planning/          # P02 contracts/validation and P03 transport/thin executor
alembic/versions/      # Published migration history 0001 through 0007
tests/                # Contracts, controlled runtime tests and opt-in real proofs
docker-compose.yml    # PostgreSQL service and persistent database volume
```

## Set up PostgreSQL and the Python environment

Install Python 3.14 or newer and [uv](https://docs.astral.sh/uv/). Configure a
local `.env` with your own database credentials, for example:

```dotenv
POSTGRES_DB=logistics
POSTGRES_USER=logistics
POSTGRES_PASSWORD=replace-with-your-password
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg://logistics:replace-with-your-password@localhost:5432/logistics
APP_ENV=development
SQL_ECHO=false
```

Keep `DATABASE_URL` aligned with the Compose database/user/password/port. The
name `logistics` preserves the existing database contract; experiment and telemetry
history use this PostgreSQL database. URL-encode password characters when needed.
The real `.env` is ignored by Git.

```bash
uv sync --group dev
docker compose up -d postgres
docker compose ps
uv run alembic upgrade head
```

Wait for PostgreSQL to report healthy before migrating. The application needs no
mock operational dataset. The `postgres_data` named volume retains database data.
Migration status can be inspected with:

```bash
uv run alembic current
uv run alembic history
```

The current ORM registry contains experiment scenarios, strategies, runs, final
simulation results/metrics, live telemetry sessions and observations. Published
migrations `0001`–`0007` remain unchanged and resolvable. Earlier migrations still
create historical operational tables; application-code retirement does not remove
those tables or their data. Schema retirement requires a separate data-retention
and migration decision.

## Run tests and lint

```bash
uv run pytest
uv run pytest --run-postgres tests/test_postgres_integration.py tests/test_telemetry_repository.py tests/test_live_isolation.py
uv run ruff check .
uv run ruff format --check .
```

Default tests use SQLite, fake runners and controlled child processes/Admin peers.
They cover experiments, planning serialization/validation/transport, P04 observation,
telemetry, runtime lifecycle, isolation and recovery without launching OpenTTD.
Shared PostgreSQL fixtures and migration helpers live in `tests/postgres_support.py`.
The `--run-postgres` option uses temporary isolated schemas in the configured
PostgreSQL database to verify migration compatibility, telemetry constraints,
history preservation, persistence and isolation. Historical migration tests run
without retired runtime ORM packages and include PostgreSQL SQL-generation checks.

Real OpenTTD integration and P03/production proofs require `--run-openttd` and their
specific proof configuration. Ordinary test runs skip those launches. Existing
proof artifacts and fixture savegames remain the historical evidence; controlled
tests do not replace real-proof acceptance.

## Stop local infrastructure

```bash
docker compose down
```

This stops containers while preserving `postgres_data`. Removing database volumes
would also delete current experiment and telemetry history.
