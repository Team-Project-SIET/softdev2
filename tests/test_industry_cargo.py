"""Controlled cargo capability at public query/enrichment seams."""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.simulation.openttd.industry_cargo import (
    CARGO_NETWORK_SEQUENCE,
    IndustryCargoCapability,
    IndustryCargoReceipt,
    IndustryCargoRequest,
    IndustryCargoResponse,
)
from app.simulation.openttd.industry_cargo_evidence import parse_industry_cargo_evidence


def test_canonical_request():
    from app.simulation.openttd.industry_cargo import IndustryCargoRequest

    assert (
        IndustryCargoRequest("cargo-001", 3).to_bytes()
        == b'{"industry_id":3,"protocol":1,"request_id":"cargo-001","type":"industry_cargo"}'
    )


def native_cargo(produces=(63, 2, 17), accepts=(8, 0), industry=3, request_id="cargo"):
    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(Path("tests/fixtures/industry_cargo_api_15.nut").read_text())
    vm.execute(f"::produced_ids={list(produces)}; ::accepted_ids={list(accepts)};")
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="industry_cargo",request_id="'
        + request_id
        + '",industry_id='
        + str(industry)
        + "})); ::bridge <- NoMutationBridge(); try { bridge.Start(); } "
        'catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
    )
    root = vm.get_roottable()
    raw = (
        "".join("dbg: [script:4] [18] [I] " + str(line) + "\n" for line in root["markers"])
    ).encode()
    if not len(root["replies"]):
        return None, raw
    table = root["replies"][0]
    response = IndustryCargoResponse(
        str(table["request_id"]),
        IndustryCargoCapability(
            int(table["industry_id"]),
            tuple(int(i) for i in table["produces"]),
            tuple(int(i) for i in table["accepts"]),
        ),
    )
    return response, raw


@pytest.mark.parametrize(
    "produces,accepts",
    [
        ((), ()),
        ((1,), ()),
        ((), (2,)),
        ((1,), (1,)),
        ((63, 2, 17), (8, 0)),
        (tuple(range(48, 64)), tuple(range(48, 64))),
    ],
)
def test_native_handler_capabilities_sorted_and_alive(produces, accepts):
    response, raw = native_cargo(produces, accepts)
    assert response.capability == IndustryCargoCapability(
        3, tuple(sorted(produces)), tuple(sorted(accepts))
    )
    parse_industry_cargo_evidence(raw, "cargo").require_complete(
        IndustryCargoRequest("cargo", 3), response
    )
    assert b"0x" not in raw
    assert len(response.to_bytes()) <= 512


@pytest.mark.parametrize(
    "produces,accepts,industry",
    [((1, 1), (), 3), ((), (2, 2), 3), ((64,), (), 3), (tuple(range(17)), (), 3), ((), (), 63999)],
)
def test_native_invalid_query_rejected_without_empty_reply(produces, accepts, industry):
    response, raw = native_cargo(produces, accepts, industry)
    assert response is None and b"BRIDGE_POST_RESPONSE_ALIVE" not in raw


@pytest.mark.parametrize("ids", [(1, 1), (2, 1), (-1,), (64,), (True,), tuple(range(17))])
@pytest.mark.parametrize("field", ["produces", "accepts"])
def test_invalid_cargo_sets_rejected(ids, field):
    with pytest.raises(ValueError):
        IndustryCargoCapability(
            3, ids if field == "produces" else (), ids if field == "accepts" else ()
        )


@pytest.mark.parametrize(
    "change",
    [
        {"protocol": 2},
        {"request_id": "other"},
        {"industry_id": 4},
        {"type": "world_info_result"},
        {"status": "failed"},
        {"produces": [1, 1]},
    ],
)
def test_wrong_response_correlation(change):
    q = IndustryCargoRequest("cargo", 3)
    obj = json.loads(
        IndustryCargoResponse("cargo", IndustryCargoCapability(3, (1,), (2,))).to_bytes()
    )
    obj.update(change)
    with pytest.raises(ValueError):
        IndustryCargoReceipt.correlate(q.to_bytes(), json.dumps(obj).encode())


class CargoWire:
    def __init__(self, *, failure=None, change=None):
        from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
        from app.simulation.openttd.gamescript_transport import (
            GameScriptSession,
            GameScriptTransport,
        )

        self.reader = asyncio.StreamReader()
        self.requests = []
        self.writer = Mock(spec=asyncio.StreamWriter)
        self.writer.drain = AsyncMock()

        def send(frame):
            if frame[2] == 7:
                self.reader.feed_data(encode_admin_frame(126, frame[3:]))
                return
            if frame[2] != 6:
                return
            q = IndustryCargoRequest.parse(frame[3:-1])
            self.requests.append(q)
            if failure == "timeout":
                return
            if failure == "disconnect":
                self.reader.feed_eof()
                return
            obj = json.loads(
                IndustryCargoResponse(
                    q.request_id, IndustryCargoCapability(q.industry_id, (2, 17, 63), (0, 8))
                ).to_bytes()
            )
            if change:
                change(obj)
            body = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\0"
            self.reader.feed_data(encode_admin_frame(107, b"\x01\0\0\0"))
            self.reader.feed_data(encode_admin_frame(124, body))
            if failure == "duplicate":
                self.reader.feed_data(encode_admin_frame(124, body))

        self.writer.write.side_effect = send
        self.transport = GameScriptTransport(
            GameScriptSession(self.reader, self.writer), ServerProtocol(3, ((9, 64),))
        )

    async def evidence(self, q, exchange):
        _, raw = native_cargo(industry=q.industry_id, request_id=q.request_id)
        return parse_industry_cargo_evidence(raw, q.request_id)


def test_secure_transport_receipt_and_native_correlation():
    async def scenario():
        wire = CargoWire()
        q = IndustryCargoRequest("cargo", 3)
        exchange = await wire.transport.industry_cargo(q)
        exchange.validate()
        assert (
            exchange.protocol_operations == 8
            and exchange.ordered_sequence == CARGO_NETWORK_SEQUENCE
        )
        evidence = await wire.evidence(q, exchange)
        evidence.require_complete(q, exchange.response)
        assert exchange.receipt.request_payload_sha256 == hashlib.sha256(q.to_bytes()).hexdigest()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure,kind",
    [
        ("timeout", "TransportTimeout"),
        ("disconnect", "TransportDisconnected"),
        ("duplicate", "TransportProtocolError"),
    ],
)
def test_transport_failure_distinct_no_resend(failure, kind):
    async def scenario():
        wire = CargoWire(failure=failure)
        with pytest.raises((ValueError, TimeoutError, ConnectionError)) as caught:
            await wire.transport.industry_cargo(IndustryCargoRequest("cargo", 3), timeout=0.02)
        assert type(caught.value).__name__ == kind
        assert len(wire.requests) == 1
        with pytest.raises(ValueError):
            await wire.transport.industry_cargo(IndustryCargoRequest("next", 3))
        assert len(wire.requests) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "marker", ["INDUSTRY_CARGO_READ", "BRIDGE_RESPONSE_SENT", "BRIDGE_POST_RESPONSE_ALIVE"]
)
def test_missing_native_evidence_fails(marker):
    response, raw = native_cargo()
    raw = b"".join(line for line in raw.splitlines(keepends=True) if marker.encode() not in line)
    with pytest.raises(ValueError):
        parse_industry_cargo_evidence(raw, "cargo").require_complete(
            IndustryCargoRequest("cargo", 3), response
        )


def test_payload_and_source_limits():
    response = IndustryCargoResponse(
        "x" * 64, IndustryCargoCapability(63999, tuple(range(48, 64)), tuple(range(48, 64)))
    )
    assert len(response.to_bytes()) == 280 and 280 <= 512 and 280 < 1450
    manifest = json.loads(Path("tests/reference/industry_cargo_15_3/manifest.json").read_text())
    for name, item in manifest["files"].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == item["sha256"]
    assert "NUM_CARGO = 64" in Path("tests/reference/industry_cargo_15_3/cargo_type.h").read_text()
    authority = Path("tests/reference/industry_cargo_15_3/industry_type.h").read_text()
    assert "INDUSTRY_NUM_INPUTS = 16" in authority and "INDUSTRY_NUM_OUTPUTS = 16" in authority
    assert (
        "temporarily not accepted"
        in Path("tests/reference/industry_cargo_15_3/script_cargolist.hpp").read_text()
    )


def test_no_dynamic_or_mutation_apis_in_new_handler():
    source = Path("app/simulation/openttd/gamescript_bridge_package/main.nut").read_text()
    handler = source.split("function IndustryCargo(", 1)[1].split("function ", 1)[0]
    handler += source.split("function CargoIDs(", 1)[1].split("function ", 1)[0]
    for token in (
        "LastMonth",
        "Transported",
        "Stockpile",
        "GSCompany",
        "GSRoad",
        "GSVehicle",
        "GSOrder",
        "GSTile",
        "RCON",
        "GSIndustryList",
    ):
        assert token not in handler


async def inventory_fixture(ids=(3, 17)):
    from test_industry_inventory import InventoryWire, world_context

    from app.simulation.openttd.industry_query import IndustryInventorySession

    wire = InventoryWire(ids=ids)
    return await IndustryInventorySession("inventory", world_context()).collect(
        wire.transport, wire.evidence
    )


def test_complete_enrichment_preserves_inventory_and_digest_order():
    from app.simulation.openttd.industry_capability import IndustryCapabilitySession

    async def scenario():
        inventory = await inventory_fixture()
        digest = inventory.inventory_digest
        wire = CargoWire()
        session = IndustryCapabilitySession("capability", inventory)
        result = await session.collect(wire.transport, wire.evidence)
        assert result.complete and [c.industry_id for c in result.capabilities] == [3, 17]
        assert [q.request_id for q in wire.requests] == ["capability-i00003", "capability-i00017"]
        assert inventory.inventory_digest == digest and result.inventory is inventory
        assert (
            replace(result, transactions=tuple(reversed(result.transactions))).capability_digest
            == result.capability_digest
        )
        assert session.evidence.events == (
            "CAPABILITY_SESSION_STARTED",
            "CAPABILITY_VALIDATED",
            "CAPABILITY_VALIDATED",
            "CAPABILITY_OBSERVATION_ASSEMBLED",
            "CAPABILITY_SESSION_COMPLETED",
        )
        for transactions in ((result.transactions[0],), result.transactions + result.transactions):
            with pytest.raises(ValueError):
                replace(result, transactions=transactions)
        with pytest.raises((ValueError, TimeoutError, ConnectionError)):
            await session.collect(wire.transport, wire.evidence)
        assert len(wire.requests) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "budget",
    [
        dict(max_industries=1),
        dict(max_requests=1),
        dict(max_response_bytes=1),
        dict(max_operations=4),
    ],
)
def test_capability_budget_failure_is_incomplete(budget):
    from app.simulation.openttd.industry_capability import (
        CapabilityBudget,
        IndustryCapabilitySession,
    )

    async def scenario():
        session = IndustryCapabilitySession(
            "cap", await inventory_fixture(), budget=CapabilityBudget(**budget)
        )
        wire = CargoWire()
        with pytest.raises((ValueError, TimeoutError, ConnectionError)):
            await session.collect(wire.transport, wire.evidence)
        assert (
            not session.evidence.complete
            and session.evidence.events[-1] == "CAPABILITY_SESSION_FAILED"
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["timeout", "disconnect", "duplicate"])
def test_capability_session_failure_no_retry_reconnect(failure):
    from app.simulation.openttd.industry_capability import IndustryCapabilitySession

    async def scenario():
        wire = CargoWire(failure=failure)
        session = IndustryCapabilitySession("cap", await inventory_fixture(), timeout=0.02)
        with pytest.raises((ValueError, TimeoutError, ConnectionError)):
            await session.collect(wire.transport, wire.evidence)
        assert not session.evidence.complete and len(wire.requests) == 1

    asyncio.run(scenario())


def test_empty_inventory_requires_no_capability_request():
    from app.simulation.openttd.industry_capability import IndustryCapabilitySession

    async def scenario():
        wire = CargoWire()
        result = await IndustryCapabilitySession("cap", await inventory_fixture(())).collect(
            wire.transport, wire.evidence
        )
        assert result.complete and result.capabilities == () and wire.requests == []

    asyncio.run(scenario())


@pytest.mark.parametrize("industry_id", [-1, 64000, True, "3", None])
def test_invalid_industry_request_id_rejected(industry_id):
    with pytest.raises((ValueError, TypeError)):
        IndustryCargoRequest("cargo", industry_id)


@pytest.mark.parametrize("bad", ["(null : 0x00000000)", "Null", "null "])
def test_noncanonical_optional_evidence_rejected(bad):
    response, raw = native_cargo((), ())
    raw = raw.replace(b"first_produced=null ", ("first_produced=" + bad + " ").encode())
    with pytest.raises(ValueError):
        parse_industry_cargo_evidence(raw, "cargo").require_complete(
            IndustryCargoRequest("cargo", 3), response
        )


def test_extra_industry_capability_rejected():
    from app.simulation.openttd.industry_capability import IndustryCapabilitySession

    async def scenario():
        inventory = await inventory_fixture()
        wire = CargoWire()
        enriched = await IndustryCapabilitySession("cap", inventory).collect(
            wire.transport, wire.evidence
        )
        smaller = await inventory_fixture((3,))
        with pytest.raises(ValueError):
            replace(enriched, inventory=smaller)

    asyncio.run(scenario())


def test_session_rejects_connection_replacement_and_retains_receipt():
    from app.simulation.openttd.industry_capability import IndustryCapabilitySession

    async def scenario():
        wire = CargoWire()
        session = IndustryCapabilitySession("cap", await inventory_fixture())

        async def swap(q, exchange):
            value = await wire.evidence(q, exchange)
            wire.transport.session = Mock()
            return value

        with pytest.raises(ValueError):
            await session.collect(wire.transport, swap)
        assert (
            not session.evidence.complete
            and len(session.evidence.exchanges) == 1
            and len(wire.requests) == 1
        )

    asyncio.run(scenario())


def test_exact_session_budget_and_deterministic_digest():
    from app.simulation.openttd.industry_capability import (
        CapabilityBudget,
        IndustryCapabilitySession,
    )

    async def scenario():
        inventory = await inventory_fixture()
        first_wire = CargoWire()
        first = await IndustryCapabilitySession("first", inventory).collect(
            first_wire.transport, first_wire.evidence
        )
        wire = CargoWire()
        second = await IndustryCapabilitySession(
            "second",
            inventory,
            budget=CapabilityBudget(
                max_industries=2,
                max_requests=2,
                max_response_bytes=first.total_response_bytes + 2,
                max_operations=first.protocol_operations,
            ),
        ).collect(wire.transport, wire.evidence)
        assert first.capability_digest == second.capability_digest
        assert first.inventory.inventory_digest == second.inventory.inventory_digest

    asyncio.run(scenario())


def test_binding_names_follow_exact_generated_conventions():
    generator = Path("tests/reference/industry_page_bindings_15_3/SquirrelExport.cmake").read_text()
    assert 'string(REGEX REPLACE "^Script" "${APIUC}" API_CLS "${CLS}")' in generator
    declarations = Path("tests/reference/industry_cargo_15_3/script_cargolist.hpp").read_text()
    for name in ("ScriptCargoList_IndustryProducing", "ScriptCargoList_IndustryAccepting"):
        assert "class " + name + " : public ScriptList" in declarations
        assert "@api ai game" in declarations
        assert (
            name.replace("Script", "GS", 1)
            in Path("app/simulation/openttd/gamescript_bridge_package/main.nut").read_text()
        )


def test_transport_and_enrichment_import_boundaries():
    import ast

    for name in ("industry_cargo.py", "industry_cargo_evidence.py", "industry_capability.py"):
        for node in ast.walk(ast.parse(Path("app/simulation/openttd", name).read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.planning")
            if isinstance(node, ast.Import):
                assert all(not a.name.startswith("app.planning") for a in node.names)


def test_real_inventory_checkpoint_fixture_validates():
    root = Path("tests/fixtures/industry_inventory_real_checkpoint")
    from app.simulation.openttd.industry_page import (
        IndustryPageReceipt,
        IndustryPageRequest,
        IndustryPageResponse,
    )
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

    requests = [
        json.loads(line) for line in (root / "page-requests.jsonl").read_text().splitlines()
    ]
    responses = [
        json.loads(line)["raw_json"].encode()
        for line in (root / "page-responses.jsonl").read_text().splitlines()
    ]
    assert len(requests) == len(responses) == 5
    records = []
    for obj, payload in zip(requests, responses, strict=True):
        q = IndustryPageRequest.parse(json.dumps(obj).encode())
        r = IndustryPageResponse.parse(payload)
        IndustryPageReceipt.correlate(q.to_bytes(), payload)
        parse_industry_page_evidence(
            (root / "gamescript-supporting.log").read_bytes(), q.request_id
        ).require_complete(q, r)
        records.extend(r.industries)
    from dataclasses import asdict

    raw = json.dumps([asdict(r) for r in records], sort_keys=True, separators=(",", ":")).encode()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "dce9b4d257af150776e679b09c74880b918163b86ae5e5f9f6e30e35d26c865a"
    )
