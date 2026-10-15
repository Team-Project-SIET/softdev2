"""Single observed page verification; never a complete catalog or second-source claim."""

from dataclasses import dataclass

from app.simulation.openttd.cargo_page import CargoPageReceipt, CargoPageRequest, CargoPageResponse
from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.runtime.identity import RuntimeIdentity

from .cargo_page_contract import PAGE_REQUEST


@dataclass(frozen=True)
class CargoPageVerification:
    request_id: str
    request_digest: str
    response_digest: str
    after_id: int | None
    limit: int
    returned_count: int
    ordered_cargo_ids: tuple[int, ...]
    payload_size: int
    ordering_valid: bool
    uniqueness_valid: bool
    metadata_valid: bool
    cursor_valid: bool
    payload_size_valid: bool
    active_metadata_observed: bool
    runtime_identity: RuntimeIdentity
    bridge_identity: BridgePackage
    independent_second_source_catalog: None = None

    @property
    def verified(self):
        return all(
            (
                self.ordering_valid,
                self.uniqueness_valid,
                self.metadata_valid,
                self.cursor_valid,
                self.payload_size_valid,
                self.active_metadata_observed,
            )
        )

    @property
    def status(self):
        return "VERIFIED" if self.verified else "CARGO_PAGE_SEMANTIC_VALIDATION_FAILED"


def verify_cargo_page(
    request: CargoPageRequest,
    response_payload: bytes,
    receipt: CargoPageReceipt,
    *,
    runtime: RuntimeIdentity,
    bridge: BridgePackage,
) -> CargoPageVerification:
    if request != PAGE_REQUEST or runtime.version != "15.3":
        raise ValueError("Frozen cargo-page request/runtime required")
    if receipt != CargoPageReceipt.correlate(request.to_bytes(), response_payload):
        raise ValueError("Cargo page receipt does not bind retained bytes")
    response = CargoPageResponse.parse(response_payload)
    response.validate_page(request)
    ids = tuple(r.cargo_id for r in response.cargoes)
    return CargoPageVerification(
        request.request_id,
        receipt.request_payload_sha256,
        receipt.response_payload_sha256,
        request.after_id,
        request.limit,
        len(ids),
        ids,
        len(response_payload),
        all(a < b for a, b in zip(ids, ids[1:])),
        len(ids) == len(set(ids)),
        True,
        True,
        0 < len(response_payload) <= 512 and len(response_payload) < 1450,
        bool(ids),
        runtime,
        bridge,
    )
