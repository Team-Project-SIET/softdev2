"""Maintained cryptography-backed Ed25519 verification (the B2 resolution).

The runner's operator-authorization gate verifies operator signatures with
the maintained ``cryptography`` package (installed 2026-10-20, see
docs/handoff/2026-10-17/ed25519-verifier-preference.md) instead of executing
the vendored pure-Python reference module. These tests pin that path:

* the published RFC 8032 §7.1 vectors verify through the maintained backend;
* the maintained backend and the vendored reference agree on every input
  class — valid, tampered and malformed — so the two implementations can
  never silently diverge on what counts as a valid signature;
* the vendored reference's deterministic signatures remain byte-identical to
  the maintained package's signatures (issuance/replay interoperability);
* the authorization layer still binds candidate identities end to end when
  a vendored-signed record is verified through the maintained backend.
"""

import unittest.mock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.simulation.openttd.proof import (
    ed25519_cryptography,
    ed25519_rfc8032,
    operator_authorization,
)

# RFC 8032 §7.1 TEST vectors (seed, public key, message, signature) — the same
# published vectors that pin the vendored reference in test_ed25519_rfc8032.py.
VECTORS = (
    dict(
        seed="9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        public="d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        message="",
        signature=(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        ),
    ),
    dict(
        seed="4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        public="3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        message="72",
        signature=(
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
            "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        ),
    ),
    dict(
        seed="c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        public="fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        message="af82",
        signature=(
            "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
            "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"
        ),
    ),
)


@pytest.mark.parametrize("vector", VECTORS, ids=["TEST1", "TEST2", "TEST3"])
def test_published_vectors_verify_through_the_maintained_backend(vector):
    public = bytes.fromhex(vector["public"])
    message = bytes.fromhex(vector["message"])
    signature = bytes.fromhex(vector["signature"])
    assert ed25519_cryptography.verify(public, message, signature) is True


def test_maintained_backend_and_vendored_reference_agree_on_tampering():
    for index, vector in enumerate(VECTORS):
        seed = bytes.fromhex(vector["seed"])
        public = bytes.fromhex(vector["public"])
        message = b"tampering probe " + bytes.fromhex(vector["message"])
        signature = ed25519_rfc8032.sign(seed, message)
        # Both implementations accept the valid signature.
        assert ed25519_cryptography.verify(public, message, signature) is True
        assert ed25519_rfc8032.verify(public, message, signature) is True
        # Wrong message: both reject.
        assert ed25519_cryptography.verify(public, message + b"!", signature) is False
        assert ed25519_rfc8032.verify(public, message + b"!", signature) is False
        # Single flipped signature bit: both reject.
        flipped = signature[:-1] + bytes([signature[-1] ^ 1])
        assert ed25519_cryptography.verify(public, message, flipped) is False
        assert ed25519_rfc8032.verify(public, message, flipped) is False
        # Wrong key: both reject.
        wrong_public = bytes.fromhex(VECTORS[(index + 1) % len(VECTORS)]["public"])
        assert ed25519_cryptography.verify(wrong_public, message, signature) is False
        assert ed25519_rfc8032.verify(wrong_public, message, signature) is False


def test_sign_interop_between_the_two_implementations_is_byte_identical():
    """The vendored reference signs exactly like the maintained package."""
    for vector in VECTORS:
        seed = bytes.fromhex(vector["seed"])
        message = bytes.fromhex(vector["message"]) + b"|interop"
        vendored = ed25519_rfc8032.sign(seed, message)
        maintained = Ed25519PrivateKey.from_private_bytes(seed).sign(message)
        assert vendored == maintained
        assert ed25519_cryptography.verify(bytes.fromhex(vector["public"]), message, vendored)
        assert ed25519_rfc8032.verify(bytes.fromhex(vector["public"]), message, maintained)


def test_malformed_inputs_are_total_rejections():
    """Every malformed input class fails closed exactly like the reference."""
    vector = VECTORS[0]
    public = bytes.fromhex(vector["public"])
    signature = bytes.fromhex(vector["signature"])
    malformed = (
        (b"\x00" * 32, signature, b""),  # un-decodable point (no square root)
        (b"\xff" * 32, signature, b""),  # y >= p, key undecodable
        (b"\x00" * 31, signature, b""),  # short public key
        (public + b"\x00", signature, b""),  # long public key
        (public, signature[:63], b""),  # short signature
        (public, b"\x00" * 64, b""),  # well-formed length, un-decodable R
        (public, signature + b"\x00", b""),  # long signature
        ("d75a980182b10ab7", signature, b""),  # public key is text
        (public, 64, b""),  # signature is not bytes
        (public, signature, None),  # message is not bytes
        (public, signature, "msg"),  # message is text
    )
    for public_, signature_, message_ in malformed:
        assert ed25519_cryptography.verify(public_, signature_, message_) is False
        assert ed25519_rfc8032.verify(public_, signature_, message_) is False
    # bytes-like bytearray encodings remain valid in both implementations.
    assert ed25519_cryptography.verify(bytearray(public), b"", bytearray(signature)) is True
    assert ed25519_rfc8032.verify(bytearray(public), b"", bytearray(signature)) is True


def test_authorization_layer_verifies_vendored_signed_records(tmp_path):
    """End-to-end: vendored issuance -> maintained verification -> refusal."""
    payload = {"milestone": "D2-CLEARING", "probe": True, "schema": "probe"}
    record = operator_authorization.sign_authorization_record(payload, VECTORS[0]["seed"])
    directory = tmp_path / "maintained"
    directory.mkdir()
    operator_authorization.write_authorization_record(directory, record)
    with (
        unittest.mock.patch.object(
            operator_authorization,
            "authorization_payload",
            lambda metadata, seal: payload,
        ),
        unittest.mock.patch.object(
            operator_authorization,
            "OPERATOR_PUBLIC_KEY_HEX",
            VECTORS[0]["public"],
        ),
    ):
        verified = operator_authorization.verify_authorization(directory, {}, "0" * 64)
        assert verified.record == record
        assert verified.authorization_sha256 == operator_authorization.record_digest(directory)
    # A record signed by a different key never passes the same anchor.
    forged = operator_authorization.sign_authorization_record(payload, VECTORS[2]["seed"])
    operator_authorization.write_authorization_record(directory, forged)
    with (
        unittest.mock.patch.object(
            operator_authorization,
            "authorization_payload",
            lambda metadata, seal: payload,
        ),
        unittest.mock.patch.object(
            operator_authorization,
            "OPERATOR_PUBLIC_KEY_HEX",
            VECTORS[0]["public"],
        ),
    ):
        with pytest.raises(
            operator_authorization.ClearingAuthorizationError,
            match="not signed by the seeded operator anchor",
        ):
            operator_authorization.verify_authorization(directory, {}, "0" * 64)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
