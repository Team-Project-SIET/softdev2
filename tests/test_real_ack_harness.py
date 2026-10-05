import asyncio
import hashlib
import socket

import pytest
from test_real_ack_graphics import graphics_archive

from app.simulation.openttd.gamescript_protocol import Ack
from app.simulation.openttd.proof.attempt import Gate, Gates, execute_attempt
from app.simulation.openttd.proof.harness import EndpointReservation, prepare_proof
from app.simulation.openttd.runtime.config import AdminSettings


def test_authorized_only_config_has_no_password_fallback():
    settings = AdminSettings(password="", authorized_public_key_hex="ab" * 32)
    assert settings.password == ""
    with pytest.raises(ValueError):
        AdminSettings(password="")


def test_endpoints_are_distinct_loopback_owned_and_idempotent():
    reservation = EndpointReservation.allocate()
    try:
        assert reservation.game_port != reservation.admin_port
        for port in (reservation.game_port, reservation.admin_port):
            with socket.socket() as other:
                with pytest.raises(OSError):
                    other.bind(("127.0.0.1", port))
        assert all(s.getsockname()[0] == "127.0.0.1" for s in reservation.sockets)
        assert all(
            s.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0 for s in reservation.sockets
        )
    finally:
        reservation.close()
        reservation.close()


def test_preparation_freezes_without_launch_or_connect(tmp_path, monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("No process/connection permitted")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "open_connection", forbidden)
    binary = tmp_path / "openttd"
    binary.write_bytes(b"controlled binary")
    binary.chmod(0o700)
    archive = tmp_path / "graphics.zip"
    sha = graphics_archive(archive)
    prepared = prepare_proof(
        tmp_path / "prelaunch",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=archive,
        graphics_sha256=sha,
    )
    try:
        assert prepared.spec.argv == (
            str(binary.resolve()),
            f"-D127.0.0.1:{prepared.endpoints[0]}",
            "-c",
            str(prepared.spec.workspace.config),
            "-x",
            "-X",
            "-g",
            "-G",
            "42",
            "-dscript=4,grf=1,net=3",
        )
        assert prepared.spec.argv[-4:] == ("-g", "-G", "42", "-dscript=4,grf=1,net=3")
        assert f"-D127.0.0.1:{prepared.endpoints[0]}" in prepared.spec.argv
        assert prepared.spec.workspace.config.is_file()
        assert prepared.request.request_id == "openttd15-real-ack-002"
        assert (prepared.spec.workspace.game / "NoMutationBridge/main.nut").is_file()
        assert (prepared.directory / "PRELAUNCH.json").is_file()
        assert not (prepared.directory / "receipt.json").exists()
        assert not (prepared.directory / "stdout.log").exists()
        assert prepared.key_path.stat().st_mode & 0o777 == 0o600
        all_evidence = b"".join(p.read_bytes() for p in prepared.directory.glob("*.json"))
        assert prepared.key_path.read_bytes() not in all_evidence
    finally:
        prepared.dispose()


class ControlledBackend:
    kind = "CONTROLLED"

    def __init__(self, failure=None):
        self.failure = failure
        self.launches = 0
        self.sends = 0
        self.closed = 0

    def check(self, stage):
        if self.failure == stage:
            raise RuntimeError("controlled stage failure")

    def preflight(self, prepared):
        self.check("preflight")

    async def launch(self, prepared):
        self.check("launch")
        self.launches += 1
        self.prepared = prepared
        prepared.spec.stderr_path.write_text(
            "dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n"
        )

    async def authenticate(self, prepared, gates):
        self.check("auth")
        for gate in (
            Gate.ADMIN_CONNECTED,
            Gate.AUTHENTICATED,
            Gate.ENCRYPTION,
            Gate.PROTOCOL,
            Gate.WELCOME,
            Gate.IDENTITY,
        ):
            gates.advance(gate)
        return {"auth_method": "X25519_AuthorizedKey"}

    async def subscribe(self):
        self.check("subscription")

    async def ping(self, request):
        self.sends += 1
        self.check("ping")
        response = Ack("wrong" if self.failure == "wrong_ack" else request.request_id).to_bytes()
        with self.prepared.spec.stderr_path.open("a") as stream:
            for marker in ("BRIDGE_REQUEST_RECEIVED", "BRIDGE_ACK_SENT", "BRIDGE_POST_ACK_ALIVE"):
                stream.write(f"dbg: [script:4] [18] [I] {marker} request_id={request.request_id}\n")
        self.response = response
        return response

    async def wait_gamescript(self, prepared, *, complete):
        from app.simulation.openttd.proof.gamescript_evidence import parse_gamescript_evidence

        evidence = parse_gamescript_evidence(
            prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
        )
        if complete:
            evidence.require_complete()
        return evidence

    async def finish_network(self, receipt):
        from app.simulation.openttd.proof.causality import NetworkProofEvidence

        return NetworkProofEvidence(
            self.prepared.request.to_bytes(),
            self.response,
            receipt,
            ("REQUEST_SENT", "NETWORK_ACK_RECEIVED", "RECEIPT_CREATED"),
            self.sends,
            1,
            0,
            (),
        )

    def health(self):
        self.check("script")

    async def cleanup(self, prepared):
        self.closed += 1
        return {"reaped": True, "remaining_processes": [], "graceful_attempted": True}


def make_prepared(tmp_path):
    binary = tmp_path / "openttd"
    binary.write_bytes(b"controlled")
    binary.chmod(0o700)
    archive = tmp_path / "graphics.zip"
    sha = graphics_archive(archive)
    return prepare_proof(
        tmp_path / "prelaunch",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=archive,
        graphics_sha256=sha,
    )


def test_gates_reject_out_of_order():
    gates = Gates()
    with pytest.raises(ValueError):
        gates.advance(Gate.WELCOME)
    gates.advance(Gate.PROCESS)
    assert gates.completed == [Gate.PROCESS]


def test_one_controlled_attempt_receipt_and_cleanup(tmp_path):
    prepared = make_prepared(tmp_path)
    backend = ControlledBackend()
    outcome = asyncio.run(execute_attempt(prepared, backend))
    assert outcome["status"] == "CONTROLLED_SUCCESS"
    assert backend.launches == backend.sends == backend.closed == 1
    assert outcome["receipt"]["request_id"] == "openttd15-real-ack-002"
    assert not prepared.key_path.exists() and not prepared.spec.workspace.root.exists()
    assert (tmp_path / "openttd-15.3-real-ack-attempt2/artifact-manifest.sha256").is_file()
    with pytest.raises(ValueError):
        asyncio.run(execute_attempt(prepared, backend))
    assert backend.launches == 1


@pytest.mark.parametrize("stage", ["launch", "auth", "subscription", "ping", "wrong_ack", "script"])
def test_each_failure_stops_cleans_and_never_retries(tmp_path, stage):
    prepared = make_prepared(tmp_path)
    backend = ControlledBackend(stage)
    outcome = asyncio.run(execute_attempt(prepared, backend))
    assert outcome["status"] == "CONTROLLED_FAILED"
    assert backend.launches <= 1 and backend.sends <= 1 and backend.closed == 1
    assert not prepared.key_path.exists()
    assert outcome["receipt"] is None


def test_prelaunch_changed_source_stops_with_zero_launches(tmp_path):
    prepared = make_prepared(tmp_path)
    backend = ControlledBackend()
    prepared.spec.workspace.config.write_text("tampered")
    outcome = asyncio.run(execute_attempt(prepared, backend))
    assert outcome["launches"] == 0 and backend.launches == 0
    assert not (tmp_path / "openttd-15.3-real-ack-attempt2").exists()
    assert (prepared.directory / "PRELAUNCH-FAILURE.json").is_file()


def test_changed_source_after_ack_retains_failed_evidence(tmp_path):
    prepared = make_prepared(tmp_path)

    class ChangedBackend(ControlledBackend):
        async def ping(self, request):
            response = await super().ping(request)
            prepared.spec.workspace.config.write_text("changed postlaunch")
            return response

    outcome = asyncio.run(execute_attempt(prepared, ChangedBackend()))
    attempt = tmp_path / "openttd-15.3-real-ack-attempt2"
    assert outcome["status"] == "CONTROLLED_FAILED" and outcome["receipt"] is None
    assert (attempt / "response.json").is_file()
    assert (attempt / "source-freeze-post.json").is_file()


def test_native_backend_requires_authorization():
    from app.simulation.openttd.proof.native import NativeBackend

    with pytest.raises(PermissionError):
        NativeBackend()


@pytest.mark.parametrize("stage", ["auth", "subscription", "ping"])
def test_timeout_retains_no_success_receipt(tmp_path, stage):
    prepared = make_prepared(tmp_path)

    requested_stage = stage

    class TimeoutBackend(ControlledBackend):
        def check(self, stage):
            if stage == requested_stage:
                raise TimeoutError("controlled timeout")

    backend = TimeoutBackend()
    outcome = asyncio.run(execute_attempt(prepared, backend))
    assert outcome["error_type"] == "TimeoutError" and outcome["receipt"] is None
    assert backend.launches == 1 and backend.closed == 1


def test_freeze_and_manifest_deterministic_and_private_redacted(tmp_path):
    from app.simulation.openttd.proof.harness import manifest, source_freeze

    prepared = make_prepared(tmp_path)
    try:
        assert source_freeze() == source_freeze()
        assert manifest(prepared.directory) == manifest(prepared.directory)
        secret = prepared.key_path.read_bytes()
        evidence = b"".join(p.read_bytes() for p in prepared.directory.glob("*.json"))
        assert secret not in evidence and secret.hex().encode() not in evidence
        assert b"admin_password = \n" in evidence.replace(b"\\n", b"\n")
        assert (
            "GetAPIVersion"
            in (prepared.spec.workspace.game / "NoMutationBridge/info.nut").read_text()
        )
    finally:
        prepared.dispose()


def test_busy_frozen_endpoint_is_prelaunch_failure(tmp_path):
    prepared = make_prepared(tmp_path)
    backend = ControlledBackend()
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", prepared.endpoints[1]))
        outcome = asyncio.run(execute_attempt(prepared, backend))
    assert outcome["launches"] == 0 and backend.launches == 0 and backend.closed == 1


def test_cleanup_failure_retains_logs_and_removes_secret(tmp_path):
    prepared = make_prepared(tmp_path)

    class CleanupFailure(ControlledBackend):
        async def launch(self, prepared):
            await super().launch(prepared)
            prepared.spec.stdout_path.write_text("controlled stdout")
            prepared.spec.stderr_path.write_text("controlled stderr")

        async def cleanup(self, prepared):
            self.closed += 1
            raise RuntimeError("controlled cleanup failure")

    result = asyncio.run(execute_attempt(prepared, CleanupFailure()))
    directory = tmp_path / "openttd-15.3-real-ack-attempt2"
    assert result["receipt"] is None
    assert (directory / "stdout.log").read_text() == "controlled stdout"
    assert (directory / "stderr.log").read_text() == "controlled stderr"
    assert not prepared.key_path.exists()
    # Retained workspace because process reaping could not be established.
    assert prepared.spec.workspace.root.exists()
    prepared.dispose()


def test_preparation_rejects_global_profile_before_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    binary = tmp_path / "bin"
    binary.write_bytes(b"controlled")
    binary.chmod(0o700)
    forbidden = tmp_path / "home/.config/openttd/proof"
    with pytest.raises(ValueError, match="normal profiles"):
        prepare_proof(
            forbidden, binary=binary, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest()
        )
    assert not forbidden.parent.exists()
