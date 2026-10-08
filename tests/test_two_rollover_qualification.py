"""Controlled native calendar evidence; no live clock or wall-clock waits."""

from dataclasses import FrozenInstanceError, replace

import pytest
from test_structural_world import context

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.qualification_clock import (
    MAX_CLOCK_RESPONSE_BYTES,
    MAX_LIFETIME_RESPONSE_BYTES,
    EconomyClockReading,
    EconomyClockRequest,
    IndustryLifetimeReading,
    IndustryLifetimeRequest,
    NativeReadExchange,
    NativeReadReceipt,
    NativeReadResponse,
    native_calendar_month,
)
from app.simulation.openttd.qualification_policy import MAX_CLOCK_REQUESTS
from app.simulation.openttd.qualification_stability import QualificationProfile
from app.simulation.openttd.qualification_state import NativeRolloverEvidence, QualificationState


def reading(year=1950, month=1, day=1):
    m = native_calendar_month(year, month)
    return EconomyClockReading(m.start_date + day - 1, year, month, day, m.start_date, m.end_date)


def observe(*samples):
    c = context()
    evidence = NativeRolloverEvidence(c)
    for sample in samples:
        evidence = evidence.observe(sample, c)
    return evidence


@pytest.mark.parametrize("day", [1, 15, 31])
def test_two_adjacent_rollovers_bound_only_middle_month(day):
    evidence = observe(reading(day=day), reading(month=2), reading(month=3))
    assert evidence.state is QualificationState.SECOND_ROLLOVER_OBSERVED
    assert evidence.bounded_month == native_calendar_month(1950, 2)
    assert not evidence.qualified  # Clock evidence cannot replace fresh complete coverage.


@pytest.mark.parametrize(
    "samples,state",
    [
        ((), QualificationState.UNINITIALIZED),
        ((reading(),), QualificationState.BASELINE_MONTH_OBSERVED),
        ((reading(), reading(month=2)), QualificationState.FIRST_ROLLOVER_OBSERVED),
    ],
)
def test_incomplete_evidence_never_qualifies(samples, state):
    evidence = observe(*samples)
    assert evidence.state is state and not evidence.qualified


def test_year_transition():
    evidence = observe(reading(1950, 12, 15), reading(1951, 1), reading(1951, 2))
    assert evidence.bounded_month == native_calendar_month(1951, 1)


@pytest.mark.parametrize("year,days", [(0, 29), (1900, 28), (2000, 29), (1950, 28), (2024, 29)])
def test_native_gregorian_leap_rules(year, days):
    month = native_calendar_month(year, 2)
    assert month.end_date - month.start_date == days


@pytest.mark.parametrize(
    "samples",
    [
        (reading(), reading(month=3)),
        (reading(), reading(month=2), reading(month=4)),
        (reading(day=15), reading(day=14)),
        (reading(), reading(month=2, day=2)),
        (reading(), reading(month=2), reading(month=3, day=2)),
        (reading(), reading(month=2), reading(month=3), reading(month=4)),
    ],
)
def test_skips_backwards_missed_boundaries_and_third_rollover_fail(samples):
    with pytest.raises(BridgeProtocolError):
        observe(*samples)


def test_repeated_samples_do_not_count_rollovers():
    evidence = observe(*([reading()] * MAX_CLOCK_REQUESTS))
    assert len(evidence.boundaries) == 1
    with pytest.raises(BridgeProtocolError, match="budget"):
        evidence.observe(reading(), evidence.context)


def test_evidence_immutable_and_failure_terminal():
    evidence = observe(reading())
    with pytest.raises(FrozenInstanceError):
        evidence.polls = 0
    failed = evidence.fail("native disconnect")
    assert failed.state is QualificationState.FAILED
    with pytest.raises(BridgeProtocolError, match="resume"):
        failed.observe(reading(month=2), failed.context)


@pytest.mark.parametrize(
    "field", ["process_identity", "connection_identity", "configuration_digest"]
)
def test_lineage_replacement_rejected(field):
    evidence = observe(reading())
    value = "a" * 64 if field == "configuration_digest" else object()
    with pytest.raises(BridgeProtocolError):
        evidence.observe(reading(month=2), replace(evidence.context, **{field: value}))


@pytest.mark.parametrize(
    "field",
    ["economy_date", "economy_year", "economy_month", "economy_day", "month_start", "month_end"],
)
def test_incoherent_native_clock_rejected(field):
    value = getattr(reading(), field)
    with pytest.raises((BridgeProtocolError, ValueError)):
        replace(reading(), **{field: value + 1})


@pytest.mark.parametrize(
    "q,record",
    [
        (EconomyClockRequest("clock-001"), reading()),
        (IndustryLifetimeRequest("lifetime-001", 2), IndustryLifetimeReading(2, 1, 712223, 712223)),
    ],
)
def test_canonical_native_read_receipt_and_semantic_sequence(q, record):
    response = NativeReadResponse(q.request_id, record).to_bytes()
    assert len(response) <= 512
    receipt = NativeReadReceipt.correlate(q.to_bytes(), response)
    command = q.command.upper()
    exchange = NativeReadExchange(
        q.to_bytes(),
        response,
        receipt,
        (
            command + "_REQUEST_SENT",
            command + "_RESPONSE_RECEIVED",
            "TRANSPORT_RECEIPT_CREATED",
            command + "_VALIDATED",
        ),
        4,
    )
    exchange.validate()
    assert exchange.response.reading == record
    with pytest.raises(BridgeProtocolError):
        replace(exchange, network_sequence=("TRANSPORT_RECEIPT_CREATED",)).validate()
    with pytest.raises(BridgeProtocolError):
        replace(exchange, protocol_operations=9).validate()


def test_payload_bounds():
    assert MAX_CLOCK_RESPONSE_BYTES <= 512 and MAX_LIFETIME_RESPONSE_BYTES <= 512


@pytest.mark.parametrize(
    "field", ["calendar_economy", "no_newgrf", "continuous_runtime", "pre_decision"]
)
def test_unsupported_profiles_fail_closed(field):
    with pytest.raises(BridgeProtocolError):
        replace(QualificationProfile(True, True, True, True), **{field: False})
