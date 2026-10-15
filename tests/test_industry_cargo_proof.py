"""Controlled production cargo proof preparation; never a native gameplay launch."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_industry_page_proof import ControlledIndustryBackend

from app.simulation.openttd.industry_cargo import (
    CARGO_NETWORK_SEQUENCE,
    IndustryCargoCapability,
    IndustryCargoExchange,
    IndustryCargoReceipt,
    IndustryCargoResponse,
)
from app.simulation.openttd.proof.cargo_contract import CARGO_REQUEST, cargo_contract
from app.simulation.openttd.proof.cargo_verification import verify_industry_cargo


def test_canonical_frozen_request():
    raw = CARGO_REQUEST.to_bytes()
    assert (
        raw == b'{"industry_id":0,"protocol":1,"request_id":"openttd15-industry-cargo-001",'
        b'"type":"industry_cargo"}'
    )
    assert len(raw) == 98
    assert CARGO_REQUEST.industry_id == 0
    assert (
        hashlib.sha256(raw).hexdigest()
        == "64e228cdf2a3a9b696de1d959ae34b46721518192ca3f5af67e051ecded43e63"
    )


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
            mode="industry-cargo",
            binary=binary,
            binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            graphics=archive,
            graphics_sha256=digest,
        )


def test_public_cli_mode(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    from app.simulation.openttd.proof import __main__ as cli

    prepare = Mock(return_value=SimpleNamespace(directory=tmp_path))
    monkeypatch.setattr(cli, "prepare_proof", prepare)
    monkeypatch.setattr(
        sys, "argv", ["proof", "prepare", "--mode", "industry-cargo", "--directory", str(tmp_path)]
    )
    cli.main()
    prepare.assert_called_once_with(tmp_path, mode="industry-cargo")


@pytest.mark.parametrize("produces,accepts", [((), ()), ((2,), ()), ((), (8,)), ((2, 63), (2, 8))])
def test_verification_including_empty_and_overlap(tmp_path, produces, accepts):
    from app.simulation.openttd.gamescript_bridge import BridgePackage
    from app.simulation.openttd.runtime.identity import RuntimeIdentity

    raw = IndustryCargoResponse(
        CARGO_REQUEST.request_id, IndustryCargoCapability(0, produces, accepts)
    ).to_bytes()
    receipt = IndustryCargoReceipt.correlate(CARGO_REQUEST.to_bytes(), raw)
    result = verify_industry_cargo(
        CARGO_REQUEST,
        raw,
        receipt,
        runtime=RuntimeIdentity(tmp_path / "binary", "15.3", "f" * 64),
        bridge=BridgePackage(tmp_path, "f" * 64),
    )
    assert result.verified and result.independent_second_source_capability is None
    assert result.produced_ids == produces and result.accepted_ids == accepts


@pytest.mark.parametrize(
    "change",
    [
        {"produces": [2, 1]},
        {"accepts": [8, 0]},
        {"produces": [1, 1]},
        {"accepts": [1, 1]},
        {"produces": [-1]},
        {"accepts": [64]},
        {"industry_id": 1},
        {"request_id": "wrong"},
        {"type": "ack"},
        {"type": "world_info_result"},
        {"type": "industry_page_result"},
        {"protocol": 2},
        {"status": "failed"},
    ],
)
def test_bad_response_rejected(change):
    obj = json.loads(
        IndustryCargoResponse(
            CARGO_REQUEST.request_id, IndustryCargoCapability(0, (), ())
        ).to_bytes()
    )
    obj.update(change)
    with pytest.raises(ValueError):
        IndustryCargoReceipt.correlate(CARGO_REQUEST.to_bytes(), json.dumps(obj).encode())


def test_payload_over_bound_rejected():
    with pytest.raises(ValueError):
        IndustryCargoResponse.parse(b" " * 513)


def test_authorization_and_failure_contract():
    contract = cargo_contract()
    assert contract["industry_id"] == 0
    assert contract["success"]["requests"] == 1
    assert contract["success"]["retries"] == contract["success"]["reconnects"] == 0
    assert contract["independent_second_source_capability"] is None
    assert (
        contract["empty_capability_policy"]
        == "valid native query proof; no non-empty cargo expectation"
    )


def cargo_native_fixture(produces=(2, 63), accepts=(2, 8)):
    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(Path("tests/fixtures/industry_cargo_api_15.nut").read_text())
    vm.execute(
        f"::valid_industries=[0]; ::produced_ids={list(produces)}; ::accepted_ids={list(accepts)};"
    )
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="industry_cargo",'
        'request_id="openttd15-industry-cargo-001",industry_id=0}));'
        " ::bridge <- NoMutationBridge(); try { bridge.Start(); }"
        ' catch(e) { if(e!="CONTROLLED_STOP") throw e; }'
    )
    root = vm.get_roottable()
    raw = "".join(
        "dbg: [script:4] [18] [I] " + str(line) + "\n" for line in root["markers"]
    ).encode()
    return IndustryCargoResponse(
        CARGO_REQUEST.request_id,
        IndustryCargoCapability(0, tuple(sorted(produces)), tuple(sorted(accepts))),
    ).to_bytes(), raw


@pytest.mark.parametrize(
    "missing",
    ["INDUSTRY_CARGO_READ", "BRIDGE_RESPONSE_SENT", "BRIDGE_POST_RESPONSE_ALIVE", "BRIDGE_STARTED"],
)
def test_missing_native_evidence_fails(missing):
    from app.simulation.openttd.proof.cargo_evidence import parse_cargo_proof_evidence

    response, raw = cargo_native_fixture()
    raw = b"".join(line for line in raw.splitlines(keepends=True) if missing.encode() not in line)
    with pytest.raises(ValueError):
        parse_cargo_proof_evidence(raw, CARGO_REQUEST.request_id).correlate(CARGO_REQUEST, response)


def test_native_metadata_and_digest_correlation():
    from dataclasses import replace

    from app.simulation.openttd.proof.cargo_evidence import parse_cargo_proof_evidence

    response, raw = cargo_native_fixture((), ())
    assert b"first_produced=null last_produced=null" in raw
    assert b"first_accepted=null last_accepted=null" in raw
    assert b"0x" not in raw
    evidence = parse_cargo_proof_evidence(raw, CARGO_REQUEST.request_id).correlate(
        CARGO_REQUEST, response
    )
    assert evidence.ordered_sequence == tuple(cargo_contract()["internal_chain"])
    assert evidence.response_digest == hashlib.sha256(response).hexdigest()
    with pytest.raises(ValueError):
        replace(evidence, response_digest="f" * 64).correlate(CARGO_REQUEST, response)


def test_guarded_public_cli_preflight(monkeypatch, tmp_path, capsys):
    from app.simulation.openttd.proof import __main__ as cli
    from app.simulation.openttd.proof.harness import EndpointReservation

    prepared = make_prepared(tmp_path)
    guards = []
    create = Mock(side_effect=AssertionError("no process in dry run"))
    connect = Mock(side_effect=AssertionError("no Admin in dry run"))
    monkeypatch.setattr("subprocess.Popen", create)
    monkeypatch.setattr("socket.socket.connect", connect)
    monkeypatch.setattr(sys, "addaudithook", guards.append)
    backend = Mock()
    monkeypatch.setattr(cli, "load_prepared", lambda directory, mode: prepared)
    monkeypatch.setattr(cli, "CargoNativeBackend", lambda **kwargs: backend)
    reserve = EndpointReservation.allocate
    calls = []

    def allocate(*ports):
        calls.append(ports)
        return reserve(*ports)

    monkeypatch.setattr(EndpointReservation, "allocate", allocate)
    monkeypatch.setattr(
        sys,
        "argv",
        ["proof", "preflight", "--mode", "industry-cargo", "--directory", str(prepared.directory)],
    )
    try:
        cli.main()
        result = json.loads(capsys.readouterr().out)
        assert result["state"] == "READY_TO_LAUNCH" and result["process_creation_blocked"]
        assert result["launches"] == result["connections"] == result["requests"] == 0
        assert result["cargo_contract"] == cargo_contract() and result["validator_loaded"]
        assert result["canonical_evidence_policy_loaded"]
        assert calls == [prepared.endpoints]
        create.assert_not_called()
        connect.assert_not_called()
        for event in ("subprocess.Popen", "socket.connect"):
            with pytest.raises(PermissionError):
                guards[0](event, ())
        assert not Path(result["evidence_destination"]).exists()
    finally:
        prepared.dispose()


class ControlledCargoBackend(ControlledIndustryBackend):
    async def industry_cargo(self, request):
        self.sent += 1
        self.raw_response, raw = (
            cargo_native_fixture((), ()) if self.case == "empty" else cargo_native_fixture()
        )
        if self.case in ("read", "send", "alive"):
            marker = {
                "read": "INDUSTRY_CARGO_READ",
                "send": "BRIDGE_RESPONSE_SENT",
                "alive": "BRIDGE_POST_RESPONSE_ALIVE",
            }[self.case].encode()
            raw = b"".join(line for line in raw.splitlines(keepends=True) if marker not in line)
        self.prepared.spec.stderr_path.write_bytes(raw)
        self.events = list(CARGO_NETWORK_SEQUENCE)
        if self.case == "semantic":
            self.raw_response = self.raw_response.replace(
                b'"produces":[2,63]', b'"produces":[63,2]'
            )
        self.receipt = IndustryCargoReceipt.correlate_transport(
            request.to_bytes(), self.raw_response
        )
        return IndustryCargoExchange(
            request.to_bytes(), self.raw_response, self.receipt, CARGO_NETWORK_SEQUENCE
        )

    async def wait_cargo(self, prepared, *, complete):
        from app.simulation.openttd.proof.cargo_evidence import parse_cargo_proof_evidence

        return parse_cargo_proof_evidence(
            prepared.spec.stderr_path.read_bytes(), CARGO_REQUEST.request_id
        )

    def cargo_network_evidence(self):
        return self.industry_network_evidence()

    def cargo_response_payload(self):
        return self.raw_response

    def cargo_receipt(self):
        return self.receipt


@pytest.mark.parametrize("case", ["ok", "empty", "read", "send", "alive", "semantic"])
def test_controlled_production_lifecycle(tmp_path, case):
    from app.simulation.openttd.proof.cargo_attempt import execute_cargo_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledCargoBackend(case)
    result = asyncio.run(execute_cargo_attempt(prepared, backend))
    assert (backend.launches, backend.connected, backend.sent, backend.closed) == (1, 1, 1, 1)
    assert result["status"] == (
        "CONTROLLED_SUCCESS" if case in ("ok", "empty") else "CONTROLLED_FAILED"
    )
    if case in ("ok", "empty"):
        assert result["verification"]["verified"] and result["states"][-1] == "COMPLETED"
        assert result["source_integrity"]
    if case == "semantic":
        assert result["transport_verified"] and "CAPABILITY_VALIDATED" not in result["states"]
    assert not prepared.key_path.exists()
    with pytest.raises(ValueError, match="claimed"):
        asyncio.run(execute_cargo_attempt(prepared, backend))


def test_freeze_key_bridge_and_authority(tmp_path):
    from app.simulation.openttd.proof.cargo_contract import (
        CARGO_BRIDGE_DIGEST,
        cargo_contract_digest,
    )
    from app.simulation.openttd.proof.harness import source_freeze

    prepared = make_prepared(tmp_path)
    try:
        assert source_freeze() == source_freeze()
        frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
        for path, digest in frozen.items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        assert str(prepared.key_path) not in frozen
        assert prepared.key_path.stat().st_mode & 0o777 == 0o600
        secret = prepared.key_path.read_bytes()
        assert all(
            secret not in p.read_bytes() and secret.hex().encode() not in p.read_bytes()
            for p in prepared.directory.iterdir()
            if p.is_file()
        )
        bridge = json.loads((prepared.directory / "bridge-package-identity.json").read_text())
        assert bridge["sha256"] == CARGO_BRIDGE_DIGEST
        assert bridge["commands"] == ["ping", "world_info", "industry_page", "industry_cargo"]
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert metadata["proof_config_sha256"] == cargo_contract_digest()
        authority = json.loads((prepared.directory / "source-authority.json").read_text())
        assert any("script_cargolist.hpp" in p for p in authority["files"])
        assert not Path(metadata["attempt_directory"]).exists()
    finally:
        prepared.dispose()


@pytest.mark.parametrize("field", ["request_sha256", "response_sha256"])
def test_network_digest_failure(tmp_path, field, monkeypatch):
    from app.simulation.openttd.proof.cargo_attempt import execute_cargo_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledCargoBackend()
    original = backend.cargo_network_evidence
    monkeypatch.setattr(
        backend, "cargo_network_evidence", lambda: dict(original(), **{field: "f" * 64})
    )
    result = asyncio.run(execute_cargo_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED" and "digest-bound" in result["error"]


@pytest.mark.parametrize(
    "event",
    [
        "INDUSTRY_CARGO_REQUEST_SENT",
        "INDUSTRY_CARGO_RESPONSE_RECEIVED",
        "TRANSPORT_RECEIPT_CREATED",
        "CAPABILITY_VALIDATED",
    ],
)
def test_python_chain_failure(tmp_path, event, monkeypatch):
    from app.simulation.openttd.proof.cargo_attempt import execute_cargo_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledCargoBackend()
    original = backend.cargo_network_evidence
    monkeypatch.setattr(
        backend,
        "cargo_network_evidence",
        lambda: dict(
            original(), ordered_sequence=[e for e in CARGO_NETWORK_SEQUENCE if e != event]
        ),
    )
    assert asyncio.run(execute_cargo_attempt(prepared, backend))["status"] == "CONTROLLED_FAILED"


def test_recorded_transport_retains_receipt_before_semantic_validation():
    from unittest.mock import AsyncMock

    from app.simulation.openttd.admin_protocol import encode_admin_frame
    from app.simulation.openttd.gamescript_transport import (
        SERVER_GAMESCRIPT,
        encode_gamescript,
    )
    from app.simulation.openttd.proof.cargo_native import CargoRecordedSession

    async def run():
        query = encode_gamescript(CARGO_REQUEST.to_bytes())
        obj = json.loads(
            IndustryCargoResponse(
                CARGO_REQUEST.request_id, IndustryCargoCapability(0, (), ())
            ).to_bytes()
        )
        obj["produces"] = [63, 2]
        raw = json.dumps(obj, separators=(",", ":")).encode()
        session = Mock(
            reader=asyncio.StreamReader(),
            _writer=Mock(),
            send=AsyncMock(),
            receive=AsyncMock(return_value=encode_admin_frame(SERVER_GAMESCRIPT, raw + b"\0")),
        )
        recorded = CargoRecordedSession(session)
        await recorded.send(query)
        await recorded.receive()
        assert recorded.events == list(CARGO_NETWORK_SEQUENCE[:3])
        assert recorded.receipt is not None
        assert recorded.receipt.response_payload_sha256 == hashlib.sha256(raw).hexdigest()
        with pytest.raises(ValueError):
            IndustryCargoResponse.parse(raw)
        with pytest.raises(ValueError):
            await recorded.receive()
        assert recorded.sent == 1
        with pytest.raises(ValueError):
            await recorded.send(query)

    asyncio.run(run())


def test_post_cleanup_copy_failure_is_failed_and_retained(tmp_path, monkeypatch):
    from app.simulation.openttd.proof import cargo_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledCargoBackend()
    original = cargo_attempt.shutil.copyfile

    def copy(source, target, *args, **kwargs):
        if Path(target).name == "stdout.log":
            raise OSError("controlled log copy failure")
        return original(source, target, *args, **kwargs)

    monkeypatch.setattr(cargo_attempt.shutil, "copyfile", copy)
    result = asyncio.run(cargo_attempt.execute_cargo_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED" and result["states"][-1] == "FAILED"
    assert "controlled log copy failure" in result["error"] and backend.closed == 1
    attempt = prepared.directory.with_name("openttd-15.3-industry-cargo-real-attempt1")
    assert (attempt / "proof-evidence.json").is_file() and (
        attempt / "inventory-provenance.json"
    ).is_file()
    assert not prepared.key_path.exists()


def test_native_no_resend_or_reconnect(monkeypatch):
    from unittest.mock import AsyncMock

    from app.simulation.openttd.proof.cargo_native import CargoNativeBackend
    from app.simulation.openttd.secure_admin import SecureAdminSession

    connect = AsyncMock(side_effect=AssertionError("no real connection"))
    monkeypatch.setattr(SecureAdminSession, "connect_secure", connect)
    backend = CargoNativeBackend(authorized_one_launch=True)
    backend._connection_claimed = True
    backend._sent = True

    async def run():
        with pytest.raises(ValueError, match="no auth retry"):
            await backend.authenticate(None, None)
        with pytest.raises(ValueError, match="no retry"):
            await backend.industry_cargo(CARGO_REQUEST)
        with pytest.raises(ValueError, match="No ping"):
            await backend.ping(None)

    asyncio.run(run())
    connect.assert_not_called()


def test_source_change_fails_before_controlled_launch(tmp_path):
    from app.simulation.openttd.proof.cargo_attempt import execute_cargo_attempt

    prepared = make_prepared(tmp_path)
    backend = ControlledCargoBackend()
    try:
        (prepared.directory / "request.json").write_bytes(b"changed")
        with pytest.raises(ValueError):
            asyncio.run(execute_cargo_attempt(prepared, backend))
        assert backend.launches == backend.connected == backend.sent == 0
        failure = prepared.directory.with_name(prepared.directory.name + "-gate-failure")
        assert failure.exists()
        with pytest.raises(ValueError, match="no retry"):
            asyncio.run(execute_cargo_attempt(prepared, backend))
    finally:
        prepared.dispose()


def test_mutation_and_dynamic_api_audit():
    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    source = (BRIDGE_DIRECTORY / "main.nut").read_text()
    # Capability remains structural even when a separate dynamic handler is present.
    handler = source.split("function IndustryCargo(", 1)[1].split("function ", 1)[0]
    for token in (
        "GetLastMonthProduction",
        "GetLastMonthTransported",
        "Stockpile",
        "IsCargoAccepted",
        "GSCompanyMode",
        "GSRoad",
        "GSRail",
        "GSStation",
        "GSVehicle",
        "GSOrder",
        "Terraform",
        "RCON",
    ):
        assert token not in handler
    for token in (
        "GSCargoList_IndustryProducing",
        "GSCargoList_IndustryAccepting",
        "GSList.SORT_ASCENDING",
        "GSCargo.IsValidCargo",
    ):
        assert token in source


def test_fresh_preparation_credentials(tmp_path):
    one = make_prepared(tmp_path / "one")
    two = make_prepared(tmp_path / "two")
    try:
        assert one.public_key != two.public_key
        assert one.key_path.read_bytes() != two.key_path.read_bytes()
        assert one.key_path.stat().st_mode & 0o777 == two.key_path.stat().st_mode & 0o777 == 0o600
    finally:
        one.dispose()
        two.dispose()
