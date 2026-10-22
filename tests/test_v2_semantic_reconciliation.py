"""Focused tests for the offline V1/V2 semantic reconciliation policy.

Offline only: no OpenTTD launch, no AdminPort connection. Retained-evidence
tests skip when the ignored artifacts are absent from this checkout and never
mutate them. The strict sealed coherence gate
(``tile_classification.projection_disagrees``) is exercised unchanged.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import pytest

from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts, TileFact
from app.simulation.openttd.tile_classification import (
    CLASSIFICATION_FLAG_NAMES,
    flags_index,
    projection_disagrees,
)
from app.simulation.openttd.v2_semantic_reconciliation import (
    CONTRADICTION,
    OWNER_UNOWNED_SENTINEL,
    RECONCILED,
    SEMANTIC_BUILDABLE_ACCEPTANCE,
    TEMPORAL,
    UNRESOLVED,
    VERDICT_ESTABLISHED,
    VERDICT_PARTIAL,
    VERDICT_REJECTED,
    SameStateProvenance,
    SemanticReconciliation,
    bit,
    reconcile_tile,
    replay_retained_census,
    vacant_projection,
)

SEED17_RUN = Path("artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253")
SEED17_CANDIDATE = Path("artifacts/demos/classification-exec-seed17-3a8f9e46")
FIXED_DEMO_RUN = Path("artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a")

# Pinned identities from docs/p08-v1v2-semantic-provenance-diagnosis.md.
CENSUS_ECONOMY_DATE = 712224
# tree+buildable schema-2 mask vs tree-only V1 concept.
EXPECTED_SEMANTIC_TILE = 43946
EXPECTED_TEMPORAL_TILES = (43951, 47286, 47288, 48042, 48309, 51378)


@lru_cache(maxsize=1)
def _seed17_replay() -> SemanticReconciliation:
    return replay_retained_census(SEED17_RUN / "network-facts-0.json", SEED17_CANDIDATE)


def _pressed_flags(**overrides) -> int:
    """Build a schema-2 flag word from named bits (all false by default)."""

    flags = 0
    for name, value in overrides.items():
        if value:
            flags |= 1 << flags_index(name)
    return flags


def _fact(**overrides) -> TileFact:
    """A flat, unowned, bare grass TileFact with named overrides."""

    values = dict(
        buildable=True,
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
    )
    values.update(overrides)
    return TileFact(
        tile_id=0,
        x=0,
        y=0,
        min_height=1,
        slope=0,
        industry_id=None,
        **values,
    )


def _provenance(
    census_date: int, retained: tuple[int, int] = (712285, 712291)
) -> SameStateProvenance:
    return SameStateProvenance(
        census_page_dates=(census_date,),
        retained_date_before=retained[0],
        retained_date_after=retained[1],
    )


# --- Vacant (V1 planner producer) versus native IsBuildable ---------------


def test_vacant_projection_excludes_trees_rough_and_requires_flat_unowned():
    tree_flags = _pressed_flags(buildable=True, tree=True)
    assert bit(tree_flags, "buildable")  # native IsBuildable is true on MP_TREES
    tree_fact = _fact(buildable=False, tree=True)
    assert f"{projection_disagrees(tree_fact, tree_flags)}" == "True"
    # The V1 producer's Vacant still excludes tree, rough and non-flat/non-unowned.
    assert vacant_projection(0, OWNER_UNOWNED_SENTINEL, tree_flags) is False
    rough_flags = _pressed_flags(buildable=True, rough=True)
    assert projection_disagrees(_fact(tree=True), rough_flags)
    assert vacant_projection(0, OWNER_UNOWNED_SENTINEL, rough_flags) is False
    assert vacant_projection(1, OWNER_UNOWNED_SENTINEL, _pressed_flags(buildable=True)) is False
    assert vacant_projection(0, 0, _pressed_flags(buildable=True)) is False
    assert (
        vacant_projection(
            0, OWNER_UNOWNED_SENTINEL, _pressed_flags(buildable=True, road_track=True)
        )
        is False
    )
    grass = _pressed_flags(buildable=True)
    assert vacant_projection(0, OWNER_UNOWNED_SENTINEL, grass) is True


def test_v1_vacant_projection_accepts_the_recorded_tree_tile_transformation():
    """Seed 17 tile 43946 shape: V1 tree-not-ownable vs native MP_TREES+buildable."""

    fact = _fact(buildable=False, tree=True)
    tree_flags = _pressed_flags(buildable=True, tree=True)
    raw_flagged = projection_disagrees(fact, tree_flags)
    assert raw_flagged
    tile = reconcile_tile(
        fact,
        flags=tree_flags,
        slope=0,
        owner=OWNER_UNOWNED_SENTINEL,
        census_date=CENSUS_ECONOMY_DATE,
        provenance=_provenance(CENSUS_ECONOMY_DATE),
    )
    assert tile.raw_gate_disagrees is raw_flagged
    assert tile.status == RECONCILED
    assert [(o.field, o.outcome) for o in tile.field_outcomes] == [
        ("buildable", SEMANTIC_BUILDABLE_ACCEPTANCE)
    ]
    # The accepted transformation records the recorded producer value against
    # the freshly projected Vacant boolean (never a reinterpretation of it).
    assert all(o.retained_value is False and o.census_value is False for o in tile.field_outcomes)


def test_unexplained_buildable_residual_is_a_genuine_contradiction():
    """Same-state record claiming buildable=False where Vacant must be true."""

    fact = _fact(buildable=False)
    flags = _pressed_flags(buildable=True)
    tile = reconcile_tile(
        fact,
        flags=flags,
        slope=0,
        owner=OWNER_UNOWNED_SENTINEL,
        census_date=CENSUS_ECONOMY_DATE,
        provenance=_provenance(CENSUS_ECONOMY_DATE),
    )
    assert tile.status == CONTRADICTION
    assert [o.field for o in tile.field_outcomes] == ["buildable"]


def test_distinct_air_predicates_reject_correspondence_on_mismatch():
    """V1 TRANSPORT_AIR vs V2 IsAirportTile: mismatch stays unresolved evidence."""

    fact = _fact(buildable=True, air_transport=True)
    flags = _pressed_flags(buildable=True)
    tile = reconcile_tile(
        fact,
        flags=flags,
        slope=0,
        owner=OWNER_UNOWNED_SENTINEL,
        census_date=CENSUS_ECONOMY_DATE,
        provenance=_provenance(CENSUS_ECONOMY_DATE),
    )
    assert tile.status == UNRESOLVED
    assert [o.field for o in tile.field_outcomes] == ["air_transport"]


# --- Same-state provenance ------------------------------------------------


def test_shared_predicate_difference_outside_retained_window_is_temporal():
    fact = _fact(tree=True)
    flags = _pressed_flags(buildable=True)
    tile = reconcile_tile(
        fact,
        flags=flags,
        slope=0,
        owner=OWNER_UNOWNED_SENTINEL,
        census_date=CENSUS_ECONOMY_DATE,
        provenance=_provenance(CENSUS_ECONOMY_DATE, retained=(712285, 712291)),
    )
    assert tile.status == TEMPORAL
    assert any(o.field == "tree" and o.outcome == TEMPORAL for o in tile.field_outcomes)


def test_shared_predicate_difference_inside_retained_window_is_contradiction():
    fact = _fact(tree=True)
    flags = _pressed_flags(buildable=True)
    provenance = SameStateProvenance(
        census_page_dates=(712288,),
        retained_date_before=712285,
        retained_date_after=712291,
    )
    tile = reconcile_tile(
        fact,
        flags=flags,
        slope=0,
        owner=OWNER_UNOWNED_SENTINEL,
        census_date=712288,
        provenance=provenance,
    )
    assert tile.status == CONTRADICTION
    assert not provenance.within_window(CENSUS_ECONOMY_DATE)


def test_same_state_matches_flag_name_layout():
    """Guard against bit-layout drift between diagnosis and policy modules."""

    assert CLASSIFICATION_FLAG_NAMES[:7] == (
        "buildable",
        "water",
        "coast",
        "tree",
        "farm",
        "rock",
        "rough",
    )


# --- Verdict and P08 gating ------------------------------------------------


def _synthetic_reconciliation(statuses: tuple[str, ...]) -> SemanticReconciliation:
    tiles = tuple(
        type("LedgerStub", (), {"tile_id": 0 + index, "status": status})()
        for index, status in enumerate(statuses)
    )
    return SemanticReconciliation(
        policy_version="vacant-projection-1",
        retained_facts_sha256="0" * 64,
        census_page_payload_sha256="1" * 64,
        provenance=SameStateProvenance(
            census_page_dates=(CENSUS_ECONOMY_DATE,),
            retained_date_before=712285,
            retained_date_after=712291,
        ),
        region=(0, 0, 2, 1),
        census_pages=1,
        census_tiles=len(tiles),
        census_class_counts={"CLEAR": len(tiles)},
        retained_class_counts={"ROAD_BUILDABLE": len(tiles)},
        identity_failures=(),
        hygiene_failures=(),
        raw_gate_tiles=(),
        tiles=tiles,
        completeness_reproduced=True,
        manifest_verified=True,
        manifest_entries=1,
        semantic_tiles=(),
        temporal_tiles=tuple(i for i, s in enumerate(statuses) if s == TEMPORAL),
        contradiction_tiles=tuple(i for i, s in enumerate(statuses) if s == CONTRADICTION),
        unresolved_tiles=tuple(i for i, s in enumerate(statuses) if s == UNRESOLVED),
    )


def test_p08_assessment_binds_only_on_fully_established_verdict():
    clean = _synthetic_reconciliation((RECONCILED, RECONCILED))
    assert clean.verdict() == VERDICT_ESTABLISHED
    assert clean.p08_binding()["allowed"] is True
    partial = _synthetic_reconciliation((RECONCILED, TEMPORAL))
    assert partial.verdict() == VERDICT_PARTIAL
    binding = partial.p08_binding()
    assert binding["allowed"] is False
    assert binding["preserved_retained_status"] == "INCOMPLETE_TILE_CLASSIFICATION"
    rejected = _synthetic_reconciliation((CONTRADICTION,))
    assert rejected.verdict() == VERDICT_REJECTED
    assert rejected.p08_binding()["allowed"] is False
    unresolved = _synthetic_reconciliation((UNRESOLVED,))
    assert unresolved.verdict() == VERDICT_REJECTED


def test_minimum_additional_evidence_names_the_temporal_tiles():
    partial = _synthetic_reconciliation((TEMPORAL, TEMPORAL))
    evidence = partial.minimum_additional_evidence()
    assert any("[0, 1]" in message for message in evidence)
    assert not _synthetic_reconciliation(()).minimum_additional_evidence()


# --- Retained evidence replay (independent offline verification) ----------


@pytest.mark.skipif(
    not (SEED17_RUN / "network-facts-0.json").exists() or not SEED17_CANDIDATE.exists(),
    reason="optional retained Seed 17 census evidence is not installed",
)
class TestSeed17RetainedReplay:
    def test_raw_gate_reproduces_the_sealed_83_exactly(self):
        replay = _seed17_replay()
        assert len(replay.raw_gate_tiles) == 83
        sealed = json.loads((SEED17_CANDIDATE / "classification-completeness.json").read_bytes())[
            "coherence_failures"
        ]
        assert [tile for tile, _code in replay.raw_gate_tiles] == [x[0] for x in sorted(sealed)]
        assert replay.completeness_reproduced is True

    def test_exactly_seventy_seven_definitional_tiles_reconciled(self):
        replay = _seed17_replay()
        assert len(replay.semantic_tiles) == 77
        assert EXPECTED_SEMANTIC_TILE in replay.semantic_tiles
        assert not set(replay.semantic_tiles) & set(EXPECTED_TEMPORAL_TILES)
        # Every semantic tile differs only in the buildable field.
        tile_ledger = replay.report()["tile_ledger"]
        for tile in replay.semantic_tiles:
            fields = {o["field"] for o in tile_ledger[str(tile)]["field_outcomes"]}
            assert fields == {"buildable"}
        # The sealed candidate cache reproduces its 198-entry manifest.
        assert replay.manifest_verified is True
        assert replay.manifest_entries == 198

    def test_exactly_six_temporal_tiles_preserved_as_second_instant(self):
        replay = _seed17_replay()
        assert replay.temporal_tiles == EXPECTED_TEMPORAL_TILES
        assert replay.contradiction_tiles == ()
        assert replay.unresolved_tiles == ()
        detail = replay.report()["policy_verdict"]["temporal_second_instant"]["field_detail"]
        assert detail[str(51378)][0]["field"] == "buildable"
        assert detail[str(51378)][-1]["field"] == "tree"
        rough = {tile for tile in detail if "rough" in [f["field"] for f in detail[tile]]}
        assert rough == {"47288", "48042", "48309"}
        assert replay.verdict() == VERDICT_PARTIAL
        assert replay.p08_binding()["preserved_retained_status"] == "INCOMPLETE_TILE_CLASSIFICATION"
        assert set(replay.same_state_failing_tiles) == set(EXPECTED_TEMPORAL_TILES)

    def test_same_state_provenance_defines_the_temporal_attribution(self):
        replay = _seed17_replay()
        detail = replay.report()["sources"]["provenance"]
        assert detail["census_page_economy_dates"] == {"count": 90, "min": 712224, "max": 712226}
        assert detail["retained_capture_economy_dates"] == [712285, 712291]
        assert detail["census_window_inside_retained_capture_window"] is False

    def test_replay_is_read_only_and_deterministically_serializable(self):
        retained_bytes = (SEED17_RUN / "network-facts-0.json").read_bytes()
        before_paths = sorted(SEED17_RUN.glob("*"))
        digest_before = hashlib.sha256(retained_bytes).hexdigest()

        replay = _seed17_replay()
        # A second, uncached replay must produce byte-identical report bytes.
        replay_again = replay_retained_census(SEED17_RUN / "network-facts-0.json", SEED17_CANDIDATE)
        first = replay.to_json_bytes()
        second = replay_again.to_json_bytes()
        assert first == second

        digest_after = hashlib.sha256(
            (SEED17_RUN / "network-facts-0.json").read_bytes()
        ).hexdigest()
        assert digest_after == digest_before
        assert sorted(SEED17_RUN.glob("*")) == before_paths
        retained = SupplementalPlanningFacts.model_validate_json(
            (SEED17_RUN / "network-facts-0.json").read_bytes()
        )
        assert len(retained.tiles) == replay.census_tiles


@pytest.mark.skipif(
    not (FIXED_DEMO_RUN / "network-facts-0.json").exists(),
    reason="optional retained fixed-demo evidence is not installed",
)
class TestFixedDemoCompatibility:
    def test_fixed_demo_schema1_facts_remain_parseable_for_the_policy(self):
        """The policy consumes only contract fields both demos already expose."""

        facts = SupplementalPlanningFacts.model_validate_json(
            (FIXED_DEMO_RUN / "network-facts-0.json").read_bytes()
        )
        for tile in facts.tiles:
            # Same-predicate V1 concepts the policy compares, present in schema 1.
            for field in ("water", "coast", "tree", "farm", "rock", "rough", "road", "rail"):
                assert isinstance(getattr(tile, field), bool)
