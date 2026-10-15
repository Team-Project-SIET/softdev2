"""Controlled one-page proof preparation; no native execution."""

import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_cargo_catalog import native_page
from test_industry_page_proof import ControlledIndustryBackend
from test_real_ack_graphics import graphics_archive

from app.simulation.openttd.cargo_page import CargoPageExchange, CargoPageReceipt
from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.proof.cargo_page_contract import (
    PAGE_ATTEMPT_DIRECTORY,
    PAGE_BRIDGE_DIGEST,
    PAGE_MODEL,
    PAGE_NETWORK_CHAIN,
    PAGE_REQUEST,
    PAGE_REVISION,
    page_contract,
    page_contract_digest,
)
from app.simulation.openttd.proof.cargo_page_verification import verify_cargo_page
from app.simulation.openttd.proof.harness import prepare_proof
from app.simulation.openttd.runtime.identity import RuntimeIdentity


def test_frozen_request():
    expected = (
        b'{"after_id":null,"limit":2,"protocol":1,'
        b'"request_id":"openttd15-cargo-page-001","type":"cargo_page"}'
    )
    assert PAGE_REQUEST.to_bytes() == expected
    assert PAGE_REQUEST.after_id is None and PAGE_REQUEST.limit == 2
    assert (
        hashlib.sha256(PAGE_REQUEST.to_bytes()).hexdigest() == hashlib.sha256(expected).hexdigest()
    )


def test_one_page_verification(tmp_path):
    response, raw = native_page(request_id=PAGE_REQUEST.request_id)
    payload = response.to_bytes()
    receipt = CargoPageReceipt.correlate(PAGE_REQUEST.to_bytes(), payload)
    result = verify_cargo_page(
        PAGE_REQUEST,
        payload,
        receipt,
        runtime=RuntimeIdentity(tmp_path / "binary", "15.3", "f" * 64),
        bridge=BridgePackage(tmp_path, "f" * 64),
    )
    assert (
        result.verified
        and result.ordered_cargo_ids == (0, 9)
        and result.independent_second_source_catalog is None
    )
    from app.simulation.openttd.proof.cargo_page_evidence import parse_page_proof_evidence

    assert (
        parse_page_proof_evidence(raw, PAGE_REQUEST.request_id)
        .correlate(PAGE_REQUEST, payload)
        .response_digest
        == result.response_digest
    )


def make_prepared(tmp_path):
    binary = tmp_path / "openttd"
    binary.write_bytes(b"controlled binary")
    binary.chmod(0o700)
    archive = tmp_path / "graphics.zip"
    graphics_digest = graphics_archive(archive)
    return prepare_proof(
        tmp_path / "prelaunch",
        mode="cargo-page",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=archive,
        graphics_sha256=graphics_digest,
    )


def test_frozen_preparation_and_credential(tmp_path):
    prepared = make_prepared(tmp_path)
    try:
        meta = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert meta["proof_kind"] == "cargo-page" and meta["proof_model"] == PAGE_MODEL
        assert meta["attempt_directory"] == str(
            prepared.directory.with_name(PAGE_ATTEMPT_DIRECTORY)
        )
        assert meta["proof_config_sha256"] == page_contract_digest()
        assert prepared.key_path.stat().st_mode & 0o777 == 0o600
        secret = prepared.key_path.read_bytes()
        frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
        assert str(prepared.key_path) not in frozen and list(frozen) == sorted(frozen)
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in frozen.items())
        assert all(
            secret not in p.read_bytes() and secret.hex().encode() not in p.read_bytes()
            for p in prepared.directory.iterdir()
            if p.is_file()
        )
        assert (
            json.loads((prepared.directory / "bridge-package-identity.json").read_text())["sha256"]
            == PAGE_BRIDGE_DIGEST
        )
        contract = page_contract()
        assert contract["response_bound"] == 299 and contract["generic_response_bound"] == 493
        assert (
            contract["success"]["requests"] == 1
            and contract["success"]["retries"] == contract["success"]["reconnects"] == 0
        )
    finally:
        prepared.dispose()


def test_public_guarded_preflight_zero_activity(monkeypatch, tmp_path, capsys):
    import sys

    from app.simulation.openttd.proof import __main__ as cli
    from app.simulation.openttd.proof.cargo_page_native import CargoPageNativeBackend

    prepared = make_prepared(tmp_path)
    hooks = []
    try:
        monkeypatch.setattr(sys, "addaudithook", hooks.append)
        monkeypatch.setattr(cli, "load_prepared", lambda *a, **k: prepared)
        monkeypatch.setattr(
            sys,
            "argv",
            ["proof", "preflight", "--mode", "cargo-page", "--directory", str(prepared.directory)],
        )
        launch = Mock(side_effect=AssertionError("no launch"))
        monkeypatch.setattr(CargoPageNativeBackend, "launch", launch)
        monkeypatch.setattr(CargoPageNativeBackend, "preflight", lambda self, p: None)
        cli.main()
        result = json.loads(capsys.readouterr().out)
        assert result["state"] == "READY_TO_LAUNCH"
        assert result["native_api_authority_loaded"]
        assert result["canonical_evidence_policy_loaded"]
        assert result["proof_kind"] == "cargo-page" and result["process_creation_blocked"]
        assert result["lineage_validated"] and result["lineage_predecessor_count"] == 0
        for event in ("subprocess.Popen", "socket.connect"):
            with pytest.raises(PermissionError):
                hooks[0](event, ())
        launch.assert_not_called()
    finally:
        prepared.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_directory", "wrong"),
        ("proof_kind", "industry-enrichment"),
        ("proof_config_sha256", "0" * 64),
        ("attempt_id", "wrong"),
    ],
)
def test_frozen_gate_rejects_identity_or_destination_override(tmp_path, field, value):
    from app.simulation.openttd.proof.preflight import validate_native_inputs

    prepared = make_prepared(tmp_path)
    try:
        meta = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        meta[field] = value
        (prepared.directory / "PRELAUNCH.json").write_text(json.dumps(meta))
        with pytest.raises(ValueError):
            validate_native_inputs(prepared)
    finally:
        prepared.dispose()


@pytest.mark.parametrize(
    "marker", ["CARGO_PAGE_READ", "BRIDGE_RESPONSE_SENT", "BRIDGE_POST_RESPONSE_ALIVE"]
)
def test_missing_native_marker_cannot_pass(marker):
    from app.simulation.openttd.proof.cargo_page_evidence import parse_page_proof_evidence

    response, raw = native_page(request_id=PAGE_REQUEST.request_id)
    raw = b"".join(line for line in raw.splitlines(keepends=True) if marker.encode() not in line)
    with pytest.raises(ValueError):
        parse_page_proof_evidence(raw, PAGE_REQUEST.request_id).correlate(
            PAGE_REQUEST, response.to_bytes()
        )


@pytest.mark.parametrize(
    "change",
    [
        {"request_id": "wrong"},
        {"type": "industry_cargo_result"},
        {"type": "ack"},
        {"type": "world_info_result"},
        {"type": "industry_page_result"},
        {
            "cargoes": [
                {"id": 64, "label": "434F414C", "freight": True, "town_effect": 0, "classes": 1}
            ]
        },
        {"cargoes": [{"id": 0, "label": "bad", "freight": True, "town_effect": 0, "classes": 1}]},
        {"cargoes": [{"id": 0, "label": "434F414C", "freight": 1, "town_effect": 0, "classes": 1}]},
        {
            "cargoes": [
                {"id": 0, "label": "434F414C", "freight": True, "town_effect": 6, "classes": 1}
            ]
        },
    ],
)
def test_receipt_alone_cannot_satisfy_semantics(tmp_path, change):
    response, _ = native_page(request_id=PAGE_REQUEST.request_id)
    obj = json.loads(response.to_bytes())
    obj.update(change)
    raw = json.dumps(obj).encode()
    with pytest.raises(ValueError):
        receipt = CargoPageReceipt.correlate_transport(PAGE_REQUEST.to_bytes(), raw)
        verify_cargo_page(
            PAGE_REQUEST,
            raw,
            receipt,
            runtime=RuntimeIdentity(tmp_path / "binary", "15.3", "f" * 64),
            bridge=BridgePackage(tmp_path, "f" * 64),
        )


def test_empty_generic_valid_but_metadata_proof_incomplete(tmp_path):
    response, _ = native_page((), request_id=PAGE_REQUEST.request_id)
    raw = response.to_bytes()
    receipt = CargoPageReceipt.correlate(PAGE_REQUEST.to_bytes(), raw)
    verification = verify_cargo_page(
        PAGE_REQUEST,
        raw,
        receipt,
        runtime=RuntimeIdentity(tmp_path / "binary", "15.3", "f" * 64),
        bridge=BridgePackage(tmp_path, "f" * 64),
    )
    assert not verification.verified and not verification.active_metadata_observed


def test_lineage_kind_isolation_and_unknown_failure(tmp_path):
    from app.simulation.openttd.proof.cargo_page_lineage import capture_lineage, validate_lineage

    directory = tmp_path / "prelaunch"
    directory.mkdir()
    destination = tmp_path / PAGE_ATTEMPT_DIRECTORY
    unrelated = (
        tmp_path / "openttd-15.3-industry-capability-enrichment-real-prelaunch-v3-gate-failure"
    )
    unrelated.mkdir()
    lineage = capture_lineage(directory, 1, destination)
    assert lineage["proof_kind"] == "cargo-page" and lineage["supersedes_prelaunch_attempts"] == []
    failure = tmp_path / "openttd-15.3-cargo-page-real-prelaunch-gate-failure"
    failure.mkdir()
    with pytest.raises(ValueError):
        validate_lineage(directory, lineage, 1, destination)


class ControlledPageBackend(ControlledIndustryBackend):
    async def cargo_page(self, request):
        self.sent += 1
        response, raw = native_page(
            () if self.case == "empty" else (63, 0, 9), request_id=request.request_id
        )
        if self.case in ("read", "send", "alive"):
            marker = {
                "read": "CARGO_PAGE_READ",
                "send": "BRIDGE_RESPONSE_SENT",
                "alive": "BRIDGE_POST_RESPONSE_ALIVE",
            }[self.case].encode()
            raw = b"".join(line for line in raw.splitlines(keepends=True) if marker not in line)
        self.prepared.spec.stderr_path.write_bytes(raw)
        self.raw_response = response.to_bytes()
        if self.case == "semantic":
            self.raw_response = self.raw_response.replace(b'"freight":false', b'"freight":1')
        self.receipt = CargoPageReceipt.correlate_transport(request.to_bytes(), self.raw_response)
        self.events = list(PAGE_NETWORK_CHAIN)
        return CargoPageExchange(
            request.to_bytes(), self.raw_response, self.receipt, PAGE_NETWORK_CHAIN
        )

    async def wait_cargo(self, prepared, *, complete):
        from app.simulation.openttd.proof.cargo_page_evidence import parse_page_proof_evidence

        return parse_page_proof_evidence(
            prepared.spec.stderr_path.read_bytes(), PAGE_REQUEST.request_id
        )

    def cargo_network_evidence(self):
        return self.industry_network_evidence()

    def cargo_response_payload(self):
        return self.raw_response

    def cargo_receipt(self):
        return self.receipt


@pytest.mark.parametrize("case", ["ok", "empty", "read", "send", "alive", "semantic"])
def test_controlled_owned_lifecycle_retains_failure_and_cleans(tmp_path, case):
    from app.simulation.openttd.proof.cargo_page_attempt import execute_page_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledPageBackend(case)
    result = asyncio.run(execute_page_attempt(prepared, backend))
    assert result["status"] == ("CONTROLLED_SUCCESS" if case == "ok" else "CONTROLLED_FAILED")
    assert backend.launches == backend.connected == backend.sent == backend.closed == 1
    assert result["source_integrity"] and not prepared.key_path.exists()
    attempt = prepared.directory.with_name(PAGE_ATTEMPT_DIRECTORY)
    assert (attempt / "proof-attempt.json").exists() and result["reconnects"] == result[
        "retries"
    ] == 0
    with pytest.raises(ValueError):
        asyncio.run(execute_page_attempt(prepared, backend))


def test_lineage_acknowledged_prelaunch_requires_new_revision(tmp_path):
    from app.simulation.openttd.proof.cargo_page_lineage import capture_lineage, validate_lineage
    from app.simulation.openttd.proof.world_attempt import record_prelaunch_failure

    prepared = make_prepared(tmp_path)
    try:
        record_prelaunch_failure(prepared.directory, ValueError("controlled failure"))
        nextdir = tmp_path / "prelaunch-v2"
        nextdir.mkdir()
        value = capture_lineage(
            nextdir, PAGE_REVISION + 1, nextdir.with_name(PAGE_ATTEMPT_DIRECTORY)
        )
        assert len(value["supersedes_prelaunch_attempts"]) == 1
        assert value["supersedes_prelaunch_attempts"][0]["classification"] == "PRELAUNCH"
        assert (
            validate_lineage(
                nextdir, value, PAGE_REVISION + 1, nextdir.with_name(PAGE_ATTEMPT_DIRECTORY)
            )
            == 1
        )
        with pytest.raises(ValueError):
            capture_lineage(nextdir, PAGE_REVISION, nextdir.with_name(PAGE_ATTEMPT_DIRECTORY))
    finally:
        prepared.dispose()


def test_recorded_native_adapter_correlates_single_page_without_retry():
    from unittest.mock import AsyncMock

    from app.simulation.openttd.admin_protocol import encode_admin_frame
    from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
    from app.simulation.openttd.proof.cargo_page_native import CargoPageRecordedSession

    async def run():
        response, _ = native_page(request_id=PAGE_REQUEST.request_id)
        assert response is not None
        raw = response.to_bytes()
        session = Mock(
            reader=asyncio.StreamReader(),
            _writer=Mock(),
            send=AsyncMock(),
            receive=AsyncMock(return_value=encode_admin_frame(SERVER_GAMESCRIPT, raw + b"\0")),
        )
        recorded = CargoPageRecordedSession(session)
        query = encode_gamescript(PAGE_REQUEST.to_bytes())
        await recorded.send(query)
        await recorded.receive()
        assert recorded.events == list(PAGE_NETWORK_CHAIN[:3])
        assert recorded.receipt == CargoPageReceipt.correlate(PAGE_REQUEST.to_bytes(), raw)
        with pytest.raises(ValueError):
            await recorded.send(query)
        with pytest.raises(ValueError):
            await recorded.receive()
        assert recorded.sent == 1

    asyncio.run(run())


def test_proof_specific_serializer_bound():
    from app.simulation.openttd.cargo_catalog import CargoCatalogRecord
    from app.simulation.openttd.cargo_page import CargoPageResponse

    records = tuple(CargoCatalogRecord(i, "FFFFFFFF", False, 5, 32767) for i in (62, 63))
    raw = CargoPageResponse(PAGE_REQUEST.request_id, records, None, False).to_bytes()
    assert len(raw) == page_contract()["response_bound"] == 299
    assert 512 - len(raw) == 213


# These historical modes retain their pre-production bridge safety contract.
pytestmark = pytest.mark.usefixtures("checkpoint_structural_bridge")
