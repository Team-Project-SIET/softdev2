"""Combined accounting contract tests use synthetic frames and encrypted peers."""

import asyncio

import pytest

from app.simulation.openttd.admin_protocol import encode_admin_frame
from app.simulation.openttd.proof.raw_production_contract import (
    FRAME_LIMITS,
    MAX_TOTAL_POST_AUTH_FRAMES,
    RawProductionFrameBudget,
    raw_production_contract,
    raw_production_contract_digest,
)
from app.simulation.openttd.proof.structural_contract import StructuralFrameBudget


def test_bounds_preserve_independent_phase_limits_and_single_session_overhead():
    contract = raw_production_contract()
    limits = contract["phase_limits"]
    assert sum(v["requests"] for v in limits.values()) == 608
    assert sum(v["response_bytes"] for v in limits.values()) == 220672
    assert sum(v["query_operations"] for v in limits.values()) == 5120
    assert limits["production"] == dict(
        requests=512,
        records=512,
        response_bytes=171520,
        query_operations=4096,
        per_query_operations=8,
    )
    assert MAX_TOTAL_POST_AUTH_FRAMES == 5126
    assert sum(contract["frame_budget_derivation"].values()) == 5126
    assert contract["frame_limits"] == dict(FRAME_LIMITS)
    assert contract["worst_case_production_response_bytes"] == 335
    assert contract["application_limit"] == 512
    assert contract["native_ceiling"] == 1450


def test_combined_counter_reuses_shared_observer_without_second_accounting_authority():
    budget = RawProductionFrameBudget()
    assert isinstance(budget, StructuralFrameBudget)
    assert RawProductionFrameBudget.observe is StructuralFrameBudget.observe
    assert RawProductionFrameBudget.consume is StructuralFrameBudget.consume
    assert RawProductionFrameBudget.snapshot is StructuralFrameBudget.snapshot
    assert RawProductionFrameBudget.enter is StructuralFrameBudget.enter


def test_exact_query_and_total_frame_bounds_admitted_then_overflow_rejected():
    budget = RawProductionFrameBudget()
    previous = 0
    for phase, limit in FRAME_LIMITS.items():
        if phase != "establishment":
            budget.enter(phase)
        for _ in range(limit):
            budget.observe("outbound", encode_admin_frame(1 if phase == "cleanup" else 7))
        assert budget.total_frames == previous + limit
        previous = budget.total_frames
        if phase == "production":
            assert budget.query_operations == 5120
    assert budget.total_frames == 5126
    assert not budget.failed
    with pytest.raises(ValueError, match="budget"):
        budget.observe("outbound", encode_admin_frame(1))
    assert budget.failed
    assert budget.total_frames == 5126
    assert not budget.snapshot()["frames"][-1]["admitted"]


@pytest.mark.parametrize("phase", tuple(FRAME_LIMITS))
def test_unused_other_phase_budget_cannot_increase_current_limit(phase):
    budget = RawProductionFrameBudget()
    for next_phase in FRAME_LIMITS:
        if next_phase != "establishment":
            budget.enter(next_phase)
        if next_phase == phase:
            break
    budget.consume(phase, FRAME_LIMITS[phase])
    with pytest.raises(ValueError, match="budget"):
        budget.observe("outbound", encode_admin_frame(1 if phase == "cleanup" else 7))
    assert budget.failed


@pytest.mark.parametrize("phase", ("establishment", "setup", "inventory", "capability", "catalog"))
def test_no_counter_reset_subscription_restart_or_phase_resume(phase):
    budget = RawProductionFrameBudget()
    for next_phase in ("setup", "inventory", "capability", "catalog", "production"):
        budget.enter(next_phase)
        budget.consume(next_phase)
    before = budget.snapshot()
    with pytest.raises(ValueError, match="reset/resume"):
        budget.enter(phase)
    assert budget.snapshot() == before


def test_failed_query_budget_latches_but_permits_one_cleanup_frame():
    budget = RawProductionFrameBudget()
    for phase in ("setup", "inventory", "capability", "catalog", "production"):
        budget.enter(phase)
    budget.consume("production", 4096)
    with pytest.raises(ValueError, match="budget"):
        budget.observe("inbound", encode_admin_frame(124))
    with pytest.raises(ValueError, match="later traffic"):
        budget.observe("outbound", encode_admin_frame(6))
    budget.observe("outbound", encode_admin_frame(1))
    assert budget.query_operations == 4096
    assert budget.total_frames == 4097
    assert budget.snapshot()["categories"]["cleanup"] == 1


def test_secure_session_uses_combined_observer_for_establishment_query_and_quit():
    from test_secure_admin import KEY, Writer, server_handshake

    from app.simulation.openttd.gamescript_transport import encode_gamescript
    from app.simulation.openttd.industry_production import IndustryProductionRequest
    from app.simulation.openttd.secure_admin import SecureAdminSession

    async def run():
        reader, writer = asyncio.StreamReader(), Writer()
        budget = RawProductionFrameBudget()
        session = SecureAdminSession(reader, writer, key=KEY, frame_observer=budget.observe)
        wire, _ = server_handshake()
        reader.feed_data(wire)
        await session.authenticate("controlled", "1")
        assert budget.total_frames == 2 and budget.query_operations == 0
        for phase in ("setup", "inventory", "capability", "catalog", "production"):
            budget.enter(phase)
        request = IndustryProductionRequest("controlled-production", 0, 1)
        await session.send(encode_gamescript(request.to_bytes()))
        assert budget.query_operations == 1
        await session.close(quit=True)
        assert budget.total_frames == 4
        assert session._frame_observer.__self__ is budget
        assert writer.closed

    asyncio.run(run())


def test_contract_is_deterministic_and_never_claims_qualification_or_p08():
    first = raw_production_contract()
    first["frame_limits"]["production"] = 1
    assert raw_production_contract()["frame_limits"]["production"] == 4096
    assert raw_production_contract_digest() == raw_production_contract_digest()
    assert not raw_production_contract()["qualified_for_planning"]
    assert raw_production_contract()["rollovers_observed"] == 0
    assert not raw_production_contract()["p08_completion"]
    assert raw_production_contract()["production_level"] == "DEFERRED / NOT INCLUDED"
    assert "production_level" not in raw_production_contract()["production_response_fields"]
