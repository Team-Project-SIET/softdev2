import pytest

from app.simulation.openttd.industry_page import IndustryPageRequest


def test_first_and_after_id_canonicalization():
    assert IndustryPageRequest("page-1", None, 1).to_bytes() == (
        b'{"after_id":null,"limit":1,"protocol":1,"request_id":"page-1","type":"industry_page"}'
    )
    request = IndustryPageRequest("page-2", 42, 5)
    assert request.to_bytes() == (
        b'{"after_id":42,"limit":5,"protocol":1,"request_id":"page-2","type":"industry_page"}'
    )
    assert IndustryPageRequest.parse(request.to_bytes()) == request


@pytest.mark.parametrize(
    "cursor,limit", [(None, 0), (None, 6), (-1, 1), (64000, 1), (True, 1), (1.0, 1), (None, True)]
)
def test_invalid_request(cursor, limit):
    with pytest.raises(ValueError):
        IndustryPageRequest("page", cursor, limit)


def squirrel_page(ids=(9, 2, 7, 0, 5, 3, 8), after=None, limit=5, invalid=()):
    import json
    from pathlib import Path

    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY
    from app.simulation.openttd.industry_page import IndustryPageResponse

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(Path("tests/fixtures/industry_page_api_15.nut").read_text())
    vm.execute(f"::industry_ids = {list(ids)}; ::invalid_ids = {list(invalid)};")
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    cursor = "null" if after is None else str(after)
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="industry_page",'
        f'request_id="page",after_id={cursor},limit={limit}' + "})); "
        "::bridge <- NoMutationBridge(); try { bridge.Start(); } "
        'catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
    )
    root = vm.get_roottable()
    assert len(root["replies"]) == 1
    table = root["replies"][0]
    obj = dict(
        protocol=1,
        type=str(table["type"]),
        request_id=str(table["request_id"]),
        status=str(table["status"]),
        has_more=bool(table["has_more"]),
        next_after_id=None if table["next_after_id"] is None else int(table["next_after_id"]),
        industries=[
            {k: int(row[k]) for k in ("id", "type", "tile", "x", "y")}
            for row in table["industries"]
        ],
    )
    raw = "".join("dbg: [script:4] [18] [I] " + str(m) + "\n" for m in root["markers"]).encode()
    return IndustryPageResponse.parse(json.dumps(obj).encode()), raw, int(root["location_reads"])


def test_actual_adapter_orders_and_reads_only_page_records():
    response, raw, reads = squirrel_page()
    assert [r.id for r in response.industries] == [0, 2, 3, 5, 7]
    assert [(r.type, r.tile, r.x, r.y) for r in response.industries][:2] == [
        (12, 64, 0, 1),
        (12, 66, 2, 1),
    ]
    assert response.has_more and response.next_after_id == 7
    assert reads == 5
    assert b"INDUSTRY_PAGE_READ" in raw


@pytest.mark.parametrize(
    "ids,after,limit,expected,more,cursor",
    [
        ((), None, 5, [], False, None),
        ((2,), None, 5, [2], False, None),
        ((5, 2), None, 5, [2, 5], False, None),
        ((5, 2), None, 2, [2, 5], False, None),
        ((5, 2, 7), None, 2, [2, 5], True, 5),
        ((5, 2, 7), 5, 2, [7], False, None),
        ((5, 2, 7), 7, 2, [], False, None),
        ((5, 2, 7), None, 1, [2], True, 2),
    ],
)
def test_page_semantics(ids, after, limit, expected, more, cursor):
    response, _, _ = squirrel_page(ids, after, limit)
    assert [r.id for r in response.industries] == expected
    assert (response.has_more, response.next_after_id) == (more, cursor)
    assert squirrel_page(ids, after, limit)[0] == response


def test_invalid_industry_skipped_and_stable_pages_have_no_gaps_or_overlap():
    first = squirrel_page(invalid=(3,))[0]
    second = squirrel_page(after=first.next_after_id, invalid=(3,))[0]
    assert [r.id for r in first.industries + second.industries] == [0, 2, 5, 7, 8, 9]


@pytest.mark.parametrize(
    "fields",
    [
        (-1, 1, 0, 0, 0),
        (64000, 1, 0, 0, 0),
        (0, 240, 0, 0, 0),
        (0, True, 0, 0, 0),
        (0, 1, -1, 0, 0),
        (0, 1, 4096, 0, 64),
        (0, 1, 64, 64, 0),
        (0, 1, 66, 1, 1),
    ],
)
def test_invalid_record_or_location(fields):
    from app.simulation.openttd.industry_page import IndustryRecord
    from app.simulation.openttd.world_info import WorldInfoResponse

    with pytest.raises(ValueError):
        IndustryRecord(*fields).validate_location(WorldInfoResponse("world", 64, 64))


def test_response_validation_and_payload_bound():
    import json

    from app.simulation.openttd.industry_page import IndustryPageResponse, IndustryRecord

    record = IndustryRecord(63999, 239, 4294967294, 65535, 65535)
    # Conservative bound permits repeating the largest record solely for size calculation.
    rows = [vars(record)] * 5
    obj = dict(
        protocol=1,
        type="industry_page_result",
        request_id="a" * 64,
        status="ok",
        industries=rows,
        next_after_id=63999,
        has_more=False,
    )
    assert len(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()) == 502
    rows.append(vars(record))
    assert len(json.dumps(obj, separators=(",", ":")).encode()) == 564
    for records, cursor, more in [
        ((record, record), None, False),
        ((), 1, True),
        ((record,), 1, True),
        ((record,), 63999, False),
    ]:
        with pytest.raises(ValueError):
            IndustryPageResponse("page", records, cursor, more)


def test_industry_transport_and_multi_page_assembly():
    import asyncio

    from app.simulation.openttd.industry_query import collect_industries
    from app.simulation.openttd.world_info import WorldInfoResponse

    async def scenario():
        transport, _ = fake_transport()
        return await collect_industries(
            transport, WorldInfoResponse("world", 64, 64), request_prefix="collect"
        )

    records = asyncio.run(scenario())
    assert [r.id for r in records] == [0, 2, 3, 5, 7, 8, 9]


def fake_transport(behavior="ok"):
    import asyncio
    import json
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
    from app.simulation.openttd.gamescript_transport import GameScriptSession, GameScriptTransport

    reader = asyncio.StreamReader()
    writer = Mock(spec=asyncio.StreamWriter)
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    sent = []

    def write(frame):
        if frame[2] == 7:
            reader.feed_data(encode_admin_frame(126, frame[3:]))
        elif frame[2] == 6:
            query = IndustryPageRequest.parse(frame[3:-1])
            sent.append(query)
            result = squirrel_page(after=query.after_id, limit=query.limit)[0]
            obj = json.loads(result.to_bytes())
            obj["request_id"] = query.request_id
            if behavior == "wrong_id":
                obj["request_id"] = "wrong"
            if behavior == "wrong_type":
                obj["type"] = "world_info_result"
            if behavior == "timeout":
                return
            if behavior == "disconnect":
                reader.feed_eof()
                return
            if behavior == "empty_more":
                obj["industries"] = []
                obj["has_more"] = True
            if query.after_id is not None and behavior in (
                "regression",
                "repeat",
                "duplicate_id",
                "unsorted",
            ):
                obj["industries"][0]["id"] = query.after_id
                if behavior == "regression":
                    obj["next_after_id"] = query.after_id - 1
                    obj["has_more"] = True
                elif behavior == "repeat":
                    obj["next_after_id"] = query.after_id
                    obj["has_more"] = True
                elif behavior == "unsorted":
                    obj["industries"].reverse()
            response = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
            reader.feed_data(encode_admin_frame(107, b"\x01\0\0\0"))
            reader.feed_data(encode_admin_frame(124, response + b"\0"))
            if behavior == "duplicate":
                reader.feed_data(encode_admin_frame(124, response + b"\0"))

    writer.write.side_effect = write
    return GameScriptTransport(
        GameScriptSession(reader, writer), ServerProtocol(3, ((9, 64),))
    ), sent


@pytest.mark.parametrize(
    "behavior,exception",
    [
        ("wrong_id", "TransportProtocolError"),
        ("wrong_type", "TransportProtocolError"),
        ("duplicate", "TransportProtocolError"),
        ("timeout", "TransportTimeout"),
        ("disconnect", "TransportDisconnected"),
    ],
)
def test_transport_failure_distinctions(behavior, exception):
    import asyncio

    import app.simulation.openttd.gamescript_transport as module
    from app.simulation.openttd.world_info import WorldInfoResponse

    async def scenario():
        transport, sent = fake_transport(behavior)
        with pytest.raises(getattr(module, exception)):
            await transport.industry_page(
                IndustryPageRequest("page"), WorldInfoResponse("world", 64, 64), timeout=0.01
            )
        assert len(sent) == 1

    asyncio.run(scenario())


def test_each_page_has_correlated_independent_partial_order_evidence():
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

    response, raw, _ = squirrel_page()
    evidence = parse_industry_page_evidence(raw, "page")
    evidence.require_complete(IndustryPageRequest("page"), response)
    for marker in (b"INDUSTRY_PAGE_READ", b"BRIDGE_RESPONSE_SENT", b"BRIDGE_POST_RESPONSE_ALIVE"):
        incomplete = b"".join(line for line in raw.splitlines(keepends=True) if marker not in line)
        with pytest.raises(ValueError):
            parse_industry_page_evidence(incomplete, "page").require_complete(
                IndustryPageRequest("page"), response
            )
    lines = raw.splitlines(keepends=True)
    with pytest.raises(ValueError):
        parse_industry_page_evidence(b"".join(lines[:2] + [lines[3], lines[2]] + lines[4:]), "page")


@pytest.mark.parametrize(
    "behavior", ["regression", "repeat", "duplicate_id", "unsorted", "empty_more"]
)
def test_pagination_rejects_bad_progress_and_cross_page_ids(behavior):
    import asyncio

    from app.simulation.openttd.industry_query import collect_industries
    from app.simulation.openttd.world_info import WorldInfoResponse

    async def scenario():
        transport, sent = fake_transport(behavior)
        with pytest.raises(ValueError):
            await collect_industries(
                transport, WorldInfoResponse("world", 64, 64), request_prefix="bad"
            )
        assert len(sent) <= 2

    asyncio.run(scenario())


def test_pagination_budget_never_returns_partial_success():
    import asyncio

    from app.simulation.openttd.industry_query import collect_industries
    from app.simulation.openttd.world_info import WorldInfoResponse

    async def scenario():
        transport, sent = fake_transport()
        with pytest.raises(ValueError, match="budget exhausted"):
            await collect_industries(
                transport, WorldInfoResponse("world", 64, 64), request_prefix="budget", max_pages=1
            )
        assert len(sent) == 1

    asyncio.run(scenario())


def test_network_exchange_and_fresh_request_id_required():
    import asyncio

    from app.simulation.openttd.industry_page import PAGE_NETWORK_SEQUENCE
    from app.simulation.openttd.world_info import WorldInfoResponse

    async def scenario():
        transport, sent = fake_transport()
        request = IndustryPageRequest("page")
        exchange = await transport.industry_page(request, WorldInfoResponse("world", 64, 64))
        assert exchange.ordered_sequence == PAGE_NETWORK_SEQUENCE
        assert exchange.receipt.request_id == request.request_id
        assert exchange.retries == 0
        with pytest.raises(ValueError):
            await transport.industry_page(request, WorldInfoResponse("world", 64, 64))
        assert len(sent) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"industries": "bad"},
        {"has_more": 1},
        {"status": "failed"},
        {"protocol": True},
        {"type": "ack"},
        {"next_after_id": -1},
        {"extra": 1},
        {"industries": [{"id": 1, "type": 12, "tile": 65, "x": 1}]},
        {"industries": [{"id": 1, "type": 12, "tile": 65, "x": True, "y": 1}]},
    ],
)
def test_malformed_response_schema(change):
    import json

    from app.simulation.openttd.industry_page import IndustryPageResponse

    obj = json.loads(squirrel_page(ids=(1,))[0].to_bytes())
    obj.update(change)
    with pytest.raises(ValueError):
        IndustryPageResponse.parse(json.dumps(obj).encode())


def test_evidence_metadata_and_multi_transaction_correlation():
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

    first, raw1, _ = squirrel_page()
    second, raw2, _ = squirrel_page(after=7)
    raw2 = raw2.replace(b"request_id=page", b"request_id=second")
    from dataclasses import replace

    second = replace(second, request_id="second")
    combined = raw1 + raw2
    parse_industry_page_evidence(combined, "page").require_complete(
        IndustryPageRequest("page"), first
    )
    parse_industry_page_evidence(combined, "second").require_complete(
        IndustryPageRequest("second", 7), second
    )
    for old, new in [
        (b"limit=5", b"limit=4"),
        (b"returned_count=5", b"returned_count=4"),
        (b"next_after_id=7", b"next_after_id=6"),
        (b"has_more=true", b"has_more=false"),
    ]:
        with pytest.raises(ValueError):
            parse_industry_page_evidence(raw1.replace(old, new), "page").require_complete(
                IndustryPageRequest("page"), first
            )
    with pytest.raises(ValueError):
        parse_industry_page_evidence(raw1 + raw1, "page")


def test_dtos_are_immutable_and_separate_from_planning():
    from dataclasses import FrozenInstanceError
    from pathlib import Path

    from app.simulation.openttd.industry_page import IndustryRecord

    record = IndustryRecord(1, 12, 65, 1, 1)
    with pytest.raises(FrozenInstanceError):
        setattr(record, "id", 2)
    for filename in ("industry_page.py", "industry_query.py", "industry_page_evidence.py"):
        source = (Path("app/simulation/openttd") / filename).read_text()
        assert "app.planning" not in source
        assert "PreparedWorldManifest" not in source


@pytest.mark.parametrize(
    "squirrel_request",
    [
        '{protocol=1,type="industry_page",request_id="page",after_id=null,limit=0}',
        '{protocol=1,type="industry_page",request_id="page",after_id=null,limit=6}',
        '{protocol=1,type="industry_page",request_id="page",after_id=-1,limit=1}',
        '{protocol=1,type="industry_page",request_id="page",after_id=true,limit=1}',
        '{protocol=1,type="industry_page",request_id="page",after_id=64000,limit=1}',
    ],
)
def test_actual_adapter_rejects_bad_requests_without_read_or_send(squirrel_request):
    from pathlib import Path

    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(Path("tests/fixtures/industry_page_api_15.nut").read_text())
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute("NoMutationBridge().Handle(" + squirrel_request + ");")
    root = vm.get_roottable()
    assert len(root["replies"]) == root["location_reads"] == root["type_reads"] == 0


def test_exact_15_3_source_provenance_and_read_only_api_boundary():
    import hashlib
    import json
    import re
    from pathlib import Path

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    manifest = json.loads(
        Path("tests/reference/industry_page_bindings_15_3/manifest.json").read_text()
    )
    assert manifest["version"] == "15.3"
    for path, identity in manifest["files"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == identity["sha256"]
        assert "/OpenTTD/OpenTTD/15.3/" in identity["url"]
    generator = Path("tests/reference/industry_page_bindings_15_3/SquirrelExport.cmake").read_text()
    assert 'string(REGEX REPLACE "^Script" "${APIUC}" API_CLS' in generator
    source = (BRIDGE_DIRECTORY / "main.nut").read_text()
    assert set(re.findall(r"GSIndustry\.([A-Za-z]+)\(", source)) == {
        "IsValidIndustry",
        "GetLocation",
        "GetIndustryType",
    }
    assert "source.Sort(GSList.SORT_BY_ITEM, GSList.SORT_ASCENDING)" in source
    for filename in ("industry_page.py", "industry_query.py", "industry_page_evidence.py"):
        assert "app.planning" not in (Path("app/simulation/openttd") / filename).read_text()


@pytest.mark.parametrize(
    "api",
    ["GSIndustry.BuildIndustry", "GSIndustry.SetControlFlags", "GSIndustryType.BuildIndustry"],
)
def test_shared_prelaunch_guard_rejects_industry_mutation_apis(tmp_path, monkeypatch, api):
    from test_real_ack_harness import make_prepared

    from app.simulation.openttd.proof import harness

    original = harness.stage_bridge

    def stage_with_forbidden_api(workspace):
        package = original(workspace)
        main = package.directory / "main.nut"
        main.write_text(main.read_text() + "\n" + api + "(0);\n")
        return package

    monkeypatch.setattr(harness, "stage_bridge", stage_with_forbidden_api)
    with pytest.raises(ValueError, match="API/mutation surface"):
        make_prepared(tmp_path)


def test_actual_squirrel_worst_case_page_and_send_failure_liveness():
    import json
    from pathlib import Path

    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY
    from app.simulation.openttd.industry_page import IndustryPageResponse

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    fake_source = Path("tests/fixtures/industry_page_api_15.nut").read_text()
    fake_source = (
        fake_source.replace("return 64 + id;", "return 1073741823;")
        .replace("return 12;", "return 239;")
        .replace("return 64;", "return 32768;")
        .replace("tile < 4096", "tile < 1073741824")
        .replace("tile % 64", "tile % 32768")
        .replace("tile / 64", "tile / 32768")
    )
    vm.execute(fake_source)
    vm.execute("::industry_ids = [63999,63995,63994,63997,63996,63998];")
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        'NoMutationBridge().Handle({protocol=1,type="industry_page",request_id="'
        + "a" * 64
        + '",after_id=null,limit=5});'
    )
    table = vm.get_roottable()["replies"][0]
    obj = dict(
        protocol=1,
        type=str(table["type"]),
        request_id=str(table["request_id"]),
        status=str(table["status"]),
        has_more=bool(table["has_more"]),
        next_after_id=int(table["next_after_id"]),
        industries=[
            {k: int(row[k]) for k in ("id", "type", "tile", "x", "y")}
            for row in table["industries"]
        ],
    )
    response = IndustryPageResponse.parse(json.dumps(obj, separators=(",", ":")).encode())
    assert len(response.to_bytes()) == 501 <= 502 <= 512 < 1450
    assert [row.id for row in response.industries] == [63994, 63995, 63996, 63997, 63998]
    vm.execute(
        '::send_ok=false; ::events.append(ControlledAdminEvent({protocol=1,type="industry_page",'
        'request_id="failed-send",after_id=null,limit=1})); '
        'try { NoMutationBridge().Start(); } catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
    )
    markers = [str(m) for m in vm.get_roottable()["markers"] if "failed-send" in str(m)]
    assert len(markers) == 2
    assert "BRIDGE_REQUEST_RECEIVED" in markers[0] and "INDUSTRY_PAGE_READ" in markers[1]


def test_incomplete_intermediate_page_and_id_below_cursor_rejected():
    from app.simulation.openttd.industry_page import IndustryPageResponse, IndustryRecord
    from app.simulation.openttd.world_info import WorldInfoResponse

    world = WorldInfoResponse("world", 64, 64)
    record = IndustryRecord(2, 12, 66, 2, 1)
    with pytest.raises(ValueError, match="incomplete intermediate"):
        IndustryPageResponse("page", (record,), 2, True).validate_page(
            IndustryPageRequest("page", None, 5), world
        )
    with pytest.raises(ValueError, match="advance cursor"):
        IndustryPageResponse("page", (record,), None, False).validate_page(
            IndustryPageRequest("page", 3), world
        )
