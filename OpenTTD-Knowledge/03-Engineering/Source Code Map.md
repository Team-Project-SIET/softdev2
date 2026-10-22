---
title: "Source Code Map"
type: engineering
status: current
updated: 2026-10-22
tags:
  - openttd
  - engineering
  - source
---

# Source Code Map

Paths are relative to the repository root = parent of this vault
([[07-Reference/Important Paths]]). Responsibility→files mapping (change ownership):
[[01-Architecture/Component Map]]. This page adds the fuller tree and the GameScript
packages.

## Top-level tree (live repo, 2026-10-22)

```text
app/
├── openttd_demo.py             public demo CLI (fixed / random / report / compare)
├── demo_random.py              random recipe, discovery, budgets, diagnostics
├── demo_random_native.py       native random staging + qualified capture
├── demo_operations.py          operational monitoring CLI
├── demo_smoke_preflight.py     smoke preflight checks
├── database/                   SQLAlchemy models/migrations support
├── experiments/                historical batch/live experiment CLI + persistence
│   ├── cli.py                  analyze-freight, analyze-performance-insights, …
│   ├── freight_network.py      P07 network evaluation
│   └── performance_insights.py evidence-aware insights (uncommitted work)
├── integrations/               legacy external integrations (transport-experiment path)
├── planning/                   P05/P07/P08 pure planning + contracts
│   ├── domain.py  canonical.py  optimizer.py  validation.py  execution.py
│   ├── p08_adapter.py  p08_road.py  p08_network.py  p08_clearing.py
│   ├── p08_terrain.py  p08_terraform.py  p08_v2_snapshot.py (untracked)
│   ├── construction_readiness.py  network_cli.py  transport.py  thin_ai/
└── simulation/openttd/         15.3 integration (see below)
tests/                          controlled tests; native seams blocked by default
docs/                           proof reports, specs, handoff snapshots
artifacts/                      RETAINED GIT-IGNORED evidence (attempts, demos, tools)
examples/openttd-demo/          public demo guide (README)
reports/, prototypes/, alembic/ historical/legacy support
```

## app/simulation/openttd/ — main integration modules (selected)

| Module | Role |
|---|---|
| `secure_admin.py`, `admin_protocol.py`, `admin_session.py`, `admin_crypto.py` | encrypted AdminPort session, packet layer |
| `gamescript_transport.py`, `gamescript_protocol.py`, `gamescript_bridge.py` | wire protocol to the bridge GameScript, schema-2 dispatch |
| `freight_delivery.py`, `freight_planning.py`, `freight_native_network.py` | delivery executor, planning composition, network kind |
| `freight_planning_replay.py` | offline receipt replay |
| `freight_runtime_planning.py`, `supplemental_planning_facts.py`, `world_planning_observation.py`, `planning_fact_input.py` | qualified observation + supplemental capture |
| `qualification_*` (bridge/session/clock/policy/stability/state/evidence) | same-run qualification |
| `structural_world.py`, `structural_world_session.py`, `production_observation.py` | structural/production observation contracts |
| `tile_classification.py` | schema-2 census receipts/exchange/sweep + plan (E11–E16) |
| `v2_semantic_reconciliation.py` (untracked) | offline V1/V2 reconciliation policy [[05-Planning/Blockers]] |
| `terrain_clearing.py`, `corridor_construction.py`, `road_mutation.py` | mutation contracts (D-chain) |
| `canonical_fleet` modules (`freight_canonical*.py`) + `freight_capacity_execution.py`, `freight_continuous.py` | canonical fleet + capacity/continuous groundwork |
| `proof/` (~40 modules) | one-launch preparation, ownership gates, attempt bookkeeping, Burke verification runners (`classification_capture.py`, `classification_execution.py`, `corridor_construction_native.py`, `terrain_terraform_native.py`, `cargo_page_*`, `catalog_*`, `economy_authority.py`, `historical_protection.py`, …) |
| `runtime/`, `runtime_assets.py`, `runner.py`, `live_launch.py`, `live_runner.py` | asset validation, isolated launch/live path (legacy live experiments) |

## GameScript packages (Squirrel `.nut`)

| Package | Path | Identity / role |
|---|---|---|
| Freight delivery demo | `app/simulation/openttd/freight_delivery_package/` | `RoadFreightProof` v1 — `main.nut`, `demo.nut`, `planner.nut`, `infrastructure.nut`, `vehicle.nut`, `network.nut`, `funding.nut`, `continuous.nut`, `canonical.nut`, `canonical-collector.nut` |
| Qualification bridge | `app/simulation/openttd/qualification_bridge.nut` (+ `.py`) | qualification observations |
| Road mutation | `app/simulation/openttd/road_mutation_package/` | road ceremony (D-lineage ancestor) |
| Terrain classification | `app/simulation/openttd/terrain_classification.nut` + `terrain_classification_bridge.py` | 15-predicate schema-2 pages |
| Terrain clearing | `app/simulation/openttd/terrain_clearing_package/{info,main}.nut` | `GSTile.DemolishTile` only (static test forbids others) |
| D4 corridor | `app/simulation/openttd/d4_corridor_package/{info,main}.nut` | `NetworkFreightProof extends D4CorridorProof`; handler for wire contract v4 |
| Gamescript bridge package | `app/simulation/openttd/gamescript_bridge_package/` | bridge skeleton provider |

Staging rule (AI_HANDOFF): editing the base `.nut` source alone is insufficient — inspect
staged package correspondence, legacy sealed profiles and independent replay
([[03-Engineering/Reproduction Guide]]).

## Proof-runner CLI

```bash
uv run --no-sync python -m app.simulation.openttd.proof.freight_delivery \
  {next|prepare|preflight|run|verify} <attempt> [flags]
```

`prepare`/`preflight` perform no launch and create no claim. `run --authorize-one-launch`
consumes a claim **only where operator authorization exists**. D-chain runners are
separate one-shot binaries (e.g. `proof.corridor_construction_native run <candidate>`).
Historical preflight/launch harnesses may contain consumed pathways — never execute them
as reusable scripts ([[03-Engineering/Reproduction Guide]]).

## Untracked-in-Git engineering (as of 2026-10-22)

Random World implementation, distance support, D-chain modules (e.g.
`corridor_construction.py`, `corridor_construction_native.py`, `d4_corridor_package/`),
classification execution paths, reconciliation modules, P07 analytics extension — all
present locally, none published logically by a commit. A file being present does not
imply it was accepted natively ([[00-Project/Current Status]]).
