# Reproduce and verify — 2026-10-17 (checkpoint addendum 2026-10-18)

Run from the repository root. Read CONTEXT, AI_HANDOFF and TASKS first. Python
3.14+ is required; `pyproject.toml` and `uv.lock` are dependency authority.
Use `uv sync --locked` when provisioning a new environment. Preserve the existing
environment for inspection. No PostgreSQL or Docker is required for the demo.

## Inspect without native execution

```bash
git branch --show-current
git rev-parse HEAD
git status --short --untracked-files=all
git ls-files --others --ignored --exclude-standard --directory
.venv/bin/python -m app.openttd_demo check
.venv/bin/python -m app.openttd_demo plan
.venv/bin/python -m app.openttd_demo plan --random-world --seed 17 \
  --map-size 256 --climate temperate --terrain 0 --towns 1 --industries 2 \
  --max-candidates 16 --max-services 4 --max-vehicles 4 --planning-seconds 30
```

`check` validates binary/assets/desktop only. Add `--headless` for no-desktop
prerequisite checking. Fixed `plan` writes offline scenario selection/results;
random `plan` writes a generation recipe, not an observed world or selected plan.
Commands write fresh UUID output directories where applicable. Check local
resources before installing anything; dependency setup was not rerun here.

## Focused controlled regression

Read the tests before expanding scope. These test files use controlled peers/VM,
retained offline replay and Python solver workers, with native seams blocked:

```bash
.venv/bin/pytest -q tests/test_demo_random.py tests/test_demo_random_native.py \
  tests/test_random_distance.py tests/test_random_capture_schema.py \
  tests/test_random_capture_budgets.py tests/test_demo_operations.py \
  tests/test_demo_smoke_preflight.py tests/test_openttd_demo.py
git diff --check
```

Some tests require ignored retained evidence and pinned external assets. A clone
without those files may fail; do not silently replace native evidence with
synthetic fixtures. Fresh results for this handoff are in
[validation.md](docs/handoff/2026-10-17/validation.md).
Prior extension suite counts and VM results are historical, not rerun claims.
Full-tree test/lint/type health remains UNKNOWN beyond recorded checks.
Never enable `--run-openttd` or `--run-postgres` for an offline handoff.

## Native demo — requires separate authorization

Provision the exact OpenTTD 15.3 Linux generic amd64 distribution and OpenGFX 8.0.
Set paths **before** Python imports the runner:

```bash
export OPENTTD_BINARY="/absolute/path/to/openttd-15.3-linux-generic-amd64/openttd"
export OPENTTD_OPENGFX_ARCHIVE="/absolute/path/to/opengfx-8.0-all.zip"
```

The public runner supports these overrides; inspect `proof/freight_delivery.py`.
Pinned binary SHA-256:
`276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`.
Pinned OpenGFX archive SHA-256:
`43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be`.
Keep language/distribution assets beside the executable. Read
[the demo guide](examples/openttd-demo/README.md) for setup and spectator controls.

Stable command (starts server and spectator):

```bash
.venv/bin/python -m app.openttd_demo --view-seconds 300
```

Future random smoke command shape, only after fresh preparation, independent
preflight and explicit one-shot authority:

```bash
.venv/bin/python -m app.openttd_demo run --random-world --seed 17 \
  --map-size 256 --climate temperate --terrain 0 --towns 1 --industries 2 \
  --max-candidates 16 --max-services 4 --max-vehicles 4 --planning-seconds 30 \
  --stop-on-delivery
```

This is a command reference, not authority to invoke it or retry historical runs.
The CLI defaults to `run` when the command is omitted. `--headless` still launches
the native server. Historical preflight/launch harnesses contain consumed paths
and authorizations; never execute them as reusable reproduction scripts.

A new run requires frozen code/config/assets, effective settings and source-trust
checks, bounded ports/time/requests, one encrypted session, independent readback,
receipt replay and full owned-process/credential/workspace cleanup. Failure stops
without retry/reconnect and retains partial evidence. Cleanup does not delete
historical saves/logs. `--view-seconds` uses the existing total runtime deadline.

## Offline reports after accepted native evidence

```bash
.venv/bin/python -m app.openttd_demo report --source /absolute/path/to/completed-demo
.venv/bin/python -m app.openttd_demo compare --source /absolute/path/to/report-a \
  --compare-with /absolute/path/to/report-b
```

The CLI writes fresh sibling output. Preserve source packages. P07 needs completed
native receipts; Seed 17's failed smoke supports diagnostics, not P07 deliveries.
Comparisons are descriptive across distinct seeds/configurations, not causal
matched experiments. Recompute current hashes from the dated handoff inventory
before transfer/use; this inventory is not a historical resealing authority.

## 2026-10-18 checkpoint addendum — checked commands

The evidence-aware insights subcommand regenerates P07 read-only reports offline
(no native process underneath; the attempt source is a consumed attempt, so the
analysis output keeps the FAILED terminal visible):

```bash
.venv/bin/python -m app.experiments.cli analyze-performance-insights \
  artifacts/experiments/p07-attempt19-five-year-offline \
  --output <fresh-output-directory> \
  --compare artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a-report
```

Focused classification-V2/P07 suites used for the 2026-10-18 documentation
checkpoint (all offline; 151 passed):

```bash
.venv/bin/pytest tests/test_performance_insights.py tests/test_world_correspondence.py \
  tests/test_classification_capture.py tests/test_classification_execution.py \
  tests/test_gamescript_transport_classification.py tests/test_tile_classification_receipt.py \
  tests/test_p08_classification_workflow.py tests/test_terrain_classification_preparation.py \
  tests/test_tile_classification.py tests/test_p08_feasibility_classification.py
```

Consumed Tile Classification V2 capture integrity (read-only; verifies the
retained 90-page receipts/pages/verdict candidate bytes):

```bash
cd artifacts/demos/classification-exec-seed17-3a8f9e46 && sha256sum -c artifact-manifest.sha256
```

The completed capture's fusion result is REJECTED (83 PROJECTED_FLAGS_DIFFER,
nothing fused): reproducing that binding offline means re-running only the
sweep/receipt classes over those retained page bytes (see
[the completion record](docs/p08-classification-v2-native-capture-completion.md)),
not any new launch. Native capture runs remain one-shot authorized events with
consumed identities; never re-run them from this file.

## 2026-10-31 addendum — D5-CORRIDOR-EXTENSION-3 offline validation (checked)

The terrain-survey pipeline's documented offline command of record (no launch,
no AdminPort, no candidate lifecycle; exact result 2026-10-31: 130 passed,
1 skipped, 0 failed, 0 errors; the skip is the `typeof` note at
`tests/test_corridor_terrain_survey.py:346`):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_secure_admin.py \
  tests/test_corridor_terrain_survey.py \
  tests/test_corridor_terrain_survey_native.py \
  -q -p no:cacheprovider -rs
```

Read-only status proves on retained D5-CORRIDOR-EXTENSION-3 candidates (never
a reproduction of any consumed attempt; candidate-2 is stale-by-source-drift
and never-consumed, candidate-3 is consumed COMPLETE — `SURVEY_COMPLETION_VERIFIED`):

```bash
.venv/bin/python -m app.simulation.openttd.proof.corridor_terrain_survey_native \
  verify artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-2

.venv/bin/python -m app.simulation.openttd.proof.corridor_terrain_survey_native \
  verify artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-3
```

`PRELAUNCH`/`preflight`/`run` are staging or native-execution entry points:
run them only under the exact staging/approval gates recorded in phase-a
record §11.4. A candidate whose staged bytes verify is one operator signature
and one launch approval away from execution — neither is granted by a
documentation task.
