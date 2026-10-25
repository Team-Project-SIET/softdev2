---
title: "Important Paths"
type: reference
status: current
updated: 2026-10-22
tags:
  - openttd
  - reference
  - paths
---

# Important Paths

## Vault ↔ repository relationship

This vault lives at **`<repo-root>/OpenTTD-Knowledge/`** where `<repo-root>` is the
`softdev2` checkout (`devmodule2`). Conventions used across the vault:

- **Code/document paths** (e.g. `app/planning/p08_road.py`) are written **relative to the
  repository root** (the parent of this vault).
- **Obsidian wikilinks** (`[[Note]]`) resolve only inside the vault. To open code or
  artifacts, use the repository checkout directly — Obsidian does not follow links outside
  the vault. Portable copying of the vault alone (e.g. the ZIP) keeps navigation working
  but leaves repository-relative paths informational text.
- Keep this vault out of Git staging/commits unless explicitly authorized.

## Repository map (top level)

| Path | Role |
|---|---|
| `app/` | application source (planning, simulation/integration, experiments, database) |
| `tests/` | controlled tests; opt-in native tests |
| `docs/` | proof reports, specs, handoff snapshots (`docs/handoff/<date>/`) |
| `artifacts/` | **retained, Git-ignored** evidence: `demos/`, `runtime/`, `experiments/`, `tools/` |
| `examples/openttd-demo/README.md` | public demo guide |
| `prototype/`, `alembic/`, `reports/` | historical prototype / migrations / reports |
| root files | `CONTEXT.md`, `AI_HANDOFF.md`, `TASKS.md`, `EVIDENCE_INDEX.md`, `REPRODUCE.md`, `README.md`, `pyproject.toml`, `uv.lock`, `mise.toml`, `.env(.example)`, `docker-compose.yml` |
| `--version` | unknown untracked root file — preserve, do not execute |

## Key source files by purpose

| Purpose | Path |
|---|---|
| Public demo CLI | `app/openttd_demo.py` |
| P08 adapter / road / network / terrain | `app/planning/p08_adapter.py`, `p08_road.py`, `p08_network.py`, `p08_terrain.py`, `p08_terraform.py`, `p08_clearing.py`, `p08_v2_snapshot.py` |
| P05 optimizer + contracts | `app/planning/optimizer.py`, `domain.py`, `canonical.py`, `validation.py`, `execution.py` |
| Transport + bridge | `app/simulation/openttd/secure_admin.py`, `gamescript_transport.py`, `admin_protocol.py`, `admin_session.py` |
| Observation / facts | `freight_runtime_planning.py`, `world_planning_observation.py`, `supplemental_planning_facts.py`, `planning_fact_input.py` (under `app/simulation/openttd/`) |
| Execution + replay | `freight_delivery.py`, `freight_native_network.py`, `freight_planning_replay.py` |
| Proof runner | `app/simulation/openttd/proof/freight_delivery.py` (verbs: `next|prepare|preflight|run|verify`) |
| Classification chain | `app/simulation/openttd/tile_classification.py`, `terrain_classification.nut`, `terrain_classification_bridge.py`, `proof/classification_*.py`, `proof/world_correspondence.py` |
| D-chain ceremonies | `terrain_clearing.py` + `terrain_clearing_package/`, `terrain_terraform_native` proofs, `corridor_construction.py` + `d4_corridor_package/`, `proof/corridor_construction_native.py` |
| Canonical fleet | `proof/canonical_fleet.py`, `freight_canonical*.py`, `freight_delivery_package/canonical*` |
| Reconciliation (untracked) | `app/simulation/openttd/v2_semantic_reconciliation.py` |
| P07 analytics | `app/experiments/cli.py`, `performance_insights.py`, `freight_network.py`, `app/demo_operations.py` |

## Key documentation

| Topic | Path |
|---|---|
| Planner/executor boundary spec | `docs/specs/planning-executor-boundary.md` |
| Offline evidence freeze | `docs/specs/openttd-offline-evidence-freeze.md` (+ baseline json) |
| Random world | `docs/random-world-demo.md`, `docs/random-world-distance-support.md`, `docs/random-world-observation-inventory.md` |
| Seed 17 smoke | `docs/seed17-native-smoke-preparation.md` |
| Classification lineage | `docs/p08-native-tile-classification.md`, `docs/p08-classification-v2-native-capture-*.md`, `docs/p08-classification-v2-execution-path.md`, `docs/p08-v1v2-semantic-*.md`, `docs/p08-v2-snapshot-p08-readiness.md` |
| D-milestones | `docs/p08-bounded-clearing-construction.md`; `docs/handoff/2026-10-21/d2-native-clearing-candidate-3-outcome.md`; `docs/handoff/2026-10-21/d3-native-integration-preflight-preparation.md`; `docs/handoff/2026-10-22/d3-terraform-native-candidate-1-outcome.md`; `docs/handoff/2026-10-22/d4-corridor-native-candidate-1-preparation.md`; `docs/handoff/2026-10-22/d4-corridor-native-candidate-2-preparation.md` |
| Five-year analysis | `docs/five-year-freight-performance-analysis.md`, `docs/capacity-experiment.md` |
| Demo guide | `examples/openttd-demo/README.md` |

## Key artifact directories (Git-ignored; presence may be UNKNOWN elsewhere)

| Path | Contains |
|---|---|
| `artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a/` | stable verified demo (E1) |
| `artifacts/demos/playable-demo-698799a2d…/`, `classification-exec-seed17-3a8f9e46/`, `classification-exec-seed17-e71c95a3/` | Seed 17 smoke (consumed/failed), V2 capture (consumed), first V2 attempt (failed) |
| `artifacts/runtime/openttd-15.3-first-freight-delivery-attempt*/` | freight attempts 4…19 |
| `artifacts/runtime/canonical-fleet-*q3/` | canonical create/reload (E2) |
| `artifacts/experiments/d2-clearing-native-candidate-3/`, `d3-clearing-native-candidate-1/`, `d3-terraform-native-candidate-1/`, `d4-corridor-native-candidate-1/` (consumed attempt), `d4-corridor-native-candidate-2/` (stale, never consumed), `d4-corridor-native-candidate-3/` (consumed attempt, partial/failed cleanup) | D-chain evidence + D4 candidates |
| `artifacts/diagnostics/d4-corridor-native-candidate-3-2026-10-25/` | separate non-authoritative console/manifest diagnostic copies for the consumed candidate-3 run |
| `artifacts/experiments/p07-attempt19-five-year-offline/` | five-year offline analytics |

## Environment paths

| Item | Path |
|---|---|
| OpenTTD 15.3 local install | `/home/fed/Downloads/openttd-15.3-linux-generic-amd64` (README/CONTEXT; use `OPENTTD_BINARY` anywhere else) |
| OpenGFX default | `artifacts/runtime/verified-assets/opengfx-8.0-all.zip` |
| uv cache override | `UV_CACHE_DIR=/tmp/softdev2-uv-cache`, `UV_TOOL_DIR=/tmp/softdev2-uv-tools` |
