"""Public world-info proof preparation and lifecycle contracts, controlled only."""

import hashlib
import json

import pytest
from test_real_ack_graphics import graphics_archive

from app.simulation.openttd.proof.harness import prepare_proof


def make_world_prepared(tmp_path):
    binary = tmp_path / "openttd"
    binary.write_bytes(b"controlled binary")
    binary.chmod(0o700)
    archive = tmp_path / "graphics.zip"
    graphics_digest = graphics_archive(archive)
    return prepare_proof(
        tmp_path / "world-prelaunch",
        mode="world-info",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=archive,
        graphics_sha256=graphics_digest,
    )


def test_world_preparation_freezes_separate_request_and_contract(tmp_path):
    prepared = make_world_prepared(tmp_path)
    try:
        assert (
            prepared.request.to_bytes()
            == b'{"protocol":1,"request_id":"openttd15-world-info-001","type":"world_info"}'
        )
        data = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert data["mode"] == "world-info"
        assert data["semantic_authority"] == "encrypted SERVER_WELCOME"
        assert data["request_size"] == 74
        assert data["attempt_directory"].endswith("openttd-15.3-world-info-real-attempt1")
        assert not (tmp_path / "openttd-15.3-world-info-real-attempt1").exists()
        assert prepared.key_path.stat().st_mode & 0o777 == 0o600
    finally:
        prepared.dispose()


def test_world_cli_preflight_is_public_and_guarded(tmp_path, monkeypatch, capsys):
    import socket
    import subprocess
    import sys

    import app.simulation.openttd.proof.native as native
    from app.simulation.openttd.proof import __main__ as cli

    prepared = make_world_prepared(tmp_path)
    monkeypatch.setattr(native, "BINARY", prepared.spec.identity.executable)
    monkeypatch.setattr(native, "BINARY_SHA256", prepared.spec.identity.sha256)
    monkeypatch.setattr(
        native,
        "ARCHIVE_SHA256",
        json.loads((prepared.directory / "graphics-identity.json").read_text())["archive_sha256"],
    )
    monkeypatch.setattr(sys, "addaudithook", lambda guard: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["proof", "preflight", "--mode", "world-info", "--directory", str(prepared.directory)],
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("No subprocess"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **kw: pytest.fail("No Admin"))
    before = {str(p): p.read_bytes() for p in prepared.directory.rglob("*") if p.is_file()}
    try:
        cli.main()
        result = json.loads(capsys.readouterr().out)
        assert result["state"] == "READY_TO_LAUNCH"
        assert result["request_id"] == "openttd15-world-info-001"
        assert result["endpoints_reserved"] == list(prepared.endpoints)
        assert result["launches"] == result["connections"] == result["requests"] == 0
        assert before == {
            str(p): p.read_bytes() for p in prepared.directory.rglob("*") if p.is_file()
        }
    finally:
        prepared.dispose()


class WorldControlledBackend:
    kind = "CONTROLLED"

    def __init__(self, case="ok"):
        self.case = case
        self.launches = self.sends = self.closed = 0

    def preflight(self, prepared):
        pass

    async def launch(self, prepared):
        self.launches += 1
        self.prepared = prepared
        prepared.spec.stdout_path.write_bytes(b"controlled stdout\n")
        prepared.spec.stderr_path.write_bytes(
            b"dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n"
        )

    async def authenticate(self, prepared, gates):
        from app.simulation.openttd.admin_protocol import ServerWelcome
        from app.simulation.openttd.proof.attempt import Gate

        for gate in list(Gate)[1:7]:
            gates.advance(gate)
        self.welcome = ServerWelcome(
            "controlled",
            "15.3",
            True,
            "map",
            42,
            0,
            712223,
            128 if self.case == "width" else 64,
            128 if self.case == "height" else 64,
        )
        from dataclasses import asdict

        return {
            "auth": {"method": "controlled"},
            "welcome": asdict(self.welcome),
            "protocol": {"version": 3},
        }

    async def subscribe(self):
        pass

    async def world_info(self, request):
        from app.simulation.openttd.world_info import (
            NETWORK_SEQUENCE,
            WorldInfoExchange,
            WorldInfoReceipt,
            WorldInfoResponse,
        )

        self.sends += 1
        response = WorldInfoResponse(
            "wrong" if self.case == "id" else request.request_id, 64, 64
        ).to_bytes()
        markers = [
            f"BRIDGE_REQUEST_RECEIVED request_id={request.request_id} type=world_info protocol=1",
            f"WORLD_INFO_READ request_id={request.request_id} map_width=64 map_height=64",
            f"BRIDGE_RESPONSE_SENT request_id={request.request_id} "
            "type=world_info_result status=ok protocol=1",
            f"BRIDGE_POST_RESPONSE_ALIVE request_id={request.request_id}",
        ]
        with self.prepared.spec.stderr_path.open("ab") as stream:
            for marker in markers:
                if marker.split()[0] != self.case:
                    stream.write(f"dbg: [script:4] [18] [I] {marker}\n".encode())
        return WorldInfoExchange(
            request.to_bytes(),
            response,
            WorldInfoReceipt.correlate(request.to_bytes(), response),
            NETWORK_SEQUENCE,
            2 if self.case == "second" else 1,
            2 if self.case == "duplicate" else 1,
            1 if self.case == "retry" else 0,
        )

    async def wait_world(self, prepared, *, complete):
        from app.simulation.openttd.world_info_evidence import parse_world_info_evidence

        return parse_world_info_evidence(
            prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
        )

    def health(self):
        pass

    async def cleanup(self, prepared):
        self.closed += 1
        attempt = prepared.directory.with_name("openttd-15.3-world-info-real-attempt1")
        assert (attempt / "gamescript-supporting.log").exists(), "Evidence must precede cleanup"
        return {
            "reaped": True,
            "remaining_processes": [],
            "graceful_attempted": True,
            "returncode": 0,
            "cleanup_error": [],
        }


@pytest.mark.parametrize(
    "case",
    [
        "ok",
        "width",
        "height",
        "id",
        "WORLD_INFO_READ",
        "BRIDGE_RESPONSE_SENT",
        "BRIDGE_POST_RESPONSE_ALIVE",
        "second",
        "duplicate",
        "retry",
    ],
)
def test_world_proof_lifecycle_conjunction_and_retention(tmp_path, case):
    import asyncio

    from app.simulation.openttd.proof.world_attempt import execute_world_attempt

    prepared = make_world_prepared(tmp_path)
    backend = WorldControlledBackend(case)
    result = asyncio.run(execute_world_attempt(prepared, backend))
    assert result["status"] == ("CONTROLLED_SUCCESS" if case == "ok" else "CONTROLLED_FAILED")
    assert backend.launches == backend.sends == backend.closed == 1
    assert not prepared.key_path.exists()
    attempt = tmp_path / "openttd-15.3-world-info-real-attempt1"
    assert (attempt / "gamescript-supporting.log").exists()
    assert (attempt / "artifact-manifest.sha256").exists()
    if case in ("ok", "width", "height"):
        verification = json.loads((attempt / "world-info-verification.json").read_text())
        assert verification["verified"] == (case == "ok")
        assert verification["width_match"] == (case != "width")
        assert verification["height_match"] == (case != "height")
        assert (attempt / "transport-receipt.json").exists()
        assert f"Semantic verification: {case == 'ok'}" in (attempt / "final-report.md").read_text()
    if case == "ok":
        assert result["states"] == [
            "PREPARED",
            "LAUNCHED",
            "ADMIN_ACTIVE",
            "WORLD_INFO_REQUEST_SENT",
            "WORLD_INFO_RESPONSE_RECEIVED",
            "SEMANTICALLY_VERIFIED",
            "POST_RESPONSE_LIVENESS_VERIFIED",
            "COMPLETED",
        ]
    with pytest.raises(ValueError):
        asyncio.run(execute_world_attempt(prepared, backend))
    assert backend.launches == 1


@pytest.mark.parametrize("timing", ["early", "late", "mismatch", "duplicate", "wrong_type"])
def test_production_world_backend_with_controlled_encrypted_peer(tmp_path, monkeypatch, timing):
    import asyncio
    import struct
    from pathlib import Path

    from squirrel import SQVM
    from test_real_ack_native import ControlledProcess, Peer
    from test_secure_admin import Writer

    import app.simulation.openttd.proof.native as native
    from app.simulation.openttd.admin_protocol import encode_admin_frame
    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY
    from app.simulation.openttd.gamescript_protocol import Ack
    from app.simulation.openttd.gamescript_transport import decode_gamescript
    from app.simulation.openttd.proof.world_attempt import execute_world_attempt
    from app.simulation.openttd.proof.world_native import WorldNativeBackend
    from app.simulation.openttd.secure_admin import SecureAdminSession

    prepared = make_world_prepared(tmp_path)
    monkeypatch.setattr(native, "BINARY", prepared.spec.identity.executable)
    monkeypatch.setattr(native, "BINARY_SHA256", prepared.spec.identity.sha256)
    monkeypatch.setattr(
        native,
        "ARCHIVE_SHA256",
        json.loads((prepared.directory / "graphics-identity.json").read_text())["archive_sha256"],
    )
    logs, processes, peers = [], [], []

    def popen(argv, **kwargs):
        logs.append(kwargs["stderr"])
        kwargs["stderr"].write(
            b"Using the OpenGFX base graphics set\n"
            b"dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n"
        )
        kwargs["stderr"].flush()
        process = ControlledProcess()
        processes.append(process)
        return process

    class WorldPeer(Peer):
        def write(self, frame):
            if self.in_cipher is None:
                return super().write(frame)
            assert self.out_cipher is not None
            Writer.write(self, frame)
            plain = self.in_cipher.decrypt(frame)
            if plain[2] == 2:
                self.subscribed = True
            elif plain[2] == 7:
                if timing == "late" and plain[3:] == struct.pack("<I", 0x154):
                    self.log.write(self.alive)
                    self.log.flush()
                self.reader.feed_data(self.out_cipher.encrypt(encode_admin_frame(126, plain[3:])))
            elif plain[2] == 6:
                assert self.subscribed
                self.requests += 1
                request = json.loads(decode_gamescript(plain[3:]))
                assert request == {
                    "protocol": 1,
                    "type": "world_info",
                    "request_id": "openttd15-world-info-001",
                }
                vm = SQVM()
                vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
                width = 128 if timing == "mismatch" else 64
                vm.execute(
                    f"class GSMap {{ static function GetMapSizeX() {{ return {width}; }} "
                    "static function GetMapSizeY() { return 64; } }"
                )
                vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
                vm.execute(
                    '::events.append(ControlledAdminEvent({protocol=1,type="world_info",'
                    'request_id="openttd15-world-info-001"})); '
                    "::bridge <- NoMutationBridge(); try { bridge.Start(); } "
                    'catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
                )
                root = vm.get_roottable()
                self.alive = b""
                for marker in list(root["markers"])[1:]:
                    line = f"dbg: [script:4] [18] [I] {marker}\n".encode()
                    if str(marker).startswith("BRIDGE_POST_RESPONSE_ALIVE"):
                        self.alive = line
                        if timing == "late":
                            continue
                    self.log.write(line)
                self.log.flush()
                reply = root["replies"][0]
                fields = {
                    "protocol": int(reply["protocol"]),
                    "request_id": str(reply["request_id"]),
                    "type": str(reply["type"]),
                    "status": str(reply["status"]),
                    "map_width": int(reply["map_width"]),
                    "map_height": int(reply["map_height"]),
                }
                payload = (
                    Ack(request["request_id"]).to_bytes()
                    if timing == "wrong_type"
                    else json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
                )
                packet = encode_admin_frame(124, payload + b"\0")
                self.reader.feed_data(self.out_cipher.encrypt(packet))
                if timing == "duplicate":
                    self.reader.feed_data(self.out_cipher.encrypt(packet))

    async def connect(cls, host, port, timeout, *, key):
        reader = asyncio.StreamReader()
        peer = WorldPeer(reader, key, "success", logs[0])
        peers.append(peer)
        return SecureAdminSession(reader, peer, key=key)

    monkeypatch.setattr(native.subprocess, "Popen", popen)
    monkeypatch.setattr(SecureAdminSession, "connect_secure", classmethod(connect))
    backend = WorldNativeBackend(authorized_one_launch=True)
    backend.kind = "CONTROLLED"
    result = asyncio.run(execute_world_attempt(prepared, backend))
    assert result["status"] == (
        "CONTROLLED_SUCCESS" if timing in ("early", "late") else "CONTROLLED_FAILED"
    )
    assert len(processes) == len(peers) == peers[0].requests == 1
    assert processes[0].returncode == 0 and peers[0].closed
    assert not prepared.key_path.exists()


@pytest.mark.parametrize("case", ["busy", "source", "history"])
def test_world_prelaunch_failure_is_zero_activity_and_preserves_preparation(tmp_path, case):
    import asyncio
    import socket

    from app.simulation.openttd.proof.world_attempt import execute_world_attempt

    history = tmp_path / "openttd-15.3-real-ack-attempt2"
    history.mkdir()
    report = history / "final-report.md"
    report.write_bytes(b"PASSED historical ACK evidence")
    prepared = make_world_prepared(tmp_path)
    backend = WorldControlledBackend()
    busy = None
    if case == "busy":
        busy = socket.socket()
        busy.bind(("127.0.0.1", prepared.endpoints[1]))
    elif case == "source":
        prepared.spec.workspace.config.write_text("tampered")
    else:
        report.write_bytes(b"changed externally")
    before = {str(p): p.read_bytes() for p in prepared.directory.rglob("*") if p.is_file()}
    try:
        with pytest.raises((ValueError, OSError)):
            asyncio.run(execute_world_attempt(prepared, backend))
        assert backend.launches == backend.sends == backend.closed == 0
        assert not (tmp_path / "openttd-15.3-world-info-real-attempt1").exists()
        assert before == {
            str(p): p.read_bytes() for p in prepared.directory.rglob("*") if p.is_file()
        }
        failure = json.loads(
            (tmp_path / "world-prelaunch-gate-failure/PRELAUNCH-FAILURE.json").read_text()
        )
        assert failure["launches"] == failure["connections"] == failure["requests"] == 0
    finally:
        if busy:
            busy.close()
        prepared.dispose()


def test_world_freeze_redacts_credentials_and_keeps_history(tmp_path):
    from app.simulation.openttd.proof.harness import manifest, source_freeze

    history = tmp_path / "openttd-15.3-real-ack-attempt1"
    history.mkdir()
    report = history / "final-report.md"
    report.write_bytes(b"FAILED NO RETRY: historical")
    prepared = make_world_prepared(tmp_path)
    try:
        assert report.read_bytes() == b"FAILED NO RETRY: historical"
        secret = prepared.key_path.read_bytes()
        public = b"".join(p.read_bytes() for p in prepared.directory.iterdir() if p.is_file())
        assert secret not in public and secret.hex().encode() not in public
        frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
        for path, digest in source_freeze().items():
            assert frozen[path] == digest
        assert any(path.endswith("/proof/world_attempt.py") for path in frozen)
        assert any(path.endswith("/world_info_evidence.py") for path in frozen)
        assert (
            manifest(prepared.directory)
            == (prepared.directory / "artifact-manifest.sha256").read_text()
        )
        assert "admin_password = \n" in (prepared.spec.workspace.root / "secrets.cfg").read_text()
        assert "allow_insecure_admin_login = false" in prepared.spec.workspace.config.read_text()
    finally:
        prepared.dispose()


def test_public_world_cli_rejects_run_without_authorization(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.simulation.openttd.proof",
            "run",
            "--mode",
            "world-info",
            "--directory",
            str(tmp_path / "missing"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "one-launch authorization required" in result.stderr
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    "case",
    ["receipt_first", "response_first", "semantic_first", "duplicate", "retry", "second", "digest"],
)
def test_typed_python_chain_rejects_invalid_proof(case):
    from dataclasses import replace

    from app.simulation.openttd.proof.harness import WORLD_REQUEST
    from app.simulation.openttd.proof.world_attempt import WORLD_NETWORK_CHAIN, WorldPythonEvidence
    from app.simulation.openttd.world_info import (
        NETWORK_SEQUENCE,
        WorldInfoExchange,
        WorldInfoReceipt,
        WorldInfoResponse,
    )

    response = WorldInfoResponse(WORLD_REQUEST.request_id, 64, 64).to_bytes()
    receipt = WorldInfoReceipt.correlate(WORLD_REQUEST.to_bytes(), response)
    exchange = WorldInfoExchange(
        WORLD_REQUEST.to_bytes(), response, receipt, NETWORK_SEQUENCE, 1, 1, 0
    )
    evidence = WorldPythonEvidence(
        WORLD_NETWORK_CHAIN,
        receipt.request_payload_sha256,
        receipt.response_payload_sha256,
        1,
        1,
        0,
    )
    evidence.validate(exchange)
    sequence = list(WORLD_NETWORK_CHAIN)
    if case in ("receipt_first", "response_first", "semantic_first"):
        first = {"receipt_first": 2, "response_first": 1, "semantic_first": 3}[case]
        sequence[0], sequence[first] = sequence[first], sequence[0]
        broken = replace(evidence, ordered_sequence=tuple(sequence))
    elif case == "duplicate":
        broken = replace(evidence, matching_responses=2)
    elif case == "retry":
        broken = replace(evidence, retries=1)
    elif case == "second":
        broken = replace(evidence, requests_sent=2)
    else:
        broken = replace(evidence, response_sha256="0" * 64)
    with pytest.raises(ValueError):
        broken.validate(exchange)


def test_cleanup_failure_does_not_promote_semantic_success(tmp_path):
    import asyncio

    from app.simulation.openttd.proof.world_attempt import execute_world_attempt

    prepared = make_world_prepared(tmp_path)

    class CleanupFailure(WorldControlledBackend):
        async def cleanup(self, prepared):
            await super().cleanup(prepared)
            return {"reaped": False, "remaining_processes": [123], "graceful_attempted": False}

    result = asyncio.run(execute_world_attempt(prepared, CleanupFailure()))
    assert result["verification"]["verified"]
    assert result["status"] == "CONTROLLED_FAILED"
    assert not prepared.key_path.exists()
    assert prepared.spec.workspace.root.exists()
    assert (
        tmp_path / "openttd-15.3-world-info-real-attempt1/world-info-verification.json"
    ).exists()
    prepared.dispose()


# These historical modes retain their pre-production bridge safety contract.
pytestmark = pytest.mark.usefixtures("checkpoint_structural_bridge")
