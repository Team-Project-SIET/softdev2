"""Focused tests for the offline P08 ADR-012/ADR-013 policy rebinding passes.

The ADR-012 rebinding consumes the derived census-authority policy report and
records exactly which sealed temporal rows it covers for P08 planning. The
ADR-013 application maps exactly the 19 definitional retained-UNKNOWN tiles to
``TERRAIN_MODIFICATION`` under native ``IsBuildable`` semantics, and a separate
combined rebinding consumes both policy reports. Neither layer is evidence:
both re-derive from sealed inputs and refuse anything stale, edited, narrowed,
widened or out of scope. The base ledger, sealed report bytes and the fusion
gate remain untouched.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.planning.p08_terrain import (
    SegmentClass,
    _legacy_segment,
    classify_segment,
)
from app.planning.p08_v2_snapshot import (
    UNKNOWN_OCCUPANCY_ROOT_CAUSE,
    _load_census,
    build_v2_snapshot_assessment,
    diagnose_unknown_occupancy,
)
from app.simulation.openttd.tile_classification import projection_disagrees
from app.simulation.openttd.v2_semantic_reconciliation import (
    AUTHORITY_DECISION_ADR,
    AUTHORITY_DECISION_TOKEN,
    NATIVE_ISBUILDABLE_BASE_COUNTS,
    NATIVE_ISBUILDABLE_DECISION_ADR,
    NATIVE_ISBUILDABLE_DECISION_TOKEN,
    NATIVE_ISBUILDABLE_DERIVED_CLASS,
    NATIVE_ISBUILDABLE_SCOPE_TILES,
    NATIVE_ISBUILDABLE_VERDICT,
    POLICY_REPORT_SCHEMA,
    REBINDING_REPORT_SCHEMA,
    VERDICT_POLICY_RESOLVED,
    CensusAuthorityDecision,
    NativeIsBuildableDecision,
    _scope_page_instants,
    apply_census_authority,
    apply_native_isbuildable_policy,
    rebind_p08_native_isbuildable,
    rebind_p08_policy,
    replay_retained_census,
)

PROJECT = Path(__file__).resolve().parents[1]
RETAINED = (
    PROJECT / "artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json"
)
CANDIDATE = PROJECT / "artifacts/demos/classification-exec-seed17-3a8f9e46"
SEALED_REPORT = (
    PROJECT / "artifacts/experiments/v1v2-semantic-reconciliation/reconciliation-report.json"
)
POLICY_REPORT = (
    PROJECT
    / "artifacts/experiments/v1v2-semantic-reconciliation/census-authority-policy-report.json"
)

SIX_TILES = (43951, 47286, 47288, 48042, 48309, 51378)

NO_EVIDENCE = pytest.mark.skipif(
    not (RETAINED.is_file() and (CANDIDATE / "classification-p000-response.json").is_file()),
    reason="retained Seed 17 evidence absent",
)


@pytest.fixture(scope="module")
def sealed():
    return replay_retained_census(RETAINED, CANDIDATE)


@pytest.fixture(scope="module")
def loaded():
    return _load_census(RETAINED, CANDIDATE)


def derived_bytes(base) -> bytes:
    decision = CensusAuthorityDecision(scope_tiles=frozenset(base.temporal_tiles))
    return apply_census_authority(
        base, decision, _scope_page_instants(base, decision)
    ).to_json_bytes()


def policy_document() -> dict:
    return json.loads(POLICY_REPORT.read_bytes())


@NO_EVIDENCE
class TestSealedRebinding:
    def test_valid_rebinding_preserves_provenance_and_keeps_p08_unbound(self, sealed):
        report = POLICY_REPORT.read_bytes()
        before = sealed.to_json_bytes()
        binding = rebind_p08_policy(sealed, report)

        assert binding.resolved_tiles == SIX_TILES
        assert tuple(sealed.temporal_tiles) == SIX_TILES
        assert binding.base_verdict == sealed.verdict()
        assert binding.policy_verdict == VERDICT_POLICY_RESOLVED
        assert binding.allowed is False
        assert binding.unresolved_classification_tiles == 19
        assert any("19 retained-UNKNOWN" in blocker for blocker in binding.blockers)

        out = binding.report()
        assert out["schema"] == REBINDING_REPORT_SCHEMA
        assert out["decision"]["adr"] == AUTHORITY_DECISION_ADR
        assert out["decision"]["token"] == AUTHORITY_DECISION_TOKEN
        assert out["p08_binding"]["allowed"] is False
        assert (
            out["p08_binding"]["preserved_retained_status"]
            == "INCOMPLETE_TILE_CLASSIFICATION"
        )
        assert out["resolved_tiles"] == list(SIX_TILES)
        # The resolved rows are the derived policy report's rows, verbatim.
        assert out["resolved_field_rows"] == policy_document()["resolved_field_rows"]
        assert out["retained_segmentation_counts"] == {
            "ROAD_BUILDABLE": 339,
            "SUPPORTED_CLEARING": 63,
            "UNKNOWN_OCCUPANCY": 19,
            "UNSUPPORTED_CONSTRUCTION": 29,
        }

        # Provenance: deterministic hashes of the exact inputs, never a
        # re-labelling of either file.
        assert binding.base_report_sha256 == hashlib.sha256(before).hexdigest()
        assert binding.policy_report_sha256 == hashlib.sha256(report).hexdigest()
        assert binding.retained_facts_sha256 == sealed.retained_facts_sha256
        assert binding.census_page_payload_sha256 == sealed.census_page_payload_sha256
        assert out["provenance"]["base_report_sha256"] == binding.base_report_sha256
        assert out["provenance"]["policy_report_sha256"] == binding.policy_report_sha256

        # Neither the base object nor the sealed report bytes move.
        assert sealed.to_json_bytes() == before
        assert before == SEALED_REPORT.read_bytes()
        assert hashlib.sha256(POLICY_REPORT.read_bytes()).digest() == hashlib.sha256(
            report
        ).digest()

    def test_rebinding_is_byte_deterministic(self, sealed):
        first = rebind_p08_policy(sealed, POLICY_REPORT.read_bytes())
        second = rebind_p08_policy(sealed, POLICY_REPORT.read_bytes())
        assert first.to_json_bytes() == second.to_json_bytes()
        assert first.to_json_bytes().endswith(b"\n")
        assert b'"allowed": false' in first.to_json_bytes()

    def test_snapshot_assessment_embeds_rebinding_without_changing_the_base_report(
        self, sealed
    ):
        plain = build_v2_snapshot_assessment(RETAINED, CANDIDATE, project_root=PROJECT)
        bound = build_v2_snapshot_assessment(
            RETAINED,
            CANDIDATE,
            project_root=PROJECT,
            policy_report=POLICY_REPORT,
        )
        plain_report = plain.report()
        bound_report = bound.report()
        assert "policy_rebinding" not in plain_report
        assert "unknown_occupancy_diagnosis" not in plain_report
        section = bound_report.pop("policy_rebinding")
        diagnosis = bound_report.pop("unknown_occupancy_diagnosis")

        # Every other assessment field (planning input, gate, assessments,
        # robustness) is untouched by the rebinding.
        assert plain_report == bound_report
        assert section["resolved_tiles"] == list(SIX_TILES)
        assert section["p08_binding"]["allowed"] is False
        assert section["base_verdict"] == "SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED"
        assert diagnosis["count"] == 19
        assert diagnosis["resolved"] is False

    def test_snapshot_refuses_a_tampered_policy_report(self, tmp_path):
        document = policy_document()
        document["resolved_field_rows"][0]["fields"][0]["census_value"] = "tampered"
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValueError, match="P08 policy rebinding refused"):
            build_v2_snapshot_assessment(
                RETAINED, CANDIDATE, project_root=PROJECT, policy_report=path
            )


class TestRefusalPaths:
    def test_missing_evidence_is_refused(self, sealed):
        for payload in (None, b"", b"   "):
            with pytest.raises(ValueError, match="derived policy report missing"):
                rebind_p08_policy(sealed, payload)

    def test_malformed_json_is_refused(self, sealed):
        with pytest.raises(ValueError, match="not valid JSON"):
            rebind_p08_policy(sealed, b"{not json")
        with pytest.raises(ValueError, match="not a JSON object"):
            rebind_p08_policy(sealed, b"[]")

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            (lambda d: d.update(schema="wrong/1"), "unexpected schema"),
            (lambda d: d["decision"].update(adr="ADR-999"), "is not ADR-012"),
            (lambda d: d["decision"].update(token="SOMETHING_ELSE"), "decision token"),
            (lambda d: d.update(refused_reason="nope"), "records refusals"),
            (lambda d: d.update(verdict="REJECTED"), "derived policy verdict"),
            (lambda d: d.update(base_verdict="REJECTED"), "base_verdict"),
            (
                lambda d: d["decision"].update(scope_tiles=[43951]),
                "not exactly the sealed temporal set",
            ),
            (
                lambda d: d["decision"].update(scope_tiles=sorted(SIX_TILES + (100,))),
                "not exactly the sealed temporal set",
            ),
            (
                lambda d: d["resolved_field_rows"].append(
                    {
                        "tile_id": 100,
                        "fields": [],
                    }
                ),
                "outside ADR-012's temporal scope",
            ),
            (
                lambda d: d["resolved_field_rows"][0]["fields"][0].update(
                    retained_value="not-the-observation"
                ),
                "does not preserve the sealed base evidence verbatim",
            ),
            (
                lambda d: d["base_prepared_status_verbatim"].update(
                    retained_segmentation_counts={"ROAD_BUILDABLE": 450}
                ),
                "retained segmentation counts drifted",
            ),
        ],
    )
    def test_invalid_or_out_of_scope_reports_are_refused(self, sealed, mutate, message):
        document = policy_document()
        mutate(document)
        with pytest.raises(ValueError, match=message):
            rebind_p08_policy(sealed, json.dumps(document).encode())

    def test_scope_beyond_adr_012_fields_is_refused(self, sealed):
        document = policy_document()
        document["decision"]["acceptable_fields"] = ["tree", "air_transport"]
        with pytest.raises(ValueError, match="exceed ADR-012's scope"):
            rebind_p08_policy(sealed, json.dumps(document).encode())

    def test_duplicate_tile_is_refused(self, sealed):
        document = policy_document()
        document["resolved_field_rows"].append(dict(document["resolved_field_rows"][0]))
        with pytest.raises(ValueError, match="resolved twice"):
            rebind_p08_policy(sealed, json.dumps(document).encode())

    def test_base_drift_is_refused(self, sealed):
        drifted = replace(sealed, retained_class_counts={"ROAD_BUILDABLE": 450})
        with pytest.raises(ValueError, match="retained segmentation counts drifted"):
            rebind_p08_policy(drifted, POLICY_REPORT.read_bytes())

    def test_contradictory_base_can_never_be_rebound(self, sealed):
        contradiction = replace(sealed, contradiction_tiles=(999,))
        with pytest.raises(ValueError, match="not the policy-partial state"):
            rebind_p08_policy(contradiction, derived_bytes(contradiction))

    def test_established_base_has_nothing_to_rebind(self, sealed):
        established = replace(sealed, temporal_tiles=())
        with pytest.raises(ValueError, match="not the policy-partial state"):
            rebind_p08_policy(established, derived_bytes(established))

    def test_report_from_a_different_base_is_refused(self, sealed):
        drifted = replace(
            sealed, census_class_counts={**sealed.census_class_counts, "CLEAR": 999}
        )
        with pytest.raises(ValueError, match="census segmentation counts drifted"):
            rebind_p08_policy(drifted, POLICY_REPORT.read_bytes())

    def test_schema_requires_the_policy_report_schema(self, sealed):
        document = policy_document()
        assert document["schema"] == POLICY_REPORT_SCHEMA
        document["schema"] = "v1v2-semantic-reconciliation-report/1"
        with pytest.raises(ValueError, match="unexpected schema"):
            rebind_p08_policy(sealed, json.dumps(document).encode())


class TestUnknownOccupancyDiagnosis:
    def test_all_19_form_one_definitional_group(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        diagnosis = diagnose_unknown_occupancy(retained, census, sealed)

        assert diagnosis["schema"] == "p08-unknown-occupancy-diagnosis/1"
        assert diagnosis["count"] == 19
        assert diagnosis["resolved"] is False
        assert diagnosis["all_evidence_consistent"] is True
        assert len(diagnosis["groups"]) == 1
        group = diagnosis["groups"][0]
        assert group["root_cause"] == UNKNOWN_OCCUPANCY_ROOT_CAUSE
        assert group["count"] == 19
        assert group["slopes"] == [8, 9, 12, 13]
        assert group["census_classes"] == ["CLEAR"]
        assert group["reconciliation_statuses"] == ["SEMANTIC_RECONCILED"]
        assert set(group["tiles"]) == {
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
        }
        assert "authorization" in " ".join(diagnosis["resolution_requires"])
        assert diagnosis["not_established"].startswith("the 19 tiles stay UNKNOWN_OCCUPANCY")

    def test_diagnosis_is_byte_deterministic(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        first = diagnose_unknown_occupancy(retained, census, sealed)
        second = diagnose_unknown_occupancy(retained, census, sealed)
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_diagnosis_does_not_infer_when_evidence_disagrees(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        corrupt_tile = 46517
        tiles = tuple(
            replace(tile, status="GENUINE_CONTRADICTION")
            if tile.tile_id == corrupt_tile
            else tile
            for tile in sealed.tiles
        )
        diagnosis = diagnose_unknown_occupancy(
            retained, census, replace(sealed, tiles=tiles)
        )
        assert diagnosis["all_evidence_consistent"] is False
        row = next(r for r in diagnosis["tiles"] if r["tile_id"] == corrupt_tile)
        assert row["root_cause"] == "UNEXPLAINED_OR_CONTRADICTORY_EVIDENCE"
        # Still not resolved: a disagreement only downgrades the diagnosis.
        assert diagnosis["resolved"] is False

    def test_diagnosis_does_not_change_the_p08_blocker(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        diagnosis = diagnose_unknown_occupancy(retained, census, sealed)
        before = rebind_p08_policy(sealed, POLICY_REPORT.read_bytes())
        assert before.allowed is False
        assert before.unresolved_classification_tiles == diagnosis["count"]
        assert any("19 retained-UNKNOWN" in blocker for blocker in before.blockers)


def native_policy_bytes(sealed, loaded, decision=None) -> bytes:
    retained, census, _bracket, _pages = loaded
    return apply_native_isbuildable_policy(
        sealed,
        retained,
        census,
        decision or NativeIsBuildableDecision(),
    ).to_json_bytes()


class TestNativeIsBuildablePolicy:
    """ADR-013 application and separate combined P08 rebinding pass."""

    PROPOSED_SCOPE = tuple(sorted(NATIVE_ISBUILDABLE_SCOPE_TILES))

    def test_scope_mapping_and_evidence_are_sealed_and_consistent(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        unknown = tuple(
            sorted(
                fact.tile_id
                for fact in retained.tiles
                if _legacy_segment(fact)[0] is SegmentClass.UNKNOWN_OCCUPANCY
            )
        )
        assert unknown == self.PROPOSED_SCOPE

        ledger = {tile.tile_id: tile for tile in sealed.tiles}
        instants = {tile: (before, after) for tile, before, after in sealed.census_tile_instants}
        for tile_id in unknown:
            observation = census[tile_id]
            census_fact = observation.fact()
            assert observation.classification == "CLEAR"
            assert observation.owner == -1
            assert census_fact.buildable is True
            assert projection_disagrees(census_fact, observation.flags) is False
            assert instants[tile_id][0] == instants[tile_id][1] == 712225
            assert census_fact.slope != 0
            segment, reason = classify_segment(
                census_fact, observation.classification, flags=observation.flags
            )
            assert segment is SegmentClass.TERRAIN_MODIFICATION
            assert reason == "classified-clear-sloped"
            row = ledger[tile_id]
            assert row.status == "SEMANTIC_RECONCILED"
            assert [(o.field, o.outcome) for o in row.field_outcomes] == [
                ("buildable", "SEMANTIC_V1_VACANT_VS_NATIVE_ISBUILDABLE")
            ]

    def test_application_maps_all_19_and_never_mutates_the_base(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        before = sealed.to_json_bytes()
        applied = apply_native_isbuildable_policy(
            sealed, retained, census, NativeIsBuildableDecision()
        )

        assert applied.refused_reason is None
        assert applied.verdict == NATIVE_ISBUILDABLE_VERDICT
        assert [tile for tile, _row in applied.resolved_field_rows] == list(
            self.PROPOSED_SCOPE
        )
        assert applied.derived_segmentation_counts == {
            **NATIVE_ISBUILDABLE_BASE_COUNTS,
            "UNKNOWN_OCCUPANCY": 0,
            "TERRAIN_MODIFICATION": 19,
        }
        for _tile, payload in applied.resolved_field_rows:
            assert payload["derived_segment_class"] == NATIVE_ISBUILDABLE_DERIVED_CLASS
            assert payload["mapping_reason"] == "classified-clear-sloped"
            assert len(payload["fields"]) == 1
            field = payload["fields"][0]
            assert field["field"] == "buildable"
            assert field["retained_value"] is False
            assert field["census_value"] is False
            assert field["census_native_isbuildable"] is True
            assert field["policy_outcome"] == "NATIVE_ISBUILDABLE_TERRAIN_MODIFICATION"
        assert sealed.to_json_bytes() == before
        assert dict(sealed.retained_class_counts) == NATIVE_ISBUILDABLE_BASE_COUNTS
        assert applied.p08_binding()["allowed"] is False
        assert applied.p08_binding()["preserved_retained_status"] == (
            "INCOMPLETE_TILE_CLASSIFICATION"
        )
        first = applied.to_json_bytes()
        second = apply_native_isbuildable_policy(
            sealed, retained, census, NativeIsBuildableDecision()
        ).to_json_bytes()
        assert first == second
        assert first.endswith(b"\n")

    def test_separate_rebinding_consumes_both_policies_and_binds_planning_only(
        self, sealed, loaded
    ):
        retained, census, _bracket, _pages = loaded
        before = sealed.to_json_bytes()
        policy = native_policy_bytes(sealed, loaded)
        combined = rebind_p08_native_isbuildable(
            sealed,
            policy,
            retained,
            census,
            census_authority_report_bytes=POLICY_REPORT.read_bytes(),
        )

        assert combined.allowed is True
        assert combined.resolved_temporal_tiles == (43951, 47286, 47288, 48042, 48309, 51378)
        assert combined.resolved_unknown_tiles == self.PROPOSED_SCOPE
        assert combined.derived_segmentation_counts == {
            **NATIVE_ISBUILDABLE_BASE_COUNTS,
            "UNKNOWN_OCCUPANCY": 0,
            "TERRAIN_MODIFICATION": 19,
        }
        out = combined.report()
        assert out["schema"] == "v1v2-p08-native-isbuildable-rebinding/1"
        assert out["decision"]["adr"] == NATIVE_ISBUILDABLE_DECISION_ADR
        assert out["decision"]["token"] == NATIVE_ISBUILDABLE_DECISION_TOKEN
        assert out["unresolved_classification"]["count"] == 0
        assert out["p08_binding"]["allowed"] is True
        assert out["p08_binding"]["preserved_retained_status"] is None
        assert out["p08_binding"]["p08_complete"] is False
        assert out["fusion_gate"] == {
            "status": "CLOSED",
            "opened": False,
            "reason": "sealed SOURCE_SAVE_FUSION verdict is immutable; "
            "this policy pass does not relabel or fuse it",
        }
        assert sealed.to_json_bytes() == before
        assert combined.to_json_bytes() == combined.to_json_bytes()

    def test_rebinding_requires_the_adr_012_report(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        with pytest.raises(ValueError, match="P08 policy rebinding refused"):
            rebind_p08_native_isbuildable(
                sealed,
                native_policy_bytes(sealed, loaded),
                retained,
                census,
                census_authority_report_bytes=b"",
            )

    def test_rebinding_refuses_tampered_adr_013_evidence(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        document = json.loads(native_policy_bytes(sealed, loaded))
        document["resolved_field_rows"][0]["derived_segment_class"] = "ROAD_BUILDABLE"
        with pytest.raises(ValueError, match="not the deterministic derivation"):
            rebind_p08_native_isbuildable(
                sealed,
                json.dumps(document).encode(),
                retained,
                census,
                census_authority_report_bytes=POLICY_REPORT.read_bytes(),
            )

    def test_rebinding_refuses_a_changed_decision_date(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        document = json.loads(native_policy_bytes(sealed, loaded))
        document["decision"]["date"] = "2026-10-26"
        with pytest.raises(ValueError, match="decision date"):
            rebind_p08_native_isbuildable(
                sealed,
                json.dumps(document).encode(),
                retained,
                census,
                census_authority_report_bytes=POLICY_REPORT.read_bytes(),
            )

    def test_application_refuses_a_changed_decision_date(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        applied = apply_native_isbuildable_policy(
            sealed,
            retained,
            census,
            NativeIsBuildableDecision(date="2026-10-26"),
        )
        assert applied.refused_reason is not None
        assert applied.resolved_field_rows == ()

    def test_rebinding_refuses_a_widened_scope(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        document = json.loads(native_policy_bytes(sealed, loaded))
        document["decision"]["scope_tiles"].append(100)
        with pytest.raises(ValueError, match="sealed evidence cannot support ADR-013"):
            rebind_p08_native_isbuildable(
                sealed,
                json.dumps(document).encode(),
                retained,
                census,
                census_authority_report_bytes=POLICY_REPORT.read_bytes(),
            )

    def test_application_refuses_a_non_authorized_scope(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        before = sealed.to_json_bytes()
        applied = apply_native_isbuildable_policy(
            sealed,
            retained,
            census,
            NativeIsBuildableDecision(scope_tiles=frozenset({46517})),
        )
        assert applied.refused_reason is not None
        assert applied.resolved_field_rows == ()
        assert applied.verdict == sealed.verdict()
        assert sealed.to_json_bytes() == before

    def test_application_refuses_non_single_instant_evidence(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        instants = tuple(
            (tile, before, before + 1) if tile == 46517 else (tile, before, after)
            for tile, before, after in sealed.census_tile_instants
        )
        drift = replace(sealed, census_tile_instants=instants)
        applied = apply_native_isbuildable_policy(
            drift, retained, census, NativeIsBuildableDecision()
        )
        assert applied.refused_reason is not None
        assert applied.resolved_field_rows == ()

    def test_application_refuses_contradictory_base(self, sealed, loaded):
        retained, census, _bracket, _pages = loaded
        drift = replace(sealed, contradiction_tiles=(46517,))
        applied = apply_native_isbuildable_policy(
            drift, retained, census, NativeIsBuildableDecision()
        )
        assert applied.refused_reason is not None
        assert applied.resolved_field_rows == ()

    def test_snapshot_embeds_combined_rebinding_without_changing_the_base(
        self, sealed, loaded, tmp_path
    ):
        policy_path = tmp_path / "census-authority-policy-report.json"
        policy_path.write_bytes(POLICY_REPORT.read_bytes())
        native_path = tmp_path / "native-isbuildable-policy-report.json"
        native_path.write_bytes(native_policy_bytes(sealed, loaded))

        plain = build_v2_snapshot_assessment(RETAINED, CANDIDATE, project_root=PROJECT)
        bound = build_v2_snapshot_assessment(
            RETAINED,
            CANDIDATE,
            project_root=PROJECT,
            policy_report=policy_path,
            native_isbuildable_report=native_path,
        )
        plain_report = plain.report()
        bound_report = bound.report()
        assert "policy_rebinding" not in plain_report
        assert "native_isbuildable_rebinding" not in plain_report
        assert "unknown_occupancy_diagnosis" not in plain_report
        assert bound_report.pop("policy_rebinding")["p08_binding"]["allowed"] is False
        diagnosis = bound_report.pop("unknown_occupancy_diagnosis")
        assert diagnosis["count"] == 19 and diagnosis["resolved"] is False
        combined = bound_report.pop("native_isbuildable_rebinding")
        assert combined["p08_binding"]["allowed"] is True
        assert combined["p08_binding"]["p08_complete"] is False
        assert combined["fusion_gate"]["opened"] is False
        assert plain_report == bound_report

    def test_snapshot_requires_adr_012_when_adr_013_is_supplied(self, sealed, loaded, tmp_path):
        native_path = tmp_path / "native-isbuildable-policy-report.json"
        native_path.write_bytes(native_policy_bytes(sealed, loaded))
        with pytest.raises(Exception, match="ADR-013 rebinding requires the ADR-012"):
            build_v2_snapshot_assessment(
                RETAINED,
                CANDIDATE,
                project_root=PROJECT,
                native_isbuildable_report=native_path,
            )
