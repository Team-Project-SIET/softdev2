"""Combined proof bounds; one secure observer accounts for all five phases.

This contract alone does not authorize or provide a native execution path.
"""

import hashlib
import json
from types import MappingProxyType

from app.simulation.openttd.raw_production_session import (
    MAX_COMBINED_QUERY_OPERATIONS,
    MAX_COMBINED_REQUESTS,
    MAX_COMBINED_RESPONSE_BYTES,
    MAX_PRODUCTION_QUERY_OPERATIONS,
)

from .economy_authority import economy_clock_contract
from .production_contract import production_contract
from .structural_contract import StructuralFrameBudget, structural_contract

RAW_PRODUCTION_PRELAUNCH_DIRECTORY = "openttd-15.3-complete-raw-production-real-prelaunch"
RAW_PRODUCTION_ATTEMPT_DIRECTORY = "openttd-15.3-complete-raw-production-real-attempt1"
RAW_PRODUCTION_REVISION = 1
RAW_PRODUCTION_MODEL = "complete-raw-production-correlated-channels-v1"
RAW_PRODUCTION_SESSION_ID = "openttd15-complete-raw-production-001"
FRAME_LIMITS = MappingProxyType(
    {
        "establishment": 2,
        "setup": 3,
        "inventory": 256,
        "capability": 256,
        "catalog": 512,
        "production": MAX_PRODUCTION_QUERY_OPERATIONS,
        "cleanup": 1,
    }
)
MAX_TOTAL_POST_AUTH_FRAMES = sum(FRAME_LIMITS.values())
MAX_COMBINED_POST_AUTH_FRAMES = MAX_TOTAL_POST_AUTH_FRAMES


class RawProductionFrameBudget(StructuralFrameBudget):
    """Shared native observer with independent phase limits and no phase resets.

    Setup subscribes once before inventory. Completion PING/PONG traffic is
    already query traffic. GameScript liveness comes from the owned stderr log,
    not another Admin query. Phase transitions perform no native I/O.
    """

    limits = FRAME_LIMITS
    maximum_frames = MAX_TOTAL_POST_AUTH_FRAMES
    query_phases = ("inventory", "capability", "catalog", "production")

    def __init__(self):
        super().__init__()
        self._counts = dict.fromkeys(self.limits, 0)


def raw_production_contract() -> dict:
    structural = structural_contract()
    production = production_contract()
    if (
        structural["max_query_operations"] + MAX_PRODUCTION_QUERY_OPERATIONS
        != MAX_COMBINED_QUERY_OPERATIONS
        or MAX_TOTAL_POST_AUTH_FRAMES != MAX_COMBINED_QUERY_OPERATIONS + 6
    ):
        raise ValueError("Combined native accounting derivation changed")
    return dict(
        proof_kind="complete-raw-production",
        session_id=RAW_PRODUCTION_SESSION_ID,
        economy_clock=economy_clock_contract(),
        phase_order=["inventory", "capability", "catalog", "assembly", "production"],
        max_application_requests=MAX_COMBINED_REQUESTS,
        max_response_bytes=MAX_COMBINED_RESPONSE_BYTES,
        max_query_operations=MAX_COMBINED_QUERY_OPERATIONS,
        max_total_post_auth_frames=MAX_TOTAL_POST_AUTH_FRAMES,
        max_production_records=512,
        phase_limits={
            **structural["phase_limits"],
            "production": dict(
                requests=512,
                records=512,
                response_bytes=171520,
                query_operations=MAX_PRODUCTION_QUERY_OPERATIONS,
                per_query_operations=8,
            ),
        },
        frame_limits=dict(FRAME_LIMITS),
        frame_budget_derivation=dict(
            encrypted_protocol_and_welcome=2,
            subscription_update_frequency_ping_pong=3,
            structural_query_allowance=structural["max_query_operations"],
            production_query_allowance=MAX_PRODUCTION_QUERY_OPERATIONS,
            phase_transition_frames=0,
            file_liveness_frames=0,
            graceful_quit=1,
        ),
        production_response_fields=production["fields"],
        worst_case_production_response_bytes=production["worst_case_response_bytes"],
        application_limit=production["application_limit"],
        native_ceiling=production["native_ceiling"],
        target_source="same-run complete structural capability.produces",
        target_order=["industry_id", "cargo_id"],
        zero_targets_allowed=True,
        source_structural_digest_exact=True,
        continuous_connection=True,
        continuous_accounting=True,
        rollovers_observed=0,
        qualified_for_planning=False,
        production_level=production["production_level"],
        transported=production["transported"],
        non_atomic=True,
        pre_decision=True,
        launches=1,
        connections=1,
        retries=0,
        reconnects=0,
        resume=False,
        additional_command_types=0,
        independent_production_source=None,
        p08_completion=False,
    )


def raw_production_contract_digest() -> str:
    return hashlib.sha256(
        json.dumps(raw_production_contract(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def raw_production_first_request():
    from app.simulation.openttd.industry_inventory import inventory_request_id
    from app.simulation.openttd.industry_page import IndustryPageRequest

    return IndustryPageRequest(inventory_request_id(RAW_PRODUCTION_SESSION_ID + "-inv", 1), None, 2)
