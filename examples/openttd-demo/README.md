# Run the OpenTTD freight demo

The native MVP and graphical spectator joining/inspection are VERIFIED. Run all
commands below from the repository root. No historical experiment files are
required for a new demo.

## Install prerequisites

Use Linux amd64 with a graphical desktop, Python 3.14 or newer, and uv:

```bash
uv sync --locked
```

Download and extract the official **OpenTTD 15.3 Linux generic amd64** distribution.
Keep its language and other distribution files beside the executable. Download
**OpenGFX 8.0**, retaining the `opengfx-8.0-all.zip` archive. Set both paths to your
own installation before starting Python:

```bash
export OPENTTD_BINARY="/absolute/path/to/openttd-15.3-linux-generic-amd64/openttd"
export OPENTTD_OPENGFX_ARCHIVE="/absolute/path/to/opengfx-8.0-all.zip"
.venv/bin/python -m app.openttd_demo check
```

The paths above are placeholders. The runner checks the pinned binary and archive
SHA-256 values in `app/simulation/openttd/proof/harness.py` and `graphics.py`.
Other builds and graphics versions are unsupported. OpenSFX, OpenMSX, PostgreSQL,
and Docker are not required. The runner creates isolated configuration, local
ports, and a temporary Admin credential; do not supply a shared server password.
`check` reads prerequisites and desktop environment variables without launching.
Close other OpenTTD processes before running: preflight requires an idle runtime.

## Open the graphical demo

```bash
.venv/bin/python -m app.openttd_demo --view-seconds 300
```

This starts one dedicated server, one spectator client, and one encrypted Admin
connection. Setup and delivery can take several minutes. The deterministic
scenario is a flat, temperate 64×64 seed-42 world, six freight industries, and
finite £500,000 funding. Each run rebuilds the world and captures fresh facts.

Python P08 generates bounded road candidates from qualified live observations and
supplemental facts. P05 selects three services under fleet and budget constraints.
The native bridge builds company-owned roads, stations, depots, trucks, and orders
using GameScript company mode. Independent state readback verifies construction,
loading, movement, destination delivery, and payment. Services run serially.

The verified run selected **4→5, 2→3, 0→1**, constructed vehicles **4/5/6**, and
delivered **20 coal each: 60 total, £1,022 revenue**. This is an example outcome,
not a fixed revenue guarantee. The trucks park after their delivery batches.
The game stays open for up to 300 seconds after delivery. The default hold is
120 seconds; `--stop-on-delivery` removes the hold. Close the client after delivery
or press Ctrl+C to finish early. The overall lifecycle limit is 20 minutes.

Click trucks and stations, open company finances, scroll, and zoom to inspect.
The client is a spectator: direct control of Python's trucks is unsupported.
Creating a separate company is available through Multiplayer company controls,
but manual building is outside the verified automation scope. Do not modify
Python's company or infrastructure during execution. `--headless` omits the GUI
and cannot verify graphical behavior.

## Inspect P07 results

Each run writes `artifacts/demos/playable-demo-<id>/`. After successful execution
and cleanup, a sibling `playable-demo-<id>-report/` contains `results.md`,
`evaluation.json`, and `execution-plan.json`. The terminal prints the results and
`after.sav` paths. Open `results.md` for observed metrics and `evaluation.json` for planned comparisons.
The retained save can be inspected through OpenTTD's **Load game** menu;
restarting its automation is unsupported.

Full operating costs, ROI, and net profitability remain UNKNOWN. Cash decreases
without category evidence are unallocated, not inferred operating expenses.
The bundled [sample report](sample-report/results.md) is historical Attempt 17's
offline replay: 60 coal and £1,018 revenue. It is distinct from the £1,022 demo.
[scenario.json](scenario.json) supplies the offline planning example:

```bash
.venv/bin/python -m app.openttd_demo plan
```

This generates an offline plan/report under `artifacts/demos/offline-plan-<id>/`.
It does not capture a native world or launch a game.

## Troubleshoot

- Missing binary or graphics: set the two environment variables before Python
  starts. A hash mismatch requires the exact pinned distribution/archive.
- Missing desktop: run from a graphical desktop terminal with `DISPLAY` or
  `WAYLAND_DISPLAY`, or use `--headless` for server-only operation.
- Startup or delivery failure: inspect the printed run directory's `stderr.log`,
  `result.json`, `cleanup.json`, and `client/client.log` when present.
- Client exits during automation: the run fails and retains partial observations.
  Ctrl+C also retains partial evidence and cleans up, without a successful report.

Cleanup closes/reaps the owned client before the server, closes the Admin session
and listeners, removes the credential, and disposes the owned workspace. Logs,
results, and saves remain. Never delete historical attempts or use broad process
kill commands to recover this demo.

## Limits and next milestone

Native verification covers this deterministic three-service road-coal scenario.
Controlled/offline tests cover planning and reporting contracts. Continuous fleet
operation, shared dispatch, human takeover, rail, arbitrary maps, and full expense
attribution are outside the verified MVP.

**Random World & Scalable Logistics** is future work: native random generation,
configurable seed/world size, generalized P08 industry/cargo discovery, feasible
routes over varied terrain, dynamic service selection, larger fleets/networks,
and P07 performance comparison. No such feature is introduced here.

Launch-free checks for this checkpoint are recorded in
[validation](VALIDATION.md).
