"""Controlled production DTO/qualification/session seams; no live runtime."""

import asyncio
import hashlib
import json
from dataclasses import asdict, replace

import pytest
from test_structural_world import StructuralWire, sources

from app.simulation.openttd.admin_protocol import encode_admin_frame
from app.simulation.openttd.gamescript_transport import TransportDisconnected, TransportTimeout
from app.simulation.openttd.industry_production import (
    MAX_PRODUCTION_RESPONSE_BYTES,
    IndustryProductionRecord,
    IndustryProductionRequest,
    IndustryProductionResponse,
)
from app.simulation.openttd.industry_production_evidence import parse_industry_production_evidence
from app.simulation.openttd.production_observation import (
    MAX_PRODUCTION_BYTES,
    MAX_PRODUCTION_PAIRS,
    EconomyMonth,
    ProductionBudget,
    ProductionQualificationStatus,
    ProductionWindowQualification,
)
from app.simulation.openttd.production_session import (
    IndustryProductionSession,
    ProductionDecisionBoundary,
)
from app.simulation.openttd.structural_world import StructuralWorldObservation


def test_canonical_request():
    request = IndustryProductionRequest("prod-001", 3, 1)
    expected = (
        b'{"cargo_id":1,"industry_id":3,"protocol":1,'
        b'"request_id":"prod-001","type":"industry_production"}'
    )
    assert request.to_bytes() == expected
    assert request.request_digest == hashlib.sha256(expected).hexdigest()


MONTHS = (
    EconomyMonth(1950, 1, 0, 31),
    EconomyMonth(1950, 2, 31, 59),
    EconomyMonth(1950, 3, 59, 90),
)


class ProductionWire(StructuralWire):
    def __init__(self, *, produces=(1, 63), industries=(2, 17), fail=None, duplicate=False):
        super().__init__(industries=industries, produces=produces)
        original = self.writer.write.side_effect
        self.production_requests = []
        self.metrics = (120, 7, 5)
        self.date = 60
        self.duplicate = duplicate

        def send(frame):
            if frame[2] != 6 or json.loads(frame[3:-1])["type"] != "industry_production":
                return original(frame)
            q = IndustryProductionRequest.parse(frame[3:-1])
            self.production_requests.append(q)
            if fail == "disconnect":
                self.reader.feed_eof()
                return
            if fail == "timeout":
                return
            r = IndustryProductionResponse(
                q.request_id,
                IndustryProductionRecord(
                    q.industry_id, q.cargo_id, self.date, self.date, *self.metrics
                ),
            )
            self.reader.feed_data(encode_admin_frame(124, r.to_bytes() + b"\0"))
            if self.duplicate:
                self.reader.feed_data(encode_admin_frame(124, r.to_bytes() + b"\0"))

        self.writer.write.side_effect = send

    async def evidence_for(self, q, exchange):
        read = " ".join(f"{k}={v}" for k, v in asdict(exchange.response.record).items())
        return parse_industry_production_evidence(
            self.log(q, "industry_production", "INDUSTRY_PRODUCTION_READ", read), q.request_id
        )


async def source_for(wire):
    return StructuralWorldObservation(*await sources(wire))


def qualification(source, rollovers=2):
    q = ProductionWindowQualification.initial(source, MONTHS[0])
    for month in MONTHS[1 : rollovers + 1]:
        q = q.observe(month, source.inventory.context)
    return q


@pytest.mark.parametrize(
    "rollovers,status",
    [
        (0, ProductionQualificationStatus.UNQUALIFIED_INITIAL),
        (1, ProductionQualificationStatus.UNQUALIFIED_AFTER_FIRST_ROLLOVER),
        (2, ProductionQualificationStatus.QUALIFIED_AFTER_SECOND_ROLLOVER),
    ],
)
def test_complete_not_equal_qualified(rollovers, status):
    async def run():
        wire = ProductionWire()
        source = await source_for(wire)
        q = qualification(source, rollovers)
        wire.date = MONTHS[rollovers].start_date
        session = IndustryProductionSession(wire.transport, source, wire.context, q)
        observation = await session.collect(wire.evidence_for)
        assert observation.complete and observation.qualified_for_planning == (rollovers == 2)
        assert q.status is status and q.rollover_count == rollovers
        assert [r.pair for r in observation.records] == [(2, 1), (2, 63), (17, 1), (17, 63)]
        assert [q.request_id for q in wire.production_requests] == [
            f"openttd15-industry-production-001-p{i:03d}" for i in range(1, 5)
        ]
        assert observation.records[0].last_month_transported == 7
        assert (
            session.evidence.complete
            and session.evidence.retries == session.evidence.reconnects == 0
        )
        assert session.evidence.events[-2:] == (
            "PRODUCTION_QUALIFICATION_EVALUATED",
            "INDUSTRY_PRODUCTION_SESSION_COMPLETED",
        )
        with pytest.raises(ValueError):
            await session.collect(wire.evidence_for)
        return observation

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("industry_id", -1),
        ("industry_id", 64000),
        ("cargo_id", 64),
        ("cargo_id", True),
        ("last_month_produced", -1),
        ("last_month_produced", 65536),
        ("last_month_transported", -1),
        ("last_month_transported_pct", 101),
        ("economy_date_after", 0),
    ],
)
def test_invalid_raw_record(field, value):
    r = IndustryProductionRecord(2, 1, 60, 60, 120, 7, 5)
    with pytest.raises(ValueError):
        replace(r, **{field: value})


@pytest.mark.parametrize(
    "metrics", [(0, 0, 0), (0, 65535, 0), (100, 120, 100), (65535, 65535, 100)]
)
def test_zero_and_native_wrap_semantics(metrics):
    assert IndustryProductionRecord(2, 1, 60, 60, *metrics).last_month_produced == metrics[0]


def test_payload_bound():
    r = IndustryProductionResponse(
        "x" * 64,
        IndustryProductionRecord(63999, 63, 2147483647, 2147483647, 65535, 65535, 100),
    )
    assert len(r.to_bytes()) == 335 == MAX_PRODUCTION_RESPONSE_BYTES
    assert 512 - len(r.to_bytes()) == 177 and len(r.to_bytes()) < 1450
    assert MAX_PRODUCTION_PAIRS == 512 and MAX_PRODUCTION_BYTES == 171520


@pytest.mark.parametrize(
    "mode",
    [
        "backward",
        "skip",
        "duplicate",
        "wrong_world",
        "wrong_runtime",
        "wrong_connection",
        "wrong_digest",
    ],
)
def test_rollover_and_provenance(mode):
    async def run():
        wire = ProductionWire()
        source = await source_for(wire)
        q = qualification(source, 1)
        if mode == "duplicate":
            assert q.observe(MONTHS[1], wire.context) is q
            return
        if mode == "backward":
            with pytest.raises(ValueError):
                q.observe(MONTHS[0], wire.context)
        elif mode == "skip":
            with pytest.raises(ValueError):
                qualification(source, 0).observe(MONTHS[2], wire.context)
        else:
            if mode == "wrong_digest":
                q = replace(q, source_structural_world_digest="a" * 64)
                ctx = wire.context
            elif mode == "wrong_connection":
                ctx = replace(wire.context, connection_identity=object())
            elif mode == "wrong_world":
                ctx = replace(wire.context, configuration_digest="d" * 64)
            else:
                ctx = replace(
                    wire.context,
                    world=replace(
                        wire.context.world,
                        runtime_identity=replace(
                            wire.context.world.runtime_identity, sha256="e" * 64
                        ),
                    ),
                )
            with pytest.raises(ValueError):
                IndustryProductionSession(wire.transport, source, ctx, q)

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "disconnect",
        "duplicate",
        "missing_liveness",
        "accepted_only",
        "extra_pair",
        "missing_pair",
        "connection",
        "mixed_window",
        "post_decision",
        "during_decision",
        "bytes",
        "requests",
        "operations",
    ],
)
def test_failure_terminal_and_partial_evidence(failure):
    async def run():
        wire = ProductionWire(fail=failure, duplicate=failure == "duplicate")
        source = await source_for(wire)
        q = qualification(source)
        budget = ProductionBudget()
        if failure in ("bytes", "requests", "operations"):
            budget = ProductionBudget(
                **{
                    "bytes": {"max_response_bytes": 1},
                    "requests": {"max_requests": 1},
                    "operations": {"max_operations": 4},
                }[failure]
            )
        decision = ProductionDecisionBoundary()
        session = IndustryProductionSession(
            wire.transport, source, wire.context, q, decision=decision, timeout=0.02, budget=budget
        )
        original_evidence = wire.evidence_for

        async def evidence(request, exchange):
            if failure == "missing_liveness":
                gs = await original_evidence(request, exchange)
                return parse_industry_production_evidence(
                    gs.raw_log.rsplit(b"dbg:", 1)[0], request.request_id
                )
            if failure == "connection":
                wire.transport.session = ProductionWire().transport.session
            if failure == "during_decision":
                decision.mark_decision()
            return await original_evidence(request, exchange)

        if failure == "mixed_window":
            wire.date = 90
        if failure == "post_decision":
            decision.mark_decision()
        if failure in ("accepted_only", "extra_pair", "missing_pair"):
            result = await session.collect(evidence)
            records = list(result.records)
            if failure == "missing_pair":
                records.pop()
            else:
                records[0] = replace(records[0], cargo_id=9 if failure == "accepted_only" else 8)
            with pytest.raises(ValueError):
                replace(result, records=tuple(records))
            return
        error_type = {"timeout": TransportTimeout, "disconnect": TransportDisconnected}.get(
            failure, ValueError
        )
        with pytest.raises(error_type):
            await session.collect(evidence)
        assert session.observation is None and not session.evidence.complete
        assert session.evidence.events[-1] == "INDUSTRY_PRODUCTION_SESSION_FAILED"
        assert (
            session.evidence.request_attempts
            == len(wire.production_requests)
            == (0 if failure == "post_decision" else 1)
        )
        with pytest.raises(ValueError, match="cannot retry/resume"):
            await session.collect(evidence)

    asyncio.run(run())


def test_digest_and_source_immutability():
    async def run():
        wire = ProductionWire()
        source = await source_for(wire)
        before = source.to_bytes()
        o = await IndustryProductionSession(
            wire.transport, source, wire.context, qualification(source)
        ).collect(wire.evidence_for)
        assert source.to_bytes() == before and source.complete
        assert (
            replace(o, transactions=tuple(reversed(o.transactions))).production_digest
            == o.production_digest
        )
        q = replace(o.qualification, observed_months=(MONTHS[2],))
        assert replace(o, qualification=q).production_digest != o.production_digest
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            setattr(o.records[0], "last_month_produced", 1)

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,maximum",
    [("max_requests", 512), ("max_response_bytes", 171520), ("max_operations", 4096)],
)
def test_exact_and_over_budget(field, maximum):
    b = ProductionBudget()
    b.require(512, 171520, 4096)
    with pytest.raises(ValueError):
        replace(b, **{field: maximum + 1})
    amounts = {
        "max_requests": (513, 0, 0),
        "max_response_bytes": (0, 183297, 0),
        "max_operations": (0, 0, 4097),
    }
    with pytest.raises(ValueError):
        b.require(*amounts[field])


def native_production(industry=3, cargo=1, metrics=(120, 7, 5), send_ok=True):
    from pathlib import Path

    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(Path("tests/fixtures/industry_production_api_15.nut").read_text())
    vm.execute(
        f"::production_metrics = {json.dumps(list(metrics))}; ::send_ok = {str(send_ok).lower()};"
    )
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="industry_production",request_id="prod",industry_id='
        + str(industry)
        + ",cargo_id="
        + str(cargo)
        + "})); ::bridge <- NoMutationBridge(); try { bridge.Start(); }"
        + ' catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
    )
    root = vm.get_roottable()
    raw = ("".join("dbg: [script:4] [18] [I] " + str(s) + "\n" for s in root["markers"])).encode()
    if not len(root["replies"]):
        return None, raw
    obj = root["replies"][0]
    fields = {k: int(obj[k]) for k in IndustryProductionRecord.__dataclass_fields__}
    return IndustryProductionResponse(
        str(obj["request_id"]), IndustryProductionRecord(**fields)
    ), raw


@pytest.mark.parametrize("metrics", [(0, 0, 0), (120, 0, 0), (65535, 65535, 100), (0, 65535, 0)])
def test_real_handler_under_controlled_sqvm(metrics):
    response, raw = native_production(metrics=metrics)
    assert response.record.last_month_produced == metrics[0]
    assert len(response.to_bytes()) <= 335
    parse_industry_production_evidence(raw, "prod").require_complete(
        IndustryProductionRequest("prod", 3, 1), response
    )
    assert b"0x" not in raw


@pytest.mark.parametrize("industry,cargo", [(2, 1), (3, 2), (3, 64), (3, -1)])
def test_sqvm_invalid_and_accepted_only(industry, cargo):
    response, raw = native_production(industry, cargo)
    assert response is None and b"BRIDGE_RESPONSE_SENT" not in raw


@pytest.mark.parametrize("metrics", [(-1, 0, 0), (0, -1, 0), (0, 0, 101), (True, 0, 0)])
def test_sqvm_invalid_native_fields(metrics):
    # Boolean fixture spelling must be native Squirrel, not Python debug formatting.
    response, raw = native_production(metrics=metrics)
    assert response is None


def test_sqvm_failed_send_has_no_success_evidence():
    response, raw = native_production(send_ok=False)
    assert response is None and b"BRIDGE_RESPONSE_SENT" not in raw


@pytest.mark.parametrize(
    "mutation",
    [
        {"request_id": "wrong"},
        {"type": "industry_cargo_result"},
        {"cargo_id": 9},
        {"industry_id": 17},
        {"status": "error"},
        {"last_month_produced": True},
    ],
)
def test_correlated_response_rejection(mutation):
    from app.simulation.openttd.industry_production import IndustryProductionReceipt

    q = IndustryProductionRequest("prod", 3, 1)
    r = IndustryProductionResponse("prod", IndustryProductionRecord(3, 1, 60, 60, 1, 0, 0))
    obj = json.loads(r.to_bytes())
    obj.update(mutation)
    with pytest.raises(ValueError):
        IndustryProductionReceipt.correlate(q.to_bytes(), json.dumps(obj).encode())


def test_transport_receipt_alone_not_qualification():
    response, raw = native_production()
    assert response.record.last_month_produced > 0  # Could be initialization estimate.
    # A raw response/receipt has no qualification API.
    assert not hasattr(response, "qualified_for_planning")


@pytest.mark.parametrize(
    "bad", ["duplicate", "reordered", "missing_read", "missing_send", "missing_alive", "metadata"]
)
def test_evidence_rejects_incomplete_chain(bad):
    response, raw = native_production()
    lines = raw.splitlines(keepends=True)
    if bad == "duplicate":
        lines.append(lines[-1])
    elif bad == "reordered":
        lines[1], lines[2] = lines[2], lines[1]
    elif bad == "missing_read":
        lines = [s for s in lines if b"INDUSTRY_PRODUCTION_READ" not in s]
    elif bad == "missing_send":
        lines = [s for s in lines if b"BRIDGE_RESPONSE_SENT" not in s]
    elif bad == "missing_alive":
        lines = [s for s in lines if b"BRIDGE_POST_RESPONSE_ALIVE" not in s]
    else:
        lines = [s.replace(b"last_month_produced=120", b"last_month_produced=121") for s in lines]
    with pytest.raises(ValueError):
        parse_industry_production_evidence(b"".join(lines), "prod").require_complete(
            IndustryProductionRequest("prod", 3, 1), response
        )


def test_full_512_pair_bound_uses_existing_transport_without_reset():
    async def run():
        wire = ProductionWire(industries=tuple(range(32)), produces=tuple(range(16)))
        wire.cargoes = tuple(range(16))
        source = await source_for(wire)
        prior = len(wire.transport._used_ids)
        session = IndustryProductionSession(
            wire.transport, source, wire.context, qualification(source)
        )
        result = await session.collect(wire.evidence_for)
        assert result.complete and len(result.records) == 512
        assert session.evidence.request_attempts == 512
        assert len(wire.transport._used_ids) == prior + 512
        assert result.records[-1].pair == (31, 15)
        assert wire.production_requests[-1].request_id.endswith("-p512")
        with pytest.raises(ValueError, match="fresh request_id"):
            await wire.transport.industry_production(
                IndustryProductionRequest("beyond-budget", 31, 15)
            )
        assert len(wire.production_requests) == 512

    asyncio.run(run())


def test_empty_industry_world_has_zero_production_queries():
    async def run():
        wire = ProductionWire(industries=())
        source = await source_for(wire)
        session = IndustryProductionSession(
            wire.transport, source, wire.context, qualification(source, 0)
        )
        result = await session.collect(wire.evidence_for)
        assert result.complete and not result.qualified_for_planning
        assert result.records == () and session.evidence.request_attempts == 0
        assert not wire.production_requests

    asyncio.run(run())


def test_request_ids_and_transaction_order_do_not_change_semantic_digest():
    async def run():
        observations = []
        for prefix in ("alpha", "beta"):
            wire = ProductionWire()
            source = await source_for(wire)
            session = IndustryProductionSession(
                wire.transport, source, wire.context, qualification(source), session_id=prefix
            )
            observations.append(await session.collect(wire.evidence_for))
        first, second = observations
        assert first.production_digest == second.production_digest
        assert (
            first.transactions[0].exchange.receipt.request_id
            != second.transactions[0].exchange.receipt.request_id
        )
        assert (
            replace(first, transactions=tuple(reversed(first.transactions))).production_digest
            == first.production_digest
        )

    asyncio.run(run())


def test_connection_replacement_closes_original_owned_connection():
    async def run():
        wire = ProductionWire()
        source = await source_for(wire)
        session = IndustryProductionSession(
            wire.transport, source, wire.context, qualification(source)
        )
        wire.transport.session = ProductionWire().transport.session
        with pytest.raises(ValueError, match="connection replaced"):
            await session.collect(wire.evidence_for)
        assert wire.writer.close.called
        assert session.evidence.request_attempts == 0 and not session.evidence.complete

    asyncio.run(run())


def test_missing_and_accepted_only_pairs_cannot_assemble():
    async def run():
        wire = ProductionWire()
        source = await source_for(wire)
        session = IndustryProductionSession(
            wire.transport, source, wire.context, qualification(source)
        )
        result = await session.collect(wire.evidence_for)
        with pytest.raises(ValueError):
            replace(
                result,
                records=result.records[:-1],
                transactions=result.transactions[:-1],
                total_response_bytes=sum(
                    len(t.exchange.response_payload) for t in result.transactions[:-1]
                ),
                protocol_operations=sum(
                    t.exchange.protocol_operations for t in result.transactions[:-1]
                ),
            )
        accepted_only = IndustryProductionRecord(2, 9, 60, 60, 0, 0, 0)
        with pytest.raises(ValueError):
            replace(result, records=(accepted_only, *result.records[1:]))

    asyncio.run(run())


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_missing_native_evidence_times_out_without_retry_and_preserves_failure(cleanup_fails):
    async def run():
        from unittest.mock import AsyncMock

        wire = ProductionWire()
        source = await source_for(wire)
        session = IndustryProductionSession(
            wire.transport, source, wire.context, qualification(source), timeout=0.01
        )
        if cleanup_fails:
            wire.transport.session.close = AsyncMock(
                side_effect=RuntimeError("controlled cleanup failure")
            )

        async def never(request, exchange):
            await asyncio.Event().wait()

        with pytest.raises(TimeoutError):
            await session.collect(never)
        evidence = session.evidence
        assert evidence.failure == "TimeoutError"
        assert evidence.request_attempts == len(wire.production_requests) == 1
        assert len(evidence.exchanges) == 1 and len(evidence.transactions) == 0
        assert evidence.events[-1] == "INDUSTRY_PRODUCTION_SESSION_FAILED"
        assert not evidence.complete and session.observation is None
        assert evidence.retries == evidence.reconnects == 0
        assert evidence.cleanup_failure == ("controlled cleanup failure" if cleanup_fails else None)
        with pytest.raises(ValueError, match="cannot retry/resume"):
            await session.collect(never)

    asyncio.run(run())


def test_tagged_source_authority_and_native_bound_are_hash_pinned():
    from pathlib import Path

    manifest = json.loads(
        Path("tests/reference/industry_production_15_3/manifest.json").read_text()
    )
    assert manifest["version"] == "15.3"
    for filename, identity in manifest["files"].items():
        assert hashlib.sha256(Path(filename).read_bytes()).hexdigest() == identity["sha256"]
        assert "/OpenTTD/15.3/" in identity["url"]
    cpp = Path("tests/reference/industry_production_15_3/script_industry.cpp").read_text()
    bridge = Path("app/simulation/openttd/gamescript_bridge_package/main.nut").read_text()
    for method in (
        "GetLastMonthProduction",
        "GetLastMonthTransported",
        "GetLastMonthTransportedPercentage",
    ):
        assert "ScriptIndustry::" + method in cpp
        assert "GSIndustry." + method in bridge
    assert (
        "TimerGameEconomy::date"
        in Path("tests/reference/industry_production_15_3/script_date.cpp").read_text()
    )
    assert (
        "INDUSTRY_NUM_OUTPUTS = 16"
        in Path("tests/reference/industry_cargo_15_3/industry_type.h").read_text()
    )


def test_production_layer_has_no_planning_evaluation_or_mutation_imports():
    import ast
    from pathlib import Path

    files = [
        *Path("app/simulation/openttd").glob("industry_production*.py"),
        *Path("app/simulation/openttd").glob("production_*.py"),
    ]
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("app.planning", "app.evaluation"))
            elif isinstance(node, ast.Import):
                assert all(
                    not name.name.startswith(("app.planning", "app.evaluation"))
                    for name in node.names
                )
    bridge = Path("app/simulation/openttd/gamescript_bridge_package/main.nut").read_text()
    for invented in (
        "GetProductionRate",
        "GetCargoRate",
        "GetOutputStockpile",
        "GetStockpiledCargo",
        "GetCargoIncome",
        "SetProductionLevel",
        "SetControlFlags",
        "GSCompanyMode",
        "GSVehicle",
        "GSOrder",
        "GSRoad",
        "GSRail",
    ):
        assert invented not in bridge


def test_historical_bridge_contract_fixture_is_exact_checkpoint():
    from pathlib import Path

    root = Path("tests/fixtures/structural_bridge_checkpoint")
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["git_head"] == "b6f5cfaf65a4025edebf659cd4744b2534341ae1"
    assert all(
        hashlib.sha256((root / name).read_bytes()).hexdigest() == sha
        for name, sha in manifest["files"].items()
    )


def test_current_bridge_exact_read_only_industry_and_date_surface():
    import re
    from pathlib import Path

    source = Path("app/simulation/openttd/gamescript_bridge_package/main.nut").read_text()
    assert set(re.findall(r"GSIndustry\.([A-Za-z]+)\(", source)) == {
        "IsValidIndustry",
        "GetLocation",
        "GetIndustryType",
        "GetLastMonthProduction",
        "GetLastMonthTransported",
        "GetLastMonthTransportedPercentage",
    }
    assert set(re.findall(r"GSDate\.([A-Za-z]+)\(", source)) == {"GetCurrentDate"}


def test_audited_v1_defers_production_level_from_wire_native_reads_and_digest():
    from pathlib import Path

    response = IndustryProductionResponse("prod", IndustryProductionRecord(3, 1, 60, 60, 1, 0, 0))
    assert "production_level" not in json.loads(response.to_bytes())
    obj = json.loads(response.to_bytes())
    obj["production_level"] = 16
    with pytest.raises(ValueError):
        IndustryProductionResponse.parse(json.dumps(obj).encode())
    bridge = Path("app/simulation/openttd/gamescript_bridge_package/main.nut").read_text()
    assert "GetProductionLevel" not in bridge and "production_level" not in bridge
    assert "production_level" not in IndustryProductionRecord.__dataclass_fields__
