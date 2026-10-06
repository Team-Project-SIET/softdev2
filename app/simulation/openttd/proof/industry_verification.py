"""Record invariants and independently observed map bounds, not industry inventory."""

from dataclasses import dataclass

from app.simulation.openttd.admin_protocol import ServerWelcome
from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_page import (
    IndustryPageReceipt,
    IndustryPageRequest,
    IndustryPageResponse,
)
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.world_info import validate_dimension


@dataclass(frozen=True)
class IndustryPageVerification:
    request_id: str
    request_digest: str
    response_digest: str
    requested_after_id: int | None
    requested_limit: int
    returned_count: int
    industry_ids: tuple[int, ...]
    next_after_id: int | None
    has_more: bool
    ordering_valid: bool
    cursor_valid: bool
    coordinates_valid: bool
    bounds_valid: bool
    payload_size_valid: bool
    count_valid: bool
    runtime_map_dimensions: tuple[int, int]
    runtime_identity: RuntimeIdentity
    bridge_identity: BridgePackage
    independent_map_bound_source: str = "encrypted SERVER_WELCOME"
    independent_industry_inventory: None = None

    @property
    def page_valid(self) -> bool:
        return all(
            (
                self.ordering_valid,
                self.cursor_valid,
                self.coordinates_valid,
                self.bounds_valid,
                self.payload_size_valid,
                self.count_valid,
            )
        )

    @property
    def verified(self) -> bool:
        # Frozen first-proof policy: empty protocol page remains valid, but no record proof.
        return self.page_valid and self.returned_count > 0

    @property
    def status(self) -> str:
        if not self.page_valid:
            return "PAGE_SEMANTIC_VALIDATION_FAILED"
        return "VERIFIED" if self.verified else "EMPTY_PAGE_RECORD_PROOF_NOT_ESTABLISHED"


def verify_industry_page(
    request: IndustryPageRequest,
    response_payload: bytes,
    receipt: IndustryPageReceipt,
    welcome: ServerWelcome,
    *,
    runtime: RuntimeIdentity,
    bridge: BridgePackage,
) -> IndustryPageVerification:
    if receipt != IndustryPageReceipt.correlate(request.to_bytes(), response_payload):
        raise ValueError("Industry transport receipt does not bind the retained transaction")
    if welcome.revision != runtime.version or runtime.version != "15.3" or not welcome.dedicated:
        raise ValueError("Independent runtime identity mismatch")
    width, height = validate_dimension(welcome.width), validate_dimension(welcome.height)
    result = IndustryPageResponse.parse(response_payload)
    ids = tuple(record.id for record in result.industries)
    cursor_valid = all(request.after_id is None or id > request.after_id for id in ids)
    # Response parser independently requires strictly ascending IDs and valid last-ID/null cursor.
    count_valid = len(ids) <= request.limit and (not result.has_more or len(ids) == request.limit)
    return IndustryPageVerification(
        request.request_id,
        receipt.request_payload_sha256,
        receipt.response_payload_sha256,
        request.after_id,
        request.limit,
        len(ids),
        ids,
        result.next_after_id,
        result.has_more,
        all(a < b for a, b in zip(ids, ids[1:])),
        cursor_valid,
        all(record.tile == record.y * width + record.x for record in result.industries),
        all(
            record.x < width and record.y < height and record.tile < width * height
            for record in result.industries
        ),
        0 < len(response_payload) <= 512 and len(response_payload) < 1450,
        count_valid,
        (width, height),
        runtime,
        bridge,
    )
