"""Versioned native flat-road estimates and existing P05 integer objective preconditions."""

from decimal import Decimal

from app.planning.preparation.failures import PreparationFailureCode as Code
from app.planning.preparation.failures import fail


def validate_cost_units(amounts: list[Decimal], source: str) -> None:
    """Same precision/range constraints as P05, without importing the optimizer/solver."""
    places = 2
    for amount in amounts:
        digits = list(amount.as_tuple().digits)
        exponent = amount.as_tuple().exponent
        assert isinstance(exponent, int)
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        if digits:
            places = max(places, -exponent)
    if places > 18:
        fail(
            Code.INVALID_PREPARATION_OUTPUT,
            "costs",
            source,
            "native estimates exceed P05 fixed-point precision",
        )
    scale = 10**places
    # Bound before integer conversion of potentially enormous Decimal exponents.
    if any(amount >= Decimal(2**62) / scale for amount in amounts):
        fail(
            Code.INVALID_PREPARATION_OUTPUT,
            "costs",
            source,
            "native estimates exceed P05 objective integer range",
        )
    units = [n * scale // d for n, d in (amount.as_integer_ratio() for amount in amounts)]
    if sum(units) >= 2**62:
        fail(
            Code.INVALID_PREPARATION_OUTPUT,
            "costs",
            source,
            "candidate cross-product costs exceed P05 objective integer range",
        )
