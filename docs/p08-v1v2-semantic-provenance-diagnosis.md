# P08 Tile Classification V2 — V1/V2 semantic provenance diagnosis (83 disagreements)

**Date:** 2026-10-18 (offline diagnosis only; no launch, no AdminPort, no policy/implementation changes).
**Scope:** root-cause provenance of the 83 `PROJECTED_FLAGS_DIFFER` disagreements recorded by
`artifacts/demos/classification-exec-seed17-3a8f9e46/` (verdict `SOURCE_SAVE_FUSION REJECTED`).
The captured rejection itself is unchanged and remains valid as-recorded; this analysis explains *why*
the two records differ and classifies every tile evidence-exactly.

## Evidence identity

| Record | Instant | Identity |
| --- | --- | --- |
| Retained V1 facts | economy dates **712285–712291** | `artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json`, sha256 `9e4c5c4225b697312230deae40989de643bcdd79db1063cf6eda9fa365d8bb6e` |
| Fresh V2 census | economy date **712224** (save instant) | `artifacts/demos/classification-exec-seed17-3a8f9e46/`, composition `3a8f9e46…`, 90 pages / 450 tiles |

**Direction matters:** the fresh census (replay of the source save) is observed at the *earlier*
instant (712224); the retained TileFacts were captured later in the demo session (712285–712291,
i.e. 61–67 in-game days afterwards, spread over the capture window). The two records are not
simultaneous snapshots of the same corpus.

## Producer lineage of every compared field

Both records are native reads of the same OpenTTD 15.3 binary (same GS API, same predicate calls):

- **V2 mask** (`app/simulation/openttd/terrain_classification.nut`, schema 2, one bit per predicate):
  `buildable = GSTile.IsBuildable(tile)`; `water/coast/tree/farm/rock/rough/rail/water_transport`
  via the direct GSTile calls; `road_tile = GSRoad.IsRoadTile(tile)`,
  `road_track = GSTile.HasTransportType(t, TRANSPORT_ROAD)`, `road_src_type`, `airport =
  GSAirport.IsAirportTile(tile)`, `house`, `station`; per-tile also min-height, slope, industry, owner.
- **V1 retained facts** were **not** produced by `terrain_bridge.nut`/`tile_facts.py`; they were
  produced by `capture_planning_facts()` (`app/simulation/openttd/freight_runtime_planning.py`) via the
  demo planner bridge `freight_delivery_package/planner.nut` (`kind="tile"`), whose field 3 (named
  `buildable` in the `names` tuple of `capture_planning_facts`) is:

  ```squirrel
  /* freight_delivery_package/infrastructure.nut */
  function Vacant(t) {
      return GSTile.IsBuildable(t) && GSTile.GetSlope(t) == 0 &&
          GSTile.GetOwner(t) == GSCompany.COMPANY_INVALID &&
          !GSTile.IsWaterTile(t) && !GSTile.IsCoastTile(t) &&
          !GSTile.HasTreeOnTile(t) && !GSTile.IsFarmTile(t) &&
          !GSTile.IsRockTile(t) && !GSTile.IsRoughTile(t) &&
          !GSTile.HasTransportType(t, GSTile.TRANSPORT_ROAD) &&
          !GSTile.HasTransportType(t, GSTile.TRANSPORT_RAIL) &&
          !GSTile.HasTransportType(t, GSTile.TRANSPORT_WATER) &&
          !GSTile.HasTransportType(t, GSTile.TRANSPORT_AIR);
  }
  ```

So the retained `TileFact.buildable` is the **planner's "directly placeable right now" predicate**
(flat + unowned + bare ground), *not* the raw native `IsBuildable`. Every other V1 field shares its
V2 counterpart's exact call (`road` retains `IsRoadTile` semantics; `air_transport` used
`HasTransportType(TRANSPORT_AIR)` and equaled the V2 airport bit on all 450 tiles in this corpus).

## OpenTTD 15.3 source verification

From the 15.3 tag (`src/script/api/script_tile.cpp`):

```cpp
/* static */ bool ScriptTile::IsBuildable(TileIndex tile)
{
    switch (::GetTileType(tile)) {
        default: return false;
        case MP_CLEAR: return true;
        case MP_TREES: return true;
        case MP_WATER: return IsCoast(tile);
        case MP_ROAD: /* tram/depot/crossing excluded; single-bit normal road of town or own company */ ...
    }
}
```

Native `IsBuildable()` is therefore **true for `MP_TREES` and for every `MP_CLEAR` ground type
(grass, rough, fields, rocks)** — exactly what the fresh census observed (52 tree+buildable and
10 rough+buildable tiles). This is a genuine, source-verified semantic difference, not an API quirk of
the runtime.

Tree lifecycle (`src/tree_cmd.cpp`, `TileLoop_Trees`, growth/spread active in this world — confirmed
empirically by the six transitions below):

- Grown trees **spread** (`AddTreeCount` on the tile, or `PlantTreesOnTile` on a CAN-plant neighbor —
  grass and rough are CAN-plant; fields/rocks are not).
- In the `Dead` stage, a single-tree tile converts back to `MP_CLEAR` per its stored tree ground:
  `TREE_GROUND_GRASS → MakeClear(CLEAR_GRASS,…)` and, notably, **`TREE_GROUND_ROUGH →
  MakeClear(CLEAR_ROUGH, 3)`** — a dying tree-on-rough-ground leaves *bare rough ground*.
- `OnTick_Trees` periodically `PlantRandomTree()`s on plantable clear tiles.

## Replay result (offline, read-only)

Applying the exact V1 producer formulas to the fresh V2 bits (+ slope + owner −1 sentinel)
reproduces the retained V1 boolean tuples **exactly on 444/450 tiles**. Per-field residuals remain
only on **6 tiles**, all temporal:

| Tile | x, y | Retained (later instant) | Fresh census (save instant) | Verified mechanism (`tree_cmd.cpp`) |
| --- | --- | --- | --- | --- |
| 43951 | 175,171 | tree | buildable (bare clear) | tree spread/planted onto bare grass between the instants |
| 47286 | 182,184 | tree | buildable | same |
| 47288 | 184,184 | rough (no tree) | buildable+tree | tree-on-rough-ground died → `MakeClear(CLEAR_ROUGH, 3)` |
| 48042 | 170,187 | rough (no tree) | buildable+tree | same |
| 48309 | 181,188 | rough (no tree) | buildable+tree | same |
| 51378 | 178,200 | buildable (vacant grass) | buildable+tree | single grass-tree died → vacant clear |

Slope, min-height, industry id, and owner agree on all 450 tiles; no other bit differs anywhere.

## Complete per-field and per-tile accounting of the original 83

Raw gate comparison (what `projection_disagrees()` compares: V2 bit 0 suppressed by house/station
vs `fact.buildable`; road OR-of-3 vs `fact.road`; direct bits): **83 tiles** — buildable 82, tree 6,
rough 3, all other fields 0 — exactly the sealed verdict list.

- **77 tiles — proven semantic difference, zero contradiction.** They differ *only* in
  `buildable`: retained says `Vacant= false` (tree/rough/water-side/owned-x exclusion) while the
  fresh key says `IsBuildable=true`. All ten non-buildable fields agree bit-for-bit, and the exact
  `Vacant` reproduction (item above) proves the retained `buildable` was produced by the same-world
  `Vacant` semantics. Fresh-side patterns: `buildable+tree` ×52, `buildable` ×21, `buildable+rough`
  ×10 (with the six temporal tiles inside the latter groups as counted above).
- **6 tiles — proven temporal in-world evolution.** Same predicates both sides ⇒ these are state
  changes between the two instants, not semantics. Trees spread/died (including the
  rough-ground tree→bare-rough transition) during the 61–67 economy days between the save instant
  and the retained capture window.
- **0 genuine contradictions.** The retained record is also internally Vacant-consistent (0
  violations across 450 tiles).

The five tiles where the raw `buildable` count (82) exceeds semantic+temporal buildable diffs comes
out as 77 + 5; tile 51378 is the one 83-member whose raw `buildable` agreed while `tree` differed.

## Historical P08 classes of the 83 (unchanged assessment)

Replaying the retained facts through the historical classifier (`_legacy_segment`,
`app/planning/p08_terrain.py`): **19 UNKNOWN_OCCUPANCY** ("projection-dropped-occupancy-class";
all-false retained tuples) + **63 SUPPORTED_CLEARING** ("projected-clearing-ground") +
**1 ROAD_BUILDABLE** ("vacant-flat-clear" = tile 51378) = 83 ✓.

Additions cross-checking the same corpus:

- The retained all-false corpus is 31 tiles: 12 are industry-site tiles (fresh `ind=0/1`, hence no
  P08 disagreement; they class UNSUPPORTED through `industry_id`), and the remaining **19 are the
  historically UNKNOWN set** — every one of them observes **CLEAR** in the fresh census with
  owner −1 and **slope ≠ 0 for all 19** (the industry sites are the flat ones).
- Consequence (informational, not applied): if a future fused record asserts the native-`IsBuildable`
  semantics for the 19, the unchanged legacy classifier maps them to
  `TERRAIN_MODIFICATION` ("cleared-shape-needs-corner-correction", sloped) rather than
  `ROAD_BUILDABLE`; under retained-Vacant semantics they would remain UNKNOWN. The choice of
  `buildable` semantics carried into any fused record therefore directly changes the P08 feasibility
  result — it must be an explicit, versioned policy decision, not an incidental one.

## Verified root cause

1. **Definitional (77 tiles):** the retained `TileFact.buildable` was produced by
   `planner.nut`'s `Vacant()` (flat, unowned, bare-ground planner semantics), while the V2 census
   bit is `GSTile.IsBuildable()` (native, tree/rough/ground-type-inclusive). The strict coherence
   gate compares the raw native bits against the producer-projected facts and therefore reports
   83 disagreements — 77 of them are schema-semantics differences that are fully explainable and
   reproducible (444/450 exact V1-tuple reconstruction).
2. **Temporal (6 tiles):** world evolution between the two capture instants (tree spread and tree
   death, including tree-on-rough → bare rough ground), verified against OpenTTD 15.3
   `tree_cmd.cpp`. The fresh census instant is 61–67 in-game days *earlier* than the retained facts.
3. The original `SOURCE_SAVE_FUSION REJECTED` verdict, the retained `INCOMPLETE_TILE_CLASSIFICATION`
   result, and the historical 339/63/19/29 segmentation remain valid and unchanged: the gate's raw
   strictness is correct behavior for an unfused-schema comparison, and no contradictory
   observation was discarded (all 450 raw tuples and all 6 temporal deltas are recorded in the
   provenance ledger).

## Unresolved questions

1. Which `buildable` semantics the fused record must carry (native `IsBuildable` vs planner
   `Vacant`) — this is P08 outcome-decisive (TERRAIN_MODIFICATION vs UNKNOWN for 19 sloped
   previously-UNKNOWN tiles) and needs an explicit versioned policy decision.
2. How the 6 temporal deltas should be treated (fresh-observation-authoritative for the save
   instant vs retained-record-authoritative for its later instant vs unresolved/second-observation).
3. Whether the P08 feasibility replay should be re-run on a fused record under a new reviewed
   candidate (out of scope for this diagnosis step).

## Smallest justified repair (proposal — NOT implemented)

Add a separate versioned semantic-correspondence rule (new derived layer; the strict raw gate and
the sealed verdict stay untouched):

- Compare `fact.buildable` against the **V1 producer semantics reconstructed from the V2 mask**
  (`Vacant(bits): bit0 ∧ ¬(tree ∨ farm ∨ rock ∨ rough ∨ water ∨ coast ∨ road_tile ∨ road_track ∨
  rail ∨ water_transport ∨ house ∨ station) ∧ slope==0 ∧ owner==−1`) while leaving every other
  field compared bit-for-bit; record accepted disagreements as
  `SEMANTIC_V1_VACANT_VS_NATIVE_ISBUILDABLE`.
- Route any residual non-buildable field mismatch (`tree/farm/rock/rough/…` — same API both
  producers, therefore state-only) into an explicit `TEMPORAL_SECOND_INSTANT` class, never silently
  merged; require an explicit policy choice for those 6 tiles in a new reviewed candidate.
- World identity, geometry, industry identity, and occupancy safety checks remain mandatory
  preconditions for any acceptance.

Artifact produced in this step:
`artifacts/experiments/v1v2-provenance-ledger-diagnostic.json` (derived ledger; no historical
artifact touched).
