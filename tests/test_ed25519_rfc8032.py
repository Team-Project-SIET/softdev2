"""RFC 8032 Ed25519 conformance and cross-implementation tests.

The vendored production module (app.simulation.openttd.proof.ed25519_rfc8032)
is pinned to Published Standard vectors from RFC 8032 §7.1 and cross-checked
against the RFC's own §6 Python illustration implementation (copied below, the
two known errata of the published snippet corrected: the missing ``raise`` on
the bad signature length branch). These exist to prove that a signature
produced by an independent, interoperable Ed25519 implementation verifies in
this repository, and that wrong-message, wrong-key and malformed inputs are
rejected without exceptions.
"""

import hashlib
import json
import unittest.mock

import pytest

from app.simulation.openttd.proof import ed25519_rfc8032, operator_authorization

# RFC 8032 §7.1 TEST vectors (secret key seed, public key, message, signature).
VECTOR_1 = dict(
    seed="9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
    public="d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
    message="",
    signature=(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    ),
)
VECTOR_2 = dict(
    seed="4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
    public="3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
    message="72",
    signature=(
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
    ),
)
VECTOR_3 = dict(
    seed="c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
    public="fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
    message="af82",
    signature=(
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
        "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"
    ),
)


# --- Independent reference: RFC 8032 §6 illustration, verbatim -------------


def sha512(s):
    return hashlib.sha512(s).digest()


p = 2**255 - 19


def modp_inv(x):
    return pow(x, p - 2, p)


d = -121665 * modp_inv(121666) % p

q = 2**252 + 27742317777372353535851937790883648493


def sha512_modq(s):
    return int.from_bytes(sha512(s), "little") % q


def point_add(P, Q):
    A, B = (P[1] - P[0]) * (Q[1] - Q[0]) % p, (P[1] + P[0]) * (Q[1] + Q[0]) % p
    C, D = 2 * P[3] * Q[3] * d % p, 2 * P[2] * Q[2] % p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F, G * H, F * G, E * H)


def point_mul(s, P):
    Q = (0, 1, 1, 0)  # Neutral element
    while s > 0:
        if s & 1:
            Q = point_add(Q, P)
        P = point_add(P, P)
        s >>= 1
    return Q


def point_equal(P, Q):
    if (P[0] * Q[2] - Q[0] * P[2]) % p != 0:
        return False
    if (P[1] * Q[2] - Q[1] * P[2]) % p != 0:
        return False
    return True


modp_sqrt_m1 = pow(2, (p - 1) // 4, p)


def recover_x(y, sign):
    if y >= p:
        return None
    x2 = (y * y - 1) * modp_inv(d * y * y + 1)
    if x2 == 0:
        if sign:
            return None
        else:
            return 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = x * modp_sqrt_m1 % p
    if (x * x - x2) % p != 0:
        return None
    if (x & 1) != sign:
        x = p - x
    return x


g_y = 4 * modp_inv(5) % p
g_x = recover_x(g_y, 0)
G = (g_x, g_y, 1, g_x * g_y % p)


def point_compress(P):
    zinv = modp_inv(P[2])
    x = P[0] * zinv % p
    y = P[1] * zinv % p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def point_decompress(s):
    if len(s) != 32:
        raise Exception("Invalid input length for decompression")
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = recover_x(y, sign)
    if x is None:
        return None
    else:
        return (x, y, 1, x * y % p)


def secret_expand(secret):
    if len(secret) != 32:
        raise Exception("Bad size of private key")
    h = sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return (a, h[32:])


def secret_to_public(secret):
    (a, dummy) = secret_expand(secret)
    return point_compress(point_mul(a, G))


def reference_sign(secret, msg):
    a, prefix = secret_expand(secret)
    A = point_compress(point_mul(a, G))
    r = sha512_modq(prefix + msg)
    R = point_mul(r, G)
    Rs = point_compress(R)
    h = sha512_modq(Rs + A + msg)
    s = (r + h * a) % q
    return Rs + int.to_bytes(s, 32, "little")


def reference_verify(public, msg, signature):
    if len(public) != 32:
        raise Exception("Bad public key length")
    if len(signature) != 64:
        # Errata of the published illustration: the release text dropped the
        # raise on this branch; length control must actually reject.
        raise Exception("Bad signature length")
    A = point_decompress(public)
    if not A:
        return False
    Rs = signature[:32]
    R = point_decompress(Rs)
    if not R:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= q:
        return False
    h = sha512_modq(Rs + public + msg)
    sB = point_mul(s, G)
    hA = point_mul(h, A)
    return point_equal(sB, point_add(R, hA))


# --- Conformance ------------------------------------------------------------


@pytest.mark.parametrize("vector", [VECTOR_1, VECTOR_2, VECTOR_3], ids=["TEST1", "TEST2", "TEST3"])
def test_rfc8032_sign_matches_published_vectors(vector):
    seed = bytes.fromhex(vector["seed"])
    message = bytes.fromhex(vector["message"])
    signature = ed25519_rfc8032.sign(seed, message)
    assert signature == bytes.fromhex(vector["signature"])
    # Cross-implementation agreement: the RFC illustration signs identically.
    assert reference_sign(seed, message) == signature


@pytest.mark.parametrize("vector", [VECTOR_1, VECTOR_2, VECTOR_3], ids=["TEST1", "TEST2", "TEST3"])
def test_rfc8032_verify_accepts_published_vectors(vector):
    public = bytes.fromhex(vector["public"])
    message = bytes.fromhex(vector["message"])
    signature = bytes.fromhex(vector["signature"])
    assert ed25519_rfc8032.verify(public, message, signature) is True


def test_public_from_seed_matches_the_published_public_key():
    for vector in (VECTOR_1, VECTOR_2, VECTOR_3):
        assert ed25519_rfc8032.public_from_seed(bytes.fromhex(vector["seed"])) == bytes.fromhex(
            vector["public"]
        )


def test_sign_and_verify_round_trip_and_mutations():
    seed = bytes.fromhex(VECTOR_1["seed"])
    public = bytes.fromhex(VECTOR_1["public"])
    message = b"canonical authorization bytes"
    signature = ed25519_rfc8032.sign(seed, message)
    assert ed25519_rfc8032.verify(public, message, signature) is True
    # The independent RFC implementation verifies the same signature ...
    assert reference_verify(public, message, signature) is True
    # ... and both implementations reject the wrong message.
    assert ed25519_rfc8032.verify(public, message + b"!", signature) is False
    assert reference_verify(public, message + b"!", signature) is False
    # Wrong key.
    other_public = ed25519_rfc8032.public_from_seed(bytes.fromhex(VECTOR_2["seed"]))
    assert ed25519_rfc8032.verify(other_public, message, signature) is False


def test_implementation_cross_signs_for_the_reference():
    for vector in (VECTOR_1, VECTOR_2, VECTOR_3):
        seed = bytes.fromhex(vector["seed"])
        message = bytes.fromhex(vector["message"]) + b"|cross"
        a = ed25519_rfc8032.sign(seed, message)
        b = reference_sign(seed, message)
        assert a == b
        public = bytes.fromhex(vector["public"])
        assert ed25519_rfc8032.verify(public, message, b)
        assert reference_verify(public, message, a)


def test_malformed_signature_rejected():
    public = bytes.fromhex(VECTOR_1["public"])
    for signature in (
        b"",  # empty
        bytes.fromhex(VECTOR_1["signature"]) + b"\x00",  # 65 bytes
        bytes.fromhex(VECTOR_1["signature"])[:63],  # 63 bytes
        b"\x00" * 64,  # well-formed length, undecodable R
    ):
        assert ed25519_rfc8032.verify(public, b"", signature) is False


def test_s_bound_and_point_failures_rejected():
    public = bytes.fromhex(VECTOR_1["public"])
    signature = bytes.fromhex(VECTOR_1["signature"])
    # S >= L must be rejected.
    over = signature[:32] + (2**252 + 27742317777372353535851937790883648493).to_bytes(32, "little")
    assert not ed25519_rfc8032.verify(public, b"", over)
    # Undecodable public keys (all zeros have no square root) never raise.
    assert ed25519_rfc8032.verify(b"\x00" * 32, b"", signature) is False
    # Wrong length public keys never raise.
    assert ed25519_rfc8032.verify(b"\x00" * 31, b"", signature) is False


def test_sign_rejects_bad_seed_lengths():
    with pytest.raises(ValueError):
        ed25519_rfc8032.sign(b"\x00" * 31, b"msg")
    with pytest.raises(ValueError):
        ed25519_rfc8032.sign(b"\x00" * 64, b"msg")


def test_reference_impl_agrees_on_vector_signatures_and_all_datatypes():
    """The vendored module and the RFC illustration stay byte-identical."""
    for vector in (VECTOR_1, VECTOR_2, VECTOR_3):
        seed = bytes.fromhex(vector["seed"])
        message = bytes.fromhex(vector["message"])
        assert ed25519_rfc8032.sign(seed, message) == reference_sign(seed, message)
        assert ed25519_rfc8032.verify(
            bytes.fromhex(vector["public"]), message, bytes.fromhex(vector["signature"])
        )


# --- Authorization-layer interoperability -----------------------------------


def test_authorization_layer_verifies_an_independently_signed_record(tmp_path):
    """The canonical payload signed by the RFC reference verifies in production."""
    payload = {"milestone": "D2-CLEARING", "probe": True, "schema": "probe"}
    message = operator_authorization.canonical_authorization_bytes(payload)
    signature = reference_sign(bytes.fromhex(VECTOR_1["seed"]), message)
    record = {"payload": payload, "signature": signature.hex()}
    directory = tmp_path / "candidate"
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
            VECTOR_1["public"],
        ),
    ):
        verified = operator_authorization.verify_authorization(directory, {}, "0" * 64)
        assert verified.record == record
        assert verified.authorization_sha256 == operator_authorization.record_digest(directory)
        # The identity corresponds to the pinned anchor under which it verified.
        assert verified.operator_key_identity == operator_authorization.operator_key_identity(
            VECTOR_1["public"]
        )
        # Grant minting derives from verified facts and re-verification holds.
        grant = operator_authorization.grant_launch(directory, {}, "0" * 64)
        operator_authorization.reverify_launch_grant(directory, grant, {}, "0" * 64)
        assert grant.authorization_sha256 == verified.authorization_sha256
        # A single-use grant refuses its second consumption by construction.
        grant.consume()
        with pytest.raises(
            operator_authorization.ClearingAuthorizationError, match="already consumed"
        ):
            grant.consume()


def test_authorization_layer_rejects_forged_and_malformed(tmp_path):
    payload = {"milestone": "D2-CLEARING", "probe": True}
    message = operator_authorization.canonical_authorization_bytes(payload)
    other = reference_sign(bytes.fromhex(VECTOR_2["seed"]), message)
    record = {"payload": payload, "signature": other.hex()}
    directory = tmp_path / "candidate"
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
            VECTOR_1["public"],
        ),
    ):
        with pytest.raises(
            operator_authorization.ClearingAuthorizationError,
            match="not signed by the seeded operator anchor",
        ):
            operator_authorization.verify_authorization(directory, {}, "0" * 64)
        # Malformed signature bytes (wrong length) are rejected, not crashed on.
        short = {"payload": payload, "signature": "aa"}
        (directory / "AUTHORIZATION.json").write_text(json.dumps(short))
        with pytest.raises(operator_authorization.ClearingAuthorizationError):
            operator_authorization.verify_authorization(directory, {}, "0" * 64)
        # Malformed anchors (undecodable point: y >= p) are refused explicitly.
        with unittest.mock.patch.object(
            operator_authorization, "OPERATOR_PUBLIC_KEY_HEX", "ff" * 32
        ):
            with pytest.raises(
                operator_authorization.ClearingAuthorizationError,
                match="decodable 32-byte Ed25519 public key",
            ):
                operator_authorization.verify_authorization(directory, {}, "0" * 64)


def test_anchor_key_identity_is_deterministic():
    assert operator_authorization.operator_key_identity(
        VECTOR_1["public"]
    ) == operator_authorization.operator_key_identity(VECTOR_1["public"])
    assert operator_authorization.operator_key_identity(
        VECTOR_1["public"]
    ) != operator_authorization.operator_key_identity(VECTOR_2["public"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
