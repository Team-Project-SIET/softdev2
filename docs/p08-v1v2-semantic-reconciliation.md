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

**Update 2026-10-25 (delegated decision exercised — ADR-012, Option B):** the
policy path was selected and implemented as a separate derived layer
(`CensusAuthorityDecision` / `apply_census_authority` in
`app/simulation/openttd/v2_semantic_reconciliation.py`; ADR:
`docs/handoff/2026-10-24/adr-012-six-temporal-tiles-census-authority.md`;
14/14 focused tests PASS). For the six tiles the save-instant census is
authoritative for their tree-lifecycle deltas — **planning evidence only**.
Nothing is relabeled: the base ledger keeps `TEMPORAL_SECOND_INSTANT`, the
sealed verdicts are unchanged, the fusion gate stays closed, P08 remains
`INCOMPLETE_TILE_CLASSIFICATION` (19 retained-UNKNOWN tiles remain outside
the policy), and no native evidence was collected. Option A is retained as an
optional conditional future delta-confirmation run; it is never assumed.

**Update 2026-10-25 (rebinding pass implemented — PREPARED, no native proof):**
the separately reviewed rebinding step now exists:
`rebind_p08_policy` re-derives the policy report from the sealed inputs and
byte-compares it, accepts only the exact six-tile temporal scope with verbatim
rows, and refuses stale/edited/out-of-scope/refusal-carrying reports
(`tests/test_p08_policy_rebinding.py`, 24/24 PASS). The snapshot adapter
consumes it via `build_v2_snapshot_assessment(..., policy_report=...)` /
`--policy-report`, adding a `policy_rebinding` section without changing the
planning input or the pinned base assessment. Derived evidence:
`artifacts/experiments/v1v2-semantic-reconciliation/p08-policy-rebinding-report.json`.
At that point the computed binding was still **not allowed**: the 19
retained-UNKNOWN (`UNKNOWN_OCCUPANCY`) tiles were outside ADR-012 and no
admissible evidence resolved them, and the sealed fusion verdict (ADR-010) is
immutable. The rebinding removed the "separate reviewed step not implemented"
blocker only. The later ADR-013 update below supersedes this for the derived
P08 planning binding.

**Update 2026-10-25 (19-tile root-cause census — diagnosis only):**
`diagnose_unknown_occupancy` groups the 19 retained `UNKNOWN_OCCUPANCY` tiles
as one definitional group (`DEFINITIONAL_VACANT_VS_NATIVE_ISBUILDABLE_SLOPED_CLEAR`):
all are census `CLEAR`, unowned, non-flat, and already `SEMANTIC_RECONCILED`
on exactly the `buildable` transformation. This is not a resolution: the 19
stay UNKNOWN, the binding stays not-allowed, and adopting native
`IsBuildable` semantics for P08 segmentation needs separate reviewed
authorization (or fresh same-instant evidence for exactly those tiles).
Evidence: `artifacts/experiments/v1v2-semantic-reconciliation/p08-unknown-occupancy-diagnosis.json`
(sha256 `66ed07cc…7e459`). The fusion gate remains closed independently by
the six temporal tiles; it is not on the census-only snapshot assessment
path.

**Update 2026-10-25 (ADR-013 accepted — combined P08 rebinding pass):** the
operator authorized and accepted ADR-013 for exactly the 19 definitional
retained-UNKNOWN tiles. The derived layer adopts native `GSTile.IsBuildable`
semantics for that exact scope and maps the tiles to `TERRAIN_MODIFICATION`
only when every ADR-013 evidence gate passes. Implementation:
`NativeIsBuildableDecision`, `apply_native_isbuildable_policy`,
`NativeIsBuildablePolicyApplication`, `P08NativeIsBuildableRebinding` and
`rebind_p08_native_isbuildable`; CLI `--apply-adr-013` / `--rebind-p08`.
The snapshot adapter consumes the optional report via
`build_v2_snapshot_assessment(..., native_isbuildable_report=...)` /
`--native-isbuildable-report`, which requires the ADR-012 report.

- Derived segmentation: **339 ROAD_BUILDABLE / 63 SUPPORTED_CLEARING /
  29 UNSUPPORTED_CONSTRUCTION / 19 TERRAIN_MODIFICATION / 0 UNKNOWN**.
- The base ledger, its bytes, sealed verdicts and all original evidence remain
  unchanged; the 19 stay `UNKNOWN_OCCUPANCY` there by design.
- The separate combined rebinding verifies both ADR-012 and ADR-013 reports
  and computes `p08_binding.allowed: true` for **P08 planning classification
  only**, with zero blockers. It records `p08_complete: false`, and the
  fusion gate remains **CLOSED** (sealed `SOURCE_SAVE_FUSION` verdict
  immutable, not relabeled, not opened).
- Artifacts:
  `native-isbuildable-policy-report.json` sha256
  `7616f626…a3a65d` and
  `p08-native-isbuildable-rebinding-report.json` sha256
  `079fce64…4adee62`. Existing
  `reconciliation-report.json` (`c1cfa970…2acf34d`),
  `census-authority-policy-report.json` (`221ce926…0faf28d`),
  `p08-policy-rebinding-report.json` (`c9d11d41…107ed0`) and
  `p08-unknown-occupancy-diagnosis.json` (`66ed07cc…7e459`) were verified
  byte-identical after activation.
- Validation: focused `tests/test_p08_policy_rebinding.py` 41/41; broader
  reconciliation/snapshot group 83/83; feasibility classification 24/24;
  Ruff clean. The default pinned snapshot assessment remains byte-identical;
  policy sections appear only when reports are explicitly supplied.
