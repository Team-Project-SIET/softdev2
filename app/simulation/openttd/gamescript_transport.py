"""15.3 GameScript packet primitives, separate from P04's observation policy."""

import asyncio
import math
import struct
from enum import IntEnum

from app.simulation.openttd.admin_protocol import (
    AdminClientPacketType,
    AdminFrameDecoder,
    AdminFrequency,
    AdminProtocolError,
    ServerProtocol,
    encode_admin_frame,
    encode_admin_ping,
    encode_admin_quit,
)
from app.simulation.openttd.admin_session import AdminStream
from app.simulation.openttd.gamescript_protocol import (
    MAX_PAYLOAD_BYTES,
    BridgeProtocolError,
    CommunicationReceipt,
    MalformedMessage,
    PingRequest,
)
from app.simulation.openttd.world_info import (
    NETWORK_SEQUENCE,
    WorldInfoExchange,
    WorldInfoReceipt,
    WorldInfoRequest,
)

ADMIN_GAMESCRIPT = 6
SERVER_GAMESCRIPT = 124
GAMESCRIPT_UPDATE = 9


class ServerLifecyclePacket(IntEnum):
    FULL = 100
    BANNED = 101
    ERROR = 102
    PROTOCOL = 103
    WELCOME = 104
    NEWGAME = 105
    SHUTDOWN = 106


def encode_gamescript(payload: bytes) -> bytes:
    if not 0 < len(payload) <= MAX_PAYLOAD_BYTES or b"\0" in payload:
        raise MalformedMessage("invalid GameScript payload size or NUL")
    payload.decode("utf-8")
    return encode_admin_frame(ADMIN_GAMESCRIPT, payload + b"\0")


def decode_gamescript(payload: bytes) -> bytes:
    if not payload.endswith(b"\0") or b"\0" in payload[:-1]:
        raise MalformedMessage("GameScript packet requires exactly one terminated string")
    result = payload[:-1]
    if not 0 < len(result) <= MAX_PAYLOAD_BYTES:
        raise MalformedMessage("GameScript packet exceeds application limit")
    try:
        result.decode("utf-8")
    except UnicodeError as error:
        raise MalformedMessage("invalid GameScript UTF-8") from error
    return result


class GameScriptSession(AdminStream):
    """Controlled supplied streams; production connections require SecureAdminSession."""

    @classmethod
    async def connect(cls, host: str, port: int, timeout: float):
        raise AdminProtocolError("Use SecureAdminSession.connect_secure for OpenTTD 15.3")

    def validate_outbound(self, frame: bytes) -> None:
        if len(frame) < 3:
            raise AdminProtocolError("truncated bridge frame")
        length, kind = struct.unpack_from("<HB", frame)
        if length != len(frame) or length > AdminFrameDecoder.MAX_FRAME_LENGTH:
            raise AdminProtocolError("invalid bridge frame length")
        if kind == ADMIN_GAMESCRIPT:
            payload = decode_gamescript(frame[3:])
            try:
                PingRequest.parse(payload)
            except BridgeProtocolError:
                WorldInfoRequest.parse(payload)
        elif kind == AdminClientPacketType.PING and len(frame) == 7:
            pass  # Read-only ordering barrier after GameScript subscription.
        elif frame not in (gamescript_subscription(), encode_admin_quit()):
            raise AdminProtocolError("outbound packet forbidden by bridge session")


def gamescript_subscription() -> bytes:
    return encode_admin_frame(
        AdminClientPacketType.UPDATE_FREQUENCY,
        struct.pack("<HH", GAMESCRIPT_UPDATE, int(AdminFrequency.AUTOMATIC)),
    )


class TransportTimeout(TimeoutError):
    pass


class TransportDisconnected(ConnectionError):
    pass


class TransportProtocolError(BridgeProtocolError):
    pass


class MalformedResponse(TransportProtocolError):
    pass


class GameScriptTransport:
    """One correlated request at a time on an authenticated, exclusively owned stream.

    No connection/authentication or background reader is started here. Reuse of IDs
    on a connection is rejected to prevent delayed ACKs completing a later request.
    """

    MAX_REQUESTS = 256

    def __init__(self, session: GameScriptSession, protocol: ServerProtocol) -> None:
        if protocol.version != 3 or not protocol.frequencies.get(GAMESCRIPT_UPDATE, 0) & int(
            AdminFrequency.AUTOMATIC
        ):
            raise TransportProtocolError("server must advertise GameScript AUTOMATIC updates")
        self.session = session
        self._decoder = AdminFrameDecoder()
        self._registered = False
        self._pending: str | None = None
        self._used_ids: set[str] = set()
        self._usable = True
        self._subscribing = False
        self.response_payload: bytes | None = None

    @property
    def registered(self) -> bool:
        return self._registered

    async def subscribe(self, *, token: int = 0x153, timeout: float = 5.0) -> None:
        """15.3 has no subscription ACK; ordered AdminPong confirms processing.

        Errors preceding the barrier fail the gate. This sends no bridge request.
        """
        if type(token) is not int or not 0 <= token < 2**32:
            raise ValueError("invalid barrier token")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if not self._usable or self._pending is not None or self._subscribing:
            raise TransportProtocolError("transport is unavailable")
        if self._registered:
            return
        self._subscribing = True
        completed = False
        try:
            async with asyncio.timeout(timeout):
                await self.session.send(gamescript_subscription(), encode_admin_ping(token))
                while True:
                    chunk = await self.session.receive()
                    if not chunk:
                        self._decoder.finish()
                        raise TransportDisconnected("disconnect before subscription barrier")
                    matched = False
                    for kind, body in self._decoder.feed_frames(chunk):
                        if kind == 126:
                            if body != struct.pack("<I", token):
                                raise TransportProtocolError("wrong subscription barrier token")
                            matched = True
                        elif kind in ServerLifecyclePacket or kind == SERVER_GAMESCRIPT:
                            raise TransportProtocolError("unexpected subscription response")
                    if matched:
                        self._registered = completed = True
                        return
        except TimeoutError as error:
            raise TransportTimeout("subscription deadline expired") from error
        except OSError as error:
            raise TransportDisconnected("subscription I/O failed") from error
        finally:
            self._subscribing = False
            if not completed:
                self._usable = False
                await self.session.close()

    @property
    def pending_request_id(self) -> str | None:
        return self._pending

    async def ping(self, request: PingRequest, *, timeout: float = 5.0) -> CommunicationReceipt:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if not self._usable or self._pending is not None or self._subscribing:
            raise TransportProtocolError("transport unavailable or already has a pending request")
        if request.request_id in self._used_ids or len(self._used_ids) >= self.MAX_REQUESTS:
            raise TransportProtocolError("use a fresh request_id or a new session")
        payload = request.to_bytes()
        self._pending = request.request_id
        self._used_ids.add(request.request_id)
        completed = False
        try:
            async with asyncio.timeout(timeout):
                if not self._registered:
                    await self.session.send(gamescript_subscription())
                    self._registered = True
                await self.session.send(encode_gamescript(payload))
                while True:
                    chunk = await self.session.receive(4096)
                    if not chunk:
                        try:
                            self._decoder.finish()
                        except AdminProtocolError as error:
                            raise MalformedResponse("truncated frame at disconnect") from error
                        raise TransportDisconnected("Admin stream disconnected before ACK")
                    frames = self._decoder.feed_frames(chunk)
                    receipt = None
                    for kind, body in frames:
                        if kind == SERVER_GAMESCRIPT:
                            response = decode_gamescript(body)
                            candidate = CommunicationReceipt.correlate(payload, response)
                            if receipt is None:
                                receipt = candidate
                                self.response_payload = response
                        elif kind == ServerLifecyclePacket.SHUTDOWN:
                            raise TransportDisconnected("server shutdown before ACK")
                        elif kind in ServerLifecyclePacket:
                            raise TransportProtocolError(
                                "unexpected server lifecycle packet while awaiting ACK"
                            )
                    if receipt is not None:
                        completed = True
                        return receipt
        except MalformedMessage as error:
            raise MalformedResponse(str(error)) from error
        except AdminProtocolError as error:
            raise MalformedResponse(str(error)) from error
        except BridgeProtocolError as error:
            if isinstance(error, TransportProtocolError):
                raise
            raise TransportProtocolError(str(error)) from error
        except TimeoutError as error:
            raise TransportTimeout("ACK deadline expired") from error
        except OSError as error:
            raise TransportDisconnected("Admin stream I/O failed") from error
        finally:
            self._pending = None
            if not completed:
                self._usable = False
                await self.session.close()

    async def world_info(
        self, request: WorldInfoRequest, *, timeout: float = 5.0
    ) -> WorldInfoExchange:
        """One bounded read-only query, with duplicate-response completion barrier.

        Uses the existing secure production session; no connection or retry is opened.
        The two AdminPing barriers are protocol packets, not application requests.
        """
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if not self._usable or self._pending is not None or self._subscribing:
            raise TransportProtocolError("transport unavailable or already pending")
        if request.request_id in self._used_ids or len(self._used_ids) >= self.MAX_REQUESTS:
            raise TransportProtocolError("use a fresh request_id or new session")
        payload = request.to_bytes()
        completed = False
        try:
            async with asyncio.timeout(timeout):
                if not self._registered:
                    await self.subscribe(timeout=timeout)
                self._pending = request.request_id
                self._used_ids.add(request.request_id)
                await self.session.send(encode_gamescript(payload))
                response = None
                receipt = None
                while response is None:
                    chunk = await self.session.receive(4096)
                    if not chunk:
                        self._decoder.finish()
                        raise TransportDisconnected("disconnect before world_info response")
                    for kind, body in self._decoder.feed_frames(chunk):
                        if kind == SERVER_GAMESCRIPT:
                            if response is not None:
                                raise TransportProtocolError("duplicate world_info response")
                            response = decode_gamescript(body)
                            self.response_payload = response
                            receipt = WorldInfoReceipt.correlate(payload, response)
                        elif kind == ServerLifecyclePacket.SHUTDOWN:
                            raise TransportDisconnected("server shutdown during world_info")
                        elif kind in ServerLifecyclePacket:
                            raise TransportProtocolError("world_info runtime changed/error")
                assert receipt is not None
                # Independently ordered Python chain already reached receipt creation.
                # Drain all packets through an ordered protocol barrier, rejecting a
                # queued second response even when it arrives in a different read.
                token = 0x154
                await self.session.send(encode_admin_ping(token))
                barrier = False
                while not barrier:
                    chunk = await self.session.receive(4096)
                    if not chunk:
                        self._decoder.finish()
                        raise TransportDisconnected(
                            "disconnect before world_info completion barrier"
                        )
                    for kind, body in self._decoder.feed_frames(chunk):
                        if kind == SERVER_GAMESCRIPT:
                            raise TransportProtocolError("duplicate/unrelated world_info response")
                        if kind == 126:
                            if body != struct.pack("<I", token):
                                raise TransportProtocolError("wrong world_info completion token")
                            barrier = True
                        elif kind == ServerLifecyclePacket.SHUTDOWN:
                            raise TransportDisconnected("server shutdown after world_info response")
                        elif kind in ServerLifecyclePacket:
                            raise TransportProtocolError("world_info runtime changed/error")
                result = WorldInfoExchange(payload, response, receipt, NETWORK_SEQUENCE, 1, 1, 0)
                result.validate()
                self.response_payload = response
                completed = True
                return result
        except MalformedMessage as error:
            raise MalformedResponse(str(error)) from error
        except AdminProtocolError as error:
            raise MalformedResponse(str(error)) from error
        except BridgeProtocolError as error:
            if isinstance(error, TransportProtocolError):
                raise
            raise TransportProtocolError(str(error)) from error
        except TimeoutError as error:
            raise TransportTimeout("world_info deadline expired") from error
        except OSError as error:
            raise TransportDisconnected("world_info I/O failed") from error
        finally:
            self._pending = None
            if not completed:
                self._usable = False
                await self.session.close()
