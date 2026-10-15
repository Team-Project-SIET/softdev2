"""Native capability record invariants; no independent second-source claim."""

from dataclasses import dataclass

from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_cargo import (
    IndustryCargoReceipt,
    IndustryCargoRequest,
    IndustryCargoResponse,
)
from app.simulation.openttd.runtime.identity import RuntimeIdentity


@dataclass(frozen=True)
class IndustryCargoVerification:
    request_id: str
    request_digest: str
    response_digest: str
    industry_id: int
    produced_ids: tuple[int, ...]
    accepted_ids: tuple[int, ...]
    produced_count: int
    accepted_count: int
    ordering_valid: bool
    uniqueness_valid: bool
    cargo_ids_valid: bool
    payload_size_valid: bool
    runtime_identity: RuntimeIdentity
    bridge_identity: BridgePackage
    independent_second_source_capability: None = None

    @property
    def verified(self) -> bool:
        return all(
            (
                self.ordering_valid,
                self.uniqueness_valid,
                self.cargo_ids_valid,
                self.payload_size_valid,
            )
        )

    @property
    def status(self) -> str:
        return "VERIFIED" if self.verified else "CAPABILITY_SEMANTIC_VALIDATION_FAILED"


def verify_industry_cargo(
    request: IndustryCargoRequest,
    response_payload: bytes,
    receipt: IndustryCargoReceipt,
    *,
    runtime: RuntimeIdentity,
    bridge: BridgePackage,
) -> IndustryCargoVerification:
    if receipt != IndustryCargoReceipt.correlate(request.to_bytes(), response_payload):
        raise ValueError("Cargo transport receipt does not bind retained transaction")
    if runtime.version != "15.3":
        raise ValueError("OpenTTD 15.3 runtime required")
    cap = IndustryCargoResponse.parse(response_payload).capability
    sets = (cap.produces, cap.accepts)
    return IndustryCargoVerification(
        request.request_id,
        receipt.request_payload_sha256,
        receipt.response_payload_sha256,
        cap.industry_id,
        cap.produces,
        cap.accepts,
        len(cap.produces),
        len(cap.accepts),
        all(all(a < b for a, b in zip(ids, ids[1:])) for ids in sets),
        all(len(ids) == len(set(ids)) for ids in sets),
        all(len(ids) <= 16 and all(0 <= i <= 63 for i in ids) for ids in sets),
        0 < len(response_payload) <= 512 and len(response_payload) < 1450,
        runtime,
        bridge,
    )
