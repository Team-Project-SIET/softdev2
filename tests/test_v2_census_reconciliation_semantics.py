"""Deterministic offline tests for the V2 census-reconciliation semantics.

These tests need no retained Seed 17 artifacts: they construct the exact tile
shapes the sealed census recorded and pin the expected dispositions. They do
not connect to OpenTTD, create, sign, claim or launch any candidate.

Phase 4 disposition pinned here:

- the 77 definitional ``PROJECTED_FLAGS_DIFFER`` rows are the retained
  ``Vacant`` versus native ``IsBuildable`` projection mismatch; they are
  accepted semantically and never rewritten;
- the six temporal rows are second-instant tree/rough lifecycle deltas; they
  are attributed to time and never repaired;
- the 19 retained-UNKNOWN rows stay ``UNKNOWN_OCCUPANCY`` in the base ledger;
  only the ADR-013 derived policy maps them, and only from a coherent
  same-instant native observation.
"""

from __future__ import annotations

import pytest

from app.planning.p08_terrain import SegmentClass, _legacy_segment, classify_segment
from app.simulation.openttd.proof.world_correspondence import (
    SOURCE_SAVE_MODE,
    evaluate_correspondence,
)
from app.simulation.openttd.supplemental_planning_facts import TileFact
from app.simulation.openttd.tile_classification import (
    WELCOME_IDENTITY_KEYS,
    TileClassificationSweep,
    flags_index,
    projection_disagrees,
)
from app.simulation.openttd.v2_semantic_reconciliation import (
    CONTRADICTION,
    NATIVE_ISBUILDABLE_BASE_COUNTS,
    NATIVE_ISBUILDABLE_CENSUS_INSTANT,
    NATIVE_ISBUILDABLE_DERIVED_CLASS,
    NATIVE_ISBUILDABLE_SCOPE_TILES,
    OWNER_UNOWNED_SENTINEL,
    RECONCILED,
    SEMANTIC_BUILDABLE_ACCEPTANCE,
    TEMPORAL,
    FieldOutcome,
    SameStateProvenance,
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
        census_page_dates=(CENSUS_INSTANT,),
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
