# P08 V2 snapshot readiness — offline strategy-A assessment

Date: 2026-10-18. Policy: `p08-v2-snapshot-planning/1`. Module:
`app/planning/p08_v2_snapshot.py` (untracked, additive; no historical file
modified). Tests: `tests/test_p08_v2_snapshot.py` (13, all passing).
Derived artifact:
`artifacts/experiments/v2-snapshot-p08-readiness/snapshot-assessment-report.json`
(byte-stable; full-report pinned by test).

## Question answered

Whether the retained native Tile Classification V2 census (90 verified
single-instant pages, economy days 712224–712226, 450 tiles over region
(170,171,15,30)) can serve as an independent, snapshot-scoped input for the
existing P08 bounded feasibility assessment **without fusing temporally
incompatible V1 observations** (historical projection capture: days
712285–712291), and without touching the sealed
`SOURCE_SAVE_FUSION … REJECTED` verdict.

## Verdict: strategy A is defensible for P08 feasibility (offline)

Strategy A (V2 snapshot-scoped planning) is fully justified for the P08
feasibility question; strategy B (paired native capture) remains the
separately-authorized route for full V1/V2 correspondence fusion only.

## Evidence completeness (all verified offline, fail-closed)

1. World identity and source-save provenance: sealed
   `save_binding_sha256 = f9ae7dcb…` pinned and asserted; census session
   welcome = retained welcome (seed 17, revision 15.3, 256×256).
2. Tile identity/coverage: 450/450 census tiles across receipt-bound
   re-parsed pages; region rectangle verified; duplicate/out-of-region
   tiles rejected.
3. Terrain: per-tile elevation + slope from the census; geometry was
   already proven stable across the 61-day V1/V2 spans.
4. Native classification/occupancy: 15-bit masks; native `TileFact`
   projection disagrees with the census mask on **0** tiles.
5. Industry footprints: industry 0 → 6 site tiles; industry 1 → 6 site
   tiles; recomputed radius-3 catchments equal the historical
   `industry_covered` capture exactly (40+40) — independent confirmation
   of site stability.
6. Ownership: all census tiles owner `-1` (unowned).
7. Route-planning fields: all present; production quantities are *not*
   re-observed (recorded as zero, declared not-consumed; delivery
   capability is an industry-specification constant).
8. Temporal consistency: the multi-day window is NOT claimed
   same-instant; per-page single-instant provenance is enforced
   (`date_before == date_after` per page).

## Strategy comparison

- Strategy A (implemented): census-only planning document; historical V1
  used only for configuration identity reuse (same staged save) and as
  endpoint set definitions re-validated at the census instant.
- Strategy B (specified, not executed): a same-session paired V1-facts +
  V2-classification capture is the only route to a satisfiable sealed
  fusion; a six-tile recapture can never establish it (the retained
  capture instant is immutable, so a future six-tile read is still a
  different instant). `SAME_SESSION_CENSUS` scheduling stays review-only.

## P08 feasibility result (derived, planning-only)

- Primary (capability+geometry endpoints, 31 pickups / 32 deliveries):
  `TERRAIN_MODIFICATION_REQUIRED` — 22-tile corridor
  (`ROAD_BUILDABLE 17, SUPPORTED_CLEARING 2, TERRAIN_MODIFICATION 3`),
  421 expansions, no budget exhaustion. The historical
  `INCOMPLETE_TILE_CLASSIFICATION` (24-tile corridor only through
  unknown-class tiles) is resolved: the 19 historically unknown sloped
  clear tiles are natively buildable, so the corridor lies entirely in
  supported construction classes.
- Endpoint variant B (historical quantity-gated endpoint sets re-validated
  at the census instant, 31/20): also `TERRAIN_MODIFICATION_REQUIRED`
  (24-tile corridor: 20/2/2). Verdict independent of endpoint derivation.
- `plan_bounded_levelling` now produces a bounded `TerrainProposal`
  (target height 2, corridor 24, 18 ops, 2 cleared tiles; cost `None`;
  `native_execution = UNSUPPORTED_PENDING_SEPARATE_VALIDATION`) — the
  earlier `NO_CONNECTED_LEVELED_CORRIDOR` fence opened under native
  semantics because the 19 sloped tiles leave the forbidden region.
- Robustness: 217 bounded mechanism perturbations (the 6 sealed temporal
  alternates + every single-tree death (52) + tree spread onto each clear
  neighbor (149) + counterfactual rough-tree co-occurrence (10)) leave
  the verdict and corridor **unchanged** ⇒ `ROBUST`. The six measured
  V1/V2 alternates are used as probe states only, never planning input,
  and the probe delta is asserted tree/rough-only (fail-closed).

## Semantics preserved

- The 77 accepted definitional transformations (Vacant-vs-native-IsBuildable)
  are re-established by the gate on every build; stop viability equals the
  sealed Vacant projection on all 450 tiles (`vac_semantic_divergent_tiles
  = 0`).
- Fusion rejection is demonstrated as a negative control: retained facts +
  census overlay → 83 `UNKNOWN_OCCUPANCY`, `INCOMPLETE_TILE_CLASSIFICATION`
  (the sealed gate's behavior reproduced unchanged), while the snapshot
  document contains zero unknowns with zero projection disagreements.
- Sealed verdict untouched; no native launch, no connection, no commit.

## Tests, quality, review

- 13 focused tests: gate reproduction (77/6/0/0 + manifest 198 + sealed
  REJECTED intact), coverage/page heredity, native predicate semantics,
  save-identity pin, temporal bracket ≠ retained bracket, six measured
  alternates invariance, 77-transform preservation, V1-fusion rejection,
  missing-page fail-closed rejection, full-report byte pin, planning-only
  levelling, quantity-gate separation, historical immutability (rglob
  hash watch).
- ruff check/format clean; compileall; `git diff --check` clean; report
  byte-identical across independent runs.
- One independent review: PASS WITH NOTES; all 7 MINOR findings and the
  actionable NOTEs closed (road-OR census gate, temporal probe delta
  assertion, honest rough-spread comment, farm/rock spread exclusion,
  corridor recorded per case, derived page count, full-report pin,
  catchment map-edge bounds, PlanningFactError for missing industry
  sites, revalidated-skip note, `flag_bit` naming, vac-equivalence proof
  moved before assessments).

## Residuals (explicitly not claimed)

- Town-driven house growth inside the ≤2-day window is unmeasured (no
  town-adjacency data offline; region shows zero house/station tiles).
- Production quantities/OPEX/ROI and native constructability remain
  out of scope (planning-only).
- The sealed historical fusion verdict is unaffected; nothing here
  claims historical fusion passed.

## Status

`V2 SNAPSHOT P08 READINESS VERIFIED OFFLINE`
