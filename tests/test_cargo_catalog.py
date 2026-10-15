"""Public cargo page/catalog seams; no native runtime launch."""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.simulation.openttd.cargo_catalog import (
    CargoCatalogBudget,
    CargoCatalogSession,
    validate_capability_catalog,
)
from app.simulation.openttd.cargo_page import (
    CARGO_PAGE_NETWORK_SEQUENCE,
    MAX_CARGO_PAGE_SIZE,
    CargoCatalogRecord,
    CargoPageReceipt,
    CargoPageRequest,
    CargoPageResponse,
)
from app.simulation.openttd.cargo_page_evidence import parse_cargo_page_evidence


def test_canonical_request_and_digest():
    payload = (
        b'{"after_id":null,"limit":2,"protocol":1,"request_id":"catalog-p001","type":"cargo_page"}'
    )
    request = CargoPageRequest("catalog-p001")
    assert request.to_bytes() == payload
    assert CargoPageRequest.parse(payload) == request
    assert hashlib.sha256(request.to_bytes()).hexdigest() == hashlib.sha256(payload).hexdigest()


def record(id=0, label="434F414C", freight=True, effect=0, classes=16):
    return CargoCatalogRecord(id, label, freight, effect, classes)


def test_sparse_cursor_terminal_and_payload_bound():
    records = (record(0), record(9), record(63))
    response = CargoPageResponse("catalog", records, None, False)
    assert CargoPageResponse.parse(response.to_bytes()) == response
    response.validate_page(CargoPageRequest("catalog", None, 4))
    assert (
        CargoPageReceipt.correlate(
            CargoPageRequest("catalog", None, 4).to_bytes(), response.to_bytes()
        ).request_id
        == "catalog"
    )
    worst = record(63, "FFFFFFFF", False, 5, 32767)
    # Literal lengths independently derived from the documented wire grammar.
    assert len(json.dumps(worst.to_wire(), separators=(",", ":")).encode()) == 76
    envelope = dict(
        protocol=1,
        type="cargo_page_result",
        request_id="x" * 64,
        status="ok",
        cargoes=[],
        next_after_id=None,
        has_more=False,
    )
    assert len(json.dumps(envelope, separators=(",", ":")).encode()) == 186
    ids = (60, 61, 62, 63)
    page = CargoPageResponse("x" * 64, tuple(replace(worst, cargo_id=i) for i in ids), None, False)
    assert MAX_CARGO_PAGE_SIZE == 4 and len(page.to_bytes()) == 493 < 512 < 1450
    envelope["cargoes"] = [worst.to_wire()] * 5
    assert len(json.dumps(envelope, separators=(",", ":")).encode()) == 570


@pytest.mark.parametrize(
    "change",
    [
        dict(cargo_id=-1),
        dict(cargo_id=64),
        dict(cargo_id=True),
        dict(cargo_label=None),
        dict(cargo_label="COAL"),
        dict(cargo_label="ffffffff"),
        dict(cargo_label="GG000000"),
        dict(is_freight=1),
        dict(town_effect=6),
        dict(town_effect=-1),
        dict(cargo_classes=32768),
        dict(cargo_classes=True),
    ],
)
def test_record_validation(change):
    with pytest.raises(ValueError):
        replace(record(), **change)


@pytest.mark.parametrize(
    "after,limit", [(-1, 2), (64, 2), (True, 2), (None, 0), (None, 5), (None, True)]
)
def test_invalid_request(after, limit):
    with pytest.raises(ValueError):
        CargoPageRequest("catalog", after, limit)


@pytest.mark.parametrize(
    "records,next_id,more",
    [
        ((record(2), record(1)), None, False),
        ((record(1), record(1)), None, False),
        ((), 1, True),
        ((record(1),), None, True),
        ((record(1),), 1, False),
    ],
)
def test_invalid_page_shape(records, next_id, more):
    with pytest.raises(ValueError):
        CargoPageResponse("catalog", records, next_id, more)


def test_empty_active_catalog_page_and_continuation():
    CargoPageResponse("q", (), None, False).validate_page(CargoPageRequest("q"))
    q = CargoPageRequest("q", 8, 2)
    CargoPageResponse("q", (record(9), record(63)), 63, True).validate_page(q)
    for response in (
        CargoPageResponse("q", (record(8),), None, False),
        CargoPageResponse("wrong", (), None, False),
        CargoPageResponse("q", (record(9),), 9, True),
    ):
        with pytest.raises(ValueError):
            response.validate_page(q)


@pytest.mark.parametrize(
    "change",
    [
        dict(type="industry_cargo_result"),
        dict(request_id="wrong"),
        dict(status="failed"),
        dict(protocol=2),
        dict(name="localized"),
    ],
)
def test_response_schema_and_correlation(change):
    q = CargoPageRequest("q")
    obj = json.loads(CargoPageResponse("q", (record(),), None, False).to_bytes())
    obj.update(change)
    with pytest.raises(ValueError):
        CargoPageReceipt.correlate(q.to_bytes(), json.dumps(obj).encode())


def native_page(ids=(63, 0, 9), after=None, limit=2, request_id="catalog", setup=""):
    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(Path("tests/fixtures/cargo_catalog_api_15.nut").read_text())
    vm.execute(f"::active_ids={list(ids)};" + setup)
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    cursor = "null" if after is None else str(after)
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="cargo_page",request_id="'
        + request_id
        + '",after_id='
        + cursor
        + ",limit="
        + str(limit)
        + "})); ::bridge <- NoMutationBridge(); try { bridge.Start(); }"
        ' catch(e) { if(e!="CONTROLLED_STOP") throw e; }'
    )
    root = vm.get_roottable()
    raw = (
        "".join("dbg: [script:4] [18] [I] " + str(line) + "\n" for line in root["markers"])
    ).encode()
    if not len(root["replies"]):
        return None, raw
    table = root["replies"][0]
    records = tuple(
        CargoCatalogRecord(
            int(r["id"]),
            str(r["label"]),
            bool(r["freight"]),
            int(r["town_effect"]),
            int(r["classes"]),
        )
        for r in table["cargoes"]
    )
    return CargoPageResponse(
        str(table["request_id"]),
        records,
        None if table["next_after_id"] is None else int(table["next_after_id"]),
        bool(table["has_more"]),
    ), raw


@pytest.mark.parametrize(
    "ids,after,limit,expected,more",
    [
        ((), None, 2, (), False),
        ((0,), None, 2, (0,), False),
        ((63, 0, 9), None, 2, (0, 9), True),
        ((63, 0, 9), 9, 2, (63,), False),
        ((63, 0, 9), 63, 4, (), False),
        ((63, 62, 61, 60), None, 4, (60, 61, 62, 63), False),
    ],
)
def test_native_active_list_sorted_page_and_liveness(ids, after, limit, expected, more):
    response, raw = native_page(ids, after, limit)
    assert tuple(r.cargo_id for r in response.cargoes) == expected and response.has_more is more
    q = CargoPageRequest("catalog", after, limit)
    parse_cargo_page_evidence(raw, q.request_id).require_complete(q, response)
    assert b"0x" not in raw and len(response.to_bytes()) <= 512


def test_native_four_byte_label_and_generic_properties():
    response, _ = native_page(
        (0, 63), setup='::labels[0]="\\x00\\x80\\x22\\xff"; ::class_masks[63]=32767;'
    )
    assert response.cargoes[0].cargo_label == "008022FF"
    assert response.cargoes[0].is_freight is False and response.cargoes[0].town_effect == 0
    assert (
        response.cargoes[1].is_freight is True
        and response.cargoes[1].town_effect == 3
        and response.cargoes[1].cargo_classes == 32767
    )


@pytest.mark.parametrize(
    "ids,setup",
    [
        ((64,), ""),
        ((1, 1), ""),
        ((1,), "::labels[1]=null;"),
        ((1,), '::labels[1]="abc";'),
        ((1,), "::effects[1]=6;"),
        ((1,), "::send_ok=false;"),
    ],
)
def test_native_invalid_metadata_and_failed_send(ids, setup):
    response, raw = native_page(ids, setup=setup)
    assert response is None and b"BRIDGE_POST_RESPONSE_ALIVE" not in raw


class CatalogWire:
    def __init__(self, ids=(0, 9, 63), failure=None, change=None):
        from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
        from app.simulation.openttd.gamescript_transport import (
            GameScriptSession,
            GameScriptTransport,
        )

        self.ids = ids
        self.requests = []
        self.reader = asyncio.StreamReader()
        self.writer = Mock(spec=asyncio.StreamWriter)
        self.writer.drain = AsyncMock()

        def send(frame):
            if frame[2] == 7:
                self.reader.feed_data(encode_admin_frame(126, frame[3:]))
                return
            if frame[2] != 6:
                return
            q = CargoPageRequest.parse(frame[3:-1])
            self.requests.append(q)
            if failure == "timeout":
                return
            if failure == "disconnect":
                self.reader.feed_eof()
                return
            response, _ = native_page(ids, q.after_id, q.limit, q.request_id)
            obj = json.loads(response.to_bytes())
            if change:
                change(obj)
            body = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\0"
            self.reader.feed_data(encode_admin_frame(124, body))
            if failure == "duplicate":
                self.reader.feed_data(encode_admin_frame(124, body))

        self.writer.write.side_effect = send
        self.transport = GameScriptTransport(
            GameScriptSession(self.reader, self.writer), ServerProtocol(3, ((9, 64),))
        )

    async def evidence(self, q, exchange):
        _, raw = native_page(self.ids, q.after_id, q.limit, q.request_id)
        return parse_cargo_page_evidence(raw, q.request_id)


def test_transport_validated_page_and_receipt():
    async def scenario():
        wire = CatalogWire()
        q = CargoPageRequest("q")
        exchange = await wire.transport.cargo_page(q)
        exchange.validate()
        assert exchange.ordered_sequence == CARGO_PAGE_NETWORK_SEQUENCE
        assert exchange.protocol_operations == 7
        (await wire.evidence(q, exchange)).require_complete(q, exchange.response)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["timeout", "disconnect", "duplicate"])
def test_transport_failure_no_retry(failure):
    async def scenario():
        wire = CatalogWire(failure=failure)
        with pytest.raises(Exception):
            await wire.transport.cargo_page(CargoPageRequest("q"), timeout=0.02)
        with pytest.raises(Exception):
            await wire.transport.cargo_page(CargoPageRequest("new"))
        assert len(wire.requests) == 1

    asyncio.run(scenario())


async def catalog(ids=(0, 9, 63), page_size=2, session_id="catalog", budget=None):
    wire = CatalogWire(ids)
    kwargs = {} if budget is None else {"budget": budget}
    session = CargoCatalogSession(session_id, page_size=page_size, **kwargs)
    return await session.collect(wire.transport, wire.evidence), session, wire


def test_complete_catalog_semantic_digest_independent_of_pages():
    async def scenario():
        a, session, wire = await catalog()
        b, _, _ = await catalog(page_size=1, session_id="different")
        assert a.complete and a.page_count == 2 and b.page_count == 3
        assert a.records == b.records and a.catalog_digest == b.catalog_digest
        assert (a.first_cargo_id, a.last_cargo_id) == (0, 63)
        assert len(a.page_receipts) == 2 and a.total_response_bytes > 0
        assert session.evidence.events == (
            "CARGO_CATALOG_SESSION_STARTED",
            "CARGO_PAGE_VALIDATED",
            "CARGO_PAGE_VALIDATED",
            "FINAL_PAGE_VALIDATED",
            "CARGO_CATALOG_ASSEMBLED",
            "CARGO_CATALOG_SESSION_COMPLETED",
        )
        with pytest.raises(ValueError):
            await session.collect(wire.transport, wire.evidence)
        assert len(wire.requests) == 2

    asyncio.run(scenario())


def test_empty_complete_catalog():
    async def scenario():
        observation, _, _ = await catalog(())
        assert observation.complete and observation.records == () and observation.page_count == 1
        assert observation.first_cargo_id is None and observation.last_cargo_id is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "budget",
    [
        CargoCatalogBudget(max_pages=1),
        CargoCatalogBudget(max_records=2),
        CargoCatalogBudget(max_response_bytes=1),
        CargoCatalogBudget(max_operations=4),
    ],
)
def test_session_budgets_stop_without_retry(budget):
    async def scenario():
        wire = CatalogWire()
        session = CargoCatalogSession("catalog", budget=budget)
        with pytest.raises(ValueError):
            await session.collect(wire.transport, wire.evidence)
        assert not session.evidence.complete and session.evidence.failure
        assert len(wire.requests) <= 2
        with pytest.raises(ValueError):
            await session.collect(wire.transport, wire.evidence)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["timeout", "disconnect", "duplicate"])
def test_session_transport_failure_and_truthful_evidence(failure):
    async def scenario():
        wire = CatalogWire(failure=failure)
        session = CargoCatalogSession("catalog", timeout=0.02)
        with pytest.raises(Exception):
            await session.collect(wire.transport, wire.evidence)
        assert not session.evidence.complete and session.evidence.failure
        assert len(wire.requests) == 1

    asyncio.run(scenario())


def test_connection_replacement_and_missing_liveness_fail():
    async def scenario():
        for mode in ("connection", "liveness", "timeout"):
            wire = CatalogWire()
            session = CargoCatalogSession("catalog", timeout=0.02)

            async def evidence(q, exchange):
                if mode == "timeout":
                    await asyncio.sleep(1)
                native = await wire.evidence(q, exchange)
                if mode == "connection":
                    wire.transport.session = Mock()
                if mode == "liveness":
                    native = replace(native, ordered_sequence=native.ordered_sequence[:-1])
                return native

            with pytest.raises(Exception):
                await session.collect(wire.transport, evidence)
            assert (
                not session.evidence.complete
                and len(session.evidence.exchanges) == 1
                and len(wire.requests) == 1
            )

    asyncio.run(scenario())


def test_capability_catalog_join_preserves_observations():
    from test_industry_cargo import CargoWire, inventory_fixture

    from app.simulation.openttd.industry_capability import IndustryCapabilitySession

    async def scenario():
        inventory = await inventory_fixture()
        wire = CargoWire()
        capability = await IndustryCapabilitySession("cap", inventory).collect(
            wire.transport, wire.evidence
        )
        before = capability.to_bytes()
        inventory_digest = inventory.inventory_digest
        complete, _, _ = await catalog((0, 2, 8, 17, 63))
        validate_capability_catalog(capability, complete)
        incomplete, _, _ = await catalog((0, 2, 8, 63))
        with pytest.raises(ValueError, match="17"):
            validate_capability_catalog(capability, incomplete)
        assert capability.to_bytes() == before and inventory.inventory_digest == inventory_digest

    asyncio.run(scenario())


def test_frozen_class_mapping_and_exact_source_bindings():
    from app.simulation.openttd.cargo_page import CARGO_CLASS_NAMES

    root = Path("tests/reference")
    generator = (root / "industry_page_bindings_15_3/SquirrelExport.cmake").read_text()
    declarations = (root / "industry_cargo_15_3/script_cargo.hpp").read_text()
    source = (root / "cargo_catalog_15_3/script_cargo.cpp").read_text()
    assert 'string(REGEX REPLACE "^Script" "${APIUC}" API_CLS "${CLS}")' in generator
    assert (
        "class ScriptCargoList : public ScriptList"
        in (root / "industry_cargo_15_3/script_cargolist.hpp").read_text()
    )
    for method in ("IsValidCargo", "GetCargoLabel", "IsFreight", "GetTownEffect", "HasCargoClass"):
        assert method in declarations and "ScriptCargo::" + method in source
    assert tuple(CARGO_CLASS_NAMES) == (
        "PASSENGERS",
        "MAIL",
        "EXPRESS",
        "ARMOURED",
        "BULK",
        "PIECE_GOODS",
        "LIQUID",
        "REFRIGERATED",
        "HAZARDOUS",
        "COVERED",
        "OVERSIZED",
        "POWDERIZED",
        "NON_POURABLE",
        "POTABLE",
        "NON_POTABLE",
    )
    assert all("CC_" + name in declarations for name in CARGO_CLASS_NAMES)
    assert (
        "sq_pushstring(vm, res.value())"
        in (root / "cargo_catalog_15_3/squirrel_helper.hpp").read_text()
    )
    assert "std::string_view str" in (root / "cargo_catalog_15_3/squirrel.h").read_text()


def test_evidence_rejects_duplicate_reorder_debug_and_unterminated_markers():
    q = CargoPageRequest("catalog")
    response, raw = native_page()
    lines = raw.splitlines(keepends=True)
    # First line is bridge startup; remaining lines are the four formal events.
    for changed in (
        raw + lines[-1],
        b"".join((lines[0], lines[2], lines[1], *lines[3:])),
        raw.replace(b"after_id=null", b"after_id=(null : 0x123)"),
        raw.rstrip(b"\n"),
    ):
        with pytest.raises(ValueError):
            parse_cargo_page_evidence(changed, q.request_id).require_complete(q, response)


@pytest.mark.parametrize(
    "field,value",
    [
        ("has_more", 1),
        ("next_after_id", True),
        ("cargoes", {}),
        ("label", "0" * 9),
        ("freight", 0),
        ("classes", -1),
    ],
)
def test_wire_scalar_types_and_no_unknown_record_fields(field, value):
    body = json.loads(CargoPageResponse("q", (record(),), None, False).to_bytes())
    if field in ("label", "freight", "classes"):
        body["cargoes"][0][field] = value
    else:
        body[field] = value
    with pytest.raises(ValueError):
        CargoPageResponse.parse(json.dumps(body).encode())


def test_receipt_and_exchange_cannot_be_substituted():
    from app.simulation.openttd.cargo_page import CargoPageExchange

    q = CargoPageRequest("q")
    r = CargoPageResponse("q", (record(),), None, False)
    exchange = CargoPageExchange(
        q.to_bytes(),
        r.to_bytes(),
        CargoPageReceipt.correlate(q.to_bytes(), r.to_bytes()),
        CARGO_PAGE_NETWORK_SEQUENCE,
    )
    exchange.validate()
    for broken in (
        replace(exchange, retries=1),
        replace(exchange, matching_responses=2),
        replace(exchange, protocol_operations=True),
        replace(exchange, ordered_sequence=()),
        replace(exchange, receipt=replace(exchange.receipt, response_payload_sha256="0" * 64)),
    ):
        with pytest.raises(ValueError):
            broken.validate()


def test_catalog_rejects_repeated_cursor_and_observation_tampering():
    async def scenario():
        observation, _, _ = await catalog(page_size=1)
        from app.simulation.openttd.cargo_catalog import CargoCatalogObservation

        with pytest.raises(ValueError):
            CargoCatalogObservation("catalog", ())
        with pytest.raises(ValueError):
            replace(
                observation,
                pages=(observation.pages[0], observation.pages[0], observation.pages[-1]),
            )
        with pytest.raises(ValueError):
            replace(observation, pages=observation.pages[:-1])
        with pytest.raises(ValueError):
            replace(observation, pages=list(observation.pages))
        with pytest.raises(ValueError):
            replace(observation, budget=CargoCatalogBudget(max_records=2))

    asyncio.run(scenario())


def test_all_64_cargoes_and_exact_session_bounds():
    async def scenario():
        first, _, _ = await catalog(tuple(range(64)), page_size=4)
        exact, _, _ = await catalog(
            tuple(range(64)),
            page_size=4,
            budget=CargoCatalogBudget(
                max_pages=16,
                max_records=64,
                max_response_bytes=first.total_response_bytes,
                max_operations=first.protocol_operations,
            ),
        )
        assert len(exact.records) == 64 and exact.page_count == 16 and exact.last_cargo_id == 63
        assert first.catalog_digest == exact.catalog_digest
        for field, maximum in (
            ("max_pages", 64),
            ("max_records", 64),
            ("max_response_bytes", 32768),
            ("max_operations", 512),
        ):
            for value in (0, True, maximum + 1):
                with pytest.raises(ValueError):
                    CargoCatalogBudget(**{field: value})

    asyncio.run(scenario())


def test_capability_join_requires_complete_typed_catalog():
    from test_industry_cargo import CargoWire, inventory_fixture

    from app.simulation.openttd.industry_capability import IndustryCapabilitySession

    async def scenario():
        inventory = await inventory_fixture()
        wire = CargoWire()
        capability = await IndustryCapabilitySession("cap", inventory).collect(
            wire.transport, wire.evidence
        )
        with pytest.raises(ValueError):
            validate_capability_catalog(capability, Mock(complete=False))

    asyncio.run(scenario())


def test_no_planning_imports_no_dynamic_or_mutation_apis():
    import ast

    for path in Path("app/simulation/openttd").glob("cargo_*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.planning")
            elif isinstance(node, ast.Import):
                assert all(not name.name.startswith("app.planning") for name in node.names)
    source = Path("app/simulation/openttd/gamescript_bridge_package/main.nut").read_text()
    # Structural cargo handler remains free of production queries.
    source = source.split("function CargoPage(", 1)[1].split("function ", 1)[0]
    for forbidden in (
        "GetCargoIncome",
        "GetLastMonthProduction",
        "GetLastMonthTransported",
        "GSCargo.GetName",
        "GSCompanyMode",
        "GSRoad",
        "GSVehicle",
        "GSOrder",
        "RCON",
    ):
        assert forbidden not in source


def test_real_v4_enrichment_fixture_remains_valid():
    from app.simulation.openttd.industry_cargo import (
        IndustryCargoReceipt,
        IndustryCargoRequest,
        IndustryCargoResponse,
    )
    from app.simulation.openttd.industry_cargo_evidence import parse_industry_cargo_evidence
    from app.simulation.openttd.industry_page import (
        IndustryPageReceipt,
        IndustryPageRequest,
        IndustryPageResponse,
    )
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

    fixture = Path("tests/fixtures/industry_enrichment_v4_checkpoint")
    records = []
    capabilities = []
    for phase in ("page", "capability"):
        requests = [
            json.loads(s) for s in (fixture / (phase + "-requests.jsonl")).read_text().splitlines()
        ]
        responses = [
            json.loads(s) for s in (fixture / (phase + "-responses.jsonl")).read_text().splitlines()
        ]
        for query, result in zip(requests, responses, strict=True):
            if phase == "page":
                q = IndustryPageRequest.parse(json.dumps(query).encode())
                raw = result["raw_payload"].encode()
                r = IndustryPageResponse.parse(raw)
                IndustryPageReceipt.correlate(q.to_bytes(), raw)
                parse_industry_page_evidence(
                    (fixture / "stderr.log").read_bytes(), q.request_id
                ).require_complete(q, r)
                records.extend(r.industries)
            else:
                q = IndustryCargoRequest.parse(json.dumps(query).encode())
                raw = result["raw_payload"].encode()
                r = IndustryCargoResponse.parse(raw)
                IndustryCargoReceipt.correlate(q.to_bytes(), raw)
                parse_industry_cargo_evidence(
                    (fixture / "stderr.log").read_bytes(), q.request_id
                ).require_complete(q, r)
                capabilities.append(r.capability)
    from dataclasses import asdict

    def canonical(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    assert (
        canonical([asdict(r) for r in records])
        == "dce9b4d257af150776e679b09c74880b918163b86ae5e5f9f6e30e35d26c865a"
    )
    assert (
        canonical([asdict(r) for r in capabilities])
        == "b65dc04752fffcc3958dac6cb40aa5a8cd017a3f23fb2408d9122c6bfb8a94b3"
    )
    assert [r.id for r in records] == [r.industry_id for r in capabilities]


@pytest.mark.parametrize(
    "change",
    [
        {"request_id": "wrong"},
        {"type": "world_info_result"},
        {"cargoes": [{"id": 0, "label": "bad", "freight": True, "town_effect": 0, "classes": 1}]},
    ],
)
def test_transport_wrong_correlation_and_metadata_fail_closed(change):
    async def scenario():
        wire = CatalogWire(change=lambda obj: obj.update(change))
        with pytest.raises(ValueError):
            await wire.transport.cargo_page(CargoPageRequest("q"))
        with pytest.raises(ValueError):
            await wire.transport.cargo_page(CargoPageRequest("next"))
        assert len(wire.requests) == 1

    asyncio.run(scenario())


def test_partial_final_validation_preserves_receipt_without_completion():
    async def scenario():
        wire = CatalogWire()
        session = CargoCatalogSession("catalog")

        async def native(q, exchange):
            result = await wire.evidence(q, exchange)
            if not exchange.response.has_more:
                return replace(result, ordered_sequence=result.ordered_sequence[:-1])
            return result

        with pytest.raises(ValueError):
            await session.collect(wire.transport, native)
        assert (
            len(session.evidence.exchanges) == 2
            and not session.evidence.complete
            and session.evidence.catalog_digest is None
        )
        assert "CARGO_CATALOG_SESSION_COMPLETED" not in session.evidence.events

    asyncio.run(scenario())


def test_distinct_labels_and_all_town_effects():
    response, _ = native_page((0, 1, 63), limit=4)
    assert [r.cargo_label for r in response.cargoes] == ["50415353", "4D41494C", "4F494C5F"]

    async def scenario():
        observation, _, _ = await catalog(tuple(range(6)), page_size=2)
        assert {r.town_effect for r in observation.records} == set(range(6))
        assert {r.is_freight for r in observation.records} == {True, False}

    asyncio.run(scenario())


def test_reference_source_and_checkpoint_fixture_hashes():
    manifest = json.loads(Path("tests/reference/cargo_catalog_15_3/manifest.json").read_text())
    for name, entry in manifest["files"].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == entry["sha256"]
    manifest = json.loads(
        Path("tests/fixtures/industry_enrichment_v4_checkpoint/manifest.json").read_text()
    )
    for name, expected in manifest["sha256"].items():
        assert (
            hashlib.sha256(
                Path("tests/fixtures/industry_enrichment_v4_checkpoint", name).read_bytes()
            ).hexdigest()
            == expected
        )
