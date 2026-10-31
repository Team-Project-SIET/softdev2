"""Deterministic offline tests for the V2 census-reconciliation semantics.

These tests need no retained Seed 17 artifacts: they construct the exact tile
shapes the sealed census recorded and pin the expected dispositions. They do
not connect to OpenTTD, create, sign, claim or launch any candidate.

Phase 4 disposition pinned here:

- the 77 definitional ``PROJECTED_FLAGS_DIFFER`` rows (19 sloped ``CLEAR`` +
  48 static ``TREES`` + 10 static ``ROUGH``) are the retained ``Vacant`` versus
  native ``IsBuildable`` projection mismatch; they are accepted semantically
  and never rewritten;
- the six temporal rows (``43951, 47286, 47288, 48042, 48309, 51378``) are
  second-instant tree/rough lifecycle deltas; they are attributed to time and
  never repaired;
- the 19 retained-UNKNOWN rows stay ``UNKNOWN_OCCUPANCY`` in the base ledger;
  only the ADR-013 derived policy maps them, and only from a coherent
  same-instant native observation;
- the six A0 native survey census-vs-native deviations (``D5CE3-SURVEY-3`` on
  tiles ``50095, 50096, 50352, 50608``) reflect post-D3/D4 world mutations on
  the delivery terrace and are recorded as findings without replacing or
  fusing into the V2 census.
"""

from __future__ import annotations

import pytest

from app.planning.p08_terrain import SegmentClass, _legacy_segment, classify_segment
from app.planning.p08_v2_snapshot import (
    UNKNOWN_OCCUPANCY_ROOT_CAUSE,
    CensusTile,
    diagnose_unknown_occupancy,
)
from app.simulation.openttd.proof.corridor_terrain_survey_native import (
    compare_terrain_census_findings,
)
from app.simulation.openttd.proof.world_correspondence import (
    SAME_SESSION_MODE,
    SOURCE_SAVE_MODE,
    evaluate_correspondence,
)
from app.simulation.openttd.supplemental_planning_facts import (
    ContentSettings,
    FactSource,
    RandomCaptureRegion,
    RoadFacts,
    SupplementalPlanningFacts,
    TileFact,
)
from app.simulation.openttd.tile_classification import (
    WELCOME_IDENTITY_KEYS,
    TileClassificationSweep,
    flags_index,
    projection_disagrees,
)
from app.simulation.openttd.v2_semantic_reconciliation import (
    AUTHORITY_RESOLVED_OUTCOME,
    CONTRADICTION,
    NATIVE_ISBUILDABLE_BASE_COUNTS,
    NATIVE_ISBUILDABLE_CENSUS_INSTANT,
    NATIVE_ISBUILDABLE_DERIVED_CLASS,
    NATIVE_ISBUILDABLE_SCOPE_TILES,
    NATIVE_ISBUILDABLE_VERDICT,
    OWNER_UNOWNED_SENTINEL,
    RECONCILED,
    SEMANTIC_BUILDABLE_ACCEPTANCE,
    TEMPORAL,
    VERDICT_PARTIAL,
    VERDICT_POLICY_RESOLVED,
    CensusAuthorityDecision,
    FieldOutcome,
    NativeIsBuildableDecision,
    SameStateProvenance,
    SemanticReconciliation,
    TileReconciliation,
    _scope_page_instants,
    apply_census_authority,
    apply_native_isbuildable_policy,
    rebind_p08_native_isbuildable,
    rebind_p08_policy,
    reconcile_tile,
    vacant_projection,
)

CENSUS_INSTANT = 712225
RETAINED_BEFORE = 712285
RETAINED_AFTER = 712291

# ADR-012 second-instant tree-lifecycle tiles (not embedded in code; the
# caller supplies them and the policy validates them fail-closed).
SIX_TEMPORAL_TILES = (43951, 47286, 47288, 48042, 48309, 51378)

# The exact ADR-013 scope, repeated literally so a silent widening or
# narrowing of the embedded constant fails here.
NINETEEN_UNKNOWN_TILES = (
    46517,
    46518,
    46772,
    47027,
    47028,
    47282,
    47283,
    47538,
    47793,
    48049,
    48304,
    48305,
    48554,
    48555,
    48556,
    48557,
    48558,
    48559,
    48560,
)

# Representative slopes from the sealed 19-tile group ({8, 9, 12, 13}).
NINETEEN_SLOPES = (
    8,
    9,
    12,
    13,
    8,
    9,
    12,
    13,
    8,
    9,
    12,
    13,
    8,
    9,
    12,
    13,
    12,
    9,
    12,
)

WELCOME = {
    "seed": 17,
    "width": 512,
    "height": 512,
    "landscape": 0,
    "revision": "15.3",
    "start_day": 712224,
}


def flag_word(*names: str) -> int:
    return sum(1 << flags_index(name) for name in names)


def tile_fact(**overrides) -> TileFact:
    """The retained all-false, buildable=false, sloped projection shape."""

    values = dict(
        tile_id=NINETEEN_UNKNOWN_TILES[0],
        x=181,
        y=181,
        min_height=3,
        slope=13,
        buildable=False,
        water=False,
        coast=False,
        tree=False,
        farm=False,
        rock=False,
        rough=False,
        road=False,
        rail=False,
        water_transport=False,
        air_transport=False,
        industry_id=None,
    )
    values.update(overrides)
    return TileFact(**values)


def provenance() -> SameStateProvenance:
    return SameStateProvenance(
        census_page_dates=(712224, 712225, 712226),
        retained_date_before=RETAINED_BEFORE,
        retained_date_after=RETAINED_AFTER,
    )


def test_adr013_scope_is_exactly_the_authorized_nineteen_and_disjoint():
    assert NATIVE_ISBUILDABLE_SCOPE_TILES == frozenset(NINETEEN_UNKNOWN_TILES)
    assert NATIVE_ISBUILDABLE_CENSUS_INSTANT == CENSUS_INSTANT
    assert NATIVE_ISBUILDABLE_DERIVED_CLASS == "TERRAIN_MODIFICATION"
    assert NATIVE_ISBUILDABLE_SCOPE_TILES.isdisjoint(SIX_TEMPORAL_TILES)
    assert sum(NATIVE_ISBUILDABLE_BASE_COUNTS.values()) == 450
    assert NATIVE_ISBUILDABLE_BASE_COUNTS["UNKNOWN_OCCUPANCY"] == len(NINETEEN_UNKNOWN_TILES)


def test_vacant_projection_requires_flat_unowned_unobstructed_ground():
    buildable = flag_word("buildable")
    assert vacant_projection(0, OWNER_UNOWNED_SENTINEL, buildable) is True
    # Sloped clear ground is the exact retained shape: native IsBuildable is
    # set, but the planner's Vacant excludes non-flat ground.
    assert vacant_projection(13, OWNER_UNOWNED_SENTINEL, buildable) is False
    assert vacant_projection(0, 0, buildable) is False
    assert vacant_projection(0, OWNER_UNOWNED_SENTINEL, flag_word("buildable", "house")) is False


def test_buildable_projection_residual_is_semantic_acceptance_not_contradiction():
    retained = tile_fact()
    flags = flag_word("buildable")
    assert projection_disagrees(retained, flags) is True

    row = reconcile_tile(retained, flags, 13, OWNER_UNOWNED_SENTINEL, CENSUS_INSTANT, provenance())

    assert row.raw_gate_disagrees is True
    assert row.status == RECONCILED
    assert row.field_outcomes == (
        FieldOutcome("buildable", False, False, SEMANTIC_BUILDABLE_ACCEPTANCE),
    )


@pytest.mark.parametrize(
    ("subgroup", "tile_id", "slope", "retained_kwargs", "census_flag_names", "expected_legacy"),
    (
        (
            "D1_SLOPED_CLEAR_19",
            46517,
            13,
            {"buildable": False},
            ("buildable",),
            SegmentClass.UNKNOWN_OCCUPANCY,
        ),
        (
            "D2_STATIC_TREES_48",
            43946,
            0,
            {"buildable": False, "tree": True},
            ("buildable", "tree"),
            SegmentClass.SUPPORTED_CLEARING,
        ),
        (
            "D3_STATIC_ROUGH_10",
            47537,
            13,
            {"buildable": False, "rough": True},
            ("buildable", "rough"),
            SegmentClass.SUPPORTED_CLEARING,
        ),
    ),
)
def test_all_three_definitional_disagreement_subgroups_reconcile_on_buildable_only(
    subgroup: str,
    tile_id: int,
    slope: int,
    retained_kwargs: dict[str, bool],
    census_flag_names: tuple[str, ...],
    expected_legacy: SegmentClass,
):
    """Verify the 3 definitional subgroups totaling 77/83 disagreements (19 + 48 + 10)."""

    retained = tile_fact(
        tile_id=tile_id,
        x=tile_id % 256,
        y=tile_id // 256,
        slope=slope,
        **retained_kwargs,
    )
    flags = flag_word(*census_flag_names)

    assert _legacy_segment(retained)[0] is expected_legacy
    assert projection_disagrees(retained, flags) is True
    assert vacant_projection(slope, OWNER_UNOWNED_SENTINEL, flags) is False

    row = reconcile_tile(
        retained,
        flags,
        slope,
        OWNER_UNOWNED_SENTINEL,
        CENSUS_INSTANT,
        provenance(),
    )
    assert row.raw_gate_disagrees is True, subgroup
    assert row.status == RECONCILED, subgroup
    assert row.field_outcomes == (
        FieldOutcome("buildable", False, False, SEMANTIC_BUILDABLE_ACCEPTANCE),
    )


@pytest.mark.parametrize(
    (
        "tile_id",
        "page_date",
        "slope",
        "retained_kwargs",
        "census_flag_names",
        "expected_outcomes",
    ),
    (
        # 43951 (175,171): flat clear grass at census -> tree grew by retained V1 capture.
        (
            43951,
            712224,
            0,
            {"buildable": False, "tree": True},
            ("buildable",),
            (
                FieldOutcome("buildable", False, True, TEMPORAL),
                FieldOutcome("tree", True, False, TEMPORAL),
            ),
        ),
        # 47286 (182,184): sloped clear grass at census -> tree grew by retained V1 capture.
        (
            47286,
            712225,
            12,
            {"buildable": False, "tree": True},
            ("buildable",),
            (
                FieldOutcome("buildable", False, False, SEMANTIC_BUILDABLE_ACCEPTANCE),
                FieldOutcome("tree", True, False, TEMPORAL),
            ),
        ),
        # 47288, 48042, 48309: tree on rough ground at census -> tree died exposing CLEAR_ROUGH.
        (
            47288,
            712225,
            0,
            {"buildable": False, "tree": False, "rough": True},
            ("buildable", "tree"),
            (
                FieldOutcome("buildable", False, False, SEMANTIC_BUILDABLE_ACCEPTANCE),
                FieldOutcome("rough", True, False, TEMPORAL),
                FieldOutcome("tree", False, True, TEMPORAL),
            ),
        ),
        (
            48042,
            712225,
            0,
            {"buildable": False, "tree": False, "rough": True},
            ("buildable", "tree"),
            (
                FieldOutcome("buildable", False, False, SEMANTIC_BUILDABLE_ACCEPTANCE),
                FieldOutcome("rough", True, False, TEMPORAL),
                FieldOutcome("tree", False, True, TEMPORAL),
            ),
        ),
        (
            48309,
            712225,
            0,
            {"buildable": False, "tree": False, "rough": True},
            ("buildable", "tree"),
            (
                FieldOutcome("buildable", False, False, SEMANTIC_BUILDABLE_ACCEPTANCE),
                FieldOutcome("rough", True, False, TEMPORAL),
                FieldOutcome("tree", False, True, TEMPORAL),
            ),
        ),
        # 51378 (178,200): tree on flat grass at census -> died leaving flat Vacant grass.
        (
            51378,
            712226,
            0,
            {"buildable": True, "tree": False},
            ("buildable", "tree"),
            (
                FieldOutcome("buildable", True, False, TEMPORAL),
                FieldOutcome("tree", False, True, TEMPORAL),
            ),
        ),
    ),
)
def test_all_six_temporal_tiles_reproduce_their_exact_field_outcomes(
    tile_id: int,
    page_date: int,
    slope: int,
    retained_kwargs: dict[str, bool],
    census_flag_names: tuple[str, ...],
    expected_outcomes: tuple[FieldOutcome, ...],
):
    """Verify every one of the 6 temporal tiles (6/83 disagreements) individually."""

    retained = tile_fact(
        tile_id=tile_id,
        x=tile_id % 256,
        y=tile_id // 256,
        slope=slope,
        **retained_kwargs,
    )
    flags = flag_word(*census_flag_names)

    assert projection_disagrees(retained, flags) is True
    row = reconcile_tile(
        retained,
        flags,
        slope,
        OWNER_UNOWNED_SENTINEL,
        page_date,
        provenance(),
    )
    assert row.raw_gate_disagrees is True
    assert row.status == TEMPORAL
    assert row.field_outcomes == expected_outcomes


@pytest.mark.parametrize(
    ("census_date", "expected"),
    ((CENSUS_INSTANT, TEMPORAL), (712288, CONTRADICTION)),
)
def test_tree_lifecycle_delta_is_temporal_outside_window_and_contradiction_inside(
    census_date: int, expected: str
):
    retained = tile_fact(tile_id=51378, x=178, y=200, slope=0, buildable=True, tree=True)
    flags = flag_word("buildable")

    row = reconcile_tile(retained, flags, 0, OWNER_UNOWNED_SENTINEL, census_date, provenance())

    assert row.status == expected
    assert row.field_outcomes == (FieldOutcome("tree", True, False, expected),)


def test_all_false_projection_stays_unknown_and_is_never_inferred():
    retained = tile_fact()

    assert _legacy_segment(retained) == (
        SegmentClass.UNKNOWN_OCCUPANCY,
        "projection-dropped-occupancy-class",
    )
    assert classify_segment(retained) == (
        SegmentClass.UNKNOWN_OCCUPANCY,
        "projection-dropped-occupancy-class",
    )

    # A same-instant CLEAR claim over the retained projection is a
    # contradiction, not an upgrade: the base classifier refuses it so that
    # only the explicit ADR-013 policy layer can map the tile.
    assert classify_segment(retained, "CLEAR", flags=flag_word("buildable")) == (
        SegmentClass.UNKNOWN_OCCUPANCY,
        "conflicting-occupancy-evidence",
    )


def test_adr013_derivation_uses_a_coherent_census_observation():
    flags = flag_word("buildable")
    observed = tile_fact(buildable=True)
    flat = tile_fact(slope=0, buildable=True)

    assert classify_segment(observed, "CLEAR", flags=flags) == (
        SegmentClass.TERRAIN_MODIFICATION,
        "classified-clear-sloped",
    )
    assert classify_segment(flat, "CLEAR", flags=flags) == (
        SegmentClass.ROAD_BUILDABLE,
        "classified-clear-flat",
    )


def _synthetic_seed17_corpus() -> tuple[
    SupplementalPlanningFacts,
    dict[int, CensusTile],
    SemanticReconciliation,
]:
    """Build a deterministic 450-tile synthetic corpus matching the Seed 17 partition.

    Partition (450 tiles in region 170, 171, 15, 30):
    - 19 definitional sloped CLEAR (retained UNKNOWN_OCCUPANCY, exact IDs 46517..48560)
    - 48 definitional static TREES (retained SUPPORTED_CLEARING, census TREES)
    - 10 definitional static ROUGH (retained SUPPORTED_CLEARING, census ROUGH)
    - 6 temporal tiles (exact IDs 43951, 47286, 47288, 48042, 48309, 51378):
      * 43951 (flat CLEAR -> retained tree, SUPPORTED_CLEARING)
      * 47286 (sloped CLEAR -> retained tree, SUPPORTED_CLEARING)
      * 47288, 48042, 48309 (census TREES -> retained rough, SUPPORTED_CLEARING)
      * 51378 (census TREES -> retained flat Vacant CLEAR, ROAD_BUILDABLE)
    - 338 exact-match flat CLEAR (retained ROAD_BUILDABLE, census CLEAR)
    - 17 exact-match WATER (retained UNSUPPORTED_CONSTRUCTION, census WATER)
    - 12 exact-match INDUSTRY (retained UNSUPPORTED_CONSTRUCTION, census INDUSTRY)
    Totals:
    - Retained classes: 339 ROAD_BUILDABLE, 63 SUPPORTED_CLEARING, 19 UNKNOWN_OCCUPANCY,
      29 UNSUPPORTED_CONSTRUCTION (= 450).
    - Census classes: 359 CLEAR, 52 TREES, 17 WATER, 12 INDUSTRY, 10 ROUGH (= 450).
    - Disagreements: 77 definitional + 6 temporal = 83 PROJECTED_FLAGS_DIFFER.
    """

    all_region_tiles = [y * 256 + x for y in range(171, 171 + 30) for x in range(170, 170 + 15)]
    assert len(all_region_tiles) == 450

    reserved = set(NINETEEN_UNKNOWN_TILES) | set(SIX_TEMPORAL_TILES)
    remaining = [tid for tid in all_region_tiles if tid not in reserved]
    assert len(remaining) == 450 - 25 == 425

    static_tree_ids = set(remaining[:48])
    static_rough_ids = set(remaining[48:58])
    water_ids = set(remaining[58:75])
    industry_ids = set(remaining[75:87])
    flat_clear_ids = set(remaining[87:])
    assert len(flat_clear_ids) == 338

    unknown_slopes = dict(zip(NINETEEN_UNKNOWN_TILES, NINETEEN_SLOPES, strict=True))
    prov = provenance()

    retained_tiles: list[TileFact] = []
    census_map: dict[int, CensusTile] = {}
    ledger_rows: list[TileReconciliation] = []
    instants: list[tuple[int, int, int]] = []
    raw_gate: list[tuple[int, str]] = []
    semantic_ids: list[int] = []
    temporal_ids: list[int] = []

    for tid in sorted(all_region_tiles):
        x, y = tid % 256, tid // 256
        page_date = 712224 if tid == 43951 else (712226 if tid == 51378 else CENSUS_INSTANT)
        industry_id: int | None = None
        slope = 0

        if tid in unknown_slopes:
            slope = unknown_slopes[tid]
            r_fact = tile_fact(tile_id=tid, x=x, y=y, min_height=1, slope=slope, buildable=False)
            c_flags = flag_word("buildable")
            c_class = "CLEAR"
        elif tid in static_tree_ids:
            r_fact = tile_fact(
                tile_id=tid, x=x, y=y, min_height=2, slope=0, buildable=False, tree=True
            )
            c_flags = flag_word("buildable", "tree")
            c_class = "TREES"
        elif tid in static_rough_ids:
            r_fact = tile_fact(
                tile_id=tid, x=x, y=y, min_height=1, slope=0, buildable=False, rough=True
            )
            c_flags = flag_word("buildable", "rough")
            c_class = "ROUGH"
        elif tid == 43951:
            r_fact = tile_fact(
                tile_id=tid, x=x, y=y, min_height=2, slope=0, buildable=False, tree=True
            )
            c_flags = flag_word("buildable")
            c_class = "CLEAR"
        elif tid == 47286:
            slope = 12
            r_fact = tile_fact(
                tile_id=tid, x=x, y=y, min_height=1, slope=slope, buildable=False, tree=True
            )
            c_flags = flag_word("buildable")
            c_class = "CLEAR"
        elif tid in (47288, 48042, 48309):
            r_fact = tile_fact(
                tile_id=tid, x=x, y=y, min_height=1, slope=0, buildable=False, rough=True
            )
            c_flags = flag_word("buildable", "tree")
            c_class = "TREES"
        elif tid == 51378:
            r_fact = tile_fact(
                tile_id=tid, x=x, y=y, min_height=1, slope=0, buildable=True, tree=False
            )
            c_flags = flag_word("buildable", "tree")
            c_class = "TREES"
        elif tid in water_ids:
            r_fact = tile_fact(
                tile_id=tid, x=x, y=y, min_height=0, slope=0, buildable=False, water=True
            )
            c_flags = flag_word("water")
            c_class = "WATER"
        elif tid in industry_ids:
            industry_id = 0
            r_fact = tile_fact(
                tile_id=tid, x=x, y=y, min_height=2, slope=0, buildable=False, industry_id=0
            )
            c_flags = 0
            c_class = "INDUSTRY"
        else:
            assert tid in flat_clear_ids
            r_fact = tile_fact(tile_id=tid, x=x, y=y, min_height=2, slope=0, buildable=True)
            c_flags = flag_word("buildable")
            c_class = "CLEAR"

        retained_tiles.append(r_fact)
        census_map[tid] = CensusTile(
            tile_id=tid,
            x=x,
            y=y,
            elevation=r_fact.min_height,
            slope=slope,
            flags=c_flags,
            industry_id=industry_id,
            owner=OWNER_UNOWNED_SENTINEL,
            classification=c_class,
            page_ordinal=len(census_map) // 5,
            page_date=page_date,
        )
        row = reconcile_tile(r_fact, c_flags, slope, OWNER_UNOWNED_SENTINEL, page_date, prov)
        ledger_rows.append(row)
        instants.append((tid, page_date, page_date))
        if row.raw_gate_disagrees:
            raw_gate.append((tid, "PROJECTED_FLAGS_DIFFER"))
        if row.status == RECONCILED and row.raw_gate_disagrees:
            semantic_ids.append(tid)
        elif row.status == TEMPORAL:
            temporal_ids.append(tid)

    facts_doc = SupplementalPlanningFacts(
        schema_version=1,
        transport_mode="road",
        source=FactSource(
            world_observation_digest="a" * 64,
            structural_digest="b" * 64,
            production_digest="c" * 64,
            world_id="seed17-synthetic-reconciliation",
            runtime_digest="d" * 64,
            configuration_digest="e" * 64,
            bridge_digest="f" * 64,
            content_digest="0" * 64,
            map_width=256,
            map_height=256,
        ),
        region=RandomCaptureRegion(
            x=170, y=171, profile="random-rectangle-512-v1", width=15, height=30
        ),
        settings=ContentSettings(
            content_digest="0" * 64,
            generation_seed=17,
            modified_catchment=True,
            serve_neutral_industries=False,
            timekeeping="calendar",
            effective_truck_stop_radius=3,
            context="deity-public",
            gameplay_newgrf_ids=(),
        ),
        road=RoadFacts(
            road_type_id=0,
            public_available=True,
            max_speed_native=0,
            road_piece_cost_gbp=10,
            truck_stop_cost_gbp=50,
            depot_cost_gbp=100,
            currency="GBP",
        ),
        tiles=tuple(retained_tiles),
        coverage_scopes=(),
        coverage=(),
        engines=(),
        capture_economy_date_before=RETAINED_BEFORE,
        capture_economy_date_after=RETAINED_AFTER,
    )

    reconciliation = SemanticReconciliation(
        policy_version="vacant-projection-1",
        retained_facts_sha256="9e4c5c4225b697312230deae40989de643bcdd79db1063cf6eda9fa365d8bb6e",
        census_page_payload_sha256="1" * 64,
        provenance=prov,
        region=(170, 171, 15, 30),
        census_pages=90,
        census_tiles=450,
        census_class_counts={
            "CLEAR": 359,
            "INDUSTRY": 12,
            "ROUGH": 10,
            "TREES": 52,
            "WATER": 17,
        },
        retained_class_counts=dict(NATIVE_ISBUILDABLE_BASE_COUNTS),
        identity_failures=(),
        hygiene_failures=(),
        raw_gate_tiles=tuple(raw_gate),
        tiles=tuple(ledger_rows),
        completeness_reproduced=True,
        manifest_verified=True,
        manifest_entries=198,
        semantic_tiles=tuple(semantic_ids),
        temporal_tiles=tuple(temporal_ids),
        contradiction_tiles=(),
        unresolved_tiles=(),
        census_tile_instants=tuple(instants),
    )
    return facts_doc, census_map, reconciliation


def test_full_450_tile_reconciliation_and_adr012_adr013_pipeline_offline():
    """Verify the complete 450-tile ledger (83 disagreements, 19 UNKNOWN) offline."""

    retained, census, base = _synthetic_seed17_corpus()
    before_bytes = base.to_json_bytes()

    # 1. Discrepancy accounting: 83 raw = 77 definitional + 6 temporal, 0 bugs/contradictions.
    assert len(base.raw_gate_tiles) == 83
    assert len(base.semantic_tiles) == 77
    assert base.temporal_tiles == SIX_TEMPORAL_TILES
    assert base.contradiction_tiles == ()
    assert base.unresolved_tiles == ()
    assert base.verdict() == VERDICT_PARTIAL
    assert base.p08_binding()["allowed"] is False

    # 2. Diagnosis of the 19 fresh-CLEAR / retained-UNKNOWN tiles.
    diagnosis = diagnose_unknown_occupancy(retained, census, base)
    assert diagnosis["count"] == 19
    assert diagnosis["resolved"] is False
    assert diagnosis["all_evidence_consistent"] is True
    assert len(diagnosis["groups"]) == 1
    group = diagnosis["groups"][0]
    assert group["root_cause"] == UNKNOWN_OCCUPANCY_ROOT_CAUSE
    assert group["count"] == 19
    assert group["slopes"] == [8, 9, 12, 13]
    assert group["census_classes"] == ["CLEAR"]
    assert tuple(group["tiles"]) == NINETEEN_UNKNOWN_TILES

    # 3. ADR-012 policy application & rebinding (resolves 6 temporal tiles, 19 UNKNOWN still block).
    adr012_decision = CensusAuthorityDecision(scope_tiles=frozenset(SIX_TEMPORAL_TILES))
    adr012_applied = apply_census_authority(
        base, adr012_decision, _scope_page_instants(base, adr012_decision)
    )
    assert adr012_applied.refused_reason is None
    assert adr012_applied.verdict == VERDICT_POLICY_RESOLVED
    assert [tid for tid, _rows in adr012_applied.resolved_field_rows] == list(SIX_TEMPORAL_TILES)
    for _tid, entry in adr012_applied.resolved_field_rows:
        assert all(r["policy_outcome"] == AUTHORITY_RESOLVED_OUTCOME for r in entry["fields"])

    adr012_rebound = rebind_p08_policy(base, adr012_applied.to_json_bytes())
    assert adr012_rebound.allowed is False
    assert adr012_rebound.unresolved_classification_tiles == 19

    # 4. ADR-013 policy application & combined rebinding (maps 19 UNKNOWN -> TERRAIN_MODIFICATION
    #    in derived planning layer while keeping base ledger and SOURCE_SAVE_FUSION closed).
    adr013_applied = apply_native_isbuildable_policy(
        base, retained, census, NativeIsBuildableDecision()
    )
    assert adr013_applied.refused_reason is None
    assert adr013_applied.verdict == NATIVE_ISBUILDABLE_VERDICT
    assert adr013_applied.derived_segmentation_counts == {
        "ROAD_BUILDABLE": 339,
        "SUPPORTED_CLEARING": 63,
        "TERRAIN_MODIFICATION": 19,
        "UNKNOWN_OCCUPANCY": 0,
        "UNSUPPORTED_CONSTRUCTION": 29,
    }
    assert adr013_applied.p08_binding()["allowed"] is False

    combined = rebind_p08_native_isbuildable(
        base,
        adr013_applied.to_json_bytes(),
        retained,
        census,
        census_authority_report_bytes=adr012_applied.to_json_bytes(),
    )
    assert combined.allowed is True
    assert combined.resolved_temporal_tiles == SIX_TEMPORAL_TILES
    assert combined.resolved_unknown_tiles == NINETEEN_UNKNOWN_TILES
    combined_report = combined.report()
    assert combined_report["p08_binding"]["allowed"] is True
    assert combined_report["p08_binding"]["p08_complete"] is False
    assert combined_report["fusion_gate"] == {
        "status": "CLOSED",
        "opened": False,
        "reason": "sealed SOURCE_SAVE_FUSION verdict is immutable; "
        "this policy pass does not relabel or fuse it",
    }
    # Base ledger remains byte-identical and retains UNKNOWN_OCCUPANCY: 19.
    assert base.to_json_bytes() == before_bytes
    assert base.retained_class_counts["UNKNOWN_OCCUPANCY"] == 19


def test_a0_native_survey_six_deviations_are_post_d3_d4_findings_not_census_replacements():
    """Cross-reference the 6 A0 native survey deviations (D5CE3-SURVEY-3, E40)."""

    hypotheses = {
        "state": "RETAINED_CENSUS_REBOUND",
        "hypotheses": [
            {
                "observation_index": 0,
                "tile": 50095,
                "origin": "TERRA_TILES",
                "terrain": {
                    "min_height": 1,
                    "slope": 0,
                    "buildable": True,
                    "water": False,
                    "coast": False,
                    "tree": False,
                    "farm": False,
                    "rock": False,
                    "rough": False,
                    "road": False,
                    "rail": False,
                    "water_transport": False,
                    "air_transport": False,
                },
                "kind": "HYPOTHESIS",
            },
            {
                "observation_index": 1,
                "tile": 50096,
                "origin": "TERRA_TILES",
                "terrain": {"min_height": 1, "slope": 0, "buildable": True, "rough": False},
                "kind": "HYPOTHESIS",
            },
            {
                "observation_index": 2,
                "tile": 50352,
                "origin": "TERRA_TILES",
                "terrain": {"min_height": 1, "slope": 0, "buildable": True, "rough": False},
                "kind": "HYPOTHESIS",
            },
            {
                "observation_index": 3,
                "tile": 50608,
                "origin": "TERRA_TILES",
                "terrain": {"min_height": 1, "slope": 0, "buildable": True, "rough": False},
                "kind": "HYPOTHESIS",
            },
            {
                "observation_index": 4,
                "tile": 50864,
                "origin": "TERRA_TILES",
                "terrain": {"min_height": 1, "slope": 0, "buildable": True, "rough": False},
                "kind": "HYPOTHESIS",
            },
            {
                "observation_index": 5,
                "tile": 50863,
                "origin": "TERRA_TILES",
                "terrain": {"min_height": 1, "slope": 0, "buildable": True, "rough": False},
                "kind": "HYPOTHESIS",
            },
            {
                "observation_index": 6,
                "tile": 50862,
                "origin": "TERRA_TILES",
                "terrain": {"min_height": 1, "slope": 0, "buildable": True, "rough": False},
                "kind": "HYPOTHESIS",
            },
        ],
    }
    measured_post_d4 = {
        "50095": {
            "request_id": "tile-00",
            "min_height": 2,
            "slope": 0,
            "buildable": False,
            "water": False,
            "coast": False,
            "tree": False,
            "farm": False,
            "rock": False,
            "rough": False,
            "road": True,
            "rail": False,
            "water_transport": False,
            "air_transport": False,
        },
        "50096": {
            "request_id": "tile-01",
            "min_height": 1,
            "slope": 12,
            "buildable": True,
            "rough": False,
        },
        "50352": {
            "request_id": "tile-02",
            "min_height": 1,
            "slope": 12,
            "buildable": True,
            "rough": False,
        },
        "50608": {
            "request_id": "tile-03",
            "min_height": 1,
            "slope": 8,
            "buildable": True,
            "rough": False,
        },
        "50864": {
            "request_id": "tile-04",
            "min_height": 1,
            "slope": 0,
            "buildable": True,
            "rough": False,
        },
        "50863": {
            "request_id": "tile-05",
            "min_height": 1,
            "slope": 0,
            "buildable": True,
            "rough": False,
        },
        "50862": {
            "request_id": "tile-06",
            "min_height": 1,
            "slope": 0,
            "buildable": True,
            "rough": False,
        },
    }

    findings = compare_terrain_census_findings(measured_post_d4, hypotheses)
    assert len(findings) == 6
    summary = [
        (item["tile"], item["field"], item["census_hypothesis"], item["measured"])
        for item in findings
    ]
    assert summary == [
        (50095, "min_height", 1, 2),
        (50095, "buildable", True, False),
        (50095, "road", False, True),
        (50096, "slope", 0, 12),
        (50352, "slope", 0, 12),
        (50608, "slope", 0, 8),
    ]


def test_source_save_fusion_refuses_without_a_verified_save_binding():
    unbound = evaluate_correspondence(SOURCE_SAVE_MODE, bound=True)
    assert unbound["status"] == "REJECTED"
    assert "verified retained save binding" in unbound["statement"]

    drifted = evaluate_correspondence(
        SOURCE_SAVE_MODE,
        bound=False,
        coherence_failures=((NINETEEN_UNKNOWN_TILES[0], "PROJECTED_FLAGS_DIFFER"),),
        save_binding={"save": "before.sav"},
    )
    assert drifted["status"] == "REJECTED"

    bound = evaluate_correspondence(
        SOURCE_SAVE_MODE, bound=True, save_binding={"save": "before.sav"}
    )
    assert bound["status"] == "CORRESPONDENCE_ESTABLISHED"

    # SAME_SESSION_CENSUS requires zero fresh-fact contradictions in addition to bound=True.
    same_session_ok = evaluate_correspondence(
        SAME_SESSION_MODE, bound=True, fresh_contradictions=()
    )
    assert same_session_ok["status"] == "CORRESPONDENCE_ESTABLISHED"
    same_session_bad = evaluate_correspondence(
        SAME_SESSION_MODE, bound=True, fresh_contradictions=((43951, "tree"),)
    )
    assert same_session_bad["status"] == "REJECTED"


def test_identity_gate_accepts_an_identical_recorded_welcome():
    assert TileClassificationSweep.verify_identity(WELCOME, dict(WELCOME)) == []


@pytest.mark.parametrize("key", WELCOME_IDENTITY_KEYS)
def test_identity_gate_compares_every_recorded_welcome_key(key: str):
    observed = dict(WELCOME)
    observed[key] = "different"

    assert TileClassificationSweep.verify_identity(WELCOME, observed) == [
        (-1, f"WORLD_IDENTITY_MISMATCH:{key}")
    ]


def test_identity_gate_rejects_a_missing_observed_key():
    observed = dict(WELCOME)
    observed.pop("start_day")

    assert TileClassificationSweep.verify_identity(WELCOME, observed) == [
        (-1, "WORLD_IDENTITY_MISMATCH:start_day")
    ]
