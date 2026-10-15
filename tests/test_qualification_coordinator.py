"""Full controlled qualification on a fake Admin stream and virtual operational clock."""

import asyncio
import json
from dataclasses import replace

import pytest
from test_complete_raw_production import CombinedWire
from test_two_rollover_qualification import reading

from app.simulation.openttd.admin_protocol import (
    AdminFrameDecoder,
    ServerProtocol,
    encode_admin_frame,
)
from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.gamescript_transport import GameScriptSession
from app.simulation.openttd.proof.qualification_accounting import QualificationFrameBudget
from app.simulation.openttd.qualification_clock import (
    EconomyClockRequest,
    IndustryLifetimeReading,
    IndustryLifetimeRequest,
    NativeReadResponse,
)
from app.simulation.openttd.qualification_evidence import parse_native_read_evidence
from app.simulation.openttd.qualification_policy import QualificationPollPolicy
from app.simulation.openttd.qualification_session import (
    ProductionQualificationSession,
    QualificationPhase,
    QualificationTransport,
)
from app.simulation.openttd.qualification_stability import QualificationProfile


class ObservedSession(GameScriptSession):
    def __init__(self, reader, writer, accounting):
        super().__init__(reader, writer)
        self._frame_observer = accounting.observe
        self.decoder = AdminFrameDecoder()

    def encode_outbound(self, frame: bytes) -> bytes:
        self._frame_observer("outbound", frame)
        return super().encode_outbound(frame)

    async def receive(self, size: int = 4096) -> bytes:
        raw = await super().receive(size)
        for kind, body in self.decoder.feed_frames(raw):
            self._frame_observer("inbound", encode_admin_frame(kind, body))
        return raw


class QualificationWire(CombinedWire):
    def __init__(self, *, samples=None, industries=(2, 17), produces=(1, 63), final_change=None):
        super().__init__(industries=industries, produces=produces)
        self.accounting = QualificationFrameBudget()
        self.accounting.observe("inbound", encode_admin_frame(103, b"controlled protocol"))
        self.accounting.observe("inbound", encode_admin_frame(104, b"controlled welcome"))
        self.accounting.enter("setup")
        self.samples = iter(samples or (reading(day=15), reading(month=2), reading(month=3)))
        self.current = reading(day=15)
        self.virtual_time = 0.0
        self.next_sample = None
        self.clock_requests = []
        self.lifetime_requests = []
        self.final_change = final_change
        session = ObservedSession(self.reader, self.writer, self.accounting)
        self.transport: QualificationTransport = QualificationTransport(
            session, ServerProtocol(3, ((9, 64),))
        )
        self.context = replace(self.context, connection_identity=session)
        original = self.writer.write.side_effect

        def send(frame):
            if frame[2] != 6:
                return original(frame)
            value = json.loads(frame[3:-1])
            if value["type"] == "economy_clock":
                q = EconomyClockRequest.parse(frame[3:-1])
                if not self.clock_requests:
                    self.current = next(self.samples)
                elif self.next_sample is not None:
                    self.current = self.next_sample
                    self.next_sample = None
                self.date = self.current.economy_date
                if self.current.economy_month == 3 and self.final_change:
                    change, self.final_change = self.final_change, None
                    change(self)
                self.clock_requests.append(q)
                response = NativeReadResponse(q.request_id, self.current)
            elif value["type"] == "industry_lifetime":
                q = IndustryLifetimeRequest.parse(frame[3:-1])
                self.lifetime_requests.append(q)
                birth = getattr(self, "birth", {}).get(q.industry_id, 1)
                response = NativeReadResponse(
                    q.request_id,
                    IndustryLifetimeReading(q.industry_id, birth, self.date, self.date),
                )
            else:
                return original(frame)
            self.reader.feed_data(encode_admin_frame(124, response.to_bytes() + b"\0"))

        self.writer.write.side_effect = send

    async def pace(self, seconds):
        self.virtual_time += seconds
        self.next_sample = next(self.samples, self.current)

    async def native_evidence(self, q, exchange):
        record = exchange.response.reading
        read = "".join(f" {k}={getattr(record, k)}" for k in record.__dataclass_fields__)
        rows = (
            f"BRIDGE_REQUEST_RECEIVED request_id={q.request_id} type={q.command} protocol=1",
            f"{q.command.upper()}_READ request_id={q.request_id}" + read,
            f"BRIDGE_RESPONSE_SENT request_id={q.request_id} "
            f"type={q.command}_result status=ok protocol=1",
            f"BRIDGE_POST_RESPONSE_ALIVE request_id={q.request_id}",
        )
        raw = "".join("dbg: [script:4] [18] [I] " + line + "\n" for line in rows).encode()
        return parse_native_read_evidence(raw, q.request_id, q.command)

    async def owner(self, **kwargs):
        await self.transport.subscribe()
        assert self.accounting.total_frames == 5
        return ProductionQualificationSession(
            self.transport,
            self.context,
            self.accounting,
            QualificationProfile(True, True, True, True),
            pace=self.pace,
            monotonic=lambda: self.virtual_time,
            context_provider=lambda: self.context,
            **kwargs,
        )


async def collect(wire, owner, *, native=None, production=None, inventory=None):
    return await owner.collect(
        inventory or wire.evidence,
        wire.cargo_evidence,
        wire.catalog_evidence,
        production or wire.evidence_for,
        native or wire.native_evidence,
    )


def test_full_fresh_qualified_collection_and_single_use():
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()
        result = await collect(wire, owner)
        assert result.production.complete and result.production.qualified_for_planning
        assert result.production.source is owner.final and owner.anchor is not owner.final
        assert result.qualified_month.month == 2
        assert owner.clock.boundaries[0].economy_day == 15
        assert owner.phase is QualificationPhase.COMPLETED and owner.evidence.complete
        assert len(wire.clock_requests) == 7
        assert len(wire.lifetime_requests) == 4 and len(wire.production_requests) == 4
        assert owner.anchor_targets == owner.final_targets == ((2, 1), (2, 63), (17, 1), (17, 63))
        assert all(
            r.economy_date_before == reading(month=3).economy_date
            for r in result.production.records
        )
        assert wire.accounting.query_operations == sum(u[2] for _, u in owner.evidence.phase_usage)
        assert wire.accounting.total_frames == wire.accounting.query_operations + 5
        assert owner.evidence.retries == owner.evidence.reconnects == 0
        assert owner.evidence.events[-1] == "QUALIFICATION_SESSION_COMPLETED"
        with pytest.raises(BridgeProtocolError, match="single-use"):
            await collect(wire, owner)

    asyncio.run(run())


@pytest.mark.parametrize(
    "samples",
    [
        (reading(), reading(month=3)),
        (reading(), reading(month=2), reading(month=4)),
        (reading(day=15), reading(day=14)),
        (reading(), reading(month=2, day=2)),
    ],
)
def test_native_skipped_backward_and_missed_first_day_fail_session(samples):
    async def run():
        wire = QualificationWire(samples=samples)
        owner = await wire.owner()
        with pytest.raises(BridgeProtocolError):
            await collect(wire, owner)
        assert owner.phase is QualificationPhase.FAILED and owner.result is None
        assert not wire.production_requests
        with pytest.raises(BridgeProtocolError, match="single-use"):
            await collect(wire, owner)

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        lambda w: setattr(w, "produces", (1,)),
        lambda w: setattr(w, "produces", (1, 9, 63)),
        lambda w: setattr(w, "birth", {2: 2}),
        lambda w: setattr(w, "birth", {2: reading(month=2).economy_date}),
        lambda w: setattr(w, "ids", (2,)),
    ],
)
def test_changed_targets_lifetimes_and_first_day_replacement_fail(change):
    async def run():
        wire = QualificationWire(final_change=change)
        owner = await wire.owner()
        with pytest.raises(BridgeProtocolError):
            await collect(wire, owner)
        assert owner.result is None and not wire.production_requests

    asyncio.run(run())


@pytest.mark.parametrize("industries,produces", [((), ()), ((2,), ())])
def test_stable_empty_targets_qualified_with_no_lifetime_or_production(industries, produces):
    async def run():
        wire = QualificationWire(industries=industries, produces=produces)
        owner = await wire.owner()
        result = await collect(wire, owner)
        assert result.production.complete and result.production.qualified_for_planning
        assert (
            result.production.records == ()
            and not wire.lifetime_requests
            and not wire.production_requests
        )

    asyncio.run(run())


def test_bounded_polling_does_not_qualify_same_month():
    async def run():
        wire = QualificationWire(samples=(reading(),))
        owner = await wire.owner(policy=QualificationPollPolicy(timeout=3))
        with pytest.raises((TimeoutError, BridgeProtocolError)):
            await collect(wire, owner)
        assert owner.result is None and len(wire.clock_requests) <= owner.policy.max_clock_requests

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["anchor", "final"])
def test_clock_guards_reject_collection_crossing(stage):
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()

        async def native(q, e):
            result = await wire.native_evidence(q, e)
            if (stage == "anchor" and len(wire.clock_requests) == 3) or (
                stage == "final" and len(wire.clock_requests) == 6
            ):
                wire.next_sample = reading(month=3 if stage == "anchor" else 4)
            return result

        with pytest.raises(BridgeProtocolError, match="collection crossed"):
            await collect(wire, owner, native=native)
        assert owner.production is None and not owner.evidence.complete

    asyncio.run(run())


@pytest.mark.parametrize(
    "field", ["process_identity", "connection_identity", "configuration_digest", "world", "bridge"]
)
def test_lineage_change_during_poll_or_collection_fails(field):
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()

        async def native(q, e):
            result = await wire.native_evidence(q, e)
            value = (
                object()
                if field.endswith("_identity")
                else (
                    "d" * 64
                    if field == "configuration_digest"
                    else replace(
                        getattr(wire.context, field),
                        **(
                            {"world_id": "replacement"}
                            if field == "world"
                            else {"sha256": "d" * 64}
                        ),
                    )
                )
            )
            wire.context = replace(wire.context, **{field: value})
            return result

        with pytest.raises((BridgeProtocolError, ValueError)):
            await collect(wire, owner, native=native)
        assert owner.phase is QualificationPhase.FAILED and owner.production is None

    asyncio.run(run())


def test_shared_accounting_reset_detected():
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()

        async def native(q, e):
            result = await wire.native_evidence(q, e)
            wire.accounting._counts["clock"] = 0
            return result

        with pytest.raises(BridgeProtocolError, match="reset"):
            await collect(wire, owner, native=native)

    asyncio.run(run())


@pytest.mark.parametrize(
    "marker", ["ECONOMY_CLOCK_READ", "BRIDGE_RESPONSE_SENT", "BRIDGE_POST_RESPONSE_ALIVE"]
)
def test_transport_receipt_cannot_replace_native_semantics(marker):
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()

        async def native(q, e):
            result = await wire.native_evidence(q, e)
            raw = b"".join(
                line
                for line in result.raw_log.splitlines(keepends=True)
                if marker.encode() not in line
            )
            return parse_native_read_evidence(raw, q.request_id, q.command)

        with pytest.raises(ValueError):
            await collect(wire, owner, native=native)
        assert owner.result is None

    asyncio.run(run())


@pytest.mark.parametrize("metrics", [(0, 0, 0), (168, 0, 0), (65535, 65535, 100)])
def test_qualification_independent_of_raw_metric_values(metrics):
    async def run():
        wire = QualificationWire()
        wire.metrics = metrics
        owner = await wire.owner()
        assert (await collect(wire, owner)).production.qualified_for_planning

    asyncio.run(run())


@pytest.mark.parametrize(
    "samples",
    [
        (reading(1950, 12, 15), reading(1951, 1), reading(1951, 2)),
        (reading(), reading(), reading(month=2), reading(month=2), reading(month=3)),
    ],
)
def test_adjacent_year_transition_and_repeated_monitoring_samples(samples):
    async def run():
        wire = QualificationWire(samples=samples)
        owner = await wire.owner()
        result = await collect(wire, owner)
        assert result.production.qualified_for_planning
        assert result.qualified_month_identity.boundary_start.economy_day == 1
        assert result.qualified_month_identity.boundary_end.economy_day == 1
        assert result.clock.polls == len(wire.clock_requests)

    asyncio.run(run())


def test_maximum_targets_and_shared_cargo_lifetime_scope():
    async def run():
        wire = QualificationWire(industries=tuple(range(32)), produces=tuple(range(16)))
        wire.cargoes = tuple(range(64))
        owner = await wire.owner()
        result = await collect(wire, owner)
        assert len(result.production.records) == 512
        assert len(wire.lifetime_requests) == 64
        assert tuple(q.industry_id for q in wire.lifetime_requests[:32]) == tuple(range(32))
        assert owner.production_session.observation.complete
        assert not owner.production_session.observation.qualified_for_planning
        with pytest.raises(AttributeError):
            owner.anchor_targets = ()
        with pytest.raises(AttributeError):
            owner.final_targets = ()

    asyncio.run(run())


def test_unrelated_catalog_change_does_not_require_full_structural_digest_equality():
    async def run():
        wire = QualificationWire(final_change=lambda w: setattr(w, "cargoes", (1, 9, 10, 63)))
        owner = await wire.owner()
        result = await collect(wire, owner)
        assert result.production.qualified_for_planning
        assert owner.anchor.structural_world_digest != owner.final.structural_world_digest
        assert (
            result.production.source_structural_world_digest == owner.final.structural_world_digest
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure",
    ["incomplete", "outside_m2", "missing_liveness", "invalid_values", "disconnect", "timeout"],
)
def test_final_production_failure_never_admits_qualification(failure):
    async def run():
        wire = QualificationWire()
        owner = await wire.owner(timeout=0.03)
        original = wire.writer.write.side_effect

        def send(frame):
            if frame[2] == 6 and json.loads(frame[3:-1])["type"] == "industry_production":
                if failure in ("incomplete", "disconnect"):
                    wire.reader.feed_eof()
                    return
                if failure == "timeout":
                    return
                if failure == "outside_m2":
                    wire.date = reading(month=4).economy_date
                if failure == "invalid_values":
                    wire.metrics = (-1, 0, 0)
            original(frame)

        wire.writer.write.side_effect = send

        async def production(q, e):
            evidence = await wire.evidence_for(q, e)
            if failure == "missing_liveness":
                from app.simulation.openttd.industry_production_evidence import (
                    parse_industry_production_evidence,
                )

                raw = b"".join(
                    line
                    for line in evidence.raw_log.splitlines(keepends=True)
                    if b"BRIDGE_POST_RESPONSE_ALIVE" not in line
                )
                return parse_industry_production_evidence(raw, q.request_id)
            return evidence

        with pytest.raises((BridgeProtocolError, ValueError, ConnectionError, TimeoutError)):
            await collect(wire, owner, production=production)
        assert owner.result is None and owner.production is None and not owner.evidence.complete

    asyncio.run(run())


@pytest.mark.parametrize("which", ["transport", "accounting", "decision"])
def test_replacement_or_decision_during_session_fails_before_next_query(which):
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()

        async def native(q, e):
            result = await wire.native_evidence(q, e)
            if which == "transport":
                owner.transport = QualificationTransport(
                    wire.transport.session, ServerProtocol(3, ((9, 64),))
                )
            elif which == "accounting":
                owner.accounting = QualificationFrameBudget()
            else:
                owner.decision.mark_decision()
            return result

        with pytest.raises(BridgeProtocolError):
            await collect(wire, owner, native=native)
        assert owner.result is None and len(wire.clock_requests) == 1

    asyncio.run(run())


def test_final_guard_failure_leaves_fresh_production_raw_not_qualified():
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()

        async def production(q, e):
            wire.next_sample = reading(month=4)
            return await wire.evidence_for(q, e)

        with pytest.raises(BridgeProtocolError):
            await collect(wire, owner, production=production)
        assert owner.result is None and owner.production is None
        assert owner.production_session.observation.complete
        assert not owner.production_session.observation.qualified_for_planning

    asyncio.run(run())


def test_proof_result_requires_native_and_semantic_evidence_complete():
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()
        result = await collect(wire, owner)
        with pytest.raises(BridgeProtocolError):
            replace(result, evidence=replace(result.evidence, events=result.evidence.events[:-1]))
        with pytest.raises(BridgeProtocolError):
            replace(result, evidence=replace(result.evidence, native_transactions=()))

    asyncio.run(run())


@pytest.mark.parametrize("producer", ["clock", "structural", "production"])
def test_evidence_waits_are_bounded_and_failure_terminal(producer):
    async def run():
        wire = QualificationWire()
        owner = await wire.owner(timeout=0.01)

        async def stalled(*args):
            await asyncio.Future()

        overrides = {}
        if producer == "clock":
            overrides["native"] = stalled
        elif producer == "structural":
            overrides["inventory"] = stalled
        else:
            overrides["production"] = stalled
        with pytest.raises(TimeoutError):
            await collect(wire, owner, **overrides)
        assert owner.phase is QualificationPhase.FAILED and owner.result is None
        assert owner.evidence.partial_response is not None
        with pytest.raises(BridgeProtocolError):
            await collect(wire, owner)

    asyncio.run(run())


def test_completed_result_cannot_forge_accounting_or_drop_components():
    async def run():
        wire = QualificationWire()
        owner = await wire.owner()
        result = await collect(wire, owner)
        for changes in (
            {"phase_usage": ()},
            {"accounting_frames": ()},
            {"anchor": None},
            {"final": None},
            {"production": None},
        ):
            with pytest.raises(BridgeProtocolError):
                replace(result, evidence=replace(result.evidence, **changes))

    asyncio.run(run())


def test_failure_cleanup_cannot_wait_without_bound():
    from unittest.mock import AsyncMock

    async def run():
        wire = QualificationWire()
        owner = await wire.owner(timeout=0.01)

        async def stuck():
            await asyncio.Future()

        wire.transport.session.close = AsyncMock(side_effect=stuck)

        async def invalid_evidence(q, e):
            raise ValueError("controlled invalid evidence")

        with pytest.raises(ValueError, match="controlled invalid evidence"):
            await collect(wire, owner, native=invalid_evidence)
        assert owner.phase is QualificationPhase.FAILED
        assert "Admin close failed" in owner.evidence.failure

    asyncio.run(run())
