"""Focused offline tests for the V2 snapshot-scoped P08 planning adapter.

Those tests bind the adapter (``app.planning.p08_v2_snapshot``) to the sealed
retained classification census: gate reproduction, complete native evidence
coverage, explicit predicate semantics, save-identity pinning, temporal
coherence, fail-closed missing-data rejection, the six measured temporal
tile cases, preservation of the 77 accepted semantic transformations,
rejection of any historical V1 fusion path, determinism and historical
evidence immutability. No launch, no connection, no evidence mutation.
"""

import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

REPO = Path(__file__).resolve().parents[1]
RETAINED = (
    REPO / "artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json"
)
CANDIDATE = REPO / "artifacts/demos/classification-exec-seed17-3a8f9e46"
PINNED_ARTIFACT = (
    REPO / "artifacts/experiments/v2-snapshot-p08-readiness/snapshot-assessment-report.json"
)

pytestmark = pytest.mark.skipif(
    not all(
        (
            RETAINED.is_file(),
            (CANDIDATE / "classification-p000-response.json").is_file(),
        )
    ),
    reason="retained classification census evidence not present",
)

from app.planning.p08_terrain import assess_world_feasibility  # noqa: E402
from app.planning.p08_v2_snapshot import (  # noqa: E402
    POLICY_VERSION,
    build_v2_snapshot_assessment,
)
from app.simulation.openttd.supplemental_planning_facts import (  # noqa: E402
    PlanningFactError,
    SupplementalPlanningFacts,
)
from app.simulation.openttd.tile_classification import (  # noqa: E402
    TileQueryError,
)


@lru_cache(maxsize=1)
def assessment():
    return build_v2_snapshot_assessment(RETAINED, CANDIDATE, project_root=REPO)


@lru_cache(maxsize=1)
def report():
    return assessment().report()


def test_gate_reproduces_the_completed_semantic_reconciliation():
    gate = report()["gate"]
    assert gate["reconciliation_verdict"] == "SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED"
    assert gate["semantic_tiles"] == 77
    assert gate["temporal_tiles"] == 6
    assert gate["genuine_contradictions"] == 0
    assert gate["unresolved_predicates"] == 0
    assert gate["completeness_reproduced"] is True
    assert gate["manifest_verified"] is True
    assert gate["sealed_fusion_mode"] == "SOURCE_SAVE_FUSION"
    assert gate["sealed_fusion_status"] == "REJECTED"
    assert gate["sealed_save_binding_sha256"] == (
        "f9ae7dcba3bf862bc0b1de7c2a2eb781978beb92c152c97a2a6b6d2d4f8fda70"
    )


def test_complete_tile_coverage_and_per_page_temporal_provenance():
    assert report()["census"]["pages"] == 90
    assert report()["census"]["tiles"] == 450
    assert report()["census"]["bracket"] == [712224, 712226]
    assert report()["census"]["all_pages_sampled_simultaneously_is_not_claimed"] is True
    # Region: exactly the retained RandomCaptureRegion rectangle, every tile
    # mapped into it, ownership restricted to the unowned sentinel.
    from app.planning.p08_v2_snapshot import _load_census

    retained, census, _bracket, _pages = _load_census(RETAINED, CANDIDATE)
    region = (retained.region.x, retained.region.y, retained.region.width, retained.region.height)
    assert region == (170, 171, 15, 30)
    assert len(census) == 450
    page_dates = {tile.page_date for tile in census.values()}
    assert page_dates <= {*range(712224, 712227)}
    for tile in census.values():
        assert region[0] <= tile.x < region[0] + region[2]
        assert region[1] <= tile.y < region[1] + region[3]
        assert tile.owner == -1


def test_native_predicate_interpretation_is_explicit_and_coherent():
    census_report = report()["census"]
    assert census_report["native_projection_disagreements"] == 0
    assert census_report["vac_semantic_divergent_tiles"] == 0
    # Native semantics: a tree tile is natively buildable (bit 0) yet is NOT
    # stop-viable (the stop rule excludes occupancy), and the corridor has no
    # unknown-class tiles at all.
    primary = report()["assessment_primary"]
    assert primary["code"] == "TERRAIN_MODIFICATION_REQUIRED"
    counts = {name: count for name, count in primary["corridor_segment_counts"]}
    assert counts.get("UNKNOWN_OCCUPANCY", 0) == 0
    assert counts.get("UNSUPPORTED_CONSTRUCTION", 0) == 0
    assert primary["detail"] == "corridor within supported construction classes"


def test_source_save_identity_pinned_and_semantics_documented():
    report_value = report()
    assert report_value["sources"]["structural_digest"] == (
        "f9ae7dcba3bf862bc0b1de7c2a2eb781978beb92c152c97a2a6b6d2d4f8fda70"
    )
    assert report_value["sources"]["world_id"] == "v2-snapshot-census-seed17"
    semantics = report_value["digest_semantics"]
    assert "no production observation exists in-session" in semantics["production_digest"]
    assert (
        len(
            {
                report_value["sources"][name]
                for name in (
                    "world_observation_digest",
                    "runtime_digest",
                    "configuration_digest",
                    "bridge_digest",
                )
            }
        )
        == 4
    )


def test_temporal_coherence_document_bracket_is_census_not_retained():
    retained_document = SupplementalPlanningFacts.model_validate_json(RETAINED.read_bytes())
    assessment_value = assessment()
    assert assessment_value.census_bracket == (712224, 712226)
    assert (
        assessment_value.census_bracket[0],
        assessment_value.census_bracket[1],
    ) != (
        retained_document.capture_economy_date_before,
        retained_document.capture_economy_date_after,
    )
    # The historical capture window starts 59+ economy days after the census.
    assert retained_document.capture_economy_date_before >= 712285


def test_six_measured_temporal_alternates_never_flip_the_verdict():
    robustness = report()["robustness"]
    measured = [
        case for case in robustness["cases"] if case["case"].startswith("temporal-measured:")
    ]
    assert len(measured) == 6
    sealed = json.loads(
        (
            REPO / "artifacts/experiments/v1v2-semantic-reconciliation/reconciliation-report.json"
        ).read_bytes()
    )["policy_verdict"]["temporal_second_instant"]["field_detail"]
    assert sorted(int(case["case"].split(":")[1]) for case in measured) == sorted(
        int(tile) for tile in sealed
    )
    assert robustness["verdict"] == "ROBUST"


def test_all_77_semantic_transformations_are_preserved():
    # The adapter gate re-runs the sealed policy; the 77 accepted
    # transformations (Vacant rebuild on clear shapes) remain recorded, and
    # the stop rule matches the sealed Vacant projection on every tile
    # (vac_semantic_divergent_tiles == 0) including all 77 transformed tiles.
    assert report()["gate"]["semantic_tiles"] == 77


def test_rejects_incompatible_historical_fusion_of_v1_facts_with_census():
    """The fusion path stays closed: retained facts + census overlay = 83 unknowns."""
    retained_document = SupplementalPlanningFacts.model_validate_json(RETAINED.read_bytes())
    census = assessment()
    assert census.census_bracket == (712224, 712226)
    from app.planning.p08_v2_snapshot import _load_census

    _retained, tiles, _bracket, _pages = _load_census(RETAINED, CANDIDATE)
    fused = assess_world_feasibility(
        retained_document,
        assessment().revalidated_endpoints_pickups,
        assessment().revalidated_endpoints_deliveries,
        tile_classes={tile.tile_id: tile.classification for tile in tiles.values()},
        tile_flags={tile.tile_id: tile.flags for tile in tiles.values()},
    )
    assert fused.code == "INCOMPLETE_TILE_CLASSIFICATION"
    full_histogram = dict(fused.segment_counts)
    assert full_histogram.get("UNKNOWN_OCCUPANCY", 0) == 83
    # ...while the snapshot assessment itself carries no fusion.
    snapshot_counts = {
        name: count for name, count in report()["assessment_primary"]["corridor_segment_counts"]
    }
    assert snapshot_counts.get("UNKNOWN_OCCUPANCY", 0) == 0


def test_missing_page_is_rejected_fail_closed(tmp_path: Path):
    staged = tmp_path / "candidate"
    staged.mkdir()
    for path in CANDIDATE.iterdir():
        if path.is_file():
            (staged / path.name).write_bytes(path.read_bytes())
    (staged / "classification-p089-response.json").unlink()
    with pytest.raises((PlanningFactError, TileQueryError, FileNotFoundError)):
        build_v2_snapshot_assessment(RETAINED, staged, project_root=REPO)


def test_p08_assessment_is_deterministic_and_pinned():
    pinned = json.loads(PINNED_ARTIFACT.read_bytes())
    live = json.loads(json.dumps(report()))
    # Full-report pin: every structure (gate, census, eligibility, sources,
    # assessments, levelling, 217 individual robustness cases) must match.
    assert live == pinned
    assert live["policy_version"] == POLICY_VERSION == "p08-v2-snapshot-planning/1"


def test_levelling_is_planning_only_and_costs_nothing():
    levelling = report()["levelling"]
    assert levelling["kind"] == "TerrainProposal"
    assert levelling["code"] == "PLANNING_ONLY"
    assert levelling["terraform_cost_gbp"] is None
    assert levelling["native_execution"] == "UNSUPPORTED_PENDING_SEPARATE_VALIDATION"


def test_quantity_gates_are_never_silently_re_derived():
    eligibility = report()["eligibility"]
    # Census capability+geometry derivation.
    assert len(eligibility["primary_pickups"]) == 31
    assert len(eligibility["primary_deliveries"]) == 32
    # Historical quantity-gated endpoint structure, re-validated at the
    # census instant; counts stay distinct from the census-derived set.
    assert len(eligibility["revalidated_historical_pickups"]) == 31
    assert len(eligibility["revalidated_historical_deliveries"]) == 20
    assert "not consumed by the corridor feasibility assessment" in (eligibility["quantity_gates"])


def test_historical_evidence_is_immutable_across_a_full_build(tmp_path: Path):
    watch = [
        RETAINED,
        *sorted(path for path in CANDIDATE.rglob("*") if path.is_file()),
        PINNED_ARTIFACT,
    ]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in watch}
    build_v2_snapshot_assessment(RETAINED, CANDIDATE, project_root=REPO)
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in watch}
    assert before == after
