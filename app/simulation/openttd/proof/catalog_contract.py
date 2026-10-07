"""Frozen complete cargo catalog proof, separate from single-page proof."""

import hashlib
import json

from app.simulation.openttd.cargo_catalog import CargoCatalogBudget, catalog_request_id
from app.simulation.openttd.cargo_page import CargoPageRequest

from .cargo_page_contract import PAGE_BRIDGE_DIGEST

CATALOG_SESSION_ID = "openttd15-cargo-catalog-001"
CATALOG_PAGE_SIZE = 2
CATALOG_REVISION = 1
CATALOG_MODEL = "cargo-catalog-correlated-channels-v1"
CATALOG_ATTEMPT_DIRECTORY = "openttd-15.3-cargo-catalog-real-attempt1"
CATALOG_PRELAUNCH_DIRECTORY = "openttd-15.3-cargo-catalog-real-prelaunch"
CATALOG_BUDGET = CargoCatalogBudget(32, 64, 16384, 512)


def catalog_request(number, after_id):
    if type(number) is not int or not 1 <= number <= 32:
        raise ValueError("Catalog request budget exhausted")
    return CargoPageRequest(catalog_request_id(CATALOG_SESSION_ID, number), after_id, 2)


CATALOG_FIRST_REQUEST = catalog_request(1, None)


def catalog_contract():
    return dict(
        proof_kind="cargo-catalog",
        session_id=CATALOG_SESSION_ID,
        page_size=2,
        max_pages=32,
        max_requests=32,
        max_records=64,
        max_response_bytes=16384,
        max_admin_frames=512,
        max_frames_per_query=16,
        frame_authority=(
            "32 queries x 16 frames; recorder caps post-auth subscription/query/control "
            "frames at 512; authentication frames excluded"
        ),
        request_id_pattern=CATALOG_SESSION_ID + "-pNNN",
        minimum_first_page_records=1,
        bridge_digest=PAGE_BRIDGE_DIGEST,
        application_limit=512,
        proof_response_bound=307,
        proof_response_headroom=205,
        native_ceiling=1450,
        schema="existing cargo V1 including normalized class mask",
        independent_second_source_catalog=None,
        industry_capability_equivalence="NOT PROVEN BY THIS SLICE",
        production_history="NOT INCLUDED",
        p08_completion=False,
        launches=1,
        connections=1,
        retries=0,
        reconnects=0,
        other_command_types=0,
        stable_world="one stable runtime configuration; no invented snapshot identifier",
    )


def catalog_contract_digest():
    return hashlib.sha256(
        json.dumps(catalog_contract(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_catalog(observation):
    valid = observation.complete and bool(observation.pages[0].exchange.response.cargoes)
    return dict(
        verified=valid,
        complete=observation.complete,
        catalog_digest=observation.catalog_digest,
        page_count=observation.page_count,
        cargo_count=len(observation.records),
        independent_second_source_catalog=None,
        status="VERIFIED" if valid else "EMPTY_FIRST_NATIVE_PAGE",
    )
