---
title: "Glossary"
type: reference
status: current
updated: 2026-10-22
tags:
  - openttd
  - reference
  - glossary
---

# Glossary

Project-specific vocabulary. Sources: [[99-Source-Documents/CONTEXT]] (shared language,
§ definitions), [[99-Source-Documents/AI_HANDOFF]] ("Shared language for continuation"),
records E9–E20.

## Shared language (verbatim-tier definitions from the handoff/CONTEXT addendum)

- **Canonical constructed fleet** — the common paused state containing the three original
  services and three stopped empty vehicles, before intervention or dispatch. A matching
  DTO alone is **not** native state correspondence.
- **Matched arm** — a separately authorized experimental branch of that same verified
  canonical state. Historical Attempt 19 is a contextual baseline, **not** matched arm A.
- **Native terminal result** — the immutable result of a consumed game-process attempt.
  Separate derived offline recovery does not change that result.
- **Prepared qualification** — frozen inputs and controlled checks awaiting separate
  native authorization. It is not an accepted save, reload, or experiment.

## Status vocabulary

[[07-Reference/Status Definitions]]: VERIFIED / PROVEN / CONTROLLED / PREPARED / PARTIAL /
FAILED / UNKNOWN (frontmatter `status` field is a different, vault-hygiene concept).

## Architecture and process terms

| Term | Meaning |
|---|---|
| P01–P08 | Architecture stations: contracts → schema/serialization → transport (13.4 thin AI) → admin observation → CP-SAT optimizer → executor → plan-attributed evaluation → bounded world facts/road candidates. [[01-Architecture/Planning and Execution Boundary]] |
| D1…D4 | Native-construction milestone chain reusing one ceremony: D1 contract mapping, D2 tile clearing, D3 bounded levelling, D4 corridor (roads/stops/depot) |
| AdminPort | OpenTTD's external admin socket (TCP); the project uses one encrypted X25519 session per attempt |
| Bridge GameScript / `RoadFreightProof` | Thin on-engine executor package; identity announced by `info.nut`; executes under `GSCompanyMode` |
| `GSEventAdminPort` / `GSAdmin.Send` | Engine-side event for incoming AdminPort JSON / GameScript-side send (≤1450 B JSON) |
| Correlated ACK | Response matched to its request by stable `request_id` (+ keys like `(request_id, region, cursor)` for schema-2) |
| One-shot claim | The single authorization ledger entry that, once consumed, marks an attempt identity as final |
| One launch / one connection | Environment honesty budget: exactly one process + one encrypted session per attempt, zero retries/reconnects |
| Prepared save / source save | Frozen native save bound into a candidate; its digest is verified at preflight; `PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD` chains candidates |
| Qualified observation (`WorldPlanningObservation`) | Same-run qualified world facts (structure + production, coherent economy-month window, stability checks) |
| Supplemental facts | Additional native facts captured in-session (terrain, coverage, engines, costs, funding) |
| TileFact projection | The retained historical per-tile fact model (schema-1) produced during planning capture; the comparison anchor of the V2 census |
| Tile Classification V2 | Schema-2 15-predicate single-instant census (450 tiles/90 pages); capture succeeded; fusion verdict REJECTED |
| `SOURCE_SAVE_FUSION` | The correspondence gate deciding whether a fresh census may be fused into the retained projection — currently `REJECTED` (83 disagreements) |
| Segment classes | Five deterministic corridor-segment classifications (e.g. `ROAD_BUILDABLE`, `SUPPORTED_CLEARING`, `UNSUPPORTED`); conflicts downgrade to UNKNOWN |
| `INCOMPLETE_TILE_CLASSIFICATION` | P08 feasibility diagnosis when a corridor exists only through tiles of unknown class |
| `NO_BOUNDED_CORRIDOR` / `NO_CONNECTED_LEVELED_CORRIDOR` | Feasibility verdicts: no road corridor within supported search; no corridor even with supported levelling |
| Reachability oracle (`corridor_reachability`) | Bounded terrain-aware search proving disconnectivity (E9) |
| Receipt / receipt replay | Machine-verifiable per-attempt ledger artifacts; offline replay re-derives them exactly (fail-closed) |
| `PRELAUNCH.json` / seal | Staged candidate's frozen prelaunch record (SHA-256 sealed) |
| Artifact manifest | Per-attempt `artifact-manifest.sha256` re-verified by byte after any inspection |
| Economy date / script tick / wall-clock | Three separate clocks — never infer one from another (README Attempt 15 lesson) |
| `after-diagnostic.sav` | Distinct diagnostic save retained beside the authoritative `after.sav`; never substituted |
| Fixed Scenario / Random World | The two product worlds; fixed = stable default; random = 256×256 explicit-seed bounded mode |
| `random-rectangle-512-v1` | The 512-tile fully-observed capture profile for random relationships ([[01-Architecture/Data Flow]]) |
| Freight compiler | Python staging of a validated `ExecutionPlan` service into checked native intents |
| Prepare / preflight / claim / run / verify | The proof-runner lifecycle verbs (`app.simulation.openttd.proof.freight_delivery`) |
| Independent readback | A fresh native observation after a mutation, distinct from the command's own return |
| Authority manifests | Retained freeze records pinning repo-root CONTEXT.md bytes (2026-10-08) — open conflict, see preservation |
