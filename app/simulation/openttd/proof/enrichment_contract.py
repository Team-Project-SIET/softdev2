"""Frozen same-run inventory/capability contract; no runtime activity."""

import hashlib
import json

from app.simulation.openttd.industry_enrichment import ENRICHMENT_SESSION_ID

from .cargo_contract import CARGO_BRIDGE_DIGEST
from .inventory_contract import INVENTORY_FIRST_REQUEST

ENRICHMENT_MODEL = "industry-capability-enrichment-correlated-channels-v1"
ENRICHMENT_PRELAUNCH_DIRECTORY = "openttd-15.3-industry-capability-enrichment-real-prelaunch-v4"
ENRICHMENT_REVISION = 4
ENRICHMENT_ATTEMPT_DIRECTORY = "openttd-15.3-industry-capability-enrichment-real-attempt1"
ENRICHMENT_FIRST_REQUEST = INVENTORY_FIRST_REQUEST


def enrichment_contract():
    return dict(
        historical_protection="historical-exact-paths-v1",
        attempt_policy="enrichment-attempt-lineage-v1",
        evidence_directory=ENRICHMENT_ATTEMPT_DIRECTORY,
        prelaunch_revision=ENRICHMENT_REVISION,
        session_id=ENRICHMENT_SESSION_ID,
        inventory_session_id="openttd15-industry-inventory-001",
        inventory_page_size=2,
        max_inventory_pages=32,
        max_industries=32,
        max_capability_requests=32,
        max_total_requests=64,
        max_response_bytes=32768,
        max_admin_frames=512,
        phase_response_bytes=16384,
        phase_admin_frames=256,
        bridge_digest=CARGO_BRIDGE_DIGEST,
        application_limit=512,
        native_ceiling=1450,
        capability_request_ids="<session_id>-i<five-digit actual industry ID>",
        commands=["industry_page", "industry_cargo"],
        ordering=(
            "complete same-run inventory first; capabilities exactly once in "
            "ascending observed ID order"
        ),
        empty_inventory="complete empty enrichment is valid; no capability requests",
        independent_inventory_source=None,
        independent_capability_source=None,
        production_history="NOT INCLUDED",
        p08_completion=False,
        world={"seed": 42, "map_x": 6, "map_y": 6},
        authorization={
            "launches": 1,
            "connections": 1,
            "max_requests": 64,
            "retries": 0,
            "reconnects": 0,
            "additional_launches": 0,
            "additional_commands": 0,
        },
        consistency=(
            "best effort over stable world; no snapshot epochs or concurrent-change guarantee"
        ),
        failure_policy=(
            "Prelaunch: zero activity, retain failure, stop. Post-launch: "
            "retain completed/partial transactions, accurate completeness, no "
            "resend/reconnect/relaunch/source repair; shutdown/reap, close "
            "endpoints, remove credential. Later native execution requires "
            "fresh authorization."
        ),
    )


def enrichment_contract_digest():
    return hashlib.sha256(
        json.dumps(enrichment_contract(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
