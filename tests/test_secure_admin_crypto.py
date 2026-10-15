"""Public deterministic test seeds; never use these credentials for a real server."""

import json
from pathlib import Path

import monocypher
import pytest

from app.simulation.openttd.admin_crypto import (
    AuthorizedKey,
    CryptoError,
    PacketCipher,
    authentication_response,
    derive_keys,
)
from app.simulation.openttd.admin_protocol import encode_admin_frame

V = json.loads((Path(__file__).parent / "fixtures/openttd_15_3_crypto_vectors.json").read_text())


def test_public_derivation_and_reference_key_ordering():
    key = AuthorizedKey.from_bytes(bytes(range(32)))
    assert key.public_hex == V["client_public"]
    assert key.public_key == bytes.fromhex(V["client_public"])
    keys = derive_keys(key, bytes.fromhex(V["server_public"]))
    assert keys.client_to_server.hex() == V["derived"][:64]
    assert keys.server_to_client.hex() == V["derived"][64:]
    assert bytes(range(32)).hex() not in repr(key)


@pytest.mark.parametrize("material", [b"", bytes(31), bytes(33)])
def test_reject_malformed_private(material):
    with pytest.raises(CryptoError):
        AuthorizedKey.from_bytes(material)


@pytest.mark.parametrize("public", [b"", bytes(31), bytes(33), bytes(32), b"\x01" + bytes(31)])
def test_invalid_peer_fails_closed(public):
    with pytest.raises(CryptoError):
        derive_keys(AuthorizedKey.from_bytes(bytes(range(32))), public)


def test_auth_response_reference_and_validation():
    client = AuthorizedKey.from_bytes(bytes(range(32)))
    keys = derive_keys(client, bytes.fromhex(V["server_public"]))
    nonce = bytes(range(64, 88))
    response = authentication_response(client, keys, nonce, bytes(range(112, 120)))
    assert len(response) == 56
    assert response.hex() == V["client_public"] + V["auth_mac"] + V["auth_cipher"]
    assert monocypher.unlock(
        keys.client_to_server, nonce, response[32:48], response[48:], response[:32]
    ) == bytes(range(112, 120))
    assert (
        monocypher.unlock(keys.client_to_server, nonce, response[32:48], response[48:], bytes(32))
        is None
    )


@pytest.mark.parametrize("direction", ["client", "server"])
def test_sequential_reference_packets(direction):
    material = bytes.fromhex(V["derived"])
    key = material[:32] if direction == "client" else material[32:]
    writer = PacketCipher(key, bytes(range(88, 112)))
    reader = PacketCipher(key, bytes(range(88, 112)))
    for i in range(3):
        plain = encode_admin_frame(6 if direction == "client" else 124, b"pi" + str(i).encode())
        cipher = writer.encrypt(plain)
        assert cipher.hex() == V[f"{direction}_{i}"]
        assert int.from_bytes(cipher[:2], "little") == len(plain) + 16
        assert reader.decrypt(cipher) == plain


@pytest.mark.parametrize("damage", ["mac", "cipher", "truncated", "plaintext", "direction"])
def test_packet_corruption_fails_closed(damage):
    frame = bytearray.fromhex(V["client_0"])
    material = bytes.fromhex(V["derived"])
    key = material[32:] if damage == "direction" else material[:32]
    if damage == "mac":
        frame[2] ^= 1
    if damage == "cipher":
        frame[-1] ^= 1
    if damage == "truncated":
        frame = frame[:-1]
    if damage == "plaintext":
        frame = encode_admin_frame(103, b"\x03\0")
    reader = PacketCipher(key, bytes(range(88, 112)))
    with pytest.raises(CryptoError):
        reader.decrypt(bytes(frame))
    with pytest.raises(CryptoError, match="closed"):
        reader.decrypt(bytes.fromhex(V["client_0"]))


def test_ephemeral_keys_and_hex_policy():
    first, second = AuthorizedKey.generate(), AuthorizedKey.generate()
    assert first.public_key != second.public_key
    assert len(first.public_hex) == 64 and len(first.public_sha256) == 64
    for invalid in ["z" * 64, "aa", " " * 64]:
        with pytest.raises(CryptoError):
            AuthorizedKey.from_hex(invalid)


def test_shared_secret_agreement_against_reference():
    client_public = bytes.fromhex(V["client_public"])
    server_public = bytes.fromhex(V["server_public"])
    assert monocypher.x25519(bytes(range(32)), server_public).hex() == V["shared"]
    assert monocypher.x25519(bytes(range(32, 64)), client_public).hex() == V["shared"]


@pytest.mark.parametrize("position", [0, 15, 16, 23])
def test_auth_mac_and_cipher_corruption(position):
    keys = bytes.fromhex(V["derived"])
    data = bytearray.fromhex(V["auth_mac"] + V["auth_cipher"])
    data[position] ^= 1
    assert (
        monocypher.unlock(
            keys[:32],
            bytes(range(64, 88)),
            bytes(data[:16]),
            bytes(data[16:]),
            bytes.fromhex(V["client_public"]),
        )
        is None
    )


@pytest.mark.parametrize("size", [0, 23, 25])
def test_stream_nonce_lengths(size):
    with pytest.raises(CryptoError):
        PacketCipher(bytes(32), bytes(size))
