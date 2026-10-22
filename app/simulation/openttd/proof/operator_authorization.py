"""Operator-issued launch authorization for the D2 clearing candidate (offline).

Three distinct concepts are enforced and never conflated:

1. **Operator-issued authorization** — ``AUTHORIZATION.json`` inside the
   candidate directory, produced by an explicit operator action performed OFF
   the runner host: a standard RFC 8032 Ed25519 signature over the canonical
   authorization payload. The private key (an RFC seed) never exists in this
   repository or in any runner-reachable state; the trusted origin is the
   operator public key pinned below. The operator may sign with any
   conformant Ed25519 tool; eligibility of arbitrary keys/signatures is
   verified through this module only.
2. **Authorization verification** — :func:`verify_authorization` recomputes
   the expected payload from the candidate's own staged facts (prelaunch seal,
   workspace, binary, milestone attempt, target tile, retained source world
   identity, the complete budget table and the exact approved execution
   command) and requires exact equality plus a valid operator signature;
   signature verification executes the maintained cryptography package
   (:mod:`app.simulation.openttd.proof.ed25519_cryptography`), with the
   vendored RFC 8032 module staying as the pinned vector/key reference. No
   runner-supplied boolean, metadata string (the staged PENDING note stays
   descriptive) or self-written file is ever accepted as approval.
3. **One-shot claim consumption** — the runner binds the verified record's
   digest into the exclusively created ``CLAIM.json``; preflight refuses any
   candidate whose claim already exists, so a consumed authorization can
   never authorize again.

The pinned operator anchor is **seeded** (2026-10-21, reviewed provisioning
change per docs/handoff/2026-10-17/operator-key-provisioning.md steps 1-3,
recorded as LOCAL DEVELOPMENT PROOF): the operator generated the Ed25519 key
pair ON this runner host — not off-runner — and committed only the public-key
hex here; the private seed stays in operator-held material outside the Git
repository (``~/.local/share/openttd-operator/operator-private.pem``) and is
never opened, read or signed with by the runner. While the anchor was
unseeded, every launch-capable path failed closed, and a falsy anchor still
does. The runner never signs, never approves and never bypasses this gate;
issuance tooling below exists only for the operator's own use (tests use
synthetic keys inside isolated temporary candidates exclusively).
"""

import hashlib
import json
from pathlib import Path
from typing import NamedTuple

from app.simulation.openttd.proof import ed25519_cryptography, ed25519_rfc8032

AUTHORIZATION_FILE_NAME = "AUTHORIZATION.json"

# BLOCKER 1 trust anchor — SEEDED on 2026-10-21 by the operator (LOCAL
# DEVELOPMENT PROOF, not off-runner key isolation: the key pair was generated
# ON the runner host; only this 32-byte public key entered the repository,
# and the private seed is held outside the Git repository at
# ~/.local/share/openttd-operator/operator-private.pem and is never opened,
# read or used by the runner; see docs/handoff/2026-10-17/
# operator-key-provisioning.md). A falsy value still refuses every
# launch-capable path.
OPERATOR_PUBLIC_KEY_HEX: str | None = (
    "5063982bd28d48573705f334ed4f396618c4930ce21083789dfbbf13a564880f"
)

# Versioned claim evidence: every new-schema D2 claim carries the binding of
# the exact authorization record it launched with (BLOCKER 6).
CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA = "d2-clearing-claim-authorization-v2"

# The launch environment is part of the authorized execution scope (BLOCKER
# 5): the dynamic-loader/interpreter injection vector is refused outright and
# the assembled launch environment is an explicit, exact, allowed baseline.
FORBIDDEN_ENV_KEYS = frozenset(
    (
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "DYLD_FRAMEWORK_PATH",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
    )
)
SAFE_ENV_BASELINES = frozenset(("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR"))

# Stable one-line fingerprint of the pinned Ed25519 anchor: recorded at
# launch and re-checked at replay so evidence can never be silently
# re-verified under a different, rotated operator key (BLOCKER 6).
OPERATOR_KEY_IDENTITY_ALGORITHM = "sha256-ed25519-public-key"


class ClearingAuthorizationError(ValueError):
    """Missing, malformed, untrusted or non-binding operator authorization."""


class VerifiedAuthorization(NamedTuple):
    """The exact verified record and the digests derived from its bytes."""

    record: dict
    authorization_sha256: str
    operator_key_identity: str


class LaunchGrant:
    """Single-use launch authorization bound to one candidate, one claim.

    Only :func:`grant_launch` (which is :func:`verify_authorization` + this
    binding) can mint one. ``launch_identity`` is the stat-identity snapshot
    of the launch-critical runtime taken after verification; the launch
    boundary re-checks it together with the record bytes before any process
    is spawned. :meth:`consume` marks the grant spent: a second launch
    attempt with the same grant is refused.
    """

    def __init__(
        self,
        *,
        directory: Path,
        prelaunch_sha256: str,
        authorization_sha256: str,
        operator_key_identity: str,
        record: dict,
        launch_identity: dict | None = None,
    ) -> None:
        self.directory = directory
        self.prelaunch_sha256 = prelaunch_sha256
        self.authorization_sha256 = authorization_sha256
        self.operator_key_identity = operator_key_identity
        self.record = record
        self.launch_identity = launch_identity
        self.consumed = False

    def consume(self) -> None:
        if self.consumed:
            raise ClearingAuthorizationError("launch grant already consumed")
        self.consumed = True


def canonical_authorization_bytes(payload: dict) -> bytes:
    """Deterministic signed message: canonical JSON (sorted, compact)."""
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def authorization_payload(metadata: dict, seal: str) -> dict:
    """The mandatory binding: exactly the candidate's own authorized scope.

    Built only from the candidate's own staged facts, this makes any unbound
    or altered field (identity, tile, world, budgets, command or digest)
    impossible to satisfy by equality.

    The milestone name comes from the staged prelaunch record itself
    (``metadata.get("milestone", "D2-CLEARING")``), so every sibling ceremony
    reuses this exact scalar-payload shape without a second security
    framework. When the staged plan policy carries an ordered operation
    schedule (a multi-operation milestone), the schedule and its staged
    plan digest join the authorized scope as additive keys; a plan without a
    schedule rebuilds the historical D2 payload byte-for-byte.
    """
    world = metadata["world"]
    plan = metadata["plan_policy"]
    payload = {
        "milestone": metadata.get("milestone", "D2-CLEARING"),
        "attempt": metadata["attempt"],
        "schema": metadata["schema"],
        "workspace": metadata["workspace"],
        "binary_sha256": metadata["binary_sha256"],
        "prelaunch_sha256": seal,
        "target_tile": plan["target_tile"],
        "company": plan["company"],
        "clearing_command": plan["command"],
        "stale_rule": plan["stale_rule"],
        "max_cost": plan["max_cost"],
        "source_world": {
            "retained_directory": world["retained_directory"],
            "source_save": world.get("source_save"),
            "save_sha256": world["save_sha256"],
            "qualified_save_sha256": world.get("qualified_save_sha256"),
            "expected_welcome": world["expected_welcome"],
        },
        "budgets": metadata["budgets"],
        "execution_command": metadata["execution_command"],
    }
    schedule = plan.get("schedule")
    if schedule is not None:
        payload["operation_schedule"] = schedule
        payload["plan_digest"] = plan["plan_digest"]
    return payload


def sign_authorization_record(payload: dict, private_key_hex: str) -> dict:
    """Operator issuance tooling: standard RFC 8032 Ed25519-sign a payload.

    ``private_key_hex`` is the 32-byte RFC seed (edwards25519 §5.1 seed).
    The private key is operator-held material applied off the runner host;
    the announcement record is an ordinary JSON object the operator drops
    into the candidate directory as AUTHORIZATION.json. Tests invoke this
    only with their own synthetic keys inside isolated temporary candidates.
    """
    if not isinstance(private_key_hex, str):
        raise ClearingAuthorizationError("operator private key must be hex text")
    try:
        secret = bytes.fromhex(private_key_hex)
    except ValueError:
        raise ClearingAuthorizationError("malformed operator private key encoding") from None
    try:
        signature = ed25519_rfc8032.sign(secret, canonical_authorization_bytes(payload))
    except ValueError:
        raise ClearingAuthorizationError(
            "operator private key must be a 32-byte RFC 8032 Ed25519 seed"
        ) from None
    return {"payload": payload, "signature": signature.hex()}


def write_authorization_record(directory: Path, record: dict) -> None:
    """Persist an issued record in the operator's canonical JSON style."""
    (directory / AUTHORIZATION_FILE_NAME).write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n"
    )


def record_digest(directory: Path) -> str:
    """SHA-256 of the authorization record, bound into the one-shot claim."""
    try:
        raw = (directory / AUTHORIZATION_FILE_NAME).read_bytes()
    except OSError:
        raise ClearingAuthorizationError("no operator authorization record to bind") from None
    return hashlib.sha256(raw).hexdigest()


def operator_key_identity(public_key_hex: str) -> str:
    """The stable identity of the pinned operator key used at launch."""
    if not isinstance(public_key_hex, str):
        raise ClearingAuthorizationError("operator public key must be hex text")
    try:
        raw = bytes.fromhex(public_key_hex)
    except ValueError:
        raise ClearingAuthorizationError("operator public key is not valid hex") from None
    if len(raw) != 32 or not ed25519_rfc8032.check_public(raw):
        raise ClearingAuthorizationError(
            "operator public key must be a decodable 32-byte Ed25519 key"
        )
    return OPERATOR_KEY_IDENTITY_ALGORITHM + ":" + hashlib.sha256(raw).hexdigest()


def _anchor_key(operator_public_key_hex: str | None) -> bytes:
    anchor = (
        operator_public_key_hex if operator_public_key_hex is not None else OPERATOR_PUBLIC_KEY_HEX
    )
    if not anchor:
        raise ClearingAuthorizationError(
            "operator trust anchor is unseeded; no launch authorization can be verified"
        )
    try:
        anchor_key = bytes.fromhex(str(anchor))
    except ValueError:
        raise ClearingAuthorizationError("operator trust anchor is not valid hex") from None
    if len(anchor_key) != 32 or not ed25519_rfc8032.check_public(anchor_key):
        raise ClearingAuthorizationError(
            "operator trust anchor must be a decodable 32-byte Ed25519 public key"
        )
    return anchor_key


def _read_record(directory: Path) -> tuple[bytes, dict]:
    """The exact record bytes and their parsed shape, or a refusal."""
    path = directory / AUTHORIZATION_FILE_NAME
    if not path.is_file():
        raise ClearingAuthorizationError(
            "no operator authorization record: the candidate cannot launch"
        )
    raw = path.read_bytes()
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        raise ClearingAuthorizationError(
            "operator authorization record is not valid JSON"
        ) from None
    if (
        not isinstance(record, dict)
        or set(record) != {"payload", "signature"}
        or not isinstance(record.get("payload"), dict)
        or not isinstance(record.get("signature"), str)
    ):
        raise ClearingAuthorizationError("operator authorization record is malformed")
    return raw, record


def _check_record_signature(record: dict, anchor_key: bytes, expected_payload: dict) -> None:
    if record["payload"] != expected_payload:
        raise ClearingAuthorizationError(
            "operator authorization does not bind this candidate identity"
        )
    try:
        signature = bytes.fromhex(record["signature"])
    except ValueError:
        raise ClearingAuthorizationError("operator authorization signature is not hex") from None
    if len(signature) != 64 or not ed25519_cryptography.verify(
        anchor_key, canonical_authorization_bytes(record["payload"]), signature
    ):
        raise ClearingAuthorizationError(
            "operator authorization is not signed by the seeded operator anchor"
        )


def verify_authorization(
    directory: Path,
    metadata: dict,
    seal: str,
    *,
    operator_public_key_hex: str | None = None,
) -> VerifiedAuthorization:
    """The mandatory launch gate; before claim consumption, never mutates state.

    Refusal order: trusted anchor seeded -> record present -> well formed ->
    candidate binding equality -> trusted-origin RFC 8032 Ed25519 signature.
    The verification anchor defaults to the pinned operator key; tests may
    inject their own synthetic anchor, which is never the production value.
    The returned object carries the exact verified record bytes' digest so
    the one-shot claim and the launch boundary pin the same bytes.
    """
    anchor_key = _anchor_key(operator_public_key_hex)
    raw, record = _read_record(directory)
    _check_record_signature(record, anchor_key, authorization_payload(metadata, seal))
    return VerifiedAuthorization(
        record=record,
        authorization_sha256=hashlib.sha256(raw).hexdigest(),
        operator_key_identity=operator_key_identity(anchor_key.hex()),
    )


def grant_launch(
    directory: Path,
    metadata: dict,
    seal: str,
    *,
    operator_public_key_hex: str | None = None,
) -> LaunchGrant:
    """Mint the single-use launch grant for this candidate, pre-claim only.

    A candidate whose claim already exists can never mint a grant again:
    there is exactly one ceremony, one claim and one launch.
    """
    if (directory / "CLAIM.json").exists():
        raise ClearingAuthorizationError("one native attempt already consumed")
    verified = verify_authorization(
        directory, metadata, seal, operator_public_key_hex=operator_public_key_hex
    )
    return LaunchGrant(
        directory=Path(directory).resolve(),
        prelaunch_sha256=seal,
        authorization_sha256=verified.authorization_sha256,
        operator_key_identity=verified.operator_key_identity,
        record=verified.record,
    )


def reverify_launch_grant(directory: Path, grant: LaunchGrant, metadata: dict, seal: str) -> None:
    """Re-verify the exact bytes the grant was minted from.

    The record bytes on disk must still digest to the grant's pinned digest
    (a replaced record refuses, nothing is silently substituted), the record
    itself must still be the same object, and the signature must still check
    against the anchored key the grant carries. The anchor's own identity is
    re-derived from the currently pinned key so a rotated or swapped anchor
    can never silently re-authorize a grant.
    """
    anchor_key = _anchor_key(None)
    if operator_key_identity(anchor_key.hex()) != grant.operator_key_identity:
        raise ClearingAuthorizationError(
            "operator key identity changed since the authorization was verified"
        )
    raw, record = _read_record(directory)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != grant.authorization_sha256:
        raise ClearingAuthorizationError("operator authorization bytes changed after verification")
    if record != grant.record:
        raise ClearingAuthorizationError("operator authorization record changed after verification")
    _check_record_signature(record, anchor_key, authorization_payload(metadata, seal))
