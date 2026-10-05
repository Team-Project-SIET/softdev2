"""Exercise the future native adapter with fake process and in-memory encrypted peer."""

import asyncio
import hashlib
import io
import json
import struct
from datetime import date

import monocypher
import pytest
from test_real_ack_harness import make_prepared
from test_secure_admin import Writer

from app.simulation.openttd.admin_crypto import AuthorizedKey, PacketCipher
from app.simulation.openttd.admin_protocol import encode_admin_frame
from app.simulation.openttd.gamescript_protocol import Ack, handle_ping
from app.simulation.openttd.gamescript_transport import decode_gamescript
from app.simulation.openttd.proof.attempt import execute_attempt
from app.simulation.openttd.secure_admin import SecureAdminSession


class ControlledProcess:
    pid = 123456789

    def __init__(self, *, early_exit=False):
        self.returncode = 1 if early_exit else None
        process = self

        class Input(io.BytesIO):
            def write(self, data):
                assert data == b"quit\n"
                process.returncode = 0
                return super().write(data)

        self.stdin = Input()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def send_signal(self, sig):
        self.returncode = -int(sig)

    def kill(self):
        self.returncode = -9


class Peer(Writer):
    def __init__(self, reader, key, behavior, log):
        super().__init__()
        self.log = log
        self.reader = reader
        self.key = key
        self.behavior = behavior
        self.server = AuthorizedKey.from_bytes(bytes(range(32, 64)))
        self.nonce = bytes(range(24))
        self.stream_nonce = bytes(range(24, 48))
        self.in_cipher = None
        self.out_cipher = None
        self.requests = 0
        self.subscribed = False

    def write(self, frame):
        super().write(frame)
        if self.in_cipher is None and frame[2] == 9:
            self.reader.feed_data(
                encode_admin_frame(128, b"\x02" + self.server.public_key + self.nonce)
            )
        elif self.in_cipher is None and frame[2] == 10:
            p = frame[3:]
            shared = monocypher.x25519(bytes(range(32, 64)), p[:32])
            keys = hashlib.blake2b(
                shared + self.server.public_key + p[:32], digest_size=64
            ).digest()
            assert monocypher.unlock(keys[:32], self.nonce, p[32:48], p[48:], p[:32]) is not None
            if self.behavior == "auth_failure":
                self.reader.feed_data(encode_admin_frame(102, b"\x01"))
                return
            self.in_cipher = PacketCipher(keys[:32], self.stream_nonce)
            self.out_cipher = PacketCipher(keys[32:], self.stream_nonce)
            self.reader.feed_data(encode_admin_frame(129, self.stream_nonce))
            protocol = encode_admin_frame(103, b"\x03\x01" + struct.pack("<HH", 9, 64) + b"\0")
            welcome = encode_admin_frame(
                104,
                b"proof\x0015.3\0\x01\0"
                + struct.pack("<IBIHH", 42, 0, date(1950, 1, 1).toordinal() + 365, 64, 64),
            )
            self.reader.feed_data(
                self.out_cipher.encrypt(protocol) + self.out_cipher.encrypt(welcome)
            )
        else:
            assert self.in_cipher is not None and self.out_cipher is not None
            plain = self.in_cipher.decrypt(frame)
            if plain[2] == 2:
                self.subscribed = True
            elif plain[2] == 7:
                self.reader.feed_data(self.out_cipher.encrypt(encode_admin_frame(126, plain[3:])))
                if self.behavior == "success_late_alive" and plain[3:] == struct.pack("<I", 0x154):
                    self.log.write(
                        b"dbg: [script:4] [18] [I] BRIDGE_POST_ACK_ALIVE "
                        b"request_id=openttd15-real-ack-002\n"
                    )
                    self.log.flush()
            elif plain[2] == 6:
                assert self.subscribed
                self.requests += 1
                if self.behavior != "no_internal":
                    request_id = json.loads(decode_gamescript(plain[3:]))["request_id"]
                    markers = ["BRIDGE_REQUEST_RECEIVED", "BRIDGE_ACK_SENT"]
                    if self.behavior != "success_late_alive":
                        markers.append("BRIDGE_POST_ACK_ALIVE")
                    for marker in markers:
                        self.log.write(
                            f"dbg: [script:4] [18] [I] {marker} request_id={request_id}\n".encode()
                        )
                    self.log.flush()
                response = (
                    Ack("wrong").to_bytes()
                    if self.behavior == "wrong_ack"
                    else handle_ping(decode_gamescript(plain[3:]))
                )
                self.reader.feed_data(
                    self.out_cipher.encrypt(encode_admin_frame(124, response + b"\0"))
                )
                if self.behavior == "duplicate_ack":
                    self.reader.feed_data(
                        self.out_cipher.encrypt(encode_admin_frame(124, response + b"\0"))
                    )


@pytest.mark.parametrize(
    "behavior",
    [
        "success",
        "success_late_alive",
        "duplicate_ack",
        "auth_failure",
        "wrong_ack",
        "early_exit",
        "script_error",
        "session_close_error",
    ],
)
def test_native_adapter_controlled_secure_flow(tmp_path, monkeypatch, behavior):
    import app.simulation.openttd.proof.native as native

    prepared = make_prepared(tmp_path)
    monkeypatch.setattr(native, "BINARY", prepared.spec.identity.executable)
    monkeypatch.setattr(native, "BINARY_SHA256", prepared.spec.identity.sha256)
    monkeypatch.setattr(
        native,
        "ARCHIVE_SHA256",
        json.loads((prepared.directory / "graphics-identity.json").read_text())["archive_sha256"],
    )
    peers = []
    processes = []
    logs = []

    def popen(argv, **kw):
        logs.append(kw["stderr"])
        kw["stderr"].write(b"Using the OpenGFX base graphics set\n")
        kw["stderr"].write(b"dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n")
        kw["stderr"].flush()
        if behavior == "script_error":
            kw["stderr"].write(b"The script died unexpectedly.\n")
            kw["stderr"].flush()
        process = ControlledProcess(early_exit=behavior == "early_exit")
        processes.append(process)
        return process

    monkeypatch.setattr(native.subprocess, "Popen", popen)

    async def connect(cls, host, port, timeout, *, key):
        assert host == "127.0.0.1" and port == prepared.endpoints[1]
        reader = asyncio.StreamReader()
        peer = Peer(reader, key, behavior, logs[0])
        peers.append(peer)
        return SecureAdminSession(reader, peer, key=key)

    monkeypatch.setattr(SecureAdminSession, "connect_secure", classmethod(connect))
    if behavior == "session_close_error":
        original_close = SecureAdminSession.close

        async def failed_quit(self, *, quit=False):
            if quit:
                raise OSError("controlled Admin quit failure")
            await original_close(self, quit=quit)

        monkeypatch.setattr(SecureAdminSession, "close", failed_quit)
    backend = native.NativeBackend(authorized_one_launch=True)
    backend.kind = "CONTROLLED"
    result = asyncio.run(execute_attempt(prepared, backend))
    assert result["launches"] == 1 and len(processes) == 1
    assert result["status"] == (
        "CONTROLLED_SUCCESS"
        if behavior in ("success", "success_late_alive")
        else "CONTROLLED_FAILED"
    )
    if behavior in ("success", "success_late_alive"):
        assert result["proof_model"] == "two-correlated-chains-v2"
        assert result["transaction_correlation"]["request_id"] == "openttd15-real-ack-002"
    assert processes[0].poll() is not None and processes[0].stdin.closed
    assert not prepared.key_path.exists()
    if peers:
        assert peers[0].requests == (
            1
            if behavior
            in (
                "success",
                "success_late_alive",
                "duplicate_ack",
                "wrong_ack",
                "session_close_error",
            )
            else 0
        )
        assert peers[0].closed
