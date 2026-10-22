---
title: "Reproduction Guide"
type: engineering
status: current
updated: 2026-10-22
tags:
  - openttd
  - engineering
  - reproduce
  - safety
---

# Reproduction Guide

This page condenses [[99-Source-Documents/REPRODUCE]] (read it in full). It is a command
reference, **not authority**: native commands below require separate authorization, and
none of these lines may be re-run against consumed attempts.

## 0. Non-negotiable safety rules

- Run from the repository root; read CONTEXT, AI_HANDOFF and TASKS first.
- Never enable `--run-openttd` or `--run-postgres` for an offline handoff.
- Native demo commands **launch native processes** — use only under separate runtime
  authorization.
- Historical preflight/launch harnesses contain **consumed** paths and authorizations;
  never execute them as reusable reproduction scripts.
- Failure stops without retry/reconnect and retains partial evidence; cleanup does not
  delete historical saves/logs.

## 1. Inspect without native execution

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

`check` validates binary/assets/desktop only (add `--headless` for no-desktop checking).
Fixed `plan` writes offline scenario selection; random `plan` writes a generation recipe —
**not** an observed world or selected plan. Check local resources before installing
anything; do not silently restore missing retained evidence with fixtures.

## 2. Focused controlled regression

```bash
.venv/bin/pytest -q tests/test_demo_random.py tests/test_demo_random_native.py \
  tests/test_random_distance.py tests/test_random_capture_schema.py \
  tests/test_random_capture_budgets.py tests/test_demo_operations.py \
  tests/test_demo_smoke_preflight.py tests/test_openttd_demo.py
git diff --check
```

See [[03-Engineering/Testing Strategy]] for scope rules and known baseline failures.

## 3. Runtime assets (only for an authorized native run)

Provision the exact pinned files and export **before** Python imports the runner:

```bash
export OPENTTD_BINARY="/absolute/path/to/openttd-15.3-linux-generic-amd64/openttd"
export OPENTTD_OPENGFX_ARCHIVE="/absolute/path/to/opengfx-8.0-all.zip"
```

Pinned binary SHA-256 `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`;
OpenGFX archive `43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be`.
Keep the whole extracted distribution (incl. `lib`, `lang`) together; a system OpenTTD
package does not satisfy the checksum gate. Install guide + hashes:
[[03-Engineering/Runtime and Environment]] and the public demo guide
(`examples/openttd-demo/README.md`).

## 4. Native demo — SEPARATE AUTHORIZATION REQUIRED

```bash
.venv/bin/python -m app.openttd_demo --view-seconds 300
```

Future random smoke command *shape* (only after fresh preparation, independent preflight
and explicit one-shot authority — this text is not authority):

```bash
.venv/bin/python -m app.openttd_demo run --random-world --seed 17 \
  --map-size 256 --climate temperate --terrain 0 --towns 1 --industries 2 \
  --max-candidates 16 --max-services 4 --max-vehicles 4 --planning-seconds 30 \
  --stop-on-delivery
```

New runs require frozen code/config/assets, effective settings and source-trust checks,
bounded ports/time/requests, one encrypted session, independent readback, receipt replay
and full owned-process/credential/workspace cleanup. `--headless` still launches the
native server. CLI defaults to `run` when omitted; `--view-seconds` uses the existing
total runtime deadline.

Planner-mode proof ceremony (per README):

```bash
PLANNER_ATTEMPT="$(uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery next)"
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery prepare "$PLANNER_ATTEMPT" --demo --planner --batch-limit 20
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery preflight "$PLANNER_ATTEMPT"
# … then, only once a separate launch is authorized:
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery run "$PLANNER_ATTEMPT" --authorize-one-launch
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery verify "$PLANNER_ATTEMPT"
```

## 5. Offline reports after accepted native evidence

```bash
.venv/bin/python -m app.openttd_demo report --source /absolute/path/to/completed-demo
.venv/bin/python -m app.openttd_demo compare --source /absolute/path/to/report-a \
  --compare-with /absolute/path/to/report-b
```

Writes fresh sibling output; preserve source packages. P07 needs completed native
receipts: Seed 17's failed smoke supports diagnostics, **not** P07 deliveries.
Comparisons are descriptive across distinct seeds/configurations, not causal matched
experiments. Evidence-aware insights (regenerates P07-style reports offline; keeps FAILED
terminals visible):

```bash
.venv/bin/python -m app.experiments.cli analyze-performance-insights \
  artifacts/experiments/p07-attempt19-five-year-offline \
  --output <fresh-output-directory> \
  --compare artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a-report
```

## 6. Read-only integrity checks (safe, no launch)

```bash
cd artifacts/demos/classification-exec-seed17-3a8f9e46 && sha256sum -c artifact-manifest.sha256
```

## 7. After a run — what "done" means

1 launch + 1 connection only; independent readback; receipt replay binds plan/world
identities; owned cleanup (process reaped, sockets closed, credential removed, workspace
disposed); evidence retained; then update the affected vault notes with dates + E-IDs
(refresh [[00-Project/Current Status]] and the task board).
