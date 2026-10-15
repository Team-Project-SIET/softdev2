"""OpenTTD 15.3 Monocypher compatibility, using a pinned native binding.

Secret objects have opaque reprs and stay in memory. Python and the binding can
make copies: this is not a promise of locked memory or complete memory erasure.
"""

import hashlib
import secrets
from dataclasses import dataclass, field

import monocypher

from app.simulation.openttd.admin_protocol import AdminFrameDecoder, AdminProtocolError


class CryptoError(AdminProtocolError):
    """Invalid key material or authenticated ciphertext; no secret diagnostics."""


def _size(value: bytes, size: int) -> None:
    if not isinstance(value, bytes) or len(value) != size:
        raise CryptoError("invalid cryptographic field length")


@dataclass(frozen=True)
class AuthorizedKey:
    _secret: bytes = field(repr=False)
    public_key: bytes

    def __post_init__(self) -> None:
        _size(self._secret, 32)
        _size(self.public_key, 32)
        if self.public_key != monocypher.x25519_public_key(self._secret):
            raise CryptoError("public key does not match secret")

    @classmethod
    def from_bytes(cls, secret: bytes) -> AuthorizedKey:
        _size(secret, 32)
        return cls(secret, monocypher.x25519_public_key(secret))

    @classmethod
    def from_hex(cls, secret: str) -> AuthorizedKey:
        if not isinstance(secret, str) or len(secret) != 64:
            raise CryptoError("invalid private key encoding")
        try:
            return cls.from_bytes(bytes.fromhex(secret))
        except ValueError:
            raise CryptoError("invalid private key encoding") from None

    @classmethod
    def generate(cls) -> AuthorizedKey:
        return cls.from_bytes(secrets.token_bytes(32))

    @property
    def public_hex(self) -> str:
        return self.public_key.hex()

    @property
    def public_sha256(self) -> str:
        return hashlib.sha256(self.public_key).hexdigest()


@dataclass(frozen=True)
class DerivedKeys:
    client_to_server: bytes = field(repr=False)
    server_to_client: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _size(self.client_to_server, 32)
        _size(self.server_to_client, 32)


def derive_keys(client: AuthorizedKey, server_public: bytes) -> DerivedKeys:
    _size(server_public, 32)
    shared = monocypher.x25519(client._secret, server_public)
    if shared == bytes(32):
        raise CryptoError("invalid peer public key")
    # Exact network_crypto.cpp order; AuthorizedKey has empty extra payload.
    material = hashlib.blake2b(shared + server_public + client.public_key, digest_size=64).digest()
    return DerivedKeys(material[:32], material[32:])


def authentication_response(
    client: AuthorizedKey, keys: DerivedKeys, nonce: bytes, message: bytes
) -> bytes:
    _size(nonce, 24)
    _size(message, 8)
    mac, cipher = monocypher.lock(keys.client_to_server, nonce, message, client.public_key)
    return client.public_key + mac + cipher


class PacketCipher:
    """One persistent directional Monocypher context, closed on any decode failure."""

    def __init__(self, key: bytes, nonce: bytes) -> None:
        _size(key, 32)
        _size(nonce, 24)
        self._context = monocypher.IncrementalAuthenticatedEncryption(key, nonce)
        self._closed = False

    def close(self) -> None:
        self._closed = True
        self._context = None

    def _validate(self, frame: bytes, minimum: int) -> None:
        if self._closed:
            raise CryptoError("cipher is closed")
        if (
            len(frame) < minimum
            or len(frame) > AdminFrameDecoder.MAX_FRAME_LENGTH
            or int.from_bytes(frame[:2], "little") != len(frame)
        ):
            self.close()
            raise CryptoError("invalid encrypted packet framing")

    def encrypt(self, frame: bytes) -> bytes:
        self._validate(frame, 3)
        length = len(frame) + 16
        if length > AdminFrameDecoder.MAX_FRAME_LENGTH:
            self.close()
            raise CryptoError("encrypted packet exceeds maximum length")
        assert self._context is not None
        mac, ciphertext = self._context.lock(frame[2:])
        return length.to_bytes(2, "little") + mac + ciphertext

    def decrypt(self, frame: bytes) -> bytes:
        self._validate(frame, 19)
        assert self._context is not None
        plaintext = self._context.unlock(frame[2:18], frame[18:])
        if plaintext is None:
            self.close()
            raise CryptoError("packet authentication failed")
        return (len(frame) - 16).to_bytes(2, "little") + bytes(plaintext)
