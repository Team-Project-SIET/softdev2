"""Controlled production industry proof lifecycle; never native execution."""

import hashlib
import json

import pytest
from test_real_ack_graphics import graphics_archive

from app.simulation.openttd.proof.harness import prepare_proof


def make_industry_prepared(tmp_path):
    binary = tmp_path / "openttd"
    binary.write_bytes(b"controlled binary")
    binary.chmod(0o700)
    archive = tmp_path / "graphics.zip"
    digest = graphics_archive(archive)
    return prepare_proof(
        tmp_path / "industry-prelaunch",
        mode="industry-page",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=archive,
        graphics_sha256=digest,
    )


def test_industry_preparation_freezes_canonical_request_and_limit(tmp_path):
    prepared = make_industry_prepared(tmp_path)
    try:
        assert prepared.request.to_bytes() == (
            b'{"after_id":null,"limit":3,"protocol":1,"request_id":"openttd15-industry-page-001","type":"industry_page"}'
        )
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert metadata["mode"] == "industry-page"
        assert metadata["attempt"] == metadata["prelaunch_revision"] == 2
        assert metadata["attempt_directory"].endswith("openttd-15.3-industry-page-real-attempt2")
        assert metadata["request_sha256"] == hashlib.sha256(prepared.request.to_bytes()).hexdigest()
        assert not prepared.directory.with_name("openttd-15.3-industry-page-real-attempt2").exists()
    finally:
        prepared.dispose()


def test_industry_verification_separates_empty_transport_and_record_proof(tmp_path):
    from app.simulation.openttd.admin_protocol import ServerWelcome
    from app.simulation.openttd.gamescript_bridge import BridgePackage
    from app.simulation.openttd.industry_page import IndustryPageReceipt, IndustryPageResponse
    from app.simulation.openttd.proof.industry_contract import INDUSTRY_REQUEST
    from app.simulation.openttd.proof.industry_verification import verify_industry_page
    from app.simulation.openttd.runtime.identity import RuntimeIdentity

    response = IndustryPageResponse(INDUSTRY_REQUEST.request_id, (), None, False).to_bytes()
    receipt = IndustryPageReceipt.correlate(INDUSTRY_REQUEST.to_bytes(), response)
    welcome = ServerWelcome("Server", "15.3", True, "", 42, 0, 712223, 64, 64)
    verification = verify_industry_page(
        INDUSTRY_REQUEST,
        response,
        receipt,
        welcome,
        runtime=RuntimeIdentity(tmp_path / "binary", "15.3", "a" * 64),
        bridge=BridgePackage(tmp_path / "bridge", "b" * 64),
    )
    assert verification.page_valid
    assert not verification.verified
    assert verification.status == "EMPTY_PAGE_RECORD_PROOF_NOT_ESTABLISHED"


def test_public_cli_guarded_preflight_uses_supported_endpoint_path(tmp_path, monkeypatch, capsys):
    import socket
    import subprocess
    import sys

    from app.simulation.openttd.proof import __main__ as cli
    from app.simulation.openttd.proof import native
    from app.simulation.openttd.proof.harness import EndpointReservation

    prepared = make_industry_prepared(tmp_path)
    try:
        monkeypatch.setattr(native, "BINARY", prepared.spec.identity.executable)
        monkeypatch.setattr(native, "BINARY_SHA256", prepared.spec.identity.sha256)

        class ControlledBackend:
            def __init__(self, *, authorized_one_launch):
                assert authorized_one_launch

            def preflight(self, received):
                assert received.request == prepared.request

        monkeypatch.setattr(cli, "IndustryNativeBackend", ControlledBackend)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("No process"))
        monkeypatch.setattr(socket.socket, "connect", lambda *a, **kw: pytest.fail("No connection"))
        guards = []
        monkeypatch.setattr(sys, "addaudithook", guards.append)
        calls = []
        original = EndpointReservation.allocate

        def reserve(*ports):
            calls.append(ports)
            return original(*ports)

        monkeypatch.setattr(EndpointReservation, "allocate", reserve)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "proof",
                "preflight",
                "--mode",
                "industry-page",
                "--directory",
                str(prepared.directory),
            ],
        )
        cli.main()
        output = json.loads(capsys.readouterr().out)
        assert output["state"] == "READY_TO_LAUNCH"
        assert output["launches"] == output["connections"] == output["requests"] == 0
        assert output["welcome_bounds_validator_wired"] and output["validator_loaded"]
        assert output["canonical_evidence_policy_loaded"]
        assert output["request_id"] == "openttd15-industry-page-001"
        assert calls == [prepared.endpoints]
        assert len(guards) == 1
        for event in ("subprocess.Popen", "socket.connect"):
            with pytest.raises(PermissionError):
                guards[0](event, ())
        assert not prepared.directory.with_name("openttd-15.3-industry-page-real-attempt2").exists()
    finally:
        prepared.dispose()


class ControlledIndustryBackend:
    kind = "CONTROLLED"

    def __init__(self, case="ok"):
        from app.simulation.openttd.admin_protocol import ServerWelcome

        self.case = case
        self.launches = self.sent = self.closed = self.connected = 0
        self.welcome = ServerWelcome("Server", "15.3", True, "", 42, 0, 712223, 64, 64)
        self.raw_response = self.receipt = None
        self.events = []

    def preflight(self, prepared):
        pass

    async def launch(self, prepared):
        self.launches += 1
        prepared.spec.stdout_path.write_bytes(b"controlled stdout\n")
        prepared.spec.stderr_path.write_bytes(
            b"dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n"
        )
        self.prepared = prepared

    async def authenticate(self, prepared, gates):
        from dataclasses import asdict

        from app.simulation.openttd.proof.attempt import Gate

        self.connected += 1
        for gate in (
            Gate.ADMIN_CONNECTED,
            Gate.AUTHENTICATED,
            Gate.ENCRYPTION,
            Gate.PROTOCOL,
            Gate.WELCOME,
            Gate.IDENTITY,
        ):
            gates.advance(gate)
        return dict(
            auth=dict(method="X25519_AuthorizedKey", encrypted=True),
            protocol=dict(version=3),
            welcome=asdict(self.welcome),
        )

    async def subscribe(self):
        pass

    def health(self):
        pass

    async def industry_page(self, request):
        from dataclasses import replace

        from test_industry_page import squirrel_page

        from app.simulation.openttd.industry_page import (
            PAGE_NETWORK_SEQUENCE,
            IndustryPageExchange,
            IndustryPageReceipt,
        )

        self.sent += 1
        response, raw, _ = squirrel_page(ids=() if self.case == "empty" else (1, 2, 3, 4), limit=3)
        response = replace(response, request_id=request.request_id)
        raw = raw.replace(b"request_id=page", ("request_id=" + request.request_id).encode())
        if self.case == "bounds":
            row = replace(response.industries[0], x=64)
            response = replace(response, industries=(row,) + response.industries[1:])
        if self.case in ("read", "send", "alive"):
            marker = {
                "read": b"INDUSTRY_PAGE_READ",
                "send": b"BRIDGE_RESPONSE_SENT",
                "alive": b"BRIDGE_POST_RESPONSE_ALIVE",
            }[self.case]
            raw = b"".join(line for line in raw.splitlines(keepends=True) if marker not in line)
        self.prepared.spec.stderr_path.write_bytes(raw)
        self.raw_response = response.to_bytes()
        self.receipt = IndustryPageReceipt.correlate(request.to_bytes(), self.raw_response)
        self.events = list(PAGE_NETWORK_SEQUENCE)
        return IndustryPageExchange(
            request.to_bytes(), self.raw_response, self.receipt, PAGE_NETWORK_SEQUENCE
        )

    async def wait_industry(self, prepared, *, complete):
        from app.simulation.openttd.proof.industry_evidence import parse_industry_proof_evidence

        return parse_industry_proof_evidence(
            prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
        )

    def industry_network_evidence(self):
        return dict(
            ordered_sequence=self.events,
            requests_sent=self.sent,
            matching_responses=int(self.raw_response is not None),
            retries=0,
            request_sha256=hashlib.sha256(self.prepared.request.to_bytes()).hexdigest(),
            response_sha256=None
            if self.raw_response is None
            else hashlib.sha256(self.raw_response).hexdigest(),
        )

    def industry_response_payload(self):
        return self.raw_response

    def industry_receipt(self):
        return self.receipt

    async def cleanup(self, prepared):
        self.closed += 1
        return dict(
            reaped=True,
            remaining_processes=[],
            cleanup_error=[],
            graceful_attempted=True,
            returncode=0,
        )


@pytest.mark.parametrize("case", ["ok", "empty", "bounds", "read", "send", "alive"])
def test_single_controlled_lifecycle_and_frozen_failure_policy(tmp_path, case):
    import asyncio

    from app.simulation.openttd.proof.industry_attempt import execute_industry_attempt

    prepared = make_industry_prepared(tmp_path)
    backend = ControlledIndustryBackend(case)
    result = asyncio.run(execute_industry_attempt(prepared, backend))
    assert (backend.launches, backend.connected, backend.sent, backend.closed) == (1, 1, 1, 1)
    assert result["status"] == ("CONTROLLED_SUCCESS" if case == "ok" else "CONTROLLED_FAILED")
    attempt = prepared.directory.with_name("openttd-15.3-industry-page-real-attempt2")
    assert (attempt / "industry-page-response.json").is_file()
    assert (attempt / "transport-receipt.json").is_file()
    assert not prepared.key_path.exists()
    if case == "empty":
        assert result["transport_verified"]
        assert result["verification"]["page_valid"] and not result["verification"]["verified"]
    if case == "bounds":
        assert result["transport_verified"] and not result["verification"]["bounds_valid"]
        assert "PAGE_VALIDATED" not in result["states"]
    if case == "ok":
        assert result["verification"]["verified"]
        assert result["verification"]["independent_industry_inventory"] is None
        assert result["states"][-5:] == [
            "INDUSTRY_PAGE_RESPONSE_RECEIVED",
            "TRANSPORT_RECEIPT_CREATED",
            "PAGE_VALIDATED",
            "POST_RESPONSE_LIVENESS_VERIFIED",
            "COMPLETED",
        ]
    with pytest.raises(ValueError, match="claimed"):
        asyncio.run(execute_industry_attempt(prepared, backend))


@pytest.mark.parametrize(
    "change",
    [
        {"request_id": "unrelated"},
        {"type": "ack"},
        {"type": "world_info_result"},
        {"protocol": 2},
        {"status": "failed"},
        {"has_more": True, "next_after_id": None},
        {"next_after_id": -1},
        {
            "industries": [
                {"id": 2, "type": 1, "tile": 65, "x": 1, "y": 1},
                {"id": 2, "type": 1, "tile": 66, "x": 2, "y": 1},
            ]
        },
        {
            "industries": [
                {"id": 2, "type": 1, "tile": 65, "x": 1, "y": 1},
                {"id": 1, "type": 1, "tile": 66, "x": 2, "y": 1},
            ]
        },
    ],
)
def test_proof_protocol_rejects_wrong_correlation_and_malformed_records(change):
    from app.simulation.openttd.industry_page import (
        IndustryPageReceipt,
        IndustryPageResponse,
        IndustryRecord,
    )
    from app.simulation.openttd.proof.industry_contract import INDUSTRY_REQUEST

    obj = json.loads(
        IndustryPageResponse(
            INDUSTRY_REQUEST.request_id, (IndustryRecord(1, 12, 65, 1, 1),), None, False
        ).to_bytes()
    )
    obj.update(change)
    with pytest.raises(ValueError):
        IndustryPageReceipt.correlate(INDUSTRY_REQUEST.to_bytes(), json.dumps(obj).encode())


@pytest.mark.parametrize(
    "fields,bounds,coordinates",
    [
        ((1, 12, 65, 1, 1), True, True),
        ((1, 12, 128, 64, 1), False, True),
        ((1, 12, 4096, 0, 64), False, True),
        ((1, 12, 66, 1, 1), True, False),
    ],
)
def test_proof_record_semantics_use_independent_welcome_dimensions(
    tmp_path, fields, bounds, coordinates
):
    from app.simulation.openttd.admin_protocol import ServerWelcome
    from app.simulation.openttd.gamescript_bridge import BridgePackage
    from app.simulation.openttd.industry_page import (
        IndustryPageReceipt,
        IndustryPageResponse,
        IndustryRecord,
    )
    from app.simulation.openttd.proof.industry_contract import INDUSTRY_REQUEST
    from app.simulation.openttd.proof.industry_verification import verify_industry_page
    from app.simulation.openttd.runtime.identity import RuntimeIdentity

    payload = IndustryPageResponse(
        INDUSTRY_REQUEST.request_id, (IndustryRecord(*fields),), None, False
    ).to_bytes()
    receipt = IndustryPageReceipt.correlate(INDUSTRY_REQUEST.to_bytes(), payload)
    verification = verify_industry_page(
        INDUSTRY_REQUEST,
        payload,
        receipt,
        ServerWelcome("Server", "15.3", True, "", 42, 0, 712223, 64, 64),
        runtime=RuntimeIdentity(tmp_path / "binary", "15.3", "a" * 64),
        bridge=BridgePackage(tmp_path / "bridge", "b" * 64),
    )
    assert verification.bounds_valid is bounds
    assert verification.coordinates_valid is coordinates
    assert verification.verified is (bounds and coordinates)


def test_payload_and_protocol_limits_unchanged():
    from app.simulation.openttd.gamescript_protocol import MAX_PAYLOAD_BYTES
    from app.simulation.openttd.industry_page import IndustryPageReceipt, IndustryPageRequest
    from app.simulation.openttd.proof.industry_contract import INDUSTRY_REQUEST

    assert MAX_PAYLOAD_BYTES == 512
    assert IndustryPageRequest("max", None, 5).limit == 5
    assert INDUSTRY_REQUEST.limit == 3
    with pytest.raises(ValueError):
        IndustryPageReceipt.correlate(INDUSTRY_REQUEST.to_bytes(), b" " * 513)


def test_fresh_credential_source_input_freeze_and_bridge_identity(tmp_path):
    from app.simulation.openttd.proof.harness import source_freeze

    first = make_industry_prepared(tmp_path)
    try:
        key = first.key_path.read_bytes()
        assert first.key_path.stat().st_mode & 0o777 == 0o600
        freeze = json.loads((first.directory / "source-freeze.json").read_text())
        assert str(first.key_path) not in freeze
        assert source_freeze() == source_freeze()
        assert list(freeze) == sorted(freeze)
        for path, digest in freeze.items():
            from pathlib import Path

            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        identity = json.loads((first.directory / "bridge-package-identity.json").read_text())
        assert identity["commands"] == ["ping", "world_info", "industry_page"]
        assert identity["api"] == "15"
        for name, digest in identity["files"].items():
            assert (
                hashlib.sha256(
                    (first.spec.workspace.game / "NoMutationBridge" / name).read_bytes()
                ).hexdigest()
                == digest
            )
        for path in first.directory.iterdir():
            if path.is_file():
                assert key not in path.read_bytes() and key.hex().encode() not in path.read_bytes()
        another = tmp_path / "another"
        another.mkdir()
        second = make_industry_prepared(another)
        try:
            assert second.key_path.read_bytes() != key
            assert (
                json.loads((second.directory / "bridge-package-identity.json").read_text())[
                    "sha256"
                ]
                == identity["sha256"]
            )
            assert second.request.to_bytes() == first.request.to_bytes()
        finally:
            second.dispose()
    finally:
        first.dispose()


@pytest.mark.parametrize(
    "name",
    ["request.json", "industry-page-contract.json", "source-authority.json", "PRELAUNCH.json"],
)
def test_prelaunch_tampering_retains_zero_activity_failure(tmp_path, name):
    import asyncio

    from app.simulation.openttd.proof.industry_attempt import execute_industry_attempt

    prepared = make_industry_prepared(tmp_path)
    backend = ControlledIndustryBackend()
    try:
        path = prepared.directory / name
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(ValueError):
            asyncio.run(execute_industry_attempt(prepared, backend))
        assert (backend.launches, backend.connected, backend.sent) == (0, 0, 0)
        failure = prepared.directory.with_name(prepared.directory.name + "-gate-failure")
        assert json.loads((failure / "PRELAUNCH-FAILURE.json").read_text())["launches"] == 0
        assert not prepared.directory.with_name("openttd-15.3-industry-page-real-attempt2").exists()
    finally:
        prepared.dispose()


@pytest.mark.parametrize("second", ["duplicate", "ping", "world_info", "different_id"])
def test_native_recorded_session_enforces_exactly_one_request(second):
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.gamescript_protocol import PingRequest
    from app.simulation.openttd.gamescript_transport import GameScriptSession, encode_gamescript
    from app.simulation.openttd.industry_page import IndustryPageRequest
    from app.simulation.openttd.proof.industry_contract import INDUSTRY_REQUEST
    from app.simulation.openttd.proof.industry_native import IndustryRecordedSession
    from app.simulation.openttd.world_info import WorldInfoRequest

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        session = IndustryRecordedSession(GameScriptSession(reader, writer))
        await session.send(encode_gamescript(INDUSTRY_REQUEST.to_bytes()))
        query = {
            "duplicate": INDUSTRY_REQUEST,
            "ping": PingRequest("no"),
            "world_info": WorldInfoRequest("no"),
            "different_id": IndustryPageRequest("no", None, 3),
        }[second]
        with pytest.raises(ValueError):
            await session.send(encode_gamescript(query.to_bytes()))
        assert session.sent == 1
        assert writer.write.call_count == 1

    asyncio.run(scenario())


def test_recorded_duplicate_response_rejected():
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import encode_admin_frame
    from app.simulation.openttd.gamescript_transport import GameScriptSession, encode_gamescript
    from app.simulation.openttd.industry_page import IndustryPageResponse
    from app.simulation.openttd.proof.industry_contract import INDUSTRY_REQUEST
    from app.simulation.openttd.proof.industry_native import IndustryRecordedSession

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        session = IndustryRecordedSession(GameScriptSession(reader, writer))
        await session.send(encode_gamescript(INDUSTRY_REQUEST.to_bytes()))
        packet = encode_admin_frame(
            124,
            IndustryPageResponse(INDUSTRY_REQUEST.request_id, (), None, False).to_bytes() + b"\0",
        )
        reader.feed_data(packet + packet)
        with pytest.raises(ValueError, match="Duplicate"):
            await session.receive()
        assert session.responses == 2

    asyncio.run(scenario())


def test_owned_listener_readiness_never_connects():
    import os
    import socket

    from app.simulation.openttd.proof.industry_native import owned_admin_listener

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        assert owned_admin_listener(os.getpid(), listener.getsockname()[1])
        assert not owned_admin_listener(os.getpid(), 0)


def test_native_backend_makes_one_connection_and_rejects_auth_retry(tmp_path, monkeypatch):
    import asyncio
    from datetime import date
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_crypto import AuthorizedKey
    from app.simulation.openttd.admin_protocol import ServerProtocol, ServerWelcome
    from app.simulation.openttd.proof import industry_native
    from app.simulation.openttd.proof.attempt import Gate, Gates
    from app.simulation.openttd.secure_admin import AuthState

    prepared = make_industry_prepared(tmp_path)

    async def scenario():
        backend = industry_native.IndustryNativeBackend(authorized_one_launch=True)
        monkeypatch.setattr(backend, "process", SimpleNamespace(pid=123))
        backend._key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        monkeypatch.setattr(backend, "health", lambda: None)
        prepared.spec.stdout_path.write_text("Using the OpenGFX base graphics set\n")
        prepared.spec.stderr_path.write_text("")
        session = SimpleNamespace(
            reader=Mock(),
            _writer=Mock(),
            state=AuthState.ACTIVE,
            protocol=ServerProtocol(3, ((9, 64),)),
            welcome=ServerWelcome(
                "Server", "15.3", True, "", 42, 0, date(1950, 1, 1).toordinal() + 365, 64, 64
            ),
            authenticate=AsyncMock(),
        )
        connect = AsyncMock(return_value=session)
        monkeypatch.setattr(industry_native, "owned_admin_listener", lambda pid, port: True)
        monkeypatch.setattr(industry_native.SecureAdminSession, "connect_secure", connect)
        gates = Gates()
        gates.advance(Gate.PROCESS)
        result = await backend.authenticate(prepared, gates)
        assert result["auth"]["encrypted"]
        with pytest.raises(ValueError, match="One Admin connection"):
            await backend.authenticate(prepared, gates)
        assert connect.await_count == 1

    try:
        asyncio.run(scenario())
    finally:
        prepared.dispose()


def test_missing_startup_stops_before_query(tmp_path):
    import asyncio

    from app.simulation.openttd.proof.industry_attempt import execute_industry_attempt

    class NoStartup(ControlledIndustryBackend):
        async def launch(self, prepared):
            await super().launch(prepared)
            prepared.spec.stderr_path.write_bytes(b"")

    prepared = make_industry_prepared(tmp_path)
    backend = NoStartup()
    result = asyncio.run(execute_industry_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED"
    assert (backend.launches, backend.connected, backend.sent, backend.closed) == (1, 1, 0, 1)
    assert not prepared.key_path.exists()


def test_cleanup_failure_keeps_verified_page_from_passing(tmp_path):
    import asyncio

    from app.simulation.openttd.proof.industry_attempt import execute_industry_attempt

    class BadCleanup(ControlledIndustryBackend):
        async def cleanup(self, prepared):
            result = await super().cleanup(prepared)
            result["returncode"] = 1
            return result

    prepared = make_industry_prepared(tmp_path)
    result = asyncio.run(execute_industry_attempt(prepared, BadCleanup()))
    assert result["verification"]["verified"]
    assert result["status"] == "CONTROLLED_FAILED"
    assert not prepared.key_path.exists()


def test_public_industry_run_requires_separate_authorization():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "app.simulation.openttd.proof", "run", "--mode", "industry-page"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "one-launch authorization required" in result.stderr
    assert "invalid choice" not in result.stderr


@pytest.mark.parametrize("field", ["mode", "proof_model", "attempt_directory"])
def test_semantic_metadata_tampering_retains_prelaunch_failure(tmp_path, field):
    import asyncio

    from app.simulation.openttd.proof.industry_attempt import execute_industry_attempt

    prepared = make_industry_prepared(tmp_path)
    try:
        metadata_path = prepared.directory / "PRELAUNCH.json"
        value = json.loads(metadata_path.read_text())
        value[field] = "tampered"
        metadata_path.write_text(json.dumps(value))
        backend = ControlledIndustryBackend()
        with pytest.raises(ValueError):
            asyncio.run(execute_industry_attempt(prepared, backend))
        assert (backend.launches, backend.connected, backend.sent) == (0, 0, 0)
        assert (
            prepared.directory.with_name(prepared.directory.name + "-gate-failure")
            / "PRELAUNCH-FAILURE.json"
        ).is_file()
    finally:
        prepared.dispose()


@pytest.mark.parametrize(
    "name", ["transport-receipt.json", "network-evidence.json", "gamescript-proof-evidence.json"]
)
def test_evidence_write_failure_cannot_skip_cleanup(tmp_path, monkeypatch, name):
    import asyncio

    from app.simulation.openttd.proof import industry_attempt

    prepared = make_industry_prepared(tmp_path)
    backend = ControlledIndustryBackend()
    write = industry_attempt.write_json

    def fail_artifact(path, value):
        if path.name == name:
            raise OSError("controlled retention failure")
        return write(path, value)

    monkeypatch.setattr(industry_attempt, "write_json", fail_artifact)
    result = asyncio.run(industry_attempt.execute_industry_attempt(prepared, backend))
    assert result["status"] == "CONTROLLED_FAILED"
    assert backend.closed == 1
    assert not prepared.key_path.exists()
    assert "retention failure" in result["error"]


@pytest.mark.parametrize("field", ["request_sha256", "response_sha256"])
def test_channel_digest_must_bind_transport_receipt(tmp_path, field):
    import asyncio

    from app.simulation.openttd.proof.industry_attempt import execute_industry_attempt

    class BadDigest(ControlledIndustryBackend):
        def industry_network_evidence(self):
            value = super().industry_network_evidence()
            value[field] = "f" * 64
            return value

    prepared = make_industry_prepared(tmp_path)
    result = asyncio.run(execute_industry_attempt(prepared, BadDigest()))
    assert result["status"] == "CONTROLLED_FAILED"
    assert "digest-bound" in result["error"]


def test_prelaunch_failure_is_a_permanent_no_retry_gate(tmp_path):
    import asyncio

    from app.simulation.openttd.proof.industry_attempt import execute_industry_attempt

    prepared = make_industry_prepared(tmp_path)
    path = prepared.directory / "request.json"
    original = path.read_bytes()
    try:
        path.write_bytes(b"invalid")
        backend = ControlledIndustryBackend()
        with pytest.raises(ValueError):
            asyncio.run(execute_industry_attempt(prepared, backend))
        path.write_bytes(original)
        with pytest.raises(ValueError, match="no retry"):
            asyncio.run(execute_industry_attempt(prepared, backend))
        assert (backend.launches, backend.connected, backend.sent) == (0, 0, 0)
    finally:
        prepared.dispose()


def test_preparation_historical_paths_remain_byte_identical(tmp_path):
    history = {}
    for name in (
        "openttd-15.3-real-ack-attempt2",
        "openttd-15.3-world-info-real-attempt1",
        "previous-prelaunch-gate-failure",
    ):
        directory = tmp_path / name
        directory.mkdir()
        report = directory / "final-report.md"
        report.write_bytes(b"immutable controlled history\n")
        history[report] = hashlib.sha256(report.read_bytes()).hexdigest()
    prepared = make_industry_prepared(tmp_path)
    try:
        assert all(
            hashlib.sha256(path.read_bytes()).hexdigest() == digest
            for path, digest in history.items()
        )
    finally:
        prepared.dispose()
