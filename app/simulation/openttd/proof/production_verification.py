"""Immutable single-record semantic result, never complete production coverage."""

from dataclasses import dataclass

from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_production import (
    IndustryProductionReceipt,
    IndustryProductionRecord,
    IndustryProductionRequest,
    IndustryProductionResponse,
)
from app.simulation.openttd.runtime.identity import RuntimeIdentity


@dataclass(frozen=True)
class IndustryProductionVerification:
    request_id: str
    request_digest: str
    response_digest: str
    industry_id: int
    cargo_id: int
    record: IndustryProductionRecord
    economy_window_bracket: tuple[int, int]
    payload_size: int
    semantic_validation_result: str
    runtime_identity: RuntimeIdentity
    bridge_identity: BridgePackage
    verified: bool
    qualified_for_planning: bool = False
    complete_coverage: bool = False
    independent_production_source: None = None
    same_run_structural_provenance: str = "NOT PROVEN BY THIS SLICE"


def verify_industry_production(request, response_payload, receipt, *, runtime, bridge):
    if not isinstance(request, IndustryProductionRequest):
        raise ValueError("Typed production request required")
    expected = IndustryProductionReceipt.correlate(request.to_bytes(), response_payload)
    if receipt != expected or runtime.version != "15.3":
        raise ValueError("Production receipt/runtime mismatch")
    response = IndustryProductionResponse.parse(response_payload)
    if not 0 < len(response_payload) <= 335:
        raise ValueError("Audited production payload bound exceeded")
    record = response.record
    return IndustryProductionVerification(
        request.request_id,
        expected.request_payload_sha256,
        expected.response_payload_sha256,
        request.industry_id,
        request.cargo_id,
        record,
        (record.economy_date_before, record.economy_date_after),
        len(response_payload),
        "VALID_RAW_V1_RECORD",
        runtime,
        bridge,
        True,
    )
