"""Frozen single-page native binding proof, separate from complete catalog collection."""

import hashlib
import json

from app.simulation.openttd.cargo_page import CARGO_CLASS_NAMES, CargoPageRequest

PAGE_REQUEST = CargoPageRequest("openttd15-cargo-page-001", None, 2)
PAGE_MODEL = "cargo-page-correlated-channels-v1"
PAGE_REVISION = 2
PAGE_BRIDGE_DIGEST = "7b45783b37ed93a481a58a2d768b4c490c8fad35a55db459a82cb0ddeaa84981"
PAGE_ATTEMPT_DIRECTORY = "openttd-15.3-cargo-page-real-attempt1"
PAGE_PRELAUNCH_DIRECTORY = "openttd-15.3-cargo-page-real-prelaunch-v2"
PAGE_INTERNAL_CHAIN = (
    "BRIDGE_STARTED",
    "BRIDGE_REQUEST_RECEIVED",
    "CARGO_PAGE_READ",
    "BRIDGE_RESPONSE_SENT",
    "BRIDGE_POST_RESPONSE_ALIVE",
)
PAGE_NETWORK_CHAIN = (
    "CARGO_PAGE_REQUEST_SENT",
    "CARGO_PAGE_RESPONSE_RECEIVED",
    "TRANSPORT_RECEIPT_CREATED",
    "CARGO_PAGE_VALIDATED",
)


def page_contract():
    return dict(
        proof_kind="cargo-page",
        protocol=1,
        request_id=PAGE_REQUEST.request_id,
        request_type="cargo_page",
        response_type="cargo_page_result",
        status="ok",
        after_id=None,
        limit=2,
        bridge_digest=PAGE_BRIDGE_DIGEST,
        application_limit=512,
        native_ceiling=1450,
        generic_response_bound=493,
        response_bound=299,
        minimum_records=1,
        empty_policy=(
            "generic empty page valid; proof requires metadata read on at least one "
            "active cargo; identical generation profile and prior native "
            "valid cargo evidence frozen"
        ),
        label_encoding="four native bytes, uppercase eight-digit hex",
        class_mask_v1=list(CARGO_CLASS_NAMES),
        apis=[
            "GSCargoList",
            "GSCargo.IsValidCargo",
            "GSCargo.GetCargoLabel",
            "GSCargo.IsFreight",
            "GSCargo.GetTownEffect",
            "GSCargo.HasCargoClass",
            "GSList.Sort",
            "GSList.SORT_BY_ITEM",
            "GSList.SORT_ASCENDING",
        ],
        commands=["ping", "world_info", "industry_page", "industry_cargo", "cargo_page"],
        internal_chain=list(PAGE_INTERNAL_CHAIN),
        network_chain=list(PAGE_NETWORK_CHAIN),
        independent_second_source_catalog=None,
        complete_catalog=False,
        production_history="NOT INCLUDED",
        p08_completion=False,
        success=dict(
            launches=1,
            connections=1,
            requests=1,
            retries=0,
            reconnects=0,
            additional_requests=0,
            additional_launches=0,
            mutations=0,
            clean_exit=True,
            reaped=True,
            endpoints_closed=True,
            source_integrity=True,
        ),
        failure_policy=(
            "PRELAUNCH 0/0/0 retained; runtime failure no resend/reconnect/relaunch; "
            "newer frozen lineage and fresh explicit authorization required"
        ),
        world=dict(seed=42, map_x=6, map_y=6, landscape=0),
        cross_channel="correlation and local partial order only",
    )


def page_contract_digest():
    return hashlib.sha256(
        json.dumps(page_contract(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
