# OpenTTD transport planning and freight demonstration

Python plans transport services and verifies their execution in **OpenTTD 15.3**.
The working native MVP builds a road, two truck stops and a depot, buys one truck,
loads coal from a real mine, delivers it to a real power station, and verifies
industry attribution and payment over an encrypted AdminPort connection.

On 2026-10-11, freight Attempt 4 delivered **20 units of coal**. Offline replay
verified £341 delivery income, £304 vehicle-profit increase and £9,358 construction
and purchase spending. The plan-bound receipt is in
`artifacts/runtime/openttd-15.3-first-freight-delivery-attempt4/receipt.json`.
All three authorized follow-up launches were consumed. Another execution requires
its own authorization; inspecting the existing receipt does not launch OpenTTD.

This README describes the current worktree. The freight modules and ignored runtime
artifacts have not been committed or pushed. Use a checkout containing
`app/simulation/openttd/proof/freight_delivery.py` and its GameScript package.
Historical runtime evidence is optional for a **new `--demo` run**.

## What works, and what remains incomplete

| Capability | Current evidence |
| --- | --- |
| Secure AdminPort, industry/cargo observation and native qualification | Native milestones; qualification Attempt 2's overall post-run acceptance remains FAILED |
| Road, stops, depot, purchase, orders and movement | Native readbacks |
| Freight loading, final industry delivery and payment | Attempt 4, 20 units, verified receipt and cleanup |
| WorldPlanningObservation → P08 → P05 → ExecutionPlan | Controlled end-to-end verification |
| P05 output → checked single-vehicle freight intent | Controlled compiler in `freight_planning.py` |
| Qualified observation → P08 → native delivery | **Incomplete**: authoritative post-qualification save correspondence and same-world supplemental facts are still missing |
| Arbitrary maps, rail delivery, multiple vehicles, closed-loop optimization | Outside the demonstrated MVP |

The demo uses its own native admission and `DeliveryPlan`. It does **not** claim
that P05 selected the service. Controlled planning inputs cannot authorize native
execution. Positive last-month production in the demo is native supply evidence,
not a replacement for the separate two-rollover qualification contract.

## Architecture

```text
Planning path, controlled
WorldPlanningObservation + supplemental facts + prepared-source correspondence
  → P08 bounded road candidates → P05 CP-SAT → ExecutionPlan
  → checked freight intent → native-source correspondence gate [currently blocked]

Working native demonstration
Python CLI → isolated OpenTTD 15.3 + company + bridge GameScript
  → encrypted authorized-key AdminPort → bounded native admission
  → native construction / vehicle / orders → loading / arrival / unloading
  → industry cargo monitors + company income + vehicle profit
  → Python receipt replay + saved states + complete cleanup
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

The intent's native binding calls the existing real-source gate before comparing
native geometry and identities. That gate currently rejects controlled source
correspondence. The native runner therefore remains a **standalone delivery demo**,
not a P05-driven native executor. Remaining work is same-world qualified observation,
native supplemental capture, authoritative saved-world correspondence, and support
for the exact selected corridor/facility geometry. The demonstrated L route is not
a general executor for every P08 candidate.

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

## Known limits

One company, one vehicle, one coal producer/acceptor pair, two bay stops, one depot,
a bounded flat vacant L route and default content are demonstrated. Each run uses
one process, one secure connection, no reconnect or retry, at most 26 service
requests, 512-byte responses and a 180-second overall deadline. World preparation
has its own bound of two industry builds and at most 50 clearing commands.

The demo proves one paid delivery, not long-run profitability, recurring reliability,
route-level optimization or full qualified planning integration. Amounts are OpenTTD
GBP accounting units. Receipts fail closed; neither a command ACK nor an empty
vehicle alone can establish freight delivery.
