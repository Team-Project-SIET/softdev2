"""RFC 8032 Ed25519 verification through the maintained cryptography package.

The B2 resolution (docs/handoff/2026-10-17/ed25519-verifier-preference.md):
the runner's security-critical signature-verification path executes this
module instead of the vendored pure-Python ``ed25519_rfc8032`` reference,
while the standard itself is unchanged. The ``cryptography`` package is
maintained upstream and builds on a native crypto stack that links OpenSSL's
libcrypto on CPython, and its Ed25519 primitive is independently
interoperable with every RFC 8032 conformant tool: signatures remain the
standard byte encodings over the canonical authorization bytes, whatever
produces them (including the vendored ``sign`` reference tooling — the two
implementations' byte-identical agreement is pinned in the test-suite).

Invariants preserved by this migration:

* authorization payload schema, canonical JSON encoding and digests are
  untouched (they live in ``operator_authorization``);
* operator key identity remains ``sha256-ed25519-public-key`` over the raw
  32-byte key, whose stored encodings are still validated by
  ``ed25519_rfc8032.check_public``;
* retained replay evidence re-verifies: the maintained backend accepts the
  identical RFC 8032 signatures the vendored reference accepted.

``verify`` is total exactly like the vendored reference: any malformed input
(wrong types, wrong lengths, un-decodable points) converts to ``False``
instead of raising, so tampered evidence can never convert a crash into an
acceptance. ``sign`` is deliberately absent here: issuance is operator-held
and performed off the runner host with conformant tooling; the vendored
``sign`` stays the pinned vector-image reference inside the test-suite.
"""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7 verify through the maintained backend; total.

    The vendored reference's input contract is enforced first (bytes-like
    values, 32-octet public key, 64-octet signature); the maintained
    implementation then evaluates the group equation. Any malformed input
    or failed check is ``False`` — verify never raises on
    attacker-controlled bytes.
    """
    if any(not isinstance(value, (bytes, bytearray)) for value in (public, message, signature)):
        return False
    if len(public) != 32 or len(signature) != 64:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes(public)).verify(bytes(signature), bytes(message))
    except Exception:  # noqa: BLE001 - total: every library failure rejects
        return False
    return True
