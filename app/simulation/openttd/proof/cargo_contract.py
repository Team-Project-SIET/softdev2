"""Frozen one-industry native capability proof; no runtime actions."""

import hashlib
import json

from app.simulation.openttd.industry_cargo import IndustryCargoRequest

CARGO_REQUEST = IndustryCargoRequest("openttd15-industry-cargo-001", 0)
CARGO_MODEL = "industry-cargo-correlated-channels-v1"
CARGO_BRIDGE_DIGEST = "63285895cf80be2b1f9b675c586525148117b3aa05c7ea1bea67a94bbfcecb2b"
CARGO_ATTEMPT_DIRECTORY = "openttd-15.3-industry-cargo-real-attempt1"
CARGO_PRELAUNCH_DIRECTORY = "openttd-15.3-industry-cargo-real-prelaunch"
CARGO_INTERNAL_CHAIN = (
    "BRIDGE_STARTED",
    "BRIDGE_REQUEST_RECEIVED",
    "INDUSTRY_CARGO_READ",
    "BRIDGE_RESPONSE_SENT",
    "BRIDGE_POST_RESPONSE_ALIVE",
)
CARGO_NETWORK_CHAIN = (
    "INDUSTRY_CARGO_REQUEST_SENT",
    "INDUSTRY_CARGO_RESPONSE_RECEIVED",
    "TRANSPORT_RECEIPT_CREATED",
    "CAPABILITY_VALIDATED",
)


def cargo_contract() -> dict:
    return {
        "protocol": 1,
        "request_id": CARGO_REQUEST.request_id,
        "request_type": "industry_cargo",
        "response_type": "industry_cargo_result",
        "status": "ok",
        "industry_id": 0,
        "bridge_digest": CARGO_BRIDGE_DIGEST,
        "application_limit": 512,
        "native_ceiling": 1450,
        "response_bound": 280,
        "apis": [
            "GSCargoList_IndustryProducing",
            "GSCargoList_IndustryAccepting",
            "GSList.Sort",
            "GSList.SORT_BY_ITEM",
            "GSList.SORT_ASCENDING",
            "GSIndustry.IsValidIndustry",
            "GSCargo.IsValidCargo",
        ],
        "cargo_ids": [0, 63],
        "maximum_produced": 16,
        "maximum_accepted": 16,
        "internal_chain": list(CARGO_INTERNAL_CHAIN),
        "network_chain": list(CARGO_NETWORK_CHAIN),
        "empty_capability_policy": "valid native query proof; no non-empty cargo expectation",
        "independent_second_source_capability": None,
        "semantics": (
            "structural produces/accepts; accepting list includes temporarily "
            "unaccepted cargo; no transient or production-history claim"
        ),
        "evidence_scalars": {
            "null": "null",
            "integer": "canonical base-10 integer",
            "optional_ids": "null or canonical base-10 integer",
            "native_debug_representations": False,
        },
        "digest_source": (
            "Python retained raw response SHA-256 correlated with canonical "
            "native metadata; no native digest API"
        ),
        "cross_channel": "semantic correlation only; no cross-process timestamp ordering",
        "success": {
            "launches": 1,
            "connections": 1,
            "requests": 1,
            "retries": 0,
            "reconnects": 0,
            "additional_launches": 0,
            "additional_requests": 0,
            "additional_command_types": 0,
            "mutations": 0,
            "post_response_alive": True,
            "clean_exit": True,
            "reaped": True,
            "endpoints_closed": True,
            "source_integrity": True,
        },
        "world": {"seed": 42, "map_x": 6, "map_y": 6, "landscape": 0},
        "cost": (
            "validate one industry; sort/read at most 16 produced and 16 "
            "accepted slots; no industry enumeration or tile scan"
        ),
        "failure_policy": (
            "Prelaunch: zero activity, retain failure, stop. Post-launch: "
            "retain partial evidence, no resend/reconnect/relaunch/source "
            "repair; shutdown/reap, close endpoints, remove credential. Later "
            "execution requires fresh explicit authorization."
        ),
    }


def cargo_contract_digest() -> str:
    return hashlib.sha256(
        json.dumps(cargo_contract(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
