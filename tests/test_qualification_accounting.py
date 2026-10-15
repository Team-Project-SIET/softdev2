"""Mechanically derived V1 polling bounds and shared native-frame boundaries."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from test_qualification_coordinator import QualificationWire, collect
from test_secure_admin import KEY, Writer, server_handshake

from app.simulation.openttd.admin_protocol import encode_admin_quit
from app.simulation.openttd.gamescript_transport import encode_gamescript
from app.simulation.openttd.proof.qualification_accounting import QualificationFrameBudget
from app.simulation.openttd.qualification_clock import (
    MAX_CLOCK_REQUEST_BYTES,
    MAX_CLOCK_RESPONSE_BYTES,
    MAX_LIFETIME_REQUEST_BYTES,
    MAX_LIFETIME_RESPONSE_BYTES,
    EconomyClockRequest,
    IndustryLifetimeRequest,
)
from app.simulation.openttd.qualification_policy import (
    LIFECYCLE_FRAMES,
    MAX_APPLICATION_REQUESTS,
    MAX_CLOCK_REQUESTS,
    MAX_POST_AUTH_FRAMES,
    MAX_QUERY_OPERATIONS,
    MAX_RESPONSE_BYTES,
    PHASE_BOUNDS,
    QualificationPollPolicy,
    qualification_resource_contract,
)
from app.simulation.openttd.secure_admin import SecureAdminSession


def test_actual_coordinator_poll_derivation_and_all_resource_arithmetic():
    policy = QualificationPollPolicy()
    assert policy.interval == 1 and policy.timeout == 300
    assert policy.max_wait_polls == 299  # start strictly before global deadline
    assert MAX_CLOCK_REQUESTS == 1 + 299 + 2 + 2 == 304
    assert MAX_APPLICATION_REQUESTS == 304 + 96 + 32 + 96 + 32 + 512 == 1072
    assert MAX_RESPONSE_BYTES == 304 * 271 + 49152 + 32 * 248 + 49152 + 32 * 248 + 171520 == 368080
    assert MAX_QUERY_OPERATIONS == 304 * 8 + 1024 + 32 * 8 + 1024 + 32 * 8 + 4096 == 9088
    assert LIFECYCLE_FRAMES == 2 + 3 + 1 == 6
    assert MAX_POST_AUTH_FRAMES == 9088 + 6 == 9094
    assert qualification_resource_contract()["post_auth_frames"] == 9094


@pytest.mark.parametrize(
    "interval,timeout",
    [(0, 300), (0.1, 300), (1, 301), (float("inf"), 300), (1, float("nan")), (5, 3)],
)
def test_invalid_or_unbounded_polling_policy(interval, timeout):
    with pytest.raises(ValueError):
        QualificationPollPolicy(interval, timeout)


@pytest.mark.parametrize(
    "interval,timeout,wait", [(1, 3, 2), (2, 3, 1), (1, 300, 299), (2, 300, 149)]
)
def test_deadline_slots_derived_with_strict_start_bound(interval, timeout, wait):
    policy = QualificationPollPolicy(interval, timeout)
    assert policy.max_wait_polls == wait and policy.max_clock_requests == wait + 5


def test_native_read_canonical_request_and_response_bounds():
    assert MAX_CLOCK_REQUEST_BYTES == len(EconomyClockRequest("x" * 64).to_bytes()) == 117
    assert (
        MAX_LIFETIME_REQUEST_BYTES
        == len(IndustryLifetimeRequest("x" * 64, 63999).to_bytes())
        == 141
    )
    assert MAX_CLOCK_RESPONSE_BYTES == 271 and MAX_LIFETIME_RESPONSE_BYTES == 248
    assert max(MAX_CLOCK_RESPONSE_BYTES, MAX_LIFETIME_RESPONSE_BYTES) <= 512 < 1450


@pytest.mark.parametrize("phase", list(PHASE_BOUNDS))
def test_exact_phase_query_ceiling_accepted_over_ceiling_rejected(phase):
    budget = QualificationFrameBudget()
    maximum = PHASE_BOUNDS[phase][2]
    budget.consume(phase, maximum)
    assert budget.query_operations == maximum
    with pytest.raises(ValueError):
        budget.consume(phase)
    other = next(p for p in PHASE_BOUNDS if p != phase)
    budget.consume(other)  # a distinct phase never transfers its capacity
    with pytest.raises(ValueError):
        budget.consume(phase)


def test_exact_total_frame_ceiling_and_query_ceiling_once():
    budget = QualificationFrameBudget()
    for phase, maximum in budget.limits.items():
        budget.consume(phase, maximum)
    assert budget.query_operations == MAX_QUERY_OPERATIONS
    assert budget.total_frames == MAX_POST_AUTH_FRAMES
    with pytest.raises(ValueError):
        budget.consume("clock")
    with pytest.raises(ValueError):
        budget.consume("cleanup")


def test_phase_transitions_create_no_native_admin_frames_and_cannot_reset_setup():
    budget = QualificationFrameBudget()
    budget.consume("establishment", 2)
    budget.enter("setup")
    budget.consume("setup", 3)
    for phase in (
        "clock",
        "anchor_structural",
        "anchor_lifetime",
        "clock",
        "final_structural",
        "final_lifetime",
        "production",
        "clock",
    ):
        budget.enter(phase)
        assert budget.total_frames == 5
    with pytest.raises(ValueError):
        budget.enter("setup")
    with pytest.raises(ValueError):
        budget.enter("establishment")
    budget.enter("cleanup")
    with pytest.raises(ValueError):
        budget.enter("clock")


@pytest.mark.parametrize("command", ["economy_clock", "industry_lifetime"])
def test_real_secure_codec_observes_native_read_outbound_and_graceful_quit(command):
    async def run():
        reader, writer = asyncio.StreamReader(), Writer()
        budget = QualificationFrameBudget()
        session = SecureAdminSession(reader, writer, key=KEY, frame_observer=budget.observe)
        wire, _ = server_handshake()
        reader.feed_data(wire)
        await session.authenticate("controlled", "1")
        assert budget.total_frames == 2
        budget.enter("setup")
        # Explicit setup frames are already tested by the normal fake-stream coordinator.
        budget.consume("setup", 3)
        budget.enter("clock" if command == "economy_clock" else "anchor_lifetime")
        q = (
            EconomyClockRequest("clock")
            if command == "economy_clock"
            else IndustryLifetimeRequest("life", 2)
        )
        await session.send(encode_gamescript(q.to_bytes()))
        assert budget.query_operations == 1
        await session.close(quit=True)
        assert budget.total_frames == 7 and budget.snapshot()["categories"]["cleanup"] == 1
        assert session._frame_observer.__self__ is budget

    asyncio.run(run())


def test_failed_accounting_rejects_later_traffic_but_allows_owned_quit():
    budget = QualificationFrameBudget()
    budget.consume("establishment", 2)
    budget.enter("setup")
    budget.consume("setup", 3)
    budget.enter("clock")
    budget.consume("clock", PHASE_BOUNDS["clock"][2])
    with pytest.raises(ValueError):
        budget.observe("outbound", encode_gamescript(EconomyClockRequest("overflow").to_bytes()))
    assert budget.failed
    with pytest.raises(ValueError):
        budget.observe("outbound", encode_gamescript(EconomyClockRequest("retry").to_bytes()))
    budget.observe("outbound", encode_admin_quit())
    assert budget.snapshot()["categories"]["cleanup"] == 1


def test_clock_and_lifetime_use_four_actual_operations_with_one_subscription_overhead():
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()
        await collect(wire, owner)
        transactions = owner.evidence.native_transactions
        assert transactions and all(t.exchange.protocol_operations == 4 for t in transactions)
        categories = wire.accounting.snapshot()["categories"]
        assert categories["setup"] == 3 and categories["establishment"] == 2
        assert categories["clock"] == 4 * len(wire.clock_requests)
        assert categories["anchor_lifetime"] == 4 * 2 and categories["final_lifetime"] == 4 * 2
        assert wire.accounting.query_operations == sum(v[2] for _, v in owner.evidence.phase_usage)

    asyncio.run(run())


def test_primary_source_hashes_timing_months_and_generated_binding_authority():
    for directory in ("qualification_timing_15_3", "qualification_15_3", "economy_clock_15_3"):
        manifest = json.loads(Path(f"tests/reference/{directory}/manifest.json").read_text())
        for path, row in manifest["files"].items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == row["sha256"]
            assert "/OpenTTD/OpenTTD/15.3/" in row["source_url"]
    gfx = Path("tests/reference/qualification_timing_15_3/gfx_type.h").read_text()
    tick = Path("tests/reference/qualification_15_3/timer_game_tick.h").read_text()
    economy = Path("tests/reference/economy_clock_15_3/timer_game_economy.cpp").read_text()
    date = Path("tests/reference/economy_clock_15_3/script_date.cpp").read_text()
    assert "MILLISECONDS_PER_TICK = 27" in gfx and "DAY_TICKS = 74" in tick
    assert "return CalendarConvertDateToYMD(date)" in economy
    for method in ("GetCurrentDate", "GetYear", "GetMonth", "GetDayOfMonth", "GetDate"):
        assert "ScriptDate::" + method in date
    lifetime = Path("tests/reference/economy_clock_15_3/script_industry.cpp").read_text()
    assert "ScriptIndustry::GetConstructionDate" in lifetime
    assert "i->construction_date.base()" in lifetime
