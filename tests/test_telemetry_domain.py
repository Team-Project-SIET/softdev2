"""Typed telemetry contracts; explicit values stand in for future stream sequencing."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.simulation.openttd.telemetry import (
    CompanyEconomyObservation,
    CompanyInfoObservation,
    CompletedQuarter,
    DiagnosticCode,
    DiagnosticSeverity,
    DiagnosticSummary,
    GameDateObservation,
    MeasurementPeriod,
    MetricSource,
    ObservationKind,
    ObservationSource,
    TelemetryDiagnostic,
    TelemetryObservation,
    metric_semantics,
)


def _economy() -> CompanyEconomyObservation:
    return CompanyEconomyObservation(
        company_id=2,
        cash_balance_gbp=-50,
        loan_balance_gbp=100_000,
        admin_year_to_date_net_income_gbp=-2_500,
        current_quarter_delivered_cargo_capped=65_535,
        completed_quarters=(
            CompletedQuarter(
                history_offset=1,
                company_value_gbp=500_000,
                performance_score=100,
                delivered_cargo_capped=42,
            ),
            CompletedQuarter(
                history_offset=2, company_value_gbp=0, performance_score=0, delivered_cargo_capped=0
            ),
        ),
    )


def test_explicit_envelope_keeps_exact_values_and_date_provenance() -> None:
    observation = TelemetryObservation(
        experiment_run_id=7,
        sequence=2,
        connection_epoch=1,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=1,
        source=ObservationSource.OPENTTD_ADMIN,
        protocol_version=2,
        kind=ObservationKind.COMPANY_ECONOMY,
        company_id=2,
        game_day=712223,
        date_context_sequence=1,
        date_quality="preceding_date",
        payload=_economy(),
    )
    assert observation.payload.admin_year_to_date_net_income_gbp == -2_500
    assert '"admin_year_to_date_net_income_gbp":-2500' in observation.model_dump_json()
    with pytest.raises(ValidationError):
        observation.sequence = 3


@pytest.mark.parametrize(
    "change",
    [
        {"sequence": 0},
        {"connection_epoch": 0},
        {"received_at": datetime(2026, 1, 1)},
        {"received_at": datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))},
        {"kind": ObservationKind.COMPANY_STATS},
        {"company_id": 3},
        {"date_quality": "unknown"},
        {"date_context_sequence": 2},
        {"protocol_version": None},
    ],
)
def test_envelope_rejects_mismatched_or_unproven_measurements(change: dict) -> None:
    fields = dict(
        experiment_run_id=7,
        sequence=2,
        connection_epoch=1,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=1,
        source=ObservationSource.OPENTTD_ADMIN,
        protocol_version=2,
        kind=ObservationKind.COMPANY_ECONOMY,
        company_id=2,
        game_day=712223,
        date_context_sequence=1,
        date_quality="preceding_date",
        payload=_economy(),
    )
    with pytest.raises(ValidationError):
        TelemetryObservation.model_validate({**fields, **change})


def test_date_and_diagnostic_have_distinct_valid_context_rules() -> None:
    date_observation = TelemetryObservation(
        experiment_run_id=7,
        sequence=1,
        connection_epoch=1,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=1,
        source=ObservationSource.OPENTTD_ADMIN,
        protocol_version=2,
        kind=ObservationKind.DATE,
        company_id=None,
        game_day=712223,
        date_context_sequence=None,
        date_quality="packet_date",
        payload=GameDateObservation(game_day=712223),
    )
    assert date_observation.game_day == date_observation.payload.game_day
    diagnostic = TelemetryObservation(
        experiment_run_id=7,
        sequence=3,
        connection_epoch=0,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=1,
        source=ObservationSource.LIVE_RUNTIME,
        protocol_version=None,
        kind=ObservationKind.DIAGNOSTIC,
        company_id=None,
        game_day=None,
        date_context_sequence=None,
        date_quality="unknown",
        payload=TelemetryDiagnostic(
            code=DiagnosticCode.WORLD_RESET,
            severity=DiagnosticSeverity.WARNING,
            connection_epoch=0,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    assert diagnostic.payload.code is DiagnosticCode.WORLD_RESET
    with pytest.raises(ValidationError):
        TelemetryDiagnostic(
            code="unbounded_free_text",
            severity="warning",
            connection_epoch=0,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_metric_metadata_keeps_admin_yearly_and_savegame_quarterly_distinct() -> None:
    admin = metric_semantics(MetricSource.OPENTTD_ADMIN, "admin_year_to_date_net_income_gbp")
    final = metric_semantics(MetricSource.FINAL_SAVEGAME, "current_period_income")
    cargo = metric_semantics(MetricSource.OPENTTD_ADMIN, "current_quarter_delivered_cargo_capped")
    assert admin.period is MeasurementPeriod.CALENDAR_YEAR_TO_DATE
    assert final.period is MeasurementPeriod.CURRENT_QUARTER_TO_DATE
    assert admin.name != final.name
    assert admin.source is not final.source
    assert cargo.saturates_at == 65_535
    assert "operating profit" not in admin.meaning.lower()
    assert metric_semantics(MetricSource.FINAL_SAVEGAME, "current_period_expenses").name == (
        "current_period_expenses"
    )


def test_direct_payload_validation_keeps_wire_scalar_types_exact() -> None:
    data = _economy().model_dump()
    for field, value in (
        ("cash_balance_gbp", -50.0),
        ("loan_balance_gbp", 2**63),
        ("current_quarter_delivered_cargo_capped", 65536),
    ):
        with pytest.raises(ValidationError):
            CompanyEconomyObservation.model_validate({**data, field: value})
    with pytest.raises(ValidationError):
        CompanyInfoObservation(
            company_id=0,
            name="Company",
            manager="Manager",
            colour=1,
            password_protected=1,
            inaugurated_year=1950,
            is_ai=False,
            bankruptcy_quarters=0,
            share_owners=(255, 255, 255, 255),
        )


def test_diagnostic_context_rejects_unbounded_secret_bearing_text() -> None:
    safe = TelemetryDiagnostic(
        code=DiagnosticCode.PROTOCOL_ERROR,
        severity=DiagnosticSeverity.ERROR,
        connection_epoch=1,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        summary=DiagnosticSummary.PROTOCOL_ERROR,
    )
    assert safe.summary is DiagnosticSummary.PROTOCOL_ERROR
    with pytest.raises(ValidationError):
        TelemetryDiagnostic(
            code=DiagnosticCode.PROTOCOL_ERROR,
            severity=DiagnosticSeverity.ERROR,
            connection_epoch=1,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            summary="admin password: top-secret",
        )


def test_inferred_calendar_periods_are_explicit_and_require_date_context():
    from datetime import date

    from app.simulation.openttd.telemetry import DateQuality

    day = date(1950, 1, 2).toordinal() + 365
    observation = TelemetryObservation(
        experiment_run_id=7,
        sequence=2,
        connection_epoch=1,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=1,
        source="openttd_admin",
        protocol_version=2,
        kind="company_economy",
        company_id=2,
        game_day=day,
        date_context_sequence=1,
        date_quality=DateQuality.PRECEDING_DATE,
        payload=_economy(),
    )
    periods = observation.inferred_economy_periods
    assert periods is not None and periods.inferred
    assert periods.admin_year_to_date == "1950"
    assert periods.current_quarter == "1950-Q1"
    assert periods.completed_quarters == ("1949-Q4", "1949-Q3")
    unknown = TelemetryObservation.model_validate(
        {
            **observation.model_dump(),
            "game_day": None,
            "date_context_sequence": None,
            "date_quality": "unknown",
        }
    )
    assert unknown.inferred_economy_periods is None
    assert observation.payload == unknown.payload  # No inferred economic values/history validity.
