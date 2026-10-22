---
title: "Component Map"
type: architecture
status: current
updated: 2026-10-22
tags:
  - openttd
  - architecture
  - source-map
---

# Component Map

**Source:** [[99-Source-Documents/AI_HANDOFF]] "Architecture map and code entry points"
(2026-10-17 + addendum). Paths are relative to the repository root
([[07-Reference/Important Paths]]). Component-level facts: [[01-Architecture/System Architecture]].

## Responsibility → files to read (verbatim-tier map from the handoff)

| Responsibility | Read these files when changing it |
|---|---|
| Public fixed/random CLI, spectator lifecycle | `app/openttd_demo.py`, `tests/test_openttd_demo.py`, `examples/openttd-demo/README.md` |
| Random recipe, discovery, budgets, diagnostics, bounded solver | `app/demo_random.py`, `app/demo_random_native.py`, `tests/test_demo_random*.py`, `tests/test_random_*.py` |
| Native lifecycle, isolated assets/configuration, cleanup/retention | `app/simulation/openttd/proof/freight_delivery.py`, `proof/harness.py`, `runtime/`, `proof/ownership.py`, `proof/historical_protection.py` |
| Qualified observations and complete supplemental capture | `freight_runtime_planning.py`, `supplemental_planning_facts.py`, `world_planning_observation.py`, `planning_fact_input.py` under `app/simulation/openttd/` |
| P08 adaptation/road search/network composition | `app/planning/p08_adapter.py`, `p08_road.py`, `p08_network.py`, `preparation/` |
| P05 pure selection and contracts | `app/planning/domain.py`, `canonical.py`, `optimizer.py`, `validation.py`; `docs/specs/planning-executor-boundary.md` |
| Compile/admit/execute/replay | `app/simulation/openttd/freight_planning.py`, `freight_native_network.py`, `freight_delivery.py`, `freight_planning_replay.py` |
| Wire transport and native bridge | `gamescript_transport.py`, `secure_admin.py`, `freight_delivery_package/*.nut`; planner, network and funding composition is staged by the Python proof runner |
| P07 and operational monitoring | `app/planning/network_cli.py`, `app/experiments/freight_network.py`, `app/demo_operations.py`, `tests/test_demo_operations.py` |
| Canonical state/save/reload | `app/simulation/openttd/proof/canonical_fleet.py`, `freight_canonical*.py`, package `canonical*.nut`; `docs/capacity-experiment.md` |

## D/milestone-chain components (handoff addendum records)

| Component | Path | Notes |
|---|---|---|
| Terrain clearing contract + package | `app/simulation/openttd/terrain_clearing.py`, `terrain_clearing_package/{info,main}.nut` | D1/D2; only mutation command is `GSTile.DemolishTile` in company mode; static test forbids other commands |
| Clearing planner candidates | `app/planning/p08_clearing.py` | Census-evidence-bound, `PLANNING_ONLY` |
| Bounded terraform planning | `app/planning/p08_terrain.py` (+ hook in `p08_road.py`) | E10: typed budgets, planning-only proposals; insight into `NO_BOUNDED_CORRIDOR` branches |
| Terraform native execution | `app/simulation/openttd/proof/terrain_terraform_native.py` | E18; one-shot candidate machinery reusing proven ceremony |
| Corridor construction contract | `app/simulation/openttd/corridor_construction.py` | Wire contract v4 (E20); 19 planned exchanges |
| Corridor GameScript | `app/simulation/openttd/d4_corridor_package/main.nut`, `info.nut` | `NetworkFreightProof extends D4CorridorProof` |
| Corridor native runner | `app/simulation/openttd/proof/corridor_construction_native.py` | D4 execution entry (`run <candidate-dir>`) |
| Tile classification (schema-2) | `app/simulation/openttd/tile_classification.py`, `terrain_classification.nut`, `terrain_classification_bridge.py` | E11/E12; receipt/exchange/sweep + classification plan |
| Classification staging/execution | `app/simulation/openttd/proof/classification_execution.py`, `classification_capture.py`, `world_correspondence.py` | E13/E15; health vocabulary, AI staging, fail-closed capture runner |
| V1/V2 semantic reconciliation | `app/simulation/openttd/v2_semantic_reconciliation.py` (untracked) | [[05-Planning/Blockers]] |
| Native tile classification assessment | `app/planning/p08_terrain.py` (`SegmentClass`, `classify_segment`, `assess_world_feasibility`, `FeasibilityDiagnosis`), `app/planning/construction_readiness.py` | E11 |
| Receipt/manifest verification | proof/ modules incl. `attempt.py`, plus artifact manifests (`artifact-manifest.sha256`) per attempt dir | [[04-Evidence/Evidence Preservation]] |

## Repository layout (top level)

```text
app/planning/                          typed contracts, P08 candidates, P05 optimizer
app/simulation/openttd/                transport, observation and delivery verification
app/simulation/openttd/freight_delivery_package/ native freight GameScript
app/simulation/openttd/proof/           isolated preparation, launch and receipt replay
app/experiments/                       historical batch/live experiment CLI and persistence
tests/                                controlled verification and opt-in native tests
artifacts/                            RETAINED/GIT-IGNORED native evidence and tools
docs/                                 contracts, proof reports, limitations, specs
docs/handoff/<date>/                  dated handoff snapshots and milestone records
examples/openttd-demo/                public demo guide
prototype/                            retained historical prototype
```

`artifacts/` is ignored by Git and may be absent on another machine — absence means
**UNKNOWN**, never a reason to regenerate historical evidence ([[04-Evidence/Evidence Preservation]]).

## Related

[[03-Engineering/Source Code Map]] (expanded tree + GameScript packages) ·
[[01-Architecture/Data Flow]] · [[07-Reference/Important Paths]]
