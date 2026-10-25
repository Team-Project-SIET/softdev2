"""Fail-closed tests for the delegated ADR-012 census-authority policy layer.

The decision (recorded in
``docs/handoff/2026-10-24/adr-012-six-temporal-tiles-census-authority.md``)
makes the save-instant census authoritative for exactly the six temporal
tiles' tree-lifecycle deltas, for planning evidence only. These tests pin the
application layer's guarantees: never automatic, never broader than the
sealed temporal set, never absorbing contradictions/unresolved evidence,
never mutating the base reconciliation or the sealed bytes, and never opening
the P08 binding gate.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app.simulation.openttd.v2_semantic_reconciliation import (
    AUTHORITY_RESOLVED_OUTCOME,
    CONTRADICTION,
    TEMPORAL,
    VERDICT_POLICY_RESOLVED,
    VERDICT_REJECTED,
    CensusAuthorityDecision,
    FieldOutcome,
    SameStateProvenance,
    SemanticReconciliation,
    TileReconciliation,
    _scope_page_instants,
    apply_census_authority,
    replay_retained_census,
)

PROJECT = Path(__file__).resolve().parents[1]
SEED17_RUN = PROJECT / "artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253"
SEED17_CANDIDATE = PROJECT / "artifacts/demos/classification-exec-seed17-3a8f9e46"
SEALED_REPORT = (
    PROJECT / "artifacts/experiments/v1v2-semantic-reconciliation/reconciliation-report.json"
)

NO_EVIDENCE = pytest.mark.skipif(
    not (SEED17_RUN / "network-facts-0.json").is_file() or not SEED17_CANDIDATE.is_dir(),
    reason="retained Seed 17 evidence absent",
)


def make_base(
    tiles: tuple[TileReconciliation, ...],
    temporal: tuple[int, ...],
    *,
    instants: tuple[tuple[int, int, int], ...] = (),
    hygiene: tuple[str, ...] = (),
    completeness: bool = True,
    manifest: bool = True,
    contradictions: tuple[int, ...] = (),
) -> SemanticReconciliation:
    return SemanticReconciliation(
        policy_version="vacant-projection-1",
        retained_facts_sha256="0" * 64,
        census_page_payload_sha256="0" * 64,
        provenance=SameStateProvenance(
            census_page_dates=(712224, 712225),
            retained_date_before=712285,
            retained_date_after=712291,
        ),
        region=(170, 171, 15, 30),
        census_pages=len(instants) or 2,
        census_tiles=len(tiles),
        census_class_counts=dict(sorted(Counter({"TREES": 1}).items())),
        retained_class_counts=dict(sorted(Counter({"TREES": 1}).items())),
        identity_failures=(),
        hygiene_failures=hygiene,
        raw_gate_tiles=tuple((t.tile_id, "PROJECTED_FLAGS_DIFFER") for t in tiles),
        tiles=tiles,
        completeness_reproduced=completeness,
        manifest_verified=manifest,
        manifest_entries=len(tiles),
        semantic_tiles=(),
        temporal_tiles=temporal,
        contradiction_tiles=contradictions,
        unresolved_tiles=(),
        census_tile_instants=instants,
    )


def temporal_tile(tile_id: int) -> TileReconciliation:
    return TileReconciliation(
        tile_id=tile_id,
        raw_gate_disagrees=True,
        status=TEMPORAL,
        field_outcomes=(
            FieldOutcome(field="tree", retained_value=True, census_value=False, outcome=TEMPORAL),
            FieldOutcome(field="rough", retained_value=True, census_value=False, outcome=TEMPORAL),
        ),
    )


def contradiction_tile(tile_id: int) -> TileReconciliation:
    return TileReconciliation(
        tile_id=tile_id,
        raw_gate_disagrees=True,
        status=CONTRADICTION,
        field_outcomes=(
            FieldOutcome(
                field="tree", retained_value=True, census_value=False, outcome=CONTRADICTION
            ),
        ),
    )


def decision(temporal: tuple[int, ...], **kw) -> CensusAuthorityDecision:
    return CensusAuthorityDecision(scope_tiles=frozenset(temporal), **kw)


def instants(temporal: tuple[int, ...]) -> dict[int, int]:
    return {tile: 712224 for tile in temporal}


class TestRefusalPaths:
    def test_scope_must_equal_temporal_set(self):
        base = make_base((temporal_tile(100), temporal_tile(200)), (100, 200))
        narrower = apply_census_authority(base, decision((100,)), instants((100,)))
        assert narrower.refused_reason is not None and "scope" in narrower.refused_reason
        assert narrower.verdict == base.verdict()  # refuses; never upgrades the base
        assert narrower.resolved_field_rows == ()

        empty = apply_census_authority(base, decision(()), {})
        assert empty.refused_reason is not None and "scope" in empty.refused_reason

    def test_empty_scope_never_upgrades_a_rejected_base(self):
        base = make_base((contradiction_tile(100),), (), contradictions=(100,))
        # a contradiction tile is never part of the temporal set; an empty
        # scope therefore resolves nothing and the rejected base stands
        applied = apply_census_authority(base, decision(()), {})
        assert applied.resolved_field_rows == ()
        assert applied.verdict == VERDICT_REJECTED

    def test_hygiene_failure_refuses_the_whole_application(self):
        base = make_base(
            (temporal_tile(100),), (100,), hygiene=("CENSUS_TILE_DUPLICATED:100",)
        )
        applied = apply_census_authority(base, decision((100,)), instants((100,)))
        assert applied.refused_reason == "identity or census hygiene failures present"
        assert applied.verdict == VERDICT_REJECTED

    def test_unreproduced_completeness_refuses(self):
        base = make_base((temporal_tile(100),), (100,), completeness=False)
        applied = apply_census_authority(base, decision((100,)), instants((100,)))
        assert applied.refused_reason == "sealed census completeness not reproduced"

    def test_unverified_manifest_refuses(self):
        base = make_base((temporal_tile(100),), (100,), manifest=False)
        applied = apply_census_authority(base, decision((100,)), instants((100,)))
        assert applied.refused_reason == "candidate artifact manifest unverified"

    def test_field_outside_the_declared_scope_refuses_only_that_tile(self):
        base = make_base((temporal_tile(100),), (100,))
        narrow = decision((100,), acceptable_fields=frozenset({"tree"}))
        applied = apply_census_authority(base, narrow, instants((100,)))
        assert applied.refused_tiles == (
            (100, "field rough is not in the decision's declared fields"),
        )
        assert applied.resolved_field_rows == ()
        # the base verdict is still partial, but the policy verdict must not
        # claim resolution while refusals stand
        assert applied.verdict != VERDICT_POLICY_RESOLVED

    def test_contradiction_blocks_the_policy_verdict(self):
        base = make_base(
            (temporal_tile(100), contradiction_tile(300)),
            (100,),
            contradictions=(300,),
        )
        applied = apply_census_authority(base, decision((100,)), instants((100,)))
        # the temporal tile is policy-resolved, but the base verdict is
        # REJECTED (contradiction) and the derived verdict must not upgrade it
        assert len(applied.resolved_field_rows) == 1
        assert applied.verdict == VERDICT_REJECTED
        assert applied.p08_binding()["allowed"] is False


class TestPreservationGuarantees:
    def test_accepted_rows_keep_both_values_verbatim(self):
        base = make_base((temporal_tile(100),), (100,))
        applied = apply_census_authority(base, decision((100,)), {100: 712285})
        tile, payload = applied.resolved_field_rows[0]
        assert tile == 100
        rows = payload["fields"]
        assert {(r["field"], r["retained_value"], r["census_value"]) for r in rows} == {
            ("tree", True, False),
            ("rough", True, False),
        }
        assert all(r["policy_outcome"] == AUTHORITY_RESOLVED_OUTCOME for r in rows)
        assert rows[0]["base_outcome"] == "TEMPORAL_SECOND_INSTANT"
        assert rows[0]["census_page_economy_date"] == 712285

    def test_definitional_rows_pass_through_untouched(self):
        from app.simulation.openttd.v2_semantic_reconciliation import (
            SEMANTIC_BUILDABLE_ACCEPTANCE,
        )

        tile = TileReconciliation(
            tile_id=100,
            raw_gate_disagrees=True,
            status=TEMPORAL,
            field_outcomes=(
                FieldOutcome(
                    field="tree", retained_value=True, census_value=False, outcome=TEMPORAL
                ),
                FieldOutcome(
                    field="buildable",
                    retained_value=True,
                    census_value=False,
                    outcome=SEMANTIC_BUILDABLE_ACCEPTANCE,
                ),
            ),
        )
        base = make_base((tile,), (100,))
        applied = apply_census_authority(base, decision((100,)), instants((100,)))
        assert applied.refused_tiles == () and applied.refused_reason is None
        _tile, payload = applied.resolved_field_rows[0]
        assert [r["field"] for r in payload["fields"]] == ["tree"]
        passthrough = payload["definitional_passthrough"]
        assert passthrough[0]["base_outcome"] == SEMANTIC_BUILDABLE_ACCEPTANCE
        assert "vacant-projection-1" in passthrough[0]["note"]

    def test_base_object_is_untouched_by_the_application(self):
        base = make_base((temporal_tile(100),), (100,))
        before = base.report()["tile_ledger"]["100"]["status"]
        apply_census_authority(base, decision((100,)), instants((100,)))
        after = base.report()["tile_ledger"]["100"]["status"]
        assert before == after == TEMPORAL
        assert base.temporal_tiles == (100,)

    def test_p08_binding_never_opens(self):
        base = make_base((temporal_tile(100),), (100,))
        applied = apply_census_authority(base, decision((100,)), instants((100,)))
        binding = applied.p08_binding()
        assert binding["allowed"] is False
        assert binding["preserved_retained_status"] == "INCOMPLETE_TILE_CLASSIFICATION"
        assert "ADR-010" in binding["gate"]


class TestPageInstantChecks:
    def test_scope_page_instants_refuses_non_single_instant_pages(self):
        base = make_base(
            (temporal_tile(100),), (100,), instants=((100, 712224, 712225),)
        )
        with pytest.raises(ValueError, match="non-single-instant"):
            _scope_page_instants(base, decision((100,)))

    def test_scope_page_instants_requires_every_scope_tile(self):
        base = make_base((temporal_tile(100),), (100,), instants=())
        with pytest.raises(ValueError, match="missing for scope tiles"):
            _scope_page_instants(base, decision((100,)))


@NO_EVIDENCE
class TestSeed17SealedReplay:
    def test_all_six_tiles_resolve_and_the_base_bytes_do_not_move(self):
        reconciliation = replay_retained_census(
            SEED17_RUN / "network-facts-0.json", SEED17_CANDIDATE
        )
        before = reconciliation.to_json_bytes()
        assert before == SEALED_REPORT.read_bytes()
        assert reconciliation.temporal_tiles == (43951, 47286, 47288, 48042, 48309, 51378)

        delegated = decision(reconciliation.temporal_tiles)
        applied = apply_census_authority(
            reconciliation,
            delegated,
            _scope_page_instants(reconciliation, delegated),
        )
        assert applied.refused_reason is None and applied.refused_tiles == ()
        assert applied.verdict == VERDICT_POLICY_RESOLVED
        assert [t for t, _ in applied.resolved_field_rows] == [
            43951,
            47286,
            47288,
            48042,
            48309,
            51378,
        ]
        for _tile, payload in applied.resolved_field_rows:
            for row in payload["fields"]:
                assert row["policy_outcome"] == AUTHORITY_RESOLVED_OUTCOME
                assert isinstance(row["census_page_economy_date"], int)
        # base report bytes identical after the policy application
        assert reconciliation.to_json_bytes() == before
        # derived report is deterministic and separately schema-labeled
        report = applied.to_json_bytes()
        assert b"v1v2-census-authority-policy-report/1" in report
        assert applied.to_json_bytes() == report
