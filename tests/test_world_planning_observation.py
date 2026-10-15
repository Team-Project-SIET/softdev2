"""Controlled admission at the immutable planning-observation seam; no native runtime."""

import asyncio
from dataclasses import FrozenInstanceError, replace

import pytest
from test_qualification_coordinator import QualificationWire, collect

from app.simulation.openttd.world_planning_observation import WorldPlanningObservation


@pytest.fixture
def qualified_result():
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()
        return await collect(wire, owner)

    return asyncio.run(run())


def test_complete_qualified_pair_is_composed_without_copying(qualified_result):
    final = qualified_result.verification.stability.final
    world = WorldPlanningObservation(final, qualified_result)
    assert world.structural is final and world.qualification is qualified_result
    assert world.production is qualified_result.production
    assert world.complete and world.production.qualified_for_planning
    assert world.qualified_month_identity.economy_month == 2
    assert world.production.qualification.current_month.month == 3
    assert (
        world.production.source_structural_world_digest == world.structural.structural_world_digest
    )
    with pytest.raises(FrozenInstanceError):
        setattr(world, "structural", replace(final))


def _unchecked(value, **changes):
    """Simulate a damaged typed input; admission must rerun the real validators."""
    from copy import copy

    changed = copy(value)
    for field, item in changes.items():
        object.__setattr__(changed, field, item)
    return changed


def _with_production(result, production):
    return _unchecked(result, verification=_unchecked(result.verification, production=production))


def test_before_refactor_serialization_and_digests_are_exact(qualified_result):
    import json
    from pathlib import Path

    before = json.loads(
        (Path(__file__).parent / "fixtures/observation_type_compatibility.json").read_text()
    )
    final = qualified_result.verification.stability.final
    assert final.to_bytes().decode() == before["structural"]
    assert qualified_result.production.to_bytes().decode() == before["production"]
    assert final.structural_world_digest == before["structural_digest"]
    assert qualified_result.production.production_digest == before["production_digest"]


@pytest.mark.parametrize("part", ["structure", "production", "qualification"])
def test_incomplete_or_unqualified_input_rejected(qualified_result, monkeypatch, part):
    from app.simulation.openttd.production_observation import IndustryProductionObservation
    from app.simulation.openttd.structural_world import StructuralWorldObservation

    if part == "structure":
        monkeypatch.setattr(StructuralWorldObservation, "complete", property(lambda _: False))
    elif part == "production":
        monkeypatch.setattr(IndustryProductionObservation, "complete", property(lambda _: False))
    else:
        monkeypatch.setattr(
            IndustryProductionObservation, "qualified_for_planning", property(lambda _: False)
        )
    with pytest.raises(ValueError):
        WorldPlanningObservation(qualified_result.verification.stability.final, qualified_result)


@pytest.mark.parametrize("source_digest", [None, "", "0" * 64])
def test_missing_or_mismatched_source_digest_rejected(qualified_result, source_digest):
    p = qualified_result.production
    damaged = _unchecked(p.qualification, source_structural_world_digest=source_digest)
    result = _with_production(qualified_result, _unchecked(p, qualification=damaged))
    with pytest.raises(ValueError, match="source structural digest mismatch"):
        WorldPlanningObservation(qualified_result.verification.stability.final, result)


def test_missing_qualification_metadata_rejected(qualified_result):
    result = _with_production(
        qualified_result, _unchecked(qualified_result.production, qualification=None)
    )
    with pytest.raises(ValueError, match="qualification metadata"):
        WorldPlanningObservation(qualified_result.verification.stability.final, result)


@pytest.mark.parametrize(
    "defect", ["industry", "cargo", "non_produced", "duplicate", "missing", "extra"]
)
def test_damaged_production_references_or_coverage_rejected(qualified_result, defect):
    p = qualified_result.production
    r = p.records[0]
    changes = {
        "industry": (replace(r, industry_id=999), *p.records[1:]),
        "cargo": (replace(r, cargo_id=62), *p.records[1:]),
        "non_produced": (replace(r, cargo_id=9), *p.records[1:]),
        "duplicate": (r,) * len(p.records),
        "missing": p.records[:-1],
        "extra": (*p.records, r),
    }
    result = _with_production(qualified_result, _unchecked(p, records=changes[defect]))
    with pytest.raises(ValueError):
        WorldPlanningObservation(qualified_result.verification.stability.final, result)


@pytest.mark.parametrize(
    "field", ["process_identity", "connection_identity", "configuration_digest", "bridge", "world"]
)
def test_provenance_mismatch_rejected(qualified_result, field):
    p = qualified_result.production
    context = p.context
    from app.simulation.openttd.observation_identity import BridgePackage

    changes = {
        "process_identity": object(),
        "connection_identity": object(),
        "configuration_digest": "0" * 64,
        "bridge": BridgePackage(context.bridge.directory, "0" * 64),
        "world": replace(context.world, world_id="different-world"),
    }
    result = _with_production(
        qualified_result, _unchecked(p, context=replace(context, **{field: changes[field]}))
    )
    with pytest.raises(ValueError, match="share runtime/world/process/connection"):
        WorldPlanningObservation(qualified_result.verification.stability.final, result)


def test_m1_anchor_or_equal_copy_cannot_replace_actual_final_source(qualified_result):
    stability = qualified_result.verification.stability
    for wrong in (stability.anchor, replace(stability.final)):
        with pytest.raises(ValueError, match="exact final structural source"):
            WorldPlanningObservation(wrong, qualified_result)


@pytest.mark.parametrize("defect", ["event", "clock", "lifetime", "receipt"])
def test_qualification_evidence_is_revalidated(qualified_result, defect):
    result = qualified_result
    if defect == "event":
        result = _unchecked(result, evidence=replace(result.evidence, events=()))
    elif defect == "clock":
        result = _unchecked(result, clock=replace(result.clock, polls=result.clock.polls + 1))
    elif defect == "lifetime":
        s = result.verification.stability
        lifetimes = (replace(s.final_lifetimes[0], construction_date=2), *s.final_lifetimes[1:])
        result = _unchecked(
            result,
            verification=_unchecked(
                result.verification, stability=_unchecked(s, final_lifetimes=lifetimes)
            ),
        )
    else:
        result = _unchecked(result, evidence=replace(result.evidence, native_transactions=()))
    with pytest.raises(ValueError):
        WorldPlanningObservation(qualified_result.verification.stability.final, result)


@pytest.mark.parametrize(
    "industries,produces,metrics",
    [((2,), (1,), (0, 0, 0)), ((), (), (0, 0, 0)), ((2,), (), (0, 0, 0))],
)
def test_zero_production_and_qualified_zero_target_worlds_valid(industries, produces, metrics):
    async def run():
        wire = QualificationWire(industries=industries, produces=produces)
        wire.metrics = metrics
        owner = await wire.owner()
        result = await collect(wire, owner)
        return WorldPlanningObservation(owner.final, result)

    world = asyncio.run(run())
    assert world.complete and world.production.qualified_for_planning
    assert all(r.last_month_produced == 0 for r in world.production.records)


def test_composition_digest_is_semantic_and_deterministic(qualified_result):
    import json

    world = WorldPlanningObservation(
        qualified_result.verification.stability.final, qualified_result
    )
    assert replace(world).composition_digest == world.composition_digest
    payload = json.loads(world.to_bytes())
    assert payload["qualified_month"] == dict(
        economy_year=1950, economy_month=2, start_date=712254, end_date=712282
    )
    assert payload["relevant_industry_lifetimes"] == [
        dict(industry_id=2, construction_date=1),
        dict(industry_id=17, construction_date=1),
    ]
    assert set(payload) == {
        "schema",
        "structural_world_digest",
        "production_digest",
        "qualified_month",
        "relevant_industry_lifetimes",
    }
    assert payload["structural_world_digest"] == world.structural.structural_world_digest
    assert payload["production_digest"] == world.production.production_digest


def test_transient_paths_and_request_identifiers_do_not_change_digest():
    async def run(session_id):
        wire = QualificationWire()
        from pathlib import Path

        from app.simulation.openttd.observation_identity import BridgePackage

        wire.context = replace(
            wire.context,
            bridge=BridgePackage(Path("/transient") / session_id, wire.context.bridge.sha256),
        )
        owner = await wire.owner(session_id=session_id)
        result = await collect(wire, owner)
        return WorldPlanningObservation(owner.final, result)

    a = asyncio.run(run("controlled-a"))
    b = asyncio.run(run("controlled-b"))
    assert (
        a.production.transactions[0].exchange.request_payload
        != b.production.transactions[0].exchange.request_payload
    )
    assert a.composition_digest == b.composition_digest


def test_validated_objects_remain_immutable(qualified_result):
    for value, field, replacement in [
        (qualified_result, "evidence", qualified_result.evidence),
        (qualified_result.production, "records", ()),
        (qualified_result.verification.stability.final, "budget", None),
        (qualified_result.qualified_month_identity, "economy_month", 3),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)


def test_pagination_does_not_change_composition_digest(monkeypatch):
    import app.simulation.openttd.structural_world_session as sessions

    async def run():
        wire = QualificationWire()
        owner = await wire.owner()
        result = await collect(wire, owner)
        return WorldPlanningObservation(owner.final, result)

    a = asyncio.run(run())
    monkeypatch.setattr(sessions, "STRUCTURAL_PAGE_SIZE", 1)
    b = asyncio.run(run())
    assert a.structural.total_requests != b.structural.total_requests
    assert a.composition_digest == b.composition_digest
