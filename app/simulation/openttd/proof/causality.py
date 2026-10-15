"""Two independently ordered channels, correlated by canonical transaction fields."""

import hashlib
import json
from dataclasses import asdict, dataclass

from app.simulation.openttd.gamescript_protocol import Ack, CommunicationReceipt, PingRequest

from .gamescript_evidence import GameScriptProofEvidence

NETWORK_SEQUENCE = ("REQUEST_SENT", "NETWORK_ACK_RECEIVED", "RECEIPT_CREATED")
PROOF_MODEL = "two-correlated-chains-v2"


@dataclass(frozen=True)
class NetworkPacketRecord:
    sequence: int
    direction: str
    packet_type: int
    packet_sha256: str


@dataclass(frozen=True)
class NetworkProofEvidence:
    request_payload: bytes
    response_payload: bytes | None
    receipt: CommunicationReceipt | None
    ordered_sequence: tuple[str, ...]
    requests_sent: int
    matching_acks: int
    retries: int
    packets: tuple[NetworkPacketRecord, ...]

    def public_evidence(self) -> dict:
        return {
            "channel": "Python/Admin",
            "proof_model": PROOF_MODEL,
            "request": json.loads(self.request_payload),
            "request_payload_sha256": hashlib.sha256(self.request_payload).hexdigest(),
            "response": None
            if self.response_payload is None
            else json.loads(self.response_payload),
            "response_payload_sha256": None
            if self.response_payload is None
            else hashlib.sha256(self.response_payload).hexdigest(),
            "receipt": None if self.receipt is None else asdict(self.receipt),
            "ordered_sequence": self.ordered_sequence,
            "requests_sent": self.requests_sent,
            "matching_acks": self.matching_acks,
            "retries": self.retries,
            "packets": [asdict(p) for p in self.packets],
        }

    def validate_chain(self) -> None:
        if self.ordered_sequence != NETWORK_SEQUENCE:
            raise ValueError("Incomplete or unordered Python/Admin evidence")
        if self.requests_sent != 1 or self.matching_acks != 1 or self.retries != 0:
            raise ValueError("Proof requires one request, one matching ACK and zero retries")
        if self.response_payload is None or self.receipt is None:
            raise ValueError("Network ACK and immutable receipt are independently required")
        if self.receipt != CommunicationReceipt.correlate(
            self.request_payload, self.response_payload
        ):
            raise ValueError("Receipt does not describe the retained network transaction")


@dataclass(frozen=True)
class TransactionCorrelation:
    protocol: int
    request_id: str
    request_type: str
    ack_type: str
    ack_status: str
    proof_model: str = PROOF_MODEL


def validate_proof(
    gamescript: GameScriptProofEvidence, network: NetworkProofEvidence
) -> TransactionCorrelation:
    """No cross-channel clock or global temporal sequence is an input."""
    gamescript.require_complete()
    network.validate_chain()
    request = PingRequest.parse(network.request_payload)
    assert network.response_payload is not None
    ack = Ack.parse(network.response_payload)
    # GS fields describe the verified frozen bridge path, not invented raw log fields.
    if (
        gamescript.protocol,
        gamescript.request_type,
        gamescript.ack_type,
        gamescript.ack_status,
    ) != (1, "ping", "ack", "ok"):
        raise ValueError("GameScript transaction semantics mismatch")
    if gamescript.request_id != request.request_id or request.request_id != ack.request_id:
        raise ValueError("Evidence channels describe different request IDs")
    return TransactionCorrelation(1, request.request_id, "ping", "ack", "ok")
