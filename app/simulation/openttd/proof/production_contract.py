"""Single native binding proof; raw V1 metrics never qualify planner history."""

import hashlib
import json
from types import MappingProxyType

from app.simulation.openttd.industry_production import (
    PRODUCTION_NETWORK_SEQUENCE,
    IndustryProductionRecord,
    IndustryProductionRequest,
    IndustryProductionResponse,
)
from app.simulation.openttd.industry_production_evidence import PRODUCTION_GS_SEQUENCE

PRODUCTION_REQUEST = IndustryProductionRequest("openttd15-industry-production-001", 0, 1)
PRODUCTION_MODEL = "industry-production-correlated-channels-v1"
PRODUCTION_REVISION = 3
PRODUCTION_ATTEMPT = 2
PRODUCTION_PRELAUNCH_DIRECTORY = "openttd-15.3-industry-production-real-prelaunch-v3"
PRODUCTION_ATTEMPT_DIRECTORY = "openttd-15.3-industry-production-real-attempt2"
MAX_QUERY_OPERATIONS = 4
MAX_TOTAL_POST_AUTH_FRAMES = 2 + 3 + MAX_QUERY_OPERATIONS + 1
FRAME_LIMITS = MappingProxyType({"establishment": 2, "setup": 3, "production": 4, "cleanup": 1})


def production_contract():
    worst = IndustryProductionResponse(
        "x" * 64,
        IndustryProductionRecord(63999, 63, 2147483647, 2147483647, 65535, 65535, 100),
    ).to_bytes()
    if len(worst) != 335:
        raise ValueError("Audited V1 worst-case changed; controlled design decision required")
    return dict(
        proof_kind="industry-production",
        request_id=PRODUCTION_REQUEST.request_id,
        request_type="industry_production",
        response_type="industry_production_result",
        fields=[
            "protocol",
            "type",
            "request_id",
            "status",
            *IndustryProductionRecord.__dataclass_fields__,
        ],
        application_limit=512,
        native_ceiling=1450,
        worst_case_response_bytes=len(worst),
        application_headroom=177,
        native_headroom=1115,
        max_application_requests=1,
        launches=1,
        connections=1,
        retries=0,
        reconnects=0,
        additional_command_types=0,
        max_query_operations=MAX_QUERY_OPERATIONS,
        max_total_post_auth_frames=MAX_TOTAL_POST_AUTH_FRAMES,
        frame_limits=dict(FRAME_LIMITS),
        frame_budget_derivation=dict(
            encrypted_protocol_and_welcome=2,
            setup_update_frequency_ping_pong=3,
            query_send_response_ping_pong=4,
            graceful_quit=1,
        ),
        internal_chain=list(PRODUCTION_GS_SEQUENCE),
        network_chain=list(PRODUCTION_NETWORK_SEQUENCE),
        production_level="DEFERRED / NOT INCLUDED",
        transported="OpenTTD station-allocation metric",
        raw_production="native last-month counter; zero and seeded nonzero both valid",
        percentage="native quantized/clamped integer; no synthesized quotient",
        economy_bracket="before/after economy-date readings; not qualified history",
        qualified_for_planning=False,
        independent_production_source=None,
        complete_coverage=False,
        qualified_real_production_history="NOT YET PROVEN",
        same_run_structural_provenance="NOT PROVEN BY THIS SLICE",
        p08_completion=False,
        rollover_waiting=False,
    )


def production_contract_digest():
    return hashlib.sha256(
        json.dumps(production_contract(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
