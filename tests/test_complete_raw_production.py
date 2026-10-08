"""Controlled same-stream A→B→C→D→E; never opens a native runtime/socket."""

import asyncio
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from test_industry_production import MONTHS, ProductionWire

from app.simulation.openttd.industry_production import (
    IndustryProductionExchange,
    IndustryProductionReceipt,
)
from app.simulation.openttd.production_observation import IndustryProductionObservation
from app.simulation.openttd.raw_production_session import (
    MAX_COMBINED_QUERY_OPERATIONS,
    MAX_COMBINED_REQUESTS,
    MAX_COMBINED_RESPONSE_BYTES,
    CompleteRawProductionSession,
    RawProductionBudget,
)


class CombinedWire(ProductionWire):
    def __init__(self, *, industries=(2, 17), produces=(1, 63), cargoes=(1, 9, 63), **kwargs):
        super().__init__(industries=industries, produces=produces, **kwargs)
        self.cargoes = cargoes
        self.accepts = (9,) if 9 in cargoes else ()
        self.date = 0
        self.commands = []
        original = self.writer.write.side_effect

        def send(frame):
            if frame[2] == 6:
                self.commands.append(json.loads(frame[3:-1])["type"])
            original(frame)

        self.writer.write.side_effect = send

    async def industry_production(self, *args, **kwargs):
        return await self.transport.industry_production(*args, **kwargs)


async def collect(wire, *, session=None, production_evidence=None):
    session = session or CompleteRawProductionSession(wire.context, MONTHS[0], timeout=0.05)
    result = await session.collect(
        wire,
        wire.evidence,
        wire.cargo_evidence,
        wire.catalog_evidence,
        production_evidence or wire.evidence_for,
    )
    return session, result


@pytest.mark.parametrize(
    "industries,produces,cargoes",
    [
        ((), (), (1,)),
        ((17,), (), (1,)),
        ((0,), (1,), (1,)),
        ((17,), (1, 63), (1, 9, 63)),
        ((2, 17), (1,), (1, 9)),
        ((0, 31), (63,), (0, 9, 63)),
        (tuple(range(32)), tuple(range(16)), tuple(range(64))),
    ],
)
def test_exact_same_run_coverage(industries, produces, cargoes):
    async def run():
        wire = CombinedWire(industries=industries, produces=produces, cargoes=cargoes)
        session, (structural, production) = await collect(wire)
        targets = tuple((i, c) for i in industries for c in produces)
        assert production.complete and not production.qualified_for_planning
        assert production.qualification.rollover_count == 0
        assert tuple(r.pair for r in production.records) == targets
        assert tuple((q.industry_id, q.cargo_id) for q in wire.production_requests) == targets
        assert production.source is structural
        assert production.source_structural_world_digest == structural.structural_world_digest
        assert production.context is wire.context
        assert session.evidence.complete
        assert session.evidence.request_attempts == structural.total_requests + len(targets)
        assert session.evidence.protocol_operations == 4 * session.evidence.request_attempts + 3
        assert production.protocol_operations == 4 * len(targets)
        assert (
            session.evidence.total_response_bytes
            == structural.total_response_bytes + production.total_response_bytes
        )
        assert session.evidence.retries == session.evidence.reconnects == 0
        assert session.evidence.events[-1] == "COMBINED_SESSION_COMPLETED"
        assert tuple(
            x
            for x in session.evidence.events
            if x.endswith("_PHASE_STARTED") and x != "RAW_PRODUCTION_PHASE_STARTED"
        ) == (
            "INVENTORY_PHASE_STARTED",
            "CAPABILITY_PHASE_STARTED",
            "CATALOG_PHASE_STARTED",
            "ASSEMBLY_PHASE_STARTED",
            "PRODUCTION_PHASE_STARTED",
        )
        assert session.evidence.events.index(
            "STRUCTURAL_WORLD_VERIFIED"
        ) < session.evidence.events.index("RAW_PRODUCTION_PHASE_STARTED")
        assert all(
            a[0] < b[0] and a[1] < b[1] and a[2] < b[2]
            for a, b in zip(session.evidence.accounting, session.evidence.accounting[1:])
        )
        assert session.production_session.targets == targets
        with pytest.raises(AttributeError):
            session.production_session.targets = ()
        with pytest.raises(FrozenInstanceError):
            structural.budget = None
        with pytest.raises(ValueError, match="single-use"):
            await collect(wire, session=session)
        if not targets:
            assert not wire.production_requests
        if len(targets) == 512:
            assert len(wire.production_requests) == 512
        return session

    asyncio.run(run())


@pytest.mark.parametrize("metrics", [(0, 0, 0), (168, 0, 0), (65535, 65535, 100), (0, 65535, 100)])
def test_raw_values_never_qualify(metrics):
    async def run():
        wire = CombinedWire()
        wire.metrics = metrics
        _, (_, production) = await collect(wire)
        assert not production.qualified_for_planning
        assert all(
            (r.last_month_produced, r.last_month_transported, r.last_month_transported_pct)
            == metrics
            for r in production.records
        )

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["process", "connection", "runtime", "world", "config", "bridge"])
@pytest.mark.parametrize("when", ["before", "during_production"])
def test_same_run_identity_enforced(kind, when):
    async def run():
        wire = CombinedWire()
        session = CompleteRawProductionSession(wire.context, MONTHS[0], timeout=0.05)
        ctx = wire.context
        changes = {
            "process": dict(process_identity=object()),
            "connection": dict(connection_identity=object()),
            "runtime": dict(
                world=replace(
                    ctx.world, runtime_identity=replace(ctx.world.runtime_identity, sha256="b" * 64)
                )
            ),
            "world": dict(world=replace(ctx.world, world_id="other-world")),
            "config": dict(configuration_digest="d" * 64),
            "bridge": dict(bridge=replace(ctx.bridge, sha256="e" * 64)),
        }

        async def evidence(q, e):
            wire.context = replace(ctx, **changes[kind])
            return await wire.evidence_for(q, e)

        if when == "before":
            wire.context = replace(ctx, **changes[kind])
        with pytest.raises(ValueError):
            await collect(wire, session=session, production_evidence=evidence)
        assert (
            session.phase == "FAILED"
            and not session.evidence.complete
            and session.production is None
        )
        assert len(wire.production_requests) == (0 if when == "before" else 1)

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "disconnect",
        "duplicate",
        "missing_liveness",
        "wrong_metadata",
        "evidence_timeout",
        "decision",
        "connection_replaced",
    ],
)
def test_production_failure_invalidates_combined_session(failure):
    async def run():
        wire = CombinedWire(
            fail=failure if failure in ("timeout", "disconnect") else None,
            duplicate=failure == "duplicate",
        )
        session = CompleteRawProductionSession(wire.context, MONTHS[0], timeout=0.01)

        async def evidence(q, e):
            gs = await wire.evidence_for(q, e)
            if failure == "missing_liveness":
                return replace(gs, ordered_sequence=gs.ordered_sequence[:-1])
            if failure == "wrong_metadata":
                return replace(gs, suffixes=())
            if failure == "evidence_timeout":
                await asyncio.Future()
            if failure == "decision":
                session.decision.mark_decision()
            if failure == "connection_replaced":
                wire.transport.session = CombinedWire().transport.session
            return gs

        with pytest.raises((ValueError, TimeoutError, ConnectionError)):
            await collect(wire, session=session, production_evidence=evidence)
        assert not session.evidence.complete and session.production is None
        assert session.structural is not None and session.structural.complete
        assert len(wire.production_requests) == 1
        assert session.production_session is not None
        assert not session.production_session.evidence.complete
        assert session.evidence.retries == session.evidence.reconnects == 0
        with pytest.raises(ValueError, match="single-use"):
            await collect(wire, session=session)

    asyncio.run(run())


@pytest.mark.parametrize("field", ["max_requests", "max_response_bytes", "max_operations"])
def test_combined_budget_fails_without_resume(field):
    async def run():
        wire = CombinedWire()
        # Structural phase needs 5 requests, 23 operations; first production remains blocked.
        baseline, _ = await collect(CombinedWire())
        s = baseline.structural
        limit = {
            "max_requests": s.total_requests,
            "max_response_bytes": s.total_response_bytes,
            "max_operations": s.protocol_operations,
        }[field]
        session = CompleteRawProductionSession(
            wire.context, MONTHS[0], budget=RawProductionBudget(**{field: limit}), timeout=0.05
        )
        with pytest.raises(ValueError):
            await collect(wire, session=session)
        assert session.phase == "FAILED" and not wire.production_requests

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,ceiling",
    [("max_requests", 608), ("max_response_bytes", 220672), ("max_operations", 5120)],
)
def test_combined_theoretical_bounds(field, ceiling):
    assert getattr(RawProductionBudget(), field) == ceiling
    assert getattr(RawProductionBudget(**{field: ceiling}), field) == ceiling
    with pytest.raises(ValueError):
        RawProductionBudget(**{field: ceiling + 1})
    assert MAX_COMBINED_REQUESTS == 608
    assert MAX_COMBINED_RESPONSE_BYTES == 220672
    assert MAX_COMBINED_QUERY_OPERATIONS == 1024 + 512 * 8


def test_missing_catalog_prevents_production():
    async def run():
        wire = CombinedWire(cargoes=(1, 9))
        session = CompleteRawProductionSession(wire.context, MONTHS[0])
        with pytest.raises(ValueError, match="missing catalog"):
            await collect(wire, session=session)
        assert not wire.production_requests and session.production_session is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "duplicate", "wrong_pair", "structural_digest"]
)
def test_observation_exact_coverage_not_transport_success(kind):
    async def run():
        _, (_, p) = await collect(CombinedWire())
        changes = {
            "missing": dict(records=p.records[:-1], transactions=p.transactions[:-1]),
            "extra": dict(
                records=(*p.records, p.records[-1]),
                transactions=(*p.transactions, p.transactions[-1]),
            ),
            "duplicate": dict(records=(p.records[0],) * len(p.records)),
            "wrong_pair": dict(records=(replace(p.records[0], cargo_id=9), *p.records[1:])),
            "structural_digest": dict(
                qualification=replace(p.qualification, source_structural_world_digest="e" * 64)
            ),
        }
        with pytest.raises(ValueError):
            replace(p, **changes[kind])

    asyncio.run(run())


def test_digest_ids_order_paths_date_brackets_independent():
    async def run():
        _, (_, a) = await collect(CombinedWire())
        w = CombinedWire()
        w.date = 2
        session = CompleteRawProductionSession(w.context, MONTHS[0], session_id="another")
        _, (_, b) = await collect(w, session=session)
        assert a.production_digest == b.production_digest
        assert (
            replace(b, transactions=tuple(reversed(b.transactions))).production_digest
            == a.production_digest
        )
        assert b"production_level" not in b.to_bytes()
        assert b"qualified_after_second" not in b.to_bytes()

    asyncio.run(run())


def test_historical_single_query_cannot_be_attached_to_new_structural_source():
    async def run():
        _, (_, a) = await collect(CombinedWire())
        _, (historical, _) = await collect(CombinedWire())
        with pytest.raises(ValueError):
            replace(a, source=historical)

    asyncio.run(run())


def test_proven_attempt2_response_remains_valid():
    root = Path("artifacts/runtime/openttd-15.3-industry-production-real-attempt2")
    q = (root / "request.json").read_bytes()
    r = (root / "production-response.json").read_bytes()
    receipt = IndustryProductionReceipt.correlate(q, r)
    IndustryProductionExchange(q, r, receipt).validate()
    assert json.loads((root / "proof-evidence.json").read_text())["states"][-1] == "COMPLETED"
    assert json.loads((root / "process-lifecycle.json").read_text())["postrun_integrity_verified"]
    failed = Path(
        "artifacts/runtime/openttd-15.3-industry-production-real-attempt1-postrun-verification/final-report.md"
    )
    assert "FAILED" in failed.read_text()


def test_no_wait_planning_evaluation_or_mutation_boundary():
    import ast

    paths = [
        Path("app/simulation/openttd/raw_production_session.py"),
        Path("app/simulation/openttd/production_session.py"),
    ]
    for path in paths:
        text = path.read_text()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.planning")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "sleep",
                    "observe",
                    "BuildRoad",
                    "BuildVehicle",
                    "Terraform",
                    "send_rcon",
                }
        assert "production_level" not in text
    assert set(IndustryProductionObservation.__dataclass_fields__) == {
        "source",
        "context",
        "qualification",
        "records",
        "total_response_bytes",
        "protocol_operations",
        "transactions",
        "budget",
    }


@pytest.mark.parametrize(
    "kind", ["wrong_industry", "wrong_cargo", "wrong_id", "too_many_operations", "missing_record"]
)
def test_invalid_production_exchange_fails_once(kind, monkeypatch):
    async def run():
        wire = CombinedWire()
        session = CompleteRawProductionSession(wire.context, MONTHS[0], timeout=0.05)
        original = wire.industry_production

        async def query(q, **kwargs):
            e = await original(q, **kwargs)
            if kind == "missing_record":
                raise ValueError("missing record")
            if kind == "too_many_operations":
                return replace(e, protocol_operations=9)
            response = e.response
            if kind == "wrong_industry":
                response = replace(response, record=replace(response.record, industry_id=31))
            if kind == "wrong_cargo":
                response = replace(response, record=replace(response.record, cargo_id=9))
            if kind == "wrong_id":
                response = replace(response, request_id="other")
            return replace(e, response_payload=response.to_bytes())

        monkeypatch.setattr(wire, "industry_production", query)
        with pytest.raises(ValueError):
            await collect(wire, session=session)
        assert len(wire.production_requests) == 1 and session.phase == "FAILED"
        assert session.structural is not None
        assert session.evidence.request_attempts == session.structural.total_requests + 1

    asyncio.run(run())


def test_production_blocked_until_complete_structural_evidence():
    async def run():
        wire = CombinedWire()
        session = CompleteRawProductionSession(wire.context, MONTHS[0])

        async def broken(q, e):
            raise ValueError("missing structural liveness")

        with pytest.raises(ValueError):
            await session.collect(
                wire, wire.evidence, wire.cargo_evidence, broken, wire.evidence_for
            )
        assert not wire.production_requests and session.production_session is None
        assert not session.evidence.complete

    asyncio.run(run())


def test_accepts_and_unreferenced_catalog_cargo_not_production_targets():
    async def run():
        _, (_, p) = await collect(CombinedWire(produces=(1,), cargoes=(1, 9, 63)))
        assert tuple(r.pair for r in p.records) == ((2, 1), (17, 1))

    asyncio.run(run())


def test_exact_combined_budget_succeeds_then_one_less_fails():
    async def run():
        base, _ = await collect(CombinedWire())
        ev = base.evidence
        budget = RawProductionBudget(
            ev.request_attempts, ev.total_response_bytes, ev.protocol_operations
        )
        wire = CombinedWire()
        session = CompleteRawProductionSession(wire.context, MONTHS[0], budget=budget)
        await collect(wire, session=session)
        assert session.evidence.complete
        wire = CombinedWire()
        session = CompleteRawProductionSession(
            wire.context,
            MONTHS[0],
            budget=replace(budget, max_operations=budget.max_operations - 1),
        )
        with pytest.raises(ValueError):
            await collect(wire, session=session)
        assert not session.evidence.complete

    asyncio.run(run())


def test_historical_structural_real_proof_digest_and_manifest():
    root = Path("artifacts/runtime/openttd-15.3-structural-world-real-attempt1")
    assert root.is_dir()
    for line in (root / "artifact-manifest.sha256").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    assert "REAL_SUCCESS" in (root / "proof-evidence.json").read_text()


@pytest.mark.parametrize("counter", ["_attempts", "_bytes", "_operations"])
def test_counter_reset_cannot_complete(counter):
    async def run():
        wire = CombinedWire()
        session = CompleteRawProductionSession(wire.context, MONTHS[0], timeout=0.05)

        async def evidence(q, e):
            if len(wire.production_requests) == 1:
                setattr(session, counter, 0)
            return await wire.evidence_for(q, e)

        with pytest.raises(ValueError, match="accounting mismatch"):
            await collect(wire, session=session, production_evidence=evidence)
        assert not session.evidence.complete and session.production is None

    asyncio.run(run())


def test_partial_production_failure_retains_records_but_not_observation():
    async def run():
        wire = CombinedWire()
        session = CompleteRawProductionSession(wire.context, MONTHS[0], timeout=0.05)

        async def evidence(q, e):
            if len(wire.production_requests) == 3:
                raise ValueError("third record liveness missing")
            return await wire.evidence_for(q, e)

        with pytest.raises(ValueError):
            await collect(wire, session=session, production_evidence=evidence)
        assert session.production_session is not None
        assert len(session.production_session.evidence.transactions) == 2
        assert not session.production_session.evidence.complete
        assert not session.evidence.complete and session.production is None
        assert wire.writer.close.call_count == 1

    asyncio.run(run())


def test_economy_window_crossing_fails_without_wait():
    async def run():
        wire = CombinedWire()
        wire.date = 31
        session = CompleteRawProductionSession(wire.context, MONTHS[0], timeout=0.05)
        with pytest.raises(ValueError, match="crossed economy window"):
            await collect(wire, session=session)
        assert len(wire.production_requests) == 1 and not session.evidence.complete

    asyncio.run(run())


def test_per_record_and_phase_semantic_chains():
    async def run():
        wire = CombinedWire()
        session, (_, p) = await collect(wire)
        events = session.production_session.evidence.events
        assert (
            events.index("INDUSTRY_PRODUCTION_PHASE_STARTED")
            < events.index("TARGET_SET_FINALIZED")
            < events.index("PRODUCTION_RECORD_VALIDATED")
        )
        assert (
            events.index("COMPLETE_PRODUCTION_COVERAGE_VALIDATED")
            < events.index("INDUSTRY_PRODUCTION_OBSERVATION_ASSEMBLED")
            < events.index("PRODUCTION_QUALIFICATION_EVALUATED")
        )
        for t in p.transactions:
            assert t.gamescript.ordered_sequence == (
                "BRIDGE_REQUEST_RECEIVED",
                "INDUSTRY_PRODUCTION_READ",
                "BRIDGE_RESPONSE_SENT",
                "BRIDGE_POST_RESPONSE_ALIVE",
            )
            assert t.exchange.ordered_sequence == (
                "INDUSTRY_PRODUCTION_REQUEST_SENT",
                "INDUSTRY_PRODUCTION_RESPONSE_RECEIVED",
                "TRANSPORT_RECEIPT_CREATED",
                "PRODUCTION_RECORD_VALIDATED",
            )
        assert not session.evidence.qualified_for_planning

    asyncio.run(run())
