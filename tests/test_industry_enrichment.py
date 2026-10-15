"""Controlled same-run inventory then capability preparation."""

import asyncio
import copy
import hashlib
from pathlib import Path

import pytest
from test_industry_inventory import InventoryWire, world_context
from test_industry_page_proof import ControlledIndustryBackend

from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_enrichment import EnrichmentBudget, IndustryEnrichmentSession


def test_combined_bounds():
    b = EnrichmentBudget()
    assert (b.max_requests, b.max_response_bytes, b.max_operations) == (64, 32768, 512)
    with pytest.raises(ValueError):
        EnrichmentBudget(max_requests=65)


class CombinedWire(InventoryWire):
    def __init__(self, ids=(0, 3, 17), *, failure=None, change=None, missing=None):
        import json

        from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
        from app.simulation.openttd.gamescript_transport import GameScriptTransport
        from app.simulation.openttd.industry_cargo import (
            IndustryCargoCapability,
            IndustryCargoRequest,
            IndustryCargoResponse,
        )
        from app.simulation.openttd.proof.enrichment_native import EnrichmentRecordedSession

        super().__init__(
            ids,
            fail_page=1 if failure == "inventory_disconnect" else None,
            failure="disconnect" if failure == "inventory_disconnect" else None,
        )
        self.cargo_requests = []
        self.log = b"dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n"
        self.path = None
        self.failure = failure
        self.missing = missing
        original = self.writer.write.side_effect

        def send(frame):
            if frame[2] != 6 or json.loads(frame[3:-1])["type"] != "industry_cargo":
                return original(frame)
            request = IndustryCargoRequest.parse(frame[3:-1])
            self.cargo_requests.append(request)
            if failure == "capability_disconnect":
                self.reader.feed_eof()
                return
            if failure == "timeout":
                return
            obj = json.loads(
                IndustryCargoResponse(
                    request.request_id, IndustryCargoCapability(request.industry_id, (1, 63), ())
                ).to_bytes()
            )
            if change:
                change(obj)
            raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
            self.reader.feed_data(encode_admin_frame(124, raw + b"\0"))
            if failure == "duplicate":
                self.reader.feed_data(encode_admin_frame(124, raw + b"\0"))

        self.writer.write.side_effect = send
        self.recorded = EnrichmentRecordedSession(self.transport.session)
        self.transport = GameScriptTransport(self.recorded, ServerProtocol(3, ((9, 64),)))

    def append(self, raw):
        if self.missing:
            raw = b"".join(
                line for line in raw.splitlines(keepends=True) if self.missing.encode() not in line
            )
        self.log += raw
        if self.path:
            self.path.write_bytes(self.log)
        return raw

    async def evidence(self, request, exchange):
        from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

        native = await super().evidence(request, exchange)
        native = parse_industry_page_evidence(self.append(native.raw_log), request.request_id)
        native.require_complete(request, exchange.response)
        self.recorded.validated(exchange)
        return native

    async def cargo_evidence(self, request, exchange):
        from app.simulation.openttd.industry_cargo_evidence import parse_industry_cargo_evidence

        p = exchange.response.capability.produces
        a = exchange.response.capability.accepts

        def token(v):
            return "null" if v is None else str(v)

        lines = [
            (
                f"BRIDGE_REQUEST_RECEIVED request_id={request.request_id} "
                f"type=industry_cargo protocol=1"
            ),
            (
                f"INDUSTRY_CARGO_READ request_id={request.request_id} "
                f"industry_id={request.industry_id} produced_count={len(p)} "
                f"accepted_count={len(a)} "
                f"first_produced={token(p[0] if p else None)} "
                f"last_produced={token(p[-1] if p else None)} "
                f"first_accepted={token(a[0] if a else None)} "
                f"last_accepted={token(a[-1] if a else None)}"
            ),
            (
                f"BRIDGE_RESPONSE_SENT request_id={request.request_id} "
                f"type=industry_cargo_result status=ok protocol=1"
            ),
            f"BRIDGE_POST_RESPONSE_ALIVE request_id={request.request_id}",
        ]
        raw = "".join("dbg: [script:4] [18] [I] " + line + "\n" for line in lines).encode()
        native = parse_industry_cargo_evidence(self.append(raw), request.request_id)
        native.require_complete(request, exchange.response)
        self.recorded.cargo_validated(exchange)
        return native


def make_session(budget=None):
    return IndustryEnrichmentSession(
        world_context(),
        BridgePackage(Path("controlled-bridge"), "f" * 64),
        budget=budget or EnrichmentBudget(),
        timeout=0.05,
    )


@pytest.mark.parametrize(
    "ids", [(), (17,), (0, 3), (0, 3, 17), (2, 17, 31), (0, 1, 2, 3, 5, 8, 13), tuple(range(32))]
)
def test_complete_same_run_worlds(ids):
    async def run():
        wire = CombinedWire(ids)
        session = make_session()
        result = await session.collect(
            wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
        )
        assert result.complete and result.inventory.records == result.capability.inventory.records
        assert [q.industry_id for q in wire.cargo_requests] == list(ids)
        assert len(result.capability.transactions) == len(ids)
        assert result.source_inventory_digest == result.inventory.inventory_digest
        assert result.total_requests == result.inventory.page_count + len(ids)
        assert len({q.request_id for q in wire.cargo_requests}) == len(ids)
        assert session.events.index("INVENTORY_COMPLETED") < session.events.index(
            "CAPABILITY_PHASE_STARTED"
        )
        assert result.capability.inventory.world is session.world
        assert len(result.capability_digest) == len(result.enriched_digest) == 64
        assert session.events[-1] == "ENRICHMENT_SESSION_COMPLETED"
        assert len(wire.recorded.cargo_snapshot()) == len(ids)
        with pytest.raises(ValueError, match="single-use"):
            await session.collect(
                wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
            )

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", ["inventory_disconnect", "capability_disconnect", "timeout", "duplicate"]
)
def test_transport_failure_no_retry(failure):
    async def run():
        wire = CombinedWire((3, 17), failure=failure)
        session = make_session()
        with pytest.raises((ValueError, TimeoutError, ConnectionError)):
            await session.collect(
                wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
            )
        assert session.observation is None and session.events[-1] == "ENRICHMENT_SESSION_FAILED"
        assert len(wire.cargo_requests) <= 1
        if failure == "inventory_disconnect":
            assert not wire.cargo_requests and session.inventory is None
        else:
            assert session.inventory.complete

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"industry_id": 999},
        {"request_id": "wrong"},
        {"type": "industry_page_result"},
        {"produces": [1, 1]},
        {"accepts": [63, 1]},
        {"produces": [64]},
    ],
)
def test_malformed_capability_fails_session(change):
    async def run():
        wire = CombinedWire(change=lambda obj: obj.update(change))
        session = make_session()
        with pytest.raises(ValueError):
            await session.collect(
                wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
            )
        assert session.inventory.complete and session.observation is None
        assert len(wire.cargo_requests) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "marker",
    [
        "INDUSTRY_PAGE_READ",
        "INDUSTRY_CARGO_READ",
        "BRIDGE_RESPONSE_SENT",
        "BRIDGE_POST_RESPONSE_ALIVE",
    ],
)
def test_each_native_chain_requires_liveness(marker):
    async def run():
        wire = CombinedWire(missing=marker)
        session = make_session()
        with pytest.raises(ValueError):
            await session.collect(
                wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
            )
        assert session.observation is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "budget",
    [
        EnrichmentBudget(max_requests=1),
        EnrichmentBudget(max_response_bytes=1),
        EnrichmentBudget(max_operations=1),
    ],
)
def test_combined_budget_exhaustion(budget):
    async def run():
        wire = CombinedWire((3,))
        session = make_session(budget)
        with pytest.raises(ValueError, match="budget"):
            await session.collect(
                wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
            )
        assert not wire.cargo_requests

    asyncio.run(run())


def test_exact_measured_budget_and_digests():
    async def run():
        wire = CombinedWire((3, 17))
        session = make_session()
        result = await session.collect(
            wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
        )
        exact = EnrichmentBudget(
            result.total_requests, result.total_response_bytes, result.protocol_operations
        )
        wire2 = CombinedWire((3, 17))
        second = make_session(exact)
        copy = await second.collect(
            wire2.transport, wire2.evidence, wire2.cargo_evidence, wire2.recorded.begin_capability
        )
        assert (
            copy.capability_digest == result.capability_digest
            and copy.enriched_digest == result.enriched_digest
        )
        assert len(copy.inventory.page_receipts) == 1
        assert all(t.exchange.receipt for t in copy.capability.transactions)

    asyncio.run(run())


def test_phase_start_and_connection_replacement_rejected():
    async def run():
        wire = CombinedWire()
        session = make_session()
        with pytest.raises(ValueError):
            wire.recorded.begin_capability(None)

        def swap(inventory):
            wire.recorded.begin_capability(inventory)
            wire.transport.session = copy.copy(wire.recorded.session)

        with pytest.raises(ValueError, match="connection changed"):
            await session.collect(wire.transport, wire.evidence, wire.cargo_evidence, swap)
        assert not wire.cargo_requests and session.inventory.complete

    asyncio.run(run())


def make_prepared(tmp_path):
    from test_real_ack_graphics import graphics_archive

    from app.simulation.openttd.proof.harness import prepare_proof

    tmp_path.mkdir(parents=True, exist_ok=True)
    binary = tmp_path / "openttd"
    binary.write_bytes(b"controlled binary")
    binary.chmod(0o700)
    archive = tmp_path / "graphics.zip"
    digest = graphics_archive(archive)
    # Historical proof contract keeps the exact V4 bridge, not the new catalog branch.
    from pathlib import Path

    from app.simulation.openttd import gamescript_bridge

    with pytest.MonkeyPatch.context() as checkpoint:
        checkpoint.setattr(
            gamescript_bridge,
            "BRIDGE_DIRECTORY",
            Path("tests/fixtures/industry_capability_checkpoint_bridge"),
        )
        return prepare_proof(
            tmp_path / "prelaunch",
            mode="industry-enrichment",
            binary=binary,
            binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            graphics=archive,
            graphics_sha256=digest,
        )


def test_public_cli_mode(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.simulation.openttd.proof import __main__ as cli

    prepare = Mock(return_value=SimpleNamespace(directory=tmp_path))
    monkeypatch.setattr(cli, "prepare_proof", prepare)
    monkeypatch.setattr(
        sys,
        "argv",
        ["proof", "prepare", "--mode", "industry-enrichment", "--directory", str(tmp_path)],
    )
    cli.main()
    prepare.assert_called_once_with(tmp_path, mode="industry-enrichment")


def test_guarded_cli_owns_reservation(monkeypatch, tmp_path, capsys):
    import json
    import sys
    from unittest.mock import Mock

    from app.simulation.openttd.proof import __main__ as cli
    from app.simulation.openttd.proof.harness import EndpointReservation

    prepared = make_prepared(tmp_path)
    guards = []
    calls = []
    reserve = EndpointReservation.allocate

    def allocate(*ports):
        calls.append(ports)
        return reserve(*ports)

    create = Mock(side_effect=AssertionError("no subprocess"))
    connect = Mock(side_effect=AssertionError("no connection"))
    monkeypatch.setattr("subprocess.Popen", create)
    monkeypatch.setattr("socket.socket.connect", connect)
    monkeypatch.setattr(sys, "addaudithook", guards.append)
    monkeypatch.setattr(cli, "load_prepared", lambda directory, mode: prepared)
    monkeypatch.setattr(cli, "EnrichmentNativeBackend", lambda **kwargs: Mock())
    monkeypatch.setattr(EndpointReservation, "allocate", allocate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
            "preflight",
            "--mode",
            "industry-enrichment",
            "--directory",
            str(prepared.directory),
        ],
    )
    try:
        cli.main()
        r = json.loads(capsys.readouterr().out)
        assert r["state"] == "READY_TO_LAUNCH" and r["process_creation_blocked"]
        assert (
            r["inventory_phase_loaded"]
            and r["capability_phase_loaded"]
            and r["same_run_digest_wiring_loaded"]
        )
        assert r["launches"] == r["connections"] == r["requests"] == 0
        assert calls == [prepared.endpoints]
        create.assert_not_called()
        connect.assert_not_called()
        assert not Path(r["evidence_destination"]).exists()
        for event in ("subprocess.Popen", "socket.connect"):
            with pytest.raises(PermissionError):
                guards[0](event, ())
    finally:
        prepared.dispose()


class ControlledEnrichmentBackend(ControlledIndustryBackend):
    def __init__(self, ids=(0, 3, 17), **kwargs):
        super().__init__()
        self.ids = ids
        self.kwargs = kwargs
        self.session = None
        self.wire = None

    async def authenticate(self, prepared, gates):
        auth = await super().authenticate(prepared, gates)
        self.wire = CombinedWire(self.ids, **self.kwargs)
        self.wire.path = prepared.spec.stderr_path
        self.transport = self.wire.transport
        self.session = self.wire.recorded.session
        return auth

    async def wait_inventory_startup(self, prepared):
        pass

    async def inventory_evidence(self, prepared, request, exchange):
        assert self.wire is not None
        return await self.wire.evidence(request, exchange)

    def begin_capability(self, inventory):
        assert self.wire is not None
        self.wire.recorded.begin_capability(inventory)

    async def capability_evidence(self, prepared, request, exchange):
        assert self.wire is not None
        return await self.wire.cargo_evidence(request, exchange)

    def inventory_network_evidence(self):
        return [] if self.wire is None else self.wire.recorded.snapshot()

    def capability_network_evidence(self):
        return [] if self.wire is None else self.wire.recorded.cargo_snapshot()

    @property
    def inventory_session(self):
        return None if self.wire is None else self.wire.recorded


@pytest.mark.parametrize("ids", [(), (17,), (3, 17, 31)])
def test_controlled_full_production_lifecycle(tmp_path, ids):
    import json

    from app.simulation.openttd.proof.enrichment_attempt import execute_enrichment_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledEnrichmentBackend(ids)
    result = asyncio.run(execute_enrichment_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_SUCCESS", result["error"]
    assert result["requests_sent"] == (max(1, (len(ids) + 1) // 2) + len(ids))
    assert result["source_integrity"] and result["states"][-1] == "COMPLETED"
    attempt = prepared.directory.with_name(
        "openttd-15.3-industry-capability-enrichment-real-attempt1"
    )
    observation = json.loads((attempt / "enriched-observation.json").read_text())
    assert observation["complete"] and observation["industry_count"] == observation[
        "capability_result_count"
    ] == len(ids)
    assert (
        observation["source_inventory_digest"]
        == json.loads((attempt / "inventory-digest.json").read_text())["sha256"]
    )
    assert (
        observation["independent_inventory_source"] is None
        and observation["independent_capability_source"] is None
    )
    assert not prepared.key_path.exists() and backend.closed == 1
    with pytest.raises(ValueError, match="no retry"):
        asyncio.run(execute_enrichment_attempt(prepared, backend))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"failure": "inventory_disconnect"},
        {"failure": "capability_disconnect"},
        {"failure": "duplicate"},
        {"missing": "INDUSTRY_CARGO_READ"},
        {"missing": "BRIDGE_POST_RESPONSE_ALIVE"},
        {"change": lambda obj: obj.update(industry_id=999)},
    ],
)
def test_controlled_failure_retains_partial_and_cleanup(tmp_path, kwargs):
    import json

    from app.simulation.openttd.proof.enrichment_attempt import execute_enrichment_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledEnrichmentBackend(**kwargs)
    result = asyncio.run(execute_enrichment_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED" and result["states"][-1] == "FAILED"
    attempt = prepared.directory.with_name(
        "openttd-15.3-industry-capability-enrichment-real-attempt1"
    )
    observation = json.loads((attempt / "enriched-observation.json").read_text())
    assert not observation["complete"]
    assert not json.loads((attempt / "capability-observation.json").read_text())["complete"]
    assert (attempt / "page-requests.jsonl").exists() and (
        attempt / "capability-requests.jsonl"
    ).exists()
    assert not prepared.key_path.exists() and backend.closed == 1
    assert backend.wire is not None
    assert len(backend.wire.cargo_requests) <= 1


@pytest.mark.parametrize("kind", ["missing", "duplicate", "extra"])
def test_complete_coverage_model_rejects_invalid_set(kind):
    from dataclasses import replace

    async def run():
        wire = CombinedWire((3, 17))
        session = make_session()
        result = await session.collect(
            wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
        )
        if kind == "missing":
            transactions = result.capability.transactions[:1]
        elif kind == "duplicate":
            transactions = result.capability.transactions + result.capability.transactions[:1]
        else:
            smallwire = CombinedWire((3,))
            small = make_session()
            smallresult = await small.collect(
                smallwire.transport,
                smallwire.evidence,
                smallwire.cargo_evidence,
                smallwire.recorded.begin_capability,
            )
            with pytest.raises(ValueError):
                replace(result.capability, inventory=smallresult.inventory)
            return
        with pytest.raises(ValueError):
            replace(result.capability, transactions=transactions)

    asyncio.run(run())


def test_digest_order_and_page_boundary_independence():
    from dataclasses import replace

    from app.simulation.openttd.industry_enrichment import (
        ENRICHMENT_INVENTORY_ID,
        IndustryEnrichmentObservation,
    )
    from app.simulation.openttd.industry_query import IndustryInventorySession

    async def run():
        wire = CombinedWire((0, 3, 17))
        session = make_session()
        result = await session.collect(
            wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
        )
        reversed_cap = replace(
            result.capability, transactions=tuple(reversed(result.capability.transactions))
        )
        assert reversed_cap.capability_digest == result.capability_digest
        other = InventoryWire((0, 3, 17))
        inventory = await IndustryInventorySession(
            ENRICHMENT_INVENTORY_ID, world_context(), page_size=3
        ).collect(other.transport, other.evidence)
        cap = replace(result.capability, inventory=inventory)
        observation = IndustryEnrichmentObservation(cap, result.bridge_identity)
        assert observation.source_inventory_digest == result.source_inventory_digest
        assert observation.enriched_digest == result.enriched_digest

    asyncio.run(run())


def test_freeze_key_and_no_p08_or_mutation(tmp_path):
    import ast
    import json

    prepared = make_prepared(tmp_path)
    try:
        frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
        assert list(frozen) == sorted(frozen)
        for p, h in frozen.items():
            assert hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
        assert (
            str(prepared.key_path) not in frozen
            and prepared.key_path.stat().st_mode & 0o777 == 0o600
        )
        secret = prepared.key_path.read_bytes()
        assert all(
            secret not in p.read_bytes() for p in prepared.directory.iterdir() if p.is_file()
        )
        for p in [
            Path("app/simulation/openttd/industry_enrichment.py"),
            *Path("app/simulation/openttd/proof").glob("enrichment*.py"),
        ]:
            for node in ast.walk(ast.parse(p.read_text())):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith("app.planning")
        source = Path("tests/fixtures/industry_capability_checkpoint_bridge/main.nut").read_text()
        for name in (
            "GetLastMonthProduction",
            "GetLastMonthTransported",
            "Stockpile",
            "IsCargoAccepted",
            "GSCargo.GetName",
            "GSCargo.GetCargoLabel",
            "GSCompanyMode",
            "GSRoad",
            "GSRail",
            "GSVehicle",
            "GSOrder",
            "RCON",
        ):
            assert name not in source
    finally:
        prepared.dispose()


def test_prelaunch_tamper_stops_without_activity(tmp_path):
    from app.simulation.openttd.proof.enrichment_attempt import execute_enrichment_attempt

    prepared = make_prepared(tmp_path)
    (prepared.directory / "request.json").write_bytes(b"tampered")
    backend = ControlledEnrichmentBackend()
    with pytest.raises(ValueError):
        asyncio.run(execute_enrichment_attempt(prepared, backend))
    assert backend.launches == 0 and backend.session is None
    prepared.dispose()


def test_insufficient_combined_frames_never_sends():
    async def run():
        wire = CombinedWire()
        session = make_session(budget=EnrichmentBudget(max_operations=3))
        with pytest.raises(ValueError, match="frame budget"):
            await session.collect(
                wire.transport, wire.evidence, wire.cargo_evidence, wire.recorded.begin_capability
            )
        assert not wire.recorded.pages and not wire.cargo_requests

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["inventory", "capability"])
def test_connection_replacement_during_transaction_fails(phase):
    async def run():
        wire = CombinedWire()
        session = make_session()

        async def page(request, exchange):
            value = await wire.evidence(request, exchange)
            if phase == "inventory":
                wire.transport.session = copy.copy(wire.recorded.session)
            return value

        async def cargo(request, exchange):
            value = await wire.cargo_evidence(request, exchange)
            wire.transport.session = copy.copy(wire.recorded.session)
            return value

        with pytest.raises(ValueError, match="connection changed"):
            await session.collect(wire.transport, page, cargo, wire.recorded.begin_capability)
        assert session.observation is None
        assert len(wire.cargo_requests) == (0 if phase == "inventory" else 1)

    asyncio.run(run())


@pytest.mark.parametrize("point", ["artifact", "dispose", "identity"])
def test_late_failure_reconciles_all_summaries(tmp_path, monkeypatch, point):
    import json

    from app.simulation.openttd.proof import enrichment_attempt as module

    prepared = make_prepared(tmp_path)
    backend = ControlledEnrichmentBackend()
    if point == "artifact":
        original = module.write_json

        def fail_once(path, value):
            if path.name == "process-lifecycle.json":
                raise OSError("injected late write failure")
            return original(path, value)

        monkeypatch.setattr(module, "write_json", fail_once)
    elif point == "dispose":
        original = type(prepared).dispose

        def fail_dispose(self):
            original(self)
            raise OSError("injected disposal failure")

        monkeypatch.setattr(type(prepared), "dispose", fail_dispose)
    else:

        def fail_identity(*args):
            raise OSError("injected attempt identity failure")

        monkeypatch.setattr(module, "retain_attempt_identity", fail_identity)
    result = asyncio.run(module.execute_enrichment_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED"
    attempt = prepared.directory.with_name(module.ENRICHMENT_ATTEMPT_DIRECTORY)
    for name in ("enriched-observation.json", "enrichment-session.json"):
        assert json.loads((attempt / name).read_text())["complete"] is False
    assert "CONTROLLED_FAILED" in (attempt / "final-report.md").read_text()
    assert backend.launches == 1 and result["requests_sent"] == 5
    assert not prepared.key_path.exists()


def test_inventory_failure_retains_partial_observation(tmp_path):
    import json

    from app.simulation.openttd.proof.enrichment_attempt import (
        ENRICHMENT_ATTEMPT_DIRECTORY,
        execute_enrichment_attempt,
    )

    class Interrupted(ControlledEnrichmentBackend):
        async def inventory_evidence(self, prepared, request, exchange):
            value = await super().inventory_evidence(prepared, request, exchange)
            if request.after_id is None:
                assert self.wire is not None
                self.wire.reader.feed_eof()
            return value

    prepared = make_prepared(tmp_path)
    backend = Interrupted()
    result = asyncio.run(execute_enrichment_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED"
    attempt = prepared.directory.with_name(ENRICHMENT_ATTEMPT_DIRECTORY)
    value = json.loads((attempt / "inventory-observation.json").read_text())
    assert value["complete"] is False and value["inventory_digest"] is None
    assert [r["id"] for r in value["records"]] == [0, 3]
    assert backend.wire is not None
    assert not backend.wire.cargo_requests
