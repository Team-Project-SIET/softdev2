---
title: "Testing Strategy"
type: engineering
status: current
updated: 2026-10-22
tags:
  - openttd
  - engineering
  - testing
---

# Testing Strategy

**Sources:** [[99-Source-Documents/REPRODUCE]], [[99-Source-Documents/README]]
"Development checks" + "Planning integration boundary", and the per-record test counts in
[[99-Source-Documents/EVIDENCE_INDEX]]. Test runs **do not launch OpenTTD by default**;
real integration tests are opt-in and separate from authorized proof runs.

## Principles

1. Controlled verification first: controlled peers/VM, retained offline replay, Python
   solver workers; native seams blocked. Never silently replace native evidence with
   synthetic fixtures.
2. Suites are scoped and dated. "Prior extension suite counts and VM results are
   historical, not rerun claims" (REPRODUCE). Full-tree test/lint/type health remains
   UNKNOWN beyond recorded checks.
3. A file-passing suite never upgrades a project status ([[07-Reference/Status Definitions]]).

## Environment setup

```bash
uv python install 3.14
uv sync --locked --group dev        # lockfile + dev group required for controlled GameScript tests
```

Python 3.14+ required; `pyproject.toml` + `uv.lock` are dependency authority. Some tests
require ignored retained evidence and pinned external assets — a fresh clone without them
may fail (that is honest behavior, not a bug to fix by faking).

## Focused controlled regression (handoff standard)

```bash
.venv/bin/pytest -q tests/test_demo_random.py tests/test_demo_random_native.py \
  tests/test_random_distance.py tests/test_random_capture_schema.py \
  tests/test_random_capture_budgets.py tests/test_demo_operations.py \
  tests/test_demo_smoke_preflight.py tests/test_openttd_demo.py
git diff --check
```

## Engine-area suites (from records; run the subsets relevant to your change)

- Freight core: `tests/test_freight_delivery.py` `tests/test_freight_planning.py`
- Network / planner: `test_freight_network.py`, `test_planning_optimizer.py`,
  `test_native_freight_network.py`, `test_p08_controlled_e2e.py`
- Random world: `test_random_distance.py`, `test_random_capture_schema.py`,
  `test_random_capture_budgets.py`
- Classification chain: `test_tile_classification.py`, `test_tile_classification_receipt.py`,
  `test_classification_capture.py`, `test_classification_execution.py`,
  `test_gamescript_transport_classification.py`, `test_p08_classification_workflow.py`,
  `test_terrain_classification_preparation.py`, `test_p08_feasibility_classification.py`,
  `test_world_correspondence.py`, `test_v2_semantic_reconciliation.py`
- D-chain: `test_terrain_clearing.py`, `test_terrain_terraform_native.py`,
  `test_corridor_construction.py`, `test_corridor_construction_native.py`, `test_p08_bounded_terrain.py`
- Opt-in native Postgres: `tests/test_freight_history_postgres.py --run-postgres`
  (never used for an offline handoff).

## Quality gates (offline)

```bash
uv run --no-sync ruff check app/simulation/openttd/freight_delivery.py ...   # scoped
uv run --no-sync ruff format --check ...
uvx ty check ...          # typechecking tooling recorded UNAVAILABLE in several recent offline runs:
                          # mypy not installed; `ty` configured but not installed.
uv run --no-sync python -m compileall app   # recorded clean in recent offline records
git diff --check
```

Recorded historical suite outcomes (per their own records; not fresh reruns): e.g. P06
51 focused + 918 controlled; P07 990 controlled; E7 suites 90+297+216 (11 skipped); E9
17 new + 124 P08 + 18 audit; E15 35 focused + 84 p08/dispatch + 90 REPRODUCE; classification
suite list in REPRODUCE addendum "151 passed"; D4 21+26 PASS. These are per-record facts.

## What tests cannot establish

- Native runtime behavior — only consumed one-shot attempts can (with receipts).
- Station catchment, cargo availability, traffic deadlock freedom, travel time, delivery
  throughput, profitability (explicit P06 limits).
- Correspondence between fresh captures and historical evidence (fusion gates decide,
  not reviewers) — E16 REJECTED verdict stands until separately scoped reconciliation.

## Known baseline failures (keep visible, do not "fix" silently)

- Two protected-authority tests + `test_industry_production_proof::test_architecture_authority_unchanged`
  fail because retained authority manifests pin repo-root CONTEXT.md bytes captured
  2026-10-08 (sha256 `b94b966…`); commit `bdbec43` moved the file past the capture. Any
  resolution (pin-repair or re-capture) is a separate, explicitly authorized decision
  ([[04-Evidence/Evidence Preservation]]).
