"""15.3 authorized-key Admin login. No gameplay, reconnect, or insecure fallback."""

import asyncio
import math
import secrets
import struct
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from typing import Self

from app.simulation.openttd.admin_crypto import (
    AuthorizedKey,
    DerivedKeys,
    PacketCipher,
    authentication_response,
    derive_keys,
)
from app.simulation.openttd.admin_protocol import (
    AdminFrameDecoder,
    AdminProtocolError,
    ServerProtocol,
    ServerWelcome,
    decode_server_packet,
    encode_admin_frame,
)
from app.simulation.openttd.admin_session import AdminWriter
from app.simulation.openttd.gamescript_transport import GameScriptSession, ServerLifecyclePacket

AUTH_METHOD = 2  # NetworkAuthenticationMethod::X25519_AuthorizedKey
AUTH_METHOD_MASK = 1 << AUTH_METHOD
AUTH_DEADLINE = 10.0


class SecurePacketType(IntEnum):
    JOIN_SECURE = 9
    AUTH_RESPONSE = 10
    AUTH_REQUEST = 128
    ENABLE_ENCRYPTION = 129


class AuthState(Enum):
    DISCONNECTED = auto()
    CONNECTED = auto()
    AUTH_JOIN_SENT = auto()
    AUTH_REQUEST_RECEIVED = auto()
    AUTH_RESPONSE_SENT = auto()
    ENCRYPTION_ENABLED = auto()
    PROTOCOL_RECEIVED = auto()
    WELCOME_RECEIVED = auto()
    ACTIVE = auto()
    CLOSED = auto()


class AuthProtocolError(AdminProtocolError):
    pass


class AuthRejected(AuthProtocolError):
    pass


class AuthTimeout(TimeoutError):
    pass


class AuthDisconnected(ConnectionError):
    pass


@dataclass(frozen=True)
class AuthRequest:
    server_public: bytes
    nonce: bytes


def encode_join_secure(name: str, version: str) -> bytes:
    # 15.3 network_type.h string capacities include their terminating NUL.
    def string(value: str, capacity: int) -> bytes:
        raw = value.encode("utf-8")
        if not raw or len(raw) >= capacity or b"\0" in raw:
            raise AuthProtocolError("invalid secure client identification")
        return raw + b"\0"

    return encode_admin_frame(
        SecurePacketType.JOIN_SECURE,
        string(name, 25) + string(version, 33) + struct.pack("<H", AUTH_METHOD_MASK),
    )


def parse_auth_request(payload: bytes) -> AuthRequest:
    if len(payload) != 57 or payload[0] != AUTH_METHOD:
        raise AuthProtocolError("unsupported authentication method or malformed request")
    return AuthRequest(payload[1:33], payload[33:])


def parse_encryption_nonce(payload: bytes) -> bytes:
    if len(payload) != 24:
        raise AuthProtocolError("malformed encryption nonce")
    return payload


class SecureAdminSession(GameScriptSession):
    """Owns handshake and directional ciphers beneath Admin packet semantics.

    ``reader`` is the raw socket stream and exclusively owned by this session.
    Application consumers use ``receive`` and ``send`` only after ACTIVE.
    """

    def __init__(
        self, reader: asyncio.StreamReader, writer: AdminWriter, *, key: AuthorizedKey
    ) -> None:
        super().__init__(reader, writer)
        self._state = AuthState.CONNECTED
        self._key: AuthorizedKey | None = key
        self._keys: DerivedKeys | None = None
        self._out_cipher: PacketCipher | None = None
        self._in_cipher: PacketCipher | None = None
        self._frames: deque[bytes] = deque()
        self._framer = AdminFrameDecoder()
        self.protocol: ServerProtocol | None = None
        self.welcome: ServerWelcome | None = None

    @property
    def state(self) -> AuthState:
        return self._state

    @classmethod
    async def connect_secure(
        cls, host: str, port: int, timeout: float, *, key: AuthorizedKey
    ) -> Self:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("connection timeout must be positive and finite")
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        except TimeoutError:
            raise AuthTimeout("Admin connection deadline expired") from None
        except OSError:
            raise AuthDisconnected("Admin connection failed") from None
        return cls(reader, writer, key=key)

    def validate_outbound(self, frame: bytes) -> None:
        if self.state is not AuthState.ACTIVE:
            raise AuthProtocolError("Admin application traffic requires ACTIVE")
        super().validate_outbound(frame)

    async def send(self, *frames: bytes) -> None:
        # Validate before touching state. Once encryption starts, any uncertainty
        # about delivery invalidates this stream; it cannot safely be retried.
        for frame in frames:
            self.validate_outbound(frame)
        try:
            await super().send(*frames)
        except BaseException:
            await self.close()
            raise

    def encode_outbound(self, frame: bytes) -> bytes:
        if self._out_cipher is None:
            raise AuthProtocolError("encrypted stream is not enabled")
        return self._out_cipher.encrypt(frame)

    async def _next_frame(self) -> bytes:
        while not self._frames:
            chunk = await self.reader.read(4096)
            if not chunk:
                self._framer.finish()
                raise AuthDisconnected("Admin disconnected")
            self._frames.extend(self._framer.feed_wire_frames(chunk))
        frame = self._frames.popleft()
        return self._in_cipher.decrypt(frame) if self._in_cipher else frame

    async def receive(self, size: int = 4096) -> bytes:
        if self.state is not AuthState.ACTIVE:
            raise AuthProtocolError("Admin application traffic requires ACTIVE")
        try:
            return await self._next_frame()
        except AuthDisconnected:
            await self.close()
            return b""
        except BaseException:
            await self.close()
            raise

    async def _expect(self, kind: int) -> bytes:
        frame = await self._next_frame()
        if frame[2] in (
            ServerLifecyclePacket.FULL,
            ServerLifecyclePacket.BANNED,
            ServerLifecyclePacket.ERROR,
        ):
            raise AuthRejected("server rejected Admin authentication")
        if frame[2] != kind:
            raise AuthProtocolError("unexpected secure authentication packet")
        return frame[3:]

    async def authenticate(
        self,
        name: str,
        version: str,
        *,
        timeout: float = AUTH_DEADLINE,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        if self.state is not AuthState.CONNECTED:
            await self.close()
            raise AuthProtocolError("authentication already started or session closed")
        if not math.isfinite(timeout) or not 0 < timeout <= AUTH_DEADLINE:
            raise ValueError("authentication timeout must be positive and at most 10 seconds")
        try:
            async with asyncio.timeout(timeout):
                self._writer.write(encode_join_secure(name, version))
                self._state = AuthState.AUTH_JOIN_SENT
                await self._writer.drain()
                request = parse_auth_request(await self._expect(SecurePacketType.AUTH_REQUEST))
                self._state = AuthState.AUTH_REQUEST_RECEIVED
                assert self._key is not None
                self._keys = derive_keys(self._key, request.server_public)
                response = authentication_response(
                    self._key, self._keys, request.nonce, random_bytes(8)
                )
                self._writer.write(encode_admin_frame(SecurePacketType.AUTH_RESPONSE, response))
                self._state = AuthState.AUTH_RESPONSE_SENT
                await self._writer.drain()
                nonce = parse_encryption_nonce(
                    await self._expect(SecurePacketType.ENABLE_ENCRYPTION)
                )
                self._out_cipher = PacketCipher(self._keys.client_to_server, nonce)
                self._in_cipher = PacketCipher(self._keys.server_to_client, nonce)
                self._key = None
                self._keys = None
                self._state = AuthState.ENCRYPTION_ENABLED
                protocol = decode_server_packet(
                    ServerLifecyclePacket.PROTOCOL,
                    await self._expect(ServerLifecyclePacket.PROTOCOL),
                )
                if not isinstance(protocol, ServerProtocol) or protocol.version != 3:
                    raise AuthProtocolError("secure Admin requires protocol version 3")
                self.protocol = protocol
                self._state = AuthState.PROTOCOL_RECEIVED
                welcome = decode_server_packet(
                    ServerLifecyclePacket.WELCOME, await self._expect(ServerLifecyclePacket.WELCOME)
                )
                assert isinstance(welcome, ServerWelcome)
                self.welcome = welcome
                self._state = AuthState.WELCOME_RECEIVED
                self._state = AuthState.ACTIVE
        except TimeoutError:
            await self.close()
            raise AuthTimeout("Admin authentication deadline expired") from None
        except OSError:
            await self.close()
            raise AuthDisconnected("Admin authentication I/O failed") from None
        except BaseException:
            await self.close()
            raise

    async def close(self, *, quit: bool = False) -> None:
        try:
            await super().close(quit=quit and self.state is AuthState.ACTIVE)
        finally:
            self._state = AuthState.CLOSED
            self._key = None
            self._keys = None
            for cipher in (self._out_cipher, self._in_cipher):
                if cipher is not None:
                    cipher.close()
            self._out_cipher = self._in_cipher = None
            self._frames.clear()
