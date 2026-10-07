"""Complete native catalog preparation; controlled fixtures only."""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, Mock

import pytest
from test_cargo_catalog import native_page
from test_industry_page_proof import ControlledIndustryBackend
from test_real_ack_graphics import graphics_archive

from app.simulation.openttd.cargo_catalog import CargoCatalogSession
from app.simulation.openttd.cargo_page import (
    CargoPageExchange,
    CargoPageReceipt,
)
from app.simulation.openttd.cargo_page_evidence import parse_cargo_page_evidence
from app.simulation.openttd.proof.cargo_page_contract import PAGE_NETWORK_CHAIN
from app.simulation.openttd.proof.catalog_contract import (
    CATALOG_ATTEMPT_DIRECTORY,
    CATALOG_BUDGET,
    CATALOG_SESSION_ID,
    catalog_request,
)
from app.simulation.openttd.proof.harness import prepare_proof


def test_frozen_session_requests_and_limits():
    assert catalog_request(1, None).request_id == "openttd15-cargo-catalog-001-p001"
    assert catalog_request(2, 9).request_id == "openttd15-cargo-catalog-001-p002"
    assert catalog_request(1, None).limit == 2
    assert CATALOG_BUDGET.max_pages == 32
    assert CATALOG_BUDGET.max_records == 64
    assert CATALOG_BUDGET.max_response_bytes == 16384
    assert CATALOG_BUDGET.max_operations == 512


def make_prepared(tmp_path):
    binary = tmp_path / "fake-openttd"
    binary.write_bytes(b"controlled executable")
    binary.chmod(0o755)
    graphics = tmp_path / "graphics.tar"
    graphics_digest = graphics_archive(graphics)
    return prepare_proof(
        tmp_path / "prelaunch",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=graphics,
        graphics_sha256=graphics_digest,
        mode="cargo-catalog",
    )


class ControlledCatalogBackend(ControlledIndustryBackend):
    def __init__(self, ids=(0, 3, 9, 63), case="ok"):
        super().__init__(case)
        self.ids = ids
        self.network = []
        self.transport = self
        self.session = object()

    async def wait_catalog_startup(self, prepared):
        self.prepared = prepared

    async def cargo_page(self, request, *, timeout, operation_budget=None):
        self.sent += 1
        if self.case == "timeout":
            raise TimeoutError("controlled deadline")
        if self.case == "disconnect":
            raise ConnectionError("controlled disconnect")
        response, raw = native_page(
            self.ids, after=request.after_id, limit=request.limit, request_id=request.request_id
        )
        if self.case == "alive":
            raw = b"".join(
                line
                for line in raw.splitlines(keepends=True)
                if b"BRIDGE_POST_RESPONSE_ALIVE" not in line
            )
        if self.sent >= 1:
            raw = b"".join(
                line for line in raw.splitlines(keepends=True) if b"BRIDGE_STARTED" not in line
            )
        with self.prepared.spec.stderr_path.open("ab") as stream:
            stream.write(raw)
        payload = response.to_bytes()
        receipt = CargoPageReceipt.correlate(request.to_bytes(), payload)
        self.network.append(
            dict(
                request_id=request.request_id,
                ordered_sequence=list(PAGE_NETWORK_CHAIN),
                request_sha256=receipt.request_payload_sha256,
                response_sha256=receipt.response_payload_sha256,
            )
        )
        if self.case == "replacement":
            self.session = object()
        return CargoPageExchange(
            request.to_bytes(), payload, receipt, PAGE_NETWORK_CHAIN, protocol_operations=7
        )

    async def catalog_evidence(self, prepared, request, exchange):
        page = parse_cargo_page_evidence(prepared.spec.stderr_path.read_bytes(), request.request_id)
        page.require_complete(request, exchange.response)
        return page

    def catalog_network_evidence(self):
        return self.network


@pytest.mark.parametrize(
    "ids,case",
    [
        ((), "ok"),
        ((0,), "ok"),
        ((0, 3, 9, 63), "ok"),
        ((0, 3, 9, 63), "alive"),
        ((0, 3), "timeout"),
        ((0, 3), "disconnect"),
        ((0, 3), "replacement"),
    ],
)
def test_controlled_complete_lifecycle_and_truthful_partial(tmp_path, ids, case):
    from app.simulation.openttd.proof.catalog_attempt import execute_catalog_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledCatalogBackend(ids, case)
    result = asyncio.run(execute_catalog_attempt(prepared, backend))
    success = bool(ids) and case == "ok"
    assert result["status"] == ("CONTROLLED_SUCCESS" if success else "CONTROLLED_FAILED")
    assert result["source_integrity"] and not prepared.key_path.exists()
    attempt = prepared.directory.with_name(CATALOG_ATTEMPT_DIRECTORY)
    observation = json.loads((attempt / "catalog-observation.json").read_text())
    assert observation["complete"] == success
    assert result["retries"] == result["reconnects"] == 0
    if success:
        assert observation["page_count"] == (len(ids) + 1) // 2
        assert len(observation["records"]) == len(ids)
    with pytest.raises(ValueError):
        asyncio.run(execute_catalog_attempt(prepared, backend))


def test_public_catalog_preflight_guard(monkeypatch, tmp_path, capsys):
    import sys

    from app.simulation.openttd.proof import __main__ as cli
    from app.simulation.openttd.proof.catalog_native import CatalogNativeBackend

    prepared = make_prepared(tmp_path)
    hooks = []
    try:
        monkeypatch.setattr(sys, "addaudithook", hooks.append)
        monkeypatch.setattr(cli, "load_prepared", lambda *a, **k: prepared)
        monkeypatch.setattr(CatalogNativeBackend, "preflight", lambda *a: None)
        launch = Mock(side_effect=AssertionError("No native launch"))
        monkeypatch.setattr(CatalogNativeBackend, "launch", launch)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "proof",
                "preflight",
                "--mode",
                "cargo-catalog",
                "--directory",
                str(prepared.directory),
            ],
        )
        cli.main()
        result = json.loads(capsys.readouterr().out)
        assert result["state"] == "READY_TO_LAUNCH"
        assert result["catalog_session_loaded"] and result["catalog_digest_loaded"]
        assert result["native_api_authority_loaded"] and result["proof_kind"] == "cargo-catalog"
        assert result["launches"] == result["connections"] == result["requests"] == 0
        assert result["process_creation_blocked"]
        launch.assert_not_called()
        for event in ("subprocess.Popen", "socket.connect"):
            with pytest.raises(PermissionError):
                hooks[0](event, ())
    finally:
        prepared.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_directory", "/tmp/wrong"),
        ("proof_kind", "cargo-page"),
        ("proof_config_sha256", "wrong"),
        ("checkpoint_head", "wrong"),
    ],
)
def test_frozen_destination_and_identity_rejected(tmp_path, field, value):
    from app.simulation.openttd.proof.preflight import validate_native_inputs

    prepared = make_prepared(tmp_path)
    try:
        meta = prepared.directory / "PRELAUNCH.json"
        obj = json.loads(meta.read_text())
        obj[field] = value
        meta.write_text(json.dumps(obj))
        with pytest.raises(ValueError):
            validate_native_inputs(prepared)
    finally:
        prepared.dispose()


@pytest.mark.parametrize("total", [1, 2, 3, 7, 64])
def test_complete_collection_count_not_hardcoded(tmp_path, total):
    from app.simulation.openttd.proof.catalog_attempt import execute_catalog_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledCatalogBackend(tuple(range(total)))
    result = asyncio.run(execute_catalog_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_SUCCESS"
    assert backend.sent == (total + 1) // 2


def test_proof_kind_lineage_isolates_page_and_enrichment(tmp_path):
    from app.simulation.openttd.proof.catalog_lineage import capture_lineage, validate_lineage

    p = tmp_path / "current"
    p.mkdir()
    dest = p.with_name(CATALOG_ATTEMPT_DIRECTORY)
    for kind in ("cargo-page", "industry-capability-enrichment"):
        (tmp_path / f"openttd-15.3-{kind}-real-prelaunch-gate-failure").mkdir()
    lineage = capture_lineage(p, 1, dest)
    assert lineage["supersedes_prelaunch_attempts"] == []
    (tmp_path / "openttd-15.3-cargo-catalog-real-prelaunch-gate-failure").mkdir()
    with pytest.raises(ValueError):
        validate_lineage(p, lineage, 1, dest)


def test_recorded_adapter_boundaries_and_terminal(tmp_path):
    from app.simulation.openttd.admin_protocol import encode_admin_frame
    from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
    from app.simulation.openttd.proof.catalog_native import CatalogRecordedSession

    async def run():
        session = Mock(
            reader=asyncio.StreamReader(), _writer=Mock(), send=AsyncMock(), receive=AsyncMock()
        )
        recorder = CatalogRecordedSession(session)
        q = catalog_request(1, None)
        response, _ = native_page((0, 63), request_id=q.request_id)
        raw = response.to_bytes()
        session.receive.return_value = encode_admin_frame(SERVER_GAMESCRIPT, raw + b"\0")
        await recorder.send(encode_gamescript(q.to_bytes()))
        await recorder.receive()
        receipt = CargoPageReceipt.correlate(q.to_bytes(), raw)
        exchange = CargoPageExchange(
            q.to_bytes(), raw, receipt, PAGE_NETWORK_CHAIN, protocol_operations=7
        )
        recorder.validated(exchange)
        assert recorder.snapshot()[0]["ordered_sequence"] == list(PAGE_NETWORK_CHAIN)
        with pytest.raises(ValueError):
            await recorder.send(encode_gamescript(catalog_request(2, 63).to_bytes()))
        recorder.operations = 511
        recorder.count()
        assert recorder.operations == 512
        with pytest.raises(ValueError):
            recorder.count()

    asyncio.run(run())


def test_correlated_receipt_survives_failure_before_exchange(tmp_path):
    from types import SimpleNamespace

    from app.simulation.openttd.proof.catalog_attempt import execute_catalog_attempt

    class FailAfterReceipt(ControlledCatalogBackend):
        async def cargo_page(self, request, **kwargs):
            exchange = await super().cargo_page(request, **kwargs)
            self.catalog_session = SimpleNamespace(
                pages=[
                    dict(
                        request=exchange.request_payload,
                        response=exchange.response_payload,
                        receipt=exchange.receipt,
                    )
                ]
            )
            self.network[-1]["ordered_sequence"] = list(PAGE_NETWORK_CHAIN[:3])
            raise ConnectionError("completion barrier disconnected after receipt")

    prepared = make_prepared(tmp_path)
    backend = FailAfterReceipt()
    result = asyncio.run(execute_catalog_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED"
    attempt = prepared.directory.with_name(CATALOG_ATTEMPT_DIRECTORY)
    receipts = [
        json.loads(line) for line in (attempt / "page-receipts.jsonl").read_text().splitlines()
    ]
    assert len(receipts) == 1 and receipts[0]["response_semantics_valid"] is False
    assert receipts[0]["response_payload_sha256"] == backend.network[0]["response_sha256"]


def test_late_finalization_failure_reconciles_digest(tmp_path, monkeypatch):
    from app.simulation.openttd.proof.catalog_attempt import execute_catalog_attempt

    prepared = make_prepared(tmp_path)
    monkeypatch.setattr(
        type(prepared),
        "dispose",
        lambda self: (_ for _ in ()).throw(OSError("controlled disposal failure")),
    )
    result = asyncio.run(execute_catalog_attempt(prepared, ControlledCatalogBackend()))
    assert result["status"] == "CONTROLLED_FAILED" and result["verification"]["status"] == "FAILED"
    attempt = prepared.directory.with_name(CATALOG_ATTEMPT_DIRECTORY)
    assert json.loads((attempt / "catalog-digest.json").read_text())["verified"] is False
    assert json.loads((attempt / "catalog-observation.json").read_text())["complete"] is False


@pytest.mark.parametrize("number", [0, 33, 64, True])
def test_request_ceiling_rejected(number):
    with pytest.raises(ValueError):
        catalog_request(number, None)


@pytest.mark.parametrize("limit", [1, 2, 4])
def test_canonical_digest_page_boundary_independent(tmp_path, limit):
    from dataclasses import replace

    from app.simulation.openttd.cargo_catalog import CargoCatalogObservation, CargoCatalogPage

    records = (0, 3, 9, 63)

    def assemble(size):
        pages = []
        cursor = None
        while True:
            request = replace(catalog_request(len(pages) + 1, cursor), limit=size)
            response, raw = native_page(
                records, after=cursor, limit=size, request_id=request.request_id
            )
            payload = response.to_bytes()
            receipt = CargoPageReceipt.correlate(request.to_bytes(), payload)
            exchange = CargoPageExchange(request.to_bytes(), payload, receipt, PAGE_NETWORK_CHAIN)
            pages.append(
                CargoCatalogPage(exchange, parse_cargo_page_evidence(raw, request.request_id))
            )
            if not response.has_more:
                break
            cursor = response.next_after_id
        return CargoCatalogObservation(CATALOG_SESSION_ID, tuple(pages))

    assert assemble(limit).catalog_digest == assemble(2).catalog_digest


@pytest.mark.parametrize(
    "budget,expected",
    [
        (dict(max_pages=1), False),
        (dict(max_records=2), False),
        (dict(max_response_bytes=1), False),
        (dict(max_operations=4), False),
        (dict(max_pages=2, max_records=4, max_response_bytes=16384, max_operations=14), True),
    ],
)
def test_catalog_exact_and_exceeded_session_budgets(tmp_path, budget, expected):
    from app.simulation.openttd.cargo_catalog import CargoCatalogBudget

    prepared = make_prepared(tmp_path)
    backend = ControlledCatalogBackend()
    backend.prepared = prepared
    prepared.spec.stderr_path.write_bytes(b"")
    session = CargoCatalogSession(
        CATALOG_SESSION_ID, page_size=2, budget=CargoCatalogBudget(**budget)
    )
    try:
        if expected:
            observation = asyncio.run(
                session.collect(backend, lambda q, e: backend.catalog_evidence(prepared, q, e))
            )
            assert observation.complete
        else:
            with pytest.raises(Exception):
                asyncio.run(
                    session.collect(backend, lambda q, e: backend.catalog_evidence(prepared, q, e))
                )
            assert not session.evidence.complete
        with pytest.raises(Exception):
            asyncio.run(
                session.collect(backend, lambda q, e: backend.catalog_evidence(prepared, q, e))
            )
    finally:
        prepared.dispose()


def test_preserved_prelaunch_failure_requires_fresh_revision(tmp_path):
    from app.simulation.openttd.proof.catalog_lineage import capture_lineage, validate_lineage
    from app.simulation.openttd.proof.world_attempt import record_prelaunch_failure

    prepared = make_prepared(tmp_path)
    try:
        record_prelaunch_failure(prepared.directory, ValueError("controlled gate failure"))
        new = tmp_path / "new"
        new.mkdir()
        destination = new.with_name(CATALOG_ATTEMPT_DIRECTORY)
        lineage = capture_lineage(new, 2, destination)
        assert len(lineage["supersedes_prelaunch_attempts"]) == 1
        assert validate_lineage(new, lineage, 2, destination) == 1
        with pytest.raises(ValueError):
            capture_lineage(new, 1, destination)
    finally:
        prepared.dispose()


@pytest.mark.parametrize(
    "change",
    [
        dict(type="industry_page_result"),
        dict(type="cargo_page"),
        dict(request_id="wrong"),
        dict(protocol=2),
        dict(status="error"),
        dict(next_after_id=None),
        dict(next_after_id=0),
        dict(has_more=False, next_after_id=3),
        dict(has_more=True, cargoes=[]),
        dict(cargoes=[dict(id=64, label="FFFFFFFF", freight=True, town_effect=0, classes=0)]),
        dict(cargoes=[dict(id=0, label="invalid", freight=True, town_effect=0, classes=0)]),
        dict(cargoes=[dict(id=0, label="FFFFFFFF", freight=1, town_effect=0, classes=0)]),
        dict(cargoes=[dict(id=0, label="FFFFFFFF", freight=True, town_effect=6, classes=0)]),
        dict(cargoes=[dict(id=3, label="FFFFFFFF", freight=True, town_effect=0, classes=0)] * 2),
        dict(
            cargoes=[
                dict(id=i, label="FFFFFFFF", freight=True, town_effect=0, classes=0) for i in (3, 0)
            ]
        ),
    ],
)
def test_invalid_page_cannot_complete_session(tmp_path, change):
    class Malformed(ControlledCatalogBackend):
        async def cargo_page(self, request, **kwargs):
            exchange = await super().cargo_page(request, **kwargs)
            obj = json.loads(exchange.response_payload)
            obj.update(change)
            raw = json.dumps(obj, separators=(",", ":")).encode()
            receipt = CargoPageReceipt.correlate_transport(request.to_bytes(), raw)
            return CargoPageExchange(request.to_bytes(), raw, receipt, PAGE_NETWORK_CHAIN)

    prepared = make_prepared(tmp_path)
    backend = Malformed()
    backend.prepared = prepared
    prepared.spec.stderr_path.write_bytes(b"")
    session = CargoCatalogSession(CATALOG_SESSION_ID, page_size=2, budget=CATALOG_BUDGET)
    try:
        with pytest.raises(Exception):
            asyncio.run(
                session.collect(backend, lambda q, e: backend.catalog_evidence(prepared, q, e))
            )
        assert not session.evidence.complete and backend.sent == 1
    finally:
        prepared.dispose()


def test_exact_cumulative_byte_boundary(tmp_path):
    from app.simulation.openttd.cargo_catalog import CargoCatalogBudget

    prepared = make_prepared(tmp_path)
    backend = ControlledCatalogBackend()
    backend.prepared = prepared

    def collect(bound):
        backend.sent = 0
        backend.network = []
        prepared.spec.stderr_path.write_bytes(b"")
        session = CargoCatalogSession(
            CATALOG_SESSION_ID, budget=CargoCatalogBudget(max_response_bytes=bound)
        )
        return asyncio.run(
            session.collect(backend, lambda q, e: backend.catalog_evidence(prepared, q, e))
        )

    try:
        baseline = collect(16384)
        assert collect(baseline.total_response_bytes).complete
        with pytest.raises(Exception):
            collect(baseline.total_response_bytes - 1)
    finally:
        prepared.dispose()


def test_payload_and_generic_defaults_stay_frozen():
    from app.simulation.openttd.cargo_page import (
        DEFAULT_CARGO_PAGE_SIZE,
        MAX_CARGO_PAGE_SIZE,
        CargoCatalogRecord,
        CargoPageResponse,
    )

    assert DEFAULT_CARGO_PAGE_SIZE == 2 and MAX_CARGO_PAGE_SIZE == 4
    request = catalog_request(32, 61)
    raw = CargoPageResponse(
        request.request_id,
        tuple(CargoCatalogRecord(i, "FFFFFFFF", False, 5, 32767) for i in (62, 63)),
        None,
        False,
    ).to_bytes()
    assert len(raw) == 307 < 512 < 1450
