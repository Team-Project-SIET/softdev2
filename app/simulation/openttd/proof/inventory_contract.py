"""Frozen multi-page proof policy and deterministic runtime request generation."""

import hashlib
import json

from app.simulation.openttd.industry_inventory import (
    IndustryInventoryBudget,
    IndustryInventoryObservation,
    inventory_request_id,
)
from app.simulation.openttd.industry_page import IndustryPageRequest

INVENTORY_SESSION_ID = "openttd15-industry-inventory-001"
INVENTORY_PAGE_SIZE = 2
INVENTORY_MODEL = "industry-inventory-correlated-pages-v1"
INVENTORY_PRELAUNCH_DIRECTORY = "openttd-15.3-industry-inventory-real-prelaunch"
INVENTORY_ATTEMPT_DIRECTORY = "openttd-15.3-industry-inventory-real-attempt1"
INVENTORY_BRIDGE_DIGEST = "2151a6a4b9669c3e9a0fef595c758f6f8aeae20a21a26c6f808ab23fcefdccfc"


def inventory_request(page: int, after_id: int | None) -> IndustryPageRequest:
    return IndustryPageRequest(
        inventory_request_id(INVENTORY_SESSION_ID, page), after_id, INVENTORY_PAGE_SIZE
    )


INVENTORY_FIRST_REQUEST = inventory_request(1, None)


def inventory_contract() -> dict:
    return {
        "session_id": INVENTORY_SESSION_ID,
        "proof_model": INVENTORY_MODEL,
        "page_size": INVENTORY_PAGE_SIZE,
        "minimum_pages": 2,
        "budget": {
            "max_pages": 32,
            "max_records": 32,
            "max_response_bytes": 16384,
            "max_operations": 256,
        },
        "authorization": {
            "launches": 1,
            "connections": 1,
            "industry_page_requests": 32,
            "automatic_retries": 0,
            "manual_retries": 0,
            "reconnects": 0,
            "additional_command_types": 0,
        },
        "request_generation": (
            "inventory_request_id(session_id, page): session_id + "
            "'-p' + three-digit decimal page; IndustryPageRequest.to_bytes(); first "
            "after_id=null; continuation=prior next_after_id; stop at first "
            "has_more=false"
        ),
        "protocol": 1,
        "request_type": "industry_page",
        "response_type": "industry_page_result",
        "status": "ok",
        "generic_default_page_size": 3,
        "protocol_max_limit": 5,
        "application_limit": 512,
        "native_ceiling": 1450,
        "bridge_digest": INVENTORY_BRIDGE_DIGEST,
        "world": {
            "seed": 42,
            "map_x": 6,
            "map_y": 6,
            "landscape": "temperate",
            "starting_year": 1950,
            "land_generator": 1,
            "max_no_competitors": 0,
        },
        "world_support": (
            "Successful single-page Attempt #2 returned IDs 0,1,2 under "
            "this same generation configuration. Expected continuation with limit 2; "
            "actual runtime success still required."
        ),
        "success_policy": (
            "minimum two validated pages; first has_more=true; strict "
            "advancing cursor chain; final has_more=false and next_after_id=null; "
            "complete observation; canonical digest; liveness each page; clean "
            "shutdown/integrity"
        ),
        "one_page_policy": (
            "MULTI-PAGE CONDITION NOT ESTABLISHED; retain valid "
            "single-page observation, fail proof; no relaunch/page-size change"
        ),
        "independent_industry_inventory": None,
        "independent_map_bounds": "encrypted SERVER_WELCOME dimensions only",
        "consistency": (
            "best-effort stable world; no gameplay mutation; no snapshot "
            "consistency under industry creation/removal"
        ),
        "failure_policy": (
            "Prelaunch: retain zero-activity failure, stop, no retry. "
            "Post-launch: retain completed/partial page evidence with incomplete session;"
            " no resend/reconnect/relaunch/source repair; clean shutdown/reap; remove "
            "credential. Later execution requires fresh explicit authorization."
        ),
        "cost": (
            "each page enumerates GSIndustryList, sorts and traverses; repeated "
            "list work across pages; bounded reads; no full-map scan or bulk response"
        ),
    }


def inventory_contract_bytes() -> bytes:
    return json.dumps(inventory_contract(), sort_keys=True, separators=(",", ":")).encode("ascii")


def inventory_contract_digest() -> str:
    return hashlib.sha256(inventory_contract_bytes()).hexdigest()


def verify_inventory(observation: IndustryInventoryObservation) -> dict:
    """Observation construction already requires complete per-page/native validation."""
    budget = IndustryInventoryBudget()
    if observation.session_id != INVENTORY_SESSION_ID or observation.budget != budget:
        raise ValueError("Frozen inventory session/budget mismatch")
    if any(
        p.request != inventory_request(i, p.request.after_id)
        for i, p in enumerate(observation.pages, 1)
    ):
        raise ValueError("Frozen inventory request generation mismatch")
    multi_page = observation.page_count >= 2 and observation.pages[0].exchange.response.has_more
    return {
        "verified": multi_page,
        "status": "PASS" if multi_page else "MULTI-PAGE CONDITION NOT ESTABLISHED",
        "complete": observation.complete,
        "page_count": observation.page_count,
        "record_count": len(observation.records),
        "inventory_sha256": observation.inventory_digest,
        "independent_industry_inventory": None,
        "map_width": observation.world.map_width,
        "map_height": observation.world.map_height,
    }
