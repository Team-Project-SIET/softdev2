import asyncio
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.simulation.openttd.admin_protocol import ServerWelcome
from app.simulation.openttd.runtime.identity import RuntimeIdentity


def test_two_page_inventory_is_complete_and_retains_receipt():
    from test_industry_page import fake_transport, squirrel_page

    from app.simulation.openttd.industry_inventory import IndustryInventoryWorld
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        world = IndustryInventoryWorld.from_welcome(
            "stable-world",
            RuntimeIdentity(Path("fake-openttd"), "15.3", "a" * 64),
            ServerWelcome("Test", "15.3", True, "", 42, 0, 712223, 64, 64),
        )
        transport, sent = fake_transport()

        async def evidence(request, exchange):
            _, raw, _ = squirrel_page(after=request.after_id, limit=request.limit)
            raw = raw.replace(b"request_id=page", ("request_id=" + request.request_id).encode())
            return parse_industry_page_evidence(raw, request.request_id)

        session = IndustryInventorySession("inventory-001", world, page_size=5)
        result = await session.collect(transport, evidence)
        assert result.complete and result.page_count == 2
        assert [r.id for r in result.records] == [0, 2, 3, 5, 7, 8, 9]
        assert sent[0].request_id == "inventory-001-p001"
        assert sent[1].after_id == 7
        assert len(result.page_receipts) == 2
        assert session.evidence.events[-1] == "INVENTORY_SESSION_COMPLETED"

    asyncio.run(scenario())


def world_context():
    from app.simulation.openttd.industry_inventory import IndustryInventoryWorld

    return IndustryInventoryWorld.from_welcome(
        "stable-world",
        RuntimeIdentity(Path("controlled-runtime"), "15.3", "a" * 64),
        ServerWelcome("Test", "15.3", True, "", 42, 0, 712223, 64, 64),
    )


class InventoryWire:
    """Fake Admin stream; production frame decoder/query/receipt validation are real."""

    def __init__(
        self, ids=(0, 1, 2, 5, 8, 13, 21), *, change=None, fail_page=None, failure=None, unrelated=0
    ):
        from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
        from app.simulation.openttd.gamescript_transport import (
            GameScriptSession,
            GameScriptTransport,
        )
        from app.simulation.openttd.industry_page import IndustryPageRequest

        self.requests = []
        self.ids, self.change = tuple(sorted(ids)), change
        self.responses = []
        self.reader = asyncio.StreamReader()
        self.writer = Mock(spec=asyncio.StreamWriter)
        self.writer.drain = AsyncMock()
        self.writer.wait_closed = AsyncMock()

        def write(frame):
            if frame[2] == 7:
                self.reader.feed_data(encode_admin_frame(126, frame[3:]))
                return
            if frame[2] != 6:
                return
            request = IndustryPageRequest.parse(frame[3:-1])
            self.requests.append(request)
            if len(self.requests) == fail_page:
                if failure == "disconnect":
                    self.reader.feed_eof()
                return
            candidates = [i for i in self.ids if request.after_id is None or i > request.after_id]
            selected = candidates[: request.limit]
            more = len(candidates) > len(selected)
            obj = dict(
                protocol=1,
                type="industry_page_result",
                status="ok",
                request_id=request.request_id,
                has_more=more,
                next_after_id=selected[-1] if more else None,
                industries=[
                    dict(id=i, type=12, tile=64 + i, x=i % 64, y=(64 + i) // 64) for i in selected
                ],
            )
            if self.change is not None:
                self.change(obj, len(self.requests))
            raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
            self.responses.append(raw)
            for _ in range(unrelated):
                self.reader.feed_data(encode_admin_frame(107, b"\x01\0\0\0"))
            self.reader.feed_data(encode_admin_frame(124, raw + b"\0"))
            if failure == "duplicate":
                self.reader.feed_data(encode_admin_frame(124, raw + b"\0"))

        self.writer.write.side_effect = write
        self.transport = GameScriptTransport(
            GameScriptSession(self.reader, self.writer), ServerProtocol(3, ((9, 64),))
        )

    async def evidence(self, request, exchange):
        from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

        result = exchange.response

        def token(value):
            return "null" if value is None else str(value)

        ids = [r.id for r in result.industries]
        marker = (
            f"INDUSTRY_PAGE_READ request_id={request.request_id} "
            f"after_id={token(request.after_id)} limit={request.limit} returned_count={len(ids)} "
            f"first_id={token(ids[0] if ids else None)} last_id={token(ids[-1] if ids else None)} "
            f"next_after_id={token(result.next_after_id)} has_more={str(result.has_more).lower()}"
        )
        lines = [
            f"BRIDGE_REQUEST_RECEIVED request_id={request.request_id} "
            "type=industry_page protocol=1",
            marker,
            f"BRIDGE_RESPONSE_SENT request_id={request.request_id} "
            "type=industry_page_result status=ok protocol=1",
            f"BRIDGE_POST_RESPONSE_ALIVE request_id={request.request_id}",
        ]
        raw = "".join("dbg: [script:4] [18] [I] " + line + "\n" for line in lines).encode()
        return parse_industry_page_evidence(raw, request.request_id)


@pytest.mark.parametrize(
    "ids,pages",
    [
        ((), 1),
        ((17,), 1),
        ((0, 1, 2), 1),
        ((0, 1, 2, 5), 2),
        ((0, 1, 2, 5, 8, 13), 2),
        ((0, 1, 2, 5, 8, 13, 21), 3),
        (tuple(range(32)), 11),
    ],
)
def test_complete_stable_worlds_and_cursor_chain(ids, pages):
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        wire = InventoryWire(ids)
        session = IndustryInventorySession("inventory-001", world_context())
        result = await session.collect(wire.transport, wire.evidence)
        assert result.complete and result.page_count == pages
        assert tuple(r.id for r in result.records) == ids
        assert result.first_industry_id == (ids[0] if ids else None)
        assert result.last_industry_id == (ids[-1] if ids else None)
        assert [r.request_id for r in wire.requests] == [
            f"inventory-001-p{i:03}" for i in range(1, pages + 1)
        ]
        assert wire.requests[0].after_id is None
        assert session.evidence.requested_cursors == tuple(r.after_id for r in wire.requests)
        assert session.evidence.final_has_more is False
        assert session.evidence.next_cursors[-1] is None
        assert session.evidence.total_records == len(ids)
        assert result.total_response_bytes == sum(map(len, wire.responses))
        assert result.world.map_width == result.world.map_height == 64
        assert result.world.runtime_identity == world_context().runtime_identity
        assert len(result.page_receipts) == pages
        for page in result.pages:
            page.validate(world_context().dimensions)
        with pytest.raises(FrozenInstanceError):
            setattr(result, "session_id", "changed")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind,value,message",
    [
        ("max_pages", 1, "page budget"),
        ("max_records", 3, "record budget"),
        ("max_response_bytes", 1, "byte budget"),
        ("max_operations", 8, "operation budget"),
    ],
)
def test_each_session_budget_fails_without_partial_success(kind, value, message):
    from app.simulation.openttd.industry_inventory import IndustryInventoryBudget
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        wire = InventoryWire()
        session = IndustryInventorySession(
            "budget", world_context(), budget=IndustryInventoryBudget(**{kind: value})
        )
        with pytest.raises(ValueError, match=message):
            await session.collect(wire.transport, wire.evidence)
        assert session.evidence.inventory_digest is None
        assert session.evidence.events[-1] == "INVENTORY_SESSION_FAILED"
        assert len(wire.requests) <= 2

    asyncio.run(scenario())


def test_exact_measured_budgets_accepted_and_one_byte_less_rejected():
    from app.simulation.openttd.industry_inventory import IndustryInventoryBudget
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        first = InventoryWire((0, 1, 2, 5))
        observation = await IndustryInventorySession("exact", world_context()).collect(
            first.transport, first.evidence
        )
        budget = IndustryInventoryBudget(
            max_pages=2,
            max_records=4,
            max_response_bytes=observation.total_response_bytes,
            max_operations=11,
        )
        second = InventoryWire((0, 1, 2, 5))
        result = await IndustryInventorySession("exact", world_context(), budget=budget).collect(
            second.transport, second.evidence
        )
        assert result.complete and result.protocol_operations == 11
        third = InventoryWire((0, 1, 2, 5))
        with pytest.raises(ValueError, match="byte budget"):
            await IndustryInventorySession(
                "exact",
                world_context(),
                budget=replace(budget, max_response_bytes=budget.max_response_bytes - 1),
            ).collect(third.transport, third.evidence)

    asyncio.run(scenario())


def test_record_and_page_hard_boundary_32_accepted_33_rejected():
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        wire = InventoryWire(tuple(range(32)))
        result = await IndustryInventorySession("boundary", world_context(), page_size=1).collect(
            wire.transport, wire.evidence
        )
        assert result.page_count == len(result.records) == 32
        over = InventoryWire(tuple(range(33)))
        with pytest.raises(ValueError, match="record budget"):
            await IndustryInventorySession("boundary", world_context()).collect(
                over.transport, over.evidence
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_pages", 33),
        ("max_records", 33),
        ("max_response_bytes", 16385),
        ("max_operations", 257),
        ("max_pages", 0),
        ("max_records", True),
        ("max_operations", 1.5),
    ],
)
def test_budget_configuration_cannot_bypass_hard_caps(field, value):
    from app.simulation.openttd.industry_inventory import IndustryInventoryBudget

    with pytest.raises(ValueError, match="session budget"):
        IndustryInventoryBudget(**{field: value})


@pytest.mark.parametrize(
    "failure,exception",
    [
        ("timeout", "TransportTimeout"),
        ("disconnect", "TransportDisconnected"),
        ("duplicate", "TransportProtocolError"),
    ],
)
def test_transport_failure_stops_session_without_reconnect_or_retry(
    failure, exception, monkeypatch
):
    import app.simulation.openttd.gamescript_transport as module
    from app.simulation.openttd.industry_query import IndustryInventorySession
    from app.simulation.openttd.secure_admin import SecureAdminSession

    monkeypatch.setattr(
        SecureAdminSession, "connect_secure", lambda *a, **kw: pytest.fail("No reconnect")
    )

    async def scenario():
        wire = InventoryWire(failure=failure, fail_page=2 if failure != "duplicate" else None)
        session = IndustryInventorySession("failure", world_context(), timeout=0.02)
        with pytest.raises(getattr(module, exception)):
            await session.collect(wire.transport, wire.evidence)
        count = len(wire.requests)
        assert count == (1 if failure == "duplicate" else 2)
        assert session.evidence.events[-1] == "INVENTORY_SESSION_FAILED"
        with pytest.raises(ValueError, match="single-use"):
            await session.collect(wire.transport, wire.evidence)
        assert len(wire.requests) == count

    asyncio.run(scenario())


def test_operations_include_unrelated_frames_and_stop_flood():
    from app.simulation.openttd.industry_inventory import IndustryInventoryBudget
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        wire = InventoryWire((0,), unrelated=1)
        result = await IndustryInventorySession("operations", world_context()).collect(
            wire.transport, wire.evidence
        )
        assert (
            result.protocol_operations == 8
        )  # subscription(3), query(2), unrelated(1), barrier(2)
        flood = InventoryWire((0,), unrelated=100)
        session = IndustryInventorySession(
            "operations", world_context(), budget=IndustryInventoryBudget(max_operations=8)
        )
        with pytest.raises(ValueError, match="operation budget"):
            await session.collect(flood.transport, flood.evidence)
        assert len(flood.requests) == 1
        assert session.evidence.inventory_digest is None

    asyncio.run(scenario())


def test_digest_is_canonical_and_independent_of_session_identity():
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        results = []
        for name in ("one", "two"):
            wire = InventoryWire((0, 17))
            results.append(
                await IndustryInventorySession(name, world_context()).collect(
                    wire.transport, wire.evidence
                )
            )
        gold = (
            b'[{"id":0,"tile":64,"type":12,"x":0,"y":1},{"id":17,"tile":81,"type":12,"x":17,"y":1}]'
        )
        assert results[0].to_bytes() == results[1].to_bytes() == gold
        assert (
            results[0].inventory_digest
            == results[1].inventory_digest
            == hashlib.sha256(gold).hexdigest()
        )

    asyncio.run(scenario())


def test_session_evidence_retains_ordered_transactions_and_completion():
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        wire = InventoryWire()
        session = IndustryInventorySession("ordered", world_context())
        result = await session.collect(wire.transport, wire.evidence)
        evidence = session.evidence
        assert evidence.events == (
            "INVENTORY_SESSION_STARTED",
            "PAGE_1_VALIDATED",
            "PAGE_2_VALIDATED",
            "FINAL_PAGE_VALIDATED",
            "INVENTORY_ASSEMBLED",
            "INVENTORY_SESSION_COMPLETED",
        )
        assert evidence.requested_cursors == (None, 2, 13)
        assert evidence.next_cursors == (2, 13, None)
        assert evidence.request_digests == tuple(
            p.exchange.receipt.request_payload_sha256 for p in result.pages
        )
        assert evidence.response_digests == tuple(
            hashlib.sha256(b).hexdigest() for b in wire.responses
        )
        assert evidence.inventory_digest == result.inventory_digest
        with pytest.raises(ValueError):
            replace(result, pages=result.pages[:-1])
        with pytest.raises(ValueError):
            replace(result, pages=())
        with pytest.raises(ValueError):
            replace(result, pages=result.pages + result.pages[-1:])

    asyncio.run(scenario())


def test_missing_gamescript_liveness_keeps_receipt_but_cannot_complete():
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        wire = InventoryWire((0,))
        session = IndustryInventorySession("liveness", world_context())

        async def missing(request, exchange):
            e = await wire.evidence(request, exchange)
            raw = b"".join(
                s
                for s in e.raw_log.splitlines(keepends=True)
                if b"BRIDGE_POST_RESPONSE_ALIVE" not in s
            )
            return parse_industry_page_evidence(raw, request.request_id)

        with pytest.raises(ValueError, match="lifecycle"):
            await session.collect(wire.transport, missing)
        assert len(session.page_exchanges) == 1
        assert session.evidence.inventory_digest is None

    asyncio.run(scenario())


def test_native_squirrel_two_requests_share_one_live_loop_and_source():
    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY
    from app.simulation.openttd.industry_page import IndustryPageRequest, IndustryPageResponse
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

    vm = SQVM()
    api = (
        Path("tests/fixtures/gamescript_api_15.nut")
        .read_text()
        .replace(
            'if (::ticks == 2) throw "CONTROLLED_STOP";',
            """if (::ticks == 2) {
            if (::replies.len() != 1) throw "missing first reply";
            ::events.append(ControlledAdminEvent({protocol=1,type="industry_page",
                request_id="sequence-p002",after_id=::replies[0].next_after_id,limit=3}));
        }
        if (::ticks == 4) throw "CONTROLLED_STOP";""",
        )
    )
    vm.execute(api)
    vm.execute(Path("tests/fixtures/industry_page_api_15.nut").read_text())
    vm.execute("::industry_ids = [13,5,2,8,1,0];")
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute("""::events.append(ControlledAdminEvent({protocol=1,type="industry_page",
        request_id="sequence-p001",after_id=null,limit=3}));
        ::bridge <- NoMutationBridge(); try { bridge.Start(); }
        catch(e) { if(e != "CONTROLLED_STOP") throw e; }""")
    root = vm.get_roottable()
    assert len(root["replies"]) == 2
    raw = "".join("dbg: [script:4] [18] [I] " + str(m) + "\n" for m in root["markers"]).encode()
    for number, after, ids in [(1, None, [0, 1, 2]), (2, 2, [5, 8, 13])]:
        table = root["replies"][number - 1]
        obj = dict(
            protocol=1,
            type="industry_page_result",
            status="ok",
            request_id=str(table["request_id"]),
            has_more=bool(table["has_more"]),
            next_after_id=None if table["next_after_id"] is None else int(table["next_after_id"]),
            industries=[
                {k: int(row[k]) for k in ("id", "type", "tile", "x", "y")}
                for row in table["industries"]
            ],
        )
        response = IndustryPageResponse.parse(json.dumps(obj).encode())
        request = IndustryPageRequest(f"sequence-p{number:03}", after, 3)
        evidence = parse_industry_page_evidence(raw, request.request_id)
        evidence.require_complete(request, response)
        assert [r.id for r in response.industries] == ids
        assert b"0x" not in evidence.suffixes[1].encode()
    assert raw.count(b"BRIDGE_STARTED") == 1
    assert raw.index(b"BRIDGE_POST_RESPONSE_ALIVE request_id=sequence-p001") < raw.index(
        b"BRIDGE_REQUEST_RECEIVED request_id=sequence-p002"
    )
    assert int(root["location_reads"]) == int(root["type_reads"]) == 6


def test_real_page_fixtures_keep_attempt_two_valid_and_attempt_one_failed():
    from app.simulation.openttd.proof.industry_contract import INDUSTRY_REQUEST
    from app.simulation.openttd.proof.industry_evidence import parse_industry_proof_evidence

    for number in (1, 2):
        raw = Path(f"tests/fixtures/industry_page_attempt{number}.log").read_bytes()
        response = Path(f"tests/fixtures/industry_page_attempt{number}_response.json").read_bytes()
        evidence = parse_industry_proof_evidence(raw, INDUSTRY_REQUEST.request_id)
        if number == 1:
            with pytest.raises(ValueError, match="metadata mismatch"):
                evidence.correlate(INDUSTRY_REQUEST, response)
        else:
            assert (
                evidence.correlate(INDUSTRY_REQUEST, response).response_digest
                == hashlib.sha256(response).hexdigest()
            )


@pytest.mark.parametrize("ids", [(), (0,), (0, 1, 2, 5)])
def test_connection_replacement_mid_session_is_not_resumed(ids):
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        wire = InventoryWire(ids=ids)
        original = wire.transport.session

        async def swapped(request, exchange):
            result = await wire.evidence(request, exchange)
            wire.transport.session = Mock()
            return result

        with pytest.raises(ValueError, match="connection changed"):
            await IndustryInventorySession("continuous", world_context()).collect(
                wire.transport, swapped
            )
        assert len(wire.requests) == 1
        wire.transport.session = original

    asyncio.run(scenario())


def test_gamescript_evidence_deadline_fails_without_resend():
    from app.simulation.openttd.gamescript_transport import TransportTimeout
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def scenario():
        wire = InventoryWire((0,))

        async def hanging(request, exchange):
            await asyncio.Event().wait()

        session = IndustryInventorySession("deadline", world_context(), timeout=0.01)
        with pytest.raises(TransportTimeout, match="evidence deadline"):
            await session.collect(wire.transport, hanging)
        assert len(wire.requests) == len(session.page_exchanges) == 1
        assert session.evidence.inventory_digest is None

    asyncio.run(scenario())


@pytest.mark.parametrize("session_id", ["a" * 60, "contains space", "-bad", ""])
def test_all_request_ids_are_validated_before_sending(session_id):
    from app.simulation.openttd.industry_query import IndustryInventorySession

    with pytest.raises(ValueError):
        IndustryInventorySession(session_id, world_context())


def test_query_and_inventory_modules_keep_planning_import_boundary():
    import ast

    for name in (
        "industry_inventory.py",
        "industry_query.py",
        "industry_page.py",
        "gamescript_transport.py",
    ):
        tree = ast.parse((Path("app/simulation/openttd") / name).read_text())
        for node in ast.walk(tree):
            imports = (
                [i.name for i in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(i.startswith("app.planning") for i in imports)


@pytest.mark.parametrize(
    "case",
    [
        "repeat_cursor",
        "regress_cursor",
        "empty_more",
        "null_more",
        "no_progress",
        "duplicate_page",
        "duplicate_across",
        "global_regression",
        "unsorted",
        "wrong_id",
        "wrong_type",
        "protocol",
        "status",
        "final_cursor",
        "x_bounds",
        "y_bounds",
        "tile",
        "oversized_payload",
    ],
)
def test_invalid_pages_fail_entire_session(case):
    from app.simulation.openttd.industry_query import IndustryInventorySession

    def change(obj, number):
        if (
            case
            in (
                "repeat_cursor",
                "regress_cursor",
                "duplicate_across",
                "global_regression",
                "no_progress",
            )
            and number != 2
        ):
            return
        if case == "repeat_cursor":
            obj["next_after_id"] = 2
        elif case == "regress_cursor":
            obj["next_after_id"] = 1
        elif case == "empty_more":
            obj["industries"] = []
        elif case == "null_more":
            obj["next_after_id"] = None
        elif case in ("duplicate_across", "no_progress"):
            obj["industries"][0]["id"] = 2
        elif case == "global_regression":
            obj["industries"][0]["id"] = 1
        elif case == "duplicate_page":
            obj["industries"][1]["id"] = obj["industries"][0]["id"]
        elif case == "unsorted":
            obj["industries"].reverse()
        elif case == "wrong_id":
            obj["request_id"] = "other"
        elif case == "wrong_type":
            obj["type"] = "world_info_result"
        elif case == "protocol":
            obj["protocol"] = 2
        elif case == "status":
            obj["status"] = "failed"
        elif case == "final_cursor":
            obj.update(has_more=False, next_after_id=2)
        elif case == "x_bounds":
            obj["industries"][0]["x"] = 64
        elif case == "y_bounds":
            obj["industries"][0]["y"] = 64
        elif case == "tile":
            obj["industries"][0]["tile"] = 0
        elif case == "oversized_payload":
            obj["request_id"] = "a" * 512

    async def scenario():
        wire = InventoryWire(change=change)
        session = IndustryInventorySession("reject", world_context())
        with pytest.raises(ValueError):
            await session.collect(wire.transport, wire.evidence)
        assert session.evidence.events[-1] == "INVENTORY_SESSION_FAILED"
        assert session.evidence.inventory_digest is None
        assert len(wire.requests) <= 2
        with pytest.raises(ValueError, match="single-use"):
            await session.collect(wire.transport, wire.evidence)

    asyncio.run(scenario())
