import asyncio
import struct

import monocypher
import pytest

from app.simulation.openttd.admin_crypto import (
    AuthorizedKey,
    CryptoError,
    PacketCipher,
    derive_keys,
)
from app.simulation.openttd.admin_protocol import encode_admin_frame
from app.simulation.openttd.gamescript_protocol import PingRequest, handle_ping
from app.simulation.openttd.gamescript_transport import (
    GameScriptSession,
    GameScriptTransport,
    decode_gamescript,
    gamescript_subscription,
)
from app.simulation.openttd.secure_admin import (
    AuthDisconnected,
    AuthProtocolError,
    AuthRejected,
    AuthState,
    AuthTimeout,
    SecureAdminSession,
    encode_join_secure,
    parse_auth_request,
    parse_encryption_nonce,
)

KEY = AuthorizedKey.from_bytes(bytes(range(32)))
SERVER = AuthorizedKey.from_bytes(bytes(range(32, 64)))
NONCE = bytes(range(64, 88))
STREAM_NONCE = bytes(range(88, 112))


class Writer:
    def __init__(self):
        self.frames = []
        self.closed = False
        self.written = asyncio.Event()

    def write(self, frame):
        self.frames.append(frame)
        self.written.set()

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    def is_closing(self):
        return self.closed

    def get_extra_info(self, name):
        return None


def server_handshake():
    cipher = PacketCipher(derive_keys(KEY, SERVER.public_key).server_to_client, STREAM_NONCE)
    protocol = encode_admin_frame(103, b"\x03\x01" + struct.pack("<HH", 9, 64) + b"\0")
    welcome = encode_admin_frame(
        104, b"proof\x0015.3\0\x01\0" + struct.pack("<IBIHH", 1, 0, 730000, 64, 64)
    )
    return (
        encode_admin_frame(128, b"\x02" + SERVER.public_key + NONCE)
        + encode_admin_frame(129, STREAM_NONCE)
        + cipher.encrypt(protocol)
        + cipher.encrypt(welcome),
        cipher,
    )


def test_join_and_exact_auth_fields():
    frame = encode_join_secure("proof", "1")
    assert frame == encode_admin_frame(9, b"proof\x001\x00\x04\x00")
    request = parse_auth_request(b"\x02" + SERVER.public_key + NONCE)
    assert request.server_public == SERVER.public_key and request.nonce == NONCE
    assert parse_encryption_nonce(STREAM_NONCE) == STREAM_NONCE
    for method in [0, 1, 3, 255]:
        with pytest.raises(AuthProtocolError):
            parse_auth_request(bytes([method]) + SERVER.public_key + NONCE)
    for invalid in [b"", b"\x02" + bytes(55), b"\x02" + bytes(57)]:
        with pytest.raises(AuthProtocolError):
            parse_auth_request(invalid)
    for invalid in [bytes(23), bytes(25)]:
        with pytest.raises(AuthProtocolError):
            parse_encryption_nonce(invalid)


def test_secure_handshake_coalesced_and_active_gate():
    async def run():
        reader = asyncio.StreamReader()
        writer = Writer()
        session = SecureAdminSession(reader, writer, key=KEY)
        assert session.state is AuthState.CONNECTED
        with pytest.raises(AuthProtocolError):
            await session.send(encode_admin_frame(6, b"{}\0"))
        wire, _ = server_handshake()
        reader.feed_data(wire)
        await session.authenticate("proof", "1")
        assert session.state is AuthState.ACTIVE
        assert session.protocol.version == 3
        assert session.welcome.name == "proof"
        assert [frame[2] for frame in writer.frames] == [9, 10]
        assert len(writer.frames[1]) == 59
        await session.close(quit=True)
        assert session.state is AuthState.CLOSED and writer.closed
        assert len(writer.frames[-1]) == 19

    asyncio.run(run())


@pytest.mark.parametrize("kind", [129, 103, 104, 124, 128])
def test_invalid_initial_packets_close(kind):
    async def run():
        reader = asyncio.StreamReader()
        writer = Writer()
        reader.feed_data(encode_admin_frame(kind, bytes(24)))
        session = SecureAdminSession(reader, writer, key=KEY)
        with pytest.raises(AuthProtocolError):
            await session.authenticate("p", "1")
        assert session.state is AuthState.CLOSED and writer.closed

    asyncio.run(run())


@pytest.mark.parametrize("behavior", ["timeout", "disconnect", "rejected", "truncated", "zero_key"])
def test_auth_failure_classification(behavior):
    async def run():
        reader = asyncio.StreamReader()
        writer = Writer()
        expected = {
            "timeout": AuthTimeout,
            "disconnect": AuthDisconnected,
            "rejected": AuthRejected,
            "truncated": AuthProtocolError,
            "zero_key": CryptoError,
        }[behavior]
        if behavior == "disconnect":
            reader.feed_eof()
        if behavior == "rejected":
            reader.feed_data(encode_admin_frame(102, b"\x01"))
        if behavior == "truncated":
            reader.feed_data(b"\x30\0\x80")
            reader.feed_eof()
        if behavior == "zero_key":
            reader.feed_data(encode_admin_frame(128, b"\x02" + bytes(32) + NONCE))
        session = SecureAdminSession(reader, writer, key=KEY)
        # Truncated framing raises the shared AdminProtocolError, not a timeout.
        from app.simulation.openttd.admin_protocol import AdminProtocolError

        if behavior == "truncated":
            expected = AdminProtocolError
        with pytest.raises(expected):
            await session.authenticate("p", "1", timeout=0.01)
        assert session.state is AuthState.CLOSED and writer.closed
        await session.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "behavior",
    ["bad_nonce", "duplicate_enable", "plaintext_protocol", "bad_version", "welcome_first"],
)
def test_post_response_transitions_fail_closed(behavior):
    async def run():
        reader = asyncio.StreamReader()
        writer = Writer()
        initial = encode_admin_frame(128, b"\x02" + SERVER.public_key + NONCE)
        enable = encode_admin_frame(129, STREAM_NONCE)
        cipher = PacketCipher(derive_keys(KEY, SERVER.public_key).server_to_client, STREAM_NONCE)
        if behavior == "bad_nonce":
            wire = initial + encode_admin_frame(129, bytes(23))
        elif behavior == "duplicate_enable":
            wire = initial + enable + enable
        elif behavior == "plaintext_protocol":
            wire = initial + enable + encode_admin_frame(103, b"\x03\0")
        elif behavior == "bad_version":
            wire = initial + enable + cipher.encrypt(encode_admin_frame(103, b"\x02\0"))
        else:
            wire = initial + enable + cipher.encrypt(encode_admin_frame(104, b""))
        reader.feed_data(wire)
        session = SecureAdminSession(reader, writer, key=KEY)
        from app.simulation.openttd.admin_protocol import AdminProtocolError

        with pytest.raises(AdminProtocolError):
            await session.authenticate("p", "1")
        assert session.state is AuthState.CLOSED

    asyncio.run(run())


class ReferencePeer(Writer):
    """In-memory server model adapted from 15.3 TestAuthenticationAuthorizedKey."""

    def __init__(self, reader, *, authorized=KEY.public_key):
        super().__init__()
        self.reader = reader
        self.authorized = authorized
        keys = derive_keys(KEY, SERVER.public_key)
        self.in_cipher = PacketCipher(keys.client_to_server, STREAM_NONCE)
        self.out_cipher = None
        self.authenticated = False

    def write(self, frame):
        super().write(frame)
        if not self.authenticated and frame[2] == 9:
            self.reader.feed_data(encode_admin_frame(128, b"\x02" + SERVER.public_key + NONCE))
        elif not self.authenticated and frame[2] == 10:
            payload = frame[3:]
            # Independent server-side shared secret and derivation order.
            import hashlib

            shared = monocypher.x25519(bytes(range(32, 64)), payload[:32])
            keys = hashlib.blake2b(
                shared + SERVER.public_key + payload[:32], digest_size=64
            ).digest()
            message = monocypher.unlock(
                keys[:32], NONCE, payload[32:48], payload[48:], payload[:32]
            )
            if message is None or payload[:32] != self.authorized:
                self.reader.feed_data(encode_admin_frame(102, b"\x01"))
                return
            self.authenticated = True
            wire, self.out_cipher = server_handshake()
            # Request was already sent; feed ENABLE + encrypted Protocol/Welcome.
            self.reader.feed_data(wire[60:])
        else:
            plain = self.in_cipher.decrypt(frame)
            if plain[2] == 6:
                assert self.out_cipher is not None
                response = handle_ping(decode_gamescript(plain[3:]))
                self.reader.feed_data(
                    self.out_cipher.encrypt(encode_admin_frame(126, struct.pack("<I", 123)))
                )
                self.reader.feed_data(
                    self.out_cipher.encrypt(encode_admin_frame(124, response + b"\0"))
                )


def test_secure_auth_and_encrypted_bridge_roundtrip():
    async def run():
        reader = asyncio.StreamReader()
        writer = ReferencePeer(reader)
        session = SecureAdminSession(reader, writer, key=KEY)
        with pytest.raises(AuthProtocolError):
            await session.send(gamescript_subscription())
        with pytest.raises(AuthProtocolError):
            await session.receive()
        await session.authenticate("proof", "1", random_bytes=lambda n: bytes(range(112, 112 + n)))
        assert writer.authenticated and session.state is AuthState.ACTIVE
        assert session.protocol is not None
        transport = GameScriptTransport(session, session.protocol)
        for request_id in ["a", "b", "c"]:
            receipt = await transport.ping(PingRequest(request_id))
            assert receipt.request_id == request_id and receipt.status == "ok"
        await session.close(quit=True)
        await session.close(quit=True)
        assert writer.closed

    asyncio.run(run())


def test_wrong_authorized_public_key_hex_rejected():
    async def run():
        reader = asyncio.StreamReader()
        writer = ReferencePeer(reader, authorized=SERVER.public_key)
        session = SecureAdminSession(reader, writer, key=KEY)
        with pytest.raises(AuthRejected):
            await session.authenticate("proof", "1")
        assert not writer.authenticated and session.state is AuthState.CLOSED

    asyncio.run(run())


def test_no_plaintext_connect_fallback():
    async def run():
        from app.simulation.openttd.admin_protocol import AdminProtocolError

        for cls in [GameScriptSession, SecureAdminSession]:
            with pytest.raises(AdminProtocolError, match="connect_secure"):
                await cls.connect("127.0.0.1", 3977, 1)

    asyncio.run(run())


@pytest.mark.parametrize(
    "name,version", [("", "1"), ("a" * 25, "1"), ("p", "v" * 33), ("p\0", "1")]
)
def test_client_identity_bounds(name, version):
    with pytest.raises(AuthProtocolError):
        encode_join_secure(name, version)


def test_authorized_public_config_isolated(tmp_path):
    from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace

    workspace = RuntimeWorkspace.create(tmp_path)
    try:
        workspace.write_config(
            AdminSettings(password="proof", authorized_public_key_hex=KEY.public_hex)
        )
        private = workspace.root / "private.cfg"
        assert private.read_text().endswith("[admin_authorized_keys]\n" + KEY.public_hex + "\n")
        assert private.stat().st_mode & 0o777 == 0o600
        assert "allow_insecure_admin_login = false" in workspace.config.read_text()
        assert bytes(range(32)).hex() not in private.read_text()
        assert private.resolve().is_relative_to(workspace.root)
        for invalid in ["", "z" * 64, "a" * 63, "a" * 64 + "\n"]:
            with pytest.raises(ValueError):
                AdminSettings(password="proof", authorized_public_key_hex=invalid)
    finally:
        workspace.close()


def test_auth_cancellation_closes():
    async def run():
        reader = asyncio.StreamReader()
        writer = Writer()
        session = SecureAdminSession(reader, writer, key=KEY)
        task = asyncio.create_task(session.authenticate("proof", "1"))
        # Explicit write event proves the handshake has started before cancellation.
        await writer.written.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert session.state is AuthState.CLOSED and writer.closed

    asyncio.run(run())


def test_reauthentication_fails_closed():
    async def run():
        reader = asyncio.StreamReader()
        writer = ReferencePeer(reader)
        session = SecureAdminSession(reader, writer, key=KEY)
        await session.authenticate("proof", "1")
        with pytest.raises(AuthProtocolError):
            await session.authenticate("proof", "1")
        assert session.state is AuthState.CLOSED

    asyncio.run(run())


class FragmentedReader(asyncio.StreamReader):
    def __init__(self, wire):
        super().__init__()
        self.chunks = [wire[i : i + 1] for i in range(len(wire))]

    async def read(self, n=-1):
        return self.chunks.pop(0) if self.chunks else b""


def test_fragmented_secure_handshake_and_eof():
    async def run():
        wire, _ = server_handshake()
        reader = FragmentedReader(wire)
        writer = Writer()
        session = SecureAdminSession(reader, writer, key=KEY)
        await session.authenticate("p", "1")
        assert session.state is AuthState.ACTIVE
        assert await session.receive() == b""
        assert session.state is AuthState.CLOSED and writer.closed

    asyncio.run(run())


def test_encrypted_request_before_enable_rejected():
    async def run():
        cipher = PacketCipher(bytes.fromhex("11" * 32), STREAM_NONCE)
        reader = asyncio.StreamReader()
        writer = Writer()
        reader.feed_data(
            cipher.encrypt(encode_admin_frame(128, b"\x02" + SERVER.public_key + NONCE))
        )
        session = SecureAdminSession(reader, writer, key=KEY)
        with pytest.raises(AuthProtocolError):
            await session.authenticate("p", "1")
        assert session.state is AuthState.CLOSED

    asyncio.run(run())


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), 11])
def test_auth_deadline_bounds(timeout):
    async def run():
        session = SecureAdminSession(asyncio.StreamReader(), Writer(), key=KEY)
        with pytest.raises(ValueError):
            await session.authenticate("p", "1", timeout=timeout)
        await session.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["write", "drain", "cancel"])
def test_secure_write_failure_discards_stream(failure, monkeypatch):
    async def run():
        reader = asyncio.StreamReader()
        writer = ReferencePeer(reader)
        session = SecureAdminSession(reader, writer, key=KEY)
        await session.authenticate("p", "1")

        def failed_write(frame):
            raise OSError("controlled write failure")

        async def failed_drain():
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise OSError("controlled drain failure")

        if failure == "write":
            monkeypatch.setattr(writer, "write", failed_write)
        else:
            monkeypatch.setattr(writer, "drain", failed_drain)
        expected = asyncio.CancelledError if failure == "cancel" else OSError
        with pytest.raises(expected):
            await session.send(gamescript_subscription())
        assert session.state is AuthState.CLOSED and writer.closed
        assert session._out_cipher is None and session._in_cipher is None

    asyncio.run(run())
