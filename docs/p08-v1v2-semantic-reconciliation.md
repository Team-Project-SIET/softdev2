# P08 V1/V2 semantic correspondence — policy implementation and offline replay

**Date:** 2026-10-18. Offline only: no OpenTTD launch, no AdminPort connection, no
historical evidence mutation, no commit. This record belongs to the semantic
reconciliation work and follows
[the provenance diagnosis](p08-v1v2-semantic-provenance-diagnosis.md), which
established the exact V1/V2 producer lineage behind the 83
`PROJECTED_FLAGS_DIFFER` disagreements of the sealed
`artifacts/demos/classification-exec-seed17-3a8f9e46/` census.

## Policy `vacant-projection-1`

Implemented in `app/simulation/openttd/v2_semantic_reconciliation.py` as a
derived, read-only reconciliation layer. The strict sealed coherence gate
(`tile_classification.projection_disagrees`) and the sealed native verdicts
(`TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT` / `SOURCE_SAVE_FUSION REJECTED`)
are untouched; reconciliation does not relabel them.

Concept mapping (fields compared as equivalent concepts, not as raw booleans):

| Retained V1 field | Producer concept | Fresh V2 concept | Rule |
| --- | --- | --- | --- |
| `buildable` | planner `Vacant(t)` (`planner.nut` → `infrastructure.nut`: flat + unowned + bare) | `GSTile.IsBuildable` bit (15.3: `MP_CLEAR`/`MP_TREES`/coast/own-plain-road) | rebuild `Vacant` from the schema-2 mask (`slope==0 ∧ owner==-1 ∧ ¬(excluded bits)`) and accept the recorded transformation `SEMANTIC_V1_VACANT_VS_NATIVE_ISBUILDABLE` when the rebuild matches the retained producer |
| `water/coast/tree/farm/rock/rough/rail/water_transport` | identical `GSTile` calls both sides | same bit | bit-for-bit; mismatch = `TEMPORAL_SECOND_INSTANT` (state difference), `GENUINE_CONTRADICTION` when the census instant falls inside the retained capture window |
| `road` | `GSRoad.IsRoadTile` both sides | `road_tile` bit (not the OR of `road_track`/`road_src_type`, which have no V1 counterpart) | bit-for-bit as above |
| `air_transport` | `GSTile.HasTransportType(TRANSPORT_AIR)` | `GSAirport.IsAirportTile` | distinct native predicates: equality observed corpus-wide only; any mismatch = `UNRESOLVED_DISTINCT_PREDICATE` (blocks binding verdicts, never reinterpreted) |

Any unexplained `buildable` residual with zero shared-predicate differences is
`GENUINE_CONTRADICTION`. Temporal (second-instant) tiles are never fused and
never reclassified; they keep the fusion gate closed.

## Offline replay (deterministic, 450 tiles)

`replay_retained_census(retained_facts, candidate_dir)` rebuilds the sealed
sweep from the candidate page payloads through the project's own code
(`TileClassificationRequest.parse` + receipt correlation + exchange validation
+ `TileClassificationSweep.record`), verifies the candidate's 198-entry frozen
artifact manifest in place, and asserts the rebuilt seal reproduces
`classification-completeness.json` (83 coherence failures, class counts,
unknown tiles, bound flag, region). Per-page provenance: each page is verified
single-instant; the census spans economy dates 712224–712226 versus the
retained capture window 712285–712291.

Derived report: `artifacts/experiments/v1v2-semantic-reconciliation/reconciliation-report.json`

- Raw gate: **83** disagreement tiles (byte-equal to the sealed list).
- **77** reconciled as definitional (`buildable` only; accepted per-tile
  transformation recorded); **0 genuine contradictions**; **0 unresolved**;
  **6** temporal second-instant tiles preserved separately:
  43951, 47286 (trees grew after the census instant), 47288, 48042, 48309
  (rough-ground trees died to bare rough ground), 51378 (grass tree died to
  vacant ground) — mechanism verified against OpenTTD 15.3 `tree_cmd.cpp`
  (`TileLoop_Trees` growth/death incl. `MakeClear(CLEAR_ROUGH, 3)`).
- Same-state: census window **not** inside the retained capture window ⇒ the
  same-state requirement is violated by the six tiles ⇒ fusion gate closed.
- Final derived verdict:
  **`SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`** (partial — semantics fully
  accounted, same-state provably not achieved).
- P08 binding: **not allowed**; the retained assessment stays
  **`INCOMPLETE_TILE_CLASSIFICATION`** with the historical
  339 ROAD_BUILDABLE + 63 SUPPORTED_CLEARING + 19 UNKNOWN + 29 UNSUPPORTED
  segmentation unchanged.
- Minimum additional evidence (recorded in the report): a bounded,
  separately-authorized same-instant native re-observation of exactly
  `[43951, 47286, 47288, 48042, 48309, 51378]`, and/or an explicit operator
  policy decision declaring the save-instant census authoritative for those
  tiles' tree-lifecycle deltas, sealed in a new reviewed candidate under a
  fresh authorization.

## Tests

`tests/test_v2_semantic_reconciliation.py` — 15 focused tests: Vacant versus
IsBuildable semantics; the accepted tree-tile transformation; genuine
contradiction rejection; distinct-predicate (air) blocking; temporal versus
contradiction attribution by same-state provenance; the exact 77/6/0/0
replay identities from the retained evidence (skip-if evidence absent);
manifest verification; sealed-completeness reproduction; read-only
immutability of the retained inputs and deterministic byte-stable
serialization; P08 gating; minimum-evidence naming; fixed-demo schema-1
shape compatibility.

Pre-existing baseline (`/tmp/opencode/baseline-failures.txt`, full-suite run
before any change) distinguishes documented failures from new regressions.

## Status

`SEMANTIC RECONCILIATION IMPLEMENTED AND OFFLINE VERIFIED` — with the
CORRESPONDENCE_ESTABLISHED path deliberately not reached: the six
second-instant tiles keep the fused P08 assessment unbound, and the next
step (fresh same-instant evidence or a policy decision under a new reviewed
candidate) is listed above.
