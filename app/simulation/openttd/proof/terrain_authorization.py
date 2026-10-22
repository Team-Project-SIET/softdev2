"""Bounded authorization contract only: no issuer, keys, signing, or execution."""

import json
import os
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

SCHEMA = "openttd-terrain-one-launch"
OPERATION = "openttd-15.3.tile_facts_page.single_page"


@dataclass(frozen=True)
class OneLaunchAuthorization:
    schema: str
    version: int
    authorization_id: str
    seal_sha256: str
    attempt_identity: str
    attempt_directory: str
    authorized_launch_count: int
    proof_operation: str
    issuer_id: str
    approval_evidence: str

    def __post_init__(self):
        if (
            self.schema != SCHEMA
            or type(self.version) is not int
            or self.version != 1
            or type(self.authorized_launch_count) is not int
            or self.authorized_launch_count != 1
            or self.proof_operation != OPERATION
        ):
            raise PermissionError("Unsupported one-launch authorization contract")
        for value in (self.authorization_id, self.attempt_identity, self.issuer_id):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
                raise PermissionError("Invalid authorization/issuer identity")
        if not isinstance(self.seal_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.seal_sha256
        ):
            raise PermissionError("Invalid exact-seal digest")
        if (
            not isinstance(self.attempt_directory, str)
            or len(self.attempt_directory) > 1024
            or not Path(self.attempt_directory).is_absolute()
            or str(Path(self.attempt_directory)) != self.attempt_directory
            or ".." in Path(self.attempt_directory).parts
        ):
            raise PermissionError("Invalid exact attempt destination")
        if (
            not isinstance(self.approval_evidence, str)
            or not self.approval_evidence
            or len(self.approval_evidence.encode()) > 4096
        ):
            raise PermissionError("Missing/oversized verifiable approval evidence")

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise PermissionError("Missing/unknown authorization fields")
        return cls(**value)

    def canonical_bytes(self):
        """Exact approval subject; external verifier must authenticate these bytes."""
        subject = asdict(self)
        del subject["approval_evidence"]
        return json.dumps(subject, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    def to_mapping(self):
        return asdict(self)


# Local development policy is separate from independent issuer authentication.

LOCAL_POLICY = "OPERATOR_ATTENDED_LOCAL_PROOF"
INDEPENDENT_POLICY = "INDEPENDENTLY_AUTHENTICATED_PROOF"
_LOCAL_GRANT = object()
_CONTROLLED_GRANT = object()


class FailureCode(StrEnum):
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    SEAL_INVALID = "SEAL_INVALID"
    OPERATOR_CONFIRMATION_DECLINED = "OPERATOR_CONFIRMATION_DECLINED"
    AUTHORIZATION_INVALID = "AUTHORIZATION_INVALID"
    ATTEMPT_ALREADY_CONSUMED = "ATTEMPT_ALREADY_CONSUMED"
    CLAIM_ACQUISITION_FAILED = "CLAIM_ACQUISITION_FAILED"
    SOURCE_INTEGRITY_FAILED = "SOURCE_INTEGRITY_FAILED"
    LAUNCH_FAILED = "LAUNCH_FAILED"
    POSTLAUNCH_PROOF_FAILED = "POSTLAUNCH_PROOF_FAILED"
    ACCEPTANCE_FAILED = "ACCEPTANCE_FAILED"
    CLEANUP_FAILED = "CLEANUP_FAILED"


class LocalProofFailure(PermissionError):
    def __init__(self, code: FailureCode, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class LocalTrust(StrEnum):
    LOCAL_OPERATOR_ATTESTED = "LOCAL_OPERATOR_ATTESTED"
    CONTROLLED_OPERATOR_ATTESTED = "CONTROLLED_OPERATOR_ATTESTED"


def process_start_identity():
    # Linux process start ticks, not merely a reusable PID.
    return Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]


@dataclass(frozen=True)
class LocalOperatorAuthorization:
    seal_sha256: str
    attempt_identity: str
    attempt_directory: str
    owner_pid: int
    owner_start: str
    owner_nonce: str
    trust: LocalTrust
    proof_operation: str = OPERATION
    authorization_mode: str = LOCAL_POLICY
    launch_allowance: int = 1
    _grant: object = field(default=None, repr=False, compare=False)

    def require_process(self, *, native: bool):
        allowed = (_LOCAL_GRANT,) if native else (_CONTROLLED_GRANT,)
        expected_trust = (
            LocalTrust.LOCAL_OPERATOR_ATTESTED
            if native
            else LocalTrust.CONTROLLED_OPERATOR_ATTESTED
        )
        if (
            all(self._grant is not grant for grant in allowed)
            or self.trust != expected_trust
            or self.owner_pid != os.getpid()
            or self.owner_start != process_start_identity()
            or self.authorization_mode != LOCAL_POLICY
            or self.proof_operation != OPERATION
            or type(self.launch_allowance) is not int
            or self.launch_allowance != 1
        ):
            raise LocalProofFailure(
                FailureCode.AUTHORIZATION_INVALID, "Missing/wrong attended in-process authorization"
            )

    def public_record(self):
        return {n: getattr(self, n) for n in self.__dataclass_fields__ if n != "_grant"}
