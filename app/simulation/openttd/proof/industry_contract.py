"""Frozen one-query industry proof policy; no runtime actions."""

from app.simulation.openttd.industry_page import IndustryPageRequest

INDUSTRY_REQUEST = IndustryPageRequest("openttd15-industry-page-001", None, 3)
INDUSTRY_MODEL = "industry-page-correlated-channels-v2"
INDUSTRY_ATTEMPT = 2
INDUSTRY_REVISION = 2
INDUSTRY_ATTEMPT_DIRECTORY = "openttd-15.3-industry-page-real-attempt2"
INDUSTRY_PRELAUNCH_DIRECTORY = "openttd-15.3-industry-page-real-prelaunch-v2"
INDUSTRY_INTERNAL_CHAIN = (
    "BRIDGE_STARTED",
    "BRIDGE_REQUEST_RECEIVED",
    "INDUSTRY_PAGE_READ",
    "BRIDGE_RESPONSE_SENT",
    "BRIDGE_POST_RESPONSE_ALIVE",
)
INDUSTRY_NETWORK_CHAIN = (
    "INDUSTRY_PAGE_REQUEST_SENT",
    "INDUSTRY_PAGE_RESPONSE_RECEIVED",
    "TRANSPORT_RECEIPT_CREATED",
    "PAGE_VALIDATED",
)


def industry_contract() -> dict:
    return {
        "protocol": 1,
        "request_id": INDUSTRY_REQUEST.request_id,
        "request_type": "industry_page",
        "response_type": "industry_page_result",
        "status": "ok",
        "evidence_scalars": {
            "null": "null",
            "integer": "canonical base-10 integer",
            "boolean": "true or false",
            "optional_ids": "null or canonical base-10 integer",
            "request_id": "validated unescaped ASCII identifier",
            "native_debug_representations": False,
        },
        "after_id": None,
        "limit": 3,
        "protocol_max_limit": 5,
        "application_limit": 512,
        "native_ceiling": 1450,
        "proof_response_bound": 339,
        "internal_chain": list(INDUSTRY_INTERNAL_CHAIN),
        "network_chain": list(INDUSTRY_NETWORK_CHAIN),
        "cross_channel": "semantic correlation only; no cross-process timestamp ordering",
        "independent_map_bounds": "encrypted SERVER_WELCOME from the same secure Admin session",
        "independent_industry_inventory": None,
        "empty_page_policy": "valid transport/protocol; industry-record proof NOT_ESTABLISHED",
        "success": {
            "minimum_records": 1,
            "maximum_records": 3,
            "launches": 1,
            "connections": 1,
            "requests": 1,
            "retries": 0,
            "additional_launches": 0,
            "additional_requests": 0,
            "mutations": 0,
            "post_response_alive": True,
            "clean_exit": True,
            "reaped": True,
            "endpoints_closed": True,
            "source_integrity": True,
        },
        "world": {
            "seed": 42,
            "map_x": 6,
            "map_y": 6,
            "landscape": 0,
            "industries": "default deterministic generation; no industry creation commands",
        },
        "cost": "native Industry pool enumeration and ascending item iterator; O(industry count); "
        "at most three record reads plus validity-only lookahead; no tile scan",
        "digest_source": (
            "Python raw protocol response SHA-256 correlated with native read metadata; "
            "no native SHA-256 API or independent inventory is claimed"
        ),
        "failure_policy": "Prelaunch: zero activity, retain failure, stop. Post-launch: retain all "
        "evidence, no resend/relaunch/source repair, shutdown/reap, close endpoints, "
        "remove credentials. Any second attempt needs fresh explicit authorization.",
    }
