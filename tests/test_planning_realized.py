"""P07 semantic comparison boundaries; no runtime or database."""

from decimal import Decimal

import pytest

from app.planning.realized import RealizedValue, compare_value


def test_matching_horizon_compares_exact_values():
    actual = RealizedValue(
        name="cargo_delivered",
        value=Decimal("8"),
        unit="cargo_units",
        source="public_save",
        period="full_horizon",
        horizon_days=10,
    )
    comparison = compare_value(
        "predicted_delivered_cargo_units", Decimal("10"), "cargo_units", 10, actual
    )
    assert comparison.compatibility == "compatible"
    assert comparison.absolute_difference == Decimal("2")
    assert comparison.relative_difference == Decimal("-0.2")


def test_current_period_income_is_not_full_run_profit():
    actual = RealizedValue(
        name="current_period_income",
        value=Decimal("8"),
        unit="GBP",
        source="public_save",
        period="current_economy_period",
        horizon_days=None,
    )
    comparison = compare_value("estimated_net_profit_gbp", Decimal("10"), "GBP", 10, actual)
    assert comparison.compatibility == "incompatible"
    assert comparison.absolute_difference is None


def test_realized_values_are_frozen_and_reject_float():
    with pytest.raises(ValueError):
        RealizedValue.model_validate(
            {
                "name": "company_money",
                "value": 1.2,
                "unit": "GBP",
                "source": "public_save",
                "period": "terminal_snapshot",
                "horizon_days": None,
            }
        )


def test_zero_estimate_has_no_relative_difference():
    actual = RealizedValue(
        name="cargo_delivered",
        value=Decimal("3"),
        unit="cargo_units",
        source="public_save",
        period="full_horizon",
        horizon_days=10,
    )
    result = compare_value(
        "predicted_delivered_cargo_units", Decimal("0"), "cargo_units", 10, actual
    )
    assert result.absolute_difference == Decimal("3")
    assert result.relative_difference is None


def test_different_horizon_is_incompatible():
    actual = RealizedValue(
        name="cargo_delivered",
        value=Decimal("3"),
        unit="cargo_units",
        source="public_save",
        period="full_horizon",
        horizon_days=20,
    )
    result = compare_value(
        "predicted_delivered_cargo_units", Decimal("10"), "cargo_units", 10, actual
    )
    assert result.compatibility == "incompatible"
    assert result.absolute_difference is None
