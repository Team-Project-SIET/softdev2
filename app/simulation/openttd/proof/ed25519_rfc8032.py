"""RFC 8032 Ed25519 — the standard PureEdDSA signature scheme, vendored.

Why this module exists, in this repository, today:

* The runner's operator-authorization gate must use a *standard,
  independently interoperable* Ed25519 so an off-host operator can sign with
  any conformant tool and verification here must match byte for byte. The
  previously used ``monocypher.signature_sign``/``signature_check`` binding
  exposes BLAKE2b-based EdDSA (Monocypher's ``crypto_eddsa_*``), which is a
  different scheme and must never be mislabeled as Ed25519.
* The algorithm published in RFC 8032 §5.1 (the Ed25519 instance of
  PureEdDSA) is vendored here. Since 2026-10-20 the verified ``.venv``
  carries the maintained ``cryptography`` package and the runner's
  signature-verification path executes
  ``app.simulation.openttd.proof.ed25519_cryptography`` instead of this
  module, which remains the pinned reference implementation (published
  vectors, ``check_public`` key validation, reference ``sign`` tooling).
* Every path is pinned by published §7.1 vectors and cross-verified in the
  test-suite against the RFC's own §6 illustration implementation, so the
  vendored code can never silently become a non-standard EdDSA variant.

The private key (the 32-octet RFC seed) is operator-held material generated
and stored off the runner host. Verification is the security-critical path
on this host: ``verify`` is total (converts every malformed input to
``False``), so tampered evidence can never crash its way into being accepted.

Threat model note: like every pure-Python build, ``sign`` is not
constant-time. The runner only verifies; operators should sign off-host with
their own audited tooling and may treat ``sign`` here as reference tooling.
"""

import hashlib

# RFC 7748 p and the RFC 8032 §5.1 Ed25519 parameters.
P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493  # group order of the base point
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _inv(x: int) -> int:
    """x^-1 mod p (never zero on valid per-RFC inputs)."""
    return pow(x, P - 2, P)


def _sha512_modq(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % Q


def _recover_x(y: int, sign_bit: int):
    """RFC 8032 §5.1.1 square-root recovery; None when no root exists."""
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign_bit else 0
    x = pow(x2, (P + 3) // 8, P)
    if x * x % P != x2:
        x = x * SQRT_M1 % P
    if x * x % P != x2:
        return None
    if (x & 1) != sign_bit:
        x = P - x
    return x


def _compress(point) -> bytes:
    """RFC 8032 §5.1.2 point encoding (32 octets)."""
    x, y, z, _ = point
    zinv = _inv(z)
    encoded_y = y * zinv % P
    encoded_x = x * zinv % P
    return int.to_bytes(encoded_y | ((encoded_x & 1) << 255), 32, "little")


def _decompress(data: bytes):
    """RFC 8032 §5.1.3 point decode; None on any malformed encoding."""
    if not isinstance(data, (bytes, bytearray)) or len(data) != 32:
        return None
    raw = int.from_bytes(data, "little")
    sign_bit = raw >> 255
    y = raw & ((1 << 255) - 1)
    if y >= P:
        return None
    x = _recover_x(y, sign_bit)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def _point_add(first, second):
    """Complete extended-coordinate addition for a = -1, RFC 8032 §5.1.4."""
    x1, y1, z1, t1 = first
    x2, y2, z2, t2 = second
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = t1 * 2 * D * t2 % P
    dd = z1 * 2 * z2 % P
    e, f, g, h = b - a, dd - c, dd + c, b + a
    return (e * f, g * h, f * g, e * h)


def _point_mul(scalar: int, point):
    """Double-and-add over the complete addition law."""
    result = (0, 1, 1, 0)  # neutral element
    while scalar > 0:
        if scalar & 1:
            result = _point_add(result, point)
        point = _point_add(point, point)
        scalar >>= 1
    return result


def _secret_expand(seed: bytes):
    """RFC 8032 §5.1.5 key pruning: scalar a and the nonce prefix."""
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
        raise ValueError("Ed25519 seed must be exactly 32 bytes")
    digest = hashlib.sha512(bytes(seed)).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8  # clear the low three bits ...
    scalar |= 1 << 254  # ... and set the second-highest bit
    return scalar, digest[32:]


def _base_point():
    y = 4 * _inv(5) % P
    x = _recover_x(y, 0)
    return (x, y, 1, x * y % P)


def public_from_seed(seed: bytes) -> bytes:
    """RFC 8032 §5.1.5 public-key derivation from the 32-byte seed."""
    scalar, _ = _secret_expand(seed)
    return _compress(_point_mul(scalar, _base_point()))


def sign(seed: bytes, message: bytes) -> bytes:
    """RFC 8032 §5.1.6 PureEdDSA sign; deterministic 64-byte signature."""
    scalar, prefix = _secret_expand(seed)
    encoded_public = _compress(_point_mul(scalar, _base_point()))
    r = _sha512_modq(prefix + message)
    encoded_r = _compress(_point_mul(r, _base_point()))
    k = _sha512_modq(encoded_r + encoded_public + message)
    encoded_s = ((r + k * scalar) % Q).to_bytes(32, "little")
    return encoded_r + encoded_s


def check_public(public: bytes) -> bool:
    """Total wellformedness check for a stored 32-byte Ed25519 public key."""
    if not isinstance(public, (bytes, bytearray)) or len(public) != 32:
        return False
    return _decompress(bytes(public)) is not None


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7 verify; total — any malformed input is rejected.

    Lengths, point decodability and the scalar bound are all enforced before
    the group equation is evaluated. Verify never raises on
    attacker-controlled bytes, so no tampered evidence path can convert a
    crash into an acceptance.
    """
    if any(not isinstance(value, (bytes, bytearray)) for value in (public, message, signature)):
        return False
    if len(public) != 32 or len(signature) != 64:
        return False
    point_a = _decompress(public)
    if point_a is None:
        return False
    encoded_r = bytes(signature[:32])
    point_r = _decompress(encoded_r)
    if point_r is None:
        return False
    s = int.from_bytes(bytes(signature[32:]), "little")
    if s >= Q:
        return False
    k = _sha512_modq(encoded_r + bytes(public) + bytes(message))
    # [S]B == R + [k]A — the RFC's sufficient (cofactor-less) verification.
    # Both sides are (valid but different) homogeneous representatives, so
    # equality is projective: x1*z2 == x2*z1 and y1*z2 == y2*z1 (mod p).
    left = _point_mul(s, _base_point())
    right = _point_add(point_r, _point_mul(k, point_a))
    return (left[0] * right[2] - right[0] * left[2]) % P == 0 and (
        left[1] * right[2] - right[1] * left[2]
    ) % P == 0
