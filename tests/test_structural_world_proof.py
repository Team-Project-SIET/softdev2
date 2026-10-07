"""Controlled structural proof frame-accounting contract; no native runtime."""

import pytest

from app.simulation.openttd.proof.structural_contract import (
    MAX_QUERY_OPERATIONS,
    MAX_TOTAL_POST_AUTH_FRAMES,
    StructuralFrameBudget,
    structural_contract,
)


def test_frame_ceiling_accounts_for_every_lifecycle_category():
    contract = structural_contract()
    assert MAX_QUERY_OPERATIONS == 256 + 256 + 512 == 1024
    assert contract["frame_budget_derivation"] == {
        "encrypted_protocol_and_welcome": 2,
        "subscription_outbound": 2,
        "subscription_pong": 1,
        "query_operations": 1024,
        "graceful_quit": 1,
    }
    assert MAX_TOTAL_POST_AUTH_FRAMES == 1030
    assert contract["max_application_requests"] == 96
    assert contract["max_response_bytes"] == 49152


def test_exact_query_and_total_budget_accepted():
    budget = StructuralFrameBudget()
    budget.consume("establishment", 2)
    budget.consume("setup", 3)
    for phase, limit in (("inventory", 256), ("capability", 256), ("catalog", 512)):
        budget.consume(phase, limit)
    budget.consume("cleanup", 1)
    assert budget.query_operations == 1024
    assert budget.total_frames == 1030


@pytest.mark.parametrize("phase,limit", [("inventory", 256), ("capability", 256), ("catalog", 512)])
def test_phase_query_budget_not_weakened(phase, limit):
    budget = StructuralFrameBudget()
    budget.consume(phase, limit)
    with pytest.raises(ValueError, match="budget"):
        budget.consume(phase, 1)
    assert budget.query_operations == limit


@pytest.mark.parametrize("category,limit", [("establishment", 2), ("setup", 3), ("cleanup", 1)])
def test_lifecycle_overhead_bounded(category, limit):
    budget = StructuralFrameBudget()
    budget.consume(category, limit)
    with pytest.raises(ValueError, match="budget"):
        budget.consume(category, 1)


@pytest.mark.parametrize("count", [True, False, -1, 0, 1.0])
def test_invalid_accounting_count_rejected(count):
    with pytest.raises(ValueError):
        StructuralFrameBudget().consume("inventory", count)


def test_unknown_frame_category_rejected():
    with pytest.raises(ValueError):
        StructuralFrameBudget().consume("unaccounted", 1)


def test_category_limits_cannot_be_replaced():
    from app.simulation.openttd.proof.structural_contract import FRAME_LIMITS

    with pytest.raises(TypeError):
        FRAME_LIMITS["inventory"] = 100000  # ty: ignore[invalid-assignment]


def test_initial_counter_state_cannot_be_supplied():
    with pytest.raises(TypeError):
        StructuralFrameBudget(_counts={"inventory": -100000})  # ty: ignore[unknown-argument]
